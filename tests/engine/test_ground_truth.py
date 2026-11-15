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


def test_parentheses_negative_expects_a_negative_number(ground_truth):
    """CONTRACT 2.3: "(123)" means -123, so the expected clean value is negative."""
    entries = [r for r in ground_truth if r["error_type"] == "parentheses_negative"]
    assert entries
    bad = [r for r in entries if r["original_value"] != "-" + r["injected_value"].strip("()")]
    assert not bad, f"{len(bad)} entries expect the wrong sign, first: {bad[:1]}"


def _data_rows(out_dir: Path, file_name: str) -> list[tuple]:
    path = out_dir / file_name
    if file_name.endswith(".xlsx"):
        ws = openpyxl.load_workbook(path)["Customers"]
        return [tuple(c.value for c in row) for row in ws.iter_rows(min_row=4)]
    encoding, delimiter = ("cp1252", ";") if file_name.startswith("sales") else ("utf-8-sig", ",")
    with open(path, encoding=encoding, newline="") as fh:
        return [tuple(r) for r in list(csv.reader(fh, delimiter=delimiter))[1:]]


@pytest.mark.parametrize("file_name", FILES)
def test_duplicate_row_labels_the_later_copy(out_dir, ground_truth, file_name):
    """remove_exact_duplicate_rows keeps the first occurrence, so the key must label the later ones:
    every labelled row has an identical row above it, and every row with an identical row above
    it (other than empty rows) is labelled."""
    rows = _data_rows(out_dir, file_name)
    labelled = {int(r["row"]) for r in ground_truth
                if r["file"] == file_name and r["error_type"] == "duplicate_row"}
    seen: set[tuple] = set()
    expected = set()
    for n, row in enumerate(rows, 1):
        if all(v in (None, "") for v in row):
            continue
        if row in seen:
            expected.add(n)
        seen.add(row)
    assert labelled == expected, (f"labelled but first copy: {sorted(labelled - expected)}; "
                                  f"later copy not labelled: {sorted(expected - labelled)}")


# ---- held-out batch (M6 step 8): different seed, plus a file with other region abbreviations

@pytest.fixture(scope="module")
def heldout(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("make_samples", SAMPLE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path_factory.mktemp("heldout")
    module.generate_heldout(target)
    with open(target / "ground_truth.csv", encoding="utf-8", newline="") as fh:
        return target, list(csv.DictReader(fh)), module


def test_heldout_batch_has_four_files_and_differs_from_the_tuning_batch(heldout, out_dir):
    target, gt, module = heldout
    assert {r["file"] for r in gt} == set(FILES) | {"store_visits_messy.csv"}
    assert (target / "sales_orders_messy.csv").read_bytes() != (out_dir / "sales_orders_messy.csv").read_bytes()
    assert module.HELDOUT_SEED != module.SEED


def test_heldout_store_file_uses_other_region_abbreviations(heldout):
    target, gt, _ = heldout
    with open(target / "store_visits_messy.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    regions = {r["Region"] for r in rows}
    assert {"NE", "SW", "Ctr"} <= regions and not {"Nrth", "Wset", "Sout"} & regions
    stores = [r for r in gt if r["file"] == "store_visits_messy.csv"]
    assert {"category_abbreviation", "leading_zero"} <= {r["error_type"] for r in stores}
    for r in stores:                                           # every entry points at the injected value
        if int(r["row"]) > 0 and r["column"]:
            assert rows[int(r["row"]) - 1][r["column"]] == r["injected_value"], r


def test_committed_heldout_files_match_the_generator(heldout):
    target, _, _ = heldout
    committed = ROOT / "sample_data" / "heldout"
    for name in ["sales_orders_messy.csv", "hr_survey_messy.csv", "store_visits_messy.csv", "ground_truth.csv"]:
        assert (committed / name).read_bytes() == (target / name).read_bytes(), name
