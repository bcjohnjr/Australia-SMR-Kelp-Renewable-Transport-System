"""Hourly capacity-expansion and dispatch check of the electricity supply for transport (2015-2024 weather).

The annual national programme (optimise.py) balances energy over a year and prices firming, storage and networks with
per-MWh adders. This module tests those adders against observed weather. It takes the electricity loads of the annual
solution (direct loads: vehicles, catenary, rail, mines, heat pumps; flexible loads: electrolysers for electrofuels,
direct air capture, heat storage) and finds the least-cost hourly system that serves them in three separate grids
(NEM, WA, NT), with no help from the existing grid:

  supply     wind and single-axis PV at 24 sites (hourly ERA5 capacity factors scaled to AEMO ISP REZ values,
             observed.py), each with GenCost 2050 capital cost plus ISP connection and REZ transmission cost per MW
  storage    batteries with separate power and energy capacity (ISP 2049-50 4 h and 8 h costs; 92.5% each way)
  firming    turbines burning stored renewable methane (ISP OCGT cost; fuel at the annual model's methane value)
  hydrogen   electrolysers (capacity chosen here) feeding a hydrogen store (lined rock cavern) and synthesis plants
             that run flat; air capture runs flat with synthesis
  demand     direct loads by region from APS 2025 state sales; light-vehicle charging half managed within each day;
             battery trucks mostly overnight; catenary follows traffic; mines, rail and heat flat

Capacities are chosen jointly over design years (the weakest-resource year and a median year), then every year from
2015 to 2024 is re-run with capacities fixed to report unserved energy and extra turbine fuel. Marginal prices from the
hourly balance give the cost of electricity to direct and flexible loads (in a linear programme with constant returns
these revenues recover all costs), which calibrate the annual model's adders (calibration.json).
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import json
import time
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog

import inputs as I
import optimise as O

HERE = Path(__file__).resolve().parent
OBS = HERE / "observed_data"
OUT = HERE / "outputs"
SYSTEMS = ("QLD", "NSW_VIC", "SA_TAS", "WA", "NT")      # nodes: three in the NEM, WA and NT separate
UTC_OFFSET = {"QLD": 10, "NSW_VIC": 10, "SA_TAS": 10, "WA": 8, "NT": 9.5}
STATE_SYSTEM = {"NSW": "NSW_VIC", "VIC": "NSW_VIC", "ACT": "NSW_VIC", "QLD": "QLD", "SA": "SA_TAS", "TAS": "SA_TAS",
                "WA": "WA", "NT": "NT"}
NODE_OF_GROUP = {"NSW": "NSW_VIC", "VIC": "NSW_VIC", "QLD": "QLD", "SA": "SA_TAS", "TAS": "SA_TAS", "WA_SWIS": "WA",
                 "WA_NW": "WA", "NT": "NT"}
LINKS = (("QLD", "NSW_VIC", 3.28), ("NSW_VIC", "SA_TAS", 2.5))   # new transfer capacity, AUD M per MW (ISP flow paths:
                                                                  # NNSW-SQ 3.28; SA-VIC 0.9 and Marinus ~5, blended)


def P(**kw):
    """Hourly-model parameters (2050 learning case, 4% real)."""
    isp = json.loads((OBS / "isp_2026.json").read_text())
    bc = isp["build_cost_aud_kw_real2025"]
    b4, b8 = bc["Battery storage (4hrs storage)"]["2049-50"], bc["Battery storage (8hrs storage)"]["2049-50"]
    e_kwh = (b8 - b4) / 4.0
    p = dict(
        r=0.04,
        wind_capex=I.GENCOST_CAPEX["wind"][2050], wind_fom=28.0, pv_capex=I.GENCOST_CAPEX["solar"][2050], pv_fom=14.0,
        gen_life=30,
        connection_aud_kw=isp["connection_aud_kw"], connection_default=200.0,
        rez_aud_kw=1000 * isp["rez_augmentation"]["aud_m_per_mw_median"], net_life=50,
        batt_power_kw=b4 - 4 * e_kwh, batt_energy_kwh=e_kwh, batt_fom_kw=6.0, batt_fom_kwh=4.0, batt_life=20,
        eta_c=isp["battery"]["charge_eff"], eta_d=isp["battery"]["discharge_eff"],
        turb_capex=bc["OCGT (large GT)"]["2049-50"], turb_fom=isp["fixed_opex_aud_kw_yr"]["OCGT (large GT)"], turb_life=30,
        turb_eff=0.38, methane_aud_mwh=None, turb_vom=8.0,
        elz_capex=I.GENCOST_CAPEX["electrolyser_alk"][2050], elz_om=0.02, elz_life=25,
        h2_store_aud_kwh_h2=1.5, h2_eff=0.70, h2_life=40,
        loss_direct=0.05, loss_flex=0.02,
        ldv_managed=0.5, ldv_flex_max=3.0, site_wind_max_gw=25.0, site_pv_max_gw=50.0,
        voll=20000.0, voll_adequacy=300000.0, link_life=50, wheel_aud_mwh=1.0,   # voll_adequacy: turbine sizing in the 1-h pass
    )
    p.update(kw)
    return p


def crf(r, n):
    return r * (1 + r) ** n / ((1 + r) ** n - 1)


# ---------------------------------------------------------------------------------------------- data and loads
GROUP_OF = {"NSW": "NSW", "VIC": "VIC", "QLD": "QLD", "SA": "SA", "TAS": "TAS", "WA": "WA_SWIS", "WA_NW": "WA_NW",
            "NT": "NT"}


def observed(grouped=True):
    """Hourly capacity factors. grouped=True averages sites within each state (equal weights), so each grid has a
    handful of resource groups (keeps the hourly programme tractable); site detail stays in observed_data/."""
    o = _observed_sites()
    if not grouped:
        return o
    groups = {}
    for i, n in enumerate(o["names"]):
        groups.setdefault(GROUP_OF[o["sites"][n]["state"]], []).append(i)
    names = list(groups)
    isp = json.loads((OBS / "isp_2026.json").read_text())["connection_aud_kw"]
    sites = {}
    for g, ii in groups.items():
        conns = [isp.get(o["sites"][o["names"][i]]["rez"] or "", None) for i in ii]
        conns = [c for c in conns if c is not None]
        sites[g] = dict(system=NODE_OF_GROUP[g], members=[o["names"][i] for i in ii],
                        rez=None, connection_aud_kw=float(np.mean(conns)) if conns else None)
    return dict(wind=np.array([o["wind"][ii].mean(0) for ii in groups.values()]),
                pv=np.array([o["pv"][ii].mean(0) for ii in groups.values()]), names=names, sites=sites,
                times=o["times"], years=o["years"])


def _observed_sites():
    cf = np.load(OBS / "cf_hourly.npz")
    sites = json.loads((OBS / "sites.json").read_text())["sites"]
    names = [str(x) for x in cf["sites"]]
    t0 = np.datetime64(str(cf["t0"]))
    hours = int(cf["hours"])
    times = t0 + np.arange(hours) * np.timedelta64(1, "h")
    return dict(wind=cf["wind"].astype(np.float32), pv=cf["pv"].astype(np.float32), names=names, sites=sites,
                times=times, years=(times.astype("datetime64[Y]").astype(int) + 1970))


def state_shares():
    aps = json.loads((OBS / "aps_2025.json").read_text())["by_state_ml"]
    out = {}
    for fuel, d in aps.items():
        tot = sum(d.values())
        sh = {s: 0.0 for s in SYSTEMS}
        for st, v in d.items():
            sh[STATE_SYSTEM.get(st, "NEM")] += v / tot
        out[fuel] = sh
    return out


def loads_from_annual(S):
    """Direct electricity by segment (TWh/yr, at the meter) and flexible loads from the annual solution."""
    seg = {}
    for k, v in S["end_use_twh"].items():
        s, o = k.split("|")
        car, ratio = O.OPTIONS[s][o][0], O.OPTIONS[s][o][1]
        if car == "el":
            seg[s] = seg.get(s, 0.0) + v * ratio
    ers = sum(S["ers_twh"].values()) * O.ERS_RATIO
    e = S["electricity_twh"]
    return dict(segments=seg, ers=ers, heat=e.get("refineries_heat", 0.0), heat_storage=e.get("heat_storage", 0.0),
                efuels=e.get("efuels", 0.0), dac=e.get("dac", 0.0), vehicles_rail=e.get("vehicles_rail", 0.0))


def load_profiles(hours_local):
    """Normalised (mean 1) daily shapes by local hour."""
    h = hours_local
    ldv_unmanaged = np.where((h >= 17) & (h < 23), 2.6, np.where((h >= 7) & (h < 17), 0.9, 0.45))
    truck = np.where((h >= 22) | (h < 6), 2.0, np.where((h >= 6) & (h < 18), 0.65, 0.35))
    ers = np.where((h >= 6) & (h < 20), 1.35, 0.4)
    flat = np.ones_like(h, dtype=float)
    f = lambda x: x / x.mean()
    return dict(ldv=f(ldv_unmanaged), truck=f(truck), ers=f(ers), flat=flat)


def regional_loads(L, times, p):
    """Hourly direct load (fixed part, MW), daily managed light-vehicle energy (MWh/day) by system."""
    sh = state_shares()
    seg_fuel = {"ldv_petrol": "petrol", "ldv_diesel": "diesel", "hdv": "diesel", "rail": "diesel", "mining": "diesel",
                "farm": "diesel", "construction": "diesel", "aviation": "jet", "shipping": "diesel"}
    H = len(times)
    out = {}
    for sysn in SYSTEMS:
        loc = (times + np.timedelta64(int(UTC_OFFSET[sysn] * 60), "m"))
        hl = ((loc - loc.astype("datetime64[D]")) / np.timedelta64(1, "h")).astype(int)
        day = ((loc.astype("datetime64[D]") - loc[0].astype("datetime64[D]")) / np.timedelta64(1, "D")).astype(int)
        pr = load_profiles(hl)
        fixed = np.zeros(H)
        managed = 0.0
        for s, twh in L["segments"].items():
            mw = twh * 1e6 / 8766 * sh[seg_fuel[s]][sysn] * (1 + p["loss_direct"])
            if s.startswith("ldv"):
                fixed += mw * (1 - p["ldv_managed"]) * pr["ldv"]
                managed += mw * p["ldv_managed"]
            elif s == "hdv":
                fixed += mw * pr["truck"]
            else:
                fixed += mw * pr["flat"]
        fixed += L["ers"] * 1e6 / 8766 * sh["diesel"][sysn] * (1 + p["loss_direct"]) * pr["ers"]
        fixed += (L["heat"] + L["heat_storage"]) * 1e6 / 8766 * sh["diesel"][sysn] * (1 + p["loss_direct"])
        out[sysn] = dict(fixed=fixed, managed_mw=managed, day=day)
    return out


# ---------------------------------------------------------------------------------------------- LP
class Builder:
    def __init__(self):
        self.n = 0
        self.c, self.lb, self.ub, self.names = [], [], [], {}
        self.rows, self.cols, self.vals, self.rhs, self.kind = [], [], [], [], []
        self.m = 0

    def add(self, name, n, cost=0.0, lb=0.0, ub=np.inf):
        i0 = self.n
        self.n += n
        self.c.append(np.broadcast_to(np.asarray(cost, float), (n,)).copy())
        self.lb.append(np.broadcast_to(np.asarray(lb, float), (n,)).copy())
        self.ub.append(np.broadcast_to(np.asarray(ub, float), (n,)).copy())
        self.names[name] = (i0, n)
        return np.arange(i0, i0 + n)

    def cons(self, row_cols, row_vals, rhs, kind):
        """row_cols/row_vals: lists of arrays, each of length nrows (one entry per row) or scalars broadcast."""
        nr = len(rhs)
        r = np.arange(self.m, self.m + nr)
        for cols, vals in zip(row_cols, row_vals):
            cols = np.broadcast_to(cols, (nr,))
            vals = np.broadcast_to(np.asarray(vals, float), (nr,))
            self.rows.append(r); self.cols.append(cols); self.vals.append(vals)
        self.rhs.append(np.asarray(rhs, float)); self.kind.append(np.full(nr, kind))
        self.m += nr
        return r

    def solve(self):
        rows = np.concatenate(self.rows); cols = np.concatenate(self.cols); vals = np.concatenate(self.vals)
        A = sp.csr_matrix((vals, (rows, cols)), shape=(self.m, self.n))
        rhs = np.concatenate(self.rhs); kind = np.concatenate(self.kind)
        ub_rows = np.where(kind == 0)[0]; eq_rows = np.where(kind == 1)[0]
        c = np.concatenate(self.c)
        bounds = np.column_stack([np.concatenate(self.lb), np.concatenate(self.ub)])
        bounds = [(a, None if np.isinf(b) else b) for a, b in bounds]
        res = linprog(c, A_ub=A[ub_rows], b_ub=rhs[ub_rows], A_eq=A[eq_rows] if len(eq_rows) else None,
                      b_eq=rhs[eq_rows] if len(eq_rows) else None, bounds=bounds, method=getattr(self, "method", "highs-ipm"),
                      options=dict(presolve=True, time_limit=3000))
        if res.status != 0:
            raise RuntimeError(res.message)
        dual = np.zeros(self.m)
        dual[ub_rows] = res.ineqlin.marginals
        if len(eq_rows):
            dual[eq_rows] = res.eqlin.marginals
        self.x, self.dual, self.obj = res.x, dual, res.fun
        return res

    def val(self, name):
        i0, n = self.names[name]
        return self.x[i0:i0 + n]


def blocks(x, step):
    if step == 1:
        return x
    return x.reshape(*x.shape[:-1], -1, step).mean(-1)


def build(obs, L, p, years, fixed_caps=None, step=1, hours=None, turb_fixed=False):
    """LP over the given weather years. Capacities shared across years; operations in blocks of `step` hours
    (averages of hourly capacity factors and loads). Costs per average year. `hours` restricts to a slice (tests)."""
    mask = np.isin(obs["years"], years)
    idx = np.where(mask)[0]
    if hours is not None:
        idx = idx[:hours]
    times_h = obs["times"][idx]
    ny = len(years) if hours is None else len(idx) / 8766
    wgt = 1.0 / ny
    r = p["r"]
    RLh = regional_loads(L, times_h, p)
    T = len(idx) // step
    idx = idx[:T * step]
    yrs_b = obs["years"][idx][::step]
    wcf, pcf = blocks(obs["wind"][:, idx], step), blocks(obs["pv"][:, idx], step)
    RL = {k: dict(fixed=blocks(v["fixed"][:T * step], step), managed_mw=v["managed_mw"], day=v["day"][:T * step][::step])
          for k, v in RLh.items()}
    b = Builder()
    b.step, b.ny = step, ny
    ann = lambda capex, life, fom=0.0: (capex * crf(r, life) + fom) * 1000      # AUD per MW-yr
    meth = p["methane_aud_mwh"]
    fuel_cost = meth / p["turb_eff"] + p["turb_vom"]
    sites_by_sys = {s: [i for i, n in enumerate(obs["names"]) if obs["sites"][n]["system"] == s] for s in SYSTEMS}
    rez_ann = ann(p["rez_aud_kw"], p["net_life"])
    caps, ops = {}, {}
    efuel_mw_total = L["efuels"] * 1e6 / 8766 * (1 + p["loss_flex"])
    dac_per_synth = L["dac"] / max(L["efuels"], 1e-9)
    synth = b.add("synth", len(SYSTEMS), 0.0)
    for k, sysn in enumerate(SYSTEMS):
        si = sites_by_sys[sysn]
        conn = [obs["sites"][obs["names"][i]].get("connection_aud_kw") or p["connection_default"] for i in si]
        fc = fixed_caps[sysn] if fixed_caps else None
        wl = lambda key, default: (fc[key], fc[key]) if fc else (default, None)
        cw = b.add(f"wind_cap|{sysn}", len(si), [ann(p["wind_capex"] + cn + p["rez_aud_kw"] * 0, p["gen_life"], p["wind_fom"]) + rez_ann for cn in conn],
                   lb=fc["wind"] if fc else 0.0, ub=fc["wind"] if fc else [p["site_wind_max_gw"] * 1000 * len(obs["sites"][obs["names"][i]].get("members", [1])) for i in si])
        cp = b.add(f"pv_cap|{sysn}", len(si), [ann(p["pv_capex"] + cn, p["gen_life"], p["pv_fom"]) + rez_ann for cn in conn],
                   lb=fc["pv"] if fc else 0.0, ub=fc["pv"] if fc else [p["site_pv_max_gw"] * 1000 * len(obs["sites"][obs["names"][i]].get("members", [1])) for i in si])
        one = lambda nm, cost, key: b.add(f"{nm}|{sysn}", 1, cost, lb=fc[key] if fc else 0.0, ub=fc[key] if fc else np.inf)
        bp = one("batt_p", ann(p["batt_power_kw"], p["batt_life"], p["batt_fom_kw"]), "batt_p")
        be = one("batt_e", ann(p["batt_energy_kwh"], p["batt_life"], p["batt_fom_kwh"]), "batt_e")
        tg = b.add(f"turb|{sysn}", 1, ann(p["turb_capex"], p["turb_life"], p["turb_fom"]),
                   lb=fc["turb"] if fc else 0.0,
                   ub=fc["turb"] if (fc and turb_fixed) else np.inf)   # turbines may be topped up in yearly checks
        ez = one("elz", ann(p["elz_capex"], p["elz_life"]) + p["elz_om"] * p["elz_capex"] * 1000, "elz")
        hs = one("h2s", ann(p["h2_store_aud_kwh_h2"] * p["h2_eff"], p["h2_life"]), "h2s")
        ch = b.add(f"ch|{sysn}", T, 0.0)
        dis = b.add(f"dis|{sysn}", T, 0.5 * wgt * step)          # small wear cost avoids simultaneous cycling
        soc = b.add(f"soc|{sysn}", T, 0.0)
        tu = b.add(f"tu|{sysn}", T, fuel_cost * wgt * step)
        el = b.add(f"el|{sysn}", T, 0.0)
        h2 = b.add(f"h2|{sysn}", T, 0.0)
        ldv = b.add(f"ldv|{sysn}", T, 0.0, ub=RL[sysn]["managed_mw"] * p["ldv_flex_max"])
        uns = b.add(f"uns|{sysn}", T, p["voll"] * wgt * step)
        caps[sysn] = dict(cw=cw, cp=cp, bp=bp, be=be, tg=tg, ez=ez, hs=hs, si=si)
        ops[sysn] = dict(ch=ch, dis=dis, soc=soc, tu=tu, el=el, h2=h2, ldv=ldv, uns=uns)
        # balance: sum_s cap_s*CF + dis + tu + uns - ch - el - ldv - dac(synth) >= fixed
        cols = [ch, dis, tu, el, ldv, uns]
        vals = [1.0, -1.0, -1.0, 1.0, 1.0, -1.0]
        for j, s in enumerate(si):
            cols += [np.full(T, cw[j]), np.full(T, cp[j])]
            vals += [-wcf[s], -pcf[s]]
        cols.append(np.full(T, synth[k])); vals.append(dac_per_synth * np.ones(T))
        ops[sysn]["bal"] = b.cons(cols, vals, -RL[sysn]["fixed"], 0)
        # battery state of charge, cyclic within each year
        prev = np.roll(soc, 1)
        starts = np.r_[0, np.where(np.diff(yrs_b) != 0)[0] + 1]
        ends = np.r_[starts[1:] - 1, T - 1]
        for s0, e0 in zip(starts, ends):
            prev[s0] = soc[e0]
        b.cons([soc, prev, ch, dis], [1.0, -1.0, -p["eta_c"] * step, step / p["eta_d"]], np.zeros(T), 1)
        b.cons([soc, np.full(T, be[0])], [1.0, -1.0], np.zeros(T), 0)
        b.cons([ch, np.full(T, bp[0])], [1.0, -1.0], np.zeros(T), 0)
        b.cons([dis, np.full(T, bp[0])], [1.0, -1.0], np.zeros(T), 0)
        b.cons([tu, np.full(T, tg[0])], [1.0, -1.0], np.zeros(T), 0)
        b.cons([el, np.full(T, ez[0])], [1.0, -1.0], np.zeros(T), 0)
        # hydrogen store (MWh of electrolyser input equivalent), cyclic within each year; synthesis flat
        prevh = np.roll(h2, 1)
        for s0, e0 in zip(starts, ends):
            prevh[s0] = h2[e0]
        b.cons([h2, prevh, el, np.full(T, synth[k])], [1.0, -1.0, -float(step), float(step)], np.zeros(T), 1)
        b.cons([h2, np.full(T, hs[0])], [1.0, -1.0], np.zeros(T), 0)
        if p.get("h2_buffer_h") is not None and not fc:   # counterfactual: store limited to N hours of synthesis demand
            b.cons([np.array([hs[0]]), np.array([synth[k]])], [1.0, -float(p["h2_buffer_h"])], np.zeros(1), 0)
        # managed charging: daily energy fixed
        day = RL[sysn]["day"]
        dsel = day
        # one row per day: sum of ldv over the day's hours = managed MW x hours in day
        order = np.argsort(dsel, kind="stable")
        dd = dsel[order]
        brk = np.r_[0, np.where(np.diff(dd) != 0)[0] + 1, len(dd)]
        rows_c, rows_v, rhs = [], [], []
        nrow0 = b.m
        R_, C_, V_ = [], [], []
        for q in range(len(brk) - 1):
            hh = order[brk[q]:brk[q + 1]]
            R_.append(np.full(len(hh), nrow0 + q)); C_.append(ldv[hh]); V_.append(np.ones(len(hh)))
            rhs.append(RL[sysn]["managed_mw"] * len(hh))
        b.rows.append(np.concatenate(R_)); b.cols.append(np.concatenate(C_)); b.vals.append(np.concatenate(V_))
        b.rhs.append(np.array(rhs)); b.kind.append(np.ones(len(rhs), dtype=int)); b.m += len(rhs)
    # inter-node links (new capacity, lossless, small wheeling cost)
    for a_, b_, cost_m in LINKS:
        fc_l = fixed_caps.get("links", {}).get(f"{a_}-{b_}") if fixed_caps else None
        cap = b.add(f"link|{a_}-{b_}", 1, ann(cost_m * 1000, p["link_life"]), lb=fc_l or 0.0,
                    ub=fc_l if fc_l is not None else np.inf)
        fp = b.add(f"fpos|{a_}-{b_}", T, p["wheel_aud_mwh"] * wgt * step)
        fn = b.add(f"fneg|{a_}-{b_}", T, p["wheel_aud_mwh"] * wgt * step)
        b.cons([fp, np.full(T, cap[0])], [1.0, -1.0], np.zeros(T), 0)
        b.cons([fn, np.full(T, cap[0])], [1.0, -1.0], np.zeros(T), 0)
        # export from a reduces a's supply: add to a's balance (load side) and subtract at b
        b.rows += [ops[a_]["bal"], ops[a_]["bal"], ops[b_]["bal"], ops[b_]["bal"]]
        b.cols += [fp, fn, fp, fn]
        b.vals += [np.ones(T), -np.ones(T), -np.ones(T), np.ones(T)]
        caps.setdefault("_links", {})[f"{a_}-{b_}"] = (cap, fp, fn)
    # electrofuel synthesis: national total fixed, placed where cheapest
    b.cons([synth], [np.ones(len(SYSTEMS))], [efuel_mw_total], 1) if False else None
    b.rows.append(np.full(len(SYSTEMS), b.m)); b.cols.append(synth); b.vals.append(np.ones(len(SYSTEMS)))
    b.rhs.append(np.array([efuel_mw_total])); b.kind.append(np.array([1])); b.m += 1
    if fixed_caps:
        for k, sysn in enumerate(SYSTEMS):
            b.lb[0][k] = b.ub[0][k] = fixed_caps[sysn]["synth"]
    b.wcf, b.pcf = wcf, pcf
    return b, caps, ops, RL, idx, synth


def summarise(b, caps, ops, RL, idx, synth, obs, p, years, L):
    ny, st = b.ny, b.step
    out = dict(years=list(map(int, years)), systems={})
    tot_cost = b.obj
    cost_direct = cost_flex = 0.0
    e_direct = e_flex = 0.0
    for k, sysn in enumerate(SYSTEMS):
        c, o = caps[sysn], ops[sysn]
        lam = -b.dual[o["bal"]] * ny / st   # AUD/MWh (duals are per average-year objective, per block)
        fixed = RL[sysn]["fixed"]
        ldv = b.x[o["ldv"]]
        el = b.x[o["el"]]
        dac = L["dac"] / max(L["efuels"], 1e-9) * b.x[synth[k]] * np.ones(len(fixed))
        d_e = (fixed.sum() + ldv.sum()) * st / ny
        f_e = (el.sum() + dac.sum()) * st / ny
        cd = (lam * (fixed + ldv)).sum() * st / ny
        cf = (lam * (el + dac)).sum() * st / ny
        cost_direct += cd; cost_flex += cf; e_direct += d_e; e_flex += f_e
        wind = b.x[c["cw"]]; pv = b.x[c["cp"]]
        net_exp = np.zeros(len(fixed))
        for name, (lc, fp, fn) in caps.get("_links", {}).items():
            a_, b_ = name.split("-")
            if a_ == sysn:
                net_exp += b.x[fp] - b.x[fn]
            elif b_ == sysn:
                net_exp -= b.x[fp] - b.x[fn]
        gen = sum(wind[j] * b.wcf[s] + pv[j] * b.pcf[s] for j, s in enumerate(c["si"]))
        out["systems"][sysn] = dict(
            wind_gw=float(wind.sum() / 1000), pv_gw=float(pv.sum() / 1000),
            wind_by_site_gw={obs["names"][s]: float(wind[j] / 1000) for j, s in enumerate(c["si"])},
            pv_by_site_gw={obs["names"][s]: float(pv[j] / 1000) for j, s in enumerate(c["si"])},
            battery_gw=float(b.x[c["bp"]][0] / 1000), battery_gwh=float(b.x[c["be"]][0] / 1000),
            turbine_gw=float(b.x[c["tg"]][0] / 1000), electrolyser_gw=float(b.x[c["ez"]][0] / 1000),
            h2_store_gwh_el=float(b.x[c["hs"]][0] / 1000), synth_gw_el=float(b.x[synth[k]] / 1000),
            direct_twh=d_e / 1e6, flexible_twh=f_e / 1e6, generation_twh=float(gen.sum() * st / ny / 1e6),
            wind_twh=float(sum(wind[j] * b.wcf[s_] for j, s_ in enumerate(c["si"])).sum() * st / ny / 1e6) if len(c["si"]) else 0.0,
            pv_twh=float(sum(pv[j] * b.pcf[s_] for j, s_ in enumerate(c["si"])).sum() * st / ny / 1e6) if len(c["si"]) else 0.0,
            curtail_twh=float((gen.sum() + b.x[o["dis"]].sum() + b.x[o["tu"]].sum() - b.x[o["ch"]].sum()
                               - el.sum() - ldv.sum() - fixed.sum() - dac.sum() - net_exp.sum()) * st / ny / 1e6),
            net_export_twh=float(net_exp.sum() * st / ny / 1e6),
            turbine_twh=float(b.x[o["tu"]].sum() * st / ny / 1e6), unserved_mwh=float(b.x[o["uns"]].sum() * st / ny),
            battery_twh_out=float(b.x[o["dis"]].sum() * st / ny / 1e6),
            price_direct_aud_mwh=cd / max(d_e, 1), price_flex_aud_mwh=cf / max(f_e, 1),
            electrolyser_cf=float(el.sum() * st / ny / 8766 / max(b.x[c["ez"]][0], 1e-6)),
            peak_direct_gw=float((fixed + ldv).max() / 1000),
        )
    out["links_gw"] = {k: float(b.x[v[0]][0] / 1000) for k, v in caps.get("_links", {}).items()}
    out["link_flow_twh"] = {k: float((b.x[v[1]].sum() + b.x[v[2]].sum()) * st / ny / 1e6) for k, v in caps.get("_links", {}).items()}
    out.update(total_cost_bn=tot_cost / 1e9, cost_direct_bn=cost_direct / 1e9, cost_flex_bn=cost_flex / 1e9,
               direct_twh=e_direct / 1e6, flexible_twh=e_flex / 1e6,
               price_direct_aud_mwh=cost_direct / max(e_direct, 1), price_flex_aud_mwh=cost_flex / max(e_flex, 1))
    return out


def caps_of(b, caps, synth):
    fc = {}
    for k, sysn in enumerate(SYSTEMS):
        c = caps[sysn]
        fc[sysn] = dict(wind=b.x[c["cw"]].copy(), pv=b.x[c["cp"]].copy(), batt_p=b.x[c["bp"]][0], batt_e=b.x[c["be"]][0],
                        turb=b.x[c["tg"]][0], elz=b.x[c["ez"]][0], h2s=b.x[c["hs"]][0], synth=b.x[synth[k]])
    fc["links"] = {k: float(b.x[v[0]][0]) for k, v in caps.get("_links", {}).items()}
    return fc


def resource_index(obs):
    """Annual mean of (wind + PV) capacity factor over NEM sites, to pick design years."""
    nem = [i for i, n in enumerate(obs["names"]) if obs["sites"][n]["system"] in ("QLD", "NSW_VIC", "SA_TAS")]
    return {int(y): float(obs["wind"][nem][:, obs["years"] == y].mean() + obs["pv"][nem][:, obs["years"] == y].mean())
            for y in np.unique(obs["years"])}


def annual_model_costs(S, p):
    """What the annual programme charges per MWh (for the calibration comparison)."""
    a = O.base_params()["adder"]
    sh = S["shadow_aud_mwh"]
    return dict(direct_aud_mwh=sh["el_direct"], flex_net_adder=a["net_flex"],
                adders=dict(wind_dir=a["wind_dir"], pv_dir=a["pv_dir"], pv_shift=a["pv_shift"], net_dir=a["net_dir"],
                            net_flex=a["net_flex"]))


def run(S=None, design_years=None, check=True, step=3, flexible=True, hours=None, check_years=None, **kw):
    t0 = time.time()
    S = S or json.loads((OUT / "central.json").read_text())
    obs = observed()
    p = P(**kw)
    p["methane_aud_mwh"] = p["methane_aud_mwh"] or S["shadow_aud_mwh"]["methane"]
    L = loads_from_annual(S)
    if flexible is False:      # direct loads only (comparison with whole-system firmed costs)
        L = dict(L, efuels=0.0, dac=0.0, heat_storage=0.0)
    elif flexible == "daily":  # same energy and plant, but a store of at most 24 h of demand (shift within a day)
        p["h2_buffer_h"] = 24.0
    elif flexible == "flat":   # same energy, no storage: constant industrial demand
        p["h2_buffer_h"] = 0.0
    ri = resource_index(obs)
    if design_years is None:
        ordered = sorted(ri, key=ri.get)
        design_years = [ordered[0], ordered[len(ordered) // 2]]
    b, caps, ops, RL, idx, synth = build(obs, L, p, design_years, step=step, hours=hours)
    b.solve()
    design = summarise(b, caps, ops, RL, idx, synth, obs, p, design_years, L)
    fc = caps_of(b, caps, synth)
    res = dict(params={k: v for k, v in p.items() if not isinstance(v, dict)}, loads=L, resource_index=ri,
               design_years=design_years, design=design, solve_s=time.time() - t0, step_h=step,
               capacities={k: {kk: (vv.tolist() if hasattr(vv, "tolist") else vv) for kk, vv in d.items()} for k, d in fc.items()},
               groups=obs["names"])
    if check:
        res["years"] = {}
        top = {n: fc[n]["turb"] for n in SYSTEMS}
        for y in (check_years or sorted(ri)):
            b2, c2, o2, R2, i2, s2 = build(obs, L, p, [y], fixed_caps=fc, step=step, hours=hours)
            b2.solve()
            sm = summarise(b2, c2, o2, R2, i2, s2, obs, p, [y], L)
            tg = {n: sm["systems"][n]["turbine_gw"] for n in SYSTEMS}
            for n in SYSTEMS:
                top[n] = max(top[n], tg[n] * 1000)
            res["years"][y] = dict(unserved_mwh=sum(v["unserved_mwh"] for v in sm["systems"].values()),
                                   turbine_gw=sum(tg.values()), turbine_twh=sum(v["turbine_twh"] for v in sm["systems"].values()),
                                   curtail_twh=sum(v["curtail_twh"] for v in sm["systems"].values()),
                                   battery_twh_out=sum(v["battery_twh_out"] for v in sm["systems"].values()))
        ann_t = (p["turb_capex"] * crf(p["r"], p["turb_life"]) + p["turb_fom"]) * 1000
        extra_mw = sum(top[n] - fc[n]["turb"] for n in SYSTEMS)
        fuel = p["methane_aud_mwh"] / p["turb_eff"] + p["turb_vom"]
        mean_turb = float(np.mean([v["turbine_twh"] for v in res["years"].values()]))
        res["robust"] = dict(turbine_gw_by_node={n: top[n] / 1000 for n in SYSTEMS}, turbine_gw=sum(top.values()) / 1000,
                             extra_turbine_gw=extra_mw / 1000, extra_turbine_cost_bn=extra_mw * ann_t / 1e9,
                             turbine_twh_mean_10yr=mean_turb, turbine_twh_max=max(v["turbine_twh"] for v in res["years"].values()),
                             fuel_cost_mean_bn=mean_turb * 1e6 * fuel / 1e9,
                             unserved_mwh_max=max(v["unserved_mwh"] for v in res["years"].values()),
                             direct_price_with_topup=design["price_direct_aud_mwh"] + extra_mw * ann_t / (design["direct_twh"] * 1e6))
    res["annual_model"] = annual_model_costs(S, p)
    res["solve_s"] = time.time() - t0
    return res


def _cap_cost(fc, p, obs):
    """Annualised capacity cost of fixed capacities (AUD/yr), for operating-cost reporting."""
    r = p["r"]
    ann = lambda capex, life, fom=0.0: (capex * crf(r, life) + fom) * 1000
    rez_ann = ann(p["rez_aud_kw"], p["net_life"])
    tot = 0.0
    for sysn in SYSTEMS:
        si = [i for i, n in enumerate(obs["names"]) if obs["sites"][n]["system"] == sysn]
        conn = [obs["sites"][obs["names"][i]].get("connection_aud_kw") or p["connection_default"] for i in si]
        c = fc[sysn]
        tot += sum(c["wind"][j] * (ann(p["wind_capex"] + cn, p["gen_life"], p["wind_fom"]) + rez_ann) for j, cn in enumerate(conn))
        tot += sum(c["pv"][j] * (ann(p["pv_capex"] + cn, p["gen_life"], p["pv_fom"]) + rez_ann) for j, cn in enumerate(conn))
        tot += c["batt_p"] * ann(p["batt_power_kw"], p["batt_life"], p["batt_fom_kw"])
        tot += c["batt_e"] * ann(p["batt_energy_kwh"], p["batt_life"], p["batt_fom_kwh"])
        tot += c["turb"] * ann(p["turb_capex"], p["turb_life"], p["turb_fom"])
        tot += c["elz"] * (ann(p["elz_capex"], p["elz_life"]) + p["elz_om"] * p["elz_capex"] * 1000)
        tot += c["h2s"] * ann(p["h2_store_aud_kwh_h2"] * p["h2_eff"], p["h2_life"])
    return tot


def series(year=None, days=14, step=3):
    """Re-solve one weather year with the calibrated design fixed (outputs/dispatch.json) and return the hourly-block
    supply and demand of the NEM nodes for the `days`-long window with the least wind and solar generation."""
    R = json.loads((OUT / "dispatch.json").read_text())
    S = json.loads((OUT / "central.json").read_text())
    obs = observed()
    p = P(methane_aud_mwh=R["params"]["methane_aud_mwh"])
    L = loads_from_annual(S)
    fc = {n: {k: (np.array(v) if isinstance(v, list) else v) for k, v in R["capacities"][n].items()} for n in SYSTEMS}
    fc["links"] = R["capacities"].get("links", {})
    for n in SYSTEMS:
        fc[n]["turb"] = R["robust"]["turbine_gw_by_node"][n] * 1000 if "robust" in R else fc[n]["turb"]
    year = year or R["design_years"][0]
    b, caps, ops, RL, idx, synth = build(obs, L, p, [year], fixed_caps=fc, step=step)
    b.solve()
    nem = ("QLD", "NSW_VIC", "SA_TAS")
    T = len(RL["QLD"]["fixed"])
    tot = dict(wind=np.zeros(T), pv=np.zeros(T), battery=np.zeros(T), turbine=np.zeros(T), direct=np.zeros(T),
               electrolyser=np.zeros(T), charge=np.zeros(T), managed=np.zeros(T), dac=np.zeros(T))
    for k, n in enumerate(SYSTEMS):
        if n not in nem:
            continue
        c, o = caps[n], ops[n]
        for j, s in enumerate(c["si"]):
            tot["wind"] += b.x[c["cw"]][j] * b.wcf[s]
            tot["pv"] += b.x[c["cp"]][j] * b.pcf[s]
        tot["battery"] += b.x[o["dis"]]
        tot["charge"] += b.x[o["ch"]]
        tot["turbine"] += b.x[o["tu"]]
        tot["direct"] += RL[n]["fixed"]
        tot["managed"] += b.x[o["ldv"]]
        tot["electrolyser"] += b.x[o["el"]]
        tot["dac"] += L["dac"] / max(L["efuels"], 1e-9) * b.x[synth[k]]
    per_day = 24 // step
    ren = tot["wind"] + tot["pv"]
    w = days * per_day
    roll = np.convolve(ren, np.ones(w), "valid")
    i0 = int(np.argmin(roll))
    sl = slice(i0, i0 + w)
    t0 = obs["times"][np.isin(obs["years"], [year])][0] + np.timedelta64(i0 * step, "h")
    # coincidence with existing NEM demand (AEMO operational demand, same blocks)
    dm = np.load(OBS / "demand_hourly.npz")
    yr_idx = np.where(np.isin(obs["years"], [year]))[0][:T * step]
    nem_d = sum(np.nan_to_num(dm[r][yr_idx], nan=np.nanmean(dm[r])) for r in ("NSW1", "QLD1", "VIC1", "SA1", "TAS1"))
    nem_b = blocks(nem_d, step)
    hi = nem_b >= np.percentile(nem_b, 90)
    firm = tot["turbine"] + tot["battery"]
    coincidence = dict(
        nem_demand_mean_gw=float(nem_b.mean() / 1000),
        turbine_share_in_top10pct_demand=float(tot["turbine"][hi].sum() / max(tot["turbine"].sum(), 1e-9)),
        firm_share_in_top10pct_demand=float(firm[hi].sum() / max(firm.sum(), 1e-9)),
        corr_renewable_shortfall_vs_nem_demand=float(np.corrcoef(np.maximum(tot["direct"] - ren, 0), nem_b)[0, 1]),
        window_nem_demand_mean_gw=float(nem_b[sl].mean() / 1000))
    return dict(year=year, start_utc=str(t0), step_h=step, days=days, coincidence=coincidence,
                **{k: (v[sl] / 1000).round(3).tolist() for k, v in tot.items()},
                year_mean_renewable_gw=float(ren.mean() / 1000), window_mean_renewable_gw=float(ren[sl].mean() / 1000))


def turbine_1h():
    """Turbine capacity by node (GW) needed at one-hour resolution (outputs/topup_1h_*.json), if computed."""
    need = {}
    for f in sorted(OUT.glob("topup_1h_*.json")):
        for y, v in json.loads(f.read_text()).items():
            for n, g in v.items():
                need[n] = max(need.get(n, 0.0), g)
    return need


def final_fleet(R=None, one_hour=True):
    """Final installed fleet: design capacities, turbines at the ten-year requirement of the three-hour checks and,
    if computed, of the one-hour adequacy pass (the larger of the two at each node)."""
    R = R or json.loads((OUT / "dispatch.json").read_text())
    fc = {n: {k: (np.array(v) if isinstance(v, list) else v) for k, v in R["capacities"][n].items()} for n in SYSTEMS}
    fc["links"] = R["capacities"].get("links", {})
    t1 = turbine_1h() if one_hour else {}
    for n in SYSTEMS:
        fc[n]["turb"] = max(R["robust"]["turbine_gw_by_node"][n], t1.get(n, 0.0)) * 1000
    return fc


def topup_1h(years, tag):
    """One-hour adequacy pass: each year dispatched hour by hour with every capacity fixed except turbines, which may
    be added; records the turbine capacity each node needs (GW). Shortfalls are priced at voll_adequacy, so turbines
    are added wherever a grid would otherwise be short (reliability sizing, independent of the economic VOLL)."""
    R = json.loads((OUT / "dispatch.json").read_text())
    S = json.loads((OUT / "central.json").read_text())
    obs = observed()
    p = P(methane_aud_mwh=R["params"]["methane_aud_mwh"])
    p["voll"] = p["voll_adequacy"]
    L = loads_from_annual(S)
    fc = final_fleet(R, one_hour=False)
    out = {}
    for y in years:
        t = time.time()
        b, c, o, RL, i, sy = build(obs, L, p, [y], fixed_caps=fc, step=1)
        b.solve()
        sm = summarise(b, c, o, RL, i, sy, obs, p, [y], L)
        out[y] = {n: max(v["turbine_gw"], fc[n]["turb"] / 1000) for n, v in sm["systems"].items()}
        print("topup_1h", y, {n: round(g, 2) for n, g in out[y].items()}, round(time.time() - t), "s", flush=True)
        (OUT / f"topup_1h_{tag}.json").write_text(json.dumps(out, indent=1, default=float))
    return out


def verify(years=None, step=1, tag="verify_hourly"):
    """Final verification: the final installed fleet (design capacities plus the topped-up turbines), identical in
    every year and with nothing allowed to expand, dispatched at `step`-hour resolution for each weather year."""
    R = json.loads((OUT / "dispatch.json").read_text())
    S = json.loads((OUT / "central.json").read_text())
    obs = observed()
    p = P(methane_aud_mwh=R["params"]["methane_aud_mwh"])
    L = loads_from_annual(S)
    fc = final_fleet(R)
    out = {}
    for y in (years or sorted(int(k) for k in R["resource_index"])):
        t = time.time()
        b, c, o, RL, i, sy = build(obs, L, p, [y], fixed_caps=fc, step=step, turb_fixed=True)
        b.solve()
        sm = summarise(b, c, o, RL, i, sy, obs, p, [y], L)
        out[y] = dict(unserved_mwh=sum(v["unserved_mwh"] for v in sm["systems"].values()),
                      turbine_twh=sum(v["turbine_twh"] for v in sm["systems"].values()),
                      turbine_peak_gw=float(max(b.x[o_["tu"]].max() for o_ in o.values()) / 1000),
                      curtail_twh_by_node={n: v["curtail_twh"] for n, v in sm["systems"].items()},
                      net_export_twh_by_node={n: v["net_export_twh"] for n, v in sm["systems"].items()},
                      unserved_mwh_by_node={n: v["unserved_mwh"] for n, v in sm["systems"].items()},
                      direct_twh_by_node={n: v["direct_twh"] for n, v in sm["systems"].items()},
                      battery_twh_out=sum(v["battery_twh_out"] for v in sm["systems"].values()),
                      direct_twh=sm["direct_twh"], solve_s=time.time() - t)
        print("verify", y, round(out[y]["unserved_mwh"]), "MWh unserved", round(time.time() - t), "s", flush=True)
    res = dict(step_h=step, years=out, fleet="design capacities + ten-year turbine requirement (three-hour checks and "
               "one-hour adequacy pass), identical in every year, nothing added",
               turbine_gw_by_node={n: fc[n]["turb"] / 1000 for n in SYSTEMS},
               turbine_gw_3h=R["robust"]["turbine_gw"], turbine_gw=sum(fc[n]["turb"] for n in SYSTEMS) / 1000)
    (OUT / f"{tag}.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def merge_verify(tags, tag="verify_hourly"):
    """Combine verification runs made in parallel over different years."""
    parts = [json.loads((OUT / f"{t}.json").read_text()) for t in tags]
    res = dict(parts[0], years={y: v for p_ in parts for y, v in p_["years"].items()})
    res["years"] = dict(sorted(res["years"].items()))
    (OUT / f"{tag}.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def resolution_test(hours=2880, year=2019):
    """Same slice solved at 1-hour and 3-hour resolution: bias of the 3-hour blocks."""
    obs = observed()
    S = json.loads((OUT / "central.json").read_text())
    p = P(methane_aud_mwh=S["shadow_aud_mwh"]["methane"])
    L = loads_from_annual(S)
    out = {}
    for st in (1, 3):
        b, c, o, R, i, sy = build(obs, L, p, [year], step=st, hours=hours)
        t = time.time()
        b.solve()
        sm = summarise(b, c, o, R, i, sy, obs, p, [year], L)
        out[st] = dict(cost_bn=b.obj / 1e9, solve_s=time.time() - t, price_direct=sm["price_direct_aud_mwh"],
                       price_flex=sm["price_flex_aud_mwh"],
                       battery_gwh=sum(v["battery_gwh"] for v in sm["systems"].values()),
                       turbine_gw=sum(v["turbine_gw"] for v in sm["systems"].values()))
    return dict(hours=hours, year=year, results=out)


def main(tag="dispatch", **kw):
    R = run(**kw)
    (OUT / f"{tag}.json").write_text(json.dumps(R, indent=1, default=float))
    print(tag, "solved in", round(R["solve_s"]), "s; direct", round(R["design"]["price_direct_aud_mwh"], 1),
          "flex", round(R["design"]["price_flex_aud_mwh"], 1), "AUD/MWh")
    return R


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "topup1h":
        topup_1h([int(x) for x in sys.argv[3:]], sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "merge":
        merge_verify(sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "verify":
        yrs = [int(x) for x in sys.argv[3:]] or None
        verify(years=yrs, tag=sys.argv[2] if len(sys.argv) > 2 else "verify_hourly")
    elif len(sys.argv) > 1 and sys.argv[1] == "series":
        r = series()
        (OUT / "dispatch_series.json").write_text(json.dumps(r, indent=1, default=float))
        print("series", r["year"], r["start_utc"])
    elif len(sys.argv) > 1 and sys.argv[1] == "resolution":
        r = resolution_test()
        (OUT / "dispatch_resolution.json").write_text(json.dumps(r, indent=1, default=float))
        print(r)
    else:
        main(tag=sys.argv[1] if len(sys.argv) > 1 else "dispatch")
