"""Heat-cascade screen of SMR sites during the transition (first operation 2042-2046).

Each site is the Coalition's named coal-plant site (19 June 2024) with two BWRX-300-class modules (Gladstone, not a
Coalition site, is a one-module test). Heat leaves each module in three temperature stages:
  stage 1  150-180 C extraction steam (<= 200 MWth per module; 0.19 MWh of electricity forgone per MWh, 0.24 for
           alumina digestion steam at 165-180 C, 0.30 for 240 C boehmite digestion at Gladstone): alumina digestion,
           ethanol distillation (E85/ED95), kelp refineries, a paper mill and a meat works;
  stage 2  70-80 C heat from a raised condenser pressure (<= 250 MWth per module; 0.09 MWh forgone per MWh):
           multi-effect distillation of seawater or saline mine water, or direct greenhouse heating at inland sites;
  stage 3  ~38 C MED reject heat: greenhouses and recirculating warm-water aquaculture (barramundi, prawns).
Electricity not forgone is sold at the regional value. Values in each year use the gas price, the carbon-price path
and the avoided-SWRO water cost; the fossil-free variant replaces power and heat values from 2045 with the national
model's shadow values (firm power AUD 96/MWh; heat from heat pumps). NPV at 4% real over 40 years of operation,
discounted to first operation; capital includes 4.4 years of construction interest.
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import copy
import json
from pathlib import Path

import inputs as I
import water as WT

OUT = Path(__file__).resolve().parent / "outputs"
PIPE_STEAM_M_KM, PIPE_HOT_M_KM = 4.4, 2.7      # AUD M per km (CAD 4.0 and 2.5 at 1.09)
GH_HA = I.WATER["greenhouse_mwh_ha"]

# users: (name, stage, MWh_th per year at full take, load factor, pipe km, extra)
USERS = {
    "Port Augusta": [
        ("Kelp refinery (Spencer Gulf kelp, 0.3 Mt dry/yr)", "steam", 0.46 * 0.3e6, 0.85, 2, {}),
        ("MED, 120 ML/day for Upper Spencer Gulf towns and mines", "med", 120e3 * 365 * 70 / 1000, 0.95, 3,
         {"ml_day": 120.0}),
        ("Greenhouses beside Sundrop Farms (80 ha)", "reject", 80 * GH_HA, 1.0, 2, {}),
        ("Barramundi and prawn RAS hub (4,000 t/yr)", "reject", 4000e3 * I.WATER["ras_kwh_kg"] / 1000, 1.0, 2, {}),
    ],
    "Muja": [
        ("Worsley alumina digestion steam (4.6 Mt/yr)", "alumina", 4.6e6 * 6.6 / 3.6, 0.92, 28, {}),
        ("Greenhouses, Collie (20 ha)", "lowgrade", 20 * GH_HA, 1.0, 3, {}),
    ],
    "Loy Yang": [
        ("Maryvale mill process steam", "steam", 1.5e6, 0.90, 30, {}),
        ("Kelp refinery (Bass Strait kelp, 0.3 Mt dry/yr)", "steam", 0.46 * 0.3e6, 0.85, 2, {}),
        ("Greenhouses, Latrobe Valley (40 ha)", "lowgrade", 40 * GH_HA, 1.0, 3, {}),
    ],
    "Liddell": [
        ("MED of saline mine water (20 ML/day)", "med", 20e3 * 365 * 70 / 1000, 0.95, 5, {"ml_day": 20.0, "brine": 0.5}),
        ("Greenhouses, Hunter (40 ha)", "reject", 40 * GH_HA, 1.0, 3, {}),
    ],
    "Mount Piper": [
        ("MED of saline mine water (10 ML/day)", "med", 10e3 * 365 * 70 / 1000, 0.95, 8, {"ml_day": 10.0, "brine": 0.5}),
        ("Greenhouses, Lithgow (20 ha)", "reject", 20 * GH_HA, 1.0, 3, {}),
    ],
    "Tarong": [
        ("Sorghum ethanol distillery, 200 ML/yr (E85, ED95)", "steam", 200e6 * 7.25 / 3600, 0.90, 2, {}),
        ("Greenhouses, South Burnett (20 ha)", "lowgrade", 20 * GH_HA, 1.0, 3, {}),
    ],
    "Callide": [
        ("Sorghum and cane ethanol distillery, 200 ML/yr", "steam", 200e6 * 7.25 / 3600, 0.90, 2, {}),
        ("Biloela meat works process steam", "steam", 0.05e6, 0.85, 5, {}),
        ("Greenhouses, Biloela (20 ha)", "lowgrade", 20 * GH_HA, 1.0, 3, {}),
    ],
    "Gladstone (test)": [
        ("QAL and Yarwun alumina digestion steam (boehmitic bauxite)", "alumina_hot", 7.1e6 * 7.0 / 3.6, 0.92, 15, {}),
        ("MED for the Gladstone industrial area (50 ML/day)", "med", 50e3 * 365 * 70 / 1000, 0.95, 8, {"ml_day": 50.0}),
    ],
}
FORGONE = {"steam": I.SMR["steam_forgone"], "alumina": I.SMR["steam_forgone_alumina"], "alumina_hot": 0.30,
           "lowgrade": I.SMR["lowgrade_forgone"], "med": I.SMR["lowgrade_forgone"], "reject": 0.0}


def central():
    return dict(r=0.04, life=40, module_bn=16018 * 0.3e6 / 1e9, site_bn=I.SMR["site_common_bn"],
                capacity=I.CAPACITY_VALUE_AUD_KW_YR, carbon_scale=1.0, fossil_free_from=None, idc_years=4.4,
                avail=I.SMR["avail"], fom=I.SMR["fom"], var=I.SMR["vom"] + I.SMR["fuel"] + I.SMR["waste"],
                power_ff=96.0, heat_ff=31.75)


def carbon(year, scale):
    ys = sorted(I.CARBON_AUD_T)
    if year >= ys[-1]:
        return I.CARBON_AUD_T[ys[-1]] * scale
    for a, b in zip(ys, ys[1:]):
        if a <= year <= b:
            return (I.CARBON_AUD_T[a] + (I.CARBON_AUD_T[b] - I.CARBON_AUD_T[a]) * (year - a) / (b - a)) * scale


def site_year(name, year, c):
    s = I.SITES[name]
    n = s.get("modules", 2)
    hours = 8760 * c["avail"]
    gross_el = n * I.SMR["mwe"] * hours                     # MWh_e if no heat were taken
    cap = {"steam": n * I.SMR["steam_max_mwth"] * hours, "low": n * I.SMR["lowgrade_max_mwth"] * hours}
    ff = c["fossil_free_from"] is not None and year >= c["fossil_free_from"]
    power = c["power_ff"] if ff else s["power"]
    co2 = carbon(year, c["carbon_scale"])
    gas_heat = s["gas"] * 3.6 / 0.85 + co2 * I.GAS_KG_CO2_GJ / 1000 * 3.6 / 0.85      # AUD per MWh_th of steam
    lowgas = s["gas"] * 3.6 / 0.90 + co2 * I.GAS_KG_CO2_GJ / 1000 * 3.6 / 0.90
    v_steam = (c.get("steam_ff") or c["heat_ff"] * 1.4) if ff else gas_heat        # high-temperature heat pumps/storage cost more
    v_low = c["heat_ff"] if ff else lowgas
    water_value = WT.swro(power, c["r"])["total"]
    med_other = (I.WATER["med_kwh_e_m3"] * power / 1000 + WT.capital_per_m3(I.WATER["med_capex_m3d"], c["r"])
                 + I.WATER["med_om_m3"] + I.WATER["intake_outfall_m3"])
    rows, forgone, rev_heat, used = [], 0.0, 0.0, {"steam": 0.0, "low": 0.0, "reject": 0.0}
    reject_avail = 0.0
    for (uname, stage, mwh, lf, km, ex) in USERS[name]:
        want = mwh * lf
        if stage in ("steam", "alumina", "alumina_hot"):
            take = min(want, cap["steam"] - used["steam"])
            used["steam"] += take
            val = take * v_steam
        elif stage in ("lowgrade", "med"):
            take = min(want, cap["low"] - used["low"])
            used["low"] += take
            if stage == "med":
                m3 = take / (I.WATER["med_kwh_th_m3"] / 1000)
                val = m3 * (water_value + ex.get("brine", 0.0) - med_other)
                reject_avail += take
            else:
                val = take * v_low
        else:   # reject heat from MED
            take = min(want, reject_avail - used["reject"])
            used["reject"] += take
            val = take * v_low
        forgone += take * FORGONE[stage]
        rev_heat += val
        rows.append(dict(user=uname, stage=stage, mwh_th=take, value_aud_m=val / 1e6, pipe_km=km))
    el = gross_el - forgone
    rev_el = el * power + c["capacity"] * n * I.SMR["mwe"] * 1e3
    opex = n * I.SMR["mwe"] * 1e3 * c["fom"] + gross_el * c["var"]
    med_m3 = sum(r_["mwh_th"] for r_ in rows if r_["stage"] == "med") / (I.WATER["med_kwh_th_m3"] / 1000)
    return dict(year=year, modules=n, el_twh=el / 1e6, steam_twh=used["steam"] / 1e6, low_twh=used["low"] / 1e6,
                reject_twh=used["reject"] / 1e6, water_ml_day=med_m3 / 365 / 1000, power_value=power,
                revenue_el_m=rev_el / 1e6, revenue_heat_water_m=rev_heat / 1e6, opex_m=opex / 1e6,
                net_m=(rev_el + rev_heat - opex) / 1e6, users=rows, co2_price=co2)


def capital_bn(name, c):
    n = I.SITES[name].get("modules", 2)
    pipes = sum(km * (PIPE_STEAM_M_KM if st in ("steam", "alumina", "alumina_hot") else PIPE_HOT_M_KM)
                for (_, st, _, _, km, _) in USERS[name]) / 1000
    over = n * c["module_bn"] + c["site_bn"] + pipes
    return over * (1 + c["r"]) ** (c["idc_years"] / 2), pipes


def npv(name, c=None):
    c = c or central()
    s = I.SITES[name]
    cap, pipes = capital_bn(name, c)
    pv = -cap
    for t in range(c["life"]):
        y = site_year(name, s["start"] + t, c)
        pv += y["net_m"] / 1000 / (1 + c["r"]) ** (t + 1)
    # avoided CO2 (Mt/yr) at start: gas displaced by heat + grid emissions displaced (0.35 t/MWh in the 2040s, falling)
    y0 = site_year(name, s["start"], c)
    return dict(npv_bn=pv, capital_bn=cap, pipes_bn=pipes, first_year=y0)


def breakeven_module(name, c=None):
    c = copy.deepcopy(c or central())
    lo, hi = 0.0, 10.0
    for _ in range(40):
        c["module_bn"] = (lo + hi) / 2
        if npv(name, c)["npv_bn"] > 0:
            lo = c["module_bn"]
        else:
            hi = c["module_bn"]
    return (lo + hi) / 2


VARIANTS = {
    "central": {},
    "no site infrastructure": {"site_bn": 0.0},
    "brownfield site AUD 0.9 bn": {"site_bn": 0.9},
    "modules AUD 3.0 bn, site 0.9 bn": {"module_bn": 3.0, "site_bn": 0.9},
    "modules AUD 2.0 bn, site 0.9 bn": {"module_bn": 2.0, "site_bn": 0.9},
    "capacity value AUD 60/kW-yr": {"capacity": 60.0},
    "no capacity value": {"capacity": 0.0},
    "75% of carbon value": {"carbon_scale": 0.75},
    "fossil-free grid from 2045": {"fossil_free_from": 2045},
    "7% finance": {"r": 0.07},
    "GenCost today (AUD 8.4 bn per module)": {"module_bn": I.SMR["capex_kw_today"] * 0.3e6 / 1e9},
}


def national_values():
    """Electricity and heat values from the national programme's shadow prices (central learning case)."""
    S = json.load(open(OUT / "central.json"))
    d = S["shadow_aud_mwh"]
    el = d["el_direct"]
    steam = max(v for k, v in d.items() if k.startswith("heat|"))
    return dict(power=el, steam=steam, low=el / 2.8 + 12.0)


def consistent_variants():
    """SMR sites valued throughout their lives at the national model's fossil-free shadow prices (no gas, no carbon
    price), with and without a capacity payment equal to the reserve-turbine cost the module would displace."""
    nv = national_values()
    turb = I.GENCOST_CAPEX["ocgt"][2050] * I.CRF(0.04, 30) + 15.0
    base = dict(fossil_free_from=0, power_ff=nv["power"], steam_ff=nv["steam"], heat_ff=nv["low"])
    return nv, {"consistent national pathway, no capacity payment": {**base, "capacity": 0.0},
                f"consistent national pathway, capacity AUD {turb:.0f}/kW-yr": {**base, "capacity": turb}}


def run():
    R = {"central_params": central(), "sites": {}, "variants": {}, "breakeven_module_bn": {},
         "breakeven_module_bn_brownfield": {}, "water": WT.cases()}
    for name in I.SITES:
        R["sites"][name] = npv(name)
        R["breakeven_module_bn"][name] = breakeven_module(name)
        bf = central()
        bf["site_bn"] = 0.9
        R["breakeven_module_bn_brownfield"][name] = breakeven_module(name, bf)
    for vname, ov in VARIANTS.items():
        c = central()
        c.update(ov)
        R["variants"][vname] = {name: npv(name, c)["npv_bn"] for name in I.SITES}
        R["variants"][vname]["fleet_coalition"] = sum(v for k, v in R["variants"][vname].items()
                                                      if I.SITES.get(k, {}).get("coalition"))
    nv, cv = consistent_variants()
    R["national_values"] = nv
    R["consistent"] = {}
    for vname, ov in cv.items():
        c = central()
        c.update(ov)
        R["variants"][vname] = {name: npv(name, c)["npv_bn"] for name in I.SITES}
        R["consistent"][vname] = {name: breakeven_module(name, c) for name in I.SITES}
    json.dump(R, open(OUT / "cascade.json", "w"), indent=1, default=float)
    return R


if __name__ == "__main__":
    R = run()
    for n, d in R["sites"].items():
        y = d["first_year"]
        print(f"{n:18s} NPV {d['npv_bn']:6.2f}  cap {d['capital_bn']:5.2f}  el {y['el_twh']:.2f} steam {y['steam_twh']:.2f} "
              f"low {y['low_twh']:.2f} rej {y['reject_twh']:.3f} water {y['water_ml_day']:.0f} ML/d  "
              f"net {y['net_m']:.0f} M  BE {R['breakeven_module_bn'][n]:.2f} / {R['breakeven_module_bn_brownfield'][n]:.2f}")
    for v, d in R["variants"].items():
        print(v, {k: round(x, 2) for k, x in d.items()})
