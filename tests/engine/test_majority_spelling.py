"""M6b: a clear-majority spelling wins (whole pipeline, default decisions)."""

import csv
import uuid

from engine import pipeline, recipe
from engine.models import Decisions


def _write(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _clean(tmp_path, src, decisions=None):
    prof = pipeline.profile(src)
    plan = pipeline.build_plan(prof, decisions or Decisions())
    out = tmp_path / "out"
    out.mkdir()
    pipeline.clean(src, plan, out, str(uuid.uuid4()))
    with open(out / "changelog.csv", encoding="utf-8", newline="") as fh:
        return prof, list(csv.DictReader(fh))


def test_chicago_majority_changes_only_the_20_minority_cells(tmp_path):
    cities = ["CHICAGO"] * 4953 + ["Chicago"] * 20
    src = _write(tmp_path / "c.csv", ["id", "city"], [[i, c] for i, c in enumerate(cities, 1)])
    _, rows = _clean(tmp_path, src)
    city = [r for r in rows if r["column"] == "city" and r["change_type"] == "cell"]
    assert len(city) == 20
    assert {(r["old_value"], r["new_value"], r["action"], r["reason"]) for r in city} == {
        ("Chicago", "CHICAGO", "auto", "majority spelling")
    }


def test_no_majority_is_a_suggestion_and_does_not_run_by_default(tmp_path):
    regions = ["WEST"] * 60 + ["West"] * 40 + ["North"] * 100
    src = _write(tmp_path / "r.csv", ["id", "region"], [[i, r] for i, r in enumerate(regions, 1)])
    prof, rows = _clean(tmp_path, src)
    cats = [p for p in prof.proposals if p.rule_id == "standardize_categories"]
    assert [p.params.get("tier") for p in cats] == [None]          # no Tier 1 proposal at all
    assert cats[0].params["case_suggestion"] is True and cats[0].mode == "suggest"
    assert cats[0].params["mapping"] == {"WEST": "West"}
    assert not [r for r in rows if r["column"] == "region"]


def test_approved_title_case_suggestion_logs_its_reason(tmp_path):
    regions = ["WEST"] * 60 + ["West"] * 40 + ["North"] * 100
    src = _write(tmp_path / "r.csv", ["id", "region"], [[i, r] for i, r in enumerate(regions, 1)])
    prof = pipeline.profile(src)
    _, rows = _clean(tmp_path, src, Decisions(approved=[p.id for p in prof.proposals]))
    region = [r for r in rows if r["column"] == "region"]
    assert len(region) == 60
    assert {(r["action"], r["reason"]) for r in region} == {("approved", "Title Case spelling, no clear majority")}


def test_reason_is_empty_for_other_rules(tmp_path):
    src = _write(tmp_path / "t.csv", ["id", "name"], [[i, f" a{i} "] for i in range(1, 30)])
    _, rows = _clean(tmp_path, src)
    assert rows and all(r["reason"] == "" for r in rows)


def test_report_and_recipe_are_written_when_changes_carry_a_reason(tmp_path):
    """The 11th changelog column must not break the other outputs of the same run."""
    cities = ["CHICAGO"] * 95 + ["Chicago"] * 5
    src = _write(tmp_path / "c.csv", ["id", "city"], [[i, c] for i, c in enumerate(cities, 1)])
    _, rows = _clean(tmp_path, src)
    out = tmp_path / "out"
    with open(out / "changelog.csv", encoding="utf-8", newline="") as fh:
        assert {len(r) for r in csv.reader(fh)} == {11}
    assert {r["reason"] for r in rows if r["rule_id"] == "standardize_categories"} == {"majority spelling"}
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "Chicago" in html and "CHICAGO" in html
    saved = recipe.load(out / "recipe.yaml")
    step = next(s for s in saved.steps if s.rule_id == "standardize_categories")
    assert step.params["mapping"] == {"Chicago": "CHICAGO"}
    assert "majority spelling" not in (out / "recipe.yaml").read_text(encoding="utf-8")
