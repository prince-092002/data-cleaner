"""Rule 3: trim spaces, remove hidden characters, normalize Unicode, repair mojibake (ftfy)."""

from __future__ import annotations

import ftfy

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with, value_counts


def clean_text(value: str) -> str:
    # Conservative ftfy: repair encoding damage only; keep curly quotes, ligatures and widths.
    fixed = ftfy.fix_text(
        value,
        unescape_html=False,
        uncurl_quotes=False,
        fix_latin_ligatures=False,
        fix_character_width=False,
        normalization="NFC",
    )
    return P.tidy_text(fixed)


class TrimAndNormalizeText(Rule):
    id = "trim_and_normalize_text"
    default_mode = "auto"
    severity = "low"
    label = "Trim spaces and fix hidden or broken characters"
    explain = "Extra spaces, invisible characters and broken accents are fixed; the words stay the same."

    def trigger(self, profile):
        cols = columns_with(profile, issues=("whitespace", "hidden_characters", "encoding_damage"))
        out = [Candidate(column=c.name) for c in cols]
        # Name casing (M6): a suggestion only, on person-name columns.
        for c in columns_with(profile, types=("text", "category")):
            if P.is_name_column(c.name):
                out.append(Candidate(
                    column=c.name, params={"name_case": True, "mapping": {}}, force_suggest=True,
                    title="Give names normal capital letters",
                    note=("Names written all in capitals or all in lower case get normal capitals "
                          "(JOHN O'BRIEN becomes John O'Brien). Names with mixed capitals are left alone."),
                ))
        return out

    def prepare(self, df, column, params):
        if not params.get("name_case"):
            return params, None
        return {**params, "mapping": P.name_case_mapping(value_counts(df, column))}, None

    def apply(self, df, column, params):
        if params.get("name_case"):
            mapping = params.get("mapping", {})
            if not mapping:
                return df, []
            return self.map_values(df, column, lambda v: mapping.get(v, mapping.get(P.tidy_text(v), v)))
        return self.map_values(df, column, clean_text)
