"""Observed data for version 4: processes the raw downloads (fetch_data.py, fetch_data_part2.py and the three
workbooks downloaded by hand) into the compact files in observed_data/ that the models read.

    python observed.py --raw /path/to/data_raw      # rebuild observed_data/ from raw files (about 2 minutes)
    python observed.py                              # print a summary of the processed files

The raw files (about 450 MB) are not shipped; their URLs, sizes and SHA-256 hashes are in observed_data/raw_manifest.json
and the download scripts reproduce them. Everything below is deterministic.

Contents of observed_data/
  cf_hourly.npz        hourly capacity factors 2015-2024 (UTC) for wind (140 m hub, generic 6.2 MW, 170 m rotor) and
                       single-axis-tracking PV (DC/AC 1.25) at 24 sites, from ERA5 (Open-Meteo), each site scaled to
                       the AEMO 2026 ISP REZ capacity factor where a REZ matches (others: median NEM scaling).
  sites.json           site metadata, raw and calibrated mean capacity factors, matched REZ and scaling factor
  demand_hourly.npz    hourly operational demand (MW) for NSW1, QLD1, VIC1, SA1, TAS1 (2015-2024) and WA SWIS (2015-2023)
  kelp_ocean.json      per kelp zone: SST climatology, marine heatwave statistics (Hobday et al. 2016 definition),
                       days above the species' thermal limit, wave climate, nitrate by month and depth, shelf area 10-60 m
  prices.json          EIA Brent (monthly), RBA AUD/USD, AIP terminal-gate prices (national average), 2025 and October 2026
  aps_2025.json        Australian Petroleum Statistics, calendar 2025 sales by product and by state
  isp_2026.json        AEMO Draft 2026 ISP IASR: REZ capacity factors, 2050 build costs (Step Change), battery
                       properties, connection costs and REZ augmentation costs per MW
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OBS = HERE / "observed_data"

SITE_REZ = {   # site -> AEMO ISP REZ id used for calibration (None: no NEM REZ)
    "NSW_Central_West_Orana": "N3", "NSW_New_England": "N2", "NSW_South_West": "N5", "NSW_Hunter": "N9",
    "VIC_Western": "V3", "VIC_Murray_River": "V1", "VIC_Gippsland": "V6", "TAS_North_West": "T2",
    "TAS_Central_Highlands": "T3", "SA_Mid_North": "S3", "SA_Eyre_Peninsula": "S7", "SA_Northern_Port_Augusta": "S5",
    "QLD_Darling_Downs": "Q8a", "QLD_Fitzroy": "Q6", "QLD_Isaac": "Q4", "QLD_Far_North": "Q1",
    "QLD_North_West_Mt_Isa": None, "WA_Mid_West": None, "WA_South_Wheatbelt": None, "WA_Goldfields": None,
    "WA_Pilbara": None, "WA_Kimberley": None, "NT_Darwin": None, "NT_Alice_Springs": None,
}
SYSTEM_OF = {"NSW": "NEM", "VIC": "NEM", "QLD": "NEM", "SA": "NEM", "TAS": "NEM", "WA": "WA", "WA_NW": "WA", "NT": "NT"}
KELP_SPECIES_LIMIT_C = {   # sustained-temperature limit used for 'stress days' (screening, literature range)
    "tas_se": 20.0, "tas_e": 20.0, "bass": 23.0, "bonney": 23.0, "sa_gulfs": 23.0, "sa_shelf": 23.0,
    "wa_south": 23.0, "wa_west": 23.0, "nsw_south": 23.0}
SPECIES = {"tas_se": "giant kelp (Macrocystis)", "tas_e": "giant kelp (Macrocystis)"}


# ============================================================================================ wind and solar
def wind_power_curve(v, rated_mw=6.2, rotor_m=170.0, cp=0.45, cut_in=3.0, cut_out=25.0, rho=1.225):
    """Per-unit power of a generic low-specific-power turbine; ramps smoothly near cut-out (storm control)."""
    area = math.pi * (rotor_m / 2) ** 2
    p = 0.5 * rho * area * cp * np.maximum(v, 0.0) ** 3 / (rated_mw * 1e6)
    p = np.clip(p, 0.0, 1.0)
    p = np.where(v < cut_in, 0.0, p)
    p = np.where(v > cut_out, np.clip(1.0 - (v - cut_out) / 5.0, 0.0, 1.0), p)   # high-wind ride-through to 30 m/s
    return p


def wind_cf(v100, v10, scale=1.0, hub=140.0, losses=0.12):
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha = np.log(np.maximum(v100, 0.1) / np.maximum(v10, 0.1)) / np.log(10.0)
    alpha = np.clip(np.nan_to_num(alpha, nan=0.14), 0.0, 0.40)
    vh = scale * v100 * (hub / 100.0) ** alpha
    return wind_power_curve(vh) * (1 - losses)


def solar_position(t_utc, lat, lon):
    """Zenith and azimuth (deg, azimuth clockwise from north) for numpy datetime64 times (NOAA algorithm)."""
    t = (t_utc - np.datetime64("2000-01-01T12:00")) / np.timedelta64(1, "D")      # days since J2000
    g = np.radians((357.529 + 0.98560028 * t) % 360)
    q = (280.459 + 0.98564736 * t) % 360
    L = np.radians((q + 1.915 * np.sin(g) + 0.020 * np.sin(2 * g)) % 360)
    e = np.radians(23.439 - 0.00000036 * t)
    ra = np.arctan2(np.cos(e) * np.sin(L), np.cos(L))
    dec = np.arcsin(np.sin(e) * np.sin(L))
    gmst = (18.697374558 + 24.06570982441908 * t) % 24
    ha = np.radians(((gmst * 15 + lon) - np.degrees(ra) + 540) % 360 - 180)
    la = np.radians(lat)
    cz = np.sin(la) * np.sin(dec) + np.cos(la) * np.cos(dec) * np.cos(ha)
    zen = np.degrees(np.arccos(np.clip(cz, -1, 1)))
    az = np.degrees(np.arctan2(-np.sin(ha), np.tan(dec) * np.cos(la) - np.sin(la) * np.cos(ha))) % 360
    return zen, az


def pv_cf(times, lat, lon, ghi, dni, temp, scale=1.0, dc_ac=1.25, losses=0.12, gamma=-0.0035, albedo=0.2):
    """Single-axis (north-south axis) tracking PV, AC output per kW_ac. Radiation is the mean of the preceding hour,
    so the sun position is taken at the half hour."""
    zen, az = solar_position(times - np.timedelta64(30, "m"), lat, lon)
    up = zen < 89.5
    z, a = np.radians(zen), np.radians(az)
    # ideal rotation of a horizontal N-S tracker (no backtracking), limited to +-60 deg
    rot = np.arctan2(np.sin(z) * np.sin(a), np.cos(z))
    rot = np.clip(rot, -math.radians(60), math.radians(60))
    sun = np.stack([np.sin(z) * np.sin(a), np.sin(z) * np.cos(a), np.cos(z)])        # east, north, up
    normal = np.stack([np.sin(rot), np.zeros_like(rot), np.cos(rot)])
    cos_inc = np.clip((sun * normal).sum(0), 0, 1)
    dhi = np.clip(ghi - dni * np.cos(z), 0, None)
    tilt = np.abs(rot)
    poa = np.where(up, dni * cos_inc + dhi * (1 + np.cos(tilt)) / 2 + ghi * albedo * (1 - np.cos(tilt)) / 2, 0.0)
    tcell = temp + poa / 800.0 * 25.0
    dc = scale * poa / 1000.0 * (1 + gamma * (tcell - 25.0)) * (1 - losses)
    return np.clip(dc * dc_ac, 0.0, 1.0)


def read_weather(path):
    with gzip.open(path, "rt") as f:
        r = csv.reader(f)
        h = next(r)
        rows = [x for x in r]
    t = np.array([np.datetime64(x[0]) for x in rows])
    cols = {k: np.array([float(x[i + 1]) if x[i + 1] != "" else np.nan for x in rows]) for i, k in enumerate(h[1:6])}
    return t, cols


def isp_cf(isp_xlsx):
    import openpyxl
    wb = openpyxl.load_workbook(isp_xlsx, read_only=True, data_only=True)
    ws = wb["Capacity Factors "]
    out = {}
    for r in ws.iter_rows(min_row=8, max_row=212, values_only=True):
        rez, name, tech = r[1], r[2], r[3]
        vals = [v for v in r[5:] if isinstance(v, (int, float))]
        if rez and tech in ("Wind High", "Large scale Solar PV") and vals:
            out.setdefault(rez, {})["wind" if tech == "Wind High" else "pv"] = float(np.mean(vals))
            out[rez]["name"] = name
    return out


def calibrate(f, target, lo=0.6, hi=1.6):
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def build_cf(raw, isp_xlsx):
    sites = json.loads((raw / "weather" / "sites.json").read_text()) if (raw / "weather" / "sites.json").exists() else None
    if sites is None:
        import fetch_data
        sites = {k: dict(lat=v[0], lon=v[1], region=v[2]) for k, v in fetch_data.SITES.items()}
    icf = isp_cf(isp_xlsx)
    names = list(SITE_REZ)
    W, P, meta = [], [], {}
    times = None
    for n in names:
        t, c = read_weather(raw / "weather" / f"{n}.csv.gz")
        times = t if times is None else times
        assert len(t) == len(times) and (t == times).all(), n
        lat, lon = sites[n]["lat"], sites[n]["lon"]
        v100 = np.nan_to_num(c["wind_speed_100m"], nan=np.nanmean(c["wind_speed_100m"]))
        v10 = np.nan_to_num(c["wind_speed_10m"], nan=np.nanmean(c["wind_speed_10m"]))
        ghi = np.nan_to_num(c["shortwave_radiation"]); dni = np.nan_to_num(c["direct_normal_irradiance"])
        tmp = np.nan_to_num(c["temperature_2m"], nan=20.0)
        raw_w = float(wind_cf(v100, v10).mean())
        raw_p = float(pv_cf(times, lat, lon, ghi, dni, tmp).mean())
        rez = SITE_REZ[n]
        tw = icf.get(rez, {}).get("wind") if rez else None
        tp = icf.get(rez, {}).get("pv") if rez else None
        kw = calibrate(lambda s: wind_cf(v100, v10, s).mean(), tw) if tw else None
        kp = calibrate(lambda s: pv_cf(times, lat, lon, ghi, dni, tmp, s).mean(), tp, 0.5, 1.8) if tp else None
        meta[n] = dict(lat=lat, lon=lon, state=sites[n]["region"], system=SYSTEM_OF[sites[n]["region"]], rez=rez,
                       rez_name=icf.get(rez, {}).get("name") if rez else None, isp_wind_cf=tw, isp_pv_cf=tp,
                       raw_wind_cf=raw_w, raw_pv_cf=raw_p, wind_scale=kw, pv_scale=kp,
                       _arrays=(v100, v10, ghi, dni, tmp))
    kw_med = float(np.median([m["wind_scale"] for m in meta.values() if m["wind_scale"]]))
    kp_med = float(np.median([m["pv_scale"] for m in meta.values() if m["pv_scale"]]))
    for n in names:
        m = meta[n]
        v100, v10, ghi, dni, tmp = m.pop("_arrays")
        m["wind_scale_used"] = m["wind_scale"] or 1.0      # no REZ benchmark: raw ERA5 (conservative outside the NEM)
        m["pv_scale_used"] = m["pv_scale"] or kp_med
        w = wind_cf(v100, v10, m["wind_scale_used"])
        p = pv_cf(times, m["lat"], m["lon"], ghi, dni, tmp, m["pv_scale_used"])
        m["wind_cf"], m["pv_cf"] = float(w.mean()), float(p.mean())
        yrs = times.astype("datetime64[Y]").astype(int) + 1970
        m["wind_cf_by_year"] = {int(y): float(w[yrs == y].mean()) for y in np.unique(yrs)}
        m["pv_cf_by_year"] = {int(y): float(p[yrs == y].mean()) for y in np.unique(yrs)}
        W.append(w.astype(np.float32))
        P.append(p.astype(np.float32))
    np.savez_compressed(OBS / "cf_hourly.npz", wind=np.array(W, dtype=np.float16), pv=np.array(P, dtype=np.float16),
                        sites=np.array(names), t0=str(times[0]), hours=len(times))
    (OBS / "sites.json").write_text(json.dumps(dict(sites=meta, wind_scale_median=kw_med, pv_scale_median=kp_med,
                                                    method=dict(wind="ERA5 100 m and 10 m wind (hourly shear), hub 140 m, "
                                                                     "Cp 0.45 power curve, 6.2 MW / 170 m rotor, losses 12%",
                                                                pv="single-axis N-S tracking, DC/AC 1.25, losses 12%, "
                                                                   "-0.35%/K, albedo 0.2",
                                                                calibration="wind speed (or irradiance) scaled so the "
                                                                            "2015-2024 mean equals the ISP REZ mean; sites "
                                                                            "without an ISP REZ: wind unscaled (ERA5), PV "
                                                                            "scaled by the NEM median")),
                                               indent=1))


# ============================================================================================ demand
def build_demand(raw):
    import pandas as pd
    t0 = pd.Timestamp("2015-01-01 00:00")
    idx = pd.date_range(t0, periods=87672, freq="h")
    out = {}
    for reg in ("NSW1", "QLD1", "VIC1", "SA1", "TAS1"):
        fs = sorted((raw / "demand" / "nem").glob(f"PRICE_AND_DEMAND_*_{reg}.csv"))
        d = pd.concat([pd.read_csv(f, usecols=["SETTLEMENTDATE", "TOTALDEMAND"]) for f in fs])
        # interval-ending AEST stamps -> interval-start UTC hour
        ts = pd.to_datetime(d["SETTLEMENTDATE"], format="%Y/%m/%d %H:%M:%S") - pd.Timedelta(hours=10) - pd.Timedelta(minutes=1)
        h = d.groupby(ts.dt.floor("h"))["TOTALDEMAND"].mean()
        out[reg] = h.reindex(idx).to_numpy(dtype=np.float32)
    fs = sorted((raw / "demand" / "wem").glob("load-summary-*.csv"))
    d = pd.concat([pd.read_csv(f, usecols=["Trading Interval", "Operational Load (MWh)"]) for f in fs])
    ts = pd.to_datetime(d["Trading Interval"]) - pd.Timedelta(hours=8)
    h = (d["Operational Load (MWh)"] * 2).groupby(ts.dt.floor("h")).mean()
    out["WA_SWIS"] = h.reindex(idx).to_numpy(dtype=np.float32)
    np.savez_compressed(OBS / "demand_hourly.npz", **out, t0=str(t0))


# ============================================================================================ ocean
def hobday(dates, sst, clim=(1983, 2012), min_days=5):
    """Marine heatwaves after Hobday et al. (2016): daily SST above the 90th-percentile climatology (11-day window)
    for at least five days. Returns per-year days, events and cumulative intensity."""
    doy = np.array([d.timetuple().tm_yday for d in dates])
    yr = np.array([d.year for d in dates])
    base = (yr >= clim[0]) & (yr <= clim[1])
    p90 = np.zeros(367); mean = np.zeros(367)
    for d in range(1, 367):
        win = base & (np.minimum(np.abs(doy - d), 366 - np.abs(doy - d)) <= 5)
        p90[d] = np.nanpercentile(sst[win], 90); mean[d] = np.nanmean(sst[win])
    over = sst > p90[doy]
    mhw = np.zeros_like(over)
    i = 0
    while i < len(over):
        if over[i]:
            j = i
            while j < len(over) and over[j]:
                j += 1
            if j - i >= min_days:
                mhw[i:j] = True
            i = j
        else:
            i += 1
    res = {}
    for y in np.unique(yr):
        m = yr == y
        ev = int(((mhw[m][1:] & ~mhw[m][:-1]).sum()) + (1 if mhw[m][0] else 0))
        res[int(y)] = dict(mhw_days=int(mhw[m].sum()), events=ev,
                           cum_intensity=float(np.nansum((sst[m] - mean[doy[m]])[mhw[m]])))
    return res, mean


def build_ocean(raw, nitrate_csv):
    import datetime as dt
    from scipy.io import netcdf_file
    import fetch_data
    zones = fetch_data.KELP
    out = {}
    # bathymetry
    nc = netcdf_file(str(raw / "ocean" / "etopo_southern_australia.nc"), "r", mmap=False)
    blat, blon = nc.variables["latitude"][:].copy(), nc.variables["longitude"][:].copy()
    alt = nc.variables["altitude"][:].astype(float)
    dlat = abs(blat[1] - blat[0]); dlon = abs(blon[1] - blon[0])
    # nitrate
    N = {}
    with open(nitrate_csv) as f:
        for row in csv.DictReader(f):
            N.setdefault((float(row["lat"]), float(row["lon"])), []).append(
                (int(row["month"]), float(row["depth_m"]), float(row["nitrate_umol_kg"])))
    npts = np.array(list(N.keys()))
    for z, (lon, lat) in zones.items():
        d = {}
        # SST: mean over the box each day
        days = {}
        with open(raw / "ocean" / "sst" / f"oisst_{z}.csv") as f:
            r = csv.reader(f); next(r); next(r)
            for row in r:
                if row[4] in ("", "NaN"):
                    continue
                days.setdefault(row[0][:10], []).append(float(row[4]))
        dates = [dt.date.fromisoformat(k) for k in sorted(days)]
        sst = np.array([np.mean(days[k.isoformat()]) for k in dates])
        mhw, clim = hobday(dates, sst)
        yr = np.array([x.year for x in dates])
        lim = KELP_SPECIES_LIMIT_C[z]
        stress = {int(y): int((sst[yr == y] > lim).sum()) for y in np.unique(yr)}
        rec = (yr >= 2015) & (yr <= 2024)
        d.update(sst_mean_2015_2024=float(sst[rec].mean()), sst_max_month_clim=float(np.nanmax(clim[1:366])),
                 sst_trend_c_per_decade=float(np.polyfit(np.arange(len(sst)) / 3652.5, sst, 1)[0]),
                 mhw=mhw, species_limit_c=lim, stress_days=stress,
                 mhw_days_mean_1983_2012=float(np.mean([mhw[y]["mhw_days"] for y in range(1983, 2013)])),
                 mhw_days_mean_2015_2024=float(np.mean([mhw[y]["mhw_days"] for y in range(2015, 2025)])),
                 damaging_year_share_2005_2024=float(np.mean([stress.get(y, 0) >= 10 for y in range(2005, 2025)])),
                 sst_first=str(dates[0]), sst_last=str(dates[-1]))
        # waves
        with gzip.open(raw / "weather" / f"waves_{z}.csv.gz", "rt") as f:
            r = csv.DictReader(f)
            hs = np.array([float(x["wave_height_max"]) for x in r if x["wave_height_max"] not in ("", "None")])
        d.update(hs_max_p50=float(np.median(hs)), hs_max_p99=float(np.percentile(hs, 99)),
                 days_hs_over_6m_per_yr=float((hs > 6).sum() / (len(hs) / 365.25)))
        # nitrate: nearest grid points (within 1.5 deg) with data, mean over 0-30 m and 30-60 m by month
        dist = np.hypot(npts[:, 0] - lat, (npts[:, 1] - lon) * np.cos(np.radians(lat)))
        near = npts[dist <= 1.5]
        near = near[np.argsort(np.hypot(near[:, 0] - lat, near[:, 1] - lon))][:4]
        surf, deep = np.full(12, np.nan), np.full(12, np.nan)
        for m in range(1, 13):
            s = [v for p in near for (mm, dep, v) in N[tuple(p)] if mm == m and dep <= 30]
            q = [v for p in near for (mm, dep, v) in N[tuple(p)] if mm == m and 30 < dep <= 60]
            surf[m - 1] = np.mean(s) if s else np.nan
            deep[m - 1] = np.mean(q) if q else np.nan
        d.update(nitrate_0_30m=[round(float(x), 3) for x in surf], nitrate_30_60m=[round(float(x), 3) for x in deep],
                 nitrate_points=[[float(a), float(b)] for a, b in near],
                 months_surface_no3_ge_1=int(np.nansum(surf >= 1.0)),
                 months_any_no3_ge_1_within_60m=int(np.nansum(np.fmax(surf, deep) >= 1.0)))
        # shelf area 10-60 m deep within 50 km of the zone centre
        ii = np.where(np.abs(blat - lat) <= 0.8)[0]
        jj = np.where(np.abs(blon - lon) <= 1.1)[0]
        sub = alt[np.ix_(ii, jj)]
        LA, LO = np.meshgrid(blat[ii], blon[jj], indexing="ij")
        dist = np.hypot((LA - lat) * 111.0, (LO - lon) * 111.0 * np.cos(np.radians(lat)))
        cell_km2 = (dlat * 111.0) * (dlon * 111.0 * np.cos(np.radians(LA)))
        d["centre_depth_m"] = float(-sub[np.unravel_index(np.argmin(dist), dist.shape)])
        for R in (50, 75):
            for lo_, hi_ in ((10, 60), (10, 100), (10, 150)):
                d[f"area_{lo_}_{hi_}m_within_{R}km_km2"] = float(cell_km2[(dist <= R) & (sub <= -lo_) & (sub >= -hi_)].sum())
        out[z] = d
    (OBS / "kelp_ocean.json").write_text(json.dumps(out, indent=1))


# ============================================================================================ prices, APS, ISP
def build_prices(raw):
    import pandas as pd
    b = pd.read_excel(raw / "econ" / "eia_brent_monthly.xlsx", sheet_name="Data 1", skiprows=2)
    b.columns = ["date", "brent"]
    b["date"] = pd.to_datetime(b["date"])
    brent = {d.strftime("%Y-%m"): float(v) for d, v in zip(b["date"], b["brent"]) if d.year >= 2015}
    fx = {}
    with open(raw / "econ" / "rba_f11_1_exchange_rates.csv", encoding="latin-1") as f:
        rows = list(csv.reader(f))
    hdr = next(i for i, r in enumerate(rows) if r and r[0].strip() == "Series ID")
    col = rows[hdr].index("FXRUSD")
    for r in rows[hdr + 1:]:
        if r and r[0] and len(r) > col and r[col].strip():
            try:
                d = pd.to_datetime(r[0], dayfirst=True)
                fx.setdefault(d.strftime("%Y-%m"), []).append(float(r[col]))
            except Exception:
                pass
    fx = {k: float(np.mean(v)) for k, v in fx.items()}
    tgp = {}
    aip = raw / "part2" / "econ" / "aip" / "AIP_TGP_Data_13-Nov-2026.xlsx"
    for sh, k in (("Petrol TGP", "petrol"), ("Diesel TGP", "diesel")):
        v = pd.read_excel(aip, sheet_name=sh)
        c = v.columns[0]
        v[c] = pd.to_datetime(v[c], errors="coerce")
        v = v.dropna(subset=[c])
        nat = [x for x in v.columns if "National" in str(x)][0]
        v[nat] = pd.to_numeric(v[nat], errors="coerce")
        tgp[k] = dict(avg2025=float(v[v[c].dt.year == 2025][nat].mean()),
                      oct2026=float(v[(v[c] >= "2026-10-01") & (v[c] <= "2026-10-31")][nat].mean()),
                      last_date=str(v[c].max().date()))
    yr25 = [f"2025-{m:02d}" for m in range(1, 13)]
    out = dict(brent_usd_bbl=brent, aud_usd=fx,
               brent_avg2025=float(np.mean([brent[m] for m in yr25])), brent_oct2026=brent.get("2026-10"),
               audusd_avg2025=float(np.mean([fx[m] for m in yr25 if m in fx])), audusd_oct2026=fx.get("2026-10"),
               tgp_cpl_incl_gst_excise=tgp,
               sources=dict(brent="EIA RBRTEm (Europe Brent spot FOB, monthly)", fx="RBA F11.1 FXRUSD (monthly mean)",
                            tgp="AIP terminal gate prices, national average, inclusive of GST and excise"))
    (OBS / "prices.json").write_text(json.dumps(out, indent=1))


def build_aps(aps_xlsx):
    import pandas as pd
    d = pd.read_excel(aps_xlsx, sheet_name="Sales of products")
    d["Month"] = pd.to_datetime(d["Month"], errors="coerce")
    y = d[d["Month"].dt.year == 2025]
    num = y.drop(columns=["Month"]).apply(pd.to_numeric, errors="coerce").sum()
    s = pd.read_excel(aps_xlsx, sheet_name="Sales by state and territory")
    s["Month"] = pd.to_datetime(s["Month"], errors="coerce")
    s = s[s["Month"].dt.year == 2025]
    st = {}
    for col, k in (("Automotive gasoline: total (ML)", "petrol"), ("Diesel oil: total", "diesel"),
                   ("Aviation turbine fuel: total (ML)", "jet")):
        g = s.groupby("State")[col].apply(lambda x: pd.to_numeric(x, errors="coerce").sum())
        st[k] = {str(a): float(b) for a, b in g.items()}
    out = dict(months=int(len(y)), first=str(y["Month"].min().date()), last=str(y["Month"].max().date()),
               sales_ml={k: float(v) for k, v in num.items()}, by_state_ml=st,
               source="DCCEEW Australian Petroleum Statistics, data extract December 2025 (Sales of products; "
                      "Sales by state and territory)")
    (OBS / "aps_2025.json").write_text(json.dumps(out, indent=1))


def build_isp(isp_xlsx):
    import openpyxl
    wb = openpyxl.load_workbook(isp_xlsx, read_only=True, data_only=True)
    ws = wb["Build costs"]
    rows = list(ws.iter_rows(min_row=10, max_row=80, max_col=40, values_only=True))
    hdr = rows[0]
    c50 = hdr.index("2049-50")
    c26 = hdr.index("2025-26")
    build = {}
    for r in rows[1:]:
        if r[1] and r[3] == "Step Change":
            build[r[1]] = {"2025-26": float(r[c26]), "2049-50": float(r[c50])}
    ws = wb["Fixed OPEX"]
    fom = {}
    for r in ws.iter_rows(min_row=8, max_row=60, max_col=9, values_only=True):
        if r[6] and isinstance(r[7], (int, float)):
            fom[r[6]] = float(r[7])
    ws = wb["Connection cost"]
    conn = {}
    for r in ws.iter_rows(min_row=8, max_row=60, max_col=9, values_only=True):
        if r[1] and isinstance(r[8], (int, float)):
            conn[r[1]] = float(r[8])
    ws = wb["REZ augmentations options"]
    aug = []
    for r in ws.iter_rows(min_row=11, max_row=400, max_col=12, values_only=True):
        mw, cost = r[6], r[8]
        try:
            mw = float(str(mw).replace(",", "").split()[0])
            cost = float(cost)
        except Exception:
            continue
        if mw > 0 and cost > 0:
            aug.append((r[1] or "", mw, cost))
    per = np.array([c / m for _, m, c in aug])
    wts = np.array([m for _, m, _ in aug])
    isp = dict(rez_cf=isp_cf(isp_xlsx), build_cost_aud_kw_real2025=build, fixed_opex_aud_kw_yr=fom,
               connection_aud_kw=conn,
               rez_augmentation=dict(n_options=len(aug), aud_m_per_mw_median=float(np.median(per)),
                                     aud_m_per_mw_p25=float(np.percentile(per, 25)),
                                     aud_m_per_mw_p75=float(np.percentile(per, 75)),
                                     aud_m_per_mw_capacity_weighted=float((per * wts).sum() / wts.sum())),
               battery=dict(charge_eff=0.925, discharge_eff=0.925, rte_4h=0.85, degradation_4h=0.014),
               source="AEMO Draft 2026 ISP Inputs and Assumptions workbook (Build costs: GenCost Global NZE post 2050 / "
                      "Step Change, real 2025 AUD; Storage properties; Connection cost; REZ augmentations options)")
    (OBS / "isp_2026.json").write_text(json.dumps(isp, indent=1))


def raw_manifest(raw, extra):
    files = []
    for p in sorted(raw.rglob("*")):
        if p.is_file():
            files.append(dict(path=str(p.relative_to(raw)), bytes=p.stat().st_size,
                              sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    for p in extra:
        files.append(dict(path=Path(p).name, bytes=Path(p).stat().st_size,
                          sha256=hashlib.sha256(Path(p).read_bytes()).hexdigest()))
    (OBS / "raw_manifest.json").write_text(json.dumps(dict(n_files=len(files), files=files), indent=0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw")
    ap.add_argument("--isp")
    ap.add_argument("--aps")
    ap.add_argument("--nitrate")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    OBS.mkdir(exist_ok=True)
    if a.raw:
        raw = Path(a.raw)
        isp = Path(a.isp or raw / "manual" / "Draft_2026_ISP_Inputs_and_Assumptions_workbook.xlsx")
        aps = Path(a.aps or raw / "manual" / "australian_petroleum_statistics_data_extract_december_2025.xlsx")
        nit = Path(a.nitrate or raw / "part2" / "ocean" / "woa23_nitrate_aus_0-200m.csv")
        steps = a.only or ["isp", "aps", "prices", "ocean", "demand", "cf", "manifest"]
        for s in steps:
            print("observed:", s, flush=True)
            {"isp": lambda: build_isp(isp), "aps": lambda: build_aps(aps), "prices": lambda: build_prices(raw),
             "ocean": lambda: build_ocean(raw, nit), "demand": lambda: build_demand(raw),
             "cf": lambda: build_cf(raw, isp), "manifest": lambda: raw_manifest(raw, [])}[s]()
    for f in sorted(OBS.glob("*")):
        print(f"  {f.name:28s} {f.stat().st_size / 1e6:6.2f} MB")


if __name__ == "__main__":
    main()
