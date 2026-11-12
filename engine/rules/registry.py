"""Rule registry: the 10 Phase 1 rules in their fixed run order (CONTRACT.md section 2.2)."""

from __future__ import annotations

from engine.rules.base import Rule
from engine.rules.booleans import StandardizeBooleans
from engine.rules.categories import StandardizeCategories
from engine.rules.coerce_numeric import CoerceNumeric
from engine.rules.drop_empty import DropEmptyRowsAndColumns
from engine.rules.duplicates import RemoveExactDuplicateRows
from engine.rules.normalize_headers import NormalizeHeaders
from engine.rules.null_tokens import StandardizeNullTokens
from engine.rules.outliers import FlagOutliers
from engine.rules.parse_dates import ParseDates
from engine.rules.trim_text import TrimAndNormalizeText

RULES: list[Rule] = [
    NormalizeHeaders(),
    DropEmptyRowsAndColumns(),
    TrimAndNormalizeText(),
    StandardizeNullTokens(),
    CoerceNumeric(),
    ParseDates(),
    StandardizeBooleans(),
    RemoveExactDuplicateRows(),
    StandardizeCategories(),
    FlagOutliers(),
]

RULES_BY_ID: dict[str, Rule] = {rule.id: rule for rule in RULES}
ORDER: dict[str, int] = {rule.id: i for i, rule in enumerate(RULES)}
