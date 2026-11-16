"""Rule 4: placeholders for "missing" (N/A, -, TBD, ...) become real empty cells."""

from __future__ import annotations

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with

DEFAULT_TOKENS = ["", "NA", "N/A", "null", "-", "?", "#N/A", "TBD"]


class StandardizeNullTokens(Rule):
    id = "standardize_null_tokens"
    default_mode = "auto"
    severity = "medium"
    label = "Turn placeholders into empty cells"
    explain = 'Placeholders such as "N/A", "-" or "TBD" become real empty cells.'

    def trigger(self, profile):
        cols = columns_with(profile, issues=("null_tokens",))
        return [Candidate(column=c.name, params={"tokens": DEFAULT_TOKENS}) for c in cols]

    def apply(self, df, column, params):
        tokens = {t.casefold() for t in params.get("tokens", DEFAULT_TOKENS)}
        return self.map_values(
            df, column, lambda v: None if P.strip_hidden(v).casefold() in tokens else v
        )
