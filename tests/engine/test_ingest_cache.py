"""M6 step 7: the file is parsed once; profile caches it (all text, Parquet) and clean reuses it."""

import csv
import hashlib
import uuid
from pathlib import Path

import pytest

from engine import ingest as _ingest
from engine import pipeline
from engine import profile as _profile
from engine.models import Decisions

SALES = Path(__file__).resolve().parents[2] / "sample_data" / "sales_orders_messy.csv"
CUSTOMERS = Path(__file__).resolve().parents[2] / "sample_data" / "customers_messy.xlsx"


def _changelog(path: Path) -> list[tuple]:
    with open(path, encoding="utf-8", newline="") as fh:
        return [(r["rule_id"], r["row_id"], r["column"], r["change_type"], r["old_value"], r["new_value"])
                for r in csv.DictReader(fh)]


def _clean(src, plan, out, cache=None):
    return pipeline.clean(src, plan, out, str(uuid.uuid4()), cache_dir=cache)


@pytest.mark.parametrize("src", [SALES, CUSTOMERS], ids=["csv", "xlsx"])
def test_clean_reuses_the_cached_file_and_gives_identical_output(tmp_path, monkeypatch, src):
    before_hash = hashlib.sha256(src.read_bytes()).hexdigest()
    cache = tmp_path / "cache"
    prof = pipeline.profile(src, cache_dir=cache)
    assert sorted(p.suffix for p in cache.iterdir()) == [".json", ".parquet"]
    plan = pipeline.build_plan(prof, Decisions(approved=[p.id for p in prof.proposals]))

    plain = _clean(src, plan, tmp_path / "plain")                     # no cache: reads the file

    calls = {"profile_dataframe": 0}
    real_profile = _profile.profile_dataframe

    def counting(*a, **k):
        calls["profile_dataframe"] += 1
        return real_profile(*a, **k)

    def no_read(*a, **k):
        raise AssertionError("clean re-parsed the file although a cache exists")

    monkeypatch.setattr(_ingest, "ingest", no_read)
    monkeypatch.setattr(_profile, "profile_dataframe", counting)
    cached = _clean(src, plan, tmp_path / "cached", cache)
    assert calls["profile_dataframe"] == 1                             # only the "after" score

    assert cached.before == plain.before and cached.after == plain.after
    assert cached.summary == plain.summary
    assert (tmp_path / "cached" / "clean.csv").read_bytes() == (tmp_path / "plain" / "clean.csv").read_bytes()
    assert _changelog(tmp_path / "cached" / "changelog.csv") == _changelog(tmp_path / "plain" / "changelog.csv")
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before_hash   # original never modified


def test_a_different_header_row_is_not_served_from_the_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    pipeline.profile(SALES, cache_dir=cache)
    reads = []
    real = _ingest.ingest
    monkeypatch.setattr(_ingest, "ingest", lambda *a, **k: reads.append(k.get("header_row")) or real(*a, **k))
    prof = pipeline.profile(SALES, header_row=1, cache_dir=cache)
    assert reads == [1] and prof.source.header_row == 1


def test_display_name_comes_from_the_current_call(tmp_path):
    cache = tmp_path / "cache"
    prof = pipeline.profile(SALES, cache_dir=cache, display_name="first.csv")
    plan = pipeline.build_plan(prof, Decisions())
    result = pipeline.clean(SALES, plan, tmp_path / "out", str(uuid.uuid4()), cache_dir=cache,
                            display_name="second.csv")
    assert "second.csv" in (tmp_path / "out" / "report.html").read_text(encoding="utf-8")
    assert result.summary.rows_before == prof.row_count
