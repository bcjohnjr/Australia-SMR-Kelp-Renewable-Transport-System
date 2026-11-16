"""One electricity portfolio, one cost, one emissions figure.

The annual programme chooses the transport system; the hourly model chooses the electricity supply for the loads the
annual programme sets. This script replaces the annual model's stylised electricity supply (wind and PV energy with
firming adders, electrolysers and hydrogen storage priced per MWh) by the hourly model's final installed fleet:

  reconciled cost = annual objective
                    - annual electricity supply cost (generation + firming/network adders)
                    - annual electrolyser and hydrogen-storage cost
                    + hourly final fleet: wind, PV, connections, batteries, turbines (ten-year requirement),
                      electrolysers, hydrogen store, new inter-regional links (annualised)
                    + turbine variable O&M and a methane store (turbine methane itself is produced in the annual model)
                    + distribution adder x direct load + flexible network adder x flexible load

The methane the turbines burn (ten-year mean of the one-hour verification / turbine efficiency) is a fixed demand in the
annual model's methane balance, so its supply (waste biomethane, kelp methane or synthetic methane), cost and emissions
are counted there; a store carries the worst year's draw above the mean. Emissions are recomputed with the hourly
fleet's wind and PV output (curtailed energy included, since panels and turbines are built whether or not their output
is used).
Output: outputs/reconciled.json.
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import copy
import json
from pathlib import Path

import numpy as np

import dispatch as D
import optimise as O

OUT = Path(__file__).resolve().parent / "outputs"


def fleet_cost(R, obs=None):
    obs = obs or D.observed()
    p = D.P(**{k: v for k, v in R["params"].items() if k in D.P()})
    fc = D.final_fleet(R)
    cap = D._cap_cost(fc, p, obs)
    ann = lambda capex, life: capex * D.crf(p["r"], life) * 1000
    links = sum(fc["links"].get(f"{a}-{b}", 0.0) * ann(c * 1000, p["link_life"]) for a, b, c in D.LINKS)
    return dict(capacity_bn=cap / 1e9, links_bn=links / 1e9, p=p, fc=fc)


def potential_generation(R, obs=None):
    """Mean annual wind and PV output of the final fleet over 2015-2024 (TWh, before curtailment)."""
    obs = obs or D.observed()
    fc = D.final_fleet(R)
    w = pv = 0.0
    for n in D.SYSTEMS:
        si = [i for i, g in enumerate(obs["names"]) if obs["sites"][g]["system"] == n]
        for j, s in enumerate(si):
            w += fc[n]["wind"][j] * float(np.mean(obs["wind"][s].astype(float)))
            pv += fc[n]["pv"][j] * float(np.mean(obs["pv"][s].astype(float)))
    return w * 8.766 / 1000, pv * 8.766 / 1000


FILL_LIFE = 30      # years over which the store's initial fill is annualised (cost and emissions)


def methane_inventory(use, production, cycles=2):
    """Turbine-methane store over the verification years, repeated `cycles` times in sequence. Conservative ordering:
    within each year all withdrawals come before any of that year's production counts towards the minimum, and all
    production before any withdrawal towards the maximum. Returns the smallest opening inventory that never runs
    out, the capacity needed, and the year-by-year table (TWh). Surplus production (rounding of the allocation)
    accumulates in the store."""
    ys = list(use)
    seq = ys * cycles
    cum, low = 0.0, 0.0
    for y in seq:                       # lowest point relative to the opening inventory
        low = min(low, cum - use[y])
        cum += production - use[y]
    opening = -low
    rows, s, cap = [], opening, opening
    for k, y in enumerate(seq):
        lo, hi = s - use[y], s + production
        cap = max(cap, hi)
        s = s + production - use[y]
        if k < len(ys):
            rows.append(dict(year=y, opening=lo + use[y], production=production, use=use[y], lowest=lo, highest=hi,
                             closing=s))
    return dict(opening_twh=opening, capacity_twh=cap, closing_twh=rows[-1]["closing"] if rows else opening,
                production_twh=production, use_mean_twh=sum(use.values()) / max(len(use), 1), years=rows,
                surplus_10yr_twh=production * len(ys) - sum(use.values()))


def reconcile(S=None, R=None, V=None):
    S = S or json.loads((OUT / "central.json").read_text())
    R = R or json.loads((OUT / "dispatch.json").read_text())
    vf = OUT / "verify_hourly.json"
    V = V or (json.loads(vf.read_text()) if vf.exists() else None)
    cal = O.calibration()
    obs = D.observed()
    f = fleet_cost(R, obs)
    p = f["p"]
    a = O.base_params()["adder"]
    d = R["design"]
    fuel_unit = p["methane_aud_mwh"] / p["turb_eff"] + p["turb_vom"]
    if V:
        turb_twh = float(np.mean([v["turbine_twh"] for v in V["years"].values()]))
        src = f"{V['step_h']}-hour verification of the final fleet"
    else:
        turb_twh = R["robust"]["turbine_twh_mean_10yr"]
        src = "three-hour yearly checks"
    # turbine methane is produced in the annual model (fixed demand in its methane balance, priced there); here turbine
    # variable O&M, the methane store and its initial fill, from a ten-year inventory of production and withdrawals
    ch4_need = turb_twh / p["turb_eff"]
    ch4_assigned = S.get("methane_balance_twh", {}).get("turbines", 0.0)
    years = V["years"] if V else {}
    inv = methane_inventory({y: v["turbine_twh"] / p["turb_eff"] for y, v in years.items()}, ch4_assigned)
    store_cost = O._base_params()["reserve"]["storage_cost"]
    ch4_price = S["shadow_aud_mwh"]["methane"]
    fill_bn = inv["opening_twh"] * 1e6 * ch4_price * D.crf(S["params_r"], FILL_LIFE) / 1e9
    store_bn = inv["capacity_twh"] * 1e6 * store_cost / 1e9
    vom_bn = turb_twh * 1e6 * p["turb_vom"] / 1e9
    fuel_bn = vom_bn + store_bn + fill_bn
    dist = cal.get("distribution_aud_mwh", a["net_dir"] - D_trans(R))
    net_bn = (max(dist, 0.0) * d["direct_twh"] + a["net_flex"] * d["flexible_twh"]) * 1e6 / 1e9
    hourly_el_bn = f["capacity_bn"] + f["links_bn"] + fuel_bn + net_bn
    annual_el_bn = S["electricity_supply_cost_bn"] + S["electrolyser_cost_bn"]
    total = S["objective_bn"] - annual_el_bn + hourly_el_bn
    w, pv = potential_generation(R, obs)
    # emissions with the hourly fleet
    S2 = copy.deepcopy(S)
    S2["generation_twh"] = dict(S["generation_twh"], wind=w, pv=pv)
    # turbine methane is already in the annual fuel supply; the store's initial fill is added, spread over FILL_LIFE
    S2["fuels_twh"]["waste_biomethane"] = S2["fuels_twh"].get("waste_biomethane", 0.0) + inv["opening_twh"] / FILL_LIFE
    em = O.residual_emissions(S2)
    em_lo = O.residual_emissions(S2, bound="lo")
    em_hi = O.residual_emissions(S2, bound="hi", ch4_leak=0.03)
    sysd = d["systems"]
    port = dict(
        wind_gw=sum(v["wind_gw"] for v in sysd.values()), pv_gw=sum(v["pv_gw"] for v in sysd.values()),
        battery_gw=sum(v["battery_gw"] for v in sysd.values()), battery_gwh=sum(v["battery_gwh"] for v in sysd.values()),
        turbine_gw=sum(f["fc"][n]["turb"] for n in D.SYSTEMS) / 1000, turbine_gw_3h=R["robust"]["turbine_gw"], electrolyser_gw=sum(v["electrolyser_gw"] for v in sysd.values()),
        h2_store_twh_el=sum(v["h2_store_gwh_el"] for v in sysd.values()) / 1000, links_gw=sum(d["links_gw"].values()),
        wind_twh_potential=w, pv_twh_potential=pv, wind_share_potential=w / (w + pv))
    annual_port = dict(wind_gw=S["wind_gw"], pv_gw=S["pv_gw"], wind_twh=S["generation_twh"]["wind"],
                       pv_twh=S["generation_twh"]["pv"], electrolyser_gw=S["electrolyser_gw"])
    return dict(
        objective_annual_bn=S["objective_bn"], annual_electricity_bn=annual_el_bn,
        annual_electricity_parts_bn=dict(supply=S["electricity_supply_cost_bn"], electrolysers_h2=S["electrolyser_cost_bn"]),
        hourly_electricity_bn=hourly_el_bn,
        hourly_parts_bn=dict(capacity=f["capacity_bn"], links=f["links_bn"], turbine_vom_and_methane_store=fuel_bn,
                             networks=net_bn),
        methane=dict(turbine_need_twh=ch4_need, assigned_in_annual_model_twh=ch4_assigned,
                     store_twh=inv["capacity_twh"], opening_twh=inv["opening_twh"], inventory=inv,
                     balance=S.get("methane_balance_twh", {}), shortfall_twh=max(ch4_need - ch4_assigned, 0.0),
                     cost_bn=dict(turbine_vom=vom_bn, store=store_bn, initial_fill=fill_bn),
                     methane_price_aud_mwh=ch4_price, fill_life_yr=FILL_LIFE),
        reconciled_cost_bn=total, difference_bn=total - S["objective_bn"],
        difference_pct=100 * (total / S["objective_bn"] - 1),
        turbine_twh_mean=turb_twh, turbine_source=src,
        portfolio_hourly=port, portfolio_annual=annual_port,
        residual_wtw_mt=em, residual_range_mt=dict(lo=em_lo, hi=em_hi),
        wtw_reduction_pct=100 * (1 - em / S["fossil_wtw_mt"]),
        residual_wtw_annual_mt=S["residual_wtw_mt"],
        rule="hourly final fleet replaces the annual model's electricity supply; transport choices from the annual model")


def D_trans(R):
    import calibrate
    return calibrate.transmission_per_mwh(R)


if __name__ == "__main__":
    r = reconcile()
    (OUT / "reconciled.json").write_text(json.dumps(r, indent=1, default=float))
    print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items() if not isinstance(v, dict)})
    print("hourly", {k: round(v, 2) for k, v in r["portfolio_hourly"].items()})
    print("annual", {k: round(v, 2) for k, v in r["portfolio_annual"].items()})
    print("parts", r["annual_electricity_parts_bn"], r["hourly_parts_bn"])
