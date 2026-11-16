#!/usr/bin/env python3
"""Second, small download for version 4: fills the gaps left by fetch_data.py.

Run in the same folder as before (the one that contains data_raw/):

    python3 -m pip install numpy h5py      # only needed for step 1 (nitrate conversion)
    python3 fetch_data_part2.py

It writes everything to data_raw_part2/ and packs it into australia_data_v4_part2.zip (a few MB to tens of MB).
You do not need to send the first zip again.

Steps
  1. World Ocean Atlas 2023 nitrate: the twelve monthly netCDF-4 files already in data_raw/ocean/woa23/ are
     reduced to one CSV (Australian region, 0-200 m). The analysis machine cannot read netCDF-4.
  2. Australian Petroleum Statistics: the first run picked up blank submission templates; this finds the real
     data workbook through the data.gov.au catalogue (and the energy.gov.au page as a fallback).
  3. WA electricity demand for 2024 (the 2024 load-summary file was not at the expected address).
  4. CAPAD marine protected areas (polygons) for the kelp-zone constraint, through data.gov.au.
  5. AIP terminal-gate prices (October 2026 wholesale check) and the AEMO 2026 ISP Inputs and Assumptions
     workbook (battery and network costs), by scraping their pages.
Anything not found is listed at the end with a manual download link.
"""
import csv
import hashlib
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

SRC = Path("data_raw")
OUT = Path("data_raw_part2")
UA = "Mozilla/5.0 (research data download; australia-transport-energy v4 part 2)"
MANIFEST, MANUAL = [], []


def log(m):
    print(time.strftime("%H:%M:%S"), m, flush=True)


def get(url, timeout=300, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404):
                raise
            time.sleep(5 * (k + 1))
        except Exception as e:
            last = e
            time.sleep(5 * (k + 1))
    raise last


def save(url, path, note=""):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not (path.exists() and path.stat().st_size > 0):
            path.write_bytes(get(url))
        MANIFEST.append(dict(path=str(path), url=url, status="ok", note=note, bytes=path.stat().st_size,
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        log(f"  ok {path.name} ({path.stat().st_size / 1e6:.1f} MB)")
        return True
    except Exception as e:
        MANIFEST.append(dict(path=str(path), url=url, status="failed", note=repr(e)[:200]))
        log(f"  failed {url}: {e}")
        return False


def links(page, pattern, exclude=None):
    try:
        html = get(page).decode("utf-8", "replace")
    except Exception as e:
        log(f"  cannot open {page}: {e}")
        return []
    out = []
    for h in re.findall(r'href="([^"]+)"', html):
        u = urllib.parse.urljoin(page, h.replace("&amp;", "&"))
        if re.search(pattern, u, re.I) and not (exclude and re.search(exclude, u, re.I)):
            out.append(u)
    return list(dict.fromkeys(out))


def ckan(query, rows=20):
    """data.gov.au catalogue search; returns list of (dataset title, resource name, format, url, last_modified)."""
    url = "https://data.gov.au/data/api/3/action/package_search?" + urllib.parse.urlencode(dict(q=query, rows=rows))
    try:
        res = json.loads(get(url))["result"]["results"]
    except Exception as e:
        log(f"  catalogue search failed ({query}): {e}")
        return []
    out = []
    for d in res:
        for r in d.get("resources", []):
            out.append((d.get("title", ""), r.get("name") or "", (r.get("format") or "").lower(), r.get("url") or "",
                        r.get("last_modified") or r.get("created") or ""))
    return out


def fname(url):
    return urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name) or "download"


# ------------------------------------------------------------------------------------------------ 1 nitrate
def nitrate():
    files = sorted((SRC / "ocean" / "woa23").glob("woa23_all_n??_01.nc"))
    if not files:
        MANUAL.append("WOA23 nitrate: data_raw/ocean/woa23/woa23_all_nMM_01.nc not found; run from the folder that "
                      "contains data_raw/.")
        return
    try:
        import h5py
        import numpy as np
    except ImportError:
        MANUAL.append("WOA23 nitrate: install the readers with `python3 -m pip install numpy h5py` and re-run.")
        return
    path = OUT / "ocean" / "woa23_nitrate_aus_0-200m.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["month", "depth_m", "lat", "lon", "nitrate_umol_kg", "n_obs_dd"])
        for f in files:
            mth = int(re.search(r"_n(\d\d)_", f.name).group(1))
            with h5py.File(f, "r") as h:
                lat, lon, dep = h["lat"][:], h["lon"][:], h["depth"][:]
                ii = np.where((lat >= -47) & (lat <= -9))[0]
                jj = np.where((lon >= 108) & (lon <= 158))[0]
                kk = np.where(dep <= 200)[0]
                an = h["n_an"][0, kk[0]:kk[-1] + 1, ii[0]:ii[-1] + 1, jj[0]:jj[-1] + 1].astype(float)
                fill = h["n_an"].attrs.get("_FillValue", np.array([9.96921e36]))[0]
                dd = h["n_dd"][0, kk[0]:kk[-1] + 1, ii[0]:ii[-1] + 1, jj[0]:jj[-1] + 1] if "n_dd" in h else None
                for a, k in enumerate(kk):
                    for b, i in enumerate(ii):
                        for c, j in enumerate(jj):
                            v = an[a, b, c]
                            if not np.isfinite(v) or abs(v) > 1e30 or v == fill:
                                continue
                            w.writerow([mth, float(dep[k]), float(lat[i]), float(lon[j]), round(v, 3),
                                        int(dd[a, b, c]) if dd is not None and abs(dd[a, b, c]) < 1e6 else ""])
                            n += 1
            log(f"  nitrate month {mth} done")
    MANIFEST.append(dict(path=str(path), url="converted from data_raw/ocean/woa23", status="ok",
                         note=f"{n} rows", bytes=path.stat().st_size))


# ------------------------------------------------------------------------------------------------ 2 petroleum
def petroleum():
    got = 0
    for title, name, fmt, url, mod in ckan('title:"petroleum statistics"', 20) + ckan("australian petroleum statistics", 20):
        if (fmt in ("xlsx", "xls") and re.search("petroleum", title + name, re.I)
                and not re.search("template", name + url, re.I)):
            log(f"  APS candidate: {title} | {name} | {mod}")
            if save(url, OUT / "econ" / "aps" / fname(url), f"{title} | {name} | {mod}"):
                got += 1
            if got >= 3:
                break
    if not got:
        for u in links("https://www.energy.gov.au/energy-data/australian-petroleum-statistics",
                       r"\.xlsx?($|\?)", exclude="template")[:3]:
            got += save(u, OUT / "econ" / "aps" / fname(u))
    if not got:
        MANUAL.append("Australian Petroleum Statistics: download the latest data extract workbook (not a submission "
                      "template) from https://www.energy.gov.au/energy-data/australian-petroleum-statistics or "
                      "data.gov.au into data_raw_part2/econ/aps/.")


# ------------------------------------------------------------------------------------------------ 3 WA demand
def wa_demand():
    base = "https://data.wa.aemo.com.au/public/public-data/datafiles/load-summary/"
    cand = links(base, r"(2024|2025)[^/]*\.csv")
    for u in cand:
        save(u, OUT / "demand" / "wem" / fname(u))
    if not cand:
        for u in (base + "load-summary-2024.csv", base + "load_summary_2024.csv",
                  "https://data.wa.aemo.com.au/public/public-data/datafiles/load-summary/2024.csv"):
            if save(u, OUT / "demand" / "wem" / "load-summary-2024.csv"):
                return
        MANUAL.append("WA 2024 demand: from https://data.wa.aemo.com.au (Public data > Load summary, or the "
                      "post-reform 'operational demand' dataset for 2024) into data_raw_part2/demand/wem/.")


# ------------------------------------------------------------------------------------------------ 4 CAPAD
def capad():
    got = False
    for title, name, fmt, url, mod in ckan("CAPAD marine protected areas", 20):
        text = (title + " " + name).lower()
        if "marine" in text and fmt in ("zip", "geojson", "gpkg", "shp", "esri shapefile", "kmz", "kml"):
            log(f"  CAPAD candidate: {title} | {name} | {fmt} | {mod}")
            if save(url, OUT / "ocean" / "capad" / fname(url), f"{title} | {name} | {mod}"):
                got = True
                break
    if not got:
        MANUAL.append("CAPAD marine: download the latest 'CAPAD marine' spatial layer (zip shapefile or GeoPackage) "
                      "from https://www.dcceew.gov.au/environment/land/nrs/science/capad into data_raw_part2/ocean/capad/.")


# ------------------------------------------------------------------------------------------------ 5 prices, ISP
def prices_and_isp():
    tgp = []
    for page in ("https://www.aip.com.au/historical-ulp-and-diesel-tgp-data",
                 "https://www.aip.com.au/pricing/terminal-gate-prices"):
        tgp += links(page, r"(tgp|terminal).*\.xlsx?($|\?)")
    for u in list(dict.fromkeys(tgp))[:2]:
        save(u, OUT / "econ" / "aip" / fname(u))
    if not tgp:
        MANUAL.append("AIP terminal gate prices: 'Historical ULP and diesel TGP data' workbook from "
                      "https://www.aip.com.au/historical-ulp-and-diesel-tgp-data into data_raw_part2/econ/aip/.")
    isp = []
    for page in ("https://aemo.com.au/energy-systems/major-publications/integrated-system-plan-isp/2026-integrated-system-plan-isp",
                 "https://aemo.com.au/energy-systems/major-publications/integrated-system-plan-isp/2025-iasr"):
        isp += links(page, r"(input|assumption|iasr).*\.xlsx($|\?)")
    for u in list(dict.fromkeys(isp))[:2]:
        save(u, OUT / "econ" / "benchmarks" / fname(u))
    if not isp:
        MANUAL.append("AEMO 2026 ISP Inputs and Assumptions workbook (xlsx) from aemo.com.au (Integrated System Plan "
                      "> 2026 ISP > inputs, assumptions and scenarios) into data_raw_part2/econ/benchmarks/.")
    MANUAL.append("Optional: CSIRO GenCost 2025-26 data workbook from https://www.csiro.au/en/research/"
                  "technology-space/energy/energy-data-modelling/gencost into data_raw_part2/econ/benchmarks/. "
                  "Not essential: the model already uses the GenCost report values.")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", choices=["nitrate", "petroleum", "wa", "capad", "prices"])
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    t0 = time.time()
    steps = {"nitrate": ("nitrate", nitrate), "petroleum": ("petroleum statistics", petroleum),
             "wa": ("WA demand 2024", wa_demand), "capad": ("CAPAD marine", capad), "prices": ("fuel prices and ISP", prices_and_isp)}
    for name, f in [steps[k] for k in (a.only or steps)]:
        log(f"=== {name}")
        try:
            f()
        except Exception as e:
            log(f"  step failed: {e}")
            MANUAL.append(f"{name}: failed with {e!r}; please download by hand.")
    (OUT / "manifest_part2.json").write_text(json.dumps(dict(
        created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"), python=sys.version.split()[0],
        files=MANIFEST, manual=MANUAL), indent=1))
    zp = Path("australia_data_v4_part2.zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in OUT.rglob("*"):
            if p.is_file():
                z.write(p)
    log(f"done in {(time.time() - t0) / 60:.1f} min; {zp} = {zp.stat().st_size / 1e6:.1f} MB")
    if MANUAL:
        print("\nStill needed by hand (put the files in the folders named, then re-run to re-zip):")
        for m in MANUAL:
            print(" -", m)


if __name__ == "__main__":
    main()
