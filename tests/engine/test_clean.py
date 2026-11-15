import csv
import hashlib
import re
import uuid
from pathlib import Path

import openpyxl
import polars as pl
import pytest
import yaml

from engine import pipeline, recipe
from engine.changelog import COLUMNS
from engine.errors import PlanError
from engine.models import Decisions, EditedProposal

SAMPLES = Path(__file__).parents[2] / "sample_data"
SALES = SAMPLES / "sales_orders_messy.csv"
CUSTOMERS = SAMPLES / "customers_messy.xlsx"
HR = SAMPLES / "hr_survey_messy.csv"
FILES = ["clean.csv", "clean.xlsx", "report.html", "recipe.yaml", "changelog.csv"]


def _prop(profile, rule_id, column=None, tier=None):
    return next(p for p in profile.proposals if p.rule_id == rule_id and p.column == column
                and (tier is None or p.params.get("tier") == tier))


def _changelog(out_dir):
    with open(out_dir / "changelog.csv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def hr_profile():
    return pipeline.profile(HR)


@pytest.fixture(scope="module")
def sales_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("sales")
    profile = pipeline.profile(SALES)
    plan = pipeline.build_plan(profile, Decisions(approved=[p.id for p in profile.proposals]))
    run_id = str(uuid.uuid4())
    steps = []
    result = pipeline.clean(SALES, plan, out, run_id, progress=lambda pct, s: steps.append((pct, s)))
    return profile, plan, result, out, run_id, steps


# --------------------------------------------------------------------------- proposals

def test_proposals_follow_rule_order_and_modes(hr_profile):
    from engine.rules.registry import ORDER

    order = [ORDER[p.rule_id] for p in hr_profile.proposals]
    assert order == sorted(order)
    assert _prop(hr_profile, "parse_dates", "start_date").mode == "suggest"          # ambiguous
    assert _prop(hr_profile, "standardize_categories", "department", tier=1).mode == "auto"     # case only
    assert _prop(hr_profile, "standardize_categories", "department", tier=2).mode == "suggest"  # typos
    assert _prop(hr_profile, "flag_outliers", "salary").mode == "flag"
    assert _prop(hr_profile, "coerce_numeric", "salary").mode == "auto"
    assert _prop(hr_profile, "remove_exact_duplicate_rows").rows_affected == 6
    for p in hr_profile.proposals:
        assert p.rows_affected > 0 and 1 <= len(p.samples) <= 5
        assert p.id.startswith("sug_") and p.title and p.description
        assert p.confidence is None or p.confidence >= 0.80


def test_low_confidence_numeric_is_a_suggestion():
    profile = pipeline.profile(CUSTOMERS)
    p = _prop(profile, "coerce_numeric", "lifetime_value")
    assert 0.80 <= p.confidence < 0.98 and p.mode == "suggest"


def test_proposal_ids_are_stable_across_profiles(hr_profile):
    assert [p.id for p in pipeline.profile(HR).proposals] == [p.id for p in hr_profile.proposals]
    assert len({p.id for p in hr_profile.proposals}) == len(hr_profile.proposals)


def test_proposals_list_values_left_alone_with_a_reason():
    profile = pipeline.profile(SALES)
    amount = _prop(profile, "coerce_numeric", "amount_usd")
    left = {x.value: x for x in amount.left_alone}
    assert {"abc", "12..5"} <= set(left)
    assert left["abc"].count > 0 and "not a number" in left["abc"].reason.lower()
    dates = _prop(profile, "parse_dates", "order_date")
    assert {"soon", "31/02/2024"} <= {x.value for x in dates.left_alone}


def test_name_casing_proposal_describes_itself_not_the_trim_rule():
    profile = pipeline.profile(SALES)
    names = next(p for p in profile.proposals if p.params.get("name_case"))
    assert names.mode == "suggest" and names.title.startswith("Give names normal capital letters")
    assert "words stay the same" not in names.description and "John O'Brien" in names.description


def test_no_coerce_proposal_for_id_columns():
    profile = pipeline.profile(SALES)
    assert not [p for p in profile.proposals if p.rule_id == "coerce_numeric" and p.column == "zip_code"]


# --------------------------------------------------------------------------- build_plan

def test_plan_defaults_run_auto_and_flag_but_not_suggestions(hr_profile):
    plan = pipeline.build_plan(hr_profile, Decisions())
    ids = {s.proposal_id for s in plan.steps}
    for p in hr_profile.proposals:
        assert (p.id in ids) == (p.mode in ("auto", "flag"))
    assert all(s.action == "auto" for s in plan.steps)


def test_plan_approve_reject_and_edit(hr_profile):
    dates = _prop(hr_profile, "parse_dates", "start_date")
    cats = _prop(hr_profile, "standardize_categories", "department", tier=2)
    trim = _prop(hr_profile, "trim_and_normalize_text", "manager")
    plan = pipeline.build_plan(
        hr_profile,
        Decisions(approved=[cats.id], rejected=[trim.id],
                  edited=[EditedProposal(id=dates.id, params={"dayfirst": True})]),
    )
    by_id = {s.proposal_id: s for s in plan.steps}
    assert trim.id not in by_id
    assert by_id[cats.id].action == "approved"
    assert by_id[dates.id].action == "approved" and by_id[dates.id].params["dayfirst"] is True


def test_plan_rejects_bad_decisions(hr_profile):
    some = hr_profile.proposals[0].id
    dates = _prop(hr_profile, "parse_dates", "start_date")
    with pytest.raises(PlanError):
        pipeline.build_plan(hr_profile, Decisions(approved=["sug_doesnotexist"]))
    with pytest.raises(PlanError):
        pipeline.build_plan(hr_profile, Decisions(approved=[some], rejected=[some]))
    with pytest.raises(PlanError):
        pipeline.build_plan(hr_profile, Decisions(edited=[EditedProposal(id=dates.id, params={"formats": []})]))


# --------------------------------------------------------------------------- clean

def test_clean_writes_all_files_and_leaves_the_original_alone(tmp_path):
    before = hashlib.sha256(SALES.read_bytes()).hexdigest()
    profile = pipeline.profile(SALES)
    pipeline.clean(SALES, pipeline.build_plan(profile, Decisions()), tmp_path, "run-1")
    assert hashlib.sha256(SALES.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [f for f in FILES if f != "clean.xlsx"] + ["xlsx_spec.json"])      # Excel is built on download


def test_clean_improves_the_score(sales_run):
    profile, _, result, *_ = sales_run
    assert result.before == profile.quality
    assert result.after.overall > result.before.overall + 10
    assert result.after.consistency == 98.5 and result.after.conformity == 98.8   # unfixable leftovers remain
    s = result.summary
    assert (s.rows_before, s.rows_after, s.rows_removed) == (433, 400, 33)
    assert (s.columns_removed, s.columns_added) == (1, 1)
    assert s.total_changes == sum(r.changes for r in s.by_rule)
    names = {c.name: c for c in result.columns}
    assert names["unnamed"].after is None                       # removed column
    assert names["amount_usd_outlier_flag"].before is None      # added column
    assert result.warnings == []


def test_clean_csv_content(sales_run):
    *_, out, _, _ = sales_run
    df = pl.read_csv(out / "clean.csv", infer_schema_length=0)
    assert "_row_id" not in df.columns
    assert df.columns[:4] == ["order_id", "customer_name", "order_date", "amount_usd"]
    assert df.height == 400
    dates = df["order_date"].drop_nulls()
    assert set(dates.filter(~dates.str.contains(r"^\d{4}-\d{2}-\d{2}$")).unique()) <= {"soon", "31/02/2024", "99/99/9999"}
    assert df["amount_usd"].drop_nulls().str.contains(r"^-?\d+(\.\d+)?$|^(abc|12\.\.5|see note|unknown)$").all()   # invalid text is kept, not guessed
    assert set(df["paid"].drop_nulls().unique()) == {"true", "false"}
    assert df["zip_code"].drop_nulls().str.len_chars().min() == 5            # leading zeros kept
    assert df["customer_name"].drop_nulls().str.contains(r"^\S(.*\S)?$").all()
    assert not df["customer_name"].drop_nulls().str.contains("  ").any()


def test_clean_xlsx_has_real_types(sales_run):
    *_, out, _, _ = sales_run
    ws = openpyxl.load_workbook(pipeline.build_xlsx(out), read_only=True)["clean"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    def col(name):   # read-only xlsx rows can be shorter than the header when trailing cells are empty
        i = header.index(name)
        return [r[i] for r in rows[1:] if i < len(r) and r[i] is not None]
    assert all(isinstance(v, (int, float)) or v in {"abc", "12..5", "see note", "unknown"} for v in col("amount_usd"))
    assert all(isinstance(v, bool) for v in col("paid"))
    assert all(hasattr(v, "year") or v in {"soon", "31/02/2024", "99/99/9999"} for v in col("order_date"))   # impossible dates are kept as text
    assert all(isinstance(v, str) and len(v) == 5 for v in col("zip_code"))


def test_changelog_schema_and_stamping(sales_run):
    _, _, result, out, run_id, _ = sales_run
    rows = _changelog(out)
    assert list(rows[0].keys()) == COLUMNS == [
        "run_id", "rule_id", "rule_version", "row_id", "column", "change_type",
        "old_value", "new_value", "action", "timestamp",
    ]
    assert len(rows) == result.summary.total_changes
    assert {r["run_id"] for r in rows} == {run_id}
    assert {r["action"] for r in rows} == {"auto", "approved"}
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", r["timestamp"]) for r in rows)
    approved = {r["rule_id"] for r in rows if r["action"] == "approved"}
    assert approved == {"standardize_categories", "coerce_numeric", "parse_dates", "trim_and_normalize_text"}
    assert {r["change_type"] for r in rows} == {
        "cell", "row_removed", "column_removed", "header_renamed", "column_added",
    }


def test_changelog_replays_to_the_clean_file(sales_run):
    """Every cell in clean.csv that differs from the original has a change log entry."""
    *_, out, _, _ = sales_run
    from engine.ingest import ingest

    original = ingest(SALES).df
    renamed = {r["old_value"]: r["new_value"] for r in _changelog(out) if r["change_type"] == "header_renamed"}
    original = original.rename(renamed)
    logged = {(int(r["row_id"]), r["column"]) for r in _changelog(out) if r["change_type"] == "cell"}
    clean = pl.read_csv(out / "clean.csv", infer_schema_length=0)
    removed = {int(r["row_id"]) for r in _changelog(out) if r["change_type"] == "row_removed"}
    kept = original.filter(~pl.col("_row_id").is_in(list(removed)))
    assert kept.height == clean.height
    for column in ("customer_name", "order_date", "amount_usd", "region", "paid"):
        for row_id, old, new in zip(kept["_row_id"], kept[column], clean[column]):
            if old != new:
                assert (row_id, column) in logged


def test_rejected_fix_is_not_applied(tmp_path, hr_profile):
    bools = _prop(hr_profile, "standardize_booleans", "remote")
    plan = pipeline.build_plan(hr_profile, Decisions(rejected=[bools.id]))
    pipeline.clean(HR, plan, tmp_path, "run-2")
    df = pl.read_csv(tmp_path / "clean.csv", infer_schema_length=0)
    assert set(df["remote"].unique()) <= {"Y", "N", "y", "n"}
    assert df["start_date"][0].count("/") == 2                 # ambiguous dates left alone by default
    assert "standardize_booleans" not in {r["rule_id"] for r in _changelog(tmp_path)}


def test_edited_dayfirst_changes_the_output(tmp_path, hr_profile):
    dates = _prop(hr_profile, "parse_dates", "start_date")
    raw = pl.read_csv(HR, infer_schema_length=0, encoding="utf8")["Start Date"][0]
    day, month, year = raw.split("/")
    plan = pipeline.build_plan(hr_profile, Decisions(edited=[EditedProposal(id=dates.id, params={"dayfirst": True})]))
    pipeline.clean(HR, plan, tmp_path, "run-3")
    assert pl.read_csv(tmp_path / "clean.csv", infer_schema_length=0)["start_date"][0] == f"{year}-{month}-{day}"


def test_rejecting_header_normalisation_still_cleans_columns(tmp_path, hr_profile):
    headers = _prop(hr_profile, "normalize_headers")
    plan = pipeline.build_plan(hr_profile, Decisions(rejected=[headers.id]))
    result = pipeline.clean(HR, plan, tmp_path, "run-4")
    df = pl.read_csv(tmp_path / "clean.csv", infer_schema_length=0)
    assert "Remote" in df.columns and set(df["Remote"].unique()) == {"true", "false"}
    assert result.warnings == []


def test_progress_steps(sales_run):
    *_, steps = sales_run
    assert steps[0] == (3, "Reading file") and steps[-1] == (100, "Done")
    assert [p for p, _ in steps] == sorted(p for p, _ in steps)
    assert any(s.startswith("Applying ") for _, s in steps)
    assert "Applying Convert dates to ISO 8601" in [s for _, s in steps]      # label as written
    assert ("Scoring results" in [s for _, s in steps]) and ("Writing files" in [s for _, s in steps])


@pytest.mark.parametrize("path", [SALES, CUSTOMERS, HR], ids=lambda p: p.name)
def test_all_samples_clean_end_to_end(tmp_path, path):
    profile = pipeline.profile(path)
    plan = pipeline.build_plan(profile, Decisions(approved=[p.id for p in profile.proposals]))
    result = pipeline.clean(path, plan, tmp_path, str(uuid.uuid4()))
    floor = {SALES: 92, CUSTOMERS: 95, HR: 95}[path]          # sales: realistic messy file, see test_quality_scores.py
    assert result.after.overall >= floor > result.before.overall
    assert pipeline.profile(tmp_path / "clean.csv").duplicate_row_count == 0


def test_cleaning_a_clean_file_changes_nothing(tmp_path, sales_run):
    *_, out, _, _ = sales_run
    profile = pipeline.profile(out / "clean.csv")
    leftovers = [p for p in profile.proposals if p.mode == "auto"]
    assert leftovers == []


# --------------------------------------------------------------------------- recipe

def test_recipe_yaml_schema(sales_run):
    _, plan, _, out, _, _ = sales_run
    data = yaml.safe_load((out / "recipe.yaml").read_text(encoding="utf-8"))
    assert list(data) == ["recipe_version", "name", "created_at", "engine_version", "source", "steps"]
    assert data["recipe_version"] == "1.0" and data["source"]["filename"] == SALES.name
    assert len(data["steps"]) == len(plan.steps)
    assert set(data["steps"][0]) == {"rule_id", "rule_version", "column", "action", "params"}
    assert data["steps"][0]["rule_id"] == "normalize_headers"


def test_recipe_rerun_gives_the_same_clean_file(tmp_path, sales_run):
    *_, out, _, _ = sales_run
    loaded = recipe.load(out / "recipe.yaml")
    result = recipe.run(loaded, SALES, tmp_path, "rerun-1")
    assert (tmp_path / "clean.csv").read_bytes() == (out / "clean.csv").read_bytes()
    assert result.warnings == []
    assert recipe.load(tmp_path / "recipe.yaml").steps == loaded.steps


def test_recipe_skips_missing_columns_with_a_warning(tmp_path, sales_run):
    *_, out, _, _ = sales_run
    other = tmp_path / "other.csv"
    other.write_text("Order ID;Region\nORD-1; north\nORD-2;North\nORD-2;North\n", encoding="utf-8")
    result = recipe.run(recipe.load(out / "recipe.yaml"), other, tmp_path / "out", "rerun-2")
    assert any("amount_usd" in w for w in result.warnings)
    df = pl.read_csv(tmp_path / "out" / "clean.csv", infer_schema_length=0)
    assert df.columns == ["order_id", "region"] and df["region"].to_list() == ["North", "North"]


def test_recipe_version_mismatch_fails_clearly(tmp_path, sales_run):
    *_, out, _, _ = sales_run
    loaded = recipe.load(out / "recipe.yaml")
    loaded.steps[0].rule_version = "2.0.0"
    with pytest.raises(PlanError, match="version"):
        recipe.run(loaded, SALES, tmp_path, "rerun-3")


def test_invalid_recipe_file(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("steps: [oops", encoding="utf-8")
    with pytest.raises(PlanError):
        recipe.load(bad)


# --------------------------------------------------------------------------- report

def test_report_html(sales_run):
    _, _, result, out, run_id, _ = sales_run
    html = (out / "report.html").read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>") and '<html lang="en">' in html
    assert "<script" not in html and "http://" not in html and "https://" not in html   # self-contained
    for text in ("Cleaning report", SALES.name, run_id, str(result.before.overall), str(result.after.overall),
                 "Completeness", "Conformity", "Remove exact duplicate rows", "approved by you", "amount_usd"):
        assert text in html


def test_report_escapes_cell_values(tmp_path):
    src = tmp_path / "x.csv"
    src.write_text("name,qty\n  <b>Ann</b> ,1\nBo,2\n", encoding="utf-8")
    profile = pipeline.profile(src)
    pipeline.clean(src, pipeline.build_plan(profile, Decisions()), tmp_path / "out", "run-x")
    html = (tmp_path / "out" / "report.html").read_text(encoding="utf-8")
    assert "<b>Ann</b>" not in html and "&lt;b&gt;Ann&lt;/b&gt;" in html
