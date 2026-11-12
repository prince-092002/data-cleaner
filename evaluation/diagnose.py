"""Classify the missed duplicate rows and missed outliers from the evaluation (M6 step 1).

    .venv/Scripts/python evaluation/diagnose.py

Read-only. Prints one line per missed item with its category, then the counts.
Duplicates:  (i) exact copy in the raw file the rule missed, (ii) copy only after cleaning,
             (iii) not a duplicate of any earlier row, so the answer key is wrong.
             "key labels the wrong copy" is a sub-case of (iii): the copy exists, but it sits
             above the row it was copied from, so the rule (keep the first) removes the other one.
Outliers:    (i) value inside the IQR fence, (ii) method misses it, (iii) engine bug.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_evaluation as ev  # noqa: E402
from engine import ingest  # noqa: E402


def _rows(fname: str) -> dict[int, tuple]:
    df = ingest.ingest(ev.SAMPLES / fname).df
    cols = [c for c in df.columns if c != ev.ROW_ID]
    return {int(r[ev.ROW_ID]): tuple(r[c] for c in cols) for r in df.to_dicts()}


def duplicates(missed: list[dict]) -> list[tuple[str, int, str, str]]:
    out = []
    cache: dict[str, dict[int, tuple]] = {}
    canon = lambda row: tuple(ev.canon_text(v) if v is not None and not ev.is_null(v) else None for v in row)  # noqa: E731
    for m in missed:
        if m["error_type"] != "duplicate_row":
            continue
        rows = cache.setdefault(m["file"], _rows(m["file"]))
        rid, me = m["row"], rows[m["row"]]
        same = sorted(k for k, v in rows.items() if v == me and k != rid)
        if any(k < rid for k in same):
            cat, why = "i", f"identical to earlier row {min(same)} in raw file, rule did not remove it"
        elif same:
            cat, why = "iii", (f"identical to row {same[0]} which sits BELOW it; the rule keeps the first "
                               f"occurrence ({rid}) and removes {same[0]}; key labels the wrong copy")
        elif any(canon(v) == canon(me) for k, v in rows.items() if k < rid):
            cat, why = "ii", "identical to an earlier row only after trimming/null tokens"
        else:
            cat, why = "iii", "no identical row anywhere in the raw file"
        out.append((m["file"], rid, cat, why))
    return out


def outliers(missed: list[dict]) -> list[tuple[str, int, str, str]]:
    out = []
    for m in missed:
        if m["error_type"] != "outlier":
            continue
        df = ingest.ingest(ev.SAMPLES / m["file"]).df
        vals = sorted(x for x in (ev.num_value(v) for v in df[m["column"]].to_list() if v is not None)
                      if x is not None)
        n = len(vals)
        q1, q3 = _quantile(vals, 0.25), _quantile(vals, 0.75)
        lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        v = ev.num_value(m["injected"])
        inside = lo <= v <= hi
        cat = "i" if inside else "iii"
        why = (f"value {v:g}; fence {lo:g} .. {hi:g} (Q1 {q1:g}, Q3 {q3:g}, n={n}); "
               f"min of the rest {vals[1] if vals[0] == v else vals[0]:g}")
        out.append((m["file"], m["row"], cat, why))
    return out


def _quantile(vals: list[float], p: float) -> float:
    """Linear interpolation, same as numpy/polars 'linear'."""
    pos = p * (len(vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def main() -> int:
    results = ev.run(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp()))
    for title, items in (("Duplicates", duplicates(results["missed"])), ("Outliers", outliers(results["missed"]))):
        print(f"\n{title}")
        for f, r, cat, why in items:
            print(f"  ({cat}) {f} row {r}: {why}")
        counts = {c: sum(1 for x in items if x[2] == c) for c in ("i", "ii", "iii")}
        print(f"  counts: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
