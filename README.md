# Replacing Australia's transport fuels: electricity, biofuels and nuclear heat: model and data

Python model for the article by Jonathan Karl Bily, Christoph Pahl and Patricia Valdés Bacallao (submitted to Science).

## Reproduce

```bash
python -m pip install -r requirements-lock.txt
python run_all.py              # or --no-pdf without LibreOffice; --recalibrate to redo the hourly calibration
python test_model.py           # the tests alone
```

Measured: 45 s for the full build with PDFs using the shipped calibration; the hourly recalibration took 283 min. Step times are written to `outputs/runtime.json` on every run.

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
