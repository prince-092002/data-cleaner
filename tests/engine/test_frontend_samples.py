"""The website bundles copies of the sample files; they must match sample_data/ exactly."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NAMES = ["sales_orders_messy.csv", "hr_survey_messy.csv"]


@pytest.mark.parametrize("name", NAMES)
def test_frontend_sample_copy_is_current(name):
    assert (ROOT / "sample_data" / name).read_bytes() == (ROOT / "frontend" / "public" / "samples" / name).read_bytes(), (
        f"frontend/public/samples/{name} is stale: copy it from sample_data/"
    )


def test_frontend_customers_copy_has_same_cells():
    import openpyxl

    def cells(path):
        wb = openpyxl.load_workbook(path, read_only=True)
        return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb}

    assert cells(ROOT / "sample_data" / "customers_messy.xlsx") == cells(ROOT / "frontend" / "public" / "samples" / "customers_messy.xlsx")
