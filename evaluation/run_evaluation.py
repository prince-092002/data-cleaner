"""Precision and recall of the cleaning engine on the ground-truth sample files.

Two batches: the tuning batch (sample_data/, three files, the one the engine was developed on)
and the held-out batch (sample_data/heldout/, a different seed plus store_visits_messy.csv; never
tune against it). The headline numbers are detection recall and fix recall over ALL injected
errors (M6 step 8); the older "recall on fixable errors" view is kept below them.

    .venv/Scripts/python evaluation/run_evaluation.py

For each file in sample_data/ground_truth.csv (the chicago file is excluded: no ground truth):
profile, approve every proposal, clean into a temp dir, align input rows to output rows by
_row_id, then score recall, precision, damaged cells and the engine's own quality scores.

Writes evaluation/RESULTS.md and evaluation/results.json. Importable: run(out_dir=None) -> dict.
Read-only on sample_data/. Scoring logic is independent of the engine's own parsers, except
that the engine's profile and clean output are the things being measured.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
import tempfile
import unicodedata
import uuid
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import ftfy  # noqa: E402

from engine import ingest as _ingest  # noqa: E402
from engine import pipeline  # noqa: E402
from engine.models import Decisions  # noqa: E402

SAMPLES = ROOT / "sample_data"
GROUND_TRUTH = SAMPLES / "ground_truth.csv"
HERE = Path(__file__).resolve().parent
FILES = ["sales_orders_messy.csv", "customers_messy.xlsx", "hr_survey_messy.csv"]
HELDOUT = SAMPLES / "heldout"
HELDOUT_FILES = FILES + ["store_visits_messy.csv"]
ROW_ID = "_row_id"
FLAG_SUFFIX = "_outlier_flag"
DIMENSIONS = ["overall", "completeness", "validity", "consistency", "uniqueness", "conformity"]
RULE_ORDER = [
    "normalize_headers", "drop_empty_rows_and_columns", "trim_and_normalize_text",
    "standardize_null_tokens", "coerce_numeric", "parse_dates", "standardize_booleans",
    "remove_exact_duplicate_rows", "standardize_categories", "flag_outliers",
]

# ---------------------------------------------------------------- error-type claims

# error_type -> (rule that claims it, value kind used to compare the cell)
FIXABLE: dict[str, tuple[str, str]] = {
    "extra_whitespace": ("trim_and_normalize_text", "text"),
    "non_breaking_space": ("trim_and_normalize_text", "text"),
    "zero_width_space": ("trim_and_normalize_text", "text"),
    "mojibake": ("trim_and_normalize_text", "text"),
    "null_token": ("standardize_null_tokens", "null"),
    "currency_symbol": ("coerce_numeric", "num"),
    "number_with_thousands_sep": ("coerce_numeric", "num"),
    "parentheses_negative": ("coerce_numeric", "num"),
    "percent_symbol": ("coerce_numeric", "num"),
    "mixed_date_format": ("parse_dates", "date"),
    "boolean_variant": ("standardize_booleans", "bool"),
    "typo_category": ("standardize_categories", "text"),
    "case_variant": ("standardize_categories", "text"),
    "outlier": ("flag_outliers", "flag"),
    "category_abbreviation": ("standardize_categories", "text"),   # held-out stores file
    "leading_zero": ("coerce_numeric", "num"),                     # held-out stores file
}
# Column-level detection: the profile issue that names this kind of problem for the column.
ISSUE_FOR: dict[str, str] = {
    "missing_value": "missing_values",
    "invalid_value": "mixed_types",
    "ambiguous_date": "ambiguous_dates",
    "duplicate_key": "duplicate_keys",
    "category_synonym": "inconsistent_categories",
}
# Error types whose correct clean form is an empty cell (the original value cannot be known).
EXPECT_NULL = {"null_token", "placeholder_token"}
# Structural errors scored by a file-level or column-level check.
STRUCTURAL: dict[str, tuple[str, str]] = {
    "header_whitespace": ("normalize_headers", "header"),
    "duplicate_header": ("normalize_headers", "header"),
    "empty_header": ("normalize_headers", "header"),
    "empty_column": ("drop_empty_rows_and_columns", "column"),
}
ROW_LEVEL: dict[str, str] = {
    "duplicate_row": "remove_exact_duplicate_rows",
    "empty_row": "drop_empty_rows_and_columns",
}
# Injected errors that no rule claims to fix (listed, excluded from headline recall).
NOT_FIXABLE: dict[str, str] = {
    "missing_value": "a deleted value cannot be restored; no rule imputes",
    "invalid_value": "unparseable text stays as it was (by design: 'never guessed')",
    "ambiguous_date": "day/month choice needed; the rule applies one order column-wide",
    "category_synonym": "no rule maps synonyms; clustering is by spelling only",
    "placeholder_token": "filler such as 'unknown' is not in the null-token list",
    "stray_marker": "no rule removes a marker inside a non-empty column",
    "duplicate_key": "no rule detects an id copied from the previous row",
}
# Structural errors handled by file reading, not by a cleaning rule (not scored).
OUT_OF_SCOPE: dict[str, str] = {
    "title_row": "title line above header is skipped by header detection (ingest)",
    "blank_row_above_header": "blank line above header is skipped by header detection (ingest)",
    "utf8_bom": "byte order mark handled by the reader (ingest)",
    "non_default_encoding": "encoding detection (ingest)",
    "non_default_delimiter": "delimiter detection (ingest)",
}
NULL_TOKENS = {"", "na", "n/a", "null", "-", "?", "#n/a", "tbd"}
ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)


# ---------------------------------------------------------------- independent value semantics

def is_null(v: str | None) -> bool:
    return v is None or v.strip().lower() in NULL_TOKENS


def canon_text(v: str) -> str:
    s = unicodedata.normalize("NFC", ftfy.fix_text(v)).translate(ZERO_WIDTH)
    return " ".join(s.replace("\u00a0", " ").split())


_BOOL_TRUE = {"yes", "y", "true", "t", "1", "on"}
_BOOL_FALSE = {"no", "n", "false", "f", "0", "off"}
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


def bool_value(v: str) -> str | None:
    s = v.strip().lower()
    if s in _BOOL_TRUE:
        return "true"
    if s in _BOOL_FALSE:
        return "false"
    return None


def num_value(v: str) -> float | None:
    s = v.strip().replace("\u00a0", "")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    for ch in "$£€,% ":
        s = s.replace(ch, "")
    if not _NUM_RE.match(s):
        return None
    x = float(s)
    return -abs(x) if neg else x


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$")
_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?:\s.*)?$")
_D_MON_Y = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})$")
_MON_D_Y = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$")


def _valid(y: int, m: int, d: int) -> tuple[int, int, int] | None:
    try:
        dt.date(y, m, d)
    except ValueError:
        return None
    return (y, m, d)


def date_candidates(v: str) -> set[tuple[int, int, int]]:
    """All calendar dates the text could mean (both day/month orders for numeric forms)."""
    s = v.strip()
    out: set = set()
    if m := _ISO.match(s):
        out.add(_valid(int(m[1]), int(m[2]), int(m[3])))
    elif m := _DMY.match(s):
        out.add(_valid(int(m[3]), int(m[2]), int(m[1])))
        out.add(_valid(int(m[3]), int(m[1]), int(m[2])))
    elif m := _D_MON_Y.match(s):
        if m[2][:3].lower() in _MONTHS:
            out.add(_valid(int(m[3]), _MONTHS[m[2][:3].lower()], int(m[1])))
    elif m := _MON_D_Y.match(s):
        if m[1][:3].lower() in _MONTHS:
            out.add(_valid(int(m[3]), _MONTHS[m[1][:3].lower()], int(m[2])))
    out.discard(None)
    return out


def equivalent(a: str | None, b: str | None) -> bool:
    """Same meaning, ignoring formatting: whitespace, case-free tokens, number/date/bool styles."""
    if is_null(a) or is_null(b):
        return is_null(a) and is_null(b)
    ba, bb = bool_value(a), bool_value(b)
    if ba is not None and bb is not None:
        return ba == bb
    na, nb = num_value(a), num_value(b)
    if na is not None and nb is not None:
        return na == nb
    da, db = date_candidates(a), date_candidates(b)
    if da and db:
        return bool(da & db)
    return canon_text(a) == canon_text(b)


def clean_matches(kind: str, out: str | None, expected: str | None) -> bool:
    """Is the cell after cleaning the expected clean form for this value kind?"""
    if expected is None or expected == "":
        return is_null(out)
    if is_null(out):
        return False
    if kind == "num":
        return num_value(out) is not None and num_value(out) == num_value(expected)
    if kind == "bool":
        return bool_value(out) is not None and bool_value(out) == bool_value(expected)
    if kind == "date":
        return out.strip() == expected.strip() or bool(date_candidates(out) & date_candidates(expected))
    return canon_text(out) == canon_text(expected)


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def strict_fixed(out: str | None, expected: str | None) -> bool:
    """Fixed correctly: the cell holds the expected value AND is written in the standard form
    (real empty cell, plain number, ISO date, true/false, tidy text). No partial credit."""
    if expected is None or expected == "":
        return out is None or out == ""
    if out is None or out == "":
        return False
    if _ISO_DATE_RE.match(expected):
        return bool(_ISO_RE.match(out)) and out[:10] == expected[:10]
    if num_value(expected) is not None:
        return bool(_NUM_RE.match(out)) and float(out) == num_value(expected)
    if bool_value(expected) is not None:
        return out in ("true", "false") and out == bool_value(expected)
    # Same text (curly or straight quotes both accepted) and written tidily.
    return canon_text(out) == canon_text(expected) and out == " ".join(out.split())


def _looks_snake(name: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9_]*$", name))


# ---------------------------------------------------------------- per-file evaluation

def _gt_for(fname: str, rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["file"] == fname]


def _evaluate_file(fname: str, gt: list[dict], samples: Path = SAMPLES) -> dict:
    path = samples / fname
    profile = pipeline.profile(path)
    plan = pipeline.build_plan(profile, Decisions(approved=[p.id for p in profile.proposals]))
    ptype = {c.name: c.inferred_type for c in profile.columns}
    issues = {c.name: {i.code for i in c.issues} for c in profile.columns}
    listed: dict[str, set[str]] = defaultdict(set)          # column -> values shown as "left alone"
    for prop in profile.proposals:
        if prop.column:
            listed[prop.column].update(x.value for x in prop.left_alone)

    loaded = _ingest.ingest(path)
    df = loaded.df
    src_names = loaded.source_names
    src2df: dict[str, str] = {}
    for col in df.columns:
        if col != ROW_ID:
            src2df.setdefault(src_names.get(col, col), col)
    tidy_of: dict[str, str] = {}
    for step in plan.steps:
        if step.rule_id == "normalize_headers":
            tidy_of.update(step.params["mapping"])
    input_rows = df.to_dicts()
    input_ids = [int(r[ROW_ID]) for r in input_rows]
    inputs = {int(r[ROW_ID]): r for r in input_rows}

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        result = pipeline.clean(path, plan, out, str(uuid.uuid4()))
        with open(out / "changelog.csv", encoding="utf-8", newline="") as fh:
            log = list(csv.DictReader(fh))
        with open(out / "clean.csv", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            out_header = list(reader.fieldnames or [])
            out_rows = list(reader)

    removed = {int(r["row_id"]) for r in log if r["change_type"] == "row_removed"}
    changed_cells = {(int(r["row_id"]), r["column"]) for r in log
                     if r["change_type"] == "cell" and r["row_id"]}
    removed_cols = {r["column"] for r in log if r["change_type"] == "column_removed"}
    out_ids = [rid for rid in input_ids if rid not in removed]
    if len(out_ids) != len(out_rows):
        raise RuntimeError(f"{fname}: {len(out_ids)} surviving input rows but {len(out_rows)} output rows")
    out_by_id = dict(zip(out_ids, out_rows))
    out_cols = set(out_header)
    header_ok = bool(out_header) and len(set(out_header)) == len(out_header) and all(
        _looks_snake(h) for h in out_header)

    def tidy(df_col: str) -> str:
        return tidy_of.get(df_col, df_col)

    # --- classify each ground-truth entry
    cell_keys: dict[tuple[int, str], dict] = {}
    entries = []
    for e in gt:
        row, col, et = int(e["row"]), e["column"], e["error_type"]
        item = {"file": fname, "row": row, "column": col, "error_type": et,
                "original": e["original_value"], "injected": e["injected_value"],
                "status": None, "method": None, "rule": None, "tidy": None, "input_ok": None}
        if row == 0:
            if et in OUT_OF_SCOPE:
                item.update(status="out_of_scope", method=OUT_OF_SCOPE[et])
            elif et in STRUCTURAL and STRUCTURAL[et][1] == "header":
                item.update(rule=STRUCTURAL[et][0], status="fixed" if header_ok else "missed",
                            method="all output headers unique snake_case")
            elif et == "empty_column":
                df_col = src2df.get(col)
                t = tidy(df_col) if df_col else None
                item.update(rule="drop_empty_rows_and_columns", tidy=t,
                            status="fixed" if t in removed_cols else "missed",
                            method="column removed")
            else:
                item.update(status="unmatched", method="unknown structural type")
        elif col == "":
            item["rule"] = ROW_LEVEL.get(et)
            if et in NOT_FIXABLE:
                item.update(status="not_fixable", method=NOT_FIXABLE[et])
            else:
                if row in removed:
                    item.update(status="fixed", method="row removed")
                else:
                    item.update(status="missed", method="row kept: no identical row after cleaning")
        else:
            df_col = src2df.get(col)
            if df_col is None:
                item.update(status="unmatched", method=f"no input column for header {col!r}")
            else:
                t = tidy(df_col)
                item["tidy"] = t
                cell_keys[(row, t)] = item
                item["input_ok"] = _input_matches(inputs.get(row, {}).get(df_col), e)
                _judge_cell(item, et, row, t, removed, out_by_id, out_cols, ptype)
        _judge_all(item, et, row, removed, out_by_id, out_cols, changed_cells, listed, issues, inputs, src2df)
        entries.append(item)

    # --- damaged cells: kept rows and columns, no injected error on the cell
    damaged = []
    compared = 0
    kept_cols = [(c, tidy(c)) for c in df.columns if c != ROW_ID and tidy(c) in out_cols]
    rule_by_cell: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for r in log:
        if r["change_type"] == "cell" and r["row_id"]:
            rule_by_cell[(int(r["row_id"]), r["column"])].append(r)
    for pos, rid in enumerate(out_ids):
        for df_col, t in kept_cols:
            if (rid, t) in cell_keys:
                continue
            before = inputs[rid].get(df_col)
            after = out_rows[pos].get(t)
            compared += 1
            if not equivalent(before, after):
                changed_by = [c["rule_id"] for c in rule_by_cell.get((rid, t), [])]
                damaged.append({"file": fname, "row": rid, "column": t,
                                "input": before, "output": after, "changed_by": changed_by})

    # --- precision: change-log records
    rule_stats: dict[str, Counter] = defaultdict(Counter)
    gt_removed_rows = {int(e["row"]) for e in gt if e["column"] == "" and int(e["row"]) > 0}
    gt_empty_cols = {tidy(src2df[e["column"]]) for e in gt if e["error_type"] == "empty_column"
                     and e["column"] in src2df}
    for r in log:
        rule = r["rule_id"]
        ct = r["change_type"]
        if ct == "cell":
            base = r["column"]
            if rule == "flag_outliers" and base.endswith(FLAG_SUFFIX):
                base = base[: -len(FLAG_SUFFIX)]
            rid = int(r["row_id"])
            if (rid, base) in cell_keys:
                rule_stats[rule]["on_injected"] += 1
            elif equivalent(r["old_value"], r["new_value"]):
                rule_stats[rule]["neutral"] += 1
            else:
                rule_stats[rule]["false_positive"] += 1
                fp_examples.append({"file": fname, "row": rid, "column": base, "rule": rule,
                                    "old": r["old_value"], "new": r["new_value"]})
        elif ct == "row_removed":
            key = "row_correct" if int(r["row_id"]) in gt_removed_rows else "row_wrong"
            rule_stats[rule][key] += 1
        elif ct == "column_removed":
            key = "row_correct" if r["column"] in gt_empty_cols else "row_wrong"
            rule_stats[rule][key] += 1

    # --- engine's own quality scores
    before = result.before.model_dump()
    after = result.after.model_dump()
    lift = {d: round(after[d] - before[d], 1) for d in DIMENSIONS}

    # --- sanity: did the injected values land on the rows we think they did
    checked = [e for e in entries if e["input_ok"] is not None]
    alignment = {"checked": len(checked), "matched": sum(1 for e in checked if e["input_ok"])}

    return {
        "file": fname,
        "rows_before": result.summary.rows_before,
        "rows_after": result.summary.rows_after,
        "quality_before": before,
        "quality_after": after,
        "lift": lift,
        "entries": entries,
        "damaged": damaged,
        "rule_stats": {k: dict(v) for k, v in rule_stats.items()},
        "alignment": alignment,
        "cells_compared": compared,
        "missed": [e for e in entries if e["status"] == "missed"],
        "fp_examples": [x for x in fp_examples if x["file"] == fname],
    }


fp_examples: list[dict] = []


def _judge_all(item, et, row, removed, out_by_id, out_cols, changed_cells, listed, issues, inputs, src2df) -> None:
    """The M6 view over ALL injected errors: was it fixed correctly, and if not, was it at least
    detected (the engine changed, flagged or listed the cell, or named the problem for the column)?

    item["noop"]: the injection changed nothing (original == injected), so it is not an error.
    item["fixed_all"]: fixed correctly (strict_fixed, row/column removed, outlier flagged, or a
    reading problem handled at ingest).
    item["detect"]: "fixed" | "cell" | "column" | "none".
    """
    t = item["tidy"]
    item["noop"] = row > 0 and item["column"] != "" and item["original"] == item["injected"]
    if row == 0 or item["column"] == "":                     # structural and row-level
        fixed = item["status"] in ("fixed", "out_of_scope")
        item.update(fixed_all=fixed, detect="fixed" if fixed else "none")
        return
    if t is None:
        item.update(fixed_all=False, detect="none")
        return
    if row in removed:
        item.update(fixed_all=True, detect="fixed")
        return
    out = out_by_id[row].get(t)
    if et == "outlier":
        fixed = (t + FLAG_SUFFIX) in out_cols and out_by_id[row].get(t + FLAG_SUFFIX) == "true"
    else:
        expected = None if et in EXPECT_NULL else item["original"]
        fixed = strict_fixed(out, expected)
    if fixed and et == "ambiguous_date":
        # Right only because "approve everything" keeps the default day/month order and the
        # generator happens to use the same one. The engine cannot know; the user must choose.
        item.update(fixed_all=False, detect="cell", lucky=True)
        return
    if fixed:
        item.update(fixed_all=True, detect="fixed")
        return
    raw = inputs.get(row, {}).get(src2df.get(item["column"]))
    shown = raw is not None and (raw in listed[t] or canon_text(raw) in listed[t])
    if (row, t) in changed_cells or shown:
        detect = "cell"
    elif ISSUE_FOR.get(et) in issues.get(t, ()):
        detect = "column"
    else:
        detect = "none"
    item.update(fixed_all=False, detect=detect)


def _input_matches(raw: str | None, e: dict) -> bool:
    """The injected value should be what the messy file holds in that cell."""
    injected = e["injected_value"]
    if e["error_type"] == "outlier":
        return raw is not None and num_value(raw) is not None
    if is_null(injected):
        return is_null(raw)
    return raw == injected or equivalent(raw, injected)


def _judge_cell(item, et, row, t, removed, out_by_id, out_cols, ptype) -> None:
    if et in NOT_FIXABLE:
        item.update(status="not_fixable", method=NOT_FIXABLE[et], rule=None)
        return
    if et in OUT_OF_SCOPE:
        item.update(status="out_of_scope", method=OUT_OF_SCOPE[et])
        return
    if et not in FIXABLE:
        item.update(status="unmatched", method="error type has no rule mapping")
        return
    rule, kind = FIXABLE[et]
    item["rule"] = rule
    if et == "case_variant" and ptype.get(t) != "category":
        item.update(status="not_fixable", method="standardize_categories clusters category columns only")
        return
    if et == "typo_category" and len(item["original"]) < 5:
        item.update(status="not_fixable", method="short-value guard: under 5 characters, no safe merge")
        return
    if row in removed:
        item.update(status="fixed", method="row removed")
        return
    if et == "outlier":
        flag_col = t + FLAG_SUFFIX
        flagged = flag_col in out_cols and out_by_id[row].get(flag_col) == "true"
        item.update(status="fixed" if flagged else "missed",
                    method="flagged by flag_outliers" if flagged else "not flagged: value inside the IQR fence")
        return
    expected = None if kind == "null" or item["original"] == "" else item["original"]
    value = out_by_id[row].get(t)
    ok = clean_matches("text" if kind == "flag" else kind, value, expected)
    item.update(status="fixed" if ok else "missed",
                method="value matches expected" if ok else f"output {value!r}, expected {expected!r}")


# ---------------------------------------------------------------- aggregation

def _aggregate(per_file: list[dict]) -> dict:
    entries = [e for f in per_file for e in f["entries"]]
    by_type: dict[str, Counter] = defaultdict(Counter)
    for e in entries:
        by_type[e["error_type"]][e["status"]] += 1
    fixed = sum(1 for e in entries if e["status"] == "fixed")
    missed = sum(1 for e in entries if e["status"] == "missed")
    scored = fixed + missed

    rule_rows = {}
    for rule in RULE_ORDER:
        claimed = [e for e in entries if e["rule"] == rule and e["status"] in ("fixed", "missed")]
        stats: Counter = Counter()
        for f in per_file:
            stats.update(f["rule_stats"].get(rule, {}))
        on_inj = stats["on_injected"]
        fp = stats["false_positive"]
        rule_rows[rule] = {
            "injected": len(claimed),
            "fixed": sum(1 for e in claimed if e["status"] == "fixed"),
            "recall": _pct(sum(1 for e in claimed if e["status"] == "fixed"), len(claimed)),
            "cell_changes_on_injected": on_inj,
            "neutral": stats["neutral"],
            "false_positives": fp,
            "precision": _pct(on_inj, on_inj + fp),
            "row_or_column_correct": stats["row_correct"],
            "row_or_column_wrong": stats["row_wrong"],
        }

    not_fixable = defaultdict(lambda: {"count": 0, "no_op": 0, "reason": ""})
    for e in entries:
        if e["status"] == "not_fixable":
            slot = not_fixable[e["error_type"]]
            slot["count"] += 1
            slot["no_op"] += int(e["original"] == e["injected"])
            slot["reason"] = e["method"]

    real = [e for e in entries if not e["noop"]]
    by_type_all: dict[str, Counter] = defaultdict(Counter)
    for e in real:
        by_type_all[e["error_type"]][e["detect"]] += 1
    n_fixed = sum(1 for e in real if e["fixed_all"])
    n_cell = sum(1 for e in real if e["detect"] == "cell")
    n_col = sum(1 for e in real if e["detect"] == "column")
    all_errors = {
        "injected": len(real),
        "noop_injections": len(entries) - len(real),
        "fixed": n_fixed,
        "fix_recall": _pct(n_fixed, len(real)),
        "detected_cell_level": n_fixed + n_cell,
        "detected": n_fixed + n_cell + n_col,
        "detection_recall": _pct(n_fixed + n_cell + n_col, len(real)),
        "detection_recall_cell_level": _pct(n_fixed + n_cell, len(real)),
        "by_error_type": {k: dict(v) for k, v in sorted(by_type_all.items())},
    }
    lucky = sum(1 for e in real if e.get("lucky"))
    all_errors["ambiguous_dates_right_by_default_order"] = lucky
    all_errors["fix_recall_if_date_order_is_right"] = _pct(n_fixed + lucky, len(real))
    all_errors["fix_recall_counting_noops_as_errors"] = _pct(n_fixed, len(entries))

    return {
        "all_errors": all_errors,
        "headline": {"scored": scored, "fixed": fixed, "missed": missed,
                     "recall": _pct(fixed, scored),
                     "not_fixable": sum(v["count"] for v in not_fixable.values()),
                     "out_of_scope": sum(1 for e in entries if e["status"] == "out_of_scope"),
                     "unmatched": sum(1 for e in entries if e["status"] == "unmatched")},
        "by_error_type": {k: dict(v) for k, v in sorted(by_type.items())},
        "rules": rule_rows,
        "not_fixable": dict(sorted(not_fixable.items())),
        "out_of_scope": dict(sorted(Counter(e["error_type"] for e in entries
                                            if e["status"] == "out_of_scope").items())),
    }


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


# ---------------------------------------------------------------- rendering

def _md(headers: list[str], rows: list[list]) -> str:
    def cell(x):
        if x is None:
            return "n/a"
        return str(x).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(cell(x) for x in r) + " |" for r in rows]
    return "\n".join(lines)


def _render(results: dict) -> str:
    h = results["headline"]
    files = results["files"]
    parts = ["# Evaluation results", "",
             "Generated by `evaluation/run_evaluation.py`. Every proposal is approved. "
             "The chicago file has no ground truth; see `evaluation/CHICAGO_HANDCHECK.md`.", ""]
    parts += _render_all_errors(results)
    parts += ["# Tuning batch in detail (older view: recall on fixable errors only)", "",
              "The sections below are for the tuning batch and count only the error types a rule is "
              "meant to fix. They are kept for continuity with M5; the numbers above are the honest ones.", ""]

    parts += ["## Headline per file", ""]
    rows = []
    for name, f in files.items():
        hh = f["headline"]
        rows.append([name, hh["scored"], hh["fixed"], hh["recall"],
                     f["precision"], f["damaged_cells"],
                     f"{f['quality_before']['overall']} -> {f['quality_after']['overall']}"])
    rows.append(["**All files**", h["scored"], h["fixed"], h["recall"],
                 results["precision"], results["damaged_cells"]["total"],
                 ""])
    parts += [_md(["File", "Scored injected errors", "Fixed", "Recall %", "Precision %",
                   "Damaged cells", "Overall quality before -> after"], rows), ""]
    parts += ["Recall = fixed / scored, where scored excludes not-fixable-by-design and out-of-scope "
              "errors. Precision = changes on injected cells / (changes on injected cells + "
              "false positives), neutral changes excluded. Scored = fixable errors only.", ""]

    parts += ["## Per-dimension lift (engine's own scores)", ""]
    rows = []
    for name, f in files.items():
        for d in DIMENSIONS:
            rows.append([name, d, f["quality_before"][d], f["quality_after"][d], f["lift"][d]])
    parts += [_md(["File", "Dimension", "Before", "After", "Lift"], rows), ""]

    parts += ["## Recall by error type", ""]
    rows = []
    for et, c in results["by_error_type"].items():
        claim = _claim(et)
        scored = c.get("fixed", 0) + c.get("missed", 0)
        rows.append([et, claim, c.get("fixed", 0), c.get("missed", 0),
                     _pct(c.get("fixed", 0), scored) if scored else "not scored",
                     c.get("not_fixable", 0), c.get("out_of_scope", 0), c.get("unmatched", 0)])
    parts += [_md(["Error type", "Claimed by", "Fixed", "Missed", "Recall %", "Not fixable",
                   "Out of scope", "Unmatched"], rows), ""]

    parts += ["## Precision and recall by rule", ""]
    rows = []
    for rule, r in results["rules"].items():
        rows.append([rule, r["injected"], r["fixed"], r["recall"], r["cell_changes_on_injected"],
                     r["neutral"], r["false_positives"], r["precision"],
                     f"{r['row_or_column_correct']} / {r['row_or_column_wrong']}"])
    parts += [_md(["Rule", "Injected (claimed)", "Fixed", "Recall %", "Changes on injected cells",
                   "Neutral", "False positives", "Precision %", "Row/column removals right / wrong"],
                  rows), "",
              "Row/column removals are not data cells, so they are shown separately. "
              "Changes on the *_outlier_flag column count against the base column.", ""]

    parts += ["## Damaged cells", ""]
    dc = results["damaged_cells"]
    parts += [f"Cells with no injected error whose value after cleaning differs in meaning from the "
              f"input. Total: **{dc['total']}** (must be 0). Cells compared: {dc['cells_compared']}.", ""]
    if dc["examples"]:
        rows = [[x["file"], x["row"], x["column"], x["input"], x["output"], ", ".join(x["changed_by"])]
                for x in dc["examples"]]
        parts += [_md(["File", "Row", "Column", "Input", "Output", "Changed by"], rows), ""]

    parts += ["## Missed fixable errors", "",
              "Each row is a fixable injected error the engine did not fix (no change is made to "
              "the ground truth). Causes are in the last column.", ""]
    if results["missed"]:
        rows = [[m["file"], m["row"], m["column"], m["error_type"], m["original"], m["injected"],
                 m["method"]] for m in results["missed"]]
        parts += [_md(["File", "Row", "Column", "Error type", "Original", "Injected", "Why missed"],
                      rows), ""]
    else:
        parts += ["None.", ""]

    parts += ["## Not fixable by design (excluded from headline recall)", ""]
    rows = [[k, v["count"], v["no_op"], v["reason"]] for k, v in results["not_fixable"].items()]
    parts += [_md(["Error type", "Count", "No-op injections (original = injected)", "Reason"], rows), ""]
    if results["out_of_scope"]:
        rows = [[k, v] for k, v in results["out_of_scope"].items()]
        parts += ["Structural errors handled by file reading, not scored:", "",
                  _md(["Error type", "Count"], rows), ""]

    parts += ["## Alignment check", "",
              "For each injected cell, the messy file must hold the injected value at the stated "
              "row and column. Mismatches mean the row or column mapping is off.", ""]
    rows = [[name, f["alignment"]["checked"], f["alignment"]["matched"]] for name, f in files.items()]
    parts += [_md(["File", "Checked", "Matched"], rows), ""]
    return "\n".join(parts)


TIMING_NOTE = [
    "## Timing and memory (M6 step 7, see TIMING.md)", "",
    _md(["File", "Profile", "Clean", "Peak memory", "Excel on first download"],
        [["100,000 rows, 5.4 MB", "about 12 s", "about 12 s", "about 0.46 GB", "about 8 s"],
         ["872,050 rows, 47.5 MB", "about 60 to 80 s", "about 90 s", "about 1.8 GB", "about 70 to 120 s"]]), "",
    "Measured on the development machine, whose speed varies between runs. Clean no longer writes "
    "clean.xlsx; it is built on the first Excel download. Supported size: 50 MB locally, 4 MB on the live site.", "",
]


def _render_all_errors(results: dict) -> list[str]:
    parts = ["## Honest metrics: all injected errors", "",
             "- **Detection recall:** share of injected errors the engine fixed, changed, flagged, listed as "
             "\"left alone\", or named as a problem for that column in the profile.",
             "- **Fix recall:** share of injected errors that end up correct AND in the standard form "
             "(real empty cell, plain number, ISO date, true/false, tidy text). A deleted value cannot be "
             "restored, so missing values can be detected but never fixed.",
             "- Injections that changed nothing (original equals injected) are not errors and are left out.",
             "- **Ambiguous dates** (03/04/2024) are counted as detected, not fixed: the engine cannot know "
             "the order and asks the user. If the user picks the right order they are all fixed; that figure "
             "is in the last column.",
             "- The held-out batch uses a different seed and a file with region abbreviations the engine "
             "was never tuned on. It is the figure to quote.", ""]
    rows = []
    for label, r in (("**Held-out batch**", results["heldout"]), ("Tuning batch", results)):
        a = r["all_errors"]
        rows.append([label, a["injected"], a["detection_recall"], a["detection_recall_cell_level"],
                     a["fix_recall"], r["precision"], r["damaged_cells"]["total"],
                     a["fix_recall_if_date_order_is_right"]])
    parts += [_md(["Batch", "Injected errors", "Detection recall %", "of which cell-level %",
                   "Fix recall %", "Precision %", "Damaged cells",
                   "Fix recall % if the user picks the right date order"], rows), ""]
    a = results["all_errors"]
    parts += [f"For comparison with the M5 count of 3,057 entries: counting the {a['noop_injections']} "
              f"no-op injections of the tuning batch as unfixed errors would give "
              f"{a['fix_recall_counting_noops_as_errors']}%.", ""]
    for label, r in (("Held-out batch", results["heldout"]), ("Tuning batch", results)):
        parts += [f"### {label} per file", ""]
        rows = [[name, f["all_errors"]["injected"], f["all_errors"]["detection_recall"],
                 f["all_errors"]["fix_recall"], f["precision"], f["damaged_cells"],
                 f"{f['quality_before']['overall']} -> {f['quality_after']['overall']}"]
                for name, f in r["files"].items()]
        parts += [_md(["File", "Injected errors", "Detection recall %", "Fix recall %", "Precision %",
                       "Damaged cells", "Quality before -> after"], rows), ""]
    parts += ["### Held-out batch by error type", ""]
    rows = []
    for et, c in results["heldout"]["all_errors"]["by_error_type"].items():
        n = sum(c.values())
        rows.append([et, n, c.get("fixed", 0), c.get("cell", 0), c.get("column", 0), c.get("none", 0),
                     _pct(c.get("fixed", 0), n)])
    parts += [_md(["Error type", "Injected", "Fixed", "Detected at the cell, not fixed",
                   "Detected for the column only", "Not detected", "Fix recall %"], rows), ""]
    h = results["heldout"]
    if h["missed"]:
        parts += ["### Held-out batch: fixable errors that were missed", ""]
        rows = [[m["file"], m["row"], m["column"], m["error_type"], m["original"], m["injected"], m["method"]]
                for m in h["missed"][:40]]
        parts += [_md(["File", "Row", "Column", "Error type", "Original", "Injected", "Why missed"], rows), ""]
    if h["damaged_cells"]["examples"]:
        parts += ["### Held-out batch: damaged cells", ""]
        rows = [[x["file"], x["row"], x["column"], x["input"], x["output"], ", ".join(x["changed_by"])]
                for x in h["damaged_cells"]["examples"]]
        parts += [_md(["File", "Row", "Column", "Input", "Output", "Changed by"], rows), ""]
    return parts + TIMING_NOTE


def _claim(et: str) -> str:
    if et in FIXABLE:
        return FIXABLE[et][0]
    if et in STRUCTURAL:
        return STRUCTURAL[et][0]
    if et in ROW_LEVEL:
        return ROW_LEVEL[et]
    return "none (not fixable by design)" if et in NOT_FIXABLE else "ingest"


# ---------------------------------------------------------------- entry point

def evaluate(samples: Path = SAMPLES, file_names: list[str] = FILES) -> dict:
    """Evaluate one batch of sample files against the ground_truth.csv in the same folder."""
    with open(samples / "ground_truth.csv", encoding="utf-8", newline="") as fh:
        gt = list(csv.DictReader(fh))

    fp_examples.clear()
    per_file = [_evaluate_file(f, _gt_for(f, gt), samples) for f in file_names]
    agg = _aggregate(per_file)

    files = {}
    for f in per_file:
        scored = [e for e in f["entries"] if e["status"] in ("fixed", "missed")]
        fixed = sum(1 for e in scored if e["status"] == "fixed")
        neutral = f["rule_stats"]
        on_inj = sum(v.get("on_injected", 0) for v in neutral.values())
        fp = sum(v.get("false_positive", 0) for v in neutral.values())
        real = [e for e in f["entries"] if not e["noop"]]
        files[f["file"]] = {
            "all_errors": {
                "injected": len(real),
                "fixed": sum(1 for e in real if e["fixed_all"]),
                "fix_recall": _pct(sum(1 for e in real if e["fixed_all"]), len(real)),
                "detection_recall": _pct(sum(1 for e in real if e["detect"] != "none"), len(real)),
            },
            "headline": {"scored": len(scored), "fixed": fixed, "missed": len(scored) - fixed,
                         "recall": _pct(fixed, len(scored))},
            "precision": _pct(on_inj, on_inj + fp),
            "rows_before": f["rows_before"], "rows_after": f["rows_after"],
            "quality_before": f["quality_before"], "quality_after": f["quality_after"],
            "lift": f["lift"], "alignment": f["alignment"],
            "damaged_cells": len(f["damaged"]),
            "cells_compared": f["cells_compared"],
            "rule_stats": f["rule_stats"],
        }

    all_on = sum(s.get("on_injected", 0) for f in per_file for s in f["rule_stats"].values())
    all_fp = sum(s.get("false_positive", 0) for f in per_file for s in f["rule_stats"].values())
    damaged = [d for f in per_file for d in f["damaged"]]
    results = {
        "all_errors": agg["all_errors"],
        "headline": agg["headline"],
        "precision": _pct(all_on, all_on + all_fp),
        "neutral_changes": sum(s.get("neutral", 0) for f in per_file for s in f["rule_stats"].values()),
        "false_positive_changes": all_fp,
        "files": files,
        "by_error_type": agg["by_error_type"],
        "rules": agg["rules"],
        "not_fixable": agg["not_fixable"],
        "out_of_scope": agg["out_of_scope"],
        "damaged_cells": {"total": len(damaged), "cells_compared": sum(f["cells_compared"] for f in per_file),
                          "examples": damaged[:25]},
        "missed": [{k: e[k] for k in ("file", "row", "column", "error_type", "original", "injected", "method")}
                   for f in per_file for e in f["missed"]],
        "false_positive_examples": list(fp_examples[:25]),
    }
    return results


def run(out_dir: Path | None = None) -> dict:
    """Evaluate both batches. Writes RESULTS.md and results.json into out_dir (default: evaluation/).
    Returns the tuning-batch results, with the held-out batch under "heldout"."""
    out_dir = Path(out_dir) if out_dir else HERE
    results = evaluate(SAMPLES, FILES)
    results["heldout"] = evaluate(HELDOUT, HELDOUT_FILES)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "RESULTS.md").write_text(_render(results), encoding="utf-8")
    return results


def main() -> int:
    results = run()
    for label, r in (("Held-out", results["heldout"]), ("Tuning", results)):
        a = r["all_errors"]
        print(f"{label}: detection recall {a['detection_recall']}%, fix recall {a['fix_recall']}% "
              f"({a['fixed']}/{a['injected']} injected errors), precision {r['precision']}%, "
              f"damaged cells {r['damaged_cells']['total']}")
    h = results["headline"]
    print(f"Recall {h['recall']}% ({h['fixed']}/{h['scored']} fixable injected errors)")
    print(f"Precision {results['precision']}% (neutral changes excluded)")
    print(f"Damaged cells {results['damaged_cells']['total']}")
    print(f"Wrote {HERE / 'RESULTS.md'} and {HERE / 'results.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
