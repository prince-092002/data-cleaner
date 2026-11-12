import json

import polars as pl
import pytest

from engine.models import SourceInfo
from engine.profile import profile_dataframe
from engine.rules.base import Rule, proposal_id, resolve_mode
from engine.rules.registry import RULES, RULES_BY_ID

SOURCE = SourceInfo(filename="t.csv", file_type="csv")


def frame(data: dict[str, list]) -> pl.DataFrame:
    n = len(next(iter(data.values())))
    return pl.DataFrame(
        {"_row_id": list(range(1, n + 1)), **data},
        schema={"_row_id": pl.Int64, **{c: pl.Utf8 for c in data}},
    )


def run(rule_id: str, df: pl.DataFrame, column=None, params=None):
    before = df.clone()
    new_df, records = RULES_BY_ID[rule_id].apply(df, column, params or {})
    assert df.equals(before), "apply must not mutate its input"
    return new_df, records


def triggers(rule_id: str, data: dict[str, list], source_names=None):
    df = frame(data)
    profile = profile_dataframe(df, SOURCE, source_names)
    return RULES_BY_ID[rule_id].trigger(profile)


# --------------------------------------------------------------------------- registry / interface

def test_registry_has_exactly_the_ten_rules_in_order():
    assert [r.id for r in RULES] == [
        "normalize_headers", "drop_empty_rows_and_columns", "trim_and_normalize_text",
        "standardize_null_tokens", "coerce_numeric", "parse_dates", "standardize_booleans",
        "remove_exact_duplicate_rows", "standardize_categories", "flag_outliers",
    ]


def test_every_rule_declares_the_contract_fields():
    for rule in RULES:
        assert isinstance(rule, Rule)
        assert rule.id and rule.version.count(".") == 2 and rule.label and rule.explain
        assert rule.scope in ("column", "table")
        assert rule.default_mode in ("auto", "suggest", "flag")
        assert rule.severity in ("high", "medium", "low")
        assert isinstance(rule.is_destructive, bool)


def test_default_modes_match_the_phase_1_table():
    modes = {r.id: r.default_mode for r in RULES}
    assert modes["standardize_categories"] == "suggest"
    assert modes["flag_outliers"] == "flag"
    assert all(m == "auto" for rid, m in modes.items() if rid not in ("standardize_categories", "flag_outliers"))


@pytest.mark.parametrize(
    "confidence, expected", [(1.0, "auto"), (0.98, "auto"), (0.9799, "suggest"), (0.80, "suggest"), (0.79, None), (None, "auto")]
)
def test_confidence_thresholds(confidence, expected):
    assert resolve_mode(RULES_BY_ID["coerce_numeric"], confidence) == expected


def test_mode_resolution_special_cases():
    assert resolve_mode(RULES_BY_ID["parse_dates"], 1.0, force_suggest=True) == "suggest"
    assert resolve_mode(RULES_BY_ID["standardize_categories"], 1.0) == "suggest"   # never auto
    assert resolve_mode(RULES_BY_ID["flag_outliers"], None) == "flag"
    assert resolve_mode(RULES_BY_ID["remove_exact_duplicate_rows"], None) == "auto"


def test_proposal_id_is_stable_and_param_sensitive():
    a = proposal_id("parse_dates", "d", {"dayfirst": True})
    assert a == proposal_id("parse_dates", "d", {"dayfirst": True})
    assert a != proposal_id("parse_dates", "d", {"dayfirst": False})
    assert a.startswith("sug_") and len(a) == 16


# --------------------------------------------------------------------------- 1 normalize_headers

def test_normalize_headers():
    data = {"Order ID": ["1"], " Total ": ["2"], "ok_name": ["3"]}
    cands = triggers("normalize_headers", data, {c: c for c in data})
    assert cands[0].params == {"mapping": {"Order ID": "order_id", " Total ": "total"}}
    df, records = run("normalize_headers", frame(data), None, cands[0].params)
    assert df.columns == ["_row_id", "order_id", "total", "ok_name"]
    assert [(r.change_type, r.old_value, r.new_value, r.row_id) for r in records] == [
        ("header_renamed", "Order ID", "order_id", None), ("header_renamed", " Total ", "total", None),
    ]


def test_normalize_headers_not_triggered_for_clean_names():
    assert triggers("normalize_headers", {"a": ["1"], "b_c": ["2"]}, {"a": "a", "b_c": "b_c"}) == []


# --------------------------------------------------------------------------- 2 drop_empty

def test_drop_empty_rows_and_columns():
    df = frame({"a": ["1", None, "N/A", "2"], "b": ["x", None, "-", "y"], "c": [None, None, "", None]})
    out, records = run("drop_empty_rows_and_columns", df, None, {"drop_rows": True, "drop_columns": True})
    assert out.columns == ["_row_id", "a", "b"]
    assert out["_row_id"].to_list() == [1, 4]
    kinds = [(r.change_type, r.row_id, r.column) for r in records]
    assert kinds == [("column_removed", None, "c"), ("row_removed", 2, None), ("row_removed", 3, None)]
    assert json.loads(records[2].old_value) == {"a": "N/A", "b": "-"}


def test_drop_empty_can_keep_rows():
    df = frame({"a": ["1", None], "c": [None, None]})
    out, _ = run("drop_empty_rows_and_columns", df, None, {"drop_rows": False, "drop_columns": True})
    assert out.height == 2 and out.columns == ["_row_id", "a"]


# --------------------------------------------------------------------------- 3 trim

def test_trim_and_normalize_text():
    df = frame({"name": ["  Ann  Lee ", "Bo​", "Zo e", "CafÃ©", "fine", None]})
    out, records = run("trim_and_normalize_text", df, "name")
    assert out["name"].to_list() == ["Ann Lee", "Bo", "Zo e", "Café", "fine", None]
    assert [r.row_id for r in records] == [1, 2, 3, 4]
    assert records[0].old_value == "  Ann  Lee " and records[0].new_value == "Ann Lee"


def test_trim_keeps_curly_quotes():
    out, records = run("trim_and_normalize_text", frame({"t": ["don’t stop"]}), "t")
    assert records == [] and out["t"][0] == "don’t stop"


# --------------------------------------------------------------------------- 4 null tokens

def test_standardize_null_tokens():
    values = ["N/A", "na", "-", "?", "#N/A", "TBD", "null", " ", "real", "0", None]
    df = frame({"v": values})
    params = triggers("standardize_null_tokens", {"v": values})[0].params
    out, records = run("standardize_null_tokens", df, "v", params)
    assert out["v"].to_list() == [None] * 8 + ["real", "0", None]
    assert len(records) == 8 and all(r.new_value is None for r in records)


# --------------------------------------------------------------------------- 5 coerce_numeric

def test_coerce_numeric():
    df = frame({"amt": ["$1,234.50", "(123)", "45%", "12", "oops", None]})
    out, records = run("coerce_numeric", df, "amt")
    assert out["amt"].to_list() == ["1234.50", "-123", "45", "12", "oops", None]   # "oops" left alone
    assert [r.row_id for r in records] == [1, 2, 3]


def test_coerce_numeric_never_triggers_on_ids():
    n = 30
    data = {
        "zip": [f"0{i:04d}" for i in range(n)],
        "phone_number": [str(5550000 + i) for i in range(n)],
        "customer_id": [f"{1000 + i:,}" for i in range(n)],
        "amount": [f"${i}.00" for i in range(n)],
    }
    assert [c.column for c in triggers("coerce_numeric", data)] == ["amount"]


def test_coerce_numeric_confidence_is_share_of_numbers():
    data = {"amount": [f"${i}" for i in range(19)] + ["unknown"]}
    cand = triggers("coerce_numeric", data)[0]
    assert cand.confidence == 0.95
    assert resolve_mode(RULES_BY_ID["coerce_numeric"], cand.confidence) == "suggest"


# --------------------------------------------------------------------------- 6 parse_dates

def test_parse_dates_dayfirst_detected_from_data():
    values = ["25/12/2024", "03/04/2024", "2024-01-05", "5 Apr 2024", "not a date", None]
    df = frame({"d": values * 4})
    rule = RULES_BY_ID["parse_dates"]
    cand = triggers("parse_dates", {"d": values * 4})[0]
    assert not cand.force_suggest
    params, _ = rule.prepare(df, "d", cand.params)
    assert params == {"dayfirst": True}
    out, records = run("parse_dates", df, "d", params)
    assert out["d"].to_list()[:6] == ["2024-12-25", "2024-04-03", "2024-01-05", "2024-04-05", "not a date", None]
    assert {r.row_id for r in records} >= {1, 2, 4} and 3 not in {r.row_id for r in records}


def test_parse_dates_ambiguous_is_a_suggestion_and_editable():
    values = ["03/04/2024", "05/06/2024", "01/02/2024"] * 5
    cand = triggers("parse_dates", {"d": values})[0]
    rule = RULES_BY_ID["parse_dates"]
    assert cand.force_suggest
    assert resolve_mode(rule, cand.confidence, cand.force_suggest) == "suggest"
    assert "dayfirst" in rule.editable_params
    month_first, _ = run("parse_dates", frame({"d": values}), "d", {"dayfirst": False})
    day_first, _ = run("parse_dates", frame({"d": values}), "d", {"dayfirst": True})
    assert month_first["d"][0] == "2024-03-04" and day_first["d"][0] == "2024-04-03"


def test_parse_dates_keeps_time():
    out, _ = run("parse_dates", frame({"d": ["3/4/2024 2:30 PM"]}), "d", {"dayfirst": True})
    assert out["d"][0] == "2024-04-03T14:30:00"


# --------------------------------------------------------------------------- 7 booleans

def test_standardize_booleans():
    values = ["Yes", "no", "Y", "N", "TRUE", "false", "1", "0", "on", "OFF", None]
    cand = triggers("standardize_booleans", {"b": values})[0]
    out, records = run("standardize_booleans", frame({"b": values}), "b", cand.params)
    assert out["b"].to_list() == ["true", "false"] * 5 + [None]
    assert len(records) == 9                      # "false" was already standard


def test_booleans_not_triggered_when_other_values_present():
    values = ["yes", "no"] * 9 + ["maybe", "yes"]
    assert triggers("standardize_booleans", {"b": values}) == []


# --------------------------------------------------------------------------- 8 duplicates

def test_remove_exact_duplicate_rows_keeps_first():
    df = frame({"a": ["1", "2", "1", "1", "3"], "b": ["x", "y", "x", "z", None]})
    out, records = run("remove_exact_duplicate_rows", df)
    assert out["_row_id"].to_list() == [1, 2, 4, 5]
    assert [(r.change_type, r.row_id) for r in records] == [("row_removed", 3)]
    assert json.loads(records[0].old_value) == {"a": "1", "b": "x"}


# --------------------------------------------------------------------------- 9 categories

def test_standardize_categories():
    values = ["North"] * 20 + ["north", "NORTH", "Nrth"] + ["South"] * 20 + ["East"] * 10 + ["West"] * 10
    df = frame({"region": values})
    rule = RULES_BY_ID["standardize_categories"]
    cand = triggers("standardize_categories", {"region": values})[0]
    params, confidence = rule.prepare(df, "region", cand.params)
    assert params["mapping"] == {"NORTH": "North", "Nrth": "North", "north": "North"}
    assert 0.80 <= confidence < 0.98
    assert rule.is_destructive and resolve_mode(rule, confidence) == "suggest"
    out, records = run("standardize_categories", df, "region", params)
    assert set(out["region"].to_list()) == {"North", "South", "East", "West"}
    assert len(records) == 3


def test_standardize_categories_accepts_an_edited_mapping():
    df = frame({"c": ["USA", "U.S.A.", "UK"]})
    out, records = run("standardize_categories", df, "c", {"mapping": {"U.S.A.": "USA"}})
    assert out["c"].to_list() == ["USA", "USA", "UK"] and len(records) == 1


# --------------------------------------------------------------------------- 10 outliers

def test_flag_outliers_adds_a_column_and_changes_nothing_else():
    values = [str(v) for v in range(50, 80)] + ["9999", None, "n/a"]
    df = frame({"salary": values, "other": ["x"] * len(values)})
    out, records = run("flag_outliers", df, "salary", {"k": 1.5})
    assert out.columns == ["_row_id", "salary", "salary_outlier_flag", "other"]
    assert out["salary"].to_list() == values and out.height == df.height        # nothing removed or changed
    flags = out["salary_outlier_flag"].to_list()
    assert flags[30] == "true" and flags[0] == "false" and flags[31] is None and flags[32] is None
    assert [(r.change_type, r.row_id, r.new_value) for r in records] == [
        ("column_added", None, None), ("cell", 31, "true"),
    ]


def test_flag_outliers_needs_twenty_values():
    df = frame({"n": [str(v) for v in range(10)] + ["9999"]})
    out, records = run("flag_outliers", df, "n", {"k": 1.5})
    assert records == [] and out.columns == df.columns


# --------------------------------------------------------------------------- all rules

@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_rules_are_deterministic_and_keep_row_ids(rule):
    values = ["  $1,200 ", "N/A", "03/04/2024", "Yes", "yes", None] * 5
    df = frame({"v": values, "w": values})
    column = "v" if rule.scope == "column" else None
    params, _ = rule.prepare(df, column, {})
    first, rec1 = rule.apply(df, column, params)
    second, rec2 = rule.apply(df, column, params)
    assert first.equals(second) and len(rec1) == len(rec2)
    assert first["_row_id"].is_unique().all()
    assert set(first["_row_id"].to_list()) <= set(df["_row_id"].to_list())
    for r in rec1:
        assert r.rule_id == rule.id and r.rule_version == rule.version
        assert r.run_id is None and r.action is None and r.timestamp is None   # stamped by the pipeline
