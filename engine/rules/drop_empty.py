"""Rule 2: remove rows and columns where every cell is empty (null or a null token)."""

from __future__ import annotations

import polars as pl

from engine.rules.base import ROW_ID, Candidate, Rule, data_columns, is_blank_expr, row_json


class DropEmptyRowsAndColumns(Rule):
    id = "drop_empty_rows_and_columns"
    scope = "table"
    is_destructive = True
    auto_when_destructive = True     # only removes rows/columns that hold no information
    default_mode = "auto"
    severity = "low"
    label = "Remove empty rows and columns"
    explain = "Rows and columns with no values at all are removed."

    def trigger(self, profile):
        if profile.empty_row_count or any(c.inferred_type == "empty" for c in profile.columns):
            return [Candidate(params={"drop_rows": True, "drop_columns": True})]
        return []

    def apply(self, df, column, params):
        records = []
        cols = data_columns(df)
        if params.get("drop_columns", True) and cols and df.height:
            blank = df.select([is_blank_expr(c).all().alias(c) for c in cols]).row(0)
            empty_cols = [c for c, is_empty in zip(cols, blank) if is_empty]
            if empty_cols and len(empty_cols) < len(cols):
                df = df.drop(empty_cols)
                records += [self.record(None, c, "column_removed", None, None) for c in empty_cols]
                cols = data_columns(df)
        if params.get("drop_rows", True) and cols:
            empty = pl.all_horizontal([is_blank_expr(c) for c in cols])
            removed = df.filter(empty)
            if removed.height:
                records += [
                    self.record(row[ROW_ID], None, "row_removed", row_json(row), None)
                    for row in removed.iter_rows(named=True)
                ]
                df = df.filter(~empty)
        return df, records
