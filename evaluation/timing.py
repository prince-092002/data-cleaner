"""Timing and peak memory of the cleaning pipeline on generated sales-like files.

    .venv/Scripts/python evaluation/timing.py --rows 100000
    .venv/Scripts/python evaluation/timing.py --size-mb 48
    .venv/Scripts/python evaluation/timing.py --rows 100000 --no-api --out-dir <folder>

The file has the same columns and messy-value mix as the sales sample (made by
sample_data/make_samples.py, make_sales), with the same duplicate and empty-row rates
(25 and 8 per 400 rows) and a fixed seed. No ground truth is written.

Each run times pipeline.profile and pipeline.clean (every proposal approved). Unless --no-api
is given, it also times the same work through the backend API (FastAPI TestClient: upload,
profile job, clean job, results).

Units: --size-mb uses decimal megabytes (48 MB = 48,000,000 bytes), which is under the 50 MB
limit read either as 50,000,000 bytes or as the 50 MiB (52,428,800 bytes) in backend/config.py.
Memory is reported in MiB (1 MiB = 1,048,576 bytes).

Peak memory: psutil when installed; otherwise the process working set (Windows, via ctypes
GetProcessMemoryInfo) or /proc/self/statm (Linux), sampled every 20 ms in a background thread.
A sampled peak can miss a spike shorter than 20 ms.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import random
import sys
import tempfile
import threading
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sample_data.make_samples import (  # noqa: E402
    SEED, _currency_tags, _mojibake_name, _name, _pick,
)
from engine import pipeline  # noqa: E402
from engine.models import Decisions  # noqa: E402

MIB = 1024 * 1024
MB = 1_000_000
HEADER = ["Order ID", " Customer Name ", "Order Date", "Amount (USD)", "Discount %",
          "Region", "Paid?", "ZIP Code", "Notes", "Unnamed"]
START = dt.date(2024, 1, 1)
NULL_TOKENS = {"", "na", "n/a", "null", "-", "?", "#n/a", "tbd"}   # CONTRACT section 1
DUP_PER_ROW = 25 / 400      # sample file: 25 duplicate rows in 400
EMPTY_PER_ROW = 8 / 400     # sample file: 8 empty rows in 400


# --------------------------------------------------------------------------- generator

def _base_row(rng: random.Random, i: int) -> list[str]:
    """One sales row. Option lists copied from make_samples.make_sales (error tags dropped)."""
    order_clean = f"ORD-{i:05d}"
    order_id = _pick(rng, [
        (order_clean, 60), ("", 14), (f" {order_clean}", 10), ("N/A", 4), ("TBD", 3),
    ], order_clean)[0]
    d = START + dt.timedelta(days=rng.randrange(0, 360))
    date = _pick(rng, [
        (d.isoformat(), 48), (d.strftime("%d/%m/%Y"), 14), (f"{d.day} {d.strftime('%b')} {d.year}", 4),
        (f"{d.year}/{d.month:02d}/{d.day:02d}", 3), ("TBD", 3), ("N/A", 3), ("", 9),
        ("soon", 3), ("31/02/2024", 2), ("99/99/9999", 1),
    ], d.isoformat())[0]
    amount = round(rng.uniform(20, 5000), 2)
    amount_txt = _pick(rng, [
        (f"{amount:.2f}", 45), (f"${amount:,.2f}", 15, _currency_tags(amount), None),
        (f"({amount:.2f})", 2), (f" {amount:.2f} ", 4), ("N/A", 5), ("TBD", 3), ("", 10),
        ("abc", 3), ("12..5", 1), ("?", 2),
    ], f"{amount:.2f}")[0]
    disc = rng.choice([0, 5, 10, 15, 20])
    discount = _pick(rng, [
        (str(disc), 45), (f"{disc}%", 15), ("", 16), ("N/A", 8), ("TBD", 5), ("?", 5),
    ], str(disc))[0]
    clean_region = rng.choice(["North", "South", "East", "West"])
    region = _pick(rng, [
        (clean_region, 50), ("north", 3), ("NORTH", 3), ("Nrth", 2), ("South ", 4), ("Sout", 2),
        ("  east", 3), ("EAST", 3), ("Wset", 2), ("west ", 3), ("N/A", 3), ("", 4), ("?", 2),
    ], clean_region)[0]
    paid = _pick(rng, [
        ("Yes", 26), ("No", 20), ("Y", 6), ("N", 5), ("TRUE", 4), ("false", 4), ("yes", 3),
        ("no", 2), ("", 6), ("N/A", 4), ("?", 4),
    ], None)[0]
    name = _name(rng)
    moj = _mojibake_name(name)
    name = _pick(rng, [
        (name, 48), (f"  {name}", 4), (name.upper(), 4), (name.replace(" ", "  "), 5),
        (f"{name} ", 4), (name.lower(), 2), (moj, 6 if moj != name else 0), ("", 10),
        ("unknown", 3),
    ], name)[0]
    notes = _pick(rng, [
        ("", 68), ("-", 6), ("?", 4), ("N/A", 6), ("TBD", 3), ("priority", 5), ("gift wrap", 5),
        ("gift  wrap", 3),
    ], "")[0]
    zip_clean = f"{rng.randrange(1000, 99999):05d}"
    zip_code = _pick(rng, [
        (zip_clean, 55), ("", 18), (f" {zip_clean}", 8), ("N/A", 6), ("?", 6),
    ], zip_clean)[0]
    return [order_id, name, date, amount_txt, discount, region, paid, zip_code, notes, ""]


def _line(row: list[str]) -> str:
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator="\n").writerow(row)
    return buf.getvalue()


def _lines(rows: int, seed: int) -> tuple[list[str], int]:
    """Shuffled data lines (no header), and the number of rows left after cleaning."""
    rng = random.Random(seed)
    n_dup = round(rows * DUP_PER_ROW)
    n_empty = round(rows * EMPTY_PER_ROW)
    n_base = rows - n_dup - n_empty
    base: list[str] = []
    all_null = 0
    for i in range(1, n_base + 1):
        row = _base_row(rng, i)
        # drop_empty_rows_and_columns removes rows where every cell is a null token
        if all(v.strip().lower() in NULL_TOKENS for v in row):
            all_null += 1
        base.append(_line(row))
    empty = _line([""] * len(HEADER))
    lines = base + [rng.choice(base) for _ in range(n_dup)] + [empty] * n_empty
    rng.shuffle(lines)
    return lines, n_base - all_null


@dataclass
class GeneratedFile:
    path: Path
    rows: int           # data rows in the file (duplicates and empty rows included)
    clean_rows: int     # expected rows after cleaning: minus empty rows and exact copies. Sparse rows can
                        # also become identical after null tokens are cleared, so the engine may remove a few more.
    size_bytes: int


def write_messy_sales(out_path: Path, rows: int, seed: int = SEED) -> GeneratedFile:
    """Write a messy sales CSV with `rows` data rows (cp1252, semicolon-delimited, like the sample)."""
    out_path = Path(out_path)
    lines, clean_rows = _lines(rows, seed)
    with open(out_path, "w", encoding="cp1252", newline="") as fh:
        fh.write(_line(HEADER))
        fh.writelines(lines)
    return GeneratedFile(out_path, rows, clean_rows, out_path.stat().st_size)


def write_messy_sales_mb(out_path: Path, size_mb: float, seed: int = SEED) -> GeneratedFile:
    """Grow the row count until the file is within 2% under size_mb decimal megabytes."""
    target = size_mb * MB
    probe, _ = _lines(5000, seed)
    rows = int(target / (sum(len(line) for line in probe) / len(probe)))
    gen = write_messy_sales(out_path, rows, seed)
    for _ in range(3):
        if 0.98 * target <= gen.size_bytes <= target:
            break
        rows = int(rows * target / gen.size_bytes * (0.99 if gen.size_bytes > target else 1.0))
        gen = write_messy_sales(out_path, rows, seed)
    if gen.size_bytes > target:
        raise RuntimeError(f"could not fit {gen.rows} rows under {size_mb} MB")
    return gen


# --------------------------------------------------------------------------- memory

def _rss_reader():
    """Return (method name, function giving the current process resident memory in bytes)."""
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is not None:
        proc = psutil.Process()
        return "psutil", lambda: proc.memory_info().rss
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        handle = ctypes.windll.kernel32.GetCurrentProcess()

        def win_rss() -> int:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            get_info(handle, ctypes.byref(counters), counters.cb)
            return counters.WorkingSetSize

        return "ctypes GetProcessMemoryInfo (psutil not installed)", win_rss

    import os

    page = os.sysconf("SC_PAGE_SIZE")

    def proc_rss() -> int:
        with open("/proc/self/statm") as fh:
            return int(fh.read().split()[1]) * page

    return "/proc/self/statm (psutil not installed)", proc_rss


class PeakRss:
    """Samples resident memory every 20 ms in a background thread while the block runs."""

    def __init__(self, read, interval: float = 0.02):
        self._read = read
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak = 0

    def _run(self) -> None:
        while not self._stop.is_set():
            self.peak = max(self.peak, self._read())
            self._stop.wait(self._interval)

    def __enter__(self) -> "PeakRss":
        self.peak = self._read()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, self._read())


def _timed(fn, read):
    """Run fn and return (its result, wall-clock seconds, peak RSS bytes during the call)."""
    with PeakRss(read) as mem:
        t0 = time.perf_counter()
        value = fn()
        seconds = time.perf_counter() - t0
    return value, seconds, mem.peak


# --------------------------------------------------------------------------- measurements

def run_engine(src: Path, work_dir: Path, read) -> dict:
    """pipeline.profile, then build_plan with every proposal approved, then pipeline.clean."""
    run_id = str(uuid.uuid4())
    baseline = read()
    cache = work_dir / "cache"                       # like the backend: read-once cache per dataset
    profile, profile_s, profile_peak = _timed(lambda: pipeline.profile(src, cache_dir=cache), read)
    plan = pipeline.build_plan(profile, Decisions(approved=[p.id for p in profile.proposals]))
    result, clean_s, clean_peak = _timed(
        lambda: pipeline.clean(src, plan, work_dir, run_id, cache_dir=cache), read)
    return {
        "proposals": len(profile.proposals),
        "baseline_mib": round(baseline / MIB, 1),
        "profile_s": round(profile_s, 2),
        "clean_s": round(clean_s, 2),
        "total_s": round(profile_s + clean_s, 2),
        "peak_mib": round(max(profile_peak, clean_peak) / MIB, 1),
        "clean_rows": result.summary.rows_after,
    }


def _timed_call(fn):
    t0 = time.perf_counter()
    response = fn()
    return response, time.perf_counter() - t0


def _check_job(client, response) -> None:
    assert response.status_code == 202, response.text
    job = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "done", job.get("error")


def run_api(src: Path, storage: Path, read) -> dict:
    """The same work through the backend: upload, profile job, clean job (all approved), results."""
    from fastapi.testclient import TestClient

    from backend.config import Settings
    from backend.main import create_app

    with TestClient(create_app(Settings(storage_dir=storage))) as client, PeakRss(read) as mem:
        with open(src, "rb") as fh:
            upload, upload_s = _timed_call(
                lambda: client.post("/api/datasets", files={"file": (src.name, fh)}))
        assert upload.status_code == 201, upload.text
        ds = upload.json()["dataset_id"]

        profile_job, profile_s = _timed_call(lambda: client.post(f"/api/datasets/{ds}/profile", json={}))
        _check_job(client, profile_job)
        proposals = client.get(f"/api/datasets/{ds}/profile").json()["proposals"]

        clean_job, clean_s = _timed_call(
            lambda: client.post(f"/api/datasets/{ds}/clean", json={"approved": [p["id"] for p in proposals]}))
        _check_job(client, clean_job)

        results, results_s = _timed_call(lambda: client.get(f"/api/datasets/{ds}/results"))
        assert results.status_code == 200, results.text

    total_s = upload_s + profile_s + clean_s + results_s
    return {
        "upload_s": round(upload_s, 2),
        "profile_s": round(profile_s, 2),
        "clean_s": round(clean_s, 2),
        "results_s": round(results_s, 2),
        "total_s": round(total_s, 2),
        "peak_mib": round(mem.peak / MIB, 1),
        "clean_rows": results.json()["summary"]["rows_after"],
    }


def run(rows: int | None = None, size_mb: float | None = None, out_dir: Path | None = None,
        api: bool = True) -> dict:
    """Generate the file, then measure. Uses a temporary folder unless out_dir is given."""
    if (rows is None) == (size_mb is None):
        raise ValueError("give exactly one of rows or size_mb")
    with ExitStack() as stack:
        if out_dir is None:
            base = Path(stack.enter_context(tempfile.TemporaryDirectory(ignore_cleanup_errors=True)))
        else:
            base = Path(out_dir)
            base.mkdir(parents=True, exist_ok=True)
        src = base / "sales_messy.csv"

        t0 = time.perf_counter()
        gen = write_messy_sales(src, rows) if rows is not None else write_messy_sales_mb(src, size_mb)
        generate_s = time.perf_counter() - t0

        method, read = _rss_reader()
        out = {
            "rows": gen.rows,
            "clean_rows_expected": gen.clean_rows,
            "size_mb": round(gen.size_bytes / MB, 2),
            "generate_s": round(generate_s, 2),
            "rss_method": method,
            "engine": run_engine(src, base / "engine_out", read),
        }
        if api:
            out["api"] = run_api(src, base / "api_storage", read)
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--rows", type=int, help="number of data rows to generate")
    group.add_argument("--size-mb", type=float, help="grow rows until the file is about this many decimal MB")
    parser.add_argument("--out-dir", type=Path, help="keep the generated file and outputs here (default: temp folder)")
    parser.add_argument("--no-api", action="store_true", help="skip the backend API timing")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.rows, args.size_mb, args.out_dir, api=not args.no_api), indent=2))


if __name__ == "__main__":
    main()
