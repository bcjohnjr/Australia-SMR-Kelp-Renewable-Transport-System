"""Least-cost fossil-free supply of all transport fuel sold in Australia (annual mixed-integer programme, scipy/HiGHS).

The programme is an annual energy-and-cost screening model: it balances annual energy, not hourly supply and demand.
Each highway catenary corridor is a yes/no build decision (binary variable carrying the whole corridor's annualised
capital cost); everything else is continuous. Shadow prices are taken from the linear programme re-solved with the
corridor decisions fixed at their optimal values.

Units: TWh/yr, km2, Mt; costs in AUD million (objective) and AUD billion (reports), AUD 2026, pre-tax.
Demand: 2025 sales (inputs.demand): cars and utes, trucks and buses, rail, mining (haulage and site power), farm and
  construction machinery, aviation including international flights, and shipping.
End uses: battery-electric; catenary-electric trucks on eight named highway corridors (each with its own traffic and
  cost, so the model chooses which highways to electrify); drop-in renewable diesel and petrol; renewable jet; ethanol
  (E100, ED95); methane, methanol and ammonia (not in the electric-or-biofuel case).
Electricity: new onshore wind and large-scale PV in three resource tiers each (GenCost 2025-26 capital costs), with
  firming and network adders for direct loads and cheaper adders for flexible loads (electrolysers, heat storage,
  air capture). Solar-led electrolysers run at a 30% capacity factor, wind-led ones at 50%.
SMRs: BWRX-300-class modules in three fleets that can sell electricity and 150 C extraction steam (0.19 MWh of
  electricity forgone per MWh): 'east' (NEM sites Loy Yang, Liddell, Mount Piper, Tarong, Callide), 'sa' (Port Augusta)
  and 'wa' (Muja). Steam is balanced in regional heat pools and reaches only a share of each pool's heat:
  SA (Spencer Gulf and Eyre kelp refineries; at most 60% beside Port Augusta), WA (WA kelp refineries at Bunbury,
  55 km of steam main from Muja; 70%), VIC (Bass Strait kelp refined beside Loy Yang; 100%), inland east (sorghum and
  cane ethanol distilleries; 30% beside a site), TAS and SE (no SMR site). Heat pumps (COP 2.8, at most 60% of a
  pool), solar- or wind-charged thermal storage and electric boilers serve every pool.
Fuels: native kelp (kelp.py; Great Southern Reef zones), cereal straw and sugarcane trash/bagasse, plantation
  residues, tallow and used cooking oil (HEFA), canola oil (HVO), sorghum, cane and molasses ethanol and
  alcohol-to-jet, landfill, manure and food-waste biomethane, electrofuels (Fischer-Tropsch, methanol, ammonia)
  with biogenic CO2 or direct air capture. No fossil energy is used.
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import copy
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog, milp, LinearConstraint, Bounds

import inputs as I
import kelp as K
import geo

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
OUT.mkdir(exist_ok=True)
CRF = I.CRF
POOLS = ("SA", "WA", "VIC", "TAS", "SE", "INLAND")
FLEETS = {"east": ("VIC", "INLAND"), "sa": ("SA",), "wa": ("WA",)}
FLEET_SITES = {"east": ("Loy Yang", "Liddell", "Mount Piper", "Tarong", "Callide"), "sa": ("Port Augusta",),
               "wa": ("Muja",)}

# segment -> option: (carrier, MWh carrier per MWh fossil replaced, max share, delivery AUD/MWh carrier, premium AUD/MWh fossil)
OPTIONS = {
    "ldv_petrol": {"bev": ("el", 0.27, 1.0, 0, 6), "liq": ("dropin", 1.0, 1.0, 22, 0), "e100": ("ethanol", 1.0, 1.0, 25, 2)},
    "ldv_diesel": {"bev": ("el", 0.30, 1.0, 0, 10), "liq": ("dropin", 1.0, 1.0, 22, 0)},
    "hdv": {"bet": ("el", 0.50, 0.85, 20, 25), "liq": ("dropin", 1.0, 1.0, 20, 0), "ed95": ("ethanol", 1.05, 0.30, 30, 8),
            "lng": ("methane", 1.15, 0.30, 45, 20)},
    "rail": {"el": ("el", 0.45, 0.50, 25, 15), "liq": ("dropin", 1.0, 1.0, 10, 0)},
    "mining": {"el": ("el", 0.40, 0.60, 30, 20), "liq": ("dropin", 1.0, 1.0, 15, 0)},
    "farm": {"el": ("el", 0.42, 0.30, 40, 30), "liq": ("dropin", 1.0, 1.0, 22, 0)},
    "construction": {"el": ("el", 0.45, 0.40, 35, 25), "liq": ("dropin", 1.0, 1.0, 22, 0)},
    "aviation": {"jet": ("jet", 1.0, 1.0, 8, 0)},
    "shipping": {"meoh": ("methanol", 1.0, 1.0, 8, 10), "nh3": ("ammonia", 1.05, 0.50, 12, 15),
                 "lng": ("methane", 1.0, 0.30, 30, 12), "liq": ("dropin", 1.0, 1.0, 8, 0)},
}
NON_EB = (("hdv", "lng"), ("shipping", "meoh"), ("shipping", "nh3"), ("shipping", "lng"))
ERS_RATIO, ERS_PREMIUM = 0.38, 12.0
SHORTFALL_PENALTY = 5000.0   # AUD/MWh; any unserved liquid fuel is reported, never hidden


CALIBRATION = Path(__file__).resolve().parent / "calibration.json"


def calibration():
    """Adders calibrated against the hourly model (calibrate.py); empty if not yet calibrated."""
    if CALIBRATION.exists():
        return json.loads(CALIBRATION.read_text()).get("annual_overrides", {})
    return {}


def base_params(calibrated=True):
    """Learning-target case (4% real): GenCost 2050 capital costs and learning in kelp, conversion and electrofuels.
    With calibrated=True the firming/network adders and electrolyser utilisation come from calibration.json."""
    p = _base_params()
    if calibrated:
        cal = calibration()
        p["adder"].update(cal.get("adder", {}))
        p["electrolyser"].update(cal.get("electrolyser", {}))
        p["h2_storage_aud_mwh_el"] = cal.get("h2_storage_aud_mwh_el", 0.0)
        p["wind_share"] = json.loads(CALIBRATION.read_text()).get("wind_share") if CALIBRATION.exists() else None
        p["turbine_ch4_twh"] = json.loads(CALIBRATION.read_text()).get("turbine_methane_twh", 0.0) if CALIBRATION.exists() else 0.0

    else:
        p["h2_storage_aud_mwh_el"] = 0.0
    return p


def _base_params():
    r = 0.04
    return dict(
        r=r,
        wind=dict(capex=I.GENCOST_CAPEX["wind"][2050], fom=28.0, cf=(0.42, 0.37, 0.32), cap_gw=(60, 150, 400), life=30),
        pv=dict(capex=I.GENCOST_CAPEX["solar"][2050], fom=14.0, cf=(0.30, 0.27, 0.24), cap_gw=(100, 300, 1000), life=30),
        adder=dict(wind_dir=18.0, pv_dir=10.0, pv_shift=32.0, net_dir=30.0, net_flex=6.0, pv_dir_share=0.35,
                   loss=0.05, flex_pv_share_wind_led=0.40),
        electrolyser=dict(capex=I.GENCOST_CAPEX["electrolyser_alk"][2050], om=0.02, life=25, cf_solar=0.30, cf_wind=0.50),
        eft=dict(el=2.40, synth=70.0, co2=0.30, jet_max=0.60),
        emeoh=dict(el=1.90, synth=45.0, co2=0.25),
        # synthetic methane (electrolysis + Sabatier methanation, ~78% H2->CH4 LHV): MWh el, AUD and t CO2 per MWh CH4
        emch4=dict(el=1.85, synth=40.0, co2=0.198),
        turbine_ch4_twh=0.0,        # methane burnt by the firming turbines of the hourly model (set by calibration)
        enh3=dict(el=1.75, synth=40.0),
        dac=dict(el=1.5, cost=500.0),
        bio_co2=dict(cost=60.0),
        heat=dict(hp_cop=2.8, hp_max=0.6, hp_cost=12.0, tes_eff=0.95, tes_cost=18.0, eb_cost=4.0),
        smr=dict(capex_kw=I.SMR["capex_kw_2050"], fom=I.SMR["fom"], var=I.SMR["vom"] + I.SMR["fuel"] + I.SMR["waste"],
                 avail=I.SMR["avail"], life=I.SMR["life"], steam_ratio=I.SMR["steam_max_mwth"] / I.SMR["mwe"],
                 forgone=I.SMR["steam_forgone"], max_gw={"east": 6.0, "sa": 1.2, "wa": 1.2},
                 enabled={"east": True, "sa": True, "wa": True}, fixed_gw=None),
        steam_delivery={"SA": 8.0, "WA": 14.0, "VIC": 16.0, "INLAND": 8.0},
        smr_share_max={"SA": 0.6, "WA": 0.7, "VIC": 1.0, "INLAND": 0.3, "TAS": 0.0, "SE": 0.0},
        kelp=dict(level="learning", scale=1.0, cost=K.KelpCost(), forced={}, enabled=True,
                  area_cap_km2=K.DEPLOYMENT_CAP_KM2),
        straw=dict(cap_mt=12.0, cost_odt=90.0, mwh_odt=2.2, conv=95.0, jet_max=0.50, co2_t_mwh=0.30),
        cane=dict(cap_mt=4.0, cost_odt=60.0, mwh_odt=2.3, conv=85.0, jet_max=0.40, co2_t_mwh=0.20),
        forest=dict(cap_mt=4.0, cost_odt=95.0, mwh_odt=2.4, conv=85.0, jet_max=0.40, co2_t_mwh=0.20),
        hefa=dict(cap=6.0, cost=205.0, jet_max=0.70),
        canola=dict(cap=12.0, cost=225.0, jet_max=0.70),
        etoh=dict(cap=8.0, cost=140.0, heat=0.34, co2=0.129),
        atj=dict(eff=0.925, cost=71.0),
        wch4=dict(cap=15.0, cost=85.0, co2=0.20),
        biomeoh=dict(ch4=1.5, cost=39.0),
        ers=dict(enabled=True, capex_m_km=I.CATENARY_AUD_M_PER_KM, life=I.CATENARY_LIFE, om=I.CATENARY_OM,
                 on_wire=I.ON_WIRE, force=(), corridors=list(I.CORRIDORS)),
        eb_only=False,
        reserve=dict(ch4_twh=0.0, turbine_gw=0.0, turbine_capex_kw=I.GENCOST_CAPEX["ocgt"][2050], turbine_fom=15.0,
                     storage_cost=3.0, eff=0.38),
        demand_mult={},
    )


def central_params():
    """Calibrated central case with the flexible and heat electricity loads held at the values the hourly fleet was
    verified on (calibration.json: el_load_fixed), so the reported annual solution and the hourly results use
    identical loads. Scenarios and sensitivity runs use base_params(), which leaves these loads free."""
    p = base_params()
    if CALIBRATION.exists():
        p["el_load_fixed"] = json.loads(CALIBRATION.read_text()).get("el_load_fixed")
    return p


def today_params():
    """Today's technology costs at 7% (GenCost 2025 capital costs, today's kelp and conversion costs)."""
    p = base_params()
    p["r"] = 0.07
    p["wind"]["capex"] = I.GENCOST_CAPEX["wind"][2025]
    p["pv"]["capex"] = I.GENCOST_CAPEX["solar"][2025]
    p["electrolyser"]["capex"] = I.GENCOST_CAPEX["electrolyser_alk"][2025]
    p["eft"]["synth"], p["emeoh"]["synth"], p["enh3"]["synth"] = 95.0, 60.0, 55.0
    p["emch4"]["synth"] = 55.0
    p["dac"]["cost"] = 800.0
    p["smr"]["capex_kw"] = I.SMR["capex_kw_today"]
    p["kelp"]["level"] = "design"
    p["kelp"]["cost"] = K.KelpCost(base_aud_t=575.0, depth_cycle_capex_km2=1.75e6, refinery_aud_t=330.0,
                                   exposure_learning=1.0, rate=0.07)
    p["adder"].update(pv_shift=55.0, wind_dir=22.0)
    if CALIBRATION.exists():   # same calibration shift on today's higher adders
        c = json.loads(CALIBRATION.read_text())
        m = c.get("firming_multiplier", 1.0)
        for k in ("pv_shift", "wind_dir"):
            p["adder"][k] = p["adder"][k] * m
    return p


def ers_corridors(p):
    km = geo.corridor_km()
    rows = {}
    for c in p["ers"]["corridors"]:
        d = I.CORRIDORS[c]
        kwh_km = d["l_km"] * I.KWH_PER_L["diesel"]
        twh = km[c] * d["aadt"] * 365 * kwh_km * p["ers"]["on_wire"] / 1e9
        ann_m = km[c] * p["ers"]["capex_m_km"] * (CRF(p["r"], p["ers"]["life"]) + p["ers"]["om"])
        rows[c] = dict(km=km[c], aadt=d["aadt"], twh_diesel=twh, ann_aud_m=ann_m, aud_per_mwh=ann_m / twh)
    return rows


class LP:
    def __init__(self):
        self.names, self.c, self.ub, self.lb, self.integer = [], [], [], [], []
        self.A_eq, self.b_eq, self.A_ub, self.b_ub = [], [], [], []
        self.eq_names, self.ub_names = [], []

    def var(self, name, cost=0.0, ub=None, binary=False, lb=0.0):
        self.names.append(name)
        self.c.append(cost)
        self.ub.append(1.0 if binary else ub)
        self.lb.append(lb)
        self.integer.append(1 if binary else 0)
        return len(self.names) - 1

    def eq(self, terms, rhs, name=None):
        self.A_eq.append(terms)
        self.b_eq.append(rhs)
        self.eq_names.append(name)

    def le(self, terms, rhs, name=None):
        self.A_ub.append(terms)
        self.b_ub.append(rhs)
        self.ub_names.append(name)

    def duals(self, res):
        d = {}
        for nm, m in zip(self.ub_names, res.ineqlin.marginals if self.A_ub else []):
            if nm:
                d[nm] = -float(m)
        for nm, m in zip(self.eq_names, res.eqlin.marginals if self.A_eq else []):
            if nm:
                d[nm] = -float(m)
        return d

    def solve(self):
        """MILP (if any binary variables), then the LP with binaries fixed, which gives the shadow prices."""
        n = len(self.names)

        def mat(rows):
            M = np.zeros((len(rows), n))
            for i, t in enumerate(rows):
                for j, v in t.items():
                    M[i, j] += v
            return M
        Aub = mat(self.A_ub) if self.A_ub else None
        Aeq = mat(self.A_eq) if self.A_eq else None
        lb = np.array(self.lb, float)
        ub = np.array([np.inf if u is None else u for u in self.ub], float)
        self.binary_values = {}
        if any(self.integer):
            cons = []
            if Aub is not None:
                cons.append(LinearConstraint(Aub, -np.inf, np.array(self.b_ub)))
            if Aeq is not None:
                cons.append(LinearConstraint(Aeq, np.array(self.b_eq), np.array(self.b_eq)))
            m = milp(np.array(self.c), constraints=cons, integrality=np.array(self.integer), bounds=Bounds(lb, ub),
                     options=dict(mip_rel_gap=1e-7))
            if m.status != 0:
                raise RuntimeError(m.message)
            for j, isint in enumerate(self.integer):
                if isint:
                    lb[j] = ub[j] = round(float(m.x[j]))
                    self.binary_values[self.names[j]] = int(lb[j])
        res = linprog(np.array(self.c), A_ub=Aub, b_ub=self.b_ub or None, A_eq=Aeq, b_eq=self.b_eq or None,
                      bounds=list(zip(lb, [None if np.isinf(u) else u for u in ub])), method="highs")
        if res.status != 0:
            raise RuntimeError(res.message)
        return res


def solve(p=None):
    p = copy.deepcopy(p or base_params())
    r = p["r"]
    lp = LP()
    v = {}
    D = I.demand()
    for s, m in p["demand_mult"].items():
        D[s] *= m
    T = {}   # carrier demand expressions: carrier -> {var: coef}

    def add(dct, key, j, coef):
        dct.setdefault(key, {})
        dct[key][j] = dct[key].get(j, 0.0) + coef

    # ---------------------------------------------------------------- end uses
    for s, opts in OPTIONS.items():
        seg = {}
        for o, (car, ratio, mx, deliv, prem) in opts.items():
            if p["eb_only"] and (s, o) in NON_EB:
                continue
            j = lp.var(f"u|{s}|{o}", cost=deliv * ratio + prem, ub=mx * D[s])
            v[("u", s, o)] = j
            seg[j] = 1.0
            add(T, car, j, ratio)
        if s == "hdv" and p["ers"]["enabled"]:
            for c, row in ers_corridors(p).items():
                force = c in p["ers"]["force"]
                y = lp.var(f"ers_build|{c}", cost=row["ann_aud_m"], binary=True, lb=1.0 if force else 0.0)
                j = lp.var(f"ers|{c}", cost=ERS_PREMIUM, ub=row["twh_diesel"])
                v[("ers", c)] = j
                v[("ers_build", c)] = y
                lp.le({j: 1.0, y: -row["twh_diesel"]}, 0.0)      # traffic on the wire only if the corridor is built
                seg[j] = 1.0
                add(T, "el", j, ERS_RATIO)
                if force:
                    lp.le({j: -1.0}, -row["twh_diesel"])
        lp.eq(seg, D[s])

    # ---------------------------------------------------------------- electricity
    a = p["adder"]
    W = [lp.var(f"wind{i}", cost=I.lcoe(p["wind"]["capex"], p["wind"]["fom"], cf, r, p["wind"]["life"]),
                ub=cap * cf * 8.76) for i, (cf, cap) in enumerate(zip(p["wind"]["cf"], p["wind"]["cap_gw"]))]
    P = [lp.var(f"pv{i}", cost=I.lcoe(p["pv"]["capex"], p["pv"]["fom"], cf, r, p["pv"]["life"]),
                ub=cap * cf * 8.76) for i, (cf, cap) in enumerate(zip(p["pv"]["cf"], p["pv"]["cap_gw"]))]
    w_dir = lp.var("w_dir", a["wind_dir"] + a["net_dir"])
    w_flex = lp.var("w_flex", a["net_flex"])
    p_dir = lp.var("p_dir", a["pv_dir"] + a["net_dir"])
    p_shift = lp.var("p_shift", a["pv_shift"] + a["net_dir"])
    p_flex_s = lp.var("p_flex_s", a["net_flex"])
    p_flex_w = lp.var("p_flex_w", a["net_flex"])
    lp.eq({**{j: 1.0 for j in W}, w_dir: -1.0, w_flex: -1.0}, 0.0)
    lp.eq({**{j: 1.0 for j in P}, p_dir: -1.0, p_shift: -1.0, p_flex_s: -1.0, p_flex_w: -1.0}, 0.0)
    if p.get("wind_share") is not None:   # generation mix held to the hourly model's (calibrate.py)
        sh_ = p["wind_share"]
        lp.eq({**{j: 1.0 - sh_ for j in W}, **{j: -sh_ for j in P}}, 0.0, "wind_share")

    # SMR fleets
    sm = p["smr"]
    smr_ann = sm["capex_kw"] * CRF(r, sm["life"]) + sm["fom"]          # AUD M per GW-yr
    full_twh = sm["avail"] * 8.76                                      # TWh per GW
    smr_gw, smr_el, steam = {}, {}, {}
    for f, pools in FLEETS.items():
        ub = sm["max_gw"][f] if sm["enabled"][f] else 0.0
        fixed = (sm["fixed_gw"] or {}).get(f) if sm["fixed_gw"] else None
        smr_gw[f] = lp.var(f"smr_gw|{f}", cost=smr_ann + sm["var"] * full_twh, ub=ub if fixed is None else fixed)
        if fixed is not None:
            lp.le({smr_gw[f]: -1.0}, -fixed)
        smr_el[f] = lp.var(f"smr_el|{f}", cost=a["net_dir"])
        terms = {smr_el[f]: 1.0, smr_gw[f]: -full_twh}
        cap_terms = {smr_gw[f]: -sm["steam_ratio"] * full_twh}
        for pl in pools:
            steam[(f, pl)] = lp.var(f"steam|{f}|{pl}", cost=p["steam_delivery"][pl])
            terms[steam[(f, pl)]] = sm["forgone"]
            cap_terms[steam[(f, pl)]] = 1.0
        lp.eq(terms, 0.0)
        lp.le(cap_terms, 0.0)

    # ---------------------------------------------------------------- heat pools
    heat_dem = {pl: {} for pl in POOLS}
    el_dir_extra, el_flex_s_extra = {}, {}
    # kelp
    kc = p["kelp"]
    ztab = K.zone_table(kc["level"], kc["cost"], kc["scale"])
    kv = {}
    kelp_out = {"hc": {}, "ch4": {}, "co2": {}}
    for z, row in ztab.items():
        if not kc["enabled"]:
            break
        t_km2 = row["dry_t_km2"] / 1e6        # Mt per km2
        cost = row["cost_aud_t"] * row["dry_t_km2"] / 1e6     # AUD M per km2
        j = lp.var(f"kelp|{z}", cost=cost, ub=min(row["area_km2"], kc.get("area_cap_km2") or 1e12))
        kv[z] = j
        if z in kc["forced"]:
            lp.le({j: -1.0}, -kc["forced"][z])
        add(heat_dem, row["pool"], j, K.HTL["heat_mwh"] * t_km2)      # TWh_th per km2 (Mt x MWh/t)
        el_dir_extra[j] = el_dir_extra.get(j, 0) + K.HTL["el_mwh"] * t_km2
        kelp_out["hc"][j] = K.HTL["hc_mwh"] * t_km2
        kelp_out["ch4"][j] = K.HTL["ch4_mwh"] * t_km2
        kelp_out["co2"][j] = K.HTL["co2_t"] * t_km2
    # residues (Mt odt) -> drop-in hydrocarbons
    res = {}
    for k in ("straw", "cane", "forest"):
        d = p[k]
        res[k] = lp.var(f"res|{k}", cost=d["cost_odt"] + d["conv"] * d["mwh_odt"], ub=d["cap_mt"])
    hefa = lp.var("hefa", p["hefa"]["cost"], p["hefa"]["cap"])
    canola = lp.var("canola", p["canola"]["cost"], p["canola"]["cap"])
    etoh = lp.var("etoh", p["etoh"]["cost"], p["etoh"]["cap"])
    add(heat_dem, "INLAND", etoh, p["etoh"]["heat"])
    atj = lp.var("atj", p["atj"]["cost"])
    wch4 = lp.var("wch4", p["wch4"]["cost"], p["wch4"]["cap"])
    biomeoh = lp.var("biomeoh", p["biomeoh"]["cost"])
    # electrofuels
    el_cost = lambda cf: (p["electrolyser"]["capex"] * (CRF(r, p["electrolyser"]["life"]) + p["electrolyser"]["om"]) / (cf * 8.76)
                          + p.get("h2_storage_aud_mwh_el", 0.0))
    ec_s, ec_w = el_cost(p["electrolyser"]["cf_solar"]), el_cost(p["electrolyser"]["cf_wind"])
    allow_e = not p["eb_only"]
    eft_s = lp.var("eft_s", p["eft"]["el"] * ec_s + p["eft"]["synth"], None if allow_e else 0.0)
    eft_w = lp.var("eft_w", p["eft"]["el"] * ec_w + p["eft"]["synth"], None if allow_e else 0.0)
    emeoh = lp.var("emeoh", p["emeoh"]["el"] * ec_w + p["emeoh"]["synth"], None if allow_e else 0.0)
    enh3 = lp.var("enh3", p["enh3"]["el"] * ec_w + p["enh3"]["synth"], None if allow_e else 0.0)
    emch4 = lp.var("emch4", p["emch4"]["el"] * ec_w + p["emch4"]["synth"], None if allow_e else 0.0)
    dac = lp.var("dac", p["dac"]["cost"])
    bco2 = lp.var("bio_co2", p["bio_co2"]["cost"])

    # hydrocarbon sources and jet allocation
    hc_src = {"kelp": kelp_out["hc"],
              "straw": {res["straw"]: p["straw"]["mwh_odt"]}, "cane": {res["cane"]: p["cane"]["mwh_odt"]},
              "forest": {res["forest"]: p["forest"]["mwh_odt"]}, "hefa": {hefa: 1.0}, "canola": {canola: 1.0},
              "eft_s": {eft_s: 1.0}, "eft_w": {eft_w: 1.0}}
    jet_max = {"kelp": K.HTL["jet_max"], "straw": p["straw"]["jet_max"], "cane": p["cane"]["jet_max"],
               "forest": p["forest"]["jet_max"], "hefa": p["hefa"]["jet_max"], "canola": p["canola"]["jet_max"],
               "eft_s": p["eft"]["jet_max"], "eft_w": p["eft"]["jet_max"]}
    jet_v = {}
    for k, expr in hc_src.items():
        jet_v[k] = lp.var(f"jet|{k}")
        lp.le({jet_v[k]: 1.0, **{j: -jet_max[k] * c for j, c in expr.items()}}, 0.0)
    # drop-in balance: sum hc - jet >= dropin demand
    terms = {}
    for k, expr in hc_src.items():
        for j, c in expr.items():
            terms[j] = terms.get(j, 0) - c
        terms[jet_v[k]] = terms.get(jet_v[k], 0) + 1.0
    for j, c in T.get("dropin", {}).items():
        terms[j] = terms.get(j, 0) + c
    short_d = lp.var("shortfall|dropin", SHORTFALL_PENALTY)
    terms[short_d] = -1.0
    lp.le(terms, 0.0, "dropin")
    # jet balance
    short_j = lp.var("shortfall|jet", SHORTFALL_PENALTY)
    terms = {jet_v[k]: -1.0 for k in jet_v}
    terms[short_j] = -1.0
    terms[atj] = -1.0
    for j, c in T.get("jet", {}).items():
        terms[j] = terms.get(j, 0) + c
    lp.le(terms, 0.0, "jet")
    # ethanol
    terms = {etoh: -1.0, atj: 1.0 / p["atj"]["eff"]}
    for j, c in T.get("ethanol", {}).items():
        terms[j] = terms.get(j, 0) + c
    lp.le(terms, 0.0)
    # methane (incl. reserve)
    terms = {wch4: -1.0, emch4: -1.0, biomeoh: p["biomeoh"]["ch4"], **{j: -c for j, c in kelp_out["ch4"].items()}}
    for j, c in T.get("methane", {}).items():
        terms[j] = terms.get(j, 0) + c
    # firming turbines of the hourly model burn renewable methane: a fixed demand in the national methane balance
    lp.le(terms, -p["reserve"]["ch4_twh"] - p.get("turbine_ch4_twh", 0.0), "methane")
    # methanol, ammonia
    terms = {emeoh: -1.0, biomeoh: -1.0}
    for j, c in T.get("methanol", {}).items():
        terms[j] = terms.get(j, 0) + c
    lp.le(terms, 0.0)
    terms = {enh3: -1.0}
    for j, c in T.get("ammonia", {}).items():
        terms[j] = terms.get(j, 0) + c
    lp.le(terms, 0.0)
    # CO2 (Mt): use <= biogenic captured + DAC; biogenic captured <= available
    lp.le({eft_s: p["eft"]["co2"], eft_w: p["eft"]["co2"], emeoh: p["emeoh"]["co2"], emch4: p["emch4"]["co2"],
           bco2: -1.0, dac: -1.0}, 0.0)
    terms = {bco2: 1.0, etoh: -p["etoh"]["co2"], wch4: -p["wch4"]["co2"],
             **{j: -c for j, c in kelp_out["co2"].items()}}
    for k in ("straw", "cane", "forest"):
        terms[res[k]] = -p[k]["co2_t_mwh"] * p[k]["mwh_odt"]
    lp.le(terms, 0.0)

    # heat supply per pool
    h = p["heat"]
    hp, tes, eb = {}, {}, {}
    for pl in POOLS:
        hp[pl] = lp.var(f"hp|{pl}", h["hp_cost"])
        tes[pl] = lp.var(f"tes|{pl}", h["tes_cost"])
        eb[pl] = lp.var(f"eb|{pl}", h["eb_cost"])
        terms = {hp[pl]: -1.0, tes[pl]: -1.0, eb[pl]: -1.0}
        for (f, pp), j in steam.items():
            if pp == pl:
                terms[j] = -1.0
        for j, c in heat_dem[pl].items():
            terms[j] = terms.get(j, 0) + c
        lp.le(terms, 0.0, f"heat|{pl}")
        lp.le({hp[pl]: 1.0, **{j: -h["hp_max"] * c for j, c in heat_dem[pl].items()}}, 0.0)
        st = {j: 1.0 for (f, pp), j in steam.items() if pp == pl}
        if st:
            lp.le({**st, **{j: -p["smr_share_max"][pl] * c for j, c in heat_dem[pl].items()}}, 0.0)
        el_dir_extra[hp[pl]] = 1.0 / h["hp_cop"]
        el_dir_extra[eb[pl]] = 1.0
        el_flex_s_extra[tes[pl]] = 1.0 / h["tes_eff"]

    # electricity balances
    loss = 1 + a["loss"]
    terms = {w_dir: -1.0, p_dir: -1.0, p_shift: -1.0, **{smr_el[f]: -1.0 for f in FLEETS}}
    for j, c in T.get("el", {}).items():
        terms[j] = terms.get(j, 0) + c * loss
    for j, c in el_dir_extra.items():
        terms[j] = terms.get(j, 0) + c * loss
    lp.eq(terms, 0.0, "el_direct")
    dir_load = {**{j: c for j, c in T.get("el", {}).items()}}
    for j, c in el_dir_extra.items():
        dir_load[j] = dir_load.get(j, 0) + c
    lp.le({p_dir: 1.0, **{j: -a["pv_dir_share"] * c * loss for j, c in dir_load.items()}}, 0.0)
    # solar-led flexible: solar e-FT, heat storage, DAC
    terms = {p_flex_s: -1.0, eft_s: p["eft"]["el"] * loss, dac: p["dac"]["el"] * loss}
    for j, c in el_flex_s_extra.items():
        terms[j] = terms.get(j, 0) + c * loss
    lp.eq(terms, 0.0, "el_flex_solar")
    # wind-led flexible: wind e-FT, e-methanol, e-ammonia (up to 40% solar)
    wl = {eft_w: p["eft"]["el"] * loss, emeoh: p["emeoh"]["el"] * loss, enh3: p["enh3"]["el"] * loss,
          emch4: p["emch4"]["el"] * loss}
    lp.eq({w_flex: -1.0, p_flex_w: -1.0, **wl}, 0.0, "el_flex_wind")
    lp.le({p_flex_w: 1.0, **{j: -a["flex_pv_share_wind_led"] * c for j, c in wl.items()}}, 0.0)

    # hold the flexible and heat electricity loads at the values the hourly fleet was verified on (set after the last
    # hourly run), so that closing the methane balance cannot alter the hourly model's loads
    lc = p.get("el_load_fixed")
    if lc:
        ef = {eft_s: p["eft"]["el"], eft_w: p["eft"]["el"], emeoh: p["emeoh"]["el"], enh3: p["enh3"]["el"],
              emch4: p["emch4"]["el"]}
        for nm, terms in (("efuels", ef), ("dac", {dac: p["dac"]["el"]}), ("refineries_heat", dict(el_dir_extra)),
                          ("heat_storage", dict(el_flex_s_extra))):
            if nm in lc and terms:
                lp.eq(terms, lc[nm], "el_load_" + nm)

    # winter reserve turbines (fixed capacity cost; fuel balance in the methane constraint)
    rs = p["reserve"]
    reserve_cost = (rs["turbine_gw"] * (rs["turbine_capex_kw"] * CRF(r, 30) + rs["turbine_fom"])
                    + rs["ch4_twh"] * rs["storage_cost"])

    res_lp = lp.solve()
    x = res_lp.x
    val = lambda j: float(x[j])
    S = dict(params_r=r, objective_bn=(res_lp.fun + reserve_cost) / 1000, reserve_cost_bn=reserve_cost / 1000)
    S["shortfall_twh"] = dict(dropin=val(short_d), jet=val(short_j))
    S["shadow_aud_mwh"] = lp.duals(res_lp)
    S["shortfall_total_twh"] = val(short_d) + val(short_j)
    S["objective_bn"] -= SHORTFALL_PENALTY * S["shortfall_total_twh"] / 1000   # cost of the supplied part only
    S["demand_twh"] = D
    S["demand_total_twh"] = sum(D.values())
    S["end_use_twh"] = {f"{s}|{o}": val(j) for (t, s, o), j in ((k, j) for k, j in v.items() if k[0] == "u")} \
        if False else {f"{k[1]}|{k[2]}": val(j) for k, j in v.items() if k[0] == "u"}
    S["ers_twh"] = {k[1]: val(j) for k, j in v.items() if k[0] == "ers"}
    S["ers_corridors"] = ers_corridors(p) if p["ers"]["enabled"] else {}
    S["ers_built"] = {k[1]: int(round(val(j))) for k, j in v.items() if k[0] == "ers_build"}
    S["ers_km_electrified"] = sum(S["ers_corridors"][c]["km"] for c, b in S["ers_built"].items() if b)
    S["ers_utilisation"] = {c: (S["ers_twh"][c] / S["ers_corridors"][c]["twh_diesel"]) if b else 0.0
                            for c, b in S["ers_built"].items()}
    S["ers_cost_bn"] = sum(S["ers_corridors"][c]["ann_aud_m"] for c, b in S["ers_built"].items() if b) / 1000
    S["vehicle_premium_bn"] = sum(val(j) * OPTIONS[k[1]][k[2]][4] for k, j in v.items() if k[0] == "u") / 1000 + \
        sum(val(j) * ERS_PREMIUM for k, j in v.items() if k[0] == "ers") / 1000
    S["wind_twh"] = [val(j) for j in W]
    S["pv_twh"] = [val(j) for j in P]
    S["wind_gw"] = sum(val(j) / (cf * 8.76) for j, cf in zip(W, p["wind"]["cf"]))
    S["pv_gw"] = sum(val(j) / (cf * 8.76) for j, cf in zip(P, p["pv"]["cf"]))
    el_vars = list(W) + list(P) + [w_dir, w_flex, p_dir, p_shift, p_flex_s, p_flex_w]
    S["electricity_supply_cost_bn"] = sum(lp.c[j] * val(j) for j in el_vars) / 1000
    S["el_flows_twh"] = dict(wind_direct=val(w_dir), wind_flex=val(w_flex), pv_direct=val(p_dir),
                             pv_shifted=val(p_shift), pv_flex_solar_led=val(p_flex_s), pv_flex_wind_led=val(p_flex_w))
    S["smr"] = {f: dict(gw=val(smr_gw[f]), modules=val(smr_gw[f]) / 0.3, el_twh=val(smr_el[f]),
                        steam_twh={pl: val(steam[(f, pl)]) for pl in FLEETS[f]}) for f in FLEETS}
    S["smr_gw_total"] = sum(d["gw"] for d in S["smr"].values())
    S["heat_by_pool"] = {}
    for pl in POOLS:
        dem = sum(c * val(j) for j, c in heat_dem[pl].items())
        S["heat_by_pool"][pl] = dict(demand=dem, hp=val(hp[pl]), tes=val(tes[pl]), eb=val(eb[pl]),
                                     smr=sum(val(j) for (f, pp), j in steam.items() if pp == pl))
    S["kelp_km2"] = {z: val(j) for z, j in kv.items()}
    S["kelp_total_km2"] = sum(S["kelp_km2"].values())
    S["kelp_dry_mt"] = sum(ztab[z]["dry_t_km2"] * a_ / 1e6 for z, a_ in S["kelp_km2"].items())
    S["kelp_wet_mt"] = S["kelp_dry_mt"] / p["kelp"]["cost"].dm
    S["kelp_n_kt"] = sum(ztab[z]["n_kg_km2"] * a_ for z, a_ in S["kelp_km2"].items()) / 1e6
    S["kelp_n_supply_kt"] = {src: sum(ztab[z]["n_kg_km2"] * a_ * ztab[z][key] for z, a_ in S["kelp_km2"].items()) / 1e6
                             for src, key in (("natural", "natural_share"), ("fish_farms", "imta_share"))}
    S["kelp_n_supply_kt"]["depth_cycling"] = S["kelp_n_kt"] - sum(S["kelp_n_supply_kt"].values())
    S["kelp_cost_bn"] = sum(ztab[z]["cost_aud_t"] * ztab[z]["dry_t_km2"] * a_ for z, a_ in S["kelp_km2"].items()) / 1e9
    S["kelp_zone_table"] = {z: {k: v_ for k, v_ in r_.items() if k != "parts"} for z, r_ in ztab.items()}
    hc = lambda k: sum(c * val(j) for j, c in hc_src[k].items())
    S["fuels_twh"] = {"kelp_hc": hc("kelp"), "straw_ft": hc("straw"), "cane_htl": hc("cane"), "forest_htl": hc("forest"),
                      "hefa": hc("hefa"), "canola_hvo": hc("canola"), "efuel_ft_solar": hc("eft_s"),
                      "efuel_ft_wind": hc("eft_w"), "ethanol": val(etoh), "alcohol_to_jet": val(atj),
                      "waste_biomethane": val(wch4), "kelp_methane": sum(c * val(j) for j, c in kelp_out["ch4"].items()),
                      "e_methanol": val(emeoh), "bio_methanol": val(biomeoh), "e_ammonia": val(enh3),
                      "e_methane": val(emch4)}
    S["methane_balance_twh"] = dict(
        waste_biomethane=val(wch4), kelp_methane=S["fuels_twh"]["kelp_methane"], e_methane=val(emch4),
        transport=sum(c * val(j) for j, c in T.get("methane", {}).items()), bio_methanol=p["biomeoh"]["ch4"] * val(biomeoh),
        turbines=p.get("turbine_ch4_twh", 0.0), reserve=p["reserve"]["ch4_twh"])
    S["jet_by_source_twh"] = {k: val(j) for k, j in jet_v.items()}
    S["jet_by_source_twh"]["atj"] = val(atj)
    S["residues_mt"] = {k: val(j) for k, j in res.items()}
    S["co2_mt"] = dict(biogenic=val(bco2), dac=val(dac))
    el_efuels = (p["eft"]["el"] * (val(eft_s) + val(eft_w)) + p["emeoh"]["el"] * val(emeoh) + p["enh3"]["el"] * val(enh3)
                 + p["emch4"]["el"] * val(emch4))
    S["electrolyser_gw"] = (p["eft"]["el"] * val(eft_s) / (p["electrolyser"]["cf_solar"] * 8.76)
                            + (p["eft"]["el"] * val(eft_w) + p["emeoh"]["el"] * val(emeoh) + p["enh3"]["el"] * val(enh3)
                               + p["emch4"]["el"] * val(emch4)) / (p["electrolyser"]["cf_wind"] * 8.76))
    S["electrolyser_cost_bn"] = (p["eft"]["el"] * val(eft_s) * ec_s + (p["eft"]["el"] * val(eft_w) + p["emeoh"]["el"]
                                 * val(emeoh) + p["enh3"]["el"] * val(enh3) + p["emch4"]["el"] * val(emch4)) * ec_w) / 1000
    S["h2_mt"] = el_efuels / 52.0          # 52 MWh of electricity per tonne of H2 (screening)
    S["electricity_twh"] = dict(
        vehicles_rail=sum(c * val(j) for j, c in T.get("el", {}).items()),
        refineries_heat=sum(c * val(j) for j, c in el_dir_extra.items()),
        efuels=el_efuels, dac=p["dac"]["el"] * val(dac),
        heat_storage=sum(c * val(j) for j, c in el_flex_s_extra.items()))
    S["generation_twh"] = dict(wind=sum(S["wind_twh"]), pv=sum(S["pv_twh"]),
                               smr=sum(d["el_twh"] for d in S["smr"].values()))
    S["generation_total_twh"] = sum(S["generation_twh"].values())
    S["carrier_twh"] = {car: sum(c * val(j) for j, c in d.items()) for car, d in T.items()}
    # costs and emissions
    S["fossil_cost_bn"] = {per: sum(I.fossil_price(s, per) * D[s] for s in D) / 1000 for per in ("avg2025", "oct2026")}
    S["fossil_wtw_mt"] = sum(I.co2_t_per_mwh(s) * D[s] for s in D)
    S["fossil_scope1_mt"] = sum(I.co2_t_per_mwh(s, "s1") * D[s] for s in D)
    S["names"] = {lp.names[i]: float(x[i]) for i in range(len(x)) if abs(x[i]) > 1e-9}
    S["dual_note"] = "objective in AUD bn includes vehicle premia and any winter reserve"
    S["lca_params"] = {**LCA_DEFAULTS, **p.get("lca", {})}
    S["residual_wtw_mt"], S["residual_parts_mt"] = residual_emissions(S, breakdown=True)
    S["residual_range_mt"] = dict(lo=residual_emissions(S, bound="lo"), hi=residual_emissions(S, bound="hi", ch4_leak=0.03))
    S["efuel_intensity"] = efuel_intensity(S)
    S["wtw_reduction_pct"] = 100 * (1 - S["residual_wtw_mt"] / S["fossil_wtw_mt"])
    return S


# Energy-supply life-cycle factors (t CO2-e per MWh delivered; g CO2-e/MJ x 0.0036). The boundary is the energy
# supply chain (feedstock, conversion, delivery, combustion of biogenic carbon counted as zero); vehicles, catenary,
# batteries and other end-use infrastructure are outside it. Electricity is counted once, at generation, so the
# factors of electrofuels, air capture and heat cover only plant construction and operation: their electricity
# share is endogenous (see efuel_intensity). 'iluc' is the CORSIA induced land-use-change value, applied in full in
# the central case and scaled in sensitivity; methane leakage is added separately (ch4_leak).
GMJ = 0.0036
LCA = {
    "wind": dict(core=0.012, iluc=0.0, lo=0.007, hi=0.020, src="NREL LCA Harmonization, onshore wind median ~13 g/kWh"),
    "pv": dict(core=0.035, iluc=0.0, lo=0.020, hi=0.050, src="NREL LCA Harmonization, c-Si PV (~43 g/kWh historical); 2020s modules lower"),
    "smr": dict(core=0.012, iluc=0.0, lo=0.004, hi=0.030, src="NREL LCA Harmonization, nuclear median ~13 g/kWh"),
    "hefa": dict(core=18.2 * GMJ, iluc=0.0, lo=13.9 * GMJ, hi=22.5 * GMJ, src="CORSIA default values (ICAO doc 06, 2025): UCO 13.9, tallow 22.5 g/MJ; 50:50 mix"),
    "canola_hvo": dict(core=47.4 * GMJ, iluc=26.0 * GMJ, lo=47.4 * GMJ, hi=(47.4 + 26.0) * GMJ, src="CORSIA rapeseed/canola HEFA core 47.4 + ILUC 26.0 g/MJ"),
    "straw_ft": dict(core=7.7 * GMJ, iluc=0.0, lo=5.0 * GMJ, hi=15.0 * GMJ, src="CORSIA FT agricultural residues 7.7 g/MJ"),
    "cane_htl": dict(core=7.7 * GMJ, iluc=0.0, lo=5.0 * GMJ, hi=20.0 * GMJ, src="no CORSIA HTL value; FT agricultural residues 7.7 g/MJ used"),
    "forest_htl": dict(core=8.3 * GMJ, iluc=0.0, lo=5.0 * GMJ, hi=20.0 * GMJ, src="CORSIA FT forestry residues 8.3 g/MJ (HTL assumed similar)"),
    "kelp_hc": dict(core=0.035, iluc=0.0, lo=0.020, hi=0.080, src="screening: no standard value; farm materials, vessels and hydrotreating H2, process heat and power counted in the model"),
    "ethanol": dict(core=25.0 * GMJ, iluc=15.0 * GMJ, lo=20.0 * GMJ, hi=(40.0 + 25.1) * GMJ, src="CORSIA ETJ sugarcane core 24.1, ILUC 8.5-8.7; corn grain ILUC 25.1; sorghum/cane mix, distillery heat renewable in the model"),
    "alcohol_to_jet": dict(core=5.0 * GMJ, iluc=0.0, lo=3.0 * GMJ, hi=10.0 * GMJ, src="conversion step only (ethanol counted under ethanol)"),
    "waste_biomethane": dict(core=0.010, iluc=0.0, lo=0.005, hi=0.020, src="upgrading and compression; avoided landfill/manure methane not credited; leakage added separately"),
    "kelp_methane": dict(core=0.010, iluc=0.0, lo=0.005, hi=0.020, src="as biomethane; leakage added separately"),
    "efuel_ft_solar": dict(core=0.005, iluc=0.0, lo=0.003, hi=0.010, src="plant only; electricity counted at generation"),
    "efuel_ft_wind": dict(core=0.005, iluc=0.0, lo=0.003, hi=0.010, src="plant only; electricity counted at generation"),
    "e_methanol": dict(core=0.005, iluc=0.0, lo=0.003, hi=0.010, src="plant only; electricity counted at generation"),
    "e_methane": dict(core=0.005, iluc=0.0, lo=0.003, hi=0.010, src="methanation plant only; electricity counted at generation; leakage added separately"),
    "bio_methanol": dict(core=0.010, iluc=0.0, lo=0.005, hi=0.020, src="reforming of biomethane; leakage counted on the methane"),
    "e_ammonia": dict(core=0.005, iluc=0.0, lo=0.003, hi=0.060, src="plant only; high end adds engine N2O slip (uncertain)"),
}
CH4_KT_PER_TWH = 3.6e9 / 50.0 / 1e6     # kt CH4 per TWh (LHV 50 MJ/kg)
GWP_CH4_BIO = 27.0                      # AR6 GWP100, non-fossil methane
LCA_DEFAULTS = dict(iluc_mult=1.0, ch4_leak=0.01, bound="core")


def residual_emissions(S, iluc_mult=None, ch4_leak=None, bound=None, breakdown=False):
    """Energy-supply life-cycle emissions of the replacement system, Mt CO2-e/yr."""
    q = {**LCA_DEFAULTS, **S.get("lca_params", {})}
    iluc_mult = q["iluc_mult"] if iluc_mult is None else iluc_mult
    ch4_leak = q["ch4_leak"] if ch4_leak is None else ch4_leak
    bound = q["bound"] if bound is None else bound
    f = lambda k: LCA[k][bound] + (iluc_mult * LCA[k]["iluc"] if bound == "core" else (LCA[k]["iluc"] if bound == "hi" else 0.0))
    g = S["generation_twh"]
    parts = {k: f(k) * g[k] for k in ("wind", "pv", "smr")}
    for k, t in S["fuels_twh"].items():
        parts[k] = f(k) * t
    ch4 = S["fuels_twh"]["waste_biomethane"] + S["fuels_twh"]["kelp_methane"] + S["fuels_twh"].get("e_methane", 0.0)
    parts["methane_leakage"] = ch4_leak * ch4 * CH4_KT_PER_TWH * GWP_CH4_BIO / 1000
    tot = sum(parts.values())
    return (tot, parts) if breakdown else tot


def efuel_intensity(S):
    """Endogenous life-cycle intensity of electrofuels (t CO2-e/MWh fuel): grid-mix electricity plus plant."""
    g = S["generation_twh"]
    grid = (LCA["wind"]["core"] * g["wind"] + LCA["pv"]["core"] * g["pv"] + LCA["smr"]["core"] * g["smr"]) / max(sum(g.values()), 1e-9)
    return dict(grid_t_mwh=grid, ft=2.40 * grid + LCA["efuel_ft_wind"]["core"], methanol=1.90 * grid + LCA["e_methanol"]["core"],
                ammonia=1.75 * grid + LCA["e_ammonia"]["core"])


if __name__ == "__main__":
    S = solve()
    keep = {k: S[k] for k in ("objective_bn", "vehicle_premium_bn", "demand_total_twh", "kelp_total_km2", "kelp_dry_mt",
                              "smr_gw_total", "wind_gw", "pv_gw", "generation_twh", "fuels_twh", "fossil_cost_bn",
                              "wtw_reduction_pct", "ers_twh", "kelp_km2", "electricity_twh", "electrolyser_gw",
                              "heat_by_pool", "carrier_twh", "end_use_twh")}
    print(json.dumps(keep, indent=1, default=float))
