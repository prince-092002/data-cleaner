"""Change log records. See docs/CONTRACT.md section 5.

Rules create records with the rule and cell fields filled in. The pipeline stamps
run_id, action and timestamp. A plain dataclass is used (not Pydantic) because a
run can produce millions of records.
"""

from __future__ import annotations

import csv
import datetime as _dt
from dataclasses import astuple, dataclass, fields
from pathlib import Path
from typing import Iterable

CHANGE_TYPES = ("cell", "row_removed", "column_removed", "header_renamed", "column_added")


@dataclass(slots=True)
class ChangeRecord:
    run_id: str | None
    rule_id: str
    rule_version: str
    row_id: int | None
    column: str | None
    change_type: str
    old_value: str | None
    new_value: str | None
    action: str | None
    timestamp: str | None
    reason: str | None = None        # short plain reason (category merges); empty for the rest

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


COLUMNS = [f.name for f in fields(ChangeRecord)]


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(records: list[ChangeRecord], run_id: str, action: str, timestamp: str | None = None) -> None:
    """Fill in the fields only the pipeline knows."""
    timestamp = timestamp or utc_now()
    for record in records:
        record.run_id = run_id
        record.action = action
        record.timestamp = timestamp


def write_csv(records: Iterable[ChangeRecord], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for record in records:
            writer.writerow(["" if v is None else v for v in astuple(record)])


class ChangeLogWriter:
    """Streams change records to changelog.csv one rule step at a time.

    A big file can produce millions of records; holding them all was a large part of a run's
    peak memory. The writer keeps only counts, the per-rule summary and a small sample.
    Output is byte-identical to write_csv.
    """

    def __init__(self, path: Path, sample_size: int = 50):
        self.path = Path(path)
        self.sample_size = sample_size
        self.total = 0
        self.counts: dict[str, int] = dict.fromkeys(CHANGE_TYPES, 0)
        self.sample: list[ChangeRecord] = []
        self._by_rule: dict[tuple[str, str], tuple[int, list[str]]] = {}
        self._fh = open(self.path, "w", encoding="utf-8", newline="")
        csv.writer(self._fh).writerow(COLUMNS)

    def __enter__(self) -> "ChangeLogWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def add(self, records: list[ChangeRecord]) -> None:
        if not records:
            return
        for r in records:
            self.counts[r.change_type] += 1
            changes, columns = self._by_rule.get((r.rule_id, r.action), (0, []))
            if r.column and r.column not in columns:
                columns.append(r.column)
            self._by_rule[(r.rule_id, r.action)] = (changes + 1, columns)
        room = self.sample_size - len(self.sample)
        if room > 0:
            self.sample.extend(records[:room])
        self.total += len(records)
        writer = csv.writer(self._fh)
        writer.writerows(["" if v is None else v for v in astuple(r)] for r in records)

    def by_rule(self) -> list:
        from engine.models import RuleSummary

        return [RuleSummary(rule_id=rule_id, action=action, changes=n, columns=list(columns))
                for (rule_id, action), (n, columns) in self._by_rule.items()]
