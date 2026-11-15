"""Rule interface and shared helpers. See docs/CONTRACT.md section 2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable

import polars as pl

from engine import parsing as P
from engine.changelog import ChangeRecord
from engine.models import ColumnProfile, DatasetProfile, LeftAlone

ROW_ID = "_row_id"
OUTLIER_SUFFIX = "_outlier_flag"
AUTO_THRESHOLD = 0.98
SUGGEST_THRESHOLD = 0.80


@dataclass
class Candidate:
    """Where a rule wants to act. The pipeline turns candidates into Proposals."""

    column: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    force_suggest: bool = False
    note: str | None = None          # extra sentence for the proposal description
    auto_safe: bool = False          # only removes differences of case, accents or spacing: may run auto
    title: str | None = None         # proposal title instead of the rule label (one rule, two kinds of fix)


class Rule:
    id: str = ""
    version: str = "1.0.0"
    scope: str = "column"            # "column" | "table"
    is_destructive: bool = False
    default_mode: str = "auto"       # "auto" | "suggest" | "flag"
    severity: str = "low"
    label: str = ""                  # short title shown to the user
    explain: str = ""                # one plain-language sentence
    editable_params: tuple[str, ...] = ()
    auto_when_destructive: bool = False   # True only for rules that remove provably empty/identical data

    def trigger(self, profile: DatasetProfile) -> list[Candidate]:
        """Read-only. Decide where this rule applies."""
        raise NotImplementedError

    def prepare(self, df: pl.DataFrame, column: str | None, params: dict) -> tuple[dict, float | None]:
        """Fill in params that depend on the data (as it stands after the earlier rules).

        Returns (params, confidence). A confidence of None keeps the candidate's own.
        """
        return params, None

    def left_alone(self, df: pl.DataFrame, column: str | None, params: dict) -> list[LeftAlone]:
        """Values this rule saw but will not change, with a reason (shown on the fixes screen)."""
        return []

    def apply(
        self, df: pl.DataFrame, column: str | None, params: dict
    ) -> tuple[pl.DataFrame, list[ChangeRecord]]:
        """Pure. Returns a NEW dataframe and one record per change."""
        raise NotImplementedError

    # ---- helpers for subclasses
    def record(self, row_id, column, change_type, old, new) -> ChangeRecord:
        return ChangeRecord(
            None, self.id, self.version, row_id, column, change_type, old, new, None, None
        )

    def map_values(self, df: pl.DataFrame, column: str, fn: Callable[[str], str | None]):
        """Apply fn to every non-null value of one column; log each value that changes.

        Works on distinct values: fn runs once per distinct value, the column is rewritten by
        Polars, and Python only loops over the rows that actually change (to log them).
        """
        series = df.get_column(column)
        changed: dict[str, str | None] = {}
        for value in series.drop_nulls().unique().to_list():
            new = fn(value)
            if new != value:
                changed[value] = new
        if not changed:
            return df, []
        hit = df.filter(pl.col(column).is_in(list(changed))).select(ROW_ID, column)
        records = [
            self.record(row_id, column, "cell", old, changed[old])
            for row_id, old in zip(hit.get_column(ROW_ID).to_list(), hit.get_column(column).to_list())
        ]
        new_col = series.replace_strict(list(changed), list(changed.values()), default=series,
                                        return_dtype=pl.Utf8)
        return df.with_columns(new_col.alias(column)), records


LEFT_ALONE_MAX = 20


def value_counts(df: pl.DataFrame, column: str) -> dict[str, int]:
    """Non-null, non-null-token values of a column -> count."""
    counts: dict[str, int] = {}
    for value in df.get_column(column).drop_nulls().to_list():
        if not P.is_null_token(value):
            counts[value] = counts.get(value, 0) + 1
    return counts


def left_alone_list(counts: dict[str, int], reasons: dict[str, str]) -> list[LeftAlone]:
    """Most frequent first, at most LEFT_ALONE_MAX entries."""
    items = sorted(reasons, key=lambda v: (-counts.get(v, 0), v))[:LEFT_ALONE_MAX]
    return [LeftAlone(value=v, count=counts.get(v, 0), reason=reasons[v]) for v in items]


def data_columns(df: pl.DataFrame) -> list[str]:
    return [c for c in df.columns if c != ROW_ID]


def is_blank_expr(column: str) -> pl.Expr:
    """True where a cell is null or a null token."""
    return pl.col(column).is_null() | pl.col(column).str.strip_chars().str.to_lowercase().is_in(
        list(P.NULL_TOKENS)
    )


def row_json(row: dict) -> str:
    return json.dumps({k: v for k, v in row.items() if k != ROW_ID}, ensure_ascii=False)


def columns_with(
    profile: DatasetProfile, *, types: tuple[str, ...] = (), issues: tuple[str, ...] = ()
) -> list[ColumnProfile]:
    out = []
    for col in profile.columns:
        if types and col.inferred_type not in types:
            continue
        if issues and not any(i.code in issues for i in col.issues):
            continue
        out.append(col)
    return out


def proposal_id(rule_id: str, column: str | None, params: dict) -> str:
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha1(f"{rule_id}|{column or ''}|{canonical}".encode("utf-8")).hexdigest()
    return "sug_" + digest[:12]


def resolve_mode(
    rule: Rule, confidence: float | None, force_suggest: bool = False, auto_safe: bool = False
) -> str | None:
    """auto / suggest / flag, or None when the proposal must be dropped (confidence < 0.80).

    auto_safe: the candidate only removes differences of case, accents or spacing, so it starts
    as auto even for a destructive rule (CONTRACT 2.1)."""
    mode = "auto" if auto_safe else rule.default_mode
    if confidence is not None:
        if confidence < SUGGEST_THRESHOLD:
            return None
        if confidence < AUTO_THRESHOLD and mode == "auto":
            mode = "suggest"
    if force_suggest and mode == "auto":
        mode = "suggest"
    if rule.is_destructive and mode == "auto" and not (rule.auto_when_destructive or auto_safe):
        mode = "suggest"
    return mode
