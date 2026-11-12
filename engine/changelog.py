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
