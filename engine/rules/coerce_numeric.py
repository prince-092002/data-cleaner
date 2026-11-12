"""Rule 5: numbers written with symbols become plain numbers ($1,200.50 -> 1200.50).

Never triggers on id-like columns (leading zeros, or names such as id / zip / phone):
the profiler types those as "id", not as numbers.
"""

from __future__ import annotations

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with


def to_plain_number(value: str) -> str:
    parsed = P.parse_number(value)
    return parsed.canonical if parsed else value      # cannot fix -> leave unchanged


class CoerceNumeric(Rule):
    id = "coerce_numeric"
    default_mode = "auto"
    severity = "high"
    label = "Convert to plain numbers"
    explain = "Currency symbols, thousands separators and % signs are removed; (123) becomes -123."

    def trigger(self, profile):
        cols = columns_with(profile, types=("integer", "decimal"), issues=("numeric_as_text", "whitespace"))
        return [
            Candidate(
                column=c.name,
                params={"decimal": ".", "thousands": ","},
                confidence=c.type_confidence,
                note=f"{round(100 * c.type_confidence, 1)}% of values are numbers; the rest are left as they are.",
            )
            for c in cols
        ]

    def apply(self, df, column, params):
        return self.map_values(df, column, to_plain_number)
