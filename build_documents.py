"""Build the manuscript, Supplementary Information and cover letter (DOCX, then PDF with LibreOffice) from outputs/.
Every number in the text is read from the model outputs at build time."""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import json

import numpy as np
import re
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Cm, RGBColor

import inputs as I
import kelp as K
import feed as FD

HERE = Path(__file__).resolve().parent
OUT = HERE / "outputs"
FIG = HERE / "paper_figures"
PKG = layout.PKG
L = lambda f: json.load(open(OUT / f))

C, R, CA, F, CP = L("central.json"), L("scenarios.json"), L("cascade.json"), L("feed.json"), L("coproduction.json")
A, MC, T, AC, W = L("adequacy.json"), L("montecarlo.json")["summary"], L("transition.json"), L("accounts.json"), L("water.json")
TITLE = ""   # set below
AUTHORS = "Jonathan Karl Bily¹*, Christoph Pahl² and Patricia Valdés Bacallao³"
AFFIL = ("¹Independent researcher, Zaragoza, Spain. ²Technical University of Munich and Max Planck Institute for Physics, "
         "Munich, Germany. ³University of Málaga, Málaga, Spain. *e-mail: jonathan@cloudwashlaundry.com; "
         "ORCID 0009-0004-3526-7271")


def _z(x, d):
    return 0.0 if round(float(x), d) == 0 else x


def f0(x):
    return f"{_z(x, 0):,.0f}"


def f1(x):
    return f"{_z(x, 1):,.1f}"


def f2(x):
    return f"{_z(x, 2):,.2f}"


# ------------------------------------------------------------------------------------------ numbers
D = C["demand_twh"]
N = {}
N["dem"] = f0(C["demand_total_twh"])
N["cost"] = f1(C["objective_bn"])
N["cost2"] = f2(C["objective_bn"])
N["prem"] = f1(C["vehicle_premium_bn"])
N["f25"] = f1(C["fossil_cost_bn"]["avg2025"])
N["f26"] = f1(C["fossil_cost_bn"]["oct2026"])
N["pct25"] = f0(100 * (C["objective_bn"] / C["fossil_cost_bn"]["avg2025"] - 1))
N["pct26"] = f0(100 * (1 - C["objective_bn"] / C["fossil_cost_bn"]["oct2026"]))
N["wtw0"] = f0(C["fossil_wtw_mt"])
N["wtw1"] = f1(C["residual_wtw_mt"])
N["wtwp"] = f1(C["wtw_reduction_pct"])
N["today"] = f1(R["today"]["cost_bn"])
eu = C["end_use_twh"]
N["bet"] = f0(eu["hdv|bet"])
N["ers"] = f1(sum(C["ers_twh"].values()))
N["ers_km"] = f0(C["ers_km_electrified"])
N["mine_el"] = f0(eu["mining|el"])
N["mine_liq"] = f0(eu["mining|liq"])
N["jet"] = f0(eu["aviation|jet"])
Fu = C["fuels_twh"]
liq_total = sum(v for k, v in C["carrier_twh"].items() if k != "el")
N["liq"] = f0(liq_total)
N["eft"] = f0(Fu["efuel_ft_wind"] + Fu["efuel_ft_solar"])
N["straw"] = f0(Fu["straw_ft"])
N["res2"] = f0(Fu["cane_htl"] + Fu["forest_htl"])
N["lip"] = f0(Fu["hefa"] + Fu["canola_hvo"])
N["ch4"] = f0(Fu["waste_biomethane"])
N["kelpf"] = f1(Fu["kelp_hc"] + Fu["kelp_methane"])
N["elz"] = f0(C["electrolyser_gw"])
N["h2"] = f1(C["h2_mt"])
N["dac"] = f1(C["co2_mt"]["dac"])
N["bco2"] = f1(C["co2_mt"]["biogenic"])
N["wind"] = f0(C["wind_gw"])
N["pv"] = f0(C["pv_gw"])
N["gen"] = f0(C["generation_total_twh"])
N["el_veh"] = f0(C["electricity_twh"]["vehicles_rail"])
N["el_ef"] = f0(C["electricity_twh"]["efuels"])
sh = C["shadow_aud_mwh"]
N["sh_jet"], N["sh_d"], N["sh_el"] = f0(sh["jet"]), f0(sh["dropin"]), f0(sh["el_direct"])
N["sh_jet_l"] = f2(sh["jet"] * I.KWH_PER_L["jet"] / 1000)
EB = R["electric_or_biofuel"]
N["eb_bio"], N["eb_short"] = f0(EB["liquid_biogenic_twh"]), f0(EB["shortfall_twh"])
N["ers_none"] = f2(R["ers_none"]["cost_bn"] - C["objective_bn"])
N["ers_all"] = f2(R["ers_all"]["cost_bn"] - C["objective_bn"])
N["ers_all_km"] = f0(R["ers_all"]["ers_km"])
ec = R["ers_corridors"]
N["eyre"], N["stuart"] = f0(ec["Eyre (Adelaide-Perth)"]["aud_per_mwh"]), f0(ec["Stuart (Port Augusta-Darwin)"]["aud_per_mwh"])
N["hume"] = f0(ec["Hume (Sydney-Melbourne)"]["aud_per_mwh"])
thr = sh["dropin"] + 20 - 12 - 0.38 * sh["el_direct"]
N["thr"] = f0(thr)
N["kelp"] = f0(C["kelp_total_km2"])
N["kelp_mt"] = f1(C["kelp_dry_mt"])
kf = R["kelp_forced"]
N["kf_lo"], N["kf_hi"] = f2(min(v["extra_bn"] for v in kf.values())), f2(max(v["extra_bn"] for v in kf.values()))
N["kf_bonney"], N["kf_wawest"] = f2(kf["bonney"]["extra_bn"]), f2(kf["wa_west"]["extra_bn"])
ky = R["kelp_yield"]
N["k125"], N["k150"] = f0(ky["learning x1.25"]["kelp_km2"]), f0(ky["learning x1.5"]["kelp_km2"])
zt = C["kelp_zone_table"]
_oth = [r["aud_per_mwh_fuel"] for z, r in zt.items() if C["kelp_km2"][z] < 1]
N["tas_cost"], N["bass_cost"], N["wawest_cost"] = f0(zt["tas_se"]["aud_per_mwh_fuel"]), f0(min(_oth)), f0(max(_oth))
heat_total = sum(v["demand"] for v in C["heat_by_pool"].values())
N["heat"] = f1(heat_total)
be = R["smr_breakeven_module_bn"]
N["be_e"], N["be_sa"], N["be_wa"] = f2(be["east"]), f2(be["sa"]), f2(be["wa"])
wm = [r for r in R["smr_whole_modules"]["4.6"]["rows"] if r["sites"] > 0][0]
wm25 = [r for r in R["smr_whole_modules"]["2.5"]["rows"] if r["sites"] > 0][0]
wmb = [r for r in R["smr_whole_modules_brownfield"]["rows"] if r["sites"] > 0][0]
N["wm46"], N["wm25"], N["wmb"] = f0(-1000 * wm["saving_bn"]), f0(-1000 * wm25["saving_bn"]), f0(-1000 * wmb["saving_bn"])
S = CA["sites"]
V = CA["variants"]
BE = CA["breakeven_module_bn"]
BEB = CA["breakeven_module_bn_brownfield"]
N["mod45"] = f1(CA["central_params"]["module_bn"])
N["npv_fleet"] = f1(V["central"]["fleet_coalition"])
N["npv_muja"], N["npv_ly"], N["npv_pa"], N["npv_gl"] = (f1(S["Muja"]["npv_bn"]), f1(S["Loy Yang"]["npv_bn"]),
                                                       f1(S["Port Augusta"]["npv_bn"]), f1(S["Gladstone (test)"]["npv_bn"]))
N["npv_min"] = f1(min(S[s]["npv_bn"] for s in S))
N["be_muja"], N["beb_muja"], N["be_ly"], N["be_pa"] = f2(BE["Muja"]), f2(BEB["Muja"]), f2(BE["Loy Yang"]), f2(BE["Port Augusta"])
N["be_min"] = f2(min(BE[s] for s in S))
N["v_nosite"] = f1(V["no site infrastructure"]["fleet_coalition"])
N["v30"], N["v30_muja"], N["v30_ly"] = f1(V["modules AUD 3.0 bn, site 0.9 bn"]["fleet_coalition"]), f2(V["modules AUD 3.0 bn, site 0.9 bn"]["Muja"]), f2(V["modules AUD 3.0 bn, site 0.9 bn"]["Loy Yang"])
N["v20"] = f1(V["modules AUD 2.0 bn, site 0.9 bn"]["fleet_coalition"])
N["v_ff"], N["v_ff_muja"] = f1(V["fossil-free grid from 2045"]["fleet_coalition"]), f1(V["fossil-free grid from 2045"]["Muja"])
N["v_cap0"] = f1(V["no capacity value"]["fleet_coalition"])
N["v7"] = f1(V["7% finance"]["fleet_coalition"])
N["v_today"] = f1(V["GenCost today (AUD 8.4 bn per module)"]["fleet_coalition"])
mu = S["Muja"]["first_year"]
N["muja_steam"] = f1(mu["steam_twh"])
pa = S["Port Augusta"]["first_year"]
N["pa_water"] = f0(pa["water_ml_day"])
N["pa_low"] = f1(pa["low_twh"])
wc = W["cases"]
N["swro"], N["med"], N["med_pa"], N["med_sol"], N["med_gas"] = (f2(wc["SWRO (grid electricity)"]["total"]),
                                                               f2(wc["MED, SMR 75 C heat"]["total"]),
                                                               f2(wc["MED, SMR heat + reject heat sold (Port Augusta hub)"]["total"]),
                                                               f2(wc["MED, solar-thermal heat (Sundrop-type)"]["total"]),
                                                               f2(wc["MED, gas boiler heat"]["total"]))
N["rej_be"], N["rej_pa"] = f0(100 * W["breakeven_reject_share_vs_heat_pump"]), f0(100 * W["port_augusta_reject_share"])
N["rej_be_gas"] = f0(100 * W["breakeven_reject_share_vs_gas"])
F50 = F["2050"]
prod50 = sum(FD.PRODUCTION_T["2050"].values())
N["prod50"] = f0(prod50 / 1e3)
N["feed50"] = f0(F50["no swap"]["feed_total_t"] / 1e3)
N["fc_no"], N["fc_sw"], N["fc_own"], N["fc_ff"], N["fc_ffsw"] = (f1(F50[c]["cost_aud_m"]) for c in
                                                               ("no swap", "cross-species swap", "swap, own species allowed",
                                                                "fish-free, no swap", "fish-free, cross-species swap"))
N["wf_no"], N["wf_sw"] = f1(F50["no swap"]["wild_fish_t"] / 1e3), f1(F50["cross-species swap"]["wild_fish_t"] / 1e3)
N["ff_pct"] = f1(100 * (F50["fish-free, cross-species swap"]["cost_aud_m"] / F50["cross-species swap"]["cost_aud_m"] - 1))
N["ban_cost"] = f1(F50["cross-species swap"]["cost_aud_m"] - F50["swap, own species allowed"]["cost_aud_m"])
N["crop_sw"], N["crop_ff"], N["crop_no"] = (f0(F50[c]["cropland_total_ha"] / 1e3) for c in
                                            ("cross-species swap", "fish-free, cross-species swap", "no swap"))
N["lupin"] = f0(F50["cross-species swap"]["cropland_ha"]["lupin"] / 1e3)
N["dhacan"] = f1(F50["fish-free, cross-species swap"]["cropland_ha"]["DHA canola oil"] / 1e3)
sw = F50["cross-species swap"]["swaps_t"]
N["swap_kt"] = f1(sum(sw.values()) / 1e3)
N["sal_kf"] = f1(sw.get("salmon->kingfish", 0) / 1e3)
N["poultry"] = f0(F50["cross-species swap"]["total_t"]["poultry meal"] / 1e3)
oil_mt = Fu["canola_hvo"] / 0.9 / 10.28
N["can_oil"], N["can_meal"], N["can_mha"] = f1(oil_mt), f1(oil_mt / 0.42 * 0.58), f1(oil_mt / 0.67)
N["meal_ratio"] = f0(oil_mt / 0.42 * 0.58 * 1e6 / max(F50["cross-species swap"]["total_t"]["canola meal"], 1))
gh = CP["grid_harvester"]
N["gh"], N["gh_e"], N["gh_c"] = f0(gh["units"]), f1(gh["energy_gwh"]), f1(gh["conventional_gwh"])
shf = CP["shellfish"]
N["sh_sites"], N["mussel"], N["oyster"] = f0(shf["sites"]), f0(shf["mussel_t"]), f0(shf["oyster_t"])
N["sh_man"], N["sh_best"] = f1(shf["margins_aud_m"]["Manual"]), f1(shf["margins_aud_m"]["Manual + shared kelp lease"])
dr = CP["drones"]
N["drones"], N["dr_pct"] = f0(dr["drones"]), f1(dr["share_of_farm_cost_pct"])
N["sal_be"], N["kf_be"] = f2(CP["salmon"]["cost_aud_kg"]), f2(CP["kingfish"]["cost_aud_kg"])
N["sal_n"] = f0(CP["salmon"]["n_share_of_kelp_need_pct"])
pr = CP["prawn_ras"]
N["pr_heat_hp"] = f2(pr["heat pump"]["heat_aud_kg"])
N["pr_heat_gas"] = f2(pr["gas boiler"]["heat_aud_kg"])
N["pr_cost"] = f2(pr["cascade reject heat"]["cost_aud_kg"])
N["pond_cost"] = f2(CP["prawn_pond"]["cost_aud_kg"])
ev = A["events"]
N["l7"], N["l7c"] = f1(ev[0]["methane_twh"]), f2(ev[0]["extra_bn"])
N["l14"], N["l14c"] = f1(ev[2]["methane_twh"]), f2(ev[2]["extra_bn"])
N["lpk"] = f0(A["screen"][0]["peak_gw"])
N["mc_med"], N["mc5"], N["mc95"] = f1(MC["median"]), f1(MC["p5"]), f1(MC["p95"])
N["mc_k"], N["mc_k95"] = f0(MC["kelp_any"]), f0(MC["kelp_p95"])
N["trans"] = f0(T["avoided_vs_el_only_mt"])
fi = AC["fiscal"]
N["exc_net"], N["exc_gross"] = f1(fi["excise_net_bn"]), f1(fi["excise_gross_bn"])
N["ruc"] = f0(fi["ruc_aud_per_mwh_to_replace"])
N["ruc_c"] = f1(fi["ruc_aud_per_mwh_to_replace"] / 10)
N["terr"] = f0(AC["emissions"]["territorial_mt"])
N["today_jet"] = ""
N["mod_today"] = f1(I.smr_module_bn(I.SMR["capex_kw_today"]))
N["mod2050"] = f1(I.smr_module_bn(I.SMR["capex_kw_2050"]))
N["lv"] = [(r["step"], r["cost_bn"]) for r in R["levers"]]
N["less"] = f1(R["less_demand"]["cost_bn"])
# ------------------------------------------------------------------------------------------ v4 numbers
SC, LS, FB = R["kelp_sens"], R["lca_sens"], R["fossil_breakeven"]
ACC = AC["emissions"]
CAL = json.load(open(HERE / "calibration.json"))
DSP = L("dispatch.json")
RES = L("dispatch_resolution.json")
OBS_SITES = json.load(open(HERE / "observed_data" / "sites.json"))
OCEAN = json.load(open(HERE / "observed_data" / "kelp_ocean.json"))
PX = json.load(open(HERE / "observed_data" / "prices.json"))
N["be_brent"], N["be_brent_today"] = f0(FB["brent_usd"]), f0(FB["today_brent_usd"])
N["mc_be"], N["mc_be5"], N["mc_be95"] = f0(MC["breakeven_brent_median"]), f0(MC["breakeven_brent_p5"]), f0(MC["breakeven_brent_p95"])
N["mc_cheap"] = f0(MC["cheaper_at_sampled_brent"])
N["brent25"], N["brent26"] = f0(PX["brent_avg2025"]), f0(PX["brent_oct2026"])
N["wtw_lo"], N["wtw_hi"] = f0(LS["reduction_pct"]["hi"]), f0(LS["reduction_pct"]["lo"])
N["wtw1_lo"], N["wtw1_hi"] = f1(LS["lo"]), f1(LS["hi"])
N["wtw_i2"], N["wtw_l5"] = f1(LS["iluc"]["2.0"]), f1(LS["ch4_leak"]["0.05"])
N["pv_mt"], N["can_mt"] = f1(LS["parts"]["pv"]), f1(LS["parts"]["canola_hvo"])
N["ft_int"] = f0(1000 * LS["efuel_intensity"]["ft"])
N["recon"] = f1(ACC["transport_sector_mt"])
built = [c for c, b_ in C["ers_built"].items() if b_]
N["n_corr"] = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight"][len(built)]
N["corr_names"] = ", ".join(c.split(" (")[0] for c in built[:-1]) + (" and " if len(built) > 1 else "") + built[-1].split(" (")[0]
N["kn"], N["kn_nat"], N["kn_fish"], N["kn_dc"] = (f1(C["kelp_n_kt"]), f1(C["kelp_n_supply_kt"]["natural"]),
                                                 f1(C["kelp_n_supply_kt"]["fish_farms"]), f1(C["kelp_n_supply_kt"]["depth_cycling"]))
N["kn_fish_pct"] = f0(100 * C["kelp_n_supply_kt"]["fish_farms"] / max(C["kelp_n_kt"], 1e-9))
N["kc300"], N["k_none"] = f2(SC["area cap 300 km2 per zone"]["extra_bn"]), f2(SC["no kelp"]["extra_bn"])
N["k_nat"] = f2(SC["natural nitrogen halved"]["extra_bn"])
hyp = SC["hypothetical: ocean bounds without the deployment cap"]
N["k_hyp_km2"], N["k_hyp_bn"] = f0(hyp["kelp_km2"]), f2(-hyp["extra_bn"])
_kz = [z for z, a in C["kelp_km2"].items() if a >= 50]
_ksm = {z: a for z, a in C["kelp_km2"].items() if 1 < a < 50}
_nm = {"tas_se": "southeast Tasmania", "tas_e": "east Tasmania", "bass": "Bass Strait", "bonney": "the Bonney Coast",
       "sa_gulfs": "the South Australian gulfs", "sa_shelf": "the Eyre shelf", "wa_south": "WA's south coast",
       "wa_west": "WA's west coast", "nsw_south": "the NSW south coast"}
N["kelp_where"] = (", ".join(_nm[z] for z in _kz[:-1]) + (" and " if len(_kz) > 1 else "") + _nm[_kz[-1]]) if _kz else "no zone"
N["kelp_nz"] = str(len(_kz))
N["kelp"] = f0(sum(C["kelp_km2"][z] for z in _kz))
N["kelp_small"] = ("; a further " + " and ".join(f"{a:,.0f} km² on {_nm[z]}" for z, a in _ksm.items())
                   + " supplies the last of the turbines' methane") if _ksm else ""
oc = OCEAN["tas_se"]
N["tas_no3m"] = str(oc["months_surface_no3_ge_1"])
N["tas_mhw0"], N["tas_mhw1"] = f0(oc["mhw_days_mean_1983_2012"]), f0(oc["mhw_days_mean_2015_2024"])
N["tas_area"] = f0(K.ZONES["tas_se"].area_km2)
N["warm_zones"] = ", ".join(K.ZONES[z].name.split(" (")[0] for z in ("wa_west", "nsw_south", "sa_gulfs"))
N["warm_loss_lo"], N["warm_loss_hi"] = f0(100 * min(K.ZONES[z].mhw for z in ("wa_west", "nsw_south", "sa_gulfs"))), \
    f0(100 * max(K.ZONES[z].mhw for z in ("wa_west", "nsw_south", "sa_gulfs")))
CON = CA["consistent"]
kc_cap = [k for k in CON if "capacity AUD" in k][0]
kc_no = [k for k in CON if "no capacity" in k][0]
N["con_muja"], N["con_muja_cap"] = f2(CON[kc_no]["Muja"]), f2(CON[kc_cap]["Muja"])
N["nv_el"], N["nv_steam"] = f0(CA["national_values"]["power"]), f0(CA["national_values"]["steam"])
N["fc_aa"] = f1(F50["fish-free, cross-species swap"]["cost_aud_m"] - F["sensitivity"]["fish-free swap without amino-acid constraints"]["cost_aud_m"])
# hourly model
dz = DSP["design"]
sysd = dz["systems"]
tot = lambda k: sum(v[k] for v in sysd.values())
N["h_wind"], N["h_pv"] = f0(tot("wind_gw")), f0(tot("pv_gw"))
N["h_bgw"], N["h_bgwh"] = f0(tot("battery_gw")), f0(tot("battery_gwh"))
N["h_turb"] = f1(DSP["robust"]["turbine_gw"])
N["h_turb_twh"] = f1(DSP["robust"]["turbine_twh_mean_10yr"])
N["h_turb_twh_max"] = f1(DSP["robust"]["turbine_twh_max"])
N["h_elz"], N["h_elz_cf"] = f0(tot("electrolyser_gw")), f0(100 * CAL["hourly_pass2"]["electrolyser_cf"])
N["h_h2"] = f1(tot("h2_store_gwh_el") / 1000)
N["h_links"] = " and ".join(f"{v:.1f}" for v in dz["links_gw"].values())
N["h_curt"] = f0(100 * tot("curtail_twh") / max(tot("generation_twh"), 1e-9))
N["h_direct"] = f0(CAL["hourly_pass1"]["direct"])
N["h_flex"] = f0(CAL["hourly_pass1"]["flex_electricity"])
N["h_inflex"] = f0(CAL["inflexible"]["price_direct_aud_mwh"])
N["h_inflex7"] = f0(L("dispatch_inflexible_r7.json")["design"]["price_direct_aud_mwh"])
N["a_direct0"] = f0(CAL["annual_uncalibrated"]["direct"])
N["a_direct1"] = f0(CAL["annual_prices_after"]["direct"])
N["dist"] = f0(CAL["distribution_aud_mwh"])
N["trans"] = f0(CAL["transmission_aud_mwh"])
N["firm_m"] = f2(CAL["firming_multiplier"])
N["cost_uncal"] = f1(CAL["objective_uncalibrated_bn"])
N["cal_dir"] = "raises" if C["objective_bn"] > CAL["objective_uncalibrated_bn"] else "lowers"
N["netflex"] = f0(CAL["annual_overrides"]["adder"]["net_flex"])
N["unserved"] = f0(DSP["robust"]["unserved_mwh_max"])
N["unserved_pct"] = f"{100 * DSP['robust']['unserved_mwh_max'] / (dz['direct_twh'] * 1e6):.4f}"
N["design_years"] = " and ".join(str(y) for y in DSP["design_years"])
SER = L("dispatch_series.json")
N["coin_firm"] = f0(100 * SER["coincidence"]["firm_share_in_top10pct_demand"])
N["res1"], N["res3"] = f1(RES["results"]["1"]["cost_bn"]), f1(RES["results"]["3"]["cost_bn"])
N["res_pct"] = f1(100 * (RES["results"]["3"]["cost_bn"] / RES["results"]["1"]["cost_bn"] - 1))
# ---- v5: one portfolio, one cost, one emissions figure (reconcile.py), final verification and mechanism test
REC = L("reconciled.json")
VER = L("verify_hourly.json")
CFD, CFF = L("dispatch_daily.json"), L("dispatch_flat.json")
N["cost_annual"] = f1(C["objective_bn"])
N["cost"] = f1(REC["reconciled_cost_bn"])
N["cost2"] = f1(REC["reconciled_cost_bn"])
N["rec_diff"] = f1(abs(REC["difference_bn"]))
N["rec_dir"] = "more" if REC["difference_bn"] > 0 else "less"
N["rec_pct"] = f1(abs(REC["difference_pct"]))
N["pct25"] = f0(100 * (REC["reconciled_cost_bn"] / C["fossil_cost_bn"]["avg2025"] - 1))
N["be_brent_annual"] = f0(FB["brent_usd"])
N["be_brent"] = f0(FB["reconciled_brent_usd"])
N["mc_be"], N["mc_be5"], N["mc_be95"] = (f0(MC["breakeven_reconciled_median"]), f0(MC["breakeven_reconciled_p5"]),
                                         f0(MC["breakeven_reconciled_p95"]))
N["mc_cheap"] = f0(MC["cheaper_reconciled"])
N["wtw1"] = f1(REC["residual_wtw_mt"])
N["wtwp"] = f1(REC["wtw_reduction_pct"])
N["wtw1_lo"], N["wtw1_hi"] = f1(REC["residual_range_mt"]["lo"]), f1(REC["residual_range_mt"]["hi"])
N["wtw_lo"] = f0(100 * (1 - REC["residual_range_mt"]["hi"] / C["fossil_wtw_mt"]))
N["wtw_hi"] = f0(100 * (1 - REC["residual_range_mt"]["lo"] / C["fossil_wtw_mt"]))
N["wtw_annual"] = f1(C["residual_wtw_mt"])
PH, PA = REC["portfolio_hourly"], REC["portfolio_annual"]
N["a_wind"], N["a_pv"] = f0(PA["wind_gw"]), f0(PA["pv_gw"])
N["a_share"] = f0(100 * PA["wind_twh"] / (PA["wind_twh"] + PA["pv_twh"]))
N["h_share"] = f0(100 * PH["wind_share_potential"])
N["gen"] = f0(PH["wind_twh_potential"] + PH["pv_twh_potential"])
N["wind"], N["pv"] = N["h_wind"], N["h_pv"]
N["n_iter"] = str(len(CAL.get("iteration_history", [])))
N["a_wind0"], N["a_pv0"] = "29.5", "131.6"     # v4 annual portfolio, reported in the response only
_vy = VER["years"]
N["v_unserved"] = f0(max(v["unserved_mwh"] for v in _vy.values()))
_vd = np.mean([v["direct_twh"] for v in _vy.values()]) * 1e6
N["v_mean"] = f0(np.mean([v["unserved_mwh"] for v in _vy.values()]))
N["v_mean_pct"] = f"{100 * np.mean([v['unserved_mwh'] for v in _vy.values()]) / _vd:.4f}"
N["v_n_over"] = str(sum(v["unserved_mwh"] / (v["direct_twh"] * 1e6) > 2e-5 for v in _vy.values()))
N["v_unserved_pct"] = f"{100 * max(v['unserved_mwh'] / (v['direct_twh'] * 1e6) for v in _vy.values()):.4f}"
N["v_worst_year"] = max(_vy, key=lambda y: _vy[y]["unserved_mwh"])
N["v_turb_twh"] = f1(np.mean([v["turbine_twh"] for v in _vy.values()]))
N["v_turb_twh_max"] = f1(max(v["turbine_twh"] for v in _vy.values()))
N["v_turb_peak"] = f1(max(v["turbine_peak_gw"] for v in _vy.values()))
N["v_solve"] = f0(np.mean([v["solve_s"] for v in _vy.values()]) / 60)
N["h_direct"] = f0(CAL["hourly_pass2"]["direct"])
N["h_flex"] = f0(CAL["hourly_pass2"]["flex_electricity"])
def _cf(Rx):
    d = Rx["design"]; sy = d["systems"]; t = lambda k: sum(v[k] for v in sy.values())
    return dict(cost=d["total_cost_bn"], direct=d["price_direct_aud_mwh"], flex=d["price_flex_aud_mwh"],
                wind=t("wind_gw"), pv=t("pv_gw"), bgwh=t("battery_gwh"), turb=t("turbine_gw"), elz=t("electrolyser_gw"),
                h2=t("h2_store_gwh_el") / 1000, curt=100 * t("curtail_twh") / max(t("generation_twh"), 1e-9))
CF0, CF1, CF2 = _cf(DSP), _cf(CFD), _cf(CFF)
for k_, c_ in (("s", CF0), ("d", CF1), ("f", CF2)):
    N[f"cf_{k_}_cost"], N[f"cf_{k_}_dir"], N[f"cf_{k_}_flex"] = f1(c_["cost"]), f0(c_["direct"]), f0(c_["flex"])
    N[f"cf_{k_}_bgwh"], N[f"cf_{k_}_turb"], N[f"cf_{k_}_elz"] = f0(c_["bgwh"]), f1(c_["turb"]), f0(c_["elz"])
    N[f"cf_{k_}_gen"] = f0(c_["wind"] + c_["pv"])
N["v_turb_gw"] = f1(VER["turbine_gw"])
N["topup3"] = f1(DSP["robust"]["extra_turbine_gw"])
N["topup1"] = f1(VER["turbine_gw"] - VER["turbine_gw_3h"])
# ---- v6: methane balance, regional reliability, storage-cost sensitivity
MB = C["methane_balance_twh"]
N["ch4_turb"] = f1(MB["turbines"])
N["ch4_need"] = f1(REC["methane"]["turbine_need_twh"])
N["ch4_store"] = f0(REC["methane"]["store_twh"])
N["ch4_waste"], N["ch4_kelp"], N["ch4_e"] = f0(MB["waste_biomethane"]), f1(MB["kelp_methane"]), f1(MB["e_methane"])
N["ch4_trans"], N["ch4_meoh"] = f1(MB["transport"]), f1(MB["bio_methanol"])
N["ch4_cost"] = f2(R["no_turbine_methane"]["extra_bn"])
N["h_h2_h2"] = f1(float(N["h_h2"].replace(",", "")) * DSP["params"]["h2_eff"])
_dk = C["ers_km_electrified"] - R["no_turbine_methane"]["ers_km"]
N["ch4_ers"] = (f"partly by adding {_dk:,.0f} km of catenary, and " if _dk > 1 else "and ")
N["ch4_trans0"], N["ch4_meoh0"] = "8.4", "7.5"
INV = REC["methane"]["inventory"]
BF = L("biofuel_costs.json")
N["ch4_open"], N["ch4_cap"] = f0(INV["opening_twh"]), f0(INV["capacity_twh"])
N["ch4_cap_pj"] = f0(INV["capacity_twh"] * 3.6)
N["ch4_low"] = f1(min(r["lowest"] for r in INV["years"]))
N["ch4_fill_bn"] = f2(REC["methane"]["cost_bn"]["initial_fill"] + REC["methane"]["cost_bn"]["store"])
N["ch4_turb3"], N["ch4_need3"] = f"{MB['turbines']:.3f}", f"{REC['methane']['turbine_need_twh']:.4f}"
N["ch4_surplus"] = f"{INV['surplus_10yr_twh']:.3f}"
_bp = BF["pathways"]
N["bf_twh"], N["bf_bn"] = f0(BF["biofuel_twh_2050"]), f1(BF["biofuel_spend_2050_bn"])
N["bf_l"] = f2(BF["biofuel_spend_2050_bn"] / BF["biofuel_twh_2050"] * BF["litre_basis_kwh"])
N["ef_twh"], N["ef_bn"] = f0(BF["efuel_twh_2050"]), f1(BF["efuel_spend_2050_bn"])
_ft = _bp["Fischer-Tropsch electrofuel (air-captured CO2)"]["aud_l_diesel_eq"]
N["ft_l26"], N["ft_l50"] = f2(_ft["2026"]), f2(_ft["2050"])
_lo = min(v["aud_l_diesel_eq"]["2050"] for k, v in _bp.items() if not k.startswith(("e-", "Fischer", "Kelp")))
_hi = max(v["aud_l_diesel_eq"]["2050"] for k, v in _bp.items() if not k.startswith(("e-", "Fischer", "Kelp")))
N["bf_lo"], N["bf_hi"] = f2(_lo), f2(_hi)
_fp = BF["fossil_pretax_aud_mwh"]
N["dsl_l25"], N["dsl_l26"] = f2(_fp["diesel_2025"] * BF["litre_basis_kwh"] / 1000), f2(_fp["diesel_oct2026"] * BF["litre_basis_kwh"] / 1000)
_APS = json.load(open(HERE / "observed_data" / "aps_2025.json"))
_rb = DSP["robust"]
_adq = (VER["turbine_gw"] - VER["turbine_gw_3h"]) * _rb["extra_turbine_cost_bn"] / _rb["extra_turbine_gw"]
N["h_direct_adq"] = f0(CAL["hourly_pass2"]["direct"] + _adq * 1e3 / DSP["design"]["direct_twh"])
N["ch4_turb2"], N["ch4_need2"] = f"{MB['turbines']:.3f}", f"{REC['methane']['turbine_need_twh']:.3f}"    # version 5, without turbine fuel in the balance
N["h_h2_el"] = N["h_h2"]
GRIDS = list(_vy[next(iter(_vy))]["unserved_mwh_by_node"])
REG = {}
for g in GRIDS:
    u = [v["unserved_mwh_by_node"][g] for v in _vy.values()]
    d = [v["direct_twh_by_node"][g] * 1e6 for v in _vy.values()]
    REG[g] = dict(mean=float(np.mean(u)), mean_pct=100 * float(np.mean(u)) / max(float(np.mean(d)), 1.0),
                  worst=float(max(u)), worst_pct=100 * max(x / max(y, 1.0) for x, y in zip(u, d)))
_ve = L("verify_hourly_economic_sizing.json")["years"]
_u = np.mean([v["unserved_mwh_by_node"]["SA_TAS"] for v in _ve.values()])
_d = np.mean([v["direct_twh_by_node"]["SA_TAS"] for v in _ve.values()]) * 1e6
N["reg_econ_satas"] = f"{100 * _u / _d:.4f}"
N["reg_econ_turb"] = f1(L("verify_hourly_economic_sizing.json")["turbine_gw"])
N["rel_sent"] = (
    (f"Turbines were sized in a one-hour adequacy pass that treats any shortfall as costing A$300,000 per MWh; with "
     f"them the fixed fleet leaves no demand unserved in any grid in any of the ten years (table S20), against "
     f"reliability standards of 0.002% expected unserved energy in each region of the National Electricity Market "
     f"[[aemc_rs]] and in Western Australia [[wem_pc]]. Sized at the A$20,000 used in planning, {N['reg_econ_turb']} GW "
     f"of turbines would have left South Australia–Tasmania at {N['reg_econ_satas']}%, above the standard. Because the "
     f"model merges New South Wales with Victoria and South Australia with Tasmania and omits outages, it shows that "
     f"weather alone does not leave these grids short, not compliance in each market region.")
    if max(v["unserved_mwh"] for v in _vy.values()) < 1.0 else
    (f"Expected unserved energy by modelled grid is {N['reg_list']} (table S20), against reliability standards of "
     f"0.002% in each region of the National Electricity Market [[aemc_rs]] and in Western Australia [[wem_pc]]. "
     f"Because the model merges New South Wales with Victoria and South Australia with Tasmania and omits outages, it "
     f"cannot show compliance in each market region."))
N["reg_over"] = ", ".join(g.replace("_", "/") for g, r in REG.items() if r["mean_pct"] > 0.002) or "none"
N["reg_max_g"] = max(REG, key=lambda g: REG[g]["mean_pct"]).replace("_", "/")
N["reg_max_pct"] = f"{max(r['mean_pct'] for r in REG.values()):.4f}"
N["reg_list"] = "; ".join(f"{g.replace('_', '/')} {r['mean_pct']:.4f}%" for g, r in REG.items())
H2C = {}
for c_ in (5, 10, 15):
    a_ = _cf(L(f"dispatch_h2c{c_}_seasonal.json")); b_ = _cf(L(f"dispatch_h2c{c_}_daily.json"))
    H2C[c_] = dict(seasonal=a_, daily=b_)
N["h2c_adv"] = "; ".join(f"A${c_}: {H2C[c_]['daily']['cost'] - H2C[c_]['seasonal']['cost']:.1f}" for c_ in H2C)
N["h2c_store15"] = f1(H2C[15]["seasonal"]["h2"])
N["h2c_store5"] = f1(H2C[5]["seasonal"]["h2"])
N["h2c_adv15"] = f1(H2C[15]["daily"]["cost"] - H2C[15]["seasonal"]["cost"])
N["h2c_adv0"] = f1(CF1["cost"] - CF0["cost"])
N["h2c_flat15"] = f1(CF2["cost"] - H2C[15]["seasonal"]["cost"])
_adv = [H2C[c_]["daily"]["cost"] - H2C[c_]["seasonal"]["cost"] for c_ in (5, 10, 15)]
N["h2c_sent"] = (
    (f"the seasonal case stays cheaper than daily flexibility by A${_adv[0]:.1f}, {_adv[1]:.1f} and {_adv[2]:.1f} billion "
     f"a year (A${CF1['cost'] - CF0['cost']:.1f} billion at the central cost), with a store of {H2C[5]['seasonal']['h2']:.1f}, "
     f"{H2C[10]['seasonal']['h2']:.1f} and {H2C[15]['seasonal']['h2']:.1f} TWh of electrolyser input (table S21).")
    if min(_adv) > 0 else
    (f"the advantage of seasonal over daily flexibility is A${_adv[0]:.1f}, {_adv[1]:.1f} and {_adv[2]:.1f} billion a "
     f"year, so it does not survive costly storage (table S21)."))
N["h2c_ok"] = all(H2C[c_]["daily"]["cost"] > H2C[c_]["seasonal"]["cost"] for c_ in H2C)
N["mech_word"] = ("seasonal flexibility (demand that can wait weeks against a cheap store), not to electrolysers as "
                  "such" if CF1["cost"] > CF0["cost"] and CF2["cost"] > CF1["cost"] else "flexible demand in general")
N["cf_d_extra"], N["cf_f_extra"] = f1(CF1["cost"] - CF0["cost"]), f1(CF2["cost"] - CF0["cost"])
fs = R["firming_sens"]
N["fx15"], N["fx2"] = f1(fs["firming and network adders x1.5"]["extra_bn"]), f1(fs["firming and network adders x2.0"]["extra_bn"])
N["fx2_be"] = f0(fs["firming and network adders x2.0"]["breakeven_brent"])
N["vol_incl"] = f1(ACC["fuel_included_ml"] / 1000)
N["n_tests"] = str(len([k for k in dir(__import__("test_model")) if k.startswith("test_")]))
W_ = OBS_SITES["sites"]
N["wind_scale_lo"] = f2(min(m["wind_scale"] for m in W_.values() if m["wind_scale"]))
N["wind_scale_hi"] = f2(max(m["wind_scale"] for m in W_.values() if m["wind_scale"]))

N["abs_flex"] = ("whose electrolysers, able to wait weeks for wind and sun against stored hydrogen, make firmed electricity "
                 "cheaper than in a grid without them."
                 if CAL["inflexible"]["price_direct_aud_mwh"] > CAL["hourly_pass2"]["direct"] + 10 else
                 "and every weather year from 2015 to 2024 is served reliably.")
N["disc_flex"] = ("the electrolysers that make those fuels, because they can wait weeks for wind and sun against stored "
                  "hydrogen, are the cheapest source of flexibility, so firming direct loads costs less than in a grid "
                  "without them, although electricity for the electrolysers costs more than an annual balance suggests"
                  if CAL["inflexible"]["price_direct_aud_mwh"] > CAL["hourly_pass2"]["direct"] + 10 else
                  "an hourly test over ten weather years confirms that the supply is reliable at a calibrated cost")
TITLE = "Replacing Australia's transport fuels: electricity, biofuels and nuclear heat"
SUMMARY = "Replacing all Australian transport fuel needs electrofuels, whose seasonal flexibility makes renewable power cheap."
ABSTRACT = (
    f"Australia imports most of its transport fuel and in 2026 held only weeks of stocks. We replace all {N['dem']} TWh of "
    f"transport fuel sold in 2025 in a least-cost model with electricity, catenary highways, biofuels, "
    f"electrofuels and native kelp, test small modular reactors at seven proposed sites, and plan the electricity supply "
    f"against ten observed weather years. With assumed learning the system costs A${N['cost']} billion a year, equal to "
    f"fossil fuel at a Brent-equivalent US${N['be_brent']} per barrel, and cuts supply-chain emissions by "
    f"{N['wtwp'].split('.')[0]}% ({N['wtw_lo']} to {N['wtw_hi']}%). Biofuels cannot meet demand; aviation needs "
    f"electrofuels, {N['abs_flex']} Reactors enter only below about A${N['be_e']} billion per module.")

INTRO = [
    "Transport emitted 100.9 Mt CO₂e in Australia in 2025, second only to electricity [[nggi]], and almost all of its fuel "
    "is imported. Australia sold 33.5 billion litres of diesel in 2025, a quarter of it to mines [[aps,ai_diesel]], and "
    "domestic refineries supply about a fifth of national fuel [[fuelplan]]. The conflict in the Middle East that began in "
    "February 2026 lifted Brent crude to a monthly average of US$124 per barrel in October [[eia]], put the National Fuel "
    "Security Plan at Level 2 and left 28 to 41 days of jet, diesel and petrol in stock [[fuelplan,accc]]. Net-zero "
    "studies pair electrification with low-carbon fuels and firm low-carbon power [[davis,sepulveda,ipcc]], but national "
    "studies seldom replace every transport fuel, including mining, international flights and ships, in one optimization, "
    "and fewer test the electricity such a system needs against observed weather.",
    "Australia is also debating nuclear power, which national law prohibits [[claytonutz]]. In September 2026 the federal "
    "opposition proposed lifting the ban [[energymatters]], having named seven coal-plant sites in 2024, two of them for "
    "small modular reactors (SMRs) [[coalition_sites]]. CSIRO's GenCost puts SMRs at A$28,009 per kW today and A$15,355 in "
    "2050, the highest of any technology, and the cost of a net-zero electricity system in 2050 at A$141 to 152 per MWh "
    "including transmission [[gencost]]. Reactors also make heat, which could distil water, heat alumina refineries and "
    "warm greenhouses and fish farms. Australia also has the 8,000-km Great Southern Reef [[bennett]], a growing "
    "aquaculture industry [[daff_aqua,tas_salmon]] and inland grain belts that already supply protein to fish feeds "
    "[[smith_shrimp,skretting]]. Here we ask where these pieces fit when all transport fuel is replaced, and whether the "
    "answer survives hourly weather. A companion analysis for Spain [[spain_ssrn]] and an unpublished one for Canada use "
    "the same framework; the Australian system differs because its aviation and mining demand outruns its biomass.",
]

RESULTS = [
    ("A national model checked against observed weather", [
        f"An annual mixed-integer programme meets 2025 demand of {N['dem']} TWh in nine segments, from cars to "
        f"international ships, at least annualized cost in a 2050 technology-learning case (Materials and Methods). Demand "
        f"is reconciled with the official 2025 sales of every transport fuel [[aps]]. The programme chooses wind and "
        f"solar, battery, catenary or fuel vehicles, eight highway catenary corridors as yes-or-no investments, kelp zones "
        f"bounded by ocean observations, residues, oils, electrofuels and SMR fleets selling electricity and steam into "
        f"regional heat pools. A chronological model then plans the electricity supply for the loads it sets, over "
        f"2015 to 2024, from reanalysis weather [[era5]] scaled to the market operator's zone capacity factors "
        f"[[aemo_isp]], with wind, solar, batteries, turbines, electrolysers, hydrogen storage and inter-regional links as "
        f"explicit capacities. The two models are iterated: the annual programme takes the chronological model's prices, "
        f"electrolyser utilisation and wind share, and the loads it then sets go back to the chronological model, until "
        f"prices change by less than A$1 per MWh and the wind share by less than one percentage point ({N['n_iter']} "
        f"iterations). Costs, capacities and emissions reported here use the chronological model's final fleet in place "
        f"of the annual model's stylised electricity supply (Materials and Methods). The code reproduces every number in "
        f"this article and runs {N['n_tests']} consistency tests on each build.",
    ]),
    ("Every segment replaced, but not by electricity and biofuels alone", [
        f"The least-cost system replaces all {N['dem']} TWh (Fig. 1 and Fig. 2A): every litre of petrol, diesel, jet fuel, "
        f"aviation gasoline, fuel oil and automotive LPG sold in 2025 except 0.5 GL of stationary diesel (table S23). Cars, utes and vans become "
        f"battery-electric; trucks use batteries for {N['bet']} TWh of their {f0(D['hdv'])} TWh and catenary for "
        f"{N['ers']} TWh; mines electrify {N['mine_el']} TWh and burn {N['mine_liq']} TWh of drop-in diesel; aviation "
        f"uses {N['jet']} TWh of renewable jet; ships use methanol, ammonia and methane. Transport uses "
        f"{N['liq']} TWh of liquid and gaseous fuels (Fig. 2B), made mainly from Fischer–Tropsch electrofuels {N['eft']}, cereal straw {N['straw']}, cane and "
        f"forest residues {N['res2']}, tallow, used cooking oil and canola {N['lip']}, waste biomethane {N['ch4']} and "
        f"kelp {N['kelpf']} TWh; part of the biomethane fuels the firming turbines. The electricity fleet has {N['wind']} GW of wind and {N['pv']} GW of solar, able to "
        f"generate {N['gen']} TWh a year, {N['h_share']}% of it from wind (Fig. 2C); the annual programme, given that "
        f"wind share, chooses {N['a_wind']} GW and {N['a_pv']} GW.",
        f"Aviation sets the price of liquid fuel. Each source can turn only part of its output into jet, so the last MWh of "
        f"jet costs A${N['sh_jet']} (A${N['sh_jet_l']} per litre) against A${N['sh_d']} for drop-in diesel. Without "
        f"electrofuels and methanol, ammonia or methane vehicles, Australia's residues, oils and wastes yield at most "
        f"{N['eb_bio']} TWh of liquids and leave {N['eb_short']} TWh of jet and diesel unmet. Unlike forest-rich countries, "
        f"Australia cannot decarbonize transport with electricity and biofuels alone.",
        f"Producing the {N['bf_twh']} TWh of biofuels and biomethane costs A${N['bf_bn']} billion a year: A${N['bf_lo']} to "
        f"{N['bf_hi']} per litre of diesel equivalent by pathway, A${N['bf_l']} on average, against A${N['dsl_l25']} and "
        f"{N['dsl_l26']} for fossil diesel before tax in 2025 and October 2026. We hold these mature pathways at today's "
        f"costs. Fischer–Tropsch electrofuel falls from A${N['ft_l26']} per litre today to A${N['ft_l50']} in 2050 as "
        f"electricity, electrolysers and air capture learn, and the {N['ef_twh']} TWh of electrofuels cost A${N['ef_bn']} "
        f"billion a year (fig. S13 and table S24). Biofuels are the cheap part of the system; they are limited by "
        f"feedstock, not cost.",
    ]),
    ("Seasonal flexibility firms the system", [
        f"The chronological model serves the system's loads in five grids (three in the National Electricity Market, the "
        f"Western Australian and Northern Territory systems) with no help from the existing grid. Planned in three-hour "
        f"steps over design years {N['design_years']}, the weakest and the median for wind and sun, the final fleet has "
        f"{N['h_wind']} GW of wind, {N['h_pv']} GW of solar, {N['h_bgw']} GW and {N['h_bgwh']} GWh of batteries, "
        f"{N['h_elz']} GW of electrolysers running at {N['h_elz_cf']}% of capacity, a hydrogen store holding the output of "
        f"{N['h_h2']} TWh of electrolyser input (about {N['h_h2_h2']} TWh of hydrogen), "
        f"new links of {N['h_links']} GW between the market's regions and {N['v_turb_gw']} GW of turbines burning stored "
        f"renewable methane, sized by checks of every year from 2015 to 2024 (fig. S12 and table S19). We then fixed this "
        f"fleet, identical in every year with nothing added, and dispatched it hour by hour through all ten years (table "
        f"S20). Turbines generate {N['v_turb_twh']} TWh in an average year and {N['v_turb_twh_max']} TWh in the worst. "
        f"Their methane, {N['ch4_turb']} TWh a year, is a demand in the national methane balance, not an extra supply: "
        f"the national programme frees it by moving trucks and ships from {N['ch4_trans0']} to {N['ch4_trans']} TWh of "
        f"methane, {N['ch4_ers']}making less bio-methanol, for A${N['ch4_cost']} billion a year. A ten-year inventory "
        f"of production and withdrawals (table S20) shows that a store of {N['ch4_cap']} TWh, opened with {N['ch4_open']} "
        f"TWh, never runs out and ends the decade no lower than it began; that is under half of Australia's existing "
        f"underground gas storage [[gas_storage]], and the store and its first fill cost A${N['ch4_fill_bn']} billion a "
        f"year. {N['rel_sent']} Only {N['coin_firm']}% of battery and turbine output falls in the tenth of hours with "
        f"the highest existing grid demand [[aemo_demand]], so the transport system adds little to the existing system's "
        f"peak.",
        f"Direct loads (vehicles, catenary, mines and heat pumps) pay A${N['h_direct']} per MWh at marginal prices, "
        f"including new transmission of about A${N['trans']} (A${N['h_direct_adq']} with the turbines added by the "
        f"one-hour adequacy pass); the same loads served alone cost A${N['h_inflex']} on the same basis, or "
        f"A${N['h_inflex7']} at the 7% discount rate typical of grid planning (Fig. 5C). To find what lowers the cost, we "
        f"replaced the electrolysers with an industrial demand of the same energy and the same plant that can shift "
        f"its use only within a day (24 hours of storage) or not at all. The daily-flexible demand raises the "
        f"electricity system's cost from A${N['cf_s_cost']} to {N['cf_d_cost']} billion a year and the flat demand to "
        f"{N['cf_f_cost']} billion; direct loads then pay A${N['cf_d_dir']} and {N['cf_f_dir']} per MWh before turbine "
        f"top-up, against {N['cf_s_dir']} with the seasonal store and {N['h_inflex']} alone, and the flat case needs {N['cf_f_bgwh']} GWh of batteries and "
        f"{N['cf_f_turb']} GW of turbines against {N['cf_s_bgwh']} GWh and {N['cf_s_turb']} GW. Cheap firming therefore "
        f"comes from seasonal flexibility, demand that can wait weeks for wind and sun against a cheap store, not from "
        f"electrolysers as such; any load with such a store would do the same. Because the store is costed at A$1.5 per kWh "
        f"of hydrogen, we re-optimised the seasonal and daily cases at A$5, 10 and 15 per kWh: {N['h2c_sent']} GenCost's A$141 to 152 per MWh for the "
        f"whole net-zero grid in 2050 [[gencost]] is context, not a like-for-like benchmark: it carries existing demand, "
        f"distribution-connected supply and system-security services that this model omits.",
        f"Electricity for electrolysers costs more hourly than an annual balance suggests, because they must ride through "
        f"still, dark spells on stored hydrogen (about {N['h_h2_h2']} TWh), a store larger than any yet built (Materials and "
        f"Methods). With the annual programme calibrated to the hourly prices (firming adders scaled by {N['firm_m']}, "
        f"flexible network adder A${N['netflex']} per MWh, electrolyser utilisation {N['h_elz_cf']}%, wind share "
        f"{N['h_share']}%), its objective is A${N['cost_annual']} billion a year; doubling every firming and network "
        f"adder adds A${N['fx2']} billion.",
    ]),
    ("Cost against the price of oil", [
        f"The system costs A${N['cost2']} billion a year, including A${N['prem']} billion of vehicle premia, in a "
        f"technology-learning case with GenCost's 2050 capital costs, 4% real finance and learning in electrofuels and kelp "
        f"(fig. S3). This is A${N['rec_diff']} billion {N['rec_dir']} than the annual programme's own objective "
        f"(A${N['cost_annual']} billion), because the chronological fleet replaces its stylised electricity supply. At "
        f"today's costs and 7% finance the annual programme gives A${N['today']} billion. Rather than compare it with one oil "
        f"price, we find the oil price at which it breaks even. Interpolating the pre-tax fossil bill between 2025 (Brent "
        f"US${N['brent25']}, A${N['f25']} billion) and October 2026 (US${N['brent26']}, A${N['f26']} billion) "
        f"[[eia,aip_tgp]], the learning case breaks even at US${N['be_brent']} per barrel and today's costs at "
        f"US${N['be_brent_today']}. Across 1,000 Monte Carlo draws of finance, cost, yield, resource and firming inputs, "
        f"with the reconciliation difference held fixed, the break-even price has a median of US${N['mc_be']} "
        f"(5th–95th percentile {N['mc_be5']}–{N['mc_be95']}; Fig. 5D). Paired with an oil price drawn from an assumed "
        f"lognormal distribution (median US$80), the system is cheaper in {N['mc_cheap']} of 1,000 draws; this measures "
        f"the spread of our assumptions, not the probability that the system will be cheaper. Replacing fossil fuel is a hedge against prices like those of 2026, not a saving "
        f"at the oil prices of the past decade.",
    ]),
    ("Which highways to electrify", [
        f"Battery trucks can carry up to 85% of heavy-vehicle energy; catenary competes for the rest, corridor by corridor "
        f"(Fig. 5A). Each corridor is built whole or not at all. Catenary is built on {N['n_corr']} corridors "
        f"({N['corr_names']}), {N['ers_km']} km, each carrying its full modelled traffic. It costs A${N['hume']} per MWh "
        f"of diesel replaced on the Hume Highway but A${N['eyre']} on the Eyre and A${N['stuart']} on the Stuart, where "
        f"a few hundred road trains a day share 2,700 km. Without catenary the system costs A${N['ers_none']} billion more "
        f"a year; electrifying all {N['ers_all_km']} km adds A${N['ers_all']} billion.",
    ]),
    ("Kelp is optional and conditional", [
        f"Ocean observations favour the cool, nitrate-rich waters around Tasmania and in Bass Strait. Off southeast "
        f"Tasmania surface nitrate exceeds 1 µmol/kg in {N['tas_no3m']} months of the year [[woa23]] and summer water "
        f"stays below the 20 °C limit of giant kelp, although marine-heatwave days have risen from {N['tas_mhw0']} a year "
        f"in 1983–2012 to {N['tas_mhw1']} in 2015–2024 [[oisst,hobday]]. Elsewhere nitrate is scarce or heat stress "
        f"frequent: expected heatwave losses reach {N['warm_loss_lo']} to {N['warm_loss_hi']}% in {N['warm_zones']} "
        f"(fig. S11). In a hypothetical deployment the model grows kelp on {N['kelp']} km² in {N['kelp_where']}, each at a "
        f"deployment cap of 1,000 km²{N['kelp_small']}. The cap is set in every run and lies within the shelf 10–100 m deep after half is set aside for other uses "
        f"[[etopo]]. The farms yield {N['kelp_mt']} Mt of dry biomass and need {N['kn']} kt of nitrogen a year, "
        f"{N['kn_fish_pct']}% of it from nearby salmon farms. Kelp saves only A${N['k_none']} billion a year, and the "
        f"conclusions above hold without it. Giant kelp forests of southeast Australia are a listed endangered ecological "
        f"community [[epbc_kelp]], and yields at this scale have not been demonstrated, so the kelp results describe a "
        f"hypothetical deployment, conditional on cultivation trials and approvals, not a forecast. If grown, the farms would be harvested by {N['gh']} cable-guided Grid Harvesters using a "
        f"third of the energy of conventional harvesters and tended by {N['drones']} solar-charged utility drones (figs. "
        f"S1, S2, S7 and S9).",
    ]),
    ("Where nuclear heat fits", [
        f"Refineries and distilleries in the 2050 system need only {N['heat']} TWh of process heat, so SMRs compete mainly as "
        f"electricity, which the calibrated system delivers to direct loads at about A${N['sh_el']} per MWh. The national "
        f"optimum builds reactors only below A${N['be_e']} billion per 300-MW module in the eastern fleet and {N['be_sa']} "
        f"billion at Port Augusta and Muja, against {N['mod2050']} billion at GenCost's 2050 cost and {N['mod_today']} "
        f"billion today (Fig. 4A).",
        f"The case is stronger during the transition, when gas and a carbon price set the value of steam. We screened two "
        f"modules at each proposed site from 2042–2046 with named heat users (Fig. 3A and table S9). At GenCost's 2045 cost "
        f"every site loses money; the seven together lose A${N['npv_fleet'].lstrip('-')} billion in net present value "
        f"(Fig. 4B). Muja is the least unprofitable, because the Worsley alumina refinery, 28 km away, can take all "
        f"{N['muja_steam']} TWh a year of its 165–180 °C steam [[aac_alumina,dwer_worsley]], and breaks even at "
        f"A${N['be_muja']} billion per module. Valued instead at the national model's shadow prices (A${N['nv_el']} per "
        f"MWh of electricity, {N['nv_steam']} per MWh of steam) throughout its life, Muja breaks even at "
        f"A${N['con_muja']} billion, or {N['con_muja_cap']} with a capacity payment equal to the turbines it would "
        f"displace. These are screening thresholds; the Worsley steam connection would need engineering validation.",
    ]),
    ("Water and feed", [
        f"Heat at 70–80 °C can drive multi-effect distillation: two modules at Port Augusta could distil {N['pa_water']} ML "
        f"of seawater a day, beside greenhouses that already distil seawater with solar heat [[sundrop]]. But distillation "
        f"costs A${N['med']} per m³ with reactor heat against {N['swro']} for reverse osmosis (Fig. 3B). Inland crops can "
        f"feed farmed seafood: least-cost diets for {N['prod50']} kt of salmon, prawns, barramundi and kingfish that meet "
        f"protein, lipid, EPA+DHA, lysine and methionine minima [[nrc2011]], with by-products fed across but never within "
        f"species [[eu1069]], use no wild fish for {N['ff_pct']}% more cost (fig. S8). This is a nutritional screening; "
        f"feeding trials must show that such diets keep growth and health.",
    ]),
    ("Emissions and uncertainty", [
        f"Life-cycle emissions of the energy supply fall from {N['wtw0']} to {N['wtw1']} Mt CO₂e a year ({N['wtw1_lo']}–"
        f"{N['wtw1_hi']} across factor ranges), using ICAO CORSIA default values for biofuels [[icao_corsia]] and harmonized "
        f"values for power [[nrel_lca]]. Solar panels ({N['pv_mt']} Mt) and canola with induced land-use change "
        f"({N['can_mt']} Mt) dominate; doubling land-use change gives {N['wtw_i2']} Mt and 5% methane leakage "
        f"{N['wtw_l5']} Mt. The boundary covers {N['wtw0']} Mt of fossil well-to-wheel emissions, of which {N['recon']} Mt is "
        f"combustion in the inventory's transport sector, against its 100.9 Mt (table S18). These emissions use the "
        f"chronological fleet's wind and solar output; the annual programme's own portfolio gives {N['wtw_annual']} Mt.",
    ]),
]

DISCUSSION = [
    f"Australia can replace all of its transport fuel with a system built mostly from solar, wind, residues and "
    f"electrofuels, at a cost that matches oil near US${N['be_brent']} per barrel if electrofuels, electrolysers and air "
    f"capture learn as assumed. Four findings are robust across our tests and ten years of observed weather: aviation "
    f"requires electrofuels and sets the price of liquid fuel; {N['disc_flex']}; catenary belongs on the "
    f"busiest eastern and southeastern corridors; and reactors do not earn a place in the long-run optimum, because a "
    f"solar-rich transport system needs little process heat and its firming is already cheap. Their best case is "
    f"industrial steam during the transition, at Muja, and even that needs modules at A${N['con_muja']}–{N['be_muja']} "
    f"billion, below projected costs. This agrees with studies finding that firm low-carbon resources pay where they "
    f"supply services that variable renewables supply poorly [[sepulveda,ruth,bragg]].",
    f"Two findings are conditional: kelp in {N['kelp_where']} lowers cost by only A${N['k_none']} billion a year and depends on "
    f"yields, nitrogen and approvals not yet demonstrated; and fish-free aquafeed is feasible on paper but needs feeding "
    f"trials. The main limits are the chronological model's capacity planning in three-hour steps (its fleet is verified "
    f"hour by hour) and three-node eastern grid, a hydrogen store larger than any demonstrated in rock or in Australia's "
    f"salt basins, SMR costs from overseas projects, heat users that need confirmation, and the "
    f"consent of Traditional Owners and sea-country rights holders. Within those limits, the analysis shows which parts "
    f"of a fossil-free transport system are settled by geography, weather and cost, and which still turn on "
    f"demonstration.",
]

SM_METHODS = [
    ("Scope, demand and prices", [
        "Demand is calendar-2025 sales from Australian Petroleum Statistics [[aps]]: automotive gasoline 15.82 GL, diesel "
        "33.52 GL, aviation turbine fuel 10.07 GL (58% international), aviation gasoline 0.07 GL, fuel oil 0.66 GL and "
        "automotive LPG 0.24 GL. Diesel is split into road, mining (8.7 GL), farm (2.3), construction (1.5), rail (1.2) and "
        "marine (0.4) uses [[ai_diesel,ieefa]]; 0.5 GL of other stationary diesel, non-automotive LPG, lubricants and other "
        "products are excluded (table S23). Energy contents and combustion factors follow the National Greenhouse "
        "Accounts Factors [[nga]], with a full-fuel-cycle ratio of 1.26 [[bitre]]. Costs are 2026 Australian dollars "
        "before GST and excise. Fossil benchmarks are pre-tax supply prices: retail less GST and excise for road fuels "
        "(APS quarterly retail for 2025; ACCC for October 2026, consistent with AIP terminal-gate prices plus the 2025 "
        "retail margin) [[accc,aip_tgp]], less 8 c/L off-road; IATA jet prices; and 0.9 × Brent for fuel oil, with EIA "
        "monthly Brent and RBA exchange rates [[eia,rba]]. Capital is annualized at 4% real (central) and 7% (today case).",
    ]),
    ("Annual optimization", [
        "The national model is a mixed-integer programme solved with HiGHS [[highs]] through SciPy [[scipy]]. Highway "
        "catenary corridors are binary: a built corridor carries its full annualized capital cost and may carry up to its "
        "modelled on-wire diesel. Shadow prices come from the linear programme re-solved with corridor decisions fixed. "
        "Wind and PV use GenCost 2025-26 capital costs (2050: A$2,207 and 1,029 per kW) [[gencost]] in three resource "
        "tiers, with firming, storage and network adders for direct loads and a network adder for flexible loads; these "
        "adders and the electrolyser utilisation are calibrated against the hourly model (below). Electrofuel, biofuel "
        "and residue parameters and caps are in table S2; catenary costs A$4.0 million per route-km (2.8–5.3 tested) "
        "[[hec_catenary]].",
    ]),
    ("Observed data", [
        "Hourly 100-m and 10-m wind, global and direct irradiance and temperature for 2015–2024 at 24 renewable-zone "
        "sites come from the ERA5 reanalysis [[era5]] through the Open-Meteo archive. Wind is converted with hourly shear "
        "to a 140-m hub and a generic 6.2-MW, 170-m-rotor power curve with 12% losses; PV with a single-axis tracker, "
        "DC/AC ratio 1.25, temperature derating and 12% losses. Each site with a matching zone in AEMO's 2026 Inputs and "
        f"Assumptions workbook [[aemo_isp]] is scaled to that zone's mean capacity factor (wind speed factors "
        f"{N['wind_scale_lo']}–{N['wind_scale_hi']}); sites without one keep raw ERA5 wind (fig. S10). Battery, turbine and "
        "electrolyser costs and efficiencies, connection costs and the median REZ transmission cost (A$0.77 million per "
        "MW) also come from that workbook. Ocean data are NOAA OISST v2.1 daily sea-surface temperature 1982–2026 "
        "[[oisst]] with marine heatwaves defined after Hobday et al. [[hobday]], World Ocean Atlas 2023 monthly nitrate "
        "[[woa23]], ERA5 ocean waves and ETOPO bathymetry [[etopo]]. AEMO half-hourly demand 2015–2024 is used to check "
        "when the transport system's firming need coincides with existing demand. All raw files are listed with URL, size "
        "and SHA-256 hash; download scripts reproduce them.",
    ]),
    ("Hourly model and calibration", [
        "The hourly model takes the annual solution's electricity loads, allocates direct loads to five grids by 2025 state "
        "fuel sales, gives light-vehicle charging half-managed daily profiles, trucks overnight and catenary daytime "
        "profiles, and runs mines, rail and heat flat. It chooses wind and PV capacity by state group (GenCost 2050 capital "
        "plus ISP connection and REZ transmission costs), battery power and energy separately (ISP 2050 four- and eight-hour "
        "costs; 92.5% efficiency each way), turbines on stored renewable methane (ISP OCGT cost; fuel at the annual model's "
        "methane price), electrolysers, a hydrogen store (A$1.5 per kWh, lined rock cavern; 0.3–15 tested) feeding "
        "synthesis that runs flat, and two new links within the National Electricity Market (A$3.28 and 2.5 million per MW, "
        "from ISP flow-path options). Capacities are optimized in three-hour steps over the weakest and the median resource "
        "year; each year 2015–2024 is then solved in three-hour steps with capacities fixed except turbines, and the "
        "largest turbine requirement at each node is kept. A one-hour adequacy pass repeats this for every year at one-hour "
        "resolution, pricing shortfalls at A$300,000 per MWh instead of the A$20,000 used in planning, so that turbines "
        "are added in any grid that would otherwise be short (reliability sizing; sized at A$20,000 they leave South "
        "Australia–Tasmania above the 0.002% standard). The final fleet, the larger turbine requirement of the two passes and every other capacity, is then "
        "fixed, identical in every year with nothing allowed to expand, and dispatched hour by hour for each of the ten "
        "years; this verification is what the reliability statements refer to. Marginal prices of the hourly balance "
        "allocate total cost to direct and flexible loads.",
        "The annual and chronological models are iterated. The annual model's firming adders are scaled, and its flexible "
        "network adder shifted, until it charges direct loads the hourly price plus distribution (its network adder less "
        "the hourly transmission cost) and flexible loads the hourly price plus electrolyser and storage costs; its "
        "electrolyser utilisation is set to the hourly value; and a constraint fixes the wind share of its wind and PV "
        "output to the hourly fleet's (curtailed energy included). The resulting loads go back to the chronological model, "
        "until direct and flexible prices change by less than A$1 per MWh, the wind share by less than one percentage point "
        "and electrofuel load by less than 1%. Reported system cost then replaces the annual model's electricity supply "
        "(generation and firming adders, electrolysers and hydrogen storage) by the annualized cost of the chronological "
        "model's final fleet, including new links and the turbines of the verification, turbine operating cost, a methane "
        "store and the distribution and flexible network adders; the turbines' methane is supplied and costed inside the "
        "annual model (below). Reported emissions use that fleet's wind and PV output (reconcile.py).",
        "Mechanism test. To ask whether electrolysers or flexibility as such firm the system, the electrofuel and "
        "air-capture electricity is re-solved as an equally large industrial demand with the same plant but a store "
        "limited to 24 hours of synthesis demand (daily flexibility) or no store (flat demand), with all other inputs "
        "unchanged. The seasonal and daily cases are re-optimised with the hydrogen store at A$5, 10 and 15 per kWh of "
        "hydrogen (central 1.5). Store sizes are given as the electrolyser input whose hydrogen they hold (MWh of "
        "electricity; hydrogen energy is 70% of it).",
        "Methane balance. The turbines burn renewable methane. Their ten-year mean fuel in the one-hour verification "
        "(turbine output / 38% efficiency), rounded up to 0.001 TWh, is a fixed demand in the annual model's methane "
        "balance, which waste biomethane (capped at 15 TWh), kelp methane or synthetic methane (electrolysis and "
        "methanation, 1.85 MWh of electricity, 0.198 t CO₂ and A$40 per MWh of methane in 2050) must meet, so the "
        "methane's supply, cost and life-cycle emissions are counted in the annual model. For this final solve the "
        "electrofuel, air-capture and process-heat electricity loads are held at the values the hourly fleet was designed "
        "and verified on, so closing the balance does not alter the hourly results; shadow prices and scenario "
        "differences come from the same case with those loads free. A ten-year inventory then tracks the methane store "
        "year by year over 2015–2024, repeated twice in sequence: constant annual production, each year's turbine "
        "withdrawals, and conservative ordering (all of a year's withdrawals before any of its production for the "
        "minimum, the reverse for the maximum). It gives the smallest opening inventory that never runs out and the "
        "capacity needed (table S20). The store costs A$3 per MWh-yr of capacity; its opening fill is valued at the "
        "methane shadow price and, with its supply-chain emissions, spread over 30 years; it would be filled from waste "
        "biomethane before the system is complete. Tests assert that the methane assigned covers the verified turbine "
        "fuel, that the inventory never falls below zero or exceeds capacity, and that it ends no lower than it began.",
        "Fuel production costs. Table S24 gives screening levelised costs of each fuel pathway from the model's inputs: "
        "feedstock, conversion and process heat, and for electrofuels electricity at the calibrated flexible price with "
        "electrolyser and hydrogen-storage costs and CO₂ from air capture. Today's costs use 7% finance and the 2050 case "
        "4%; 2030 and 2040 are linear interpolations. Only wind, solar, electrolysers, synthesis, air capture, kelp and "
        "finance learn; residue, lipid, ethanol and biomethane pathways keep today's costs. Costs exclude distribution, "
        "margins and taxes; litres are diesel-equivalent (10.7 kWh).",
        "Regional reliability. Unserved energy is reported for each modelled grid against the 0.002% expected-unserved-"
        "energy standards of the National Electricity Market (per region) [[aemc_rs]] and the Western Australian market "
        "[[wem_pc]]; the Northern Territory has no equivalent standard. The model's eastern grids merge New South Wales "
        "with Victoria and South Australia with Tasmania, and it has no forced outages, so it cannot establish "
        "compliance in each market region.",
        "Hydrogen storage. The store is costed as lined rock caverns or salt caverns at A$1.5 per kWh of hydrogen (0.3–15 "
        "tested). Large hydrogen storage has been demonstrated only in salt caverns, in Texas and at Teesside, UK, at up to a "
        "few hundred GWh per site; lined rock caverns have stored hydrogen only at pilot scale, 100 m³ at Luleå, Sweden, "
        "since 2022 [[hybrit]]. Australia has no operating cavern storage. Halite thick enough for caverns is proven in the "
        "Adavale Basin, Queensland, and identified in the Canning (Western Australia), Amadeus and Officer (central "
        "Australia) and offshore Polda (South Australia) basins [[bradshaw_salt]]. These lie hundreds of kilometres from "
        "most modelled electrolysers, so pipelines or lined rock caverns near the load would be needed; the stored volume "
        "in this study is an assumed capability, not a demonstrated one.",
    ]),
    ("Kelp", [
        "Nine kelp zones carry learning-target yields of 6–12 t dry ha⁻¹ yr⁻¹; farm cost scales from A$370 per dry tonne "
        "at 15 t ha⁻¹ [[greene]], and hydrothermal liquefaction yields 1.90 MWh of hydrocarbon and 0.31 MWh of methane per "
        "dry tonne [[anastasakis,elliott]]. Ocean data set four parameters by fixed rules: natural nitrogen share = months "
        "with mean nitrate ≥1 µmol/kg in 0–30 m / 12; expected heatwave loss = max(5%, 0.7 × share of 2005–2024 years with "
        "≥10 days above 20 °C for giant kelp or 23 °C for golden kelp); exposure factor = 1 + 0.03 × days a year with "
        "waves over 6 m; area = half the sea 10–100 m deep within 75 km of the zone centre, capped at 1,000 km² per zone in "
        "every run (table S22). Kelp holds 12 kg N per dry tonne; nearby fish farms supply the dissolved nitrogen they "
        "release within reach, and depth cycling the rest. Marine protected-area polygons were not used; the half set "
        "aside is an assumption. The giant kelp community's EPBC listing [[epbc_kelp]] means any lease would require referral.",
    ]),
    ("SMRs and heat cascades", [
        "Modules are BWRX-300-class (300 MWe, 870 MWth, 89% available, 40 years) with GenCost fixed and variable costs "
        "[[gencost]], in three fleets that sell electricity and up to 200 MWth per module of 150 °C steam into regional "
        "heat pools also served by heat pumps, thermal storage and electric boilers. Whole-module optima charge each new "
        "site A$1.75 billion of common infrastructure. The transition screen values electricity at regional prices plus a "
        "capacity value and steam at the avoided cost of gas with a carbon price (table S9); a consistent-pathway variant "
        "values both at the national model's shadow prices over the whole life. Distillation needs 70 kWh of heat and 1.8 "
        "kWh of electricity per m³; reverse osmosis 3.5 kWh.",
    ]),
    ("Life-cycle emissions", [
        "Emissions are energy-supply life-cycle values with biogenic combustion CO₂ counted as zero; vehicles and "
        "infrastructure are excluded. Electricity is counted once, at generation (wind 12, PV 35, nuclear 12 g/kWh "
        "[[nrel_lca]]). Biofuels use ICAO CORSIA default core and induced land-use-change values [[icao_corsia]] (table "
        "S17). Methane leakage of 1% (0–5% tested) is charged at a GWP100 of 27. Table S18 reconciles the boundary with "
        "the national inventory.",
    ]),
    ("Oil price, uncertainty and aquafeed", [
        "The fossil bill is interpolated linearly in Brent between the 2025 and October 2026 benchmarks; the break-even "
        "Brent price is where it equals system cost. The Monte Carlo analysis (1,000 draws, fixed seed) samples finance "
        "(3–7%), technology, kelp, residue, oil, catenary, firming (0.7–1.6 times the calibrated adders), electrolyser "
        "utilisation, hydrogen storage cost and a lognormal Brent price (median US$80, σ = 0.35). The aquafeed programme "
        "formulates least-cost diets meeting crude protein, lipid, EPA+DHA, total lysine and methionine [[nrc2011]] and "
        "binder minima, with crystalline amino acids allowed and by-products never fed to the same species (Regulation (EC) "
        "No 1069/2009, Art. 11(1)(d) [[eu1069]]).",
    ]),
    ("Reproducibility", [
        f"One command (python run_all.py) regenerates all outputs, figures, Source Data and documents from the processed "
        f"observed data and records measured step times; --recalibrate repeats the hourly calibration. test_model.py "
        f"({N['n_tests']} tests) checks demand conservation, fuel, electricity and heat balances, catenary accounting, kelp "
        f"bounds and nitrogen closure, the life-cycle sum, scenario monotonicity, the oil break-even identity, feed nutrient "
        f"minima, observed-data integrity, hourly reliability, calibration consistency and regression values; the build "
        f"stops if any fails.",
    ]),
    ("Use of artificial intelligence", [
        "Artificial Inventor/Synthetic Scientist V63, an AI agent system, was used for code development, data processing, "
        "numerical checks, plotting, drafting and document preparation. The prompts given to it by the corresponding "
        "author were: (i) “I need a similar article for Australia using maps of Australia, oceans, kelp farms, utility "
        "drones, the Grid Harvester, SMR reactors, wind and solar, seafood and shrimp farms, greenhouses, and heat cascades. "
        "Use the Canadian package as guidance. Use inland Australia to grow food for the fish, swap meals for cross species "
        "feeding, distill water, electrify Australia's major highways, and produce an entirely new package”; (ii) a "
        "request to fix overlapping text in the figures; (iii) requests to “fix what you agree with” in successive "
        "informal pre-submission reviews, to review the documents, to project the cost of producing the biofuels and to "
        "make the code run from a flat folder; and (iv) requests to write download scripts for weather, ocean, demand and price "
        "data and to use the downloaded files. The authors ran the downloads, checked the model, results and text, and take "
        "full responsibility for them.",
    ]),
]

REFDB = {
    "nggi": "Department of Climate Change, Energy, the Environment and Water (DCCEEW), Quarterly Update of Australia's National Greenhouse Gas Inventory: December 2025 (2026).",
    "aps": "DCCEEW, Australian Petroleum Statistics, data extract December 2025 (2026).",
    "ai_diesel": "The Australia Institute, Diesel use in Australian mining (May 2026).",
    "ieefa": "Institute for Energy Economics and Financial Analysis, Reward miners for conserving, not guzzling, diesel (6 October 2026).",
    "fuelplan": "Department of the Prime Minister and Cabinet, Fuel statistics, National Fuel Security Plan (fuelplan.gov.au, accessed 14 October 2026).",
    "eia": "U.S. Energy Information Administration, Europe Brent spot price FOB, monthly (series RBRTE, accessed 15 November 2026).",
    "accc": "Australian Competition and Consumer Commission, Weekly fuel price monitoring report (16 October 2026).",
    "davis": "S. J. Davis et al., Net-zero emissions energy systems. Science 360, eaas9793 (2018).",
    "sepulveda": "N. A. Sepulveda, J. D. Jenkins, F. J. de Sisternes, R. K. Lester, The role of firm low-carbon electricity resources in deep decarbonization of power generation. Joule 2, 2403–2420 (2018).",
    "ipcc": "Intergovernmental Panel on Climate Change, Climate Change 2022: Mitigation of Climate Change, Working Group III, chap. 10 (Cambridge Univ. Press, 2022).",
    "claytonutz": "Clayton Utz, A nuclear powered Australia? (March 2025).",
    "energymatters": "Energy Matters, Nuclear energy in Australia: the Coalition's September 2026 energy plan (2026).",
    "coalition_sites": "Liberal–National Coalition, Seven proposed nuclear sites (19 June 2024), as reported by SBS News and The Conversation.",
    "aemc_rs": "Australian Energy Market Commission, National Electricity Rules, clause 3.9.3C, Reliability standard (0.002% expected unserved energy per region per financial year).",
    "wem_pc": "Australian Energy Market Operator, 2023 Wholesale Electricity Market Electricity Statement of Opportunities (August 2023), Planning Criterion (WEM Rule 4.5.9).",
    "gas_storage": "Department of Industry, Science and Resources, Future Gas Strategy, chap. 5, table of gas storage facilities (Australian Government, 2024).",
    "hybrit": "HYBRIT Development, Fossil-free hydrogen storage in lined rock caverns ready for industrialization (SSAB, LKAB and Vattenfall, February 2025).",
    "bradshaw_salt": "M. Bradshaw et al., Australian salt basins: options for underground hydrogen storage. APPEA J. 63, 285-304 (2023).",
    "gencost": "P. Graham, J. Hayward, J. Foster, GenCost 2025-26: Final Report (CSIRO and AEMO, July 2026).",
    "bennett": "S. Bennett et al., The 'Great Southern Reef': social, ecological and economic value of Australia's neglected kelp forests. Mar. Freshw. Res. 67, 47–56 (2016).",
    "daff_aqua": "Department of Agriculture, Fisheries and Forestry, Australia's aquaculture industry (2026).",
    "tas_salmon": "Tasmanian Government, Salmon farming: tonnes produced state-wide, FY2023/24–FY2025/26 (2026).",
    "smith_shrimp": "D. M. Smith, G. L. Allan, K. C. Williams, C. G. Barlow, Fishmeal replacement research for shrimp feed in Australia. Avances en Nutrición Acuícola V (2000).",
    "skretting": "Skretting Australia, Annual production and feed composition 2022 (2023).",
    "spain_ssrn": "J. K. Bily, C. Pahl, P. Valdés Bacallao, Energy supply costs of a constrained fossil fuel phase out in Spanish transport. SSRN [Preprint] (2026). https://doi.org/10.2139/ssrn.7648876.",
    "era5": "H. Hersbach et al., The ERA5 global reanalysis. Q. J. R. Meteorol. Soc. 146, 1999–2049 (2020).",
    "aemo_isp": "Australian Energy Market Operator, Draft 2026 ISP Inputs and Assumptions workbook (AEMO, 2025).",
    "aemo_demand": "Australian Energy Market Operator, Aggregated price and demand data, NEM regions 2015-2024; WEM load summary 2015-2023 (accessed 15 November 2026).",
    "aip_tgp": "Australian Institute of Petroleum, Terminal gate prices, national average (data to 13 November 2026).",
    "woa23": "H. E. Garcia et al., World Ocean Atlas 2023, Volume 4: Dissolved Inorganic Nutrients (NOAA Atlas NESDIS 92, 2024).",
    "oisst": "B. Huang et al., Improvements of the Daily Optimum Interpolation Sea Surface Temperature (DOISST) Version 2.1. J. Clim. 34, 2923–2939 (2021).",
    "hobday": "A. J. Hobday et al., A hierarchical approach to defining marine heatwaves. Prog. Oceanogr. 141, 227–238 (2016).",
    "etopo": "C. Amante, B. W. Eakins, ETOPO1 1 Arc-Minute Global Relief Model (NOAA Technical Memorandum NESDIS NGDC-24, 2009).",
    "epbc_kelp": "Department of Sustainability, Environment, Water, Population and Communities, Listing advice and approved conservation advice for the Giant Kelp Marine Forests of South East Australia ecological community, endangered under the EPBC Act (August 2012).",
    "aac_alumina": "Australian Aluminium Council, Fact sheet 3: Alumina (2024).",
    "dwer_worsley": "Department of Water and Environmental Regulation, Western Australia, Licence L4504, Worsley Alumina Refinery (2025).",
    "sundrop": "Sundrop Farms, Port Augusta facility: 20 ha of greenhouses, solar tower and 1 ML per day of distilled seawater (2016).",
    "nrc2011": "National Research Council, Nutrient Requirements of Fish and Shrimp (National Academies Press, 2011).",
    "eu1069": "European Union, Regulation (EC) No 1069/2009 laying down health rules as regards animal by-products and derived products not intended for human consumption, Art. 11(1)(d). Off. J. Eur. Union L 300, 1–33 (2009).",
    "icao_corsia": "International Civil Aviation Organization, CORSIA Default Life Cycle Emissions Values for CORSIA Eligible Fuels, ICAO document 06 (June 2025).",
    "nrel_lca": "National Renewable Energy Laboratory, Life Cycle Greenhouse Gas Emissions from Electricity Generation: Update (NREL/FS-6A50-80580, 2021).",
    "ruth": "M. F. Ruth et al., Nuclear-renewable hybrid energy systems: opportunities, interconnections, and needs. Energy Convers. Manag. 78, 684–694 (2014).",
    "bragg": "S. M. Bragg-Sitton et al., Reimagining future energy systems: overview of the US program to maximize energy utilization via integrated nuclear-renewable energy systems. Int. J. Energy Res. 44, 8156–8169 (2020).",
    "nga": "DCCEEW, National Greenhouse Accounts Factors 2025 (2025).",
    "bitre": "Bureau of Infrastructure and Transport Research Economics, Australian Infrastructure and Transport Statistics Yearbook 2025, chap. 9 (2025).",
    "rba": "Reserve Bank of Australia, Statistical table F11.1, Exchange rates (accessed 15 November 2026).",
    "highs": "Q. Huangfu, J. A. J. Hall, Parallelizing the dual revised simplex method. Math. Program. Comput. 10, 119–142 (2018).",
    "scipy": "P. Virtanen et al., SciPy 1.0: fundamental algorithms for scientific computing in Python. Nat. Methods 17, 261–272 (2020).",
    "hec_catenary": "C. Kayser-Bril, J. Whitmore, Overhead catenary trucking on the A20-H401 corridor (HEC Montréal, 2023).",
    "greene": "J. M. Greene, J. Gulden, G. Wood, M. Huesemann, J. C. Quinn, Techno-economic analysis and global warming potential of a novel offshore macroalgae biorefinery. Algal Res. 51, 102032 (2020).",
    "anastasakis": "K. Anastasakis, A. B. Ross, Hydrothermal liquefaction of the brown macro-alga Laminaria saccharina. Bioresour. Technol. 102, 4876–4883 (2011).",
    "elliott": "D. C. Elliott, P. Biller, A. B. Ross, A. J. Schmidt, S. B. Jones, Hydrothermal liquefaction of biomass: developments from batch to continuous process. Bioresour. Technol. 178, 147–156 (2015).",
}

# number references in order of first citation: main text, then Supplementary Materials (Science style)
_CITE = re.compile(r"\[\[([^\]]+)\]\]")
_ORDER = []


def _scan(text):
    for m in _CITE.finditer(text):
        for k in m.group(1).split(","):
            k = k.strip()
            if k not in REFDB:
                raise KeyError(f"unknown reference key {k}")
            if k not in _ORDER:
                _ORDER.append(k)


for _t in INTRO + [t for _, ps in RESULTS for t in ps] + DISCUSSION:
    _scan(_t)
N_MAIN_REFS = len(_ORDER)
for _t in [t for _, ps in SM_METHODS for t in ps]:
    _scan(_t)
REFS = [REFDB[k] for k in _ORDER]


def cite(text):
    def rep(m):
        nums = sorted(_ORDER.index(k.strip()) + 1 for k in m.group(1).split(","))
        parts, i = [], 0
        while i < len(nums):
            j = i
            while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
                j += 1
            parts.append(f"{nums[i]}" if j == i else (f"{nums[i]}, {nums[j]}" if j == i + 1 else f"{nums[i]} to {nums[j]}"))
            i = j + 1
        return "(" + ", ".join(parts) + ")"
    return _CITE.sub(rep, text)


DATA_AV = ("Model inputs (with a machine-readable provenance table), processed observations (hourly capacity factors, "
           "demand, ocean, price and fuel-sales data), scenario definitions, outputs and Source Data for Figs. 1 to 5 are "
           "in the supplementary materials. Raw downloads (ERA5, OISST, World Ocean Atlas, ETOPO, AEMO, EIA, RBA, AIP and "
           "government workbooks) are not redistributed; a manifest lists each with URL, size and SHA-256 hash, and the "
           "supplied scripts download and process them. The code (Python, MIT licence) reproduces every number, figure and document with one command "
           "and runs automated tests on each build. All code and data are publicly available at "
           "https://github.com/bcjohnjr/Australia-SMR-Kelp-Renewable-Transport-System; a versioned snapshot will be archived with a DOI "
           "before publication.")

LEGENDS = [
    ("Fig. 1. Australia's fossil-free transport system in 2050 and the proposed SMR sites.",
     " Highways built with catenary in the least-cost solution (each corridor a yes-or-no investment), kelp farms (filled) "
     "and kelp zones not chosen (dashed), inland crop belts that grow fish-feed protein and oil, heat and seafood users, "
     "ocean currents, and the seven proposed SMR sites (circles; two modules) and a one-module test site at Gladstone "
     "(square), labelled with net present value and break-even module capital (A$ billion) under central transition "
     "assumptions. Coastline generalized."),
    ("Fig. 2. Annual replacement of Australian transport energy in the central 2050 case.",
     " (A) Fossil energy replaced in each segment, by the carrier that replaces it. (B) Renewable liquid and gaseous fuels "
     "by source; methane includes " + N["ch4_turb"] + " TWh a year burnt by the firming turbines. (C) Electricity available from the hourly model's final wind and solar fleet (ten-year mean, curtailed "
     "energy included) and its uses."),
    ("Fig. 3. Heat cascades and distilled water.",
     " (A) First-year output of each SMR site: electricity, 150 to 180 °C steam, 70 to 80 °C heat for distillation and "
     "greenhouses, and 38 °C distillation reject heat used by greenhouses and recirculating seafood farms; labels give "
     "distilled water. (B) Levelized cost of water from multi-effect distillation (MED) with reactor, solar-thermal or gas "
     "heat, and with reject heat sold at the Port Augusta hub, against seawater reverse osmosis (SWRO)."),
    ("Fig. 4. SMR economics.",
     " (A) Annual saving of the 2050 national optimum with SMRs allowed, against module capital (continuous solution, "
     "without site infrastructure), with break-even capital by fleet and the best whole-module fleet including site "
     "infrastructure. (B) Net present value of each transition site under central assumptions (gas and carbon-price "
     "values), with a brownfield site cost, with A$3.0 billion modules and A$0.9 billion sites, and with electricity, steam "
     "and capacity valued at the national model's shadow prices throughout."),
    ("Fig. 5. Highways, firming and oil price.",
     " (A) Catenary cost per MWh of diesel replaced on each corridor at full use (blue: built; grey: not built). (B) Hourly "
     "model, National Electricity Market: supply by source and demand in the 14 days with the least wind and solar output "
     "of the weakest design year, with the calibrated capacities. (C) Cost of electricity to direct loads: the annual model "
     "before calibration, the hourly model with electrolysers, with their energy as an equally large industrial demand "
     "that can shift only within a day or not at all, without them (also at 7% finance), and the "
     "calibrated annual model. The band shows GenCost's 2050 net-zero system cost for context only; it is not "
     "like-for-like, since it covers the whole grid with existing demand, distribution-connected supply and "
     "system-security services. Annual-model values include a distribution charge (A$" + N["dist"] + " per MWh) that "
     "the hourly model does not represent. (D) Break-even Brent oil price across 1,000 Monte Carlo draws, against the 2025 "
     "and October 2026 prices and the central case."),
]
LEGEND_S8 = ("Fig. S8. Feeding farmed seafood from inland Australia (nutritional screening).",
             " (A) Wild fish used and feed cost (labels) for 2050 production under five feed policies. (B) Inland cropland "
             "by crop. (C) Cross-species swap of rendered by-product meal and oil (same-species feeding banned). (D) "
             "Margins of pond and recirculating (RAS) prawns and barramundi with cascade, heat-pump or gas heat, and of "
             "salmon and kingfish blocks with utility robots.")
# ------------------------------------------------------------------------------------------ docx helpers
LINE = [1.25]


def style(doc, size=10.5, review=False):
    """review=True: Science review format, 12-point Times New Roman, double spacing, one-inch margins."""
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman" if review else "Arial"
    st.font.size = Pt(12 if review else size)
    LINE[0] = 2.0 if review else 1.25
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2.54 if review else 2.2)
        s.top_margin = s.bottom_margin = Cm(2.54 if review else 2.0)


def rich(p, text, bold=False, size=None, italic=False):
    for part in re.split(r"(\^\{[^}]*\})", text):
        if not part:
            continue
        sup = part.startswith("^{")
        r = p.add_run(part[2:-1] if sup else part)
        r.font.superscript = sup
        r.bold = bold
        r.italic = italic
        if size:
            r.font.size = Pt(size)
    return p


def para(doc, text, bold=False, size=None, space=6, align=None, italic=False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space)
    p.paragraph_format.line_spacing = LINE[0]
    if align == "c":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rich(p, text, bold, size, italic)
    return p


def head(doc, text, size=12):
    p = para(doc, text, bold=True, size=size, space=4)
    p.paragraph_format.space_before = Pt(8)
    return p


def table(doc, header, rows, size=7.5, widths=None):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(str(h))
        r.bold = True
        r.font.size = Pt(size)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(v))
            r.font.size = Pt(size)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def words(paras):
    return sum(len(re.sub(r"\^\{[^}]*\}", "", p).split()) for p in paras)


# ------------------------------------------------------------------------------------------ manuscript
def manuscript():
    doc = Document()
    style(doc, review=True)
    para(doc, TITLE, bold=True, size=14, space=8)
    para(doc, AUTHORS, size=12)
    para(doc, AFFIL, size=12, italic=True, space=10)
    p = para(doc, "One-sentence summary: ", bold=True, space=8)
    rich(p, SUMMARY)
    head(doc, "Abstract", 11)
    para(doc, ABSTRACT)
    for t in INTRO:
        para(doc, cite(t))
    for h, ps in RESULTS:
        head(doc, h, 10.5)
        for t in ps:
            para(doc, cite(t))
    head(doc, "Discussion", 10.5)
    for t in DISCUSSION:
        para(doc, cite(t))
    head(doc, "References and Notes")
    for i, r in enumerate(REFS, 1):
        para(doc, f"{i}. {r}", size=12, space=2)
    para(doc, f"References {N_MAIN_REFS + 1} to {len(REFS)} are cited only in the supplementary materials.", size=12,
         italic=True)
    head(doc, "Acknowledgments", 10.5)
    for lab, txt in (
            ("Funding: ", "This research received no external funding."),
            ("Author contributions: ", "J.K.B. conceived the study, developed the methodology and software and wrote the "
             "original draft. C.P. contributed to the software and reviewed and edited the manuscript. P.V.B. contributed to "
             "the visualization and reviewed and edited the manuscript. All authors approved the submission."),
            ("Competing interests: ", "The authors declare no competing interests."),
            ("Data and materials availability: ", DATA_AV),
            ("Use of artificial intelligence: ", "Artificial Inventor/Synthetic Scientist V63, an AI agent system, was used "
             "for code development, numerical checks, plotting, drafting and document preparation. Its use, version and the "
             "prompts given to it are described in the supplementary materials (Materials and Methods). The authors "
             "verified the code, results and text and are responsible for all content; the tool is not an author and is "
             "not cited as a source.")):
        p = para(doc, "")
        p.add_run(lab).bold = True
        rich(p, txt)
    head(doc, "Supplementary Materials", 10.5)
    para(doc, "Materials and Methods; Supplementary Text; Figs. S1 to S13; Tables S1 to S24; References "
              f"({N_MAIN_REFS + 1} to {len(REFS)}); Data S1 (input provenance table, model outputs and Source Data); "
              "Code S1 (model and document code).")
    head(doc, "Figure legends")
    for b, t in LEGENDS:
        p = doc.add_paragraph()
        p.add_run(b).bold = True
        p.add_run(t)
    names = ["Fig1_system_map", "Fig2_complete_replacement", "Fig3_heat_cascade", "Fig4_smr_economics",
             "Fig5_highways_firming_oil"]
    for (b, _), n in zip(LEGENDS, names):
        doc.add_page_break()
        doc.add_picture(str(FIG / f"{n}.png"), width=Cm(16.5))
        para(doc, b, bold=True, size=9)
    path = PKG / "Submission" / "Manuscript_Science.docx"
    doc.save(path)
    main = INTRO + [t for _, ps in RESULTS for t in ps] + DISCUSSION
    meth = [t for _, ps in SM_METHODS for t in ps]
    return path, words([_CITE.sub("", t) for t in main]), words([ABSTRACT]), words([_CITE.sub("", t) for t in meth])


# ------------------------------------------------------------------------------------------ SI
def si():
    doc = Document()
    style(doc, 9.5)
    para(doc, "Supplementary Materials for", size=11)
    para(doc, TITLE, bold=True, size=13)
    para(doc, AUTHORS, size=9)
    para(doc, "Corresponding author: jonathan@cloudwashlaundry.com", size=9)
    para(doc, "This PDF file includes: Materials and Methods; Supplementary Text; Figs. S1 to S13; Tables S1 to S24; "
              f"References {N_MAIN_REFS + 1} to {len(REFS)}. Other Supplementary Materials: Data S1 (input_provenance.csv, "
              "outputs and Source Data), Code S1.", size=8.5, italic=True)
    head(doc, "Materials and Methods")
    for h, ps in SM_METHODS:
        head(doc, h, 10)
        for x in ps:
            para(doc, cite(x), size=9)
    para(doc, "Table S1. Automated tests run on every build (test_model.py).", bold=True)
    import test_model as TM
    table(doc, ["Test", "What it asserts"],
          [(n, re.sub(r"\s+", " ", f.__doc__ or "").strip() or n.replace("test_", "").replace("_", " "))
           for n, f in vars(TM).items() if n.startswith("test_")])
    head(doc, "Supplementary Text")
    head(doc, "S1. Inputs and learning levers", 10)
    para(doc, "Principal inputs are summarised below; the full list with source, date, units and tested range is the "
              "machine-readable file input_provenance.csv (Supplementary Data). Fossil benchmark prices are pre-tax supply "
              "prices.")
    rows = [(s, f0(D[s]), f1(I.fossil_price(s, "avg2025")), f1(I.fossil_price(s, "oct2026")), f"{I.co2_t_per_mwh(s):.3f}")
            for s in D]
    para(doc, "Table S2A. Demand (2025), fossil pre-tax prices and well-to-wheel factors.", bold=True)
    table(doc, ["Segment", "TWh/yr", "AUD/MWh 2025", "AUD/MWh Oct 2026", "t CO₂e/MWh"], rows)
    p = O_base = __import__("optimise").base_params()
    rows = [("Wind capital (2050 / today), AUD/kW", "2,207 / 3,248", "GenCost 2025-26"),
            ("Solar PV capital (2050 / today), AUD/kW", "1,029 / 1,621", "GenCost 2025-26"),
            ("Electrolyser capital (2050 / today), AUD/kW", "1,856 / 2,100", "GenCost 2025-26"),
            ("e-FT: electricity per MWh fuel; synthesis cost", "2.40; AUD 70 (95 today)", "screening"),
            ("Direct air capture", "AUD 500/t (800 today), 1.5 MWh/t", "screening"),
            ("Cereal straw (cap, cost, yield, conversion)", "12 Mt, AUD 90/odt, 2.2 MWh/odt, AUD 95/MWh", "screening"),
            ("Cane trash and bagasse; plantation residues", "4 Mt each, AUD 60 and 95/odt", "screening"),
            ("Tallow and UCO HEFA; canola HVO", "6 TWh at AUD 205; 12 TWh at AUD 225/MWh", "screening"),
            ("Sorghum, cane and molasses ethanol", "8 TWh at AUD 140/MWh, 0.34 MWh heat/MWh", "screening"),
            ("Waste biomethane", "15 TWh at AUD 85/MWh", "screening"),
            ("Heat pool shares reachable by SMR steam", "SA 60%, WA 70%, VIC 100%, inland 30%, TAS/SE 0", "Methods"),
            ("Steam delivery, AUD/MWh_th", "SA 8, WA 14, VIC 16, inland 8", "screening")]
    para(doc, "Table S2B. Supply parameters (central learning case).", bold=True)
    table(doc, ["Parameter", "Value", "Source"], rows)
    para(doc, "Table S3A. Learning levers applied cumulatively from today's costs.", bold=True)
    table(doc, ["Step", "System cost, AUD bn/yr", "Kelp km²"], [(r["step"], f2(r["cost_bn"]), f0(r["kelp_km2"])) for r in R["levers"]])

    head(doc, "S2. National scenarios", 10)
    sc = [("Central (learning, 4%)", R["central"]), ("Today's costs, 7%", R["today"]),
          ("Electric or biofuel only*", R["electric_or_biofuel"]), ("No catenary", R["ers_none"]),
          ("All eight corridors electrified", R["ers_all"]), ("Less demand (aviation −20%, shipping −10%, mining −15%)", R["less_demand"])]
    para(doc, "Table S3B. National scenarios (2050).", bold=True)
    table(doc, ["Case", "Cost AUD bn", "Kelp km²", "Wind GW", "PV GW", "Electrofuels TWh", "DAC Mt", "Catenary km", "WTW cut %"],
          [(n, f2(d["cost_bn"]), f0(d["kelp_km2"]), f0(d["wind_gw"]), f0(d["pv_gw"]), f0(d["efuels_twh"]), f1(d["dac_mt"]),
            f0(d["ers_km"]), f1(d["wtw_reduction_pct"])) for n, d in sc])
    para(doc, f"*Infeasible within the biomass caps: {N['eb_short']} TWh of liquid fuel unmet; cost shown for the supplied part.",
         size=8)

    head(doc, "S3. Kelp zones, nitrogen and conservation", 10)
    para(doc, re.sub(r"\s+", " ", K.__doc__).strip(), size=8.5)
    para(doc, "Table S4. Kelp zones (learning-target yields after expected heatwave loss) and nitrogen supply.", bold=True)
    table(doc, ["Zone", "Species", "Yield t/ha/yr", "Area cap km²", "Pool", "AUD/dry t", "AUD/MWh fuel", "N t/km²",
                "Natural N %", "Fish-farm N %", "Chosen km²"],
          [(r["name"], r["species"].split(" (")[1].rstrip(")"), f1(r["yield_eff"]), f0(r["area_km2"]), r["pool"],
            f0(r["cost_aud_t"]), f0(r["aud_per_mwh_fuel"]), f1(r["n_kg_km2"] / 1000), f0(100 * r["natural_share"]),
            f1(100 * r["imta_share"]), f0(C["kelp_km2"][z])) for z, r in zt.items()], size=6.5)
    para(doc, "Table S5. Kelp sensitivities: area caps, nitrogen, yield levels and forcing kelp into zones not chosen.", bold=True)
    table(doc, ["Case", "Kelp km²", "N kt/yr", "Extra cost, AUD bn/yr"],
          [(k, f0(v["kelp_km2"]), f1(v["n_kt"]), f"+{f2(v['extra_bn'])}") for k, v in SC.items()]
          + [(f"Forced: {v['name']}", f0(v["area_km2"]), "", f"+{f2(v['extra_bn'])}") for v in kf.values()]
          + [(f"Yield level: {k}", f0(v["kelp_km2"]), "", f"{f2(v['cost_bn'] - C['objective_bn']):s}") for k, v in ky.items()])

    head(doc, "S4. Highway corridors", 10)
    para(doc, "Table S6. Corridors (binary build decisions).", bold=True)
    table(doc, ["Corridor", "km", "Heavy vehicles/day", "On-wire diesel TWh", "Catenary AUD/MWh at full use", "Built",
                "Traffic on wire TWh"],
          [(c, f0(r["km"]), f0(r["aadt"]), f2(r["twh_diesel"]), f0(r["aud_per_mwh"]), "yes" if r["built"] else "no",
            f2(r["chosen_twh"])) for c, r in ec.items()])

    head(doc, "S5. SMRs in the national optimum", 10)
    para(doc, "Table S7. Continuous capital sweep (no site infrastructure).", bold=True)
    table(doc, ["Module AUD bn", "Saving AUD M/yr", "GW built", "Steam TWh"],
          [(f2(r["module_bn"]), f0(1000 * r["saving_bn"]), f2(r["gw"]), f2(r["steam_twh"])) for r in R["smr_capex_sweep"]])
    para(doc, "Table S8. Whole-module enumeration (best six fleets; site infrastructure AUD 1.75 bn per new site).",
         bold=True)
    rows = []
    for m in ("4.6", "2.5"):
        for r in R["smr_whole_modules"][m]["rows"][:6]:
            rows.append((m, r["sa"], r["wa"], r["east"], r["sites"], f0(1000 * r["saving_bn"]), f2(r["steam_twh"])))
    table(doc, ["Module AUD bn", "SA", "WA", "East", "Sites", "Saving AUD M/yr", "Steam TWh"], rows)

    head(doc, "S6. Transition site heat-cascade screen", 10)
    import cascade as CS
    para(doc, re.sub(r"\s+", " ", CS.__doc__).strip(), size=8.5)
    rows = []
    for s, users in CS.USERS.items():
        for (u, st, mwh, lf, km, ex) in users:
            rows.append((s, u, st, f0(mwh / 1e3), f"{lf:.2f}", f0(km)))
    para(doc, "Table S9. Heat users at each site (GWh_th/yr at full take). The Worsley steam connection needs engineering validation (main routing, losses, digestion temperatures and contracts).", bold=True)
    table(doc, ["Site", "User", "Stage", "GWh/yr", "Load factor", "Main km"], rows, size=7)
    para(doc, "Table S10. Site NPV (AUD bn) by variant, and break-even module capital, including the consistent national pathway.", bold=True)
    sites = list(S)
    hdr = ["Variant"] + [x.replace(" (test)", "*") for x in sites] + ["Coalition seven"]
    rows = [[v] + [f2(V[v][x]) for x in sites] + [f1(V[v].get("fleet_coalition", sum(V[v][x] for x in sites if I.SITES[x].get("coalition"))))] for v in V]
    rows.append(["Break-even module, AUD bn"] + [f2(BE[x]) for x in sites] + [""])
    rows.append(["Break-even, site AUD 0.9 bn"] + [f2(BEB[x]) for x in sites] + [""])
    for k, d in CON.items():
        rows.append([f"Break-even, {k}"] + [f2(d[x]) for x in sites] + [""])
    table(doc, hdr, rows, size=6.5)
    para(doc, "Table S11. Levelized water cost (AUD/m³).", bold=True)
    table(doc, ["Case", "Heat", "Electricity", "Capital", "O&M", "Intake", "Reject credit", "Total"],
          [(k, f2(v["heat"]), f2(v["energy"]), f2(v["capital"]), f2(v["om"]), f2(v["intake"]), f2(v["reject_credit"]),
            f2(v["total"])) for k, v in wc.items()])

    head(doc, "S7. Aquafeed (nutritional screening feasibility)", 10)
    para(doc, re.sub(r"\s+", " ", FD.__doc__).strip(), size=8.5)
    para(doc, "Table S12. Feed ingredients (CP crude protein; Lys and Met total lysine and methionine).", bold=True)
    table(doc, ["Ingredient", "CP", "Lipid", "EPA+DHA", "Lys", "Met", "AUD/t", "Max incl.", "Group", "t/ha"],
          [(k, v[0], v[1], v[2], FD.AA.get(k, (0, 0))[0], FD.AA.get(k, (0, 0))[1], f0(v[3]), v[4], v[5], v[6] or "")
           for k, v in FD.ING.items()], size=6.5)
    table(doc, ["Species", "CP min", "Lipid min", "EPA+DHA min", "Lys min", "Met min", "Binder min"],
          [(sp, d["cp"], d["lipid"], d["epadha"], d["lys"], d["met"], d["binder"]) for sp, d in FD.SPEC.items()], size=7)
    rows = []
    for y in ("2025", "2050"):
        for c, d in F[y].items():
            rows.append((y, c, f1(d["cost_aud_m"]), f0(d["cost_aud_t"]), f1(d["wild_fish_t"] / 1e3), f"{d['fifo']:.2f}",
                         f0(d["cropland_total_ha"] / 1e3)))
    para(doc, "Table S13. Feed cases.", bold=True)
    for k, d in F["sensitivity"].items():
        rows.append(("2050", f"sensitivity: {k}", f1(d["cost_aud_m"]), f0(d["cost_aud_t"]), f1(d["wild_fish_t"] / 1e3),
                     f"{d['fifo']:.2f}", f0(d["cropland_total_ha"] / 1e3)))
    table(doc, ["Year", "Case", "Cost AUD M", "AUD/t", "Wild fish kt", "FIFO", "Cropland kha"], rows)

    head(doc, "S8. Co-production, lulls, uncertainty and accounts", 10)
    para(doc, "Table S14. Co-production results (screening, outside the energy cost).", bold=True)
    rows = [("Grid Harvesters", f0(gh["units"]), f"{f1(gh['energy_gwh'])} GWh/yr (conventional {f1(gh['conventional_gwh'])})"),
            ("Shellfish sites", N["sh_sites"], f"{N['mussel']} t mussels, {N['oyster']} t oysters; margin AUD {N['sh_man']}–{N['sh_best']} M"),
            ("Utility drones", N["drones"], f"AUD {f1(dr['annual_aud_m'])} M/yr, {N['dr_pct']}% of farm cost"),
            ("Salmon block 50 kt with 1,544 robots", "", f"break-even AUD {N['sal_be']}/kg"),
            ("Kingfish block 10 kt with 300 robots", "", f"break-even AUD {N['kf_be']}/kg"),
            ("Pond prawns (Queensland)", "", f"cost AUD {N['pond_cost']}/kg"),
            ("RAS prawns, cascade / heat pump / gas", "", " / ".join(f2(CP['prawn_ras'][k]['cost_aud_kg']) for k in CP['prawn_ras']) + " AUD/kg"),
            ("RAS barramundi, cascade / heat pump / gas", "", " / ".join(f2(CP['barra_ras'][k]['cost_aud_kg']) for k in CP['barra_ras']) + " AUD/kg")]
    table(doc, ["Item", "Number", "Result"], rows)
    para(doc, "Table S15. Winter lulls inside the optimization (screening; battery credit 60, 30 and 0%).", bold=True)
    table(doc, ["Event", "Methane reserve TWh", "Turbines GW", "Cost AUD bn", "Extra AUD bn"],
          [(e["event"], f2(e["methane_twh"]), f1(e["turbine_gw"]), f2(e["cost_bn"]), f2(e["extra_bn"])) for e in A["events"]])
    para(doc, "Table S16. Monte Carlo (1,000 draws), oil break-even and accounts.", bold=True)
    em = AC["emissions"]
    table(doc, ["Item", "Value"], [
        ("Median system cost, AUD bn (5th–95th)", f"{N['mc_med']} ({N['mc5']}–{N['mc95']})"),
        ("Draws cheaper than fossil at 2025 / Oct 2026 prices (reference points)", f"{MC['beat_2025']} / {MC['beat_oct2026']}"),
        ("Break-even Brent, central / today's costs, US$/bbl", f"{N['be_brent']} / {N['be_brent_today']}"),
        ("Break-even Brent across draws, median (5th–95th), US$/bbl", f"{N['mc_be']} ({N['mc_be5']}–{N['mc_be95']})"),
        ("Draws cheaper than fossil at an independently sampled Brent price", f"{N['mc_cheap']} of 1,000"),
        ("Catenary km across draws, median (5th–95th)", f"{f0(MC['ers_km_median'])} ({f0(MC['ers_km_p5'])}–{f0(MC['ers_km_p95'])})"),
        ("Draws with kelp; 95th percentile area", f"{N['mc_k']}; {N['mc_k95']} km²"),
        ("Scope-1 emissions of fuel in scope, Mt (international memo)", f"{f1(em['scope1_all_mt'])} ({f1(em['scope1_international_mt'])})"),
        ("Energy-supply life cycle, fossil / system, Mt", f"{N['wtw0']} / {N['wtw1']} ({N['wtw1_lo']}–{N['wtw1_hi']})"),
        ("Avoided 2025–2050 vs electrification only, Mt", N["trans"]),
        ("Fuel excise gross / net of fuel tax credits, AUD bn", f"{N['exc_gross']} / {N['exc_net']}"),
        ("Road-user charge to replace net excise", f"AUD {N['ruc']} per MWh of road electricity")])

    head(doc, "S9. Life-cycle emissions and boundary", 10)
    para(doc, "Table S17. Energy-supply life-cycle factors, sources and contributions, annual-model "
              "accounting (the annual programme's own wind and solar portfolio). The reported total, with the hourly "
              "model's final fleet, is " + N["wtw1"] + " Mt (main text; table S21).", bold=True)
    LC = __import__("optimise").LCA
    parts = LS["parts"]
    table(doc, ["Item", "Core t/MWh", "ILUC t/MWh", "Range t/MWh", "Mt CO₂e", "Source"],
          [(k, f"{d['core']:.3f}", f"{d['iluc']:.3f}", f"{d['lo']:.3f}–{d['hi'] + d['iluc']:.3f}", f2(parts.get(k, 0.0)), d["src"])
           for k, d in LC.items()] + [("methane leakage (1%)", "", "", "0–5%", f2(parts["methane_leakage"]), "GWP100 27 (AR6)")],
          size=6.5)
    table(doc, ["Sensitivity", "Mt CO₂e/yr", "Reduction %"],
          [("Central", f1(LS["central"]), f1(LS["reduction_pct"]["central"])),
           ("All factors low", f1(LS["lo"]), f1(LS["reduction_pct"]["lo"])),
           ("All factors high, 3% leakage", f1(LS["hi"]), f1(LS["reduction_pct"]["hi"]))]
          + [(f"ILUC x{k}", f1(v), f1(100 * (1 - v / LS["fossil_wtw"]))) for k, v in LS["iluc"].items()]
          + [(f"Methane leakage {float(k) * 100:.0f}%", f1(v), f1(100 * (1 - v / LS["fossil_wtw"]))) for k, v in LS["ch4_leak"].items()]
          + [("Electrofuel intensity with this grid, FT / methanol / ammonia (g/kWh)",
              " / ".join(f0(1000 * LS["efuel_intensity"][k]) for k in ("ft", "methanol", "ammonia")), "")])
    para(doc, "Table S18. Reconciliation of the study boundary with the national inventory (Mt CO₂e, 2025).", bold=True)
    table(doc, ["Step", "Mt CO₂e"], [(r[0], f1(r[1])) for r in ACC["reconciliation"]])

    head(doc, "S10. Hourly model, calibration and observed data", 10)
    para(doc, "Table S19. Hourly model: final fleet by grid (design years " + N["design_years"] + "; turbines after the "
              "three-hour checks and the one-hour adequacy pass over 2015-2024).", bold=True)
    rows = []
    for n_, v in sysd.items():
        rows.append((n_, f1(v["wind_gw"]), f1(v["pv_gw"]), f1(v["battery_gw"]), f0(v["battery_gwh"]),
                     f2(VER["turbine_gw_by_node"][n_]), f1(v["electrolyser_gw"]), f0(100 * v["electrolyser_cf"]),
                     f0(v["h2_store_gwh_el"]), f1(v["direct_twh"]), f1(v["flexible_twh"]), f0(v["price_direct_aud_mwh"]),
                     f0(v["price_flex_aud_mwh"])))
    table(doc, ["Grid", "Wind GW", "PV GW", "Battery GW", "Battery GWh", "Turbines GW", "Electrolysers GW", "Elz CF %",
                "H2 store GWh(el)", "Direct TWh", "Flexible TWh", "Direct AUD/MWh", "Flexible AUD/MWh"], rows, size=6.3)
    para(doc, "New links: " + ", ".join(f"{k} {v:.2f} GW ({dz['link_flow_twh'][k]:.1f} TWh/yr)" for k, v in dz["links_gw"].items())
         + f". Curtailment {N['h_curt']}% of generation.", size=8.5)
    para(doc, "Table S20. Each weather year: three-hour check with the design capacities fixed (turbines may be added) "
              "and one-hour verification of the final fleet (every capacity fixed, identical in all years).", bold=True)
    table(doc, ["Year", "Resource index", "3-h: turbines needed GW", "1-h: turbine output TWh", "1-h: largest grid turbine output GW",
                "1-h: battery output TWh", "1-h: curtailment TWh", "1-h: unserved MWh"],
          [(y, f"{DSP['resource_index'][str(y)]:.3f}", f2(v["turbine_gw"]), f2(VER["years"][str(y)]["turbine_twh"]),
            f1(VER["years"][str(y)]["turbine_peak_gw"]), f1(VER["years"][str(y)]["battery_twh_out"]),
            f1(sum(VER["years"][str(y)]["curtail_twh_by_node"].values())), f0(VER["years"][str(y)]["unserved_mwh"]))
           for y, v in DSP["years"].items()], size=7)
    para(doc, "Unserved energy by modelled grid in the one-hour verification (standard: 0.002% expected unserved energy "
              "per NEM region and in the WEM; NSW/VIC and SA/TAS each merge two NEM regions; no outages modelled).",
         size=8.5)
    table(doc, ["Grid", "Ten-year mean MWh", "Mean, % of direct demand", "Worst year MWh", "Worst year, %"],
          [(g.replace("_", "/"), f0(r["mean"]), f"{abs(r['mean_pct']):.4f}", f0(r["worst"]), f"{abs(r['worst_pct']):.4f}")
           for g, r in REG.items()], size=7)
    para(doc, "Turbine-methane inventory over the verification years (TWh): constant production of "
              + f"{INV['production_twh']:.3f} TWh a year against a ten-year mean use of {INV['use_mean_twh']:.3f}; opening "
              + f"inventory {INV['opening_twh']:.1f} TWh, capacity {INV['capacity_twh']:.1f} TWh. Lowest assumes all of the "
              "year's withdrawals precede its production; highest the reverse.", size=8.5)
    table(doc, ["Year", "Opening", "Production", "Turbine use", "Lowest", "Highest", "Closing"],
          [(r["year"], f2(r["opening"]), f2(r["production"]), f2(r["use"]), f2(abs(r["lowest"])), f2(r["highest"]),
            f2(r["closing"])) for r in INV["years"]], size=7)
    para(doc, "Table S21. Calibration of the annual model against the hourly model (AUD per MWh).", bold=True)
    ca = CAL
    table(doc, ["Quantity", "Value"], [
        ("Annual model before calibration: direct loads", f1(ca["annual_uncalibrated"]["direct"])),
        ("Annual model before calibration: flexible loads incl. electrolyser", f1(ca["annual_uncalibrated"]["flex_with_electrolyser"])),
        ("Hourly model (first pass): direct loads, incl. turbine top-up", f1(ca["hourly_pass1"]["direct"])),
        ("Hourly model (first pass): flexible electricity", f1(ca["hourly_pass1"]["flex_electricity"])),
        ("Hourly model (final): electrolyser + hydrogen storage per MWh", f1(ca["hourly_pass2"]["electrolyser"] + ca["hourly_pass2"]["h2_storage"])),
        ("Hourly model (final): electrolyser utilisation", f"{100 * ca['hourly_pass2']['electrolyser_cf']:.0f}%"),
        ("Iterations; wind share of wind+PV output, annual / hourly", f"{N['n_iter']}; {N['a_share']}% / {N['h_share']}%"),
        ("Hourly transmission (REZ) cost per MWh of load", f1(ca["transmission_aud_mwh"])),
        ("Distribution share of the annual network adder (not in hourly model)", f1(ca["distribution_aud_mwh"])),
        ("Firming adder multiplier", f2(ca["firming_multiplier"])),
        ("Annual model after calibration: direct loads", f1(ca["annual_prices_after"]["direct"])),
        ("Annual model after calibration: flexible incl. electrolyser", f1(ca["annual_prices_after"]["flex_with_electrolyser"])),
        ("Hourly model on the final solution: direct", f1(ca["hourly_pass2"]["direct"])),
        ("Hourly model on the final solution: flexible", f1(ca["hourly_pass2"]["flex_electricity"])),
        ("Mechanism: same energy, daily-flexible demand: direct / flexible", f"{N['cf_d_dir']} / {N['cf_d_flex']}"),
        ("Mechanism: same energy, flat demand: direct / flexible", f"{N['cf_f_dir']} / {N['cf_f_flex']}"),
        ("Hourly system cost, seasonal store / daily / flat, AUD bn/yr", f"{N['cf_s_cost']} / {N['cf_d_cost']} / {N['cf_f_cost']}"),
        ("Batteries GWh, seasonal / daily / flat", f"{N['cf_s_bgwh']} / {N['cf_d_bgwh']} / {N['cf_f_bgwh']}"),
        ("Turbines GW (design), seasonal / daily / flat", f"{N['cf_s_turb']} / {N['cf_d_turb']} / {N['cf_f_turb']}"),
        ("Wind + PV GW, seasonal / daily / flat", f"{N['cf_s_gen']} / {N['cf_d_gen']} / {N['cf_f_gen']}"),
        *[(f"H2 store at A${c_}/kWh: hourly cost seasonal / daily, AUD bn/yr; store TWh(el)",
           f"{H2C[c_]['seasonal']['cost']:.1f} / {H2C[c_]['daily']['cost']:.1f}; {H2C[c_]['seasonal']['h2']:.1f}")
          for c_ in (5, 10, 15)],
        ("Turbine methane in the annual methane balance / verified need, TWh/yr", f"{N['ch4_turb2']} / {N['ch4_need2']}"),
        ("Direct loads incl. turbines of the one-hour adequacy pass", N["h_direct_adq"]),
        ("Methane supply: waste / kelp / synthetic, TWh/yr", f"{N['ch4_waste']} / {N['ch4_kelp']} / {N['ch4_e']}"),
        ("Methane use: transport / bio-methanol / turbines, TWh/yr", f"{N['ch4_trans']} / {N['ch4_meoh']} / {N['ch4_turb']}"),
        ("Cost of supplying turbine methane within the annual model, AUD bn/yr", N["ch4_cost"]),
        ("Methane store: opening inventory / capacity, TWh; store and first fill, AUD bn/yr",
         f"{N['ch4_open']} / {N['ch4_cap']}; {N['ch4_fill_bn']}"),
        ("Hourly model, direct loads only (no electrolysers)", f1(ca["inflexible"]["price_direct_aud_mwh"])),
        ("Hourly model, direct loads only, 7% real discount rate", N["h_inflex7"]),
        ("GenCost 2025-26, 2050 net-zero system incl. transmission / excl.", "141–152 / 120–130"),
        ("Annual objective before / after calibration, AUD bn/yr", f"{N['cost_uncal']} / {N['cost_annual']}"),
        ("Reconciled system cost (hourly fleet), AUD bn/yr", N["cost"]),
        ("  annual electricity supply replaced / hourly fleet incl. fuel and networks, AUD bn/yr",
         f"{f1(REC['annual_electricity_bn'])} / {f1(REC['hourly_electricity_bn'])}"),
        ("Firming and network adders x1.5 / x2.0: extra AUD bn/yr", f"{N['fx15']} / {N['fx2']}"),
        ("Three-hour vs one-hour steps (test season): cost change", f"{N['res_pct']}%"),
        ("Turbines added by the one-hour adequacy pass, GW", N["topup1"]),
    ])
    para(doc, "Table S22. Kelp zones: screening values and values set from ocean observations.", bold=True)
    table(doc, ["Zone", "Area km² (screen → ocean)", "Natural N (screen → WOA23)", "Heatwave loss (screen → OISST)",
                "Exposure (screen → waves)", "MHW days 1983-2012 / 2015-2024", "Centre depth m"],
          [(K.ZONES[z].name.split(" (")[0], f"{K.ZONES_PRIOR[z].area_km2:,.0f} → {K.ZONES[z].area_km2:,.0f}",
            f"{K.ZONES_PRIOR[z].nat_n:.2f} → {K.ZONES[z].nat_n:.2f}", f"{K.ZONES_PRIOR[z].mhw:.2f} → {K.ZONES[z].mhw:.2f}",
            f"{K.ZONES_PRIOR[z].exposure:.2f} → {K.ZONES[z].exposure:.2f}",
            f"{OCEAN[z]['mhw_days_mean_1983_2012']:.0f} / {OCEAN[z]['mhw_days_mean_2015_2024']:.0f}",
            f"{OCEAN[z]['centre_depth_m']:.0f}") for z in K.ZONES], size=6.8)
    para(doc, "Table S23. 2025 fuel sales (APS) and the study's scope (ML).", bold=True)
    table(doc, ["Product", "ML", "Treatment"], [(a, f"{b:,.1f}", c) for a, b, c in ACC["fuel_reconciliation"]]
          + [("Included in the study", f"{ACC['fuel_included_ml']:,.1f}", f"{N['dem']} TWh")])

    para(doc, "Table S24. Projected production cost of each fuel pathway (screening levelised costs; AUD per litre of "
              "diesel equivalent, 10.7 kWh; 2030 and 2040 interpolated) and 2050 output and spend. Fossil diesel before "
              "tax: A$" + N["dsl_l25"] + " per litre in 2025, " + N["dsl_l26"] + " in October 2026.", bold=True)
    table(doc, ["Pathway", "2026", "2030", "2040", "2050", "2050 AUD/MWh", "2050 output TWh", "2050 spend AUD bn/yr"],
          [(k, *[f2(v["aud_l_diesel_eq"][y]) for y in ("2026", "2030", "2040", "2050")], f0(v["aud_mwh"]["2050"]),
            f1(v["twh_2050"]), f2(v["spend_2050_bn"]) + (" *" if v["note"] else "")) for k, v in BF["pathways"].items()]
          + [("Biofuels and biomethane, total", "", "", "", N["bf_l"], "", N["bf_twh"], N["bf_bn"]),
             ("Electrofuels, total", "", "", "", "", "", N["ef_twh"], N["ef_bn"])], size=7)
    para(doc, "* Intermediate: most ethanol is converted to jet, and biomethane is partly burnt in the firming turbines "
              "and partly converted to methanol; totals count each feedstock once plus conversion. Drivers in 2050 "
              f"(today): electrolyser electricity A${BF['drivers']['y2050']['electrolyser_electricity_aud_mwh']:.0f} "
              f"({BF['drivers']['today']['electrolyser_electricity_aud_mwh']:.0f}) per MWh, air-captured CO₂ "
              f"A${BF['drivers']['y2050']['co2_aud_t']:.0f} ({BF['drivers']['today']['co2_aud_t']:.0f}) per tonne.", size=8.5)

    head(doc, "Supplementary Figures")
    sfig = [("FigS1_grid_harvester_top", "Fig. S1. Grid Harvester, plan view (from the authors' engineering design)."),
            ("FigS2_grid_harvester_side", "Fig. S2. Grid Harvester, side view."),
            ("FigS3_learning_levers", "Fig. S3. System cost as learning levers are applied cumulatively."),
            ("FigS4_transition", "Fig. S4. Fleet turnover, fuel build-up and well-to-wheel emissions, 2025–2050."),
            ("FigS5_kelp_zones", "Fig. S5. Kelp fuel cost by zone at learning-target yields (green: chosen)."),
            ("FigS6_feed_composition", "Fig. S6. Least-cost diets in 2050 with the cross-species swap."),
            ("FigS7_grid_harvester_energy", "Fig. S7. Grid Harvester energy per 1.44-ha cycle by slurry solids."),
            ("FigS8_feed_and_seafood", LEGEND_S8[0] + LEGEND_S8[1]),
            ("FigS9_harvesters_and_screening_lulls", "Fig. S9. (A) Annual harvest energy of the Grid Harvester fleet "
             "against conventional harvesters. (B) Screening winter-lull test of the annual model with 60, 30 and 0% of "
             "battery power counted at the peak (superseded by the hourly model)."),
            ("FigS10_capacity_factors", "Fig. S10. Wind and single-axis PV capacity factors at the 24 sites, 2015-2024: "
             "ERA5 before scaling, AEMO 2026 ISP zone values and the values used (bars: range of annual means)."),
            ("FigS11_kelp_ocean_data", "Fig. S11. Kelp zones from ocean observations: (A) marine-heatwave days per year "
             "(OISST, Hobday definition), (B) months with nitrate at or above 1 µmol/kg in 0-30 m (WOA23), (C) farmable "
             "area from the screening values and from bathymetry with the deployment cap."),
            ("FigS12_hourly_system", "Fig. S12. Hourly model: (A) final fleet by grid (turbines after the three-hour checks "
             "and the one-hour adequacy pass), (B) turbine output and curtailment in each weather year 2015-2024, with "
             "the final fleet fixed and dispatched at one-hour resolution."),
            ("FigS13_fuel_costs", "Fig. S13. Projected production cost of each fuel pathway, today (7% finance) and in "
             "the 2050 learning case (4%), per litre of diesel equivalent, with the pre-tax price of fossil diesel in 2025 "
             "and October 2026. Bars give 2050 output. Screening levelised costs from model inputs (table S24).")]
    for n, cap in sfig:
        doc.add_picture(str(FIG / f"{n}.png"), width=Cm(15.5 if "S7" not in n else 10))
        if n.startswith("FigS8"):
            para(doc, cap, size=8.5)
            continue
        para(doc, cap, bold=True, size=8.5)
    head(doc, "References")
    for i, r in enumerate(REFS, 1):
        if i > N_MAIN_REFS:
            para(doc, f"{i}. {r}", size=8, space=2)
    path = PKG / "Supplementary" / "Supplementary_Materials_Science.docx"
    doc.save(path)
    return path


def cover(wc_main, wc_abs, wc_meth):
    doc = Document()
    style(doc, 10.5)
    for x in ("16 November 2026", "The Editors", "Science", "Dear Editors,"):
        para(doc, x)
    paras = [
        f"We submit our Research Article \u201c{TITLE}\u201d for consideration in Science.",
        "In 2026 an oil shock left Australia, which imports most of its transport fuel, with weeks of diesel and jet in "
        "stock, while its parliament debates lifting a national ban on nuclear power. We ask a question of general interest "
        "to import-dependent, resource-rich countries: can every transport fuel, including mining, international flights "
        "and ships, be replaced in one national optimization that survives a test against observed weather, and what do "
        "geography and weather decide about which technologies earn a place?",
        f"The least-cost system replaces all {N['dem']} TWh of 2025 transport fuel sales and costs as much as fossil fuel at "
        f"a Brent-equivalent price of about US${N['be_brent']} per barrel, with supply-chain emissions "
        f"{N['wtwp'].split('.')[0]}% lower. An hourly model of its electricity supply over ten years of reanalysis "
        f"weather, iterated with the national model to one consistent portfolio and verified hour by hour, shows that the "
        f"electrolysers needed for aviation fuel, because they can wait weeks for wind and sun against stored hydrogen, "
        f"make firming cheap: direct loads pay A${N['h_direct']} per MWh, against A${N['h_inflex']} for the same loads "
        f"without them, and the advantage survives a tenfold higher storage cost (CSIRO's whole-grid "
        f"estimates are not a like-for-like comparison). Reactors do not enter the long-run optimum unless "
        f"modules cost below about A${N['be_e']} billion. Kelp and fish-free aquafeed are presented as conditional findings "
        f"that need demonstration.",
        f"The main text has about {f0(round(wc_main, -1))} words, five figures and {N_MAIN_REFS} references; the abstract "
        f"has {wc_abs} words. Materials and Methods, thirteen supplementary figures, 24 supplementary tables, processed "
        "observational data and code are provided; one command reproduces every number and runs automated tests. All "
        "code and data are public at https://github.com/bcjohnjr/Australia-SMR-Kelp-Renewable-Transport-System.",
        "Related work by the same authors: a Spanish study (SSRN preprint, https://doi.org/10.2139/ssrn.7648876, cited); a "
        "Canadian study using the same framework, under review at Nature Energy and not cited because it is not publicly "
        "available (we can provide it to the editors); a UK study under review at Energy & Environmental Science; and a "
        "Costa Rican study in preparation.",
        "Use of artificial intelligence: Artificial Inventor/Synthetic Scientist V63, an AI agent system, was used for code "
        "development, data processing, numerical checks, plotting, drafting and document preparation. This is disclosed in "
        "the Acknowledgments, and the tool, version and prompts are given in the Materials and Methods. The authors "
        "verified all content and take responsibility for it.",
        "This manuscript has not been submitted elsewhere. All authors approved the submission, declare no competing "
        "interests, and received no external funding. We suggest that reviewers with expertise in energy-system "
        "optimization, power-system firming, sustainable aviation fuels and Australian energy policy would be well placed "
        "to assess the work.",
    ]
    for x in paras:
        para(doc, x)
    para(doc, "Yours sincerely,")
    para(doc, "Jonathan Karl Bily (corresponding author), on behalf of Christoph Pahl and Patricia Valdés Bacallao")
    para(doc, "Independent researcher, Zaragoza, Spain")
    para(doc, "jonathan@cloudwashlaundry.com · ORCID 0009-0004-3526-7271")
    path = PKG / "Submission" / "Cover_Letter_Science.docx"
    doc.save(path)
    return path


def response():
    """Point-by-point record of the informal review of version 7 and what version 7.1 changed. Kept in Review/, not
    part of the submission."""
    doc = Document()
    style(doc, 10)
    para(doc, "Response to the informal review of version 7", bold=True, size=14)
    para(doc, TITLE, italic=True)
    para(doc, "Not for submission. Numbers are generated from the version 7.1 outputs.", size=9)
    rows = [
        ("1. Methane allocation 0.44% below the verified turbine fuel", "Agreed; closed exactly",
         f"The annual model now supplies {N['ch4_turb3']} TWh/yr against a verified need of {N['ch4_need3']} (the need "
         f"rounded up to 0.001 TWh). To keep the hourly results valid, the final annual solve holds the electrofuel, "
         f"air-capture and process-heat electricity loads at the values the hourly fleet was designed and verified on; a "
         f"new test checks that annual and hourly loads are identical. The extra methane comes from slightly less "
         f"bio-methanol, a little more e-ammonia and 9 km² more kelp. test_methane_balance now requires allocation >= need (no "
         f"2% tolerance)."),
        ("2. Ten-year methane inventory not demonstrated", "Agreed; added",
         f"reconcile.py tracks the store year by year over 2015-2024, repeated twice in sequence, with conservative "
         f"within-year ordering. Opening inventory {N['ch4_open']} TWh, capacity {N['ch4_cap']} TWh "
         f"({N['ch4_cap_pj']} PJ, under half of Australia's existing underground gas storage), lowest level "
         f"{N['ch4_low']} TWh (2017, by construction of the smallest sufficient opening stock), ten-year surplus {N['ch4_surplus']} TWh. Store capacity and the opening fill "
         f"(valued at the methane shadow price, spread over 30 years, with its emissions) cost A${N['ch4_fill_bn']} "
         f"bn/yr. Table S20 gives the year-by-year table; a new test asserts the inventory never falls below zero or "
         f"exceeds capacity and ends no lower than it began."),
        ("Recalculate affected outputs", "Done",
         f"Reconciled cost A${N['cost']} bn/yr (was 85.30), emissions reduction {N['wtwp']}% (was 91.81), break-even "
         f"US${N['be_brent']}/bbl (was 94), Monte Carlo median US${N['mc_be']}; catenary and fleet unchanged. The "
         f"hourly dispatch did not need re-running because its loads are unchanged."),
        ("3. Public repository is flat and not executable", "Fixed in the code",
         "A new module (layout.py), imported first by every script, rebuilds outputs/, observed_data/ and "
         "illustrations/ from a flat folder on first run, and writes documents to ./package when run outside the "
         "submission package. A fresh flat copy was rebuilt and passed all tests. The authors only need to upload the "
         "files of Code/model flat (Repository/flat_upload/ holds them ready). A Zenodo DOI is still to be minted."),
        ("4a. 'All' transport fuel", "Partly disagree; clarified",
         "Automotive LPG is included (table S23: 241.7 ML, light vehicles). Excluded are non-automotive LPG, lubricants "
         "and other products, which are not transport fuels, and 0.5 GL of stationary diesel. The main text now states "
         "this scope in one sentence."),
        ("4b. Competing interests", "For the authors",
         "Unchanged ('no competing interests'); all three authors must confirm, in particular any patent or commercial "
         "interest in the Grid Harvester or the utility drones."),
        ("Rebuild did not finish in the referee's 125 s", "Noted",
         "The standard rebuild takes under a minute here; first runs are slower while matplotlib builds its font cache."),
        ("Authors' request: projected fuel production costs", "Added",
         f"New script biofuel_costs.py, table S24 and fig. S13: production cost of each pathway today, 2030, 2040 and "
         f"2050. Biofuels and biomethane: {N['bf_twh']} TWh for A${N['bf_bn']} bn/yr (A${N['bf_l']} per litre of "
         f"diesel equivalent); electrofuels: {N['ef_twh']} TWh for A${N['ef_bn']} bn/yr."),
    ]
    table(doc, ["Referee point", "Response", "Change in version 7.1"], rows, size=8, widths=[4, 2.5, 10.5])
    (PKG / "Review").mkdir(exist_ok=True)
    path = PKG / "Review" / "Response_to_review_of_v7.docx"
    doc.save(path)
    return path


def to_pdf(path):
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(path.parent), str(path)],
                   check=True, capture_output=True, timeout=300)


if __name__ == "__main__":
    m, wc_main, wc_abs, wc_meth = manuscript()
    s = si()
    c = cover(wc_main, wc_abs, wc_meth)
    rp = response()
    print("words: main", wc_main, "abstract", wc_abs, "SM methods", wc_meth, "refs", len(REFS), "main refs", N_MAIN_REFS,
          "title chars", len(TITLE), "summary chars", len(SUMMARY))
    if "--no-pdf" not in sys.argv:
        for pth in (m, s, c, rp):
            to_pdf(pth)
        # single PDF of manuscript followed by supplementary materials, for portals that want one file
        from pypdf import PdfWriter
        w = PdfWriter()
        for pth in (m, s):
            w.append(str(pth.with_suffix(".pdf")))
        w.write(str(PKG / "Submission" / "Manuscript_and_Supplementary_Materials_Science.pdf"))
        w.close()
    json.dump(dict(main_words=wc_main, abstract_words=wc_abs, methods_words=wc_meth, references=len(REFS),
                   main_references=N_MAIN_REFS, title_chars=len(TITLE), summary_chars=len(SUMMARY), display_items=len(LEGENDS)),
              open(OUT / "document_stats.json", "w"))
