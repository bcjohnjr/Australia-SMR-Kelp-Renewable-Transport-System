#!/usr/bin/env python3
"""Download the observational data needed for version 4 of the Australian transport-energy study.

Run on a machine with internet access (Python 3.8+, standard library only):

    python3 fetch_data.py                 # everything (about 30-60 min, mostly paced weather requests)
    python3 fetch_data.py --only weather  # one block: weather, demand, ocean, econ
    python3 fetch_data.py --years 2015 2024

It is safe to re-run: files already downloaded are skipped. At the end it writes data_raw/manifest.json (URL,
size, SHA-256, time, status of every file) and packs everything into australia_data_v4.zip for upload.

Blocks
  weather  Hourly ERA5 reanalysis (Open-Meteo archive API, free, no key) at 24 renewable-zone sites, 2015-2024:
           100 m and 10 m wind speed, global horizontal and direct normal irradiance, temperature.
           Also daily wave height at the nine kelp zones (Open-Meteo marine API, ERA5-ocean) for farm exposure.
  demand   AEMO NEM half-hourly price and demand by region (NSW1, QLD1, VIC1, SA1, TAS1), 2015-2024, and the
           WA Wholesale Electricity Market load summaries (if reachable).
  ocean    NOAA OISST v2.1 daily sea-surface temperature 1982-present around each kelp zone (marine-heatwave
           statistics, Hobday definition); World Ocean Atlas 2023 monthly nitrate 0-100 m (natural N supply);
           ETOPO 1-arc-minute bathymetry of southern Australia (10-60 m depth band for farm area).
  econ     EIA daily and monthly Brent spot price; RBA AUD/USD; the latest Australian Petroleum Statistics and
           AIP terminal-gate-price workbooks (scraped from their landing pages).

Some data cannot be fetched reliably by script (licence pages or changing URLs); they are listed in MANUAL at the
end of the run with instructions.
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("data_raw")
UA = "Mozilla/5.0 (research data download; australia-transport-energy v4)"
MANIFEST = []

# Renewable-energy-zone sites (lat, lon). Edit freely; the v4 dispatch model reads whatever is here.
SITES = {
    "NSW_Central_West_Orana": (-32.25, 149.00, "NSW"), "NSW_New_England": (-30.20, 151.60, "NSW"),
    "NSW_South_West": (-34.80, 144.60, "NSW"), "VIC_Western": (-37.60, 142.40, "VIC"),
    "VIC_Murray_River": (-35.20, 142.80, "VIC"), "VIC_Gippsland": (-38.30, 146.80, "VIC"),
    "TAS_North_West": (-41.10, 145.30, "TAS"), "TAS_Central_Highlands": (-42.20, 146.70, "TAS"),
    "SA_Mid_North": (-33.60, 138.70, "SA"), "SA_Eyre_Peninsula": (-33.40, 135.90, "SA"),
    "SA_Northern_Port_Augusta": (-32.50, 137.80, "SA"), "QLD_Darling_Downs": (-27.60, 151.10, "QLD"),
    "QLD_Fitzroy": (-23.50, 150.00, "QLD"), "QLD_Isaac": (-21.80, 148.50, "QLD"),
    "QLD_Far_North": (-17.40, 145.40, "QLD"), "QLD_North_West_Mt_Isa": (-20.70, 139.50, "QLD"),
    "WA_Mid_West": (-29.00, 115.30, "WA"), "WA_South_Wheatbelt": (-33.30, 117.20, "WA"),
    "WA_Goldfields": (-30.80, 121.50, "WA"), "WA_Pilbara": (-21.00, 118.00, "WA_NW"),
    "WA_Kimberley": (-17.90, 122.30, "WA_NW"), "NT_Darwin": (-12.60, 131.00, "NT"),
    "NT_Alice_Springs": (-23.70, 133.90, "NT"), "NSW_Hunter": (-32.40, 150.90, "NSW"),
}
# Kelp zones (lon, lat) as in geo.KELP_CENTROIDS
KELP = {"tas_se": (148.05, -43.55), "tas_e": (148.75, -42.10), "bass": (146.60, -39.55),
        "bonney": (140.70, -38.60), "sa_gulfs": (137.25, -34.25), "sa_shelf": (135.30, -35.55),
        "wa_south": (119.00, -35.05), "wa_west": (114.55, -30.60), "nsw_south": (150.45, -36.60)}
NEM_REGIONS = ["NSW1", "QLD1", "VIC1", "SA1", "TAS1"]
HOURLY_VARS = ["wind_speed_100m", "wind_speed_10m", "shortwave_radiation", "direct_normal_irradiance", "temperature_2m"]
MANUAL = []


# ---------------------------------------------------------------------------------------------------- helpers
def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def get(url, tries=5, timeout=180, pace_on_429=600):
    """GET with retries; returns bytes. Waits pace_on_429 s on HTTP 429 (Open-Meteo hourly limit)."""
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                log(f"  rate limited; waiting {pace_on_429 // 60} min")
                time.sleep(pace_on_429)
                continue
            if e.code in (400, 403, 404):
                raise
            time.sleep(5 * (k + 1))
        except Exception as e:  # network hiccup
            last = e
            time.sleep(5 * (k + 1))
    raise last


def record(path, url, status, note=""):
    p = Path(path)
    ok = p.exists()
    MANIFEST.append(dict(path=str(p), url=url, status=status, note=note,
                         bytes=p.stat().st_size if ok else 0,
                         sha256=hashlib.sha256(p.read_bytes()).hexdigest() if ok else "",
                         fetched_utc=datetime.now(timezone.utc).isoformat(timespec="seconds")))


def fetch_file(url, path, skip_existing=True, **kw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if skip_existing and path.exists() and path.stat().st_size > 0:
        record(path, url, "cached")
        return True
    try:
        data = get(url, **kw)
        path.write_bytes(data)
        record(path, url, "ok")
        return True
    except Exception as e:
        record(path, url, "failed", repr(e)[:300])
        log(f"  FAILED {url} -> {e}")
        return False


# ---------------------------------------------------------------------------------------------------- weather
def weather(y0, y1):
    """One gzip CSV per site with all years; requests are per site-year, paced to stay inside free limits."""
    out = ROOT / "weather"
    out.mkdir(parents=True, exist_ok=True)
    for name, (lat, lon, region) in SITES.items():
        path = out / f"{name}.csv.gz"
        if path.exists():
            record(path, "open-meteo archive", "cached")
            continue
        rows = []
        for y in range(y0, y1 + 1):
            q = dict(latitude=lat, longitude=lon, start_date=f"{y}-01-01", end_date=f"{y}-12-31",
                     hourly=",".join(HOURLY_VARS), wind_speed_unit="ms", timezone="GMT", models="era5")
            url = "https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode(q)
            try:
                d = json.loads(get(url))
            except Exception as e:
                log(f"  weather {name} {y} failed: {e}")
                continue
            h = d["hourly"]
            for i, t in enumerate(h["time"]):
                rows.append([t] + [h[v][i] for v in HOURLY_VARS])
            log(f"weather {name} {y}: {len(h['time'])} h")
            time.sleep(8)          # ~13 weighted calls each; keeps well under 600/min and 5,000/h
        with gzip.open(path, "wt", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time_utc"] + HOURLY_VARS + [f"# lat={lat} lon={lon} region={region} source=ERA5 via Open-Meteo"])
            for r in rows:
                w.writerow([r[0]] + ["" if v is None else (round(v, 2) if isinstance(v, float) else v) for v in r[1:]])
        record(path, "https://archive-api.open-meteo.com/v1/archive", "ok" if rows else "failed",
               f"{len(rows)} hourly rows, {y0}-{y1}")
    meta = ROOT / "weather" / "sites.json"
    meta.write_text(json.dumps({k: dict(lat=v[0], lon=v[1], region=v[2]) for k, v in SITES.items()}, indent=1))
    # daily wave climate at the kelp zones
    for z, (lon, lat) in KELP.items():
        path = out / f"waves_{z}.csv.gz"
        if path.exists():
            record(path, "open-meteo marine", "cached")
            continue
        got = None
        for models in ("era5_ocean", None):
            q = dict(latitude=lat, longitude=lon, start_date=f"{y0}-01-01", end_date=f"{y1}-12-31",
                     daily="wave_height_max,wave_period_max,wave_direction_dominant", timezone="GMT")
            if models:
                q["models"] = models
            try:
                got = json.loads(get("https://marine-api.open-meteo.com/v1/marine?" + urllib.parse.urlencode(q)))
                break
            except Exception as e:
                log(f"  waves {z} ({models}) failed: {e}")
        if not got:
            record(path, "open-meteo marine", "failed")
            continue
        dd = got["daily"]
        with gzip.open(path, "wt", newline="") as f:
            w = csv.writer(f)
            keys = [k for k in dd if k != "time"]
            w.writerow(["date"] + keys)
            for i, t in enumerate(dd["time"]):
                w.writerow([t] + [dd[k][i] for k in keys])
        record(path, "https://marine-api.open-meteo.com/v1/marine", "ok", f"{len(dd['time'])} days")
        log(f"waves {z}: {len(dd['time'])} days")
        time.sleep(5)


# ---------------------------------------------------------------------------------------------------- demand
def demand(y0, y1):
    out = ROOT / "demand" / "nem"
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            for reg in NEM_REGIONS:
                fn = f"PRICE_AND_DEMAND_{y}{m:02d}_{reg}.csv"
                fetch_file(f"https://aemo.com.au/aemo/data/nem/priceanddemand/{fn}", out / fn)
                time.sleep(0.3)
        log(f"demand NEM {y} done")
    out = ROOT / "demand" / "wem"
    for y in range(y0, y1 + 1):
        ok = fetch_file(f"https://data.wa.aemo.com.au/public/public-data/datafiles/load-summary/load-summary-{y}.csv",
                        out / f"load-summary-{y}.csv")
        if not ok and y == y0:
            MANUAL.append("WA demand: download the WEM 'Load Summary' yearly CSVs from https://data.wa.aemo.com.au "
                          "(public-data/datafiles/load-summary) into data_raw/demand/wem/.")
            break


# ---------------------------------------------------------------------------------------------------- ocean
def ocean():
    out = ROOT / "ocean"
    # NOAA OISST v2.1 daily SST, 0.25 deg, small box around each kelp zone (ERDDAP, CSV)
    for z, (lon, lat) in KELP.items():
        q = (f"sst[(1982-01-01T12:00:00Z):1:(last)][(0.0)][({lat - 0.25}):1:({lat + 0.25})]"
             f"[({lon - 0.25}):1:({lon + 0.25})]")
        url = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg_LonPM180.csv?" + urllib.parse.quote(q, safe="[]():,")
        if fetch_file(url, out / "sst" / f"oisst_{z}.csv", timeout=600):
            log(f"SST {z} ok")
        time.sleep(2)
    # World Ocean Atlas 2023 monthly nitrate climatology, 1 deg, subset 0-100 m over southern Australia
    for mth in range(1, 13):
        base = f"woa23/DATA/nitrate/netcdf/all/1.00/woa23_all_n{mth:02d}_01.nc"
        ncss = (f"https://www.ncei.noaa.gov/thredds-ocean/ncss/{base}?var=n_an&north=-10&south=-46&west=110&east=156"
                f"&vertCoord=0&vertCoord=10&vertCoord=20&vertCoord=30&vertCoord=50&vertCoord=75&vertCoord=100"
                f"&accept=netcdf")
        p = out / "woa23" / f"woa23_nitrate_m{mth:02d}_aus.nc"
        if not fetch_file(ncss, p, timeout=600):
            # fallback: whole file (larger); kept in the package only if it downloads
            fetch_file(f"https://www.ncei.noaa.gov/thredds-ocean/fileServer/{base}", out / "woa23" / Path(base).name,
                       timeout=900)
    # ETOPO 2022-equivalent 1-arc-minute relief (ERDDAP etopo180), southern Australian shelf
    q = "altitude[(-45.5):1:(-28.0)][(112.0):1:(154.0)]"
    fetch_file("https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.nc?" + urllib.parse.quote(q, safe="[]():,"),
               out / "etopo_southern_australia.nc", timeout=900)
    MANUAL.append("Marine parks: download CAPAD (Collaborative Australian Protected Areas Database) marine polygons "
                  "(latest release, shapefile or GeoPackage) from the DCCEEW CAPAD page into data_raw/ocean/capad/.")
    MANUAL.append("Aquaculture leases and kelp extent (optional): Tasmanian marine farming lease polygons (LISTmap/"
                  "theLIST open data) and Seamap Australia habitat or IMOS kelp extent layers into data_raw/ocean/other/.")


# ---------------------------------------------------------------------------------------------------- economics
def scrape_links(page_url, pattern):
    try:
        html = get(page_url).decode("utf-8", "replace")
    except Exception as e:
        log(f"  could not open {page_url}: {e}")
        return []
    links = re.findall(r'href="([^"]+)"', html)
    full = [urllib.parse.urljoin(page_url, l) for l in links if re.search(pattern, l, re.I)]
    return list(dict.fromkeys(full))


def econ():
    out = ROOT / "econ"
    fetch_file("https://www.eia.gov/dnav/pet/hist_xls/RBRTEd.xls", out / "eia_brent_daily.xls")
    fetch_file("https://www.eia.gov/dnav/pet/hist_xls/RBRTEm.xls", out / "eia_brent_monthly.xls")
    fetch_file("https://www.rba.gov.au/statistics/tables/csv/f11.1-data.csv", out / "rba_f11_1_exchange_rates.csv")
    aps = scrape_links("https://www.energy.gov.au/energy-data/australian-petroleum-statistics", r"\.xlsx?($|\?)")
    for u in aps[:3]:
        fetch_file(u, out / "aps" / Path(urllib.parse.urlparse(u).path).name)
    if not aps:
        MANUAL.append("Australian Petroleum Statistics: download the latest data workbook (xlsx) from "
                      "https://www.energy.gov.au/energy-data/australian-petroleum-statistics into data_raw/econ/aps/.")
    tgp = scrape_links("https://www.aip.com.au/pricing/terminal-gate-prices", r"\.xlsx?($|\?)")
    for u in tgp[:2]:
        fetch_file(u, out / "aip" / Path(urllib.parse.urlparse(u).path).name)
    if not tgp:
        MANUAL.append("AIP terminal gate prices: download the historical TGP workbook from "
                      "https://www.aip.com.au/pricing/terminal-gate-prices into data_raw/econ/aip/.")
    MANUAL.append("CSIRO GenCost 2025-26 data workbook (capital costs, LCOE and system-cost tables) and the AEMO "
                  "2026 ISP Inputs and Assumptions workbook (battery, network and REZ transmission costs): save both "
                  "into data_raw/econ/benchmarks/ (used to reconcile firming and network costs).")


# ---------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=["weather", "demand", "ocean", "econ"])
    ap.add_argument("--years", nargs=2, type=int, default=[2015, 2024])
    a = ap.parse_args()
    blocks = a.only or ["econ", "ocean", "demand", "weather"]
    ROOT.mkdir(exist_ok=True)
    y0, y1 = a.years
    t0 = time.time()
    for b in blocks:
        log(f"=== {b}")
        try:
            {"weather": lambda: weather(y0, y1), "demand": lambda: demand(y0, y1), "ocean": ocean, "econ": econ}[b]()
        except KeyboardInterrupt:
            log("interrupted; re-run to resume")
            break
    (ROOT / "manifest.json").write_text(json.dumps(dict(
        created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), python=sys.version.split()[0],
        blocks=blocks, years=[y0, y1], files=MANIFEST, manual=MANUAL), indent=1))
    zp = Path("australia_data_v4.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob("*"):
            if p.is_file():
                z.write(p)
    bad = [m for m in MANIFEST if m["status"] == "failed"]
    log(f"done in {(time.time() - t0) / 60:.0f} min: {len(MANIFEST)} files, {len(bad)} failed; "
        f"{zp} = {zp.stat().st_size / 1e6:.1f} MB")
    for m in bad[:20]:
        print("  failed:", m["url"][:140])
    if MANUAL:
        print("\nPlease also download by hand (see manifest.json):")
        for x in MANUAL:
            print(" -", x)


if __name__ == "__main__":
    main()
