"""Print before/after quality scores for the real Chicago food inspections sample.

Run from the project root:  .venv/Scripts/python sample_data/score_real_dataset.py
Output is kept short. This file has no ground truth, so this is a report, not a precision/recall score.
"""
import csv
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # project root, so `engine` imports

from engine import pipeline
from engine.models import Decisions

REAL = Path(__file__).resolve().parent / "chicago_food_inspections.csv"
DIMS = ["completeness", "validity", "consistency", "uniqueness", "conformity"]


def main() -> None:
    profile = pipeline.profile(REAL)
    plan = pipeline.build_plan(profile, Decisions(approved=[p.id for p in profile.proposals]))
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        result = pipeline.clean(REAL, plan, out, str(uuid.uuid4()))
        with open(out / "changelog.csv", encoding="utf-8", newline="") as fh:
            log = list(csv.DictReader(fh))

    s = result.summary
    print(f"Chicago food inspections: {REAL.name}")
    print(f"Overall: before {result.before.overall:.1f}  after {result.after.overall:.1f}")
    for d in DIMS:
        print(f"  {d:<13} before {getattr(result.before, d):6.1f}  after {getattr(result.after, d):6.1f}")
    print(f"Rows: before {s.rows_before}  after {s.rows_after}  removed {s.rows_removed}")
    print(f"Columns: before {s.columns_before}  after {s.columns_after}")
    print("Changes by rule:")
    for r in s.by_rule:
        nulled = sum(1 for e in log if e["rule_id"] == r.rule_id and e["change_type"] == "cell" and e["new_value"] == "")
        print(f"  {r.rule_id:<32} {r.action:<8} {r.changes:>6}  (set to empty: {nulled})")
    print(f"Total changes: {s.total_changes}  cells changed: {s.cells_changed}")
    print(f"Warnings: {len(result.warnings)}")


if __name__ == "__main__":
    main()
