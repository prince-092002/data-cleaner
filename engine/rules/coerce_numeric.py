"""Rule 5: numbers written with symbols become plain numbers ($1,200.50 -> 1200.50).

Never triggers on id-like columns (leading zeros, or names such as id / zip / phone):
the profiler types those as "id", not as numbers.
"""

from __future__ import annotations

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with


def to_plain_number(value: str, decimals: int | None = None) -> str:
    parsed = P.parse_number(value)
    if parsed is None:
        return value                                  # cannot fix -> leave unchanged
    text = parsed.canonical
    if decimals:                                      # pad only, never round
        whole, _, frac = text.partition(".")
        if len(frac) < decimals:
            text = f"{whole}.{frac.ljust(decimals, '0')}"
    return text


class CoerceNumeric(Rule):
    id = "coerce_numeric"
    version = "1.1.0"
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

    def prepare(self, df, column, params):
        """Money columns (any value written with a currency symbol) are written with 2 decimals."""
        values = df.get_column(column).drop_nulls().to_list()
        if any((p := P.parse_number(v)) and any(c in p.style for c in "$£€") for v in values):
            return {**params, "decimals": 2}, None
        return params, None

    def apply(self, df, column, params):
        decimals = params.get("decimals")
        return self.map_values(df, column, lambda v: to_plain_number(v, decimals))
