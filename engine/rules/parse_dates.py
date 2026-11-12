"""Rule 6: dates become ISO 8601 (YYYY-MM-DD, with THH:MM:SS when a time is present)."""

from __future__ import annotations

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with


class ParseDates(Rule):
    id = "parse_dates"
    default_mode = "auto"
    severity = "high"
    label = "Convert dates to ISO 8601"
    explain = "Dates are rewritten as YYYY-MM-DD so they sort and compare correctly."
    editable_params = ("dayfirst",)

    def trigger(self, profile):
        out = []
        for c in columns_with(profile, types=("date", "datetime")):
            ambiguous = any(i.code == "ambiguous_dates" for i in c.issues)
            note = f"{round(100 * c.type_confidence, 1)}% of values are dates."
            if ambiguous:
                note += (
                    " Day and month cannot be told apart (03/04 could be 3 April or 4 March),"
                    " so please confirm the order."
                )
            out.append(
                Candidate(column=c.name, params={"dayfirst": False},
                          confidence=c.type_confidence, force_suggest=ambiguous, note=note)
            )
        return out

    def prepare(self, df, column, params):
        counts: dict[str, int] = {}
        for value in df.get_column(column).drop_nulls().to_list():
            counts[value] = counts.get(value, 0) + 1
        parsed = {v: (p, n) for v, n in counts.items() if (p := P.parse_date(v))}
        order = P.decide_date_order(parsed)
        return {**params, "dayfirst": order.dayfirst}, None

    def apply(self, df, column, params):
        dayfirst = bool(params.get("dayfirst", False))

        def to_iso(value: str) -> str:
            parsed = P.parse_date(value)
            iso = parsed.to_iso(dayfirst) if parsed else None
            return iso or value                        # cannot fix -> leave unchanged

        return self.map_values(df, column, to_iso)
