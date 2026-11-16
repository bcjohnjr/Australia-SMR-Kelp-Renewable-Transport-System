"""Projected production cost of each renewable fuel pathway (screening levelised costs).

For today's costs (7% finance) and the 2050 learning case (4%), the cost of producing one MWh of each fuel from the
model's own inputs: feedstock, conversion, process heat and, for electrofuels, electricity at the calibrated flexible
price with electrolyser and hydrogen-storage costs and CO2 from direct air capture. Years between are interpolated
linearly. In the model only electrofuels, air capture, kelp, wind, solar, electrolysers and finance learn; residue,
lipid, ethanol and biomethane pathways keep today's conversion costs. Costs exclude distribution, margins and taxes.
Output: outputs/biofuel_costs.json.
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import json

import inputs as I
import optimise as O

YEARS = (2026, 2030, 2040, 2050)
L_DIESEL = I.KWH_PER_L["diesel"]


def crf(r, n):
    return r / (1 - (1 + r) ** -n)


def pathway_costs(p, S):
    sh = S["shadow_aud_mwh"]
    e = p["electrolyser"]
    elz = e["capex"] * 1000 * (crf(p["r"], e["life"]) + e["om"]) / (e["cf_wind"] * 8760) + p.get("h2_storage_aud_mwh_el", 0.0)
    el = sh["el_flex_wind"] + elz                               # AUD per MWh of electrolyser electricity
    co2 = p["dac"]["cost"] + p["dac"]["el"] * sh["el_flex_solar"]   # AUD per t CO2 from air capture
    heat = max(sh.get("heat|INLAND", 0.0), 0.0)
    eth = p["etoh"]["cost"] + p["etoh"]["heat"] * heat
    kz = S["kelp_zone_table"]
    kelp = min(kz[z]["aud_per_mwh_fuel"] for z in ("tas_se", "tas_e", "bass"))
    res = lambda k: p[k]["cost_odt"] / p[k]["mwh_odt"] + p[k]["conv"]
    return {
        "Tallow and used cooking oil (HEFA)": p["hefa"]["cost"],
        "Canola (HVO)": p["canola"]["cost"],
        "Cereal straw (gasification, Fischer-Tropsch)": res("straw"),
        "Cane residues (hydrothermal liquefaction)": res("cane"),
        "Forest residues (hydrothermal liquefaction)": res("forest"),
        "Ethanol (sorghum, cane, molasses)": eth,
        "Alcohol-to-jet": eth / p["atj"]["eff"] + p["atj"]["cost"],
        "Waste biomethane": p["wch4"]["cost"],
        "Bio-methanol (from biomethane)": p["biomeoh"]["ch4"] * p["wch4"]["cost"] + p["biomeoh"]["cost"],
        "Kelp (hydrothermal liquefaction), best zone": kelp,
        "e-Ammonia": p["enh3"]["el"] * el + p["enh3"]["synth"],
        "e-Methanol (air-captured CO2)": p["emeoh"]["el"] * el + p["emeoh"]["synth"] + p["emeoh"]["co2"] * co2,
        "Fischer-Tropsch electrofuel (air-captured CO2)": p["eft"]["el"] * el + p["eft"]["synth"] + p["eft"]["co2"] * co2,
    }, dict(electrolyser_electricity_aud_mwh=el, co2_aud_t=co2, heat_aud_mwh=heat)


VOLUME = {"Tallow and used cooking oil (HEFA)": ("hefa",), "Canola (HVO)": ("canola_hvo",),
          "Cereal straw (gasification, Fischer-Tropsch)": ("straw_ft",),
          "Cane residues (hydrothermal liquefaction)": ("cane_htl",),
          "Forest residues (hydrothermal liquefaction)": ("forest_htl",), "Ethanol (sorghum, cane, molasses)": ("ethanol",),
          "Alcohol-to-jet": ("alcohol_to_jet",), "Waste biomethane": ("waste_biomethane",),
          "Bio-methanol (from biomethane)": ("bio_methanol",), "Kelp (hydrothermal liquefaction), best zone": ("kelp_hc",),
          "e-Ammonia": ("e_ammonia",), "e-Methanol (air-captured CO2)": ("e_methanol",),
          "Fischer-Tropsch electrofuel (air-captured CO2)": ("efuel_ft_wind", "efuel_ft_solar")}
INTERMEDIATE = {"Ethanol (sorghum, cane, molasses)": "most is converted to jet", "Waste biomethane":
                "part is burnt in firming turbines and part converted to methanol"}


def main():
    C = json.loads((O.OUT / "central.json").read_text())
    T = json.loads((O.OUT / "today.json").read_text())
    c50, d50 = pathway_costs(O.base_params(), C)
    c26, d26 = pathway_costs(O.today_params(), T)
    rows = {}
    for k in c50:
        by = {y: c26[k] + (c50[k] - c26[k]) * (y - YEARS[0]) / (YEARS[-1] - YEARS[0]) for y in YEARS}
        twh = sum(C["fuels_twh"].get(f, 0.0) for f in VOLUME[k])
        rows[k] = dict(aud_mwh=by, aud_l_diesel_eq={y: v * L_DIESEL / 1000 for y, v in by.items()}, twh_2050=twh,
                       spend_2050_bn=twh * c50[k] / 1000, note=INTERMEDIATE.get(k, ""))
    final = [k for k in rows if k not in INTERMEDIATE and k != "Alcohol-to-jet" and k != "Bio-methanol (from biomethane)"]
    bio = [k for k in rows if not k.startswith(("e-", "Fischer"))]
    out = dict(years=YEARS, pathways=rows, drivers=dict(today=d26, y2050=d50),
               fossil_pretax_aud_mwh=dict(diesel_2025=I.pretax_aud_mwh("diesel", "avg2025"),
                                          diesel_oct2026=I.pretax_aud_mwh("diesel", "oct2026"),
                                          jet_2025=I.pretax_aud_mwh("jet", "avg2025"),
                                          jet_oct2026=I.pretax_aud_mwh("jet", "oct2026")),
               litre_basis_kwh=L_DIESEL,
               biofuel_spend_2050_bn=sum(rows[k]["spend_2050_bn"] for k in bio
                                         if k not in ("Alcohol-to-jet", "Bio-methanol (from biomethane)"))
               + sum(C["fuels_twh"].get(f, 0.0) * x for f, x in (("alcohol_to_jet", O.base_params()["atj"]["cost"]),
                                                                  ("bio_methanol", O.base_params()["biomeoh"]["cost"]))) / 1000,
               biofuel_twh_2050=sum(rows[k]["twh_2050"] for k in bio if k not in ("Alcohol-to-jet", "Bio-methanol (from biomethane)")),
               efuel_spend_2050_bn=sum(rows[k]["spend_2050_bn"] for k in rows if k.startswith(("e-", "Fischer"))),
               efuel_twh_2050=sum(rows[k]["twh_2050"] for k in rows if k.startswith(("e-", "Fischer"))),
               note="screening levelised production costs from model inputs; linear interpolation between today and 2050")
    (O.OUT / "biofuel_costs.json").write_text(json.dumps(out, indent=1, default=float))
    return out


if __name__ == "__main__":
    o = main()
    for k, r in o["pathways"].items():
        print(f"{k:50s}", {y: round(v) for y, v in r["aud_mwh"].items()}, {y: round(v, 2) for y, v in r["aud_l_diesel_eq"].items()},
              round(r["twh_2050"], 1), round(r["spend_2050_bn"], 2))
    print(o["drivers"], o["fossil_pretax_aud_mwh"], o["biofuel_spend_2050_bn"], o["biofuel_twh_2050"], o["efuel_spend_2050_bn"])
