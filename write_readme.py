"""Write the package README and the code README from the model outputs (run by run_all.py after the documents)."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent.parent
L = lambda f: json.loads((HERE / "outputs" / f).read_text())


def main():
    C, R, MC = L("central.json"), L("scenarios.json"), L("montecarlo.json")["summary"]
    D, st, rt = L("dispatch.json"), L("document_stats.json"), L("runtime.json") if (HERE / "outputs" / "runtime.json").exists() else {}
    cal = json.loads((HERE / "calibration.json").read_text())
    REC, V = L("reconciled.json"), L("verify_hourly.json")
    PH = REC["portfolio_hourly"]
    T = "Replacing Australia's transport fuels: electricity, biofuels and nuclear heat"
    sysd = D["design"]["systems"]
    batt_gw = sum(v["battery_gw"] for v in sysd.values())
    batt_gwh = sum(v["battery_gwh"] for v in sysd.values())
    top = f"""# {T}

Science submission package (Research Article). Authors: Jonathan Karl Bily (corresponding), Christoph Pahl, Patricia Valdés Bacallao. Prepared 15 November 2026.

- Submission/: manuscript (DOCX for upload; PDF reference copy with figures), a single PDF of manuscript and Supplementary Materials, and the cover letter.
- Supplementary/: Supplementary Materials (DOCX and PDF): Materials and Methods (with the AI-use disclosure and prompts), Supplementary Text, Figs. S1 to S12, Tables S1 to S23 and the references cited only there.
- Figures/: Figures 1 to 5 and the supplementary figures as PNG (300 dpi) and vector PDF.
- Data/: model outputs (JSON), Source Data (Data/source_data/), the provenance table (`input_provenance.csv`), processed observations (Data/observed/: hourly capacity factors, demand, ocean, prices, fuel sales, AEMO ISP extract, raw-file manifest with SHA-256) and `runtime.json`.
- Code/model/: complete model, download scripts and README; LICENSE (MIT), CITATION.cff, .zenodo.json.
- Review/: response to the third informal review (not for submission).
- Repository/: steps to publish the code and data on GitHub with a Zenodo DOI.

Format: title {st['title_chars']} characters (Science limit 96), one-sentence summary {st['summary_chars']} characters, abstract {st['abstract_words']} words, main text {st['main_words']:,} words, {st['display_items']} figures, {st['main_references']} references in the main text ({st['references']} with those cited only in the supplementary materials).

Reproduce: `python Code/model/run_all.py` (any OS; `--no-pdf` without LibreOffice). Measured on the authors' Linux machine: {rt.get('total', 0):.0f} s using the shipped hourly calibration; `--recalibrate` re-runs the hourly model over ten weather years ({cal.get('runtime_s', 0) / 60:.0f} min).

Headline results (central learning case, annual programme reconciled with the hourly model's final fleet): system cost AUD {REC['reconciled_cost_bn']:.2f} bn/yr (annual programme alone {C['objective_bn']:.2f}); break-even Brent US${R['fossil_breakeven']['reconciled_brent_usd']:.0f}/bbl (Monte Carlo median US${MC['breakeven_reconciled_median']:.0f}, conditional on the assumed input distributions); supply-chain emissions -{REC['wtw_reduction_pct']:.1f}%; catenary {C['ers_km_electrified']:,.0f} km; kelp {C['kelp_total_km2']:,.0f} km² (hypothetical deployment; no-kelp case +AUD {R['kelp_sens']['no kelp']['extra_bn']:.2f} bn/yr); electricity fleet {PH['wind_gw']:.0f} GW wind, {PH['pv_gw']:.0f} GW solar, batteries {batt_gw:.0f} GW / {batt_gwh:.0f} GWh, turbines {PH['turbine_gw']:.1f} GW; direct loads AUD {cal['hourly_pass2']['direct']:.0f}/MWh with electrolysers, {cal['inflexible']['price_direct_aud_mwh']:.0f} without; final fleet verified hour by hour in every year 2015-2024, worst-year unserved {max(v['unserved_mwh'] for v in V['years'].values()):.0f} MWh; no SMRs in the long-run optimum.
"""
    (PKG / "README.md").write_text(top)
    code = f"""# {T}: model and data

Python model for the article by Jonathan Karl Bily, Christoph Pahl and Patricia Valdés Bacallao (submitted to Science).

## Reproduce

```bash
python -m pip install -r requirements-lock.txt
python run_all.py              # or --no-pdf without LibreOffice; --recalibrate to redo the hourly calibration
python test_model.py           # the tests alone
```

Measured: {rt.get('total', 0):.0f} s for the full build with PDFs using the shipped calibration; the hourly recalibration took {cal.get('runtime_s', 0) / 60:.0f} min. Step times are written to `outputs/runtime.json` on every run.

## Observed data

`observed_data/` holds the processed observations the models read (about 7 MB). They are built from the raw downloads (about 450 MB, not shipped) by `observed.py --raw <folder>`; `observed_data/raw_manifest.json` lists every raw file with size and SHA-256. The raw files come from:

- `fetch_data.py`: ERA5 hourly weather at 24 sites and waves at nine kelp zones (Open-Meteo), AEMO NEM and WEM demand, NOAA OISST sea-surface temperature, World Ocean Atlas 2023 nitrate, ETOPO bathymetry, EIA Brent, RBA exchange rates;
- `fetch_data_part2.py`: conversion of the nitrate files and AIP terminal-gate prices;
- by hand: AEMO Draft 2026 ISP Inputs and Assumptions workbook, Australian Petroleum Statistics data extract December 2025.

## Files

| File | Content |
|---|---|
| `inputs.py` | APS 2025 volumes, energy and emission factors, prices (EIA Brent, RBA, AIP check), GenCost costs, SMR, sites, water, highways; provenance |
| `observed.py` | Builds observed_data/ from the raw downloads (capacity factors calibrated to ISP REZs, demand, ocean, prices, APS, ISP extract) |
| `optimise.py` | Annual national mixed-integer programme (binary highway corridors), shadow prices, life-cycle emissions; reads calibration.json |
| `dispatch.py` | Hourly capacity expansion and dispatch over 2015-2024 weather: five grids, wind/PV groups, batteries (power and energy), turbines, electrolysers, hydrogen storage, links |
| `calibrate.py` | Iterates the annual and hourly models to one portfolio (prices, electrolyser use, wind share), runs the final hourly pass with yearly checks, the one-hour adequacy pass and verification of the fixed fleet, and the mechanism tests (daily-flexible and flat industrial demand, direct loads only) |
| `reconcile.py` | Replaces the annual model's stylised electricity supply by the hourly final fleet: reported cost, portfolio and emissions |
| `kelp.py` | Kelp zones with area, nitrogen, heatwave loss and exposure from ocean data; deployment cap |
| `scenarios.py`, `cascade.py`, `water.py`, `feed.py`, `coproduction.py`, `adequacy.py`, `montecarlo.py`, `transition.py`, `accounts.py` | Scenarios, SMR site screen, water, aquafeed, co-products, screening lulls, Monte Carlo, transition, accounts and reconciliations |
| `test_model.py` | Consistency, observed-data, hourly-reliability, regional-balance, verification, reconciliation, calibration and regression tests |
| `figures.py`, `source_data.py`, `provenance.py`, `build_documents.py`, `write_readme.py`, `run_all.py` | Figures, Source Data, provenance, documents, READMEs, build |

## Limits

Hourly capacity planning in three-hour steps (final fleet verified at one-hour resolution in every year); three nodes in the National Electricity Market with intra-node transmission costed per MW; no existing generation or hydro credited; hydrogen storage at lined-rock-cavern cost (tested 0.3-15 AUD/kWh); kelp zones from coarse ocean data with half the shelf set aside (marine-park polygons not used); SMR costs from GenCost and one overseas project; feed formulations and aquaculture costs are screening values.

## Licence

Code: MIT. Outputs, figures and illustrations: CC BY 4.0.
"""
    (HERE / "README.md").write_text(code)


if __name__ == "__main__":
    main()
