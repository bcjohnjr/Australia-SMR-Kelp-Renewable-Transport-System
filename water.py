"""Distilled water from a heat cascade: multi-effect distillation (MED) against seawater reverse osmosis (SWRO).

MED with a top brine temperature of about 70 C needs 70 kWh of heat and 1.8 kWh of electricity per m3 (gain output
ratio ~9; Sundrop Farms at Port Augusta runs a seven-stage solar-heated distiller at 78 C making 1 ML/day). SWRO needs
3.5 kWh of electricity per m3. Both need an intake, outfall and storage, charged equally. MED rejects almost all of
its heat at ~38 C, which greenhouses (Sundrop's 20 ha) and warm-water aquaculture (barramundi and prawns at 28-30 C)
can use; only the share actually sold earns a credit. Heat from an SMR at 70-80 C costs 0.09 MWh of electricity per
MWh (raised condenser pressure); solar-thermal heat is costed at AUD 40/MWh_th (screening).
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import json
from pathlib import Path

import inputs as I

OUT = Path(__file__).resolve().parent / "outputs"
W = I.WATER


def capital_per_m3(capex_m3d, r=0.04, life=W["life"], cf=0.95):
    return capex_m3d * I.CRF(r, life) / (365 * cf)


def swro(power=95.0, r=0.04):
    e = W["ro_kwh_e_m3"] * power / 1000
    cap = capital_per_m3(W["ro_capex_m3d"], r)
    return dict(energy=e, capital=cap, om=W["ro_om_m3"], intake=W["intake_outfall_m3"], heat=0.0, reject_credit=0.0,
                total=e + cap + W["ro_om_m3"] + W["intake_outfall_m3"])


def med(heat_aud_mwh, power=95.0, r=0.04, reject_sold_share=0.0, reject_value=0.0):
    heat = W["med_kwh_th_m3"] * heat_aud_mwh / 1000
    e = W["med_kwh_e_m3"] * power / 1000
    cap = capital_per_m3(W["med_capex_m3d"], r)
    credit = W["med_kwh_th_m3"] * reject_sold_share * reject_value / 1000
    return dict(energy=e, capital=cap, om=W["med_om_m3"], intake=W["intake_outfall_m3"], heat=heat, reject_credit=-credit,
                total=heat + e + cap + W["med_om_m3"] + W["intake_outfall_m3"] - credit)


def cases(power=95.0, gas=12.0, carbon=110.0):
    smr_heat = I.SMR["lowgrade_forgone"] * power
    gas_heat = gas * 3.6 / 0.9 + carbon * I.GAS_KG_CO2_GJ / 1000 * 3.6 / 0.9
    hp_heat = power / 4.0 + 8.0
    # reject heat sold: Port Augusta hub (80 ha greenhouses + 4,000 t RAS) per 120 ML/day MED
    gh = 80 * W["greenhouse_mwh_ha"] + 4000e3 * W["ras_kwh_kg"] / 1000
    rej = 120e3 * 365 * W["med_kwh_th_m3"] / 1000
    share = gh / rej
    out = {"SWRO (grid electricity)": swro(power),
           "MED, SMR 75 C heat": med(smr_heat, power),
           "MED, SMR heat + reject heat sold (Port Augusta hub)": med(smr_heat, power, reject_sold_share=share,
                                                                     reject_value=gas_heat),
           "MED, solar-thermal heat (Sundrop-type)": med(40.0, power),
           "MED, gas boiler heat": med(gas_heat, power)}
    gap = out["MED, SMR 75 C heat"]["total"] - out["SWRO (grid electricity)"]["total"]
    breakeven_share = gap / (W["med_kwh_th_m3"] * hp_heat / 1000)
    breakeven_share_gas = gap / (W["med_kwh_th_m3"] * gas_heat / 1000)
    return dict(cases=out, port_augusta_reject_share=share, breakeven_reject_share_vs_heat_pump=breakeven_share,
                breakeven_reject_share_vs_gas=breakeven_share_gas, smr_heat_aud_mwh=smr_heat, gas_heat_aud_mwh=gas_heat,
                hp_heat_aud_mwh=hp_heat, power_aud_mwh=power)


if __name__ == "__main__":
    R = cases()
    json.dump(R, open(OUT / "water.json", "w"), indent=1)
    for k, v in R["cases"].items():
        print(f"{k:55s} {v['total']:.2f} AUD/m3")
    print({k: round(v, 4) for k, v in R.items() if k != "cases"})
