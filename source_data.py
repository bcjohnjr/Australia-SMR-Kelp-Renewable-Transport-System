"""One Source Data workbook per main figure (outputs/source_data/Source_Data_FigN.xlsx), flattened from the JSON
that figures.py writes for each figure."""
import layout  # noqa: F401  (rebuilds the folder layout if the files arrived flat)
import json
from pathlib import Path

from openpyxl import Workbook

SD = Path(__file__).resolve().parent / "outputs" / "source_data"


def flatten(obj, prefix=""):
    rows = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            rows += flatten(v, f"{prefix}{k} | " if prefix or True else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            rows += flatten(v, f"{prefix}{i} | ")
    else:
        rows.append((prefix.rstrip(" |"), obj))
    return rows


def run():
    for f in sorted(SD.glob("Fig*.json")):
        d = json.load(open(f))
        wb = Workbook()
        ws = wb.active
        ws.title = f.stem
        ws.append(["Item", "Value"])
        for k, v in flatten(d):
            ws.append([k, v])
        ws.column_dimensions["A"].width = 80
        ws.column_dimensions["B"].width = 18
        wb.save(SD / f"Source_Data_{f.stem}.xlsx")


if __name__ == "__main__":
    run()
    print("source data written")
