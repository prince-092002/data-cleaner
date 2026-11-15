import time
import uuid

import polars as pl
import pytest

from engine import pipeline
from engine.models import Decisions
from evaluation.timing import write_messy_sales

ROWS = 100_000


@pytest.mark.slow
def test_100k_rows_profile_and_clean_in_time(tmp_path):
    gen = write_messy_sales(tmp_path / "sales_100k.csv", ROWS)
    start = time.perf_counter()
    profile = pipeline.profile(gen.path, cache_dir=tmp_path / "cache")
    plan = pipeline.build_plan(profile, Decisions(approved=[p.id for p in profile.proposals]))
    out = tmp_path / "out"
    pipeline.clean(gen.path, plan, out, str(uuid.uuid4()), cache_dir=tmp_path / "cache")
    elapsed = time.perf_counter() - start

    assert elapsed < 120, f"profile + clean took {elapsed:.1f} s"
    clean = pl.read_csv(out / "clean.csv", infer_schema_length=0)
    assert clean.height <= gen.clean_rows                     # only copies and empty rows can go
    assert abs(clean.height - ROWS) <= 0.10 * ROWS
    assert clean.columns[:4] == ["order_id", "customer_name", "order_date", "amount_usd"]
