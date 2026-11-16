#!/usr/bin/env python3
"""Reproduce every number, figure, Source Data file and document of the article (Python only; any OS).

    python run_all.py                 # uses the shipped hourly calibration (outputs/dispatch.json, calibration.json)
    python run_all.py --no-pdf        # skip PDF conversion (LibreOffice not needed)
    python run_all.py --recalibrate   # also re-runs the hourly model over 2015-2024 weather and re-derives the
                                      # annual adders (calibrate.py; about 30-60 min on a laptop)

Measured step times are printed and written to outputs/runtime.json. The build stops if any test in test_model.py
fails. Observed data are read from observed_data/ (built from the raw downloads by observed.py).
"""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = layout.PKG


def step(times, *cmd):
    t = time.time()
    r = subprocess.run([sys.executable, *cmd], cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    d = time.time() - t
    name = " ".join(cmd)
    times[name] = d
    print(f"  {name:42s} {d:7.1f} s", flush=True)
    if r.returncode != 0:
        print(r.stderr[-3000:])
        raise SystemExit(f"step failed: {name}")


def main():
    args = sys.argv[1:]
    t0 = time.time()
    times = {}
    (HERE / "outputs" / "source_data").mkdir(parents=True, exist_ok=True)
    (HERE / "paper_figures").mkdir(exist_ok=True)
    recal = "--recalibrate" in args or not (HERE / "outputs" / "dispatch.json").exists()
    if recal:
        step(times, "calibrate.py")
    if recal or not (HERE / "outputs" / "dispatch_series.json").exists():
        step(times, "dispatch.py", "series")
    if recal or not (HERE / "outputs" / "dispatch_resolution.json").exists():
        step(times, "dispatch.py", "resolution")
    step(times, "-c", "import grid_harvester as g; g.main()")
    step(times, "water.py")
    step(times, "scenarios.py")
    step(times, "cascade.py")
    step(times, "feed.py")
    step(times, "coproduction.py")
    step(times, "adequacy.py")
    step(times, "montecarlo.py")
    step(times, "transition.py")
    step(times, "biofuel_costs.py")
    step(times, "accounts.py")
    step(times, "provenance.py")
    r = subprocess.run([sys.executable, "test_model.py"], cwd=HERE)
    if r.returncode != 0:
        raise SystemExit("tests failed")
    step(times, "figures.py")
    step(times, "source_data.py")
    step(times, "build_documents.py", *[a for a in args if a == "--no-pdf"])
    times["total"] = time.time() - t0
    (HERE / "outputs" / "runtime.json").write_text(json.dumps(times, indent=1))
    step(times, "write_readme.py")
    print(f"run_all: total {times['total']:.0f} s")
    # copy the record into the package folders
    data, figs = PKG / "Data", PKG / "Figures"
    (data / "source_data").mkdir(parents=True, exist_ok=True)
    figs.mkdir(exist_ok=True)
    for f in (HERE / "outputs").glob("*.json"):
        shutil.copy(f, data / f.name)
    shutil.copy(HERE / "outputs" / "input_provenance.csv", data / "input_provenance.csv")
    for f in (HERE / "outputs" / "source_data").glob("*"):
        shutil.copy(f, data / "source_data" / f.name)
    (data / "observed").mkdir(exist_ok=True)
    for f in (HERE / "observed_data").glob("*"):
        shutil.copy(f, data / "observed" / f.name)
    for f in sorted((HERE / "paper_figures").glob("Fig*_*.png")):
        stem = f.stem
        if stem.startswith("FigS"):
            n = "Figure_S" + stem[4:]
        else:
            n = "Figure_" + stem[3:]
        for ext in (".png", ".pdf"):
            src = f.with_suffix(ext)
            if src.exists():
                shutil.copy(src, figs / (n + ext))
    print("run_all: done")


if __name__ == "__main__":
    main()
