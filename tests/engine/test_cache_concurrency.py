"""Step 12: two profile jobs writing the same cache entry must not fail each other."""

import polars as pl

from engine import cache, pipeline
from engine.ingest import ingest
from tests.engine.test_ingest_cache import SALES


def _loaded_and_before():
    prof = pipeline.profile(SALES)
    return ingest(SALES), prof


def test_two_writers_of_the_same_entry_both_succeed(tmp_path, monkeypatch):
    loaded, before = _loaded_and_before()
    real = pl.DataFrame.write_parquet
    nested = {"done": False}

    def write_while_another_job_stores(self, target, *a, **k):
        real(self, target, *a, **k)
        if not nested["done"]:           # the second job finishes its whole store in between
            nested["done"] = True
            cache.store(tmp_path, SALES, loaded, before)

    monkeypatch.setattr(pl.DataFrame, "write_parquet", write_while_another_job_stores)
    cache.store(tmp_path, SALES, loaded, before)         # must not raise
    assert cache.load(tmp_path, SALES, loaded.source.sheet, loaded.source.header_row, None) is not None
    assert not list(tmp_path.glob("*.tmp"))


def test_a_cache_write_error_does_not_fail_the_profile(tmp_path, monkeypatch):
    def boom(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", boom)
    prof = pipeline.profile(SALES, cache_dir=tmp_path)
    assert prof.proposals


def test_a_miss_then_store_hashes_the_file_once(tmp_path):
    cache._content_hash.cache_clear()
    pipeline.profile(SALES, sheet=None, header_row=0, cache_dir=tmp_path / "c")
    assert cache._content_hash.cache_info().misses == 1
