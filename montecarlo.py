"""Monte Carlo analysis of the national LP (1,000 draws of cost, yield, conversion, resource and finance inputs).
SMR parameters are tested separately (scenarios.py, cascade.py). Each draw also samples a Brent-equivalent oil price
(lognormal, inputs.BRENT_DIST) for the fossil comparison; the break-even Brent price of each draw is reported."""
import copy
import json

import numpy as np

import inputs as I
import optimise as O

N = 1000
SEED = 20261115


def draw(rng):
    p = O.base_params()
    u = lambda a, b: float(rng.uniform(a, b))
    p["r"] = u(0.03, 0.07)
    p["wind"]["capex"] *= u(0.8, 1.3)
    p["pv"]["capex"] *= u(0.8, 1.4)
    p["electrolyser"]["capex"] *= u(0.7, 1.6)
    for k in ("eft", "emeoh", "enh3"):
        p[k]["synth"] *= u(0.7, 1.5)
    p["dac"]["cost"] = u(300, 900)
    p["bio_co2"]["cost"] = u(40, 100)
    p["kelp"]["scale"] = u(0.6, 1.5)
    c = copy.deepcopy(p["kelp"]["cost"])
    c.base_aud_t, c.refinery_aud_t, c.rate = u(300, 575), u(200, 330), p["r"]
    p["kelp"]["cost"] = c
    for k in ("straw", "cane", "forest"):
        p[k]["cost_odt"] *= u(0.8, 1.3)
        p[k]["conv"] *= u(0.8, 1.3)
    p["straw"]["cap_mt"] = u(8, 15)
    for k in ("hefa", "canola"):
        p[k]["cost"] *= u(0.85, 1.25)
    p["etoh"]["cost"] *= u(0.85, 1.25)
    p["ers"]["capex_m_km"] = u(2.8, 5.3)
    firm = u(0.7, 1.6)        # calibrated firming adders (hourly model) and electrolyser utilisation
    for k in ("pv_shift", "wind_dir", "pv_dir"):
        p["adder"][k] *= firm
    p["adder"]["net_dir"] *= u(0.8, 1.3)
    p["adder"]["net_flex"] *= u(0.7, 1.5)
    for k in ("cf_solar", "cf_wind"):
        p["electrolyser"][k] = min(0.95, p["electrolyser"][k] * u(0.8, 1.1))
    p["h2_storage_aud_mwh_el"] = p.get("h2_storage_aud_mwh_el", 0.0) * u(0.3, 5.0)
    p["_brent"] = float(rng.lognormal(np.log(I.BRENT_DIST["median"]), I.BRENT_DIST["sigma"]))
    return p


def run():
    rng = np.random.default_rng(SEED)
    rows = []
    C = O.solve(O.base_params())
    f25, f26 = C["fossil_cost_bn"]["avg2025"], C["fossil_cost_bn"]["oct2026"]
    rf = O.OUT / "reconciled.json"
    rec_off = json.load(open(rf))["difference_bn"] if rf.exists() else 0.0   # hourly-fleet reconciliation, held fixed
    for i in range(N):
        p = draw(rng)
        brent = p.pop("_brent")
        S = O.solve(p)
        rows.append(dict(cost_bn=S["objective_bn"], kelp_km2=S["kelp_total_km2"], smr_gw=S["smr_gw_total"],
                         efuels_twh=S["fuels_twh"]["efuel_ft_solar"] + S["fuels_twh"]["efuel_ft_wind"]
                         + S["fuels_twh"]["e_methanol"] + S["fuels_twh"]["e_ammonia"],
                         ers_km=S["ers_km_electrified"], wtw=S["wtw_reduction_pct"], r=p["r"], kelp_scale=p["kelp"]["scale"], brent=brent,
                         fossil_bn=I.fossil_cost_at_brent(brent, f25, f26),
                         breakeven_brent=I.breakeven_brent(S["objective_bn"], f25, f26),
                         breakeven_brent_reconciled=I.breakeven_brent(S["objective_bn"] + rec_off, f25, f26),
                         cheaper_reconciled=S["objective_bn"] + rec_off < I.fossil_cost_at_brent(brent, f25, f26)))
    cost = np.array([r["cost_bn"] for r in rows])
    kelp = np.array([r["kelp_km2"] for r in rows])
    be = np.array([r["breakeven_brent"] for r in rows])
    cheaper = np.array([r["cost_bn"] < r["fossil_bn"] for r in rows])
    summ = dict(n=N, median=float(np.median(cost)), p5=float(np.percentile(cost, 5)), p95=float(np.percentile(cost, 95)),
                min=float(cost.min()), max=float(cost.max()),
                beat_2025=int((cost < C["fossil_cost_bn"]["avg2025"]).sum()),
                beat_oct2026=int((cost < C["fossil_cost_bn"]["oct2026"]).sum()),
                kelp_median=float(np.median(kelp)), kelp_p95=float(np.percentile(kelp, 95)),
                kelp_any=int((kelp > 1).sum()), smr_any=int((np.array([r["smr_gw"] for r in rows]) > 0.01).sum()),
                ers_km_median=float(np.median([r["ers_km"] for r in rows])),
                ers_km_p5=float(np.percentile([r["ers_km"] for r in rows], 5)),
                ers_km_p95=float(np.percentile([r["ers_km"] for r in rows], 95)),
                wtw_median=float(np.median([r["wtw"] for r in rows])),
                breakeven_brent_median=float(np.median(be)), breakeven_brent_p5=float(np.percentile(be, 5)),
                breakeven_brent_p95=float(np.percentile(be, 95)), cheaper_at_sampled_brent=int(cheaper.sum()),
                brent_dist=I.BRENT_DIST, reconciliation_offset_bn=rec_off,
                breakeven_reconciled_median=float(np.median([r["breakeven_brent_reconciled"] for r in rows])),
                breakeven_reconciled_p5=float(np.percentile([r["breakeven_brent_reconciled"] for r in rows], 5)),
                breakeven_reconciled_p95=float(np.percentile([r["breakeven_brent_reconciled"] for r in rows], 95)),
                cheaper_reconciled=int(sum(r["cheaper_reconciled"] for r in rows)))
    json.dump(dict(summary=summ, rows=rows), open(O.OUT / "montecarlo.json", "w"), indent=0, default=float)
    return summ


if __name__ == "__main__":
    print(run())
