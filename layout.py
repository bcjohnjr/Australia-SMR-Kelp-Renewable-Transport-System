"""Folder layout. The code keeps results in outputs/, processed observations in observed_data/ and drawings in
illustrations/. If the files were uploaded or downloaded as one flat folder (for example through GitHub's web
upload), this module rebuilds those folders on first import by copying each file to where the code expects it.
Imported first by every script, so `python run_all.py` works from either layout."""
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OBSERVED = ("aps_2025.json", "cf_hourly.npz", "demand_hourly.npz", "isp_2026.json", "kelp_ocean.json", "prices.json",
            "raw_manifest.json", "sites.json")
ILLUSTRATIONS = ("grid_harvester_side.jpg", "grid_harvester_top.jpg")
ROOT_FILES = ("calibration.json",)          # stay beside the code

# inside the submission package the model lives in <package>/Code/model; elsewhere documents go to ./package
IN_PACKAGE = HERE.name == "model" and HERE.parent.name == "Code"
PKG = HERE.parent.parent if IN_PACKAGE else HERE / "package"


def ensure():
    moved = 0
    for sub, names in (("observed_data", OBSERVED), ("illustrations", ILLUSTRATIONS)):
        for n in names:
            src, dst = HERE / n, HERE / sub / n
            if src.exists() and not dst.exists():
                dst.parent.mkdir(exist_ok=True)
                shutil.copy2(src, dst)
                moved += 1
    for src in list(HERE.glob("*.json")) + list(HERE.glob("*.csv")):
        if src.name in OBSERVED or src.name in ROOT_FILES or src.name.startswith("."):
            continue
        dst = HERE / "outputs" / src.name
        if not dst.exists():
            dst.parent.mkdir(exist_ok=True)
            shutil.copy2(src, dst)
            moved += 1
    (HERE / "outputs" / "source_data").mkdir(parents=True, exist_ok=True)
    (HERE / "paper_figures").mkdir(exist_ok=True)
    if not IN_PACKAGE:
        for d in ("Submission", "Supplementary", "Review", "Data", "Figures", "Repository"):
            (PKG / d).mkdir(parents=True, exist_ok=True)
    return moved


ensure()
