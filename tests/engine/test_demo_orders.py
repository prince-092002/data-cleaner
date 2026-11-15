"""Regression: sample_data/messy_orders_demo.csv, the owner's demo file, with every suggestion approved."""

import csv
import re
import uuid
from pathlib import Path

import openpyxl
import pytest

from engine import pipeline
from engine.models import Decisions

DEMO = Path(__file__).resolve().parents[2] / "sample_data" / "messy_orders_demo.csv"


@pytest.fixture(scope="module")
def cleaned(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    prof = pipeline.profile(DEMO)
    plan = pipeline.build_plan(prof, Decisions(approved=[p.id for p in prof.proposals]))
    pipeline.clean(DEMO, plan, out, str(uuid.uuid4()))
    with open(out / "clean.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return out, rows


def test_keeps_120_rows(cleaned):
    assert len(cleaned[1]) == 120


def test_region_has_four_values(cleaned):
    regions = {r["region"] for r in cleaned[1] if r["region"]}
    assert regions == {"North", "South", "East", "West"}, sorted(regions)


def test_quantity_has_one_format(cleaned):
    values = [r["quantity"] for r in cleaned[1] if r["quantity"]]
    assert values and all(re.fullmatch(r"[1-9]\d*", v) for v in values), sorted(set(values))


def test_amount_has_two_decimals_everywhere(cleaned):
    values = [r["amount"] for r in cleaned[1] if r["amount"]]
    numbers = [v for v in values if re.fullmatch(r"-?\d+(\.\d+)?", v)]
    assert numbers and all(re.fullmatch(r"-?\d+\.\d{2}", v) for v in numbers), sorted(set(numbers))[:5]


def test_amount_shows_two_decimals_in_excel(cleaned):
    ws = openpyxl.load_workbook(pipeline.build_xlsx(cleaned[0]))["clean"]
    header = [c.value for c in ws[1]]
    col = header.index("amount") + 1
    formats = {ws.cell(row=r, column=col).number_format for r in range(2, ws.max_row + 1)
               if isinstance(ws.cell(row=r, column=col).value, float)}
    assert formats == {"0.00"}
