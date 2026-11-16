"""Downstream accounts: territorial (inventory-boundary) and well-to-wheel emissions, fuel excise and fuel tax credits,
and liquid-fuel import dependence. Screening accounts at constant 2026 tax rates; not a general-equilibrium forecast."""
import json

import inputs as I
import optimise as O


def run():
    C = json.load(open(O.OUT / "central.json"))
    D = C["demand_twh"]
    intl = I.JET_INTERNATIONAL_SHARE * D["aviation"] + I.VOL_GL["fuel_oil_marine"] * I.KWH_PER_L["fuel_oil"]
    s1 = sum(I.co2_t_per_mwh(s, "s1") * D[s] for s in D)
    s1_intl = (I.JET_INTERNATIONAL_SHARE * D["aviation"] * I.co2_t_per_mwh("aviation", "s1")
               + I.VOL_GL["fuel_oil_marine"] * I.KWH_PER_L["fuel_oil"] * I.SCOPE1_KG_GJ["fuel_oil"] * 3.6 / 1000)
    seg_s1 = {k: I.co2_t_per_mwh(k, "s1") * D[k] for k in D}
    dom_ship = I.DIESEL_SPLIT_GL["marine"] * I.KWH_PER_L["diesel"] * I.SCOPE1_KG_GJ["diesel"] * 3.6 / 1000
    transport_sector = (seg_s1["ldv_petrol"] + seg_s1["ldv_diesel"] + seg_s1["hdv"] + seg_s1["rail"]
                        + (1 - I.JET_INTERNATIONAL_SHARE) * seg_s1["aviation"] + dom_ship)
    recon = [("Study boundary, well-to-wheel (all fuel sold)", C["fossil_wtw_mt"]),
             ("less upstream (well-to-tank) emissions", -(C["fossil_wtw_mt"] - s1)),
             ("= combustion (scope 1), all fuel sold", s1),
             ("less international aviation and bunkers (inventory memo items)", -s1_intl),
             ("less mining, farm and construction diesel (inventory: stationary energy and agriculture)",
              -(seg_s1["mining"] + seg_s1["farm"] + seg_s1["construction"])),
             ("= liquid-fuel combustion in the inventory transport sector (study estimate)", transport_sector),
             ("Inventory transport sector, 2025 (includes LPG, natural gas, lubricants, non-CO2)", 100.9),
             ("Difference (outside the study, or volume-split error)", 100.9 - transport_sector)]
    aps = json.load(open(I._OBS / "aps_2025.json"))["sales_ml"]
    fuel_recon = [
        ("Automotive gasoline (incl. ethanol blends)", aps["Automotive gasoline total (ML)"], "included: light vehicles"),
        ("Diesel oil", aps["Diesel oil: total (ML)"], "included, less 0.5 GL other stationary use (screening)"),
        ("Aviation turbine fuel, domestic", aps["Aviation turbine fuel Domestic (ML)"], "included"),
        ("Aviation turbine fuel, international", aps["Aviation turbine fuel International (ML)"], "included"),
        ("Aviation gasoline", aps["Aviation gasoline (ML)"], "included: aviation"),
        ("Fuel oil", aps["Fuel oil (ML)"], "included: shipping"),
        ("LPG, automotive", aps["LPG Automotive use (ML)"], "included: light vehicles"),
        ("LPG, non-automotive", aps["LPG Non-automotive use (ML)"], "excluded: not transport"),
        ("Lubricating oils and greases", aps["Lubricating oils & greases (ML)"], "excluded: not fuel"),
        ("Other products", aps["Other products (ML)"], "excluded: not transport fuel"),
        ("Total, APS 2025", aps["Total (ML)"], ""),
    ]
    incl_ml = sum(v for _, v, n in fuel_recon if n.startswith("included")) - 500.0
    em = dict(reconciliation=recon, fuel_reconciliation=fuel_recon, fuel_included_ml=incl_ml,
              demand_twh_by_segment=D, demand_twh_total=sum(D.values()), transport_sector_mt=transport_sector, scope1_by_segment_mt=seg_s1,
              scope1_all_mt=s1, scope1_international_mt=s1_intl, territorial_mt=s1 - s1_intl,
              wtw_fossil_mt=C["fossil_wtw_mt"], wtw_residual_mt=C["residual_wtw_mt"], wtw_reduction_pct=C["wtw_reduction_pct"],
              inventory_transport_2025_mt=100.9, national_2025_mt=458.9,
              note="territorial scope-1 total includes mining, farm and construction diesel, which the inventory counts "
                   "under stationary energy; international aviation and bunkers are memo items")
    exc = I.EXCISE_CPL["oct2026"] / 100
    gl_petrol = I.VOL_GL["petrol"]
    gl_road_diesel = I.DIESEL_SPLIT_GL["road"]
    gl_offroad = sum(I.DIESEL_SPLIT_GL[k] for k in ("mining", "farm", "construction", "rail", "marine"))
    gross = (gl_petrol + I.VOL_GL["diesel"]) * exc
    ftc_off = gl_offroad * I.FTC_OFFROAD_CPL / 100
    ftc_heavy = gl_road_diesel * (1 - I.LDV_DIESEL_SHARE) * 0.9 * (I.EXCISE_CPL["oct2026"] - I.RUC_CPL) / 100
    net = gross - ftc_off - ftc_heavy
    ev_twh = C["electricity_twh"]["vehicles_rail"]
    road_ev_twh = sum(t * O.OPTIONS[k.split("|")[0]][k.split("|")[1]][1] for k, t in C["end_use_twh"].items()
                      if k.split("|")[0] in ("ldv_petrol", "ldv_diesel", "hdv") and O.OPTIONS[k.split("|")[0]][k.split("|")[1]][0] == "el")
    road_ev_twh += sum(C["ers_twh"].values()) * O.ERS_RATIO
    fiscal = dict(excise_gross_bn=gross, ftc_offroad_bn=ftc_off, ftc_heavy_bn=ftc_heavy, excise_net_bn=net,
                  road_electricity_twh=road_ev_twh,
                  ruc_aud_per_mwh_to_replace=net * 1e3 / road_ev_twh if road_ev_twh else None,
                  note="net excise kept if renewable liquids pay excise at the fossil rate per litre-equivalent is not "
                       "assumed; the road-user charge per MWh of road electricity that would replace net excise is shown")
    imp = dict(liquid_fuel_2025_gl=sum(I.VOL_GL.values()), refined_imports_ml_day_2025=143.0,
               domestic_refining_share=0.20, mso_days_oct2026={"petrol": 41, "diesel": 33, "jet": 28},
               fossil_cost_bn=C["fossil_cost_bn"], system_cost_bn=C["objective_bn"],
               renewable_liquids_twh=sum(t for k, t in C["carrier_twh"].items() if k != "el"))
    R = dict(emissions=em, fiscal=fiscal, security=imp)
    json.dump(R, open(O.OUT / "accounts.json", "w"), indent=1, default=float)
    return R


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, default=float))
