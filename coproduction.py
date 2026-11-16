"""Seafood and robotics that share the kelp farms and the heat-cascade hubs (screening accounts outside the LP).

Grid Harvesters (fleet and harvest energy), mussels and oysters inside kelp leases, utility drones (solar-charged
underwater drones for inspection and reseeding, two per km2), Tasmanian salmon and Spencer Gulf kingfish blocks with
utility robots (net inspection and cleaning, mortality removal, laser delousing for salmon), Queensland pond prawns
with seaweed bioremediation ponds, and southern recirculating (RAS) prawn and barramundi hubs warmed by heat-cascade
reject heat, by heat pumps or by gas. Feed prices come from feed.py (cross-species swap case). No food revenue is used
to lower the cost of transport energy. Canadian per-site parameters are converted at 1.09 AUD/CAD.
"""
import json
from pathlib import Path

import inputs as I
from grid_harvester import fleet_sizing, GRID_FAIRED_10_MJ, CONVENTIONAL_MJ, AREA_M2

OUT = Path(__file__).resolve().parent / "outputs"
FX = 1.09
P = {
    "grid_harvester": dict(unit_capex_aud_m=6.0 * FX),
    "shellfish": dict(km2_kelp_per_site=25.0, pass_share=0.8, mussel_t=48.0, oyster_t=24.0, sales=280800 * FX,
                      opex=247200 * FX, manual=21600 * FX, robot_var=4080 * FX, robot_fixed=57568 * FX,
                      lease_saving=60000 * FX),
    "drones": dict(per_km2=2.0, kwh_day=0.4, capex=12000 * FX, life=6, om=800 * FX, rate=0.06, bare=0.05, detect=0.85,
                   reseed_km2=250000 * FX),
    "salmon": dict(block_t=50000.0, prices=(10.0, 12.0, 14.0), fcr=1.30, pens_m=39.0, hatchery_m=41.0, robots=1544,
                   robot_m=27.5, other_m=185.0, freight_m=10.0, laser_capex=15000 * FX, laser_years=5, laser_om=1500 * FX,
                   n_released_t=690.0),
    "kingfish": dict(block_t=10000.0, prices=(14.0, 16.0, 18.0), fcr=1.60, fixed_m=62.0, robots=300, robot_m=5.4,
                     other_m=40.0),
    "prawn_pond": dict(price=17.0, fcr=1.60, other_kg=9.5, seaweed_kg=0.35, energy_kwh_kg=3.0),
    "prawn_ras": dict(price=22.0, fcr=1.50, capex_kg_yr=28.0, life=15, other_kg=12.0, pump_kwh_kg=6.0, heat_kwh_kg=8.0),
    "barra_ras": dict(price=13.0, fcr=1.45, capex_kg_yr=18.0, life=15, other_kg=6.5, pump_kwh_kg=4.0, heat_kwh_kg=6.0),
}


def grid_harvesters(C):
    f = fleet_sizing({z: a for z, a in C["kelp_km2"].items() if a > 0}, C["kelp_wet_mt"])
    cycles = f["area_pass_km2_per_year"] * 1e6 / AREA_M2
    return dict(units=f["engineering_units"], area_pass_km2=f["area_pass_km2_per_year"],
                energy_gwh=cycles * GRID_FAIRED_10_MJ / 3.6e6, conventional_gwh=cycles * CONVENTIONAL_MJ / 3.6e6,
                capex_bn=f["engineering_units"] * P["grid_harvester"]["unit_capex_aud_m"] / 1e3, fleet=f)


def shellfish(C):
    p = P["shellfish"]
    sites = C["kelp_total_km2"] / p["km2_kelp_per_site"] * p["pass_share"]
    manual = p["sales"] - p["opex"] - p["manual"]
    robot = p["sales"] - p["opex"] - p["robot_var"] - p["robot_fixed"]
    return dict(sites=sites, mussel_t=sites * p["mussel_t"], oyster_t=sites * p["oyster_t"],
                margins_aud_m={"Manual": sites * manual / 1e6, "ROV harvest": sites * robot / 1e6,
                               "ROV + shared kelp lease": sites * (robot + p["lease_saving"]) / 1e6,
                               "Manual + shared kelp lease": sites * (manual + p["lease_saving"]) / 1e6})


def drones(C):
    p = P["drones"]
    a = C["kelp_total_km2"]
    n = a * p["per_km2"]
    ann = n * (p["capex"] * I.CRF(p["rate"], p["life"]) + p["om"]) / 1e6
    return dict(drones=n, pv_gwh=n * p["kwh_day"] * 365 / 1e6, annual_aud_m=ann,
                share_of_farm_cost_pct=100 * ann / 1e3 / max(C["kelp_cost_bn"], 1e-9),
                reseed_km2=a * p["bare"] * p["detect"], reseed_aud_m=a * p["bare"] * p["detect"] * p["reseed_km2"] / 1e6)


def salmon(feed_aud_t, kelp_dry_mt):
    p = P["salmon"]
    laser = p["robots"] * (p["laser_capex"] * I.CRF(0.08, p["laser_years"]) + p["laser_om"]) / 1e6
    feed = p["block_t"] * p["fcr"] * feed_aud_t / 1e6
    cost = feed + p["pens_m"] + p["hatchery_m"] + p["robot_m"] + p["other_m"] + p["freight_m"] + laser
    rows = [dict(price=pr, net_aud_m=p["block_t"] * pr / 1e3 - cost) for pr in p["prices"]]
    return dict(cost_aud_m=cost, cost_aud_kg=cost / p["block_t"] * 1e3, feed_aud_m=feed, laser_aud_m=laser, rows=rows,
                n_share_of_kelp_need_pct=100 * p["n_released_t"] / max(kelp_dry_mt * 1e6 * 0.02, 1e-9))


def kingfish(feed_aud_t):
    p = P["kingfish"]
    cost = p["block_t"] * p["fcr"] * feed_aud_t / 1e6 + p["fixed_m"] + p["robot_m"] + p["other_m"]
    return dict(cost_aud_kg=cost / p["block_t"] * 1e3, rows=[dict(price=pr, net_aud_kg=pr - cost / p["block_t"] * 1e3)
                                                             for pr in p["prices"]])


def ras(kind, feed_aud_t, heat_aud_mwh, power=95.0, r=0.07):
    p = P[kind]
    cap = p["capex_kg_yr"] * I.CRF(r, p["life"])
    feed = p["fcr"] * feed_aud_t / 1000
    energy = p["pump_kwh_kg"] * power / 1000
    heat = p["heat_kwh_kg"] * heat_aud_mwh / 1000
    cost = cap + feed + energy + heat + p["other_kg"]
    return dict(cost_aud_kg=cost, margin_aud_kg=p["price"] - cost, heat_aud_kg=heat, feed_aud_kg=feed)


def pond_prawn(feed_aud_t, power=95.0):
    p = P["prawn_pond"]
    cost = p["fcr"] * feed_aud_t / 1000 + p["other_kg"] + p["seaweed_kg"] + p["energy_kwh_kg"] * power / 1000
    return dict(cost_aud_kg=cost, margin_aud_kg=p["price"] - cost)


def run():
    C = json.load(open(OUT / "central.json"))
    F = json.load(open(OUT / "feed.json"))["2050"]["cross-species swap"]["cost_by_species_aud_t"]
    W = json.load(open(OUT / "water.json")) if (OUT / "water.json").exists() else None
    heat = {"cascade reject heat": 0.0, "heat pump": 95.0 / 4 + 8.0,
            "gas boiler": 12.0 * 3.6 / 0.9 + 110 * I.GAS_KG_CO2_GJ / 1000 * 3.6 / 0.9}
    R = dict(params=P, grid_harvester=grid_harvesters(C), shellfish=shellfish(C), drones=drones(C),
             salmon=salmon(F["salmon"], C["kelp_dry_mt"]), kingfish=kingfish(F["kingfish"]),
             prawn_pond=pond_prawn(F["prawn"]),
             prawn_ras={k: ras("prawn_ras", F["prawn"], h) for k, h in heat.items()},
             barra_ras={k: ras("barra_ras", F["barramundi"], h) for k, h in heat.items()},
             heat_prices=heat, feed_aud_t=F)
    json.dump(R, open(OUT / "coproduction.json", "w"), indent=1, default=float)
    return R


if __name__ == "__main__":
    R = run()
    gh = R["grid_harvester"]
    print("GH units", round(gh["units"], 1), "energy", round(gh["energy_gwh"], 2), "conv", round(gh["conventional_gwh"], 2))
    print("shellfish", {k: (round(v, 2) if isinstance(v, float) else v) for k, v in R["shellfish"].items()})
    print("drones", {k: round(v, 2) for k, v in R["drones"].items()})
    print("salmon", R["salmon"])
    print("kingfish", R["kingfish"])
    print("pond prawn", R["prawn_pond"])
    print("prawn RAS", R["prawn_ras"])
    print("barra RAS", R["barra_ras"])
