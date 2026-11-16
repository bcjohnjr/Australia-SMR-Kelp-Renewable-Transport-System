"""Aquafeed from inland Australia with cross-species exchange of seafood by-product meals (least-cost LP).

A nutritional screening feasibility model: it tests whether diets meeting stated nutrient minima exist at what cost
and land; it does not show that such diets maintain growth, health, product quality or feed conversion on farms,
which needs feeding trials. Four farmed species are fed: Atlantic salmon (Tasmania), black tiger and banana prawns
(Queensland ponds and the southern heat-cascade RAS hubs), barramundi and yellowtail kingfish (Spencer Gulf). Each
diet must meet minimum crude protein, lipid, EPA+DHA, total lysine and total methionine contents (NRC 2011-based
screening values; crystalline L-lysine HCl and DL-methionine are allowed) and a binder (wheat) share, within
ingredient inclusion limits. Digestibility, other essential amino acids, minerals, palatability and extrusion
constraints are not modelled.

Inland crops: lupin kernel meal (WA wheatbelt), canola meal and oil (SA, Victoria, NSW, WA), omega-3 (DHA) canola oil
(the Australian-developed Aquaterra/DHA canola), faba-bean protein concentrate, wheat gluten and wheat. Other feeds:
poultry by-product meal (already ~18% of Skretting Australia's 2022 feed), tuna by-product hydrolysate, black
soldier fly meal grown on food waste, Novacq (a marine microbial biomass grown in prawn-farm ponds, prawns only),
algal DHA oil fermented from Queensland cane sugar, kelp meal from the Tasmanian farms, and single-cell protein made
by hydrogen-oxidising bacteria with inland solar electrolysis (25 MWh of electricity per tonne).

Cross-species swap: processing by-products of each farmed species (heads, frames, viscera, shells) are rendered to
meal and oil and may be fed to the OTHER species but never to their own (intraspecies recycling is prohibited in
the EU, Regulation (EC) No 1069/2009 Art. 11(1)(d), an export-market requirement, and is avoided as a disease-transfer
risk). Mortalities are excluded. Wild fishmeal and fish oil (imported) are allowed unless the case is 'fish-free'.

Land: hectares implied by each crop ingredient at average Australian yields (lupin 1.3 t seed/ha and 75% kernel;
canola 1.6 t seed/ha giving 0.67 t oil and 0.93 t meal; DHA canola 0.60 t oil/ha; faba 2.0 t/ha and 33% protein
concentrate; wheat 2.5 t/ha and 10% gluten). All parameters are screening values (table S12).
"""
import json
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

OUT = Path(__file__).resolve().parent / "outputs"
SPECIES = ("salmon", "prawn", "barramundi", "kingfish")
PRODUCTION_T = {"2025": {"salmon": 80000, "prawn": 10500, "barramundi": 10000, "kingfish": 4000},
                "2050": {"salmon": 90000, "prawn": 40000, "barramundi": 30000, "kingfish": 12000}}
FCR = {"salmon": 1.30, "prawn": 1.60, "barramundi": 1.50, "kingfish": 1.60}
SPEC = {   # minimum crude protein, lipid, EPA+DHA and binder (fractions of feed)
    "salmon": dict(cp=0.40, lipid=0.30, epadha=0.010, binder=0.08, lys=0.024, met=0.0070),
    "prawn": dict(cp=0.38, lipid=0.07, epadha=0.005, binder=0.15, lys=0.021, met=0.0070),
    "barramundi": dict(cp=0.45, lipid=0.14, epadha=0.008, binder=0.08, lys=0.023, met=0.0080),
    "kingfish": dict(cp=0.47, lipid=0.18, epadha=0.012, binder=0.08, lys=0.025, met=0.0080),
}
BYPRODUCT_T_PER_T = {   # rendered meal and oil per t live weight
    "salmon": {"meal": 0.085, "oil": 0.050}, "prawn": {"meal": 0.045, "oil": 0.0},
    "barramundi": {"meal": 0.100, "oil": 0.020}, "kingfish": {"meal": 0.100, "oil": 0.025}}
PREMIX = 0.02
PREMIX_COST = 3500.0
SCP_MWH_T, SCP_POWER_AUD, SCP_OTHER_AUD = 25.0, 45.0, 1800.0

# name: (cp, lipid, epadha, AUD/t, max inclusion, group, crop t/ha or None, availability t or None, origin species)
ING = {
    "wild fishmeal": (0.65, 0.09, 0.015, 2900, 0.30, "wild", None, None, None),
    "wild fish oil": (0.00, 1.00, 0.180, 6500, 0.15, "wild", None, None, None),
    "salmon meal": (0.58, 0.12, 0.010, 1800, 0.25, "byproduct", None, "meal", "salmon"),
    "salmon oil": (0.00, 1.00, 0.080, 3200, 0.20, "byproduct", None, "oil", "salmon"),
    "prawn meal": (0.45, 0.06, 0.008, 1600, 0.15, "byproduct", None, "meal", "prawn"),
    "barramundi meal": (0.56, 0.11, 0.008, 1800, 0.25, "byproduct", None, "meal", "barramundi"),
    "barramundi oil": (0.00, 1.00, 0.060, 3000, 0.15, "byproduct", None, "oil", "barramundi"),
    "kingfish meal": (0.58, 0.12, 0.010, 1800, 0.25, "byproduct", None, "meal", "kingfish"),
    "kingfish oil": (0.00, 1.00, 0.080, 3200, 0.15, "byproduct", None, "oil", "kingfish"),
    "tuna hydrolysate": (0.75, 0.08, 0.020, 2600, 0.10, "byproduct", None, 2000.0, None),
    "poultry meal": (0.65, 0.12, 0.000, 1300, 0.25, "land animal", None, 120000.0, None),
    "lupin kernel meal": (0.50, 0.06, 0.000, 900, 0.25, "inland crop", 0.98, None, None),
    "canola meal": (0.36, 0.08, 0.000, 450, 0.15, "inland crop", 0.93, None, None),
    "canola oil": (0.00, 1.00, 0.000, 1700, 0.20, "inland crop", 0.67, None, None),
    "DHA canola oil": (0.00, 1.00, 0.100, 5000, 0.15, "inland crop", 0.60, None, None),
    "faba protein concentrate": (0.60, 0.03, 0.000, 1400, 0.20, "inland crop", 0.65, None, None),
    "wheat gluten": (0.75, 0.01, 0.000, 2200, 0.15, "inland crop", 0.25, None, None),
    "wheat": (0.12, 0.02, 0.000, 380, 0.30, "inland crop", 2.50, None, None),
    "solar single-cell protein": (0.65, 0.06, 0.000, SCP_MWH_T * SCP_POWER_AUD + SCP_OTHER_AUD, 0.25, "inland solar", None, None, None),
    "Novacq": (0.35, 0.03, 0.002, 3000, 0.10, "microbial", None, None, None),
    "insect meal (BSF)": (0.50, 0.15, 0.001, 2600, 0.15, "insect", None, 30000.0, None),
    "algal DHA oil": (0.00, 1.00, 0.450, 12000, 0.05, "microbial", None, None, None),
    "kelp meal": (0.10, 0.01, 0.0005, 900, 0.03, "kelp", None, 20000.0, None),
    "L-lysine HCl": (0.00, 0.00, 0.000, 2200, 0.015, "amino acid", None, None, None),
    "DL-methionine": (0.00, 0.00, 0.000, 4800, 0.010, "amino acid", None, None, None),
}
# total lysine and methionine, fraction of ingredient (screening, NRC 2011 and supplier tables)
AA = {"wild fishmeal": (0.049, 0.018), "salmon meal": (0.043, 0.016), "prawn meal": (0.026, 0.009),
      "barramundi meal": (0.042, 0.015), "kingfish meal": (0.043, 0.016), "tuna hydrolysate": (0.055, 0.020),
      "poultry meal": (0.037, 0.012), "lupin kernel meal": (0.023, 0.0035), "canola meal": (0.020, 0.007),
      "faba protein concentrate": (0.038, 0.0045), "wheat gluten": (0.014, 0.013), "wheat": (0.0035, 0.0020),
      "solar single-cell protein": (0.046, 0.015), "Novacq": (0.016, 0.006), "insect meal (BSF)": (0.028, 0.008),
      "kelp meal": (0.004, 0.0015), "L-lysine HCl": (0.788, 0.0), "DL-methionine": (0.0, 0.99)}
CASES = {
    "no swap": dict(swap=False, wild=True, intraspecies=False),
    "cross-species swap": dict(swap=True, wild=True, intraspecies=False),
    "swap, own species allowed": dict(swap=True, wild=True, intraspecies=True),
    "fish-free, no swap": dict(swap=False, wild=False, intraspecies=False),
    "fish-free, cross-species swap": dict(swap=True, wild=False, intraspecies=False),
}
WILD_YIELD = 0.275    # t of fishmeal plus fish oil per t of whole wild fish


def solve(case="cross-species swap", year="2050", overrides=None, amino=True):
    cs = {**CASES[case], "amino": amino}
    prod = PRODUCTION_T[year]
    feed_t = {s: prod[s] * FCR[s] for s in SPECIES}
    names = list(ING)
    n_i, n_s = len(names), len(SPECIES)
    idx = lambda i, s: i * n_s + s
    N = n_i * n_s
    c = np.zeros(N)
    bounds = [(0, None)] * N
    A_ub, b_ub, A_eq, b_eq = [], [], [], []
    ov = overrides or {}
    for i, nm in enumerate(names):
        cp, lip, ed, price, mx, grp, crop, avail, origin = ING[nm]
        price = ov.get(nm, price)
        for s, sp in enumerate(SPECIES):
            c[idx(i, s)] = price
            ub = mx * feed_t[sp]
            if nm == "Novacq" and sp != "prawn":
                ub = 0.0
            if grp == "wild" and not cs["wild"]:
                ub = 0.0
            if grp == "byproduct" and origin is not None:
                if not cs["swap"]:
                    ub = 0.0
                elif origin == sp and not cs["intraspecies"]:
                    ub = 0.0
            bounds[idx(i, s)] = (0, ub)
        # availability across species
        if avail is not None:
            if isinstance(avail, str):
                av = prod[origin] * BYPRODUCT_T_PER_T[origin][avail]
            else:
                av = avail
            row = np.zeros(N)
            for s in range(n_s):
                row[idx(i, s)] = 1
            A_ub.append(row)
            b_ub.append(av)
    for s, sp in enumerate(SPECIES):
        f = feed_t[sp] * (1 - PREMIX)
        row = np.zeros(N)
        for i in range(n_i):
            row[idx(i, s)] = 1
        A_eq.append(row)
        b_eq.append(f)
        for key, col in (("cp", 0), ("lipid", 1), ("epadha", 2)):
            row = np.zeros(N)
            for i, nm in enumerate(names):
                row[idx(i, s)] = -ING[nm][col]
            A_ub.append(row)
            b_ub.append(-SPEC[sp][key] * feed_t[sp])
        for key, k in (("lys", 0), ("met", 1)):
            if not cs.get("amino", True):
                continue
            row = np.zeros(N)
            for i, nm in enumerate(names):
                row[idx(i, s)] = -AA.get(nm, (0.0, 0.0))[k]
            A_ub.append(row)
            b_ub.append(-SPEC[sp][key] * feed_t[sp])
        row = np.zeros(N)
        row[idx(names.index("wheat"), s)] = -1
        A_ub.append(row)
        b_ub.append(-SPEC[sp]["binder"] * feed_t[sp])
    res = linprog(c, A_ub=np.array(A_ub), b_ub=b_ub, A_eq=np.array(A_eq), b_eq=b_eq, bounds=bounds, method="highs")
    if res.status != 0:
        return dict(case=case, year=year, feasible=False, message=res.message)
    x = res.x.reshape(n_i, n_s)
    use = {nm: {sp: float(x[i, s]) for s, sp in enumerate(SPECIES)} for i, nm in enumerate(names)}
    tot = {nm: sum(v.values()) for nm, v in use.items()}
    cost = (res.fun + PREMIX * PREMIX_COST * sum(feed_t.values())) / 1e6
    ha = {}
    for nm, (cp, lip, ed, price, mx, grp, crop, avail, origin) in ING.items():
        if crop:
            ha[nm] = tot[nm] / crop
    canola_ha = max(ha.pop("canola meal", 0), ha.pop("canola oil", 0))
    ha["canola (meal and oil)"] = canola_ha
    ha["lupin"] = ha.pop("lupin kernel meal", 0)
    wild = (tot["wild fishmeal"] + tot["wild fish oil"]) / WILD_YIELD
    swaps = {}
    for nm, (cp, lip, ed, price, mx, grp, crop, avail, origin) in ING.items():
        if grp == "byproduct" and origin:
            for sp in SPECIES:
                if use[nm][sp] > 1e-6:
                    swaps[f"{origin}->{sp}"] = swaps.get(f"{origin}->{sp}", 0.0) + use[nm][sp]
    fish_out = sum(prod.values())
    aa = {sp: {k: sum(use[nm][sp] * AA.get(nm, (0, 0))[j] for nm in names) / feed_t[sp] for j, k in ((0, "lys"), (1, "met"))}
          for sp in SPECIES}
    return dict(case=case, year=year, feasible=True, amino_acids=aa, feed_t=feed_t, feed_total_t=sum(feed_t.values()),
                cost_aud_m=cost, cost_aud_t=cost * 1e6 / sum(feed_t.values()),
                cost_by_species_aud_t={sp: (sum(use[nm][sp] * ov.get(nm, ING[nm][3]) for nm in names)
                                            + PREMIX * PREMIX_COST * feed_t[sp]) / feed_t[sp] for sp in SPECIES},
                use_t=use, total_t=tot, cropland_ha=ha, cropland_total_ha=sum(ha.values()),
                wild_fish_t=wild, fifo=wild / fish_out, swaps_t=swaps,
                scp_twh=tot["solar single-cell protein"] * SCP_MWH_T / 1e6,
                byproduct_available_t={sp: {k: PRODUCTION_T[year][sp] * v for k, v in BYPRODUCT_T_PER_T[sp].items()}
                                       for sp in SPECIES})


def run():
    R = {y: {c: solve(c, y) for c in CASES} for y in PRODUCTION_T}
    # sensitivity: wild fishmeal and oil +50% (2026 freight and El Nino risk), DHA canola cheaper
    R["sensitivity"] = {
        "wild +50%": solve("cross-species swap", "2050", {"wild fishmeal": 4350, "wild fish oil": 9750}),
        "DHA canola AUD 3,500/t": solve("fish-free, cross-species swap", "2050", {"DHA canola oil": 3500}),
        "fish-free swap without amino-acid constraints": solve("fish-free, cross-species swap", "2050",
                                                                           amino=False),
        "SCP at AUD 25/MWh solar": solve("fish-free, cross-species swap", "2050",
                                         {"solar single-cell protein": SCP_MWH_T * 25 + SCP_OTHER_AUD}),
    }
    json.dump(R, open(OUT / "feed.json", "w"), indent=1, default=float)
    return R


if __name__ == "__main__":
    R = run()
    for y in PRODUCTION_T:
        for c, d in R[y].items():
            if not d["feasible"]:
                print(y, c, "INFEASIBLE")
                continue
            print(f"{y} {c:32s} cost {d['cost_aud_m']:7.1f} M  {d['cost_aud_t']:6.0f}/t  wild fish {d['wild_fish_t']/1e3:6.1f} kt "
                  f"FIFO {d['fifo']:.2f}  crop {d['cropland_total_ha']/1e3:6.0f} kha  SCP {d['total_t']['solar single-cell protein']/1e3:.1f} kt")
    d = R["2050"]["cross-species swap"]
    print(d["swaps_t"])
    print({k: round(v) for k, v in d["cropland_ha"].items()})
    print({k: round(v) for k, v in d["total_t"].items() if v > 1})
    for k, v in R["sensitivity"].items():
        print(k, round(v["cost_aud_m"], 1), round(v["wild_fish_t"]), round(v["cropland_total_ha"]))
