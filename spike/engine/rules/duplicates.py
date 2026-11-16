"""Rule 8: remove rows that are exact copies of an earlier row (the first one is kept)."""

from __future__ import annotations

import polars as pl

from engine.rules.base import ROW_ID, Candidate, Rule, data_columns, row_json


class RemoveExactDuplicateRows(Rule):
    id = "remove_exact_duplicate_rows"
    scope = "table"
    is_destructive = True
    auto_when_destructive = True     # only removes rows identical to a row that is kept
    default_mode = "auto"
    severity = "high"
    label = "Remove exact duplicate rows"
    explain = "Rows that are identical in every column to an earlier row are removed; the first copy is kept."

    def trigger(self, profile):
        # Always a candidate: earlier fixes (trimming, date formats) can reveal more duplicates.
        return [Candidate()] if profile.row_count > 1 else []

    def apply(self, df, column, params):
        cols = data_columns(df)
        if not cols or df.height < 2:
            return df, []
        ordered = df.sort(ROW_ID)
        first = pl.struct(cols).is_first_distinct()
        removed = ordered.filter(~first)
        if not removed.height:
            return df, []
        records = [
            self.record(row[ROW_ID], None, "row_removed", row_json(row), None)
            for row in removed.iter_rows(named=True)
        ]
        return ordered.filter(first), records
