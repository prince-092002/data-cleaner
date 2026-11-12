from pathlib import Path

import polars as pl
import pytest

from engine import pipeline
from engine.models import WEIGHTS, DatasetProfile, SourceInfo
from engine.profile import profile_dataframe

SAMPLES = Path(__file__).parents[2] / "sample_data"
SOURCE = SourceInfo(filename="t.csv", file_type="csv")


def _profile(data: dict[str, list], **kwargs) -> DatasetProfile:
    n = len(next(iter(data.values())))
    df = pl.DataFrame(
        {"_row_id": list(range(1, n + 1)), **data},
        schema={"_row_id": pl.Int64, **{c: pl.Utf8 for c in data}},
    )
    return profile_dataframe(df, SOURCE, **kwargs)


def _col(profile: DatasetProfile, name: str):
    return next(c for c in profile.columns if c.name == name)


def _codes(column) -> set[str]:
    return {i.code for i in column.issues}


# --------------------------------------------------------------------------- type inference

def test_type_inference():
    n = 30
    p = _profile(
        {
            "qty": [str(i) for i in range(n)],
            "price": [f"${i}.50" for i in range(n)],
            "day": [f"2024-01-{i % 28 + 1:02d}" for i in range(n)],
            "stamp": [f"2024-01-{i % 28 + 1:02d} 10:{i:02d}" for i in range(n)],
            "flag": ["yes", "no", "Y"] * 10,
            "zip": [f"0{i:04d}" for i in range(n)],
            "customer_id": [str(1000 + i) for i in range(n)],
            "tier": ["gold", "silver", "bronze"] * 10,
            "note": [f"free text number {i} about things" for i in range(n)],
            "blank": [None] * n,
        }
    )
    types = {c.name: c.inferred_type for c in p.columns}
    assert types == {
        "qty": "integer", "price": "decimal", "day": "date", "stamp": "datetime",
        "flag": "boolean", "zip": "id", "customer_id": "id", "tier": "category",
        "note": "text", "blank": "empty",
    }


def test_zero_one_column_is_boolean_but_small_integers_are_not():
    p = _profile({"a": ["0", "1"] * 10, "b": ["0", "1", "2", "3"] * 5})
    assert _col(p, "a").inferred_type == "boolean"
    assert _col(p, "b").inferred_type == "integer"


def test_below_threshold_falls_back_to_text():
    values = ["1", "2", "3", "x", "y", "z", "w", "v", "u", "t"]
    col = _col(_profile({"mix": values}), "mix")
    assert col.inferred_type in ("text", "category")


# --------------------------------------------------------------------------- stats

def test_column_stats():
    p = _profile({"amount": ["10", "20", "20", "N/A", None, " 30 "]})
    col = _col(p, "amount")
    assert col.row_count == 6
    assert col.null_count == 2 and col.null_pct == 33.3      # real null + null token
    assert col.distinct_count == 3
    assert (col.min, col.max, col.mean, col.median) == ("10", "30", 20.0, 20.0)
    assert col.top_values[0].value == "20" and col.top_values[0].count == 2
    assert "N/A" not in col.samples and len(col.samples) <= 5
    assert col.format_patterns[0].pattern == "99"
    assert {"missing_values", "null_tokens", "whitespace"} <= _codes(col)


def test_dataset_counts_duplicates_and_empty_rows():
    p = _profile({"a": ["1", "1", None, "2", "-"], "b": ["x", "x", None, "y", "N/A"]})
    assert p.row_count == 5 and p.column_count == 2
    assert p.duplicate_row_count == 1
    assert p.empty_row_count == 2


def test_names_come_from_source_headers():
    p = _profile({"Order ID": ["1", "2"], "Total": ["3", "4"]},
                 source_names={"Order ID": "Order ID", "Total": "Total"})
    assert [(c.name, c.source_name) for c in p.columns] == [("order_id", "Order ID"), ("total", "Total")]
    assert "messy_header" in _codes(_col(p, "order_id"))


# --------------------------------------------------------------------------- quality score

def test_perfect_column_scores_100():
    p = _profile({"amount": [str(i) for i in range(1, 21)]})
    q = _col(p, "amount").quality
    assert q.model_dump() == {
        "score": 100.0, "completeness": 100.0, "validity": 100.0, "consistency": 100.0,
        "uniqueness": 100.0, "conformity": 100.0,
    }
    assert p.quality.overall == 100.0


def test_weights_sum_to_one():
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
    assert WEIGHTS == {"completeness": 0.25, "validity": 0.25, "consistency": 0.20,
                       "uniqueness": 0.15, "conformity": 0.15}


def test_completeness_counts_nulls_and_null_tokens():
    q = _col(_profile({"a": ["x1", "x2", None, "TBD"]}), "a").quality
    assert q.completeness == 50.0


def test_validity_is_share_parsing_as_inferred_type():
    values = [str(i) for i in range(9)] + ["oops"]
    col = _col(_profile({"n": values}), "n")
    assert col.inferred_type == "integer" and col.quality.validity == 90.0
    assert "mixed_types" in _codes(col)


def test_consistent_but_not_conforming_dates():
    values = [f"{d:02d}/12/2024" for d in range(13, 29)]
    col = _col(_profile({"d": values}), "d")
    assert col.inferred_type == "date"
    assert col.quality.consistency == 100.0        # all written the same way
    assert col.quality.conformity == 20.0          # header ok (0.2), none in ISO 8601
    assert (col.min, col.max) == ("2024-12-13", "2024-12-28")


def test_mixed_date_formats_lower_consistency():
    values = ["13/12/2024"] * 6 + ["2024-12-14"] * 4
    col = _col(_profile({"d": values}), "d")
    assert col.quality.consistency == 60.0
    assert col.quality.conformity == pytest.approx(20.0 + 80.0 * 0.4)
    assert "mixed_date_formats" in _codes(col)


def test_ambiguous_dates_are_flagged():
    col = _col(_profile({"d": ["03/04/2024", "05/06/2024", "01/02/2024"]}), "d")
    assert "ambiguous_dates" in _codes(col)


def test_uniqueness_for_keys_and_other_columns():
    p = _profile({
        "code_ref": [f"A{i}" for i in range(19)] + ["A0"],
        "kind": ["a", "b"] * 10,
    })
    assert _col(p, "code_ref").is_key_candidate
    assert _col(p, "code_ref").quality.uniqueness == 95.0     # 19 distinct of 20
    assert "duplicate_keys" in _codes(_col(p, "code_ref"))
    assert _col(p, "kind").quality.uniqueness == 100.0        # no duplicate rows


def test_duplicate_rows_lower_uniqueness_of_non_key_columns():
    p = _profile({"kind": ["a", "a", "b", "c"], "v": ["1", "1", "2", "3"]})
    assert _col(p, "kind").quality.uniqueness == 75.0


def test_null_tokens_lower_conformity():
    clean = _col(_profile({"a": ["10", "20", None, None]}), "a").quality.conformity
    tokens = _col(_profile({"a": ["10", "20", "N/A", "-"]}), "a").quality.conformity
    assert clean == 100.0 and tokens == 60.0


def test_empty_column_edge_case():
    q = _col(_profile({"e": [None, None]}), "e").quality
    assert (q.completeness, q.validity, q.consistency, q.uniqueness, q.conformity) == (0, 100, 100, 100, 100)
    assert q.score == 75.0


def test_roll_up_is_weighted_mean_of_column_dimensions():
    p = _profile({"a": ["1", "2", None, "x"], "b": ["Yes", "no", "Y", "N"]})
    for dim in WEIGHTS:
        mean = sum(getattr(c.quality, dim) for c in p.columns) / len(p.columns)
        assert getattr(p.quality, dim) == pytest.approx(mean, abs=0.06)
    overall = sum(WEIGHTS[d] * getattr(p.quality, d) for d in WEIGHTS)
    assert p.quality.overall == pytest.approx(overall, abs=0.06)
    for c in p.columns:
        expected = sum(WEIGHTS[d] * getattr(c.quality, d) for d in WEIGHTS)
        assert c.quality.score == pytest.approx(expected, abs=0.06)


def test_outlier_flag_columns_are_not_scored():
    p = _profile({"a": ["1", "2"], "a_outlier_flag": [None, None]})
    assert p.quality.completeness == 100.0


# --------------------------------------------------------------------------- sample files

def test_sales_sample():
    steps = []
    p = pipeline.profile(SAMPLES / "sales_orders_messy.csv", progress=lambda pct, s: steps.append((pct, s)))
    types = {c.name: c.inferred_type for c in p.columns}
    assert types == {
        "order_id": "text", "customer_name": "text", "order_date": "date",
        "amount_usd": "decimal", "discount": "integer", "region": "category",
        "paid": "boolean", "zip_code": "id", "notes": "category", "unnamed": "empty",
    }
    assert p.row_count == 433 and p.empty_row_count == 8 and p.duplicate_row_count >= 12
    assert {"mixed_date_formats", "null_tokens"} <= _codes(_col(p, "order_date"))
    assert "numeric_as_text" in _codes(_col(p, "amount_usd"))
    assert "inconsistent_categories" in _codes(_col(p, "region"))
    assert "inconsistent_booleans" in _codes(_col(p, "paid"))
    assert 0 < p.quality.overall < 95
    assert p.proposals
    assert steps[0] == (5, "Reading file") and steps[-1] == (100, "Done")
    assert [pct for pct, _ in steps] == sorted(pct for pct, _ in steps)


def test_customers_sample():
    p = pipeline.profile(SAMPLES / "customers_messy.xlsx")
    assert p.source.sheet == "Customers" and p.source.header_row == 2
    types = {c.name: c.inferred_type for c in p.columns}
    assert types["customer_id"] == "id" and types["signup_date"] == "date"
    assert types["lifetime_value"] == "decimal" and types["active"] == "boolean"
    assert types["segment"] == "category"
    assert "hidden_characters" in _codes(_col(p, "full_name"))
    assert "outliers" in _codes(_col(p, "lifetime_value"))
    assert _col(p, "lifetime_value").max == "9750000"


def test_hr_sample():
    p = pipeline.profile(SAMPLES / "hr_survey_messy.csv")
    names = [c.name for c in p.columns]
    assert names[6:9] == ["comments", "comments_2", "column_9"]
    assert "ambiguous_dates" in _codes(_col(p, "start_date"))
    assert "encoding_damage" in _codes(_col(p, "comments"))
    assert "outliers" in _codes(_col(p, "salary"))
    assert _col(p, "comments_2").inferred_type == "empty"


def test_profile_is_json_serialisable_and_matches_contract_fields():
    p = pipeline.profile(SAMPLES / "hr_survey_messy.csv")
    data = p.model_dump(mode="json")
    assert set(data) == {
        "schema_version", "source", "row_count", "column_count", "duplicate_row_count",
        "empty_row_count", "quality", "columns", "proposals",
    }
    assert set(data["columns"][0]) == {
        "name", "source_name", "position", "inferred_type", "type_confidence", "row_count",
        "null_count", "null_pct", "distinct_count", "distinct_pct", "is_key_candidate", "min",
        "max", "mean", "median", "min_length", "max_length", "top_values", "samples",
        "format_patterns", "issues", "quality",
    }
    assert DatasetProfile.model_validate(data) == p
