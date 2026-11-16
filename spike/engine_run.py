"""Throwaway spike: run the engine end to end (profile -> approve all -> clean) and summarise.
Shared by the Vercel function and the local comparison run, so both summarise the same way."""
import csv
import hashlib
import time
import uuid
from collections import Counter
from pathlib import Path


def peak_rss_mb() -> float | None:
    try:
        import resource  # Linux only; ru_maxrss is in KiB there
    except ImportError:
        return None
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def run(path: Path, out_dir: Path) -> dict:
    t0 = time.perf_counter()
    from engine import pipeline
    from engine.models import Decisions
    t_import = time.perf_counter() - t0

    t = time.perf_counter()
    prof = pipeline.profile(path)
    t_profile = time.perf_counter() - t
    # approve every proposal, the same way evaluation/run_evaluation.py does
    plan = pipeline.build_plan(prof, Decisions(approved=[p.id for p in prof.proposals]))
    t = time.perf_counter()
    result = pipeline.clean(path, plan, out_dir, str(uuid.uuid4()))
    t_clean = time.perf_counter() - t

    clean_csv = out_dir / result.files.get("clean.csv", "clean.csv")
    data = clean_csv.read_bytes()
    with clean_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        columns = next(reader)
        rows = list(reader)
    region_col = next((i for i, c in enumerate(columns) if c.lower() == "region"), None)
    regions = dict(Counter(r[region_col] for r in rows)) if region_col is not None else None
    return {
        "import_s": round(t_import, 3),
        "profile_s": round(t_profile, 3),
        "clean_s": round(t_clean, 3),
        "proposals": len(prof.proposals),
        "plan_steps": len(plan.steps),
        "rows": len(rows),
        "columns": columns,
        "regions": regions,
        "clean_csv_sha256": hashlib.sha256(data).hexdigest(),
        "clean_csv_bytes": len(data),
        "score_before": result.before.overall,
        "score_after": result.after.overall,
        "summary": {k: v for k, v in result.summary.model_dump().items() if k != "by_rule"},
        "files": sorted(result.files),
        "peak_rss_mb": peak_rss_mb(),
    }
