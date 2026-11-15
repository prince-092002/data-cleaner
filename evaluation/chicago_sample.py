"""Draw a fixed random sample of 100 changes from cleaning the Chicago Food Inspections file
(every proposal approved), for the hand check recorded in CHICAGO_HANDCHECK.md.

    .venv/Scripts/python evaluation/chicago_sample.py            # prints the sample as TSV
"""

from __future__ import annotations

import csv
import random
import sys
import tempfile
import uuid
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import pipeline  # noqa: E402
from engine.models import Decisions  # noqa: E402

SRC = ROOT / "sample_data" / "chicago_food_inspections.csv"
SEED = 8
N = 100


def sample() -> tuple[list[dict], Counter, int]:
    prof = pipeline.profile(SRC)
    plan = pipeline.build_plan(prof, Decisions(approved=[p.id for p in prof.proposals]))
    with tempfile.TemporaryDirectory() as tmp:
        pipeline.clean(SRC, plan, Path(tmp), str(uuid.uuid4()))
        with open(Path(tmp) / "changelog.csv", encoding="utf-8", newline="") as fh:
            log = list(csv.DictReader(fh))
    by_rule = Counter(r["rule_id"] for r in log)
    picked = sorted(random.Random(SEED).sample(range(len(log)), N))
    return [log[i] for i in picked], by_rule, len(log)


if __name__ == "__main__":
    rows, by_rule, total = sample()
    print(f"# {total} changes in all; by rule: {dict(by_rule)}")
    for i, r in enumerate(rows, 1):
        old = (r["old_value"] or "").replace("\n", "\n")
        new = (r["new_value"] or "").replace("\n", "\n")
        if len(old) > 70:                      # long free text: show where the two differ
            k = next((j for j, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
            old, new = f"...{old[max(0, k - 25):k + 25]}... (len {len(old)})", f"...{new[max(0, k - 25):k + 25]}... (len {len(new)})"
        print(f"{i}\t{r['rule_id']}\t{r['change_type']}\trow {r['row_id']}\t{r['column']}\t[{old}]\t->\t[{new}]")
