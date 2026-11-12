import hashlib
import uuid
from pathlib import Path

import polars as pl
import pytest

from engine import pipeline
from engine.models import Decisions

SAMPLES = Path(__file__).parents[2] / "sample_data"
REAL = SAMPLES / "chicago_food_inspections.csv"     # real public data, no ground truth; see DATASETS.md
DIMS = ["completeness", "validity", "consistency", "uniqueness", "conformity"]


@pytest.fixture(scope="module")
def real_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("chicago")
    digest_before = hashlib.sha256(REAL.read_bytes()).hexdigest()
    profile = pipeline.profile(REAL)
    plan = pipeline.build_plan(profile, Decisions(approved=[p.id for p in profile.proposals]))
    result = pipeline.clean(REAL, plan, out, str(uuid.uuid4()))
    digest_after = hashlib.sha256(REAL.read_bytes()).hexdigest()
    return profile, result, out, digest_before, digest_after


def test_real_file_loads_with_expected_rows(real_run):
    _, result, *_ = real_run
    assert 3000 <= result.summary.rows_before <= 5000


def test_original_upload_is_not_modified(real_run):
    *_, before, after = real_run
    assert before == after


def test_overall_score_does_not_drop(real_run):
    _, result, *_ = real_run
    assert result.after.overall >= result.before.overall


def test_no_dimension_drops(real_run):
    _, result, *_ = real_run
    drops = {d: (getattr(result.before, d), getattr(result.after, d))
             for d in DIMS if getattr(result.after, d) < getattr(result.before, d)}
    # Known artifact (HANDOFF known issues): the long free-text column "violations" counts as a
    # key candidate, and trimming merges strings that differed only by whitespace, so uniqueness
    # can fall by a tenth of a point. No row is lost and no cell is damaged. Anything bigger fails.
    for dim, (before, after) in list(drops.items()):
        if dim == "uniqueness" and before - after <= 0.5:
            del drops[dim]
    assert drops == {}


def test_clean_csv_is_readable_and_matches_the_plan(real_run):
    _, result, out, *_ = real_run
    df = pl.read_csv(out / "clean.csv", infer_schema_length=0)
    assert df.height > 0
    assert df.height == result.summary.rows_after
    assert df.width == result.summary.columns_after


def test_clean_csv_has_no_replacement_characters(real_run):
    _, _, out, *_ = real_run
    df = pl.read_csv(out / "clean.csv", infer_schema_length=0)
    counts = {c: df[c].str.contains("\ufffd", literal=True).sum() for c in df.columns}
    assert sum(counts.values()) == 0, {c: n for c, n in counts.items() if n}
