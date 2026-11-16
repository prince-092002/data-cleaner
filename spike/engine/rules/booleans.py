"""Rule 7: yes/no, y/n, true/false, t/f, 1/0, on/off become true / false."""

from __future__ import annotations

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with


class StandardizeBooleans(Rule):
    id = "standardize_booleans"
    default_mode = "auto"
    severity = "medium"
    label = "Standardize yes/no values"
    explain = 'Every way of writing yes or no (Y, Yes, TRUE, 1, ...) becomes "true" or "false".'

    def trigger(self, profile):
        # Only when every non-null value is a known boolean token.
        cols = [c for c in columns_with(profile, types=("boolean",)) if c.type_confidence >= 1.0]
        return [
            Candidate(column=c.name, params={"true_tokens": P.TRUE_TOKENS, "false_tokens": P.FALSE_TOKENS})
            for c in cols
        ]

    def apply(self, df, column, params):
        true_tokens = set(params.get("true_tokens", P.TRUE_TOKENS))
        false_tokens = set(params.get("false_tokens", P.FALSE_TOKENS))

        def to_bool(value: str) -> str:
            token = P.strip_hidden(value).casefold()
            if token in true_tokens:
                return "true"
            if token in false_tokens:
                return "false"
            return value

        return self.map_values(df, column, to_bool)
