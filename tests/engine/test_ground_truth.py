"""Checks for sample_data/ground_truth.csv, written by sample_data/make_samples.py.

Generation runs into a pytest tmp dir so the repo's sample files are never overwritten.
"""

import csv
import importlib.util
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_SCRIPT = ROOT / "sample_data" / "make_samples.py"

FILES = ["sales_orders_messy.csv", "customers_messy.xlsx", "hr_survey_messy.csv"]
COLUMNS = ["file", "row", "column", "error_type", "original_value", "injected_value"]
# Row-level errors have no single column, so their column is "".
ROW_LEVEL = {"duplicate_row", "empty_row"}


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory) -> Path:
    spec = importlib.util.spec_from_file_location("make_samples", SAMPLE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path_factory.mktemp("samples")
    module.generate(target)
    return target


@pytest.fixture(scope="module")
def ground_truth(out_dir) -> list[dict]:
    with open(out_dir / "ground_truth.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _csv_table(path: Path, encoding: str, delimiter: str) -> tuple[list[str], int]:
    with open(path, encoding=encoding, newline="") as fh:
        rows = list(csv.reader(fh, delimiter=delimiter))
    return rows[0], len(rows) - 1


def _xlsx_table(path: Path) -> tuple[list[str], int]:
    ws = openpyxl.load_workbook(path)["Customers"]
    header = [c.value for c in ws[3]]
    data_rows = ws.max_row - 3
    return [h if h is not None else "" for h in header], data_rows


@pytest.fixture(scope="module")
def tables(out_dir) -> dict[str, tuple[list[str], int]]:
    return {
        "sales_orders_messy.csv": _csv_table(out_dir / "sales_orders_messy.csv", "cp1252", ";"),
        "customers_messy.xlsx": _xlsx_table(out_dir / "customers_messy.xlsx"),
        "hr_survey_messy.csv": _csv_table(out_dir / "hr_survey_messy.csv", "utf-8-sig", ","),
    }


def test_ground_truth_file_exists(out_dir):
    assert (out_dir / "ground_truth.csv").is_file()


def test_has_six_columns(out_dir):
    with open(out_dir / "ground_truth.csv", encoding="utf-8", newline="") as fh:
        assert next(csv.reader(fh)) == COLUMNS


def test_error_type_never_blank(ground_truth):
    assert ground_truth, "ground truth is empty"
    assert all(r["error_type"].strip() for r in ground_truth)


def test_every_entry_points_at_a_real_row_and_column(ground_truth, tables):
    bad = []
    for r in ground_truth:
        headers, n_rows = tables[r["file"]]
        row = int(r["row"])
        column = r["column"]
        if row == 0:
            ok = column == "" or column in headers
        elif r["error_type"] in ROW_LEVEL:
            ok = 1 <= row <= n_rows and column == ""
        else:
            ok = 1 <= row <= n_rows and column in headers
        if not ok:
            bad.append(f"{r['file']} row={row} column={column!r} type={r['error_type']}")
    assert not bad, f"{len(bad)} bad entries, first: {bad[:3]}"


@pytest.mark.parametrize("file_name", FILES)
def test_each_file_has_injected_errors(ground_truth, file_name):
    assert sum(r["file"] == file_name for r in ground_truth) > 0
