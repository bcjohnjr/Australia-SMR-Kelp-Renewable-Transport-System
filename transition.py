"""Transition 2025-2050: fleet turnover drives electrification; renewable liquid fuels are built towards the 2050
central solution; cumulative well-to-wheel emissions against an electrification-only path in which every remaining
litre stays fossil. Logistic paths (midpoint year, steepness) are screening assumptions consistent with vehicle
lifetimes of 12-20 years; 2025 renewable liquids (about 0.3 GL of ethanol and biodiesel) are taken as zero."""
import json
import math

import inputs as I
import optimise as O

YEARS = list(range(2025, 2051))
EL_MID = {"ldv_petrol": 2035, "ldv_diesel": 2037, "hdv": 2039, "rail": 2040, "mining": 2038, "farm": 2041,
          "construction": 2040, "aviation": 2100, "shipping": 2100}
LIQ_MID, K = 2040, 0.30


def logistic(y, mid, k=K, y0=2025, y1=2050):
    f = lambda t: 1 / (1 + math.exp(-k * (t - mid)))
    return max(0.0, (f(y) - f(y0)) / (f(y1) - f(y0)))


def run():
    C = json.load(open(O.OUT / "central.json"))
    D = C["demand_twh"]
    el50 = {s: 0.0 for s in D}
    for key, t in C["end_use_twh"].items():
        s, o = key.split("|")
        if O.OPTIONS[s][o][0] == "el":
            el50[s] += t
    for c, t in C["ers_twh"].items():
        el50["hdv"] += t
    ren_liq50 = sum(t for k, t in C["end_use_twh"].items() if O.OPTIONS[k.split("|")[0]][k.split("|")[1]][0] != "el")
    rows, cum_c, cum_e = [], 0.0, 0.0
    g = C["generation_twh"]
    lca_el = sum(O.LCA[k]["core"] * g[k] for k in ("wind", "pv", "smr")) / max(C["generation_total_twh"], 1)
    fuel_parts = sum(v for k, v in C["residual_parts_mt"].items() if k not in ("wind", "pv", "smr"))
    lca_liq = fuel_parts / max(sum(C["fuels_twh"].values()), 1)       # mean energy-supply factor of renewable fuels
    for y in YEARS:
        el = {s: el50[s] * logistic(y, EL_MID[s]) for s in D}
        liquid_need = {s: D[s] - el[s] for s in D}
        ren = ren_liq50 * logistic(y, LIQ_MID)
        tot_need = sum(liquid_need.values())
        share_ren = min(1.0, ren / tot_need) if tot_need > 0 else 1.0
        fossil = {s: liquid_need[s] * (1 - share_ren) for s in D}
        e_fossil = sum(I.co2_t_per_mwh(s) * fossil[s] for s in D)
        e_el_only = sum(I.co2_t_per_mwh(s) * liquid_need[s] for s in D)
        e_ren = ren * lca_liq + sum(el.values()) * 0.35 * lca_el      # ~0.35 MWh of electricity per MWh of fossil fuel
        e_c = e_fossil + e_ren
        e_e = e_el_only + sum(el.values()) * 0.35 * lca_el
        cum_c += e_c
        cum_e += e_e
        rows.append(dict(year=y, electric_twh=sum(el.values()), liquid_fossil_twh=sum(fossil.values()),
                         liquid_renewable_twh=min(ren, tot_need), wtw_mt=e_c, wtw_el_only_mt=e_e,
                         imports_gl=sum(fossil[s] / I.KWH_PER_L[I.FUEL_OF[s] if I.FUEL_OF[s] != "fuel_oil" else "fuel_oil"]
                                        for s in D)))
    R = dict(rows=rows, cumulative_mt=cum_c, cumulative_el_only_mt=cum_e, avoided_vs_el_only_mt=cum_e - cum_c)
    json.dump(R, open(O.OUT / "transition.json", "w"), indent=1, default=float)
    return R


if __name__ == "__main__":
    R = run()
    for r in R["rows"][::5]:
        print({k: round(v, 1) for k, v in r.items()})
    print(round(R["cumulative_mt"]), round(R["cumulative_el_only_mt"]), round(R["avoided_vs_el_only_mt"]))
