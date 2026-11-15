"""clean.xlsx is built on demand (pipeline.build_xlsx), not during the clean job."""

import json
import os
from pathlib import Path

import pytest

from engine import pipeline
from tests.engine.xlsx_fingerprint import SAMPLES, clean_sample, fingerprint

OLD = json.loads((Path(__file__).parent / "fixtures" / "xlsx_old_code.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sample", SAMPLES)
def test_excel_built_on_demand_matches_what_the_old_code_wrote(tmp_path, sample):
    out = clean_sample(sample, tmp_path)
    assert not (out / "clean.xlsx").exists()                 # the clean job no longer writes it
    path = pipeline.build_xlsx(out)
    assert path == out / "clean.xlsx"
    assert fingerprint(path) == OLD[sample]


def test_second_build_reuses_the_file(tmp_path):
    out = clean_sample("messy_orders_demo.csv", tmp_path)
    first = pipeline.build_xlsx(out)
    stamp = os.stat(first).st_mtime_ns
    assert os.stat(pipeline.build_xlsx(out)).st_mtime_ns == stamp
    assert [p.name for p in out.iterdir() if p.name.endswith(".tmp")] == []


def test_a_failed_build_leaves_no_half_written_file(tmp_path, monkeypatch):
    out = clean_sample("messy_orders_demo.csv", tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(pipeline, "_write_xlsx", boom)
    with pytest.raises(RuntimeError):
        pipeline.build_xlsx(out)
    assert not (out / "clean.xlsx").exists()
    assert (out / "clean.csv").exists() and (out / "report.html").exists()
