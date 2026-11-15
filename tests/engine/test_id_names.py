"""Id-like column names (M6 Part B): license, permit, number-style names are ids.

Being id-like only keeps leading-zero text and skips outlier flags. It must never block
date parsing, boolean standardization or category standardization.
"""

import csv
import uuid
from pathlib import Path

import pytest

from engine import parsing as P
from engine import pipeline
from engine.models import Decisions

SAMPLES = Path(__file__).parents[2] / "sample_data"


# --------------------------------------------------------------------------- helper

@pytest.mark.parametrize("name", [
    "License #", "LICENSE_NO", "Permit-Number", "licenseNo", "license_", "Licence", "lic_nbr",
    "Inspection ID", "cust_no", "Order Num", "ref", "API Key", "customerId", "ZIP Code",
    "zipcode", "postcode", "ssn", "sku", "Phone", "account", "Postal Code", "Inspection Date",
])
def test_id_like_names_match_whole_tokens(name):
    assert P.is_id_like_name(name)


@pytest.mark.parametrize("name", [
    "notes", "Notes", "Monkey", "reference_text", "keyboard", "nobody", "numeric_score",
    "amount", "paid", "licensed_driver", "Permits", "Codes", "zipper", "Quantity",
])
def test_id_like_names_do_not_match_inside_words(name):
    assert not P.is_id_like_name(name)


# --------------------------------------------------------------------------- profile and pipeline

N = 30


def _write(tmp_path: Path, columns: dict[str, list[str]]) -> Path:
    path = tmp_path / "t.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(list(columns))
        w.writerows(zip(*columns.values()))
    return path


def _with_outlier(base: int) -> list[str]:
    return [str(base + i) for i in range(N - 1)] + [str(base * 1000)]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("idnames")
    columns = {
        # mixed license values: short and long numbers, one huge, one non-numeric
        "License #": [str(x) for x in [1, 25, 2523422, 3000000, 99999999] * 5]
        + ["12", "7", "40", "2100000", "pending"],
        "cust_no": ["007", "12", "0450"] * 10,
        "Inspection Date": ["2024-01-05", "Jan 6 2024", "2024-01-07"] * 10,
        "Account Active": ["Yes", "no", "Y", "N", "yes", "No"] * 5,
        "Code Region": ["North", "South", "north", "South", "North", "NORTH"] * 5,
        "Notes": _with_outlier(10),
        "Monkey": _with_outlier(20),
        "Amount": _with_outlier(100),
        "Quantity": ["1", "2", "3", "03", "4", "5"] * 5,
    }
    path = _write(tmp, columns)
    profile = pipeline.profile(path)
    plan = pipeline.build_plan(profile, Decisions(approved=[p.id for p in profile.proposals]))
    out = tmp / "out"
    out.mkdir()
    pipeline.clean(path, plan, out, str(uuid.uuid4()))
    with open(out / "clean.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return profile, rows


def _types(profile):
    return {c.name: c.inferred_type for c in profile.columns}


def _rules_for(profile, column):
    return {p.rule_id for p in profile.proposals if p.column == column}


def test_license_column_is_an_id_and_never_flagged(run):
    profile, rows = run
    assert _types(profile)["license"] == "id"
    assert "flag_outliers" not in _rules_for(profile, "license")
    assert "license_outlier_flag" not in rows[0]


def test_cust_no_keeps_leading_zeros_as_text(run):
    profile, rows = run
    assert _types(profile)["cust_no"] == "id"
    assert "coerce_numeric" not in _rules_for(profile, "cust_no")
    assert [r["cust_no"] for r in rows[:3]] == ["007", "12", "0450"]


def test_id_like_name_does_not_block_dates_booleans_or_categories(run):
    profile, rows = run
    types = _types(profile)
    assert types["inspection_date"] == "date"
    assert "parse_dates" in _rules_for(profile, "inspection_date")
    assert rows[1]["inspection_date"] == "2024-01-06"
    assert types["account_active"] == "boolean"
    assert "standardize_booleans" in _rules_for(profile, "account_active")
    assert {r["account_active"] for r in rows} == {"true", "false"}
    assert types["code_region"] == "category"
    assert "standardize_categories" in _rules_for(profile, "code_region")
    assert {r["code_region"] for r in rows} == {"North", "South"}


def test_notes_and_monkey_are_not_ids(run):
    profile, _ = run
    types = _types(profile)
    assert types["notes"] == "integer"
    assert types["monkey"] == "integer"
    assert "flag_outliers" in _rules_for(profile, "notes")
    assert "flag_outliers" in _rules_for(profile, "monkey")


def test_genuine_numeric_column_still_flagged(run):
    profile, rows = run
    assert "flag_outliers" in _rules_for(profile, "amount")
    assert rows[-1]["amount_outlier_flag"] == "true"


def test_quantity_leading_zero_still_coerced(run):
    profile, rows = run
    assert _types(profile)["quantity"] == "integer"
    assert rows[3]["quantity"] == "3"


@pytest.mark.slow
def test_chicago_license_column_not_flagged():
    profile = pipeline.profile(SAMPLES / "chicago_food_inspections.csv")
    license_col = next(c for c in profile.columns if c.source_name == "license_")
    assert license_col.inferred_type == "id"
    assert not [p for p in profile.proposals
                if p.rule_id == "flag_outliers" and p.column == license_col.name]
