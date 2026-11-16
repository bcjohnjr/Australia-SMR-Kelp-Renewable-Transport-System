"""National scenarios: central learning case, today's costs, learning levers, electric-or-biofuel, kelp yields and
forced kelp, highway corridors, and SMR fleets (continuous capital sweep, break-even capital and whole-module
enumeration with common site infrastructure)."""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import copy
import itertools
import json
import math

import inputs as I
import kelp as K
import optimise as O

OUT = O.OUT


def brief(S):
    return dict(cost_bn=S["objective_bn"], kelp_km2=S["kelp_total_km2"], kelp_dry_mt=S["kelp_dry_mt"],
                smr_gw=S["smr_gw_total"], smr_modules={f: d["modules"] for f, d in S["smr"].items()},
                wind_gw=S["wind_gw"], pv_gw=S["pv_gw"], generation_twh=S["generation_total_twh"],
                efuels_twh=S["fuels_twh"]["efuel_ft_solar"] + S["fuels_twh"]["efuel_ft_wind"] + S["fuels_twh"]["e_methanol"]
                + S["fuels_twh"]["e_ammonia"], ers_km=S["ers_km_electrified"], wtw_reduction_pct=S["wtw_reduction_pct"],
                dac_mt=S["co2_mt"]["dac"], electrolyser_gw=S["electrolyser_gw"], shortfall_twh=S["shortfall_total_twh"],
                liquid_biogenic_twh=sum(S["fuels_twh"][k] for k in ("kelp_hc", "straw_ft", "cane_htl", "forest_htl",
                                                                    "hefa", "canola_hvo", "alcohol_to_jet")))


def levers():
    """Cumulative steps from today's costs at 7% to the central learning case at 4%."""
    steps = []
    p = O.today_params()
    steps.append(("Today's costs, 7% finance", copy.deepcopy(p)))
    p["r"] = 0.04
    p["kelp"]["cost"].rate = 0.04
    steps.append(("Finance at 4% real", copy.deepcopy(p)))
    q = O.base_params()
    for k in ("wind", "pv", "electrolyser"):
        p[k] = copy.deepcopy(q[k])
    p["adder"] = copy.deepcopy(q["adder"])
    steps.append(("GenCost 2050 wind, solar, batteries and electrolysers", copy.deepcopy(p)))
    for k in ("eft", "emeoh", "enh3", "dac"):
        p[k] = copy.deepcopy(q[k])
    steps.append(("Electrofuel synthesis and air capture learning", copy.deepcopy(p)))
    c = p["kelp"]["cost"]
    c.base_aud_t, c.depth_cycle_capex_km2, c.exposure_learning = 370.0, 0.87e6, 0.6
    steps.append(("Cheaper kelp farming and structures", copy.deepcopy(p)))
    p["kelp"]["level"] = "learning"
    steps.append(("Kelp learning-target yields", copy.deepcopy(p)))
    c.refinery_aud_t = 230.0
    steps.append(("Kelp refinery learning (= central case)", copy.deepcopy(p)))
    rows = []
    for name, pp in steps:
        S = O.solve(pp)
        rows.append(dict(step=name, **brief(S)))
    return rows


def smr_breakeven(fleet, steam_only=False):
    """Module capital (AUD bn per 300 MWe) at which the continuous solution starts to build the fleet."""
    lo, hi = 0.2, 8.4
    for _ in range(30):
        mid = (lo + hi) / 2
        p = O.base_params()
        p["smr"]["capex_kw"] = mid * 1e9 / 300e3
        for f in p["smr"]["enabled"]:
            p["smr"]["enabled"][f] = f == fleet
        S = O.solve(p)
        if S["smr"][fleet]["gw"] > 0.03:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def whole_modules(module_bn=4.6, site_bn=I.SMR["site_common_bn"]):
    """Enumerate whole-module fleets; each new site of up to two modules carries the common infrastructure."""
    base = O.solve(O.base_params())["objective_bn"]
    rows = []
    for n_sa, n_wa, n_e in itertools.product((0, 1, 2), (0, 1, 2), (0, 1, 2, 4)):
        p = O.base_params()
        p["smr"]["capex_kw"] = module_bn * 1e9 / 300e3
        p["smr"]["fixed_gw"] = {"sa": 0.3 * n_sa, "wa": 0.3 * n_wa, "east": 0.3 * n_e}
        p["smr"]["max_gw"] = {"sa": 0.3 * n_sa, "wa": 0.3 * n_wa, "east": 0.3 * n_e}
        S = O.solve(p)
        sites = math.ceil(n_sa / 2) + math.ceil(n_wa / 2) + math.ceil(n_e / 2)
        site_ann = sites * site_bn * I.CRF(p["r"], p["smr"]["life"])
        cost = S["objective_bn"] + site_ann
        steam = sum(sum(d["steam_twh"].values()) for d in S["smr"].values())
        rows.append(dict(sa=n_sa, wa=n_wa, east=n_e, sites=sites, cost_bn=cost, saving_bn=base - cost, steam_twh=steam))
    rows.sort(key=lambda r: -r["saving_bn"])
    return dict(module_bn=module_bn, site_bn=site_bn, base_bn=base, rows=rows)


def capex_sweep():
    out = []
    base = O.solve(O.base_params())["objective_bn"]
    for mbn in (0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.6):
        p = O.base_params()
        p["smr"]["capex_kw"] = mbn * 1e9 / 300e3
        S = O.solve(p)
        out.append(dict(module_bn=mbn, saving_bn=base - S["objective_bn"], gw=S["smr_gw_total"],
                        steam_twh=sum(sum(d["steam_twh"].values()) for d in S["smr"].values()),
                        by_fleet={f: d["gw"] for f, d in S["smr"].items()}))
    return out


def run():
    R = {}
    C = O.solve(O.central_params())     # reported central case: loads as verified by the hourly model
    C0 = O.solve(O.base_params())       # same case with loads free: reference for scenario differences
    C["shadow_fixed_loads_aud_mwh"] = C["shadow_aud_mwh"]
    C["shadow_aud_mwh"] = C0["shadow_aud_mwh"]      # marginal prices from the unconstrained solve
    C["dual_note"] = (C.get("dual_note", "") + " Shadow prices are from the same case solved with electricity loads free; "
                      "the reported solution holds them at the hourly-verified values.").strip()
    json.dump(C, open(OUT / "central.json", "w"), indent=1, default=float)
    R["central"] = brief(C)
    import reconcile
    REC = reconcile.reconcile(S=C)
    json.dump(REC, open(OUT / "reconciled.json", "w"), indent=1, default=float)
    T = O.solve(O.today_params())
    json.dump(T, open(OUT / "today.json", "w"), indent=1, default=float)
    R["today"] = brief(T)
    p = O.base_params()
    p["eb_only"] = True
    EB = O.solve(p)
    json.dump(EB, open(OUT / "electric_or_biofuel.json", "w"), indent=1, default=float)
    R["electric_or_biofuel"] = brief(EB)
    R["levers"] = levers()
    # kelp yields
    R["kelp_yield"] = {}
    for lvl, sc in (("demonstrated", 1.0), ("design", 1.0), ("learning", 1.0), ("learning", 1.25), ("learning", 1.5)):
        p = O.base_params()
        p["kelp"]["level"], p["kelp"]["scale"] = lvl, sc
        R["kelp_yield"][f"{lvl} x{sc}"] = brief(O.solve(p))
    # forced kelp per zone (deployment cap or the zone area if smaller)
    R["kelp_forced"] = {}
    for z, zz in K.ZONES.items():
        a = min(K.DEPLOYMENT_CAP_KM2, zz.area_km2)
        if C["kelp_km2"].get(z, 0) >= a - 1:
            continue
        p = O.base_params()
        p["kelp"]["forced"] = {z: a}
        S = O.solve(p)
        R["kelp_forced"][z] = dict(area_km2=a, extra_bn=S["objective_bn"] - C0["objective_bn"], name=zz.name)
    # kelp physical and environmental sensitivities
    R["kelp_sens"] = {}
    for name, f in (("area cap 300 km2 per zone", lambda p: p["kelp"].update(area_cap_km2=300.0)),
                    ("area cap 100 km2 per zone", lambda p: p["kelp"].update(area_cap_km2=100.0)),
                    ("natural nitrogen halved", lambda p: setattr(p["kelp"]["cost"], "nat_n_scale", 0.5)),
                    ("no fish-farm nitrogen", lambda p: setattr(p["kelp"]["cost"], "imta_capture", 0.0)),
                    ("demonstrated yield (1.2 t/ha)", lambda p: p["kelp"].update(level="demonstrated")),
                    ("no kelp", lambda p: p["kelp"].update(enabled=False)),
                    ("hypothetical: ocean bounds without the deployment cap", lambda p: p["kelp"].update(area_cap_km2=None))):
        p = O.base_params()
        f(p)
        S = O.solve(p)
        R["kelp_sens"][name] = dict(**brief(S), extra_bn=S["objective_bn"] - C0["objective_bn"], n_kt=S["kelp_n_kt"])
    # firming and network costs (referee: test higher firming and network charges)
    R["firming_sens"] = {}
    for mult in (1.5, 2.0):
        p = O.base_params()
        for k in ("wind_dir", "pv_dir", "pv_shift", "net_dir", "net_flex"):
            p["adder"][k] *= mult
        S = O.solve(p)
        R["firming_sens"][f"firming and network adders x{mult}"] = dict(**brief(S), extra_bn=S["objective_bn"] - C0["objective_bn"],
                                                                        breakeven_brent=I.breakeven_brent(S["objective_bn"], C["fossil_cost_bn"]["avg2025"], C["fossil_cost_bn"]["oct2026"]))
    # life-cycle emissions sensitivities (post-processing of the central solution)
    R["lca_sens"] = dict(central=C["residual_wtw_mt"], lo=C["residual_range_mt"]["lo"], hi=C["residual_range_mt"]["hi"],
                         fossil_wtw=C["fossil_wtw_mt"],
                         iluc={m: O.residual_emissions(C, iluc_mult=m) for m in (0.0, 1.0, 2.0)},
                         ch4_leak={l: O.residual_emissions(C, ch4_leak=l) for l in (0.0, 0.01, 0.03, 0.05)},
                         parts=C["residual_parts_mt"], efuel_intensity=C["efuel_intensity"])
    R["lca_sens"]["reduction_pct"] = {k: 100 * (1 - R["lca_sens"][k] / C["fossil_wtw_mt"]) for k in ("central", "lo", "hi")}
    # fossil-price break-even
    f25, f26 = C["fossil_cost_bn"]["avg2025"], C["fossil_cost_bn"]["oct2026"]
    R["fossil_breakeven"] = dict(brent_usd=I.breakeven_brent(C["objective_bn"], f25, f26), cost_2025_bn=f25,
                                 cost_oct2026_bn=f26, system_bn=C["objective_bn"],
                                 today_brent_usd=I.breakeven_brent(T["objective_bn"], f25, f26),
                                 reconciled_bn=REC["reconciled_cost_bn"],
                                 reconciled_brent_usd=I.breakeven_brent(REC["reconciled_cost_bn"], f25, f26))
    # cost of supplying the turbines' methane inside the national fuel balance
    p = O.base_params()
    p["turbine_ch4_twh"] = 0.0
    R["no_turbine_methane"] = brief(O.solve(p))
    R["no_turbine_methane"]["extra_bn"] = C["objective_bn"] - R["no_turbine_methane"]["cost_bn"]
    # highways
    p = O.base_params()
    p["ers"]["enabled"] = False
    R["ers_none"] = brief(O.solve(p))
    p = O.base_params()
    p["ers"]["force"] = tuple(I.CORRIDORS)
    R["ers_all"] = brief(O.solve(p))
    R["ers_corridors"] = {c: dict(**row, chosen_twh=C["ers_twh"].get(c, 0.0), built=C["ers_built"].get(c, 0))
                          for c, row in O.ers_corridors(O.base_params()).items()}
    # SMRs
    R["smr_capex_sweep"] = capex_sweep()
    R["smr_breakeven_module_bn"] = {f: smr_breakeven(f) for f in O.FLEETS}
    R["smr_whole_modules"] = {f"{m}": whole_modules(m) for m in (4.6, 2.5)}
    R["smr_whole_modules_brownfield"] = whole_modules(2.5, 0.9)
    # demand sensitivity
    p = O.base_params()
    p["demand_mult"] = {"aviation": 0.8, "shipping": 0.9, "mining": 0.85}
    R["less_demand"] = brief(O.solve(p))
    json.dump(R, open(OUT / "scenarios.json", "w"), indent=1, default=float)
    return R


if __name__ == "__main__":
    R = run()
    print(json.dumps({k: R[k] for k in ("central", "today", "electric_or_biofuel", "ers_none", "ers_all", "less_demand",
                                        "smr_breakeven_module_bn")}, indent=1, default=float))
    for r in R["levers"]:
        print(round(r["cost_bn"], 2), r["kelp_km2"], r["step"])
    print(json.dumps(R["kelp_yield"], indent=0, default=float)[:2000])
    print(json.dumps(R["kelp_forced"], indent=0, default=float))
    print(R["smr_capex_sweep"])
    for k, w in list(R["smr_whole_modules"].items()) + [("brown", R["smr_whole_modules_brownfield"])]:
        print(k, w["rows"][:4])
