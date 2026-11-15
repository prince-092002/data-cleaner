"""M6 step 7: change records are streamed to changelog.csv step by step instead of held in memory."""

from engine.changelog import ChangeLogWriter, ChangeRecord, stamp, write_csv


def _records(rule: str, n: int, start: int = 1) -> list[ChangeRecord]:
    tricky = ['a,b', 'say "hi"', "line\nbreak", " spaced ", None, "", "Café", "x\r\ny"]
    out = []
    for i in range(n):
        out.append(ChangeRecord(None, rule, "1.0.0", start + i, "col", "cell",
                                tricky[i % len(tricky)], tricky[(i + 3) % len(tricky)], None, None))
    out.append(ChangeRecord(None, rule, "1.0.0", None, "new_col", "column_added", None, None, None, None))
    return out


def test_streamed_file_is_byte_identical_to_the_old_writer(tmp_path):
    steps = [(_records("trim_and_normalize_text", 20), "auto"), (_records("standardize_categories", 9, 100), "approved")]
    everything = []
    with ChangeLogWriter(tmp_path / "streamed.csv") as log:
        for records, action in steps:
            stamp(records, "run-1", action, "2026-11-15T10:00:00Z")
            log.add(records)
            everything += records
    write_csv(everything, tmp_path / "old.csv")
    assert (tmp_path / "streamed.csv").read_bytes() == (tmp_path / "old.csv").read_bytes()


def test_writer_keeps_counts_and_a_small_sample_only(tmp_path):
    with ChangeLogWriter(tmp_path / "c.csv", sample_size=5) as log:
        for rule, action, n in [("trim_and_normalize_text", "auto", 20), ("standardize_categories", "approved", 9)]:
            records = _records(rule, n)
            stamp(records, "r", action)
            log.add(records)
    assert log.total == 31
    assert log.counts["cell"] == 29 and log.counts["column_added"] == 2
    assert [r.rule_id for r in log.sample] == ["trim_and_normalize_text"] * 5
    by_rule = {(s.rule_id, s.action): (s.changes, s.columns) for s in log.by_rule()}
    assert by_rule == {("trim_and_normalize_text", "auto"): (21, ["col", "new_col"]),
                       ("standardize_categories", "approved"): (10, ["col", "new_col"])}


def test_empty_log_still_has_a_header(tmp_path):
    with ChangeLogWriter(tmp_path / "c.csv") as log:
        pass
    assert (tmp_path / "c.csv").read_text(encoding="utf-8").startswith("run_id,rule_id,")
    assert log.total == 0
