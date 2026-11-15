"""Where time and memory go inside pipeline.profile and pipeline.clean, stage by stage.

    .venv/Scripts/python evaluation/stage_timing.py --rows 100000
    .venv/Scripts/python evaluation/stage_timing.py --size-mb 48 --json evaluation/stages_48mb.json

Generates the same sales-like file as evaluation/timing.py, then wraps the engine's stages
(reading, profiling, each rule's prepare / left_alone / apply, and each output writer) to record
wall time and the peak process memory seen while that stage was the innermost one running.
Measurement only: it changes no engine behaviour.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import polars as pl  # noqa: E402

from engine import changelog, pipeline, recipe, report  # noqa: E402
from engine import ingest as _ingest  # noqa: E402
from engine import profile as _profile  # noqa: E402
from engine.models import Decisions  # noqa: E402
from engine.rules.registry import RULES  # noqa: E402
from evaluation.timing import MIB, _rss_reader, write_messy_sales, write_messy_sales_mb  # noqa: E402


class Stages:
    """A stack of stage labels; a sampler thread charges each memory sample to the innermost one."""

    def __init__(self, read, interval: float = 0.01):
        self.read = read
        self.interval = interval
        self.stack: list[str] = []
        self.seconds: dict[str, float] = defaultdict(float)
        self.calls: dict[str, int] = defaultdict(int)
        self.peak: dict[str, int] = defaultdict(int)
        self.order: list[str] = []
        self._stop = threading.Event()

    def _sample(self) -> None:
        while not self._stop.is_set():
            if self.stack:
                label = self.stack[-1]
                self.peak[label] = max(self.peak[label], self.read())
            self._stop.wait(self.interval)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def wrap(self, label_fn, fn):
        def wrapper(*args, **kwargs):
            label = label_fn(*args, **kwargs)
            if label not in self.seconds:
                self.order.append(label)
            self.stack.append(label)
            self.peak[label] = max(self.peak[label], self.read())
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                self.seconds[label] += time.perf_counter() - t0
                self.calls[label] += 1
                self.peak[label] = max(self.peak[label], self.read())
                self.stack.pop()
        return wrapper


def os_peak_bytes() -> int | None:
    """The process's true peak working set from the operating system (Windows), not sampled."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t),
                    ("d", ctypes.c_size_t), ("e", ctypes.c_size_t), ("f", ctypes.c_size_t)]

    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    # Own library handles: evaluation/timing.py sets argtypes on the shared windll.psapi function.
    get_info = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    current = ctypes.WinDLL("kernel32").GetCurrentProcess
    current.restype = wintypes.HANDLE
    if not get_info(current(), ctypes.byref(counters), counters.cb):
        return None
    return counters.PeakWorkingSetSize


def instrument(st: Stages, phase: list[str]) -> None:
    p = lambda name: (lambda *a, **k: f"{phase[0]}: {name}")  # noqa: E731
    _ingest.ingest = st.wrap(p("read file (ingest)"), _ingest.ingest)
    _profile.profile_dataframe = st.wrap(p("profile_dataframe (scores)"), _profile.profile_dataframe)
    changelog.write_csv = st.wrap(p("write changelog.csv"), changelog.write_csv)
    report.render = st.wrap(p("render report.html"), report.render)
    recipe.save = st.wrap(p("write recipe.yaml"), recipe.save)
    pl.DataFrame.write_csv = st.wrap(p("write clean.csv"), pl.DataFrame.write_csv)
    for rule in RULES:
        for method in ("prepare", "left_alone", "apply"):
            fn = getattr(rule, method)
            setattr(rule, method, st.wrap(
                (lambda r, m: lambda *a, **k: f"{phase[0]}: {r.id}.{m}")(rule, method), fn))


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--rows", type=int)
    g.add_argument("--size-mb", type=float)
    ap.add_argument("--json", type=Path, help="also write the table as JSON here")
    args = ap.parse_args()

    method, read = _rss_reader()
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "sales.csv"
        gen = (write_messy_sales(src, args.rows) if args.rows
               else write_messy_sales_mb(src, args.size_mb))
        print(f"file: {gen.rows:,} rows, {gen.size_bytes / 1e6:.2f} MB; memory via {method}")

        # Like the backend: a cache folder per dataset, when this engine version supports it.
        kw = ({"cache_dir": Path(tmp) / "cache"}
              if "cache_dir" in inspect.signature(pipeline.profile).parameters else {})
        phase = ["profile"]
        st = Stages(read)
        instrument(st, phase)
        baseline = read()
        st.start()
        t0 = time.perf_counter()
        prof = pipeline.profile(src, **kw)
        t_profile = time.perf_counter() - t0
        plan = pipeline.build_plan(prof, Decisions(approved=[x.id for x in prof.proposals]))
        phase[0] = "clean"
        t0 = time.perf_counter()
        result = pipeline.clean(src, plan, Path(tmp) / "out", str(uuid.uuid4()), **kw)
        t_clean = time.perf_counter() - t0
        st.stop()

    rows = [{"stage": s, "calls": st.calls[s], "seconds": round(st.seconds[s], 2),
             "peak_mib": round(st.peak[s] / MIB)} for s in st.order]
    peak = os_peak_bytes()
    print(f"\nbaseline {baseline / MIB:.0f} MiB | profile {t_profile:.1f} s | clean {t_clean:.1f} s | "
          f"changes {result.summary.total_changes:,} | rows after {result.summary.rows_after:,} | "
          f"OS peak {peak / MIB if peak else float('nan'):,.0f} MiB\n")
    print(f"{'stage':58} {'calls':>5} {'seconds':>8} {'peak MiB':>9}")
    for r in rows:
        if r["seconds"] >= 0.05 or r["peak_mib"] >= 300:
            print(f"{r['stage']:58} {r['calls']:>5} {r['seconds']:>8.2f} {r['peak_mib']:>9,}")
    if args.json:
        args.json.write_text(json.dumps({
            "rows": gen.rows, "size_mb": round(gen.size_bytes / 1e6, 2), "baseline_mib": round(baseline / MIB),
            "profile_s": round(t_profile, 2), "clean_s": round(t_clean, 2),
            "os_peak_mib": round(peak / MIB) if peak else None,
            "changes": result.summary.total_changes, "stages": rows}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
