"""Rule 9: different spellings of the same category are merged.

Tier 1 (automatic): within values that differ only by case, accents or whitespace, a spelling
with 80% or more of the rows absorbs the others. Case suggestion: when no spelling has that
majority, an existing Title Case spelling (else the most frequent) is suggested. Tier 2
(suggestion): abbreviations and typos of an established value.
"""

from __future__ import annotations

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with, left_alone_list, value_counts

MAJORITY_REASON = "majority spelling"
EDITED_REASON = "merge chosen by the user"     # a value the user added to the mapping


def _case_kind(target: str) -> str:
    return "Title Case spelling" if P._is_title_case(target) else "most common spelling"


class StandardizeCategories(Rule):
    id = "standardize_categories"
    version = "1.2.0"
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
                                 note="Only capital letters, accents or spaces differ, and one spelling "
                                      "is used in at least 80% of these rows."))
            out.append(Candidate(column=c.name, params={"case_suggestion": True, "mapping": {}, "reasons": {}},
                                 note="Only capital letters, accents or spaces differ, but no spelling is "
                                      "used in 80% of these rows; please check."))
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
        if params.get("case_suggestion"):
            mapping = dict(sorted(P.suggest_case_variants(counts).items()))
            reasons = {v: f'No spelling is used in 80% of rows, so the {_case_kind(t)} "{t}" is suggested'
                       for v, t in mapping.items()}
            return {**params, "mapping": mapping, "reasons": reasons}, None
        merges = dict(sorted(P.suggest_category_merges(counts).items()))
        return {**params, "mapping": {v: t for v, (t, _) in merges.items()},
                "reasons": {v: r for v, (_, r) in merges.items()}}, None

    def left_alone(self, df, column, params):
        if params.get("tier") != 2:
            return []
        counts = value_counts(df, column)
        return left_alone_list(P.category_group_counts(counts), P.category_left_alone(counts))

    def apply(self, df, column, params):
        mapping: dict[str, str] = params.get("mapping", {})
        if not mapping:
            return df, []

        def remap(value: str) -> str:
            if value in mapping:
                return mapping[value]
            return mapping.get(P.tidy_text(value), value)   # still works if trimming was rejected

        df, records = self.map_values(df, column, remap)
        reasons: dict[str, str] = params.get("reasons", {})
        chosen = set(params.get("user_chosen", []))
        for r in records:
            if r.old_value in chosen or P.tidy_text(r.old_value) in chosen:
                r.reason = EDITED_REASON
            elif params.get("tier") == 1:
                r.reason = MAJORITY_REASON
            elif params.get("case_suggestion"):
                r.reason = f"{_case_kind(r.new_value)}, no clear majority"
            else:
                r.reason = reasons.get(r.old_value) or reasons.get(P.tidy_text(r.old_value)) or EDITED_REASON
        return df, records
