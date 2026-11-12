"""Rule 10: flag unusual numbers in a new <column>_outlier_flag column. Never changes or removes values."""

from __future__ import annotations

import polars as pl

from engine import parsing as P
from engine.profile import OUTLIER_MIN_VALUES, iqr_bounds
from engine.rules.base import OUTLIER_SUFFIX, ROW_ID, Candidate, Rule, columns_with


class FlagOutliers(Rule):
    id = "flag_outliers"
    default_mode = "flag"
    severity = "medium"
    label = "Flag unusual values"
    explain = "Adds a true/false column marking values far outside the usual range. Nothing is changed or removed."
    editable_params = ("k",)

    def trigger(self, profile):
        cols = columns_with(profile, types=("integer", "decimal"), issues=("outliers",))
        return [Candidate(column=c.name, params={"k": 1.5}) for c in cols]

    def apply(self, df, column, params):
        flag_col = column + OUTLIER_SUFFIX
        if flag_col in df.columns:
            return df, []
        values = df.get_column(column).to_list()
        numbers = [P.parse_number(v).value if v is not None and P.parse_number(v) else None for v in values]
        present = [x for x in numbers if x is not None]
        if len(present) < OUTLIER_MIN_VALUES:
            return df, []
        low, high = iqr_bounds(present, float(params.get("k", 1.5)))
        flags = [None if x is None else ("true" if x < low or x > high else "false") for x in numbers]
        if "true" not in flags:
            return df, []
        records = [self.record(None, flag_col, "column_added", None, None)]
        records += [
            self.record(row_id, flag_col, "cell", None, "true")
            for row_id, flag in zip(df.get_column(ROW_ID).to_list(), flags)
            if flag == "true"
        ]
        position = df.columns.index(column) + 1
        # clone first: insert_column changes a dataframe in place, and apply must not mutate its input
        return df.clone().insert_column(position, pl.Series(flag_col, flags, dtype=pl.Utf8)), records
