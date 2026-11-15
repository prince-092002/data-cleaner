"""Fingerprint of a clean.xlsx: every cell's type, value and number format, hashed.

Used by test_xlsx_on_download.py to prove that the Excel file built on download is the same as
the one the old code wrote during the clean job. The reference values in
fixtures/xlsx_old_code.json were produced by running this file on tag phase1-m6a plus Step 7
(commit 535699d), where pipeline.clean still wrote clean.xlsx itself:

    .venv/Scripts/python tests/engine/xlsx_fingerprint.py > tests/engine/fixtures/xlsx_old_code.json
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import uuid
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ["sales_orders_messy.csv", "customers_messy.xlsx", "hr_survey_messy.csv", "messy_orders_demo.csv"]


def fingerprint(path: Path) -> dict:
    ws = openpyxl.load_workbook(path)["clean"]
    digest = hashlib.sha256()
    rows = 0
    for row in ws.iter_rows():
        rows += 1
        for cell in row:
            value = cell.value
            text = value.isoformat() if hasattr(value, "isoformat") else repr(value)
            digest.update(f"{type(value).__name__}|{text}|{cell.number_format}\x1f".encode("utf-8"))
        digest.update(b"\x1e")
    return {"rows": rows, "columns": ws.max_column, "sha256": digest.hexdigest()}


def clean_sample(name: str, out: Path):
    """Profile, approve everything, clean. Returns the output folder."""
    sys.path.insert(0, str(ROOT))
    from engine import pipeline
    from engine.models import Decisions

    src = ROOT / "sample_data" / name
    prof = pipeline.profile(src)
    plan = pipeline.build_plan(prof, Decisions(approved=[p.id for p in prof.proposals]))
    pipeline.clean(src, plan, out, str(uuid.uuid4()))
    return out


if __name__ == "__main__":
    result = {}
    for sample in SAMPLES:
        with tempfile.TemporaryDirectory() as tmp:
            result[sample] = fingerprint(clean_sample(sample, Path(tmp)) / "clean.xlsx")
    print(json.dumps(result, indent=2))
