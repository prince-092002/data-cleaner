"""Rule 9: different spellings of the same category are mapped to the most common spelling."""

from __future__ import annotations

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with


class StandardizeCategories(Rule):
    id = "standardize_categories"
    is_destructive = True            # merging values is a judgment call
    default_mode = "suggest"
    severity = "medium"
    label = "Merge different spellings of the same category"
    explain = "Spellings that look like the same category are changed to the most common spelling."
    editable_params = ("mapping",)

    def trigger(self, profile):
        cols = columns_with(profile, types=("category",), issues=("inconsistent_categories",))
        return [Candidate(column=c.name, params={"mapping": {}}) for c in cols]

    def prepare(self, df, column, params):
        counts: dict[str, int] = {}
        for value in df.get_column(column).drop_nulls().to_list():
            if not P.is_null_token(value):
                counts[value] = counts.get(value, 0) + 1
        if not counts or not P.looks_categorical(len(counts), sum(counts.values())):
            return {**params, "mapping": {}}, None
        mapping, min_score = P.cluster_categories(counts)
        changes = {old: new for old, new in sorted(mapping.items()) if old != new}
        return {**params, "mapping": changes}, round(min_score / 100, 4)

    def apply(self, df, column, params):
        mapping: dict[str, str] = params.get("mapping", {})
        if not mapping:
            return df, []

        def remap(value: str) -> str:
            if value in mapping:
                return mapping[value]
            return mapping.get(P.tidy_text(value), value)   # still works if trimming was rejected

        return self.map_values(df, column, remap)
