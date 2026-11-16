"""Rule 1: snake_case column names, with duplicates and empty names made unique."""

from __future__ import annotations

import polars as pl

from engine import parsing as P
from engine.rules.base import ROW_ID, Candidate, Rule


class NormalizeHeaders(Rule):
    id = "normalize_headers"
    scope = "table"
    default_mode = "auto"
    severity = "low"
    label = "Tidy column names"
    explain = "Column names become lower-case snake_case, and repeated or empty names are made unique."

    def trigger(self, profile):
        # Dataframe columns carry the uploaded header, made unique the same way ingest does it.
        current = P.unique_column_names([c.source_name for c in profile.columns], reserved={ROW_ID})
        mapping = {old: col.name for old, col in zip(current, profile.columns) if old != col.name}
        return [Candidate(params={"mapping": mapping})] if mapping else []

    def apply(self, df, column, params):
        mapping = {
            old: new
            for old, new in params.get("mapping", {}).items()
            if old in df.columns and old != new and (new not in df.columns or new in params["mapping"])
        }
        if not mapping:
            return df, []
        records = [self.record(None, new, "header_renamed", old, new) for old, new in mapping.items()]
        return df.rename(mapping), records
