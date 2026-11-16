"""Calibrate the annual programme's electricity adders against the hourly model (2015-2024 weather).

Fixed-point procedure (about 30-60 minutes):
  1. annual central solution with uncalibrated adders -> electricity loads
  2. hourly model (dispatch.py): capacities over two design years (weakest and median resource year), then all ten
     years with capacities fixed -> marginal-price cost of electricity to direct and flexible loads
  3. annual adders adjusted so that the annual model charges the same: direct loads pay the hourly price plus the part
     of the network adder not represented hourly (distribution); flexible loads pay the hourly price plus electrolyser
     and hydrogen-storage cost at the hourly electrolyser utilisation
  4. annual central solution again with the calibrated adders, and a second hourly run on its loads (check)
It also solves the hourly model for the direct loads alone (no electrolysers), the like-for-like comparison with
CSIRO GenCost's 2050 system cost. Writes calibration.json and outputs/dispatch.json.
"""
import json
from pathlib import Path

import numpy as np
import os
import time

import dispatch as D
import optimise as O

OUT = O.OUT


def transmission_per_mwh(res):
    p = res["params"]
    r = p["r"]
    ann = (p["rez_aud_kw"] * D.crf(r, p["net_life"])) * 1000
    gw = sum(v["wind_gw"] + v["pv_gw"] for v in res["design"]["systems"].values())
    twh = res["design"]["direct_twh"] + res["design"]["flexible_twh"]
    conn = 0.0
    caps = res["capacities"]
    return ann * gw * 1000 / (twh * 1e6)


def annual_prices(S, p):
    sh = S["shadow_aud_mwh"]
    e = S["electricity_twh"]
    loss = 1 + p["adder"]["loss"]
    # flexible duals are per MWh of load including losses
    fs, fw = sh.get("el_flex_solar", 0.0), sh.get("el_flex_wind", 0.0)
    ws = S["el_flows_twh"]["pv_flex_solar_led"]
    ww = S["el_flows_twh"]["wind_flex"] + S["el_flows_twh"]["pv_flex_wind_led"]
    flex = (fs * ws + fw * ww) / max(ws + ww, 1e-9)
    el = p["electrolyser"]
    r = p["r"]
    elz = lambda cf: el["capex"] * (O.CRF(r, el["life"]) + el["om"]) / (cf * 8.76)
    elz_avg = (elz(el["cf_solar"]) * ws + elz(el["cf_wind"]) * ww) / max(ws + ww, 1e-9) + p.get("h2_storage_aud_mwh_el", 0)
    return dict(direct=sh["el_direct"], flex_electricity=flex, flex_with_electrolyser=flex + elz_avg, electrolyser=elz_avg)


def hourly_prices(res):
    d = res["design"]
    p = res["params"]
    r = p["r"]
    elz_gw = sum(v["electrolyser_gw"] for v in d["systems"].values())
    h2_gwh = sum(v["h2_store_gwh_el"] for v in d["systems"].values())
    elz_ann = elz_gw * 1000 * (p["elz_capex"] * D.crf(r, p["elz_life"]) + p["elz_om"] * p["elz_capex"]) * 1000
    h2_ann = h2_gwh * 1000 * p["h2_store_aud_kwh_h2"] * p["h2_eff"] * D.crf(r, p["h2_life"]) * 1000
    el_twh = sum(v["flexible_twh"] for v in d["systems"].values())
    efuel_twh = res["loads"]["efuels"] * (1 + p["loss_flex"])
    direct = res.get("robust", {}).get("direct_price_with_topup", d["price_direct_aud_mwh"])
    return dict(direct=direct, direct_design=d["price_direct_aud_mwh"], flex_electricity=d["price_flex_aud_mwh"],
                electrolyser=elz_ann / (efuel_twh * 1e6), h2_storage=h2_ann / (efuel_twh * 1e6),
                electrolyser_cf=efuel_twh * 1e6 / 8766 / max(elz_gw * 1000, 1),
                flex_with_electrolyser=d["price_flex_aud_mwh"] + (elz_ann + h2_ann) / (efuel_twh * 1e6))


def fit(target_direct, target_flex, elz_cf, h2_store, base, wind_share=None, turbine_ch4=0.0):
    """Scale the direct firming adders by m >= 0 (and lower the direct network adder only if m reaches 0), and shift
    the flexible network adder, so that the annual model charges the hourly targets."""
    keys = ("wind_dir", "pv_dir", "pv_shift")

    def solve_with(m, dn, df):
        cal = dict(adder={k: base["adder"][k] * m for k in keys}, electrolyser=dict(cf_solar=elz_cf, cf_wind=elz_cf),
                   h2_storage_aud_mwh_el=h2_store)
        cal["adder"]["net_dir"] = base["adder"]["net_dir"] + dn
        cal["adder"]["net_flex"] = max(0.0, base["adder"]["net_flex"] + df)
        p = O.base_params(calibrated=False)
        p["adder"].update(cal["adder"]); p["electrolyser"].update(cal["electrolyser"])
        p["h2_storage_aud_mwh_el"] = h2_store
        p["wind_share"] = wind_share
        p["turbine_ch4_twh"] = turbine_ch4
        S = O.solve(p)
        return S, p, cal, annual_prices(S, p)

    m, dn, df = 1.0, 0.0, 0.0
    hist = []
    for it in range(12):
        S, p, cal, a = solve_with(m, dn, df)
        ed, ef = target_direct - a["direct"], target_flex - a["flex_with_electrolyser"]
        hist.append(dict(m=m, dn=dn, df=df, direct=a["direct"], flex=a["flex_with_electrolyser"]))
        if abs(ed) < 0.5 and abs(ef) < 0.5:
            break
        base_firm = sum(base["adder"][k] for k in keys) / 3
        m_new = m + ed / max(base_firm, 1e-6)
        if m_new < 0:
            dn += ed + m * base_firm
            m_new = 0.0
        m = m_new
        df += ef
    delta = {k: cal["adder"][k] - base["adder"][k] for k in cal["adder"]}
    return dict(firming_multiplier=m, adder_delta=delta, annual_overrides=cal, annual_prices_after=a,
                iterations=it + 1, history=hist, objective_bn=S["objective_bn"], wind_share=wind_share)


FAST = dict(hours=720, check_years=[2019], design_years=[2019]) if os.environ.get("CAL_FAST") else {}


def wind_share_of(R):
    """Wind share of potential wind+PV generation in the hourly design (incl. curtailed energy)."""
    sysd = R["design"]["systems"]
    if all("wind_twh" in v for v in sysd.values()):
        w = sum(v["wind_twh"] for v in sysd.values()); pv = sum(v["pv_twh"] for v in sysd.values())
        return w / (w + pv)
    obs = D.observed()
    idx = np.isin(obs["years"], R["design_years"])
    w = pv = 0.0
    for n in D.SYSTEMS:
        si = [i for i, g in enumerate(obs["names"]) if obs["sites"][g]["system"] == n]
        cw, cp = R["capacities"][n]["wind"], R["capacities"][n]["pv"]
        for j, s_ in enumerate(si):
            w += cw[j] * obs["wind"][s_, idx].mean(); pv += cp[j] * obs["pv"][s_, idx].mean()
    return w / (w + pv)


def stage_iterate(max_it=4, start=None):
    """Annual model and hourly design iterated until the hourly prices, the wind share and the annual loads agree.
    The first hourly result may be reused (start: path of a dispatch json on the current calibration's loads)."""
    base = O.base_params(calibrated=False)
    S0 = O.solve(base)
    a0 = annual_prices(S0, base)
    cal0 = json.loads(O.CALIBRATION.read_text()) if O.CALIBRATION.exists() else {}
    hist = cal0.get("iteration_history", [])
    R = json.loads(Path(start).read_text()) if start else None
    prev = None
    for k in range(max_it):
        if R is None:
            S = O.solve(O.base_params())
            R = D.run(S=S, check=False, **FAST)
        h = hourly_prices(R)
        share = wind_share_of(R)
        loads = R["loads"]
        tr = transmission_per_mwh(R)
        dist = base["adder"]["net_dir"] - tr
        rec = dict(direct=h["direct_design"], flex=h["flex_electricity"], elz_cf=h["electrolyser_cf"], wind_share=share,
                   efuels_twh=loads["efuels"], vehicles_rail_twh=loads["vehicles_rail"])
        hist.append(rec)
        print("iteration", len(hist), {k_: round(v, 3) for k_, v in rec.items()}, flush=True)
        fitres = fit(h["direct_design"] + max(dist, 0.0), h["flex_with_electrolyser"] + base["adder"]["net_flex"],
                     h["electrolyser_cf"], h["h2_storage"], base, wind_share=share,
                     turbine_ch4=cal0.get("turbine_methane_twh", 0.0))
        cal = dict(fitres, hourly_last=h, annual_uncalibrated=a0, transmission_aud_mwh=tr, distribution_aud_mwh=dist,
                   objective_uncalibrated_bn=S0["objective_bn"], iteration_history=hist,
                   hourly_pass1=cal0.get("hourly_pass1", h),
                   turbine_methane_twh=cal0.get("turbine_methane_twh", 0.0),
                   turbine_methane_source=cal0.get("turbine_methane_source", "none"),
                   rule="annual el_direct dual = hourly direct design price + distribution; annual flexible price incl. "
                        "electrolyser = hourly flexible price + electrolyser + H2 store + flexible network adder; "
                        "electrolyser utilisation and wind share of generation from the hourly design; iterated")
        O.CALIBRATION.write_text(json.dumps(cal, indent=1, default=float))
        if prev and abs(rec["direct"] - prev["direct"]) < 1.0 and abs(rec["flex"] - prev["flex"]) < 1.0 \
                and abs(rec["wind_share"] - prev["wind_share"]) < 0.01 \
                and abs(rec["efuels_twh"] / prev["efuels_twh"] - 1) < 0.01:
            print("converged", flush=True)
            break
        prev = rec
        R = None


def stage_pass1():
    base = O.base_params(calibrated=False)
    S0 = O.solve(base)
    R1 = D.run(S=S0, check=True, **FAST)
    (OUT / "dispatch_pass1.json").write_text(json.dumps(R1, indent=1, default=float))
    return R1


def stage_fit():
    if O.CALIBRATION.exists():
        O.CALIBRATION.unlink()
    base = O.base_params(calibrated=False)
    S0 = O.solve(base)
    a0 = annual_prices(S0, base)
    R1 = json.loads((OUT / "dispatch_pass1.json").read_text())
    h1 = hourly_prices(R1)
    tr = transmission_per_mwh(R1)
    dist = base["adder"]["net_dir"] - tr          # network cost on direct loads not represented hourly
    print("hourly pass 1", {k: round(v, 1) for k, v in h1.items()}, "transmission", round(tr, 1), flush=True)
    fitres = fit(h1["direct"] + max(dist, 0.0), h1["flex_with_electrolyser"] + base["adder"]["net_flex"],
                 h1["electrolyser_cf"], h1["h2_storage"], base)
    cal = dict(fitres, hourly_pass1=h1, annual_uncalibrated=a0, transmission_aud_mwh=tr, distribution_aud_mwh=dist,
               objective_uncalibrated_bn=S0["objective_bn"],
               rule="direct: annual el_direct dual = hourly direct price + (annual network adder - hourly transmission); "
                    "flexible: annual flexible price incl. electrolyser = hourly flexible price + electrolyser + H2 "
                    "store + annual flexible network adder; electrolyser utilisation from the hourly model")
    O.CALIBRATION.write_text(json.dumps(cal, indent=1, default=float))
    S1 = O.solve(O.base_params())
    print("annual calibrated", round(S1["objective_bn"], 2), flush=True)


def stage_pass2():
    S1 = O.solve(O.base_params())
    R2 = D.run(S=S1, check=True, **FAST)
    (OUT / "dispatch.json").write_text(json.dumps(R2, indent=1, default=float))


def stage_inflexible():
    S1 = O.solve(O.base_params())
    R3 = D.run(S=S1, check=False, flexible=False, **FAST)
    (OUT / "dispatch_inflexible.json").write_text(json.dumps(R3, indent=1, default=float))


def stage_inflexible_r7():
    """Direct loads only at a 7% real discount rate (comparable with grid-planning studies)."""
    S1 = O.solve(O.base_params())
    R = D.run(S=S1, check=False, flexible=False, r=0.07, **FAST)
    (OUT / "dispatch_inflexible_r7.json").write_text(json.dumps(R, indent=1, default=float))


def stage_counterfactual(mode):
    """Mechanism test: the same electrofuel and air-capture energy as an equally large flexible industrial demand
    with at most 24 h of storage ("daily") or none ("flat"), against the electrolysers with seasonal hydrogen storage."""
    S1 = O.solve(O.base_params())
    R = D.run(S=S1, check=False, flexible=mode, **FAST)
    (OUT / f"dispatch_{mode}.json").write_text(json.dumps(R, indent=1, default=float))


def stage_verify():
    """One-hour adequacy pass for turbines, then the final fleet fixed in every year and verified hour by hour."""
    yrs = sorted(int(k) for k in json.loads((OUT / "dispatch.json").read_text())["resource_index"])
    D.topup_1h(yrs, "all")
    D.verify(years=yrs, step=1)
    stage_methane()


def stage_methane():
    """Set the turbine methane demand of the annual model to the ten-year mean of the one-hour verification."""
    V = json.loads((OUT / "verify_hourly.json").read_text())
    R = json.loads((OUT / "dispatch.json").read_text())
    eff = R["params"]["turb_eff"]
    need = float(np.mean([v["turbine_twh"] for v in V["years"].values()])) / eff
    cal = json.loads(O.CALIBRATION.read_text())
    old = cal.get("turbine_methane_twh", 0.0)
    cal.update(turbine_methane_twh=need, turbine_methane_source="ten-year mean of the one-hour verification / turbine "
                                                                 "efficiency")
    O.CALIBRATION.write_text(json.dumps(cal, indent=1, default=float))
    print(f"turbine methane {old:.3f} -> {need:.3f} TWh/yr", flush=True)
    return old, need


H2_COSTS = (5.0, 10.0, 15.0)    # AUD per kWh of hydrogen stored (central 1.5)


def stage_h2cost(cost, mode=True):
    """Seasonal (mode True) or daily-flexible demand re-optimised at a higher hydrogen-storage cost."""
    S1 = O.solve(O.base_params())
    R = D.run(S=S1, check=False, flexible=mode, h2_store_aud_kwh_h2=cost, **FAST)
    tag = "seasonal" if mode is True else mode
    (OUT / f"dispatch_h2c{cost:g}_{tag}.json").write_text(json.dumps(R, indent=1, default=float))


def stage_finalize(t0=None):
    cal = json.loads(O.CALIBRATION.read_text())
    S1 = O.solve(O.base_params())
    R2 = json.loads((OUT / "dispatch.json").read_text())
    R3 = json.loads((OUT / "dispatch_inflexible.json").read_text())
    h2 = hourly_prices(R2)
    print("hourly pass 2", {k: round(v, 1) for k, v in h2.items()}, flush=True)
    cal.update(hourly_pass2=h2, annual_calibrated_prices=annual_prices(S1, O.base_params()),
               objective_calibrated_bn=S1["objective_bn"],
               inflexible=dict(price_direct_aud_mwh=R3["design"]["price_direct_aud_mwh"], systems=R3["design"]["systems"]),
               runtime_s=float(os.environ.get("CAL_RUNTIME_S", 0)) or (time.time() - t0 if t0 else 0))
    O.CALIBRATION.write_text(json.dumps(cal, indent=1, default=float))


def main():
    import sys
    t0 = time.time()
    st = sys.argv[1] if len(sys.argv) > 1 else "all"
    if st == "all":
        stage_pass1(); stage_fit(); stage_iterate(); stage_pass2(); stage_inflexible(); stage_inflexible_r7()
        stage_counterfactual("daily"); stage_counterfactual("flat")
        for c in H2_COSTS:
            stage_h2cost(c, True); stage_h2cost(c, "daily")
        stage_verify(); stage_finalize(t0)
    else:
        {"pass1": stage_pass1, "fit": stage_fit, "pass2": stage_pass2, "inflexible": stage_inflexible, "iterate": lambda: stage_iterate(start=os.environ.get("CAL_START")), "inflexible_r7": stage_inflexible_r7,
         "verify": stage_verify, "methane": stage_methane,
         **{f"h2c{c:g}_{m}": (lambda c=c, m=m: stage_h2cost(c, True if m == "seasonal" else m))
            for c in H2_COSTS for m in ("seasonal", "daily")}, "daily": lambda: stage_counterfactual("daily"), "flat": lambda: stage_counterfactual("flat"),
         "finalize": lambda: stage_finalize(None)}[st]()
    print("calibrate:", st, "done in", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
