"""Profiling: per-column stats and quality score. See docs/CONTRACT.md sections 3 and 4.

DuckDB does the counting (value frequencies, duplicate rows). Per-value checks run in Python
on the *distinct* values of each column, weighted by their counts.
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Callable

import polars as pl
from ftfy.badness import is_bad

from engine import parsing as P
from engine.models import (
    WEIGHTS,
    ColumnProfile,
    ColumnQuality,
    DatasetProfile,
    FormatPattern,
    Issue,
    QualityScore,
    SourceInfo,
    TopValue,
)

ROW_ID = "_row_id"
OUTLIER_SUFFIX = "_outlier_flag"
TYPE_THRESHOLD = 0.80
KEY_THRESHOLD = 0.95
KEY_TYPES = {"id", "integer", "text"}
OUTLIER_MIN_VALUES = 20
OUTLIER_K = 1.5

ProgressFn = Callable[[int, str], None]


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _is_damaged(value: str) -> bool:
    return "�" in value or bool(P.HIDDEN_RE.search(value)) or is_bad(value)


def _fmt_num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else repr(round(x, 6))


def iqr_bounds(values: list[float], k: float = OUTLIER_K) -> tuple[float, float]:
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


# --------------------------------------------------------------------------- one column

def profile_column(
    *,
    name: str,
    source_name: str,
    position: int,
    row_count: int,
    counts: dict[str, int],
    samples: list[str],
    row_uniqueness: float,
    header_ok: bool,
) -> ColumnProfile:
    """counts: every non-null raw value of the column -> how many times it appears."""
    n = row_count
    values = {v: c for v, c in counts.items() if not P.is_null_token(v)}
    token_count = sum(c for v, c in counts.items() if v not in values)
    nn = sum(values.values())
    distinct = len(values)

    nums = {v: p for v in values if (p := P.parse_number(v))}
    bools = {v: p for v in values if (p := P.parse_bool(v))}
    dates = {v: p for v in values if (p := P.parse_date(v))}
    num_n = sum(values[v] for v in nums)
    bool_n = sum(values[v] for v in bools)
    date_order = P.decide_date_order({v: (p, values[v]) for v, p in dates.items()})
    iso = {v: s for v, p in dates.items() if (s := p.to_iso(date_order.dayfirst))}
    date_n = sum(values[v] for v in iso)

    share = (lambda k: k / nn) if nn else (lambda k: 0.0)
    leading_zero = P.leading_zeros_mean_id(nums)

    # ---- type inference (CONTRACT.md section 3)
    if nn == 0:
        itype, conf = "empty", 1.0
    elif share(date_n) >= TYPE_THRESHOLD:
        with_time = sum(values[v] for v in iso if dates[v].has_time)
        itype, conf = ("datetime" if with_time * 2 > date_n else "date"), share(date_n)
    elif share(bool_n) >= TYPE_THRESHOLD and bool_n >= num_n:
        itype, conf = "boolean", share(bool_n)
    elif share(num_n) >= TYPE_THRESHOLD and (leading_zero or P.is_id_like_name(name)):
        itype, conf = "id", 1.0
    elif share(num_n) >= TYPE_THRESHOLD:
        all_int = all(p.is_integer for p in nums.values())
        itype, conf = ("integer" if all_int else "decimal"), share(num_n)
    elif P.looks_categorical(distinct, nn):
        itype, conf = "category", 1.0
    else:
        itype, conf = "text", 1.0

    is_key = itype in KEY_TYPES and nn > 0 and distinct / nn >= KEY_THRESHOLD
    issues: list[Issue] = []

    def issue(code: str, severity: str, message: str, count: int) -> None:
        if count > 0:
            issues.append(Issue(code=code, severity=severity, message=message, count=count))

    # ---- per-type validity / consistency / standard form
    vmin = vmax = None
    mean = median = None
    if itype in ("integer", "decimal"):
        valid_n = num_n
        styles = Counter()
        for v, p in nums.items():
            styles[p.style] += values[v]
        consistent_n = max(styles.values())
        standard_n = sum(values[v] for v, p in nums.items() if v == p.canonical)   # "03" is not standard
        expanded = sorted(x for v, p in nums.items() for x in [p.value] * values[v])
        vmin, vmax = _fmt_num(expanded[0]), _fmt_num(expanded[-1])
        mean = round(statistics.fmean(expanded), 4)
        median = round(statistics.median(expanded), 4)
        issue("mixed_types", "high", f"{nn - num_n} values are not numbers", nn - num_n)
        issue("numeric_as_text", "medium",
              "Numbers written with symbols or separators (for example $ , % or brackets)",
              num_n - standard_n)
        if len(expanded) >= OUTLIER_MIN_VALUES:
            low, high = iqr_bounds(expanded)
            outliers = sum(1 for x in expanded if x < low or x > high)
            issue("outliers", "low", f"{outliers} values are far outside the usual range", outliers)
    elif itype in ("date", "datetime"):
        valid_n = date_n
        fmts = Counter()
        for v in iso:
            fmts[dates[v].fmt] += values[v]
        consistent_n = max(fmts.values())
        standard_n = sum(values[v] for v in iso if P.ISO_DATE_RE.match(v))
        vmin, vmax = min(iso.values()), max(iso.values())
        issue("mixed_types", "high", f"{nn - date_n} values are not dates", nn - date_n)
        if len(fmts) > 1:
            issue("mixed_date_formats", "high", f"{len(fmts)} date formats found",
                  date_n - consistent_n)
        if date_order.ambiguous:
            ambiguous_n = sum(values[v] for v in iso if dates[v].kind == "numeric")
            issue("ambiguous_dates", "medium",
                  "Day and month cannot be told apart (every day and month is 12 or less)",
                  ambiguous_n)
    elif itype == "boolean":
        valid_n = bool_n
        styles = Counter()
        for v, p in bools.items():
            styles[p.style] += values[v]
        consistent_n = max(styles.values())
        standard_n = sum(c for v, c in values.items() if v in ("true", "false"))
        issue("mixed_types", "high", f"{nn - bool_n} values are not yes/no values", nn - bool_n)
        if len(styles) > 1:
            issue("inconsistent_booleans", "medium",
                  f"{len(styles)} ways of writing yes/no", bool_n - consistent_n)
    else:  # id, category, text, empty
        damaged_n = sum(c for v, c in values.items() if _is_damaged(v))
        valid_n = nn - damaged_n
        tidy_n = sum(c for v, c in values.items() if v == P.tidy_text(v))
        standard_n = tidy_n
        if itype == "category":
            mapping = P.cluster_categories(values)
            consistent_n = sum(c for v, c in values.items() if mapping[v] == v)
            issue("inconsistent_categories", "medium",
                  "The same category is spelled in different ways", nn - consistent_n)
        elif itype == "id":
            patterns = Counter()
            for v, c in values.items():
                patterns[P.collapsed_pattern(v)] += c
            consistent_n = max(patterns.values()) if patterns else 0
        else:
            consistent_n = sum(c for v, c in values.items() if not P.has_whitespace_issue(v))
            best_other = max(num_n, bool_n, date_n)
            if nn and 0.5 <= best_other / nn < TYPE_THRESHOLD:
                issue("mixed_types", "high", "The column mixes text with numbers or dates",
                      nn - best_other)
        issue("encoding_damage", "medium", "Broken or unreadable characters", damaged_n)

    # ---- issues common to all types
    null_count = n - nn
    null_pct = _pct(null_count, n)
    if itype == "empty":
        issue("empty_column", "low", "The column has no values", n or 1)
    else:
        sev = "high" if null_pct > 20 else "medium" if null_pct > 5 else "low"
        issue("missing_values", sev, f"{null_pct}% of values are missing", null_count)
    issue("null_tokens", "medium", 'Placeholders such as "N/A", "-" or "TBD" used for missing',
          token_count)
    issue("whitespace", "low", "Extra spaces at the start, end or middle of values",
          sum(c for v, c in values.items() if P.has_whitespace_issue(v)))
    issue("hidden_characters", "low", "Invisible characters inside values",
          sum(c for v, c in values.items() if P.has_hidden_chars(v)))
    if is_key:
        issue("duplicate_keys", "high", "Values that should be unique are repeated", nn - distinct)
    if not header_ok:
        issue("messy_header", "low", f'Header "{source_name}" is not a clean column name', 1)

    # ---- quality (CONTRACT.md section 4)
    if n == 0:
        dims = dict.fromkeys(WEIGHTS, 0.0)
    elif nn == 0:
        dims = {"completeness": 0.0, "validity": 1.0, "consistency": 1.0,
                "uniqueness": 1.0, "conformity": 1.0}
    else:
        dims = {
            "completeness": nn / n,
            "validity": valid_n / nn,
            "consistency": consistent_n / nn,
            "uniqueness": distinct / nn if is_key else row_uniqueness,
            "conformity": 0.2 * header_ok + 0.8 * standard_n / (nn + token_count),
        }
    quality = ColumnQuality(
        score=round(100 * sum(WEIGHTS[d] * dims[d] for d in WEIGHTS), 1),
        **{d: round(100 * dims[d], 1) for d in WEIGHTS},
    )

    lengths = [len(v) for v in values]
    top = sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))[:10]
    patterns = Counter()
    for v, c in values.items():
        patterns[P.format_pattern(v)] += c

    return ColumnProfile(
        name=name,
        source_name=source_name,
        position=position,
        inferred_type=itype,
        type_confidence=round(conf, 4),
        row_count=n,
        null_count=null_count,
        null_pct=null_pct,
        distinct_count=distinct,
        distinct_pct=_pct(distinct, nn),
        is_key_candidate=is_key,
        min=vmin,
        max=vmax,
        mean=mean,
        median=median,
        min_length=min(lengths) if lengths else None,
        max_length=max(lengths) if lengths else None,
        top_values=[TopValue(value=v, count=c) for v, c in top],
        samples=[s for s in samples if not P.is_null_token(s)][:5],
        format_patterns=[
            FormatPattern(pattern=p, count=c)
            for p, c in sorted(patterns.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        ],
        issues=issues,
        quality=quality,
    )


# --------------------------------------------------------------------------- whole dataset

def roll_up(columns: list[ColumnProfile]) -> QualityScore:
    """Dataset dimension = mean over scored columns; overall = weighted sum."""
    scored = [c for c in columns if not c.name.endswith(OUTLIER_SUFFIX)]
    if not scored:
        return QualityScore(overall=0.0, **dict.fromkeys(WEIGHTS, 0.0))
    dims = {d: sum(getattr(c.quality, d) for c in scored) / len(scored) for d in WEIGHTS}
    return QualityScore(
        overall=round(sum(WEIGHTS[d] * dims[d] for d in WEIGHTS), 1),
        **{d: round(v, 1) for d, v in dims.items()},
    )


def profile_dataframe(
    df: pl.DataFrame,
    source: SourceInfo,
    source_names: dict[str, str] | None = None,
    progress: ProgressFn | None = None,
) -> DatasetProfile:
    """Profile an all-text dataframe.

    source_names maps dataframe column -> header as uploaded. Leave it out for a dataframe
    whose columns are already final names (for example the cleaned output).
    """
    report = progress or (lambda pct, step: None)
    data_cols = [c for c in df.columns if c != ROW_ID]
    n = df.height
    if source_names is None:
        names = data_cols
        originals = data_cols
    else:
        originals = [source_names.get(c, c) for c in data_cols]
        names = P.normalize_header_names(originals)

    if n and data_cols:
        distinct_rows = df.select(data_cols).unique().height
    else:
        distinct_rows = n
    duplicate_rows = n - distinct_rows
    row_uniqueness = 1 - duplicate_rows / n if n else 0.0

    if n and data_cols:
        tokens = list(P.NULL_TOKENS)
        empty_rows = df.select(
            pl.all_horizontal(
                [
                    pl.col(c).is_null()
                    | pl.col(c).str.strip_chars().str.to_lowercase().is_in(tokens)
                    for c in data_cols
                ]
            ).sum()
        ).item()
    else:
        empty_rows = 0

    columns: list[ColumnProfile] = []
    for i, (col, name, original) in enumerate(zip(data_cols, names, originals)):
        report(30 + int(50 * i / max(len(data_cols), 1)), "Profiling columns")
        # renamed so a data column called "count" cannot clash with the count column
        vc = df.get_column(col).drop_nulls().alias("value").value_counts(name="n")
        counts = dict(zip(vc.get_column("value").to_list(), vc.get_column("n").to_list()))
        samples = df.get_column(col).drop_nulls().unique(maintain_order=True).head(25).to_list()
        columns.append(
            profile_column(
                name=name,
                source_name=original,
                position=i,
                row_count=n,
                counts=counts,
                samples=samples,
                row_uniqueness=row_uniqueness,
                header_ok=(original == name),
            )
        )

    report(85, "Scoring quality")
    return DatasetProfile(
        source=source,
        row_count=n,
        column_count=len(data_cols),
        duplicate_row_count=duplicate_rows,
        empty_row_count=empty_rows,
        quality=roll_up(columns),
        columns=columns,
    )
