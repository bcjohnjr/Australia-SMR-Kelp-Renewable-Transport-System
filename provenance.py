"""Machine-readable provenance table of the principal inputs (outputs/input_provenance.csv)."""
import csv
from pathlib import Path

import inputs as I
import kelp as K
import feed as F
import optimise as O

OUT = Path(__file__).resolve().parent / "outputs"


def run():
    rows = list(I.provenance_rows())
    for k, z in K.ZONES.items():
        rows.append((f"Kelp zone {k} learning-target yield", z.y_lt, "t dry/ha/yr", "screening (Methods; kelp.py)", "", "x0.6-1.5 (Monte Carlo)",
                     f"{z.species}; heatwave loss {z.mhw}; natural N {z.nat_n}; area cap {z.area_km2} km2"))
    for k, d in O.LCA.items():
        rows.append((f"Life-cycle factor {k}", round(d["core"], 4), "t CO2-e/MWh", d["src"], "ICAO doc 06 (June 2025); NREL",
                     f"{d['lo']:.4f}-{d['hi'] + d['iluc']:.4f}", f"ILUC {d['iluc']:.4f} t/MWh" if d["iluc"] else "energy-supply boundary"))
    rows.append(("Methane leakage", O.LCA_DEFAULTS["ch4_leak"], "fraction of biomethane produced", "screening", "", "0-0.05", f"GWP100 {O.GWP_CH4_BIO} (AR6 non-fossil)"))
    rows.append(("Kelp tissue nitrogen", K.KelpCost().n_kg_t, "kg N/dry t", "screening (refinery N recovery)", "", "", ""))
    for z, n in K.IMTA_N_T.items():
        rows.append((f"Fish-farm N reachable by kelp, {z}", n, "t N/yr", "screening (finfish production x dissolved N x 50% reachable)", "", "0-2x", ""))
    rows.append(("Brent price distribution (Monte Carlo)", I.BRENT_DIST["median"], "US$/bbl median", "screening lognormal", "", f"sigma {I.BRENT_DIST['sigma']}", "5-95%: ~45-142"))
    obs = [
        ("Hourly wind and solar resource 2015-2024 (24 sites)", "observed_data/cf_hourly.npz", "capacity factor",
         "ERA5 reanalysis via Open-Meteo archive API; scaled to AEMO 2026 ISP REZ capacity factors", "2026-11", "", "observed.py"),
        ("REZ capacity factors, build costs, battery properties, connection and REZ/flow-path costs",
         "observed_data/isp_2026.json", "various", "AEMO Draft 2026 ISP Inputs and Assumptions workbook", "2025", "", ""),
        ("Electricity demand 2015-2024", "observed_data/demand_hourly.npz", "MW", "AEMO NEM price and demand; WEM load summary (2015-2023)", "2026-11", "", ""),
        ("Daily SST 1982-2026 at kelp zones", "observed_data/kelp_ocean.json", "deg C", "NOAA OISST v2.1 (ERDDAP)", "2026-11", "", "Hobday MHW definition"),
        ("Monthly nitrate climatology 0-200 m", "observed_data/kelp_ocean.json", "umol/kg", "World Ocean Atlas 2023 (1 deg)", "2024", "", ""),
        ("Bathymetry, southern Australia", "observed_data/kelp_ocean.json", "m", "ETOPO1 (ERDDAP etopo180)", "2009", "", ""),
        ("Wave climate at kelp zones 2015-2024", "observed_data/kelp_ocean.json", "m", "ERA5 ocean waves via Open-Meteo marine API", "2026-11", "", ""),
        ("Brent spot price, monthly", I.BRENT_USD_BBL["oct2026"], "USD/bbl (Oct 2026)", "EIA RBRTEm", "2026-11", "", f"2025 average {I.BRENT_USD_BBL['avg2025']:.2f}"),
        ("AUD/USD, monthly mean", round(1 / I.AUD_PER_USD["oct2026"], 4), "USD per AUD (Oct 2026)", "RBA F11.1", "2026-11", "", ""),
        ("Terminal gate prices, national average", I.TGP_CPL["diesel"]["oct2026"], "c/L diesel incl. GST and excise (Oct 2026)", "AIP", "2026-11", "", "check of retail margins"),
        ("2025 transport fuel sales", round(sum(I.VOL_GL.values()), 3), "GL", "APS data extract December 2025", "2026", "", "see accounts.json fuel_reconciliation"),
    ]
    rows += obs
    for nm, v in F.ING.items():
        rows.append((f"Feed ingredient {nm}", v[3], "AUD/t", "screening (FRDC, Skretting Australia 2022, ABARES Sep 2026)", "", "", f"CP {v[0]}, lipid {v[1]}, EPA+DHA {v[2]}, lys/met {F.AA.get(nm, (0, 0))}, max {v[4]}"))
    for sp, d in F.PRODUCTION_T["2050"].items():
        rows.append((f"Production 2050, {sp}", d, "t/yr", "screening growth scenario; 2025 from Tasmanian EPA, Queensland DAF, ABARES", "", "", f"2025: {F.PRODUCTION_T['2025'][sp]}"))
    with open(OUT / "input_provenance.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["input", "value", "units", "source", "date", "tested_range", "note"])
        w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    print(run(), "rows")
