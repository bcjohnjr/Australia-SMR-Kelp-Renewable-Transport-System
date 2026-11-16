"""Principal inputs of the Australian model, with source, date, units and tested range (AUD 2026 unless noted).

Every number used by more than one module lives here. `provenance_rows()` returns the machine-readable provenance
table written by provenance.py (outputs/input_provenance.csv). Values marked 'screening' are the authors' assumptions;
the tested range is the range used in sensitivity or Monte Carlo analysis.

Scope. Every transport fuel sold in Australia in calendar 2025 (Australian Petroleum Statistics, data extract
December 2025): automotive gasoline, diesel, aviation turbine fuel, aviation gasoline, fuel oil and automotive LPG,
including fuel for international flights and ships loaded in Australia, mining haulage and mine-site power, farm and
construction machinery, rail and coastal shipping. Outside scope: diesel burnt in other stationary uses (about
0.5 GL, screening), non-automotive LPG, lubricants and other products (observed_data/aps_2025.json; reconciliation
in accounts.py).
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import json
from pathlib import Path

_OBS = Path(__file__).resolve().parent / "observed_data"
_APS = json.loads((_OBS / "aps_2025.json").read_text())["sales_ml"]
_PX = json.loads((_OBS / "prices.json").read_text())
import math

CRF = lambda r, n: r * (1 + r) ** n / ((1 + r) ** n - 1)
GJ_PER_MWH = 3.6

# --------------------------------------------------------------------------------------------- volumes (GL, 2025)
VOL_GL = {   # APS calendar 2025 sales (GL)
    "petrol": _APS["Automotive gasoline total (ML)"] / 1000,
    "diesel": _APS["Diesel oil: total (ML)"] / 1000,
    "jet": _APS["Aviation turbine fuel total (ML)"] / 1000,
    "fuel_oil_marine": _APS["Fuel oil (ML)"] / 1000,
    "lpg_auto": _APS["LPG Automotive use (ML)"] / 1000,
    "avgas": _APS["Aviation gasoline (ML)"] / 1000,
}
DIESEL_SPLIT_GL = {       # diesel by end use (GL); road is the residual
    "mining": 8.7,         # 7.76 GL in 2023-24 (Australia Institute from AES); 9.6 GL cited for 2026
    "farm": 2.3,           # mining uses 3.4x agriculture
    "construction": 1.5,   # screening
    "rail": 1.2,           # screening (AES rail ~45 PJ)
    "marine": 0.4,         # coastal shipping, ferries, fishing (screening)
    "stationary_excluded": 0.5,
}
DIESEL_SPLIT_GL["road"] = VOL_GL["diesel"] - sum(DIESEL_SPLIT_GL.values())
LDV_DIESEL_SHARE = 0.32   # utes, SUVs and vans: share of road diesel (screening)
GJ_PER_KL = {"petrol": 34.2, "diesel": 38.6, "jet": 36.8, "fuel_oil": 39.7, "lpg": 26.2, "avgas": 33.1}   # NGA Factors 2025
KWH_PER_L = {k: v / 3.6 for k, v in GJ_PER_KL.items()}

# scope-1 combustion factors (kg CO2-e/GJ, NGA Factors) and full-fuel-cycle ratio (BITRE: road ~126%)
SCOPE1_KG_GJ = {"petrol": 67.8, "diesel": 70.2, "jet": 70.2, "fuel_oil": 73.6, "lpg": 60.6, "avgas": 67.0}
FULL_FUEL_CYCLE = 1.26

SEGMENTS = ("ldv_petrol", "ldv_diesel", "hdv", "rail", "mining", "farm", "construction", "aviation", "shipping")
FUEL_OF = {"ldv_petrol": "petrol", "ldv_diesel": "diesel", "hdv": "diesel", "rail": "diesel", "mining": "diesel",
           "farm": "diesel", "construction": "diesel", "aviation": "jet", "shipping": "fuel_oil"}
JET_INTERNATIONAL_SHARE = _APS["Aviation turbine fuel International (ML)"] / _APS["Aviation turbine fuel total (ML)"]


def demand(scope="all"):
    """Fossil energy replaced by segment, TWh/yr (2025)."""
    g = lambda gl, f: gl * KWH_PER_L[f]
    road = DIESEL_SPLIT_GL["road"]
    d = {"ldv_petrol": g(VOL_GL["petrol"], "petrol") + g(VOL_GL["lpg_auto"], "lpg"),
         "ldv_diesel": g(LDV_DIESEL_SHARE * road, "diesel"),
         "hdv": g((1 - LDV_DIESEL_SHARE) * road, "diesel"),
         "rail": g(DIESEL_SPLIT_GL["rail"], "diesel"),
         "mining": g(DIESEL_SPLIT_GL["mining"], "diesel"),
         "farm": g(DIESEL_SPLIT_GL["farm"], "diesel"),
         "construction": g(DIESEL_SPLIT_GL["construction"], "diesel"),
         "aviation": g(VOL_GL["jet"], "jet") + g(VOL_GL["avgas"], "avgas"),
         "shipping": g(DIESEL_SPLIT_GL["marine"], "diesel") + g(VOL_GL["fuel_oil_marine"], "fuel_oil")}
    if scope == "domestic":
        d["aviation"] = g(VOL_GL["jet"], "jet") * (1 - JET_INTERNATIONAL_SHARE) + g(VOL_GL["avgas"], "avgas")
    return d


def co2_t_per_mwh(seg, basis="wtw"):
    f = FUEL_OF[seg]
    mix = {"ldv_petrol": (("petrol", VOL_GL["petrol"]), ("lpg", VOL_GL["lpg_auto"])),
           "aviation": (("jet", VOL_GL["jet"]), ("avgas", VOL_GL["avgas"]))}
    if seg in mix:
        e = [(k, v * KWH_PER_L[k]) for k, v in mix[seg]]
        s1 = sum(SCOPE1_KG_GJ[k] * w for k, w in e) / sum(w for _, w in e) * 3.6 / 1000
        return s1 * (FULL_FUEL_CYCLE if basis == "wtw" else 1.0)
    if seg == "shipping":
        w = demand()["shipping"]
        md = DIESEL_SPLIT_GL["marine"] * KWH_PER_L["diesel"] / w
        s1 = (md * SCOPE1_KG_GJ["diesel"] + (1 - md) * SCOPE1_KG_GJ["fuel_oil"]) * 3.6 / 1000
    else:
        s1 = SCOPE1_KG_GJ[f] * 3.6 / 1000
    return s1 * (FULL_FUEL_CYCLE if basis == "wtw" else 1.0)


# --------------------------------------------------------------------------------------------- prices and taxes
GST = 0.10
RETAIL_CPL = {"avg2025": {"petrol": 180.75, "diesel": 183.75},   # APS quarterly retail (91 RON, diesel), 2025 mean
              "oct2026": {"petrol": 242.0, "diesel": 279.0}}    # ACCC October 2026; consistent with AIP terminal gate
TGP_CPL = {p: {k: v for k, v in _PX["tgp_cpl_incl_gst_excise"][f].items() if k != "last_date"}
           for p, f in (("petrol", "petrol"), ("diesel", "diesel"))}   # AIP national average (check of retail margins)
EXCISE_CPL = {"avg2025": 50.8, "oct2026": 53.7}      # petrol and diesel; full rate restored 3 Aug 2026
OFFROAD_DISCOUNT_CPL = 8.0                           # bulk supply without retail margin (screening)
JET_USD_BBL = {"avg2025": 90.0, "oct2026": 190.18}   # IATA: 2025 average; global weekly average, week ending 9 Oct 2026
BRENT_USD_BBL = {"avg2025": _PX["brent_avg2025"], "oct2026": _PX["brent_oct2026"]}   # EIA monthly Brent spot
AUD_PER_USD = {"avg2025": 1 / _PX["audusd_avg2025"], "oct2026": 1 / _PX["audusd_oct2026"]}   # RBA F11.1
RUC_CPL = 32.4                                       # heavy-vehicle road user charge, 2026
FTC_OFFROAD_CPL = 53.7                               # fuel tax credit for off-road business use


def pretax_aud_mwh(fuel, period, offroad=False):
    """Pre-tax supply price (excludes GST and excise), AUD per MWh of fossil fuel."""
    if fuel in ("petrol", "diesel"):
        c = RETAIL_CPL[period][fuel] / (1 + GST) - EXCISE_CPL[period] - (OFFROAD_DISCOUNT_CPL if offroad else 0.0)
        return c * 10 / KWH_PER_L[fuel]
    if fuel == "jet":
        return JET_USD_BBL[period] * AUD_PER_USD[period] / 158.987 * 100 * 10 / KWH_PER_L["jet"]
    if fuel == "fuel_oil":
        return 0.9 * BRENT_USD_BBL[period] * AUD_PER_USD[period] / 158.987 * 100 * 10 / KWH_PER_L["fuel_oil"]
    raise KeyError(fuel)


def fossil_price(seg, period):
    if seg in ("ldv_petrol",):
        return pretax_aud_mwh("petrol", period)
    if seg in ("ldv_diesel", "hdv"):
        return pretax_aud_mwh("diesel", period)
    if seg in ("rail", "mining", "farm", "construction"):
        return pretax_aud_mwh("diesel", period, offroad=True)
    if seg == "aviation":
        return pretax_aud_mwh("jet", period)
    d = demand()["shipping"]
    md = DIESEL_SPLIT_GL["marine"] * KWH_PER_L["diesel"] / d
    return md * pretax_aud_mwh("diesel", period, offroad=True) + (1 - md) * pretax_aud_mwh("fuel_oil", period)


def fossil_cost_at_brent(brent_usd, cost_2025_bn, cost_oct2026_bn):
    """Pre-tax fossil fuel bill (AUD bn/yr) at a Brent-equivalent price, interpolated linearly between the 2025
    average (EIA Brent US$69.10) and October 2026 (US$123.93) benchmarks, which carry their own margins and exchange
    rates."""
    b0, b1 = BRENT_USD_BBL["avg2025"], BRENT_USD_BBL["oct2026"]
    return cost_2025_bn + (cost_oct2026_bn - cost_2025_bn) * (brent_usd - b0) / (b1 - b0)


def breakeven_brent(system_bn, cost_2025_bn, cost_oct2026_bn):
    b0, b1 = BRENT_USD_BBL["avg2025"], BRENT_USD_BBL["oct2026"]
    return b0 + (system_bn - cost_2025_bn) * (b1 - b0) / (cost_oct2026_bn - cost_2025_bn)


BRENT_DIST = dict(median=80.0, sigma=0.35)   # lognormal Brent draw for the Monte Carlo (5-95%: ~45-142 US$/bbl)


# --------------------------------------------------------------------------------------------- electricity (GenCost)
GENCOST_CAPEX = {   # AUD/kW, Current policies scenario, GenCost 2025-26 final, Appendix Table B.1
    "smr": {2025: 28009, 2030: 20806, 2035: 20085, 2040: 16682, 2050: 15355},
    "nuclear_large": {2025: 10332, 2030: 9658, 2040: 9306, 2050: 9607},
    "wind": {2025: 3248, 2030: 2650, 2040: 2253, 2050: 2207},
    "solar": {2025: 1621, 2030: 1378, 2040: 1191, 2050: 1029},
    "ocgt": {2025: 1764, 2030: 1589, 2040: 1070, 2050: 1089},
    "electrolyser_alk": {2025: 2100, 2030: 2004, 2040: 2003, 2050: 1856},
    "battery_2h_kwh": {2025: 525, 2030: 438, 2040: 373, 2050: 362},
}
SMR = dict(mwe=300.0, mwth=870.0, avail=0.89, life=40, fom=200.0, vom=5.3, fuel=12.0, waste=2.0,
           capex_kw_2050=15355.0, capex_kw_today=28009.0, site_common_bn=1.75,
           steam_max_mwth=200.0, steam_forgone=0.19, steam_forgone_alumina=0.24,
           lowgrade_max_mwth=250.0, lowgrade_forgone=0.09)


def smr_module_bn(capex_kw):
    return capex_kw * SMR["mwe"] * 1e3 / 1e9


def lcoe(capex, fom, cf, r=0.04, life=30):
    return (capex * CRF(r, life) + fom) / (cf * 8.76)


# --------------------------------------------------------------------------------------------- SMR sites
# The Coalition's seven named sites (19 June 2024; Port Augusta and Muja were proposed for SMRs only), tested here
# as two-module BWRX-300-class sites; Gladstone is a one-module test site that the Coalition did not name.
SITES = {
    "Port Augusta": dict(state="SA", lon=137.74, lat=-32.53, start=2042, grid="NEM", gas=12.0, power=95.0,
                         seawater=True, coalition=True),
    "Muja": dict(state="WA", lon=116.30, lat=-33.44, start=2043, grid="SWIS", gas=9.5, power=105.0,
                 seawater=False, coalition=True),
    "Loy Yang": dict(state="VIC", lon=146.58, lat=-38.25, start=2044, grid="NEM", gas=12.5, power=95.0,
                     seawater=False, coalition=True),
    "Liddell": dict(state="NSW", lon=150.98, lat=-32.37, start=2044, grid="NEM", gas=12.5, power=95.0,
                    seawater=False, coalition=True),
    "Mount Piper": dict(state="NSW", lon=150.03, lat=-33.36, start=2045, grid="NEM", gas=12.5, power=95.0,
                        seawater=False, coalition=True),
    "Tarong": dict(state="QLD", lon=151.92, lat=-26.78, start=2045, grid="NEM", gas=12.0, power=95.0,
                   seawater=False, coalition=True),
    "Callide": dict(state="QLD", lon=150.62, lat=-24.35, start=2046, grid="NEM", gas=12.0, power=95.0,
                    seawater=False, coalition=True),
    "Gladstone (test)": dict(state="QLD", lon=151.25, lat=-23.85, start=2046, grid="NEM", gas=12.0, power=95.0,
                             seawater=True, coalition=False, modules=1),
}
CARBON_AUD_T = {2026: 36.0, 2030: 60.0, 2035: 80.0, 2040: 100.0, 2045: 110.0, 2050: 120.0}   # screening path
GAS_KG_CO2_GJ = 51.5
CAPACITY_VALUE_AUD_KW_YR = 110.0      # near the cost of new entry of an open-cycle gas turbine (GenCost 2040)

# --------------------------------------------------------------------------------------------- water (MED vs SWRO)
WATER = dict(med_kwh_th_m3=70.0, med_kwh_e_m3=1.8, med_capex_m3d=3000.0, med_om_m3=0.20, med_top_c=70.0,
             ro_kwh_e_m3=3.5, ro_capex_m3d=2500.0, ro_om_m3=0.30, intake_outfall_m3=0.60, life=25,
             reject_c=38.0, greenhouse_mwh_ha=800.0, ras_kwh_kg=8.0, greenhouse_m3_ha=6600.0,
             electrolyser_l_kg_h2=15.0)

# --------------------------------------------------------------------------------------------- highways
CATENARY_AUD_M_PER_KM = 4.0          # both directions; CAD 3.6 M (HEC Montreal) at 1.09 AUD/CAD, range 2.8-5.3
CATENARY_LIFE, CATENARY_OM = 30, 0.015
ON_WIRE = 0.85
CORRIDORS = {   # heavy-vehicle AADT and diesel use per km are screening values (B-doubles 0.55 L/km; road trains 0.9)
    "Hume (Sydney-Melbourne)": dict(aadt=3500, l_km=0.55),
    "Pacific (Sydney-Brisbane)": dict(aadt=3000, l_km=0.55),
    "Bruce (Brisbane-Cairns)": dict(aadt=1200, l_km=0.55),
    "Inland (Melbourne-Brisbane via Newell)": dict(aadt=1400, l_km=0.60),
    "Western (Melbourne-Adelaide)": dict(aadt=1500, l_km=0.55),
    "Eyre (Adelaide-Perth)": dict(aadt=450, l_km=0.80),
    "Stuart (Port Augusta-Darwin)": dict(aadt=250, l_km=0.90),
    "Great Northern (Perth-Port Hedland)": dict(aadt=700, l_km=0.90),
}


def provenance_rows():
    """(name, value, units, source, date, range, note) for each principal input."""
    R = []
    a = R.append
    a(("Petrol sold", VOL_GL["petrol"], "GL/yr", "DCCEEW Australian Petroleum Statistics; ACCC market composition report (>16 GL in 2024)", "2025", "15.5-16.5", ""))
    a(("Diesel sold", VOL_GL["diesel"], "GL/yr", "Australian Petroleum Statistics as reported (33 billion litres in 2025)", "2025", "32.6-33.4", ""))
    a(("Jet fuel sold", VOL_GL["jet"], "GL/yr", "173.7 kb/d in 2025 (EIA via TheGlobalEconomy) x 158.987 L/bbl", "2025", "9.5-10.5", "60% international (screening)"))
    a(("Marine fuel oil sold", VOL_GL["fuel_oil_marine"], "GL/yr", "screening (APS fuel oil and bunker sales)", "2025", "0.8-1.6", "approximate"))
    for k, v in DIESEL_SPLIT_GL.items():
        a((f"Diesel, {k}", round(v, 2), "GL/yr", "Australia Institute (2026) from AES (mining 7.76 GL in 2023-24, 3.4x agriculture); IEEFA (2026) 7.7 GL; residual for road", "2023-2026", "", "screening split"))
    for k, v in GJ_PER_KL.items():
        a((f"Energy content, {k}", v, "GJ/kL", "National Greenhouse Accounts Factors 2025", "2025", "", ""))
    for k, v in SCOPE1_KG_GJ.items():
        a((f"Scope-1 factor, {k}", v, "kg CO2-e/GJ", "National Greenhouse Accounts Factors 2025", "2025", "", "x1.26 full fuel cycle (BITRE)"))
    for per, d in RETAIL_CPL.items():
        for f, v in d.items():
            a((f"Retail {f} price, {per}", v, "c/L incl. GST", "ACCC petroleum monitoring (2025 annual average; 5 largest cities 14 Oct 2026)", per, "", "diesel 2025 approximate from quarterly 181.8-185.9"))
    a(("Fuel excise", EXCISE_CPL["oct2026"], "c/L", "ATO excise duty rates from 3 August 2026", "2026-08-03", "", "2025 average 50.8"))
    a(("Jet fuel price", JET_USD_BBL["oct2026"], "USD/bbl", "IATA Jet Fuel Price Monitor; 2025 average 90", "2026-10", "", ""))
    a(("Brent crude", BRENT_USD_BBL["oct2026"], "USD/bbl", "fuelplan.gov.au fuel statistics (ACCC weekly report 16 Oct 2026)", "2026-10-14", "", "2025 average 69"))
    a(("AUD/USD", 0.697, "USD per AUD", "market data (Oct 2026); 2025 average 0.6451", "2026-10", "", ""))
    for t, d in GENCOST_CAPEX.items():
        for y, v in d.items():
            a((f"GenCost capital cost, {t}, {y}", v, "AUD/kW (battery AUD/kWh)", "CSIRO GenCost 2025-26 Final report, Appendix Table B.1/B.4/B.11, Current policies", "2026-07", "", ""))
    a(("SMR fixed O&M", SMR["fom"], "AUD/kW-yr", "GenCost 2025-26 Appendix Table B.9", "2026-07", "150-250", ""))
    a(("SMR variable O&M", SMR["vom"], "AUD/MWh", "GenCost 2025-26 Appendix Table B.9", "2026-07", "", "+ fuel 12 + waste 2 (screening)"))
    a(("SMR availability", SMR["avail"], "-", "GenCost 2025-26 Table B.9 (high case 89%)", "2026-07", "0.53-0.95", ""))
    a(("SMR module capital, 2050", round(smr_module_bn(SMR["capex_kw_2050"]), 2), "AUD bn per 300 MWe", "GenCost 2050 SMR 15,355 AUD/kW", "2026-07", "2.5-8.4", "today 28,009 AUD/kW (8.4 bn)"))
    a(("SMR common site infrastructure", SMR["site_common_bn"], "AUD bn per site", "Darlington budget common costs CAD 1.6 bn at 1.09 AUD/CAD", "2025", "0-2.6", "brownfield coal sites tested at 0.9"))
    a(("Extraction steam electricity forgone", SMR["steam_forgone"], "MWh_e/MWh_th", "screening (150 C extraction, BWRX-300 cycle)", "", "0.15-0.25", "0.24 for 165-180 C alumina digestion steam"))
    a(("Low-grade (70-80 C) heat electricity forgone", SMR["lowgrade_forgone"], "MWh_e/MWh_th", "screening (raised condenser pressure)", "", "0.06-0.13", ""))
    for k, v in CARBON_AUD_T.items():
        a((f"Carbon price path {k}", v, "AUD/t CO2-e", "screening (Safeguard Mechanism credit/ACCU proxy)", "", "50-100% tested", ""))
    a(("Capacity value", CAPACITY_VALUE_AUD_KW_YR, "AUD/kW-yr", "GenCost 2040 OCGT 1,070 AUD/kW at 4-7% + fixed O&M", "2026-07", "0-150", ""))
    for k, v in WATER.items():
        a((f"Water/heat parameter {k}", v, "", "MED and SWRO screening values; Sundrop Farms (1 ML/day distillate, 20 ha); Adelaide desalination plant (100 GL/yr)", "", "", "screening"))
    a(("Catenary cost", CATENARY_AUD_M_PER_KM, "AUD M per route-km", "HEC Montreal A20-H401 study (CAD 3.6 M) converted", "", "2.8-5.3", ""))
    for k, v in CORRIDORS.items():
        a((f"Corridor {k}", v["aadt"], "heavy vehicles/day", "screening (GoAuto: ~3,800 vehicles/day on the Hume Freeway)", "", "+/-30%", f"{v['l_km']} L diesel/km"))
    return R
