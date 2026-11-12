"""Rule 3: trim spaces, remove hidden characters, normalize Unicode, repair mojibake (ftfy)."""

from __future__ import annotations

import ftfy

from engine import parsing as P
from engine.rules.base import Candidate, Rule, columns_with


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
        return [Candidate(column=c.name) for c in cols]

    def apply(self, df, column, params):
        return self.map_values(df, column, clean_text)
