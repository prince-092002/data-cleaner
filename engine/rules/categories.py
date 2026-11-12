"""Rule 9: different spellings of the same category are merged.

Tier 1 (automatic): values that differ only by case, accents or whitespace become one spelling
(an existing Title Case spelling if there is one, else the most frequent). Tier 2 (suggestion): abbreviations and typos of an established value.
"""

from __future__ import annotations

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with, left_alone_list, value_counts


class StandardizeCategories(Rule):
    id = "standardize_categories"
    version = "1.1.0"
    is_destructive = True            # merging values is a judgment call (except Tier 1)
    default_mode = "suggest"
    severity = "medium"
    label = "Merge different spellings of the same category"
    explain = "Spellings that look like the same category are changed to one spelling."
    editable_params = ("mapping",)

    def trigger(self, profile):
        cols = columns_with(profile, types=("category",), issues=("inconsistent_categories",))
        out = []
        for c in cols:
            out.append(Candidate(column=c.name, params={"tier": 1, "mapping": {}}, auto_safe=True,
                                 note="Only capital letters, accents or spaces differ."))
            out.append(Candidate(column=c.name, params={"tier": 2, "mapping": {}, "reasons": {}},
                                 note="Abbreviations and typos of a common value; please check each one."))
        return out

    def prepare(self, df, column, params):
        counts: dict[str, int] = {}
        for value in df.get_column(column).drop_nulls().to_list():
            if not P.is_null_token(value):
                counts[value] = counts.get(value, 0) + 1
        if not counts or not P.looks_categorical(len(counts), sum(counts.values())):
            return {**params, "mapping": {}}, None
        if params.get("tier") == 1:
            return {**params, "mapping": dict(sorted(P.merge_case_variants(counts).items()))}, None
        merges = dict(sorted(P.suggest_category_merges(counts).items()))
        return {**params, "mapping": {v: t for v, (t, _) in merges.items()},
                "reasons": {v: r for v, (_, r) in merges.items()}}, None

    def left_alone(self, df, column, params):
        if params.get("tier") != 2:
            return []
        counts = value_counts(df, column)
        groups: dict[str, int] = {}
        for v, n in counts.items():                    # count per Tier 1 spelling
            groups[P.tidy_text(v)] = groups.get(P.tidy_text(v), 0) + n
        return left_alone_list(groups, P.category_left_alone(counts))

    def apply(self, df, column, params):
        mapping: dict[str, str] = params.get("mapping", {})
        if not mapping:
            return df, []

        def remap(value: str) -> str:
            if value in mapping:
                return mapping[value]
            return mapping.get(P.tidy_text(value), value)   # still works if trimming was rejected

        return self.map_values(df, column, remap)
