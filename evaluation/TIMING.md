# Timing and memory

Measured with `evaluation/timing.py` on a Windows 11 development machine, one run at a time, nothing else running.
The file has the same columns and messy-value mix as the sales sample (`sample_data/make_samples.py`), with the
same duplicate and empty-row rates. Every proposal is approved. The API column is the same work through the
backend (upload, profile job, clean job, results) using FastAPI TestClient.

## Results

| Rows | File size (MB) | Profile (s) | Clean (s) | Total engine (s) | Peak memory (MiB) | API total (s) | API peak (MiB) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 100,000 | 5.38 | 6.06 | 16.64 | 22.70 | 405 | 29.13 | 536 |
| 872,050 | 47.52 | 46.64 | 154.76 | 201.40 | 2,004 | 223.32 | 2,365 |

- Engine total = profile + clean. API total = upload + profile + clean + results.
- File size uses decimal MB (1 MB = 1,000,000 bytes). Memory uses MiB (1,048,576 bytes).
- The 48 MB case used `--size-mb 48`, which gave 47.52 MB and 872,050 data rows. Its generation step took 59 s, and the whole run took 8 min 06 s, inside the 10-minute timeout.
- Clean row counts: 100k run 91,749 rows out of 91,750 expected. 48 MB run 799,909 out of 800,104 expected. The difference is sparse rows that become identical after null tokens are cleared, which the engine correctly removes as duplicates.
- Peak memory is the highest process working set sampled every 20 ms during the call. psutil is not installed, so the sampler used `GetProcessMemoryInfo` through ctypes.

## What this means for the 50 MB limit

A file at the 50 MB limit (about 870,000 rows) takes about 3.4 minutes in the engine (47 s profile, 155 s clean) and about 3.7 minutes through the API, so a user waits minutes, not seconds, at the top of the range, and most of that time is the clean step.
Memory is the bigger concern: a 48 MB file peaks at about 2.0 GB in the engine and 2.4 GB through the API, roughly 40 to 50 times the file size, so several jobs at once or a small server would need more RAM than a single job does.
At 100,000 rows (about 5 MB) the total is about 23 to 30 seconds, and time scales close to linearly with rows (8.7 times the rows took 8.9 times the time), so a typical upload finishes well within a minute and the 50 MB limit is the worst case.

## M6 Step 7: where the time and memory go, and what changed

Each stage was timed and the process's exact peak working set was read from Windows.
This machine's speed varied by up to 4 times between runs (stages whose code
did not change took 14 s in one run and 55 s in another), so old and new code were always run back to
back, and only those pairs are compared. Every proposal is approved.

### Before (phase1-m6a), 47.5 MB file, 872,050 rows, 2.83 million changes

| Stage | Seconds | Share |
|---|---:|---:|
| Profile: quality scoring | 14.2 | 26% of profile |
| Profile: trim text (7 columns) | 16.3 | 30% of profile |
| Profile: read file | 4.0 | 7% of profile |
| Clean: write clean.xlsx (openpyxl) | 72.1 | 48% of clean |
| Clean: quality scoring before and after | 26.3 | 17% of clean |
| Clean: trim text | 16.4 | 11% of clean |
| Clean: write changelog.csv | 14.4 | 10% of clean |
| Clean: read the file again | 3.7 | 2% of clean |

Memory rose step by step through clean (0.77 GB to 1.84 GB) while 2.83 million change records were held.
A change record costs about 200 bytes plus the old value it keeps alive.

### Changes

1. **Read once.** With `cache_dir`, profile saves the parsed all-text table as Parquet plus its own
   scores; clean reuses both, so it neither parses the file again nor scores "before" again. Never
   sampled; the dry run is never reused for the final clean.
2. **Distinct values.** `map_values` (used by every value rule) runs the fix once per distinct value,
   rewrites the column with Polars and loops in Python only over the rows that change.
3. **Change records on disk.** Clean streams each step's records straight to changelog.csv and keeps
   only counts and a 50-record sample, instead of holding millions until the end. Output is byte-identical.

### After (back-to-back pairs)

| File | Code | Profile (s) | Clean (s) | Exact peak (MiB) |
|---|---|---:|---:|---:|
| 100,000 rows, 5.4 MB | phase1-m6a | 13.1 / 12.0 | 31.1 / 31.7 | 431 / 439 |
| 100,000 rows, 5.4 MB | Step 7 | 11.4 / 11.9 | 24.5 / 25.5 | 483 / 492 |
| 872,050 rows, 47.5 MB | phase1-m6a | 60.0 | 238.4 | 1,948 |
| 872,050 rows, 47.5 MB | Step 7 | 79.3 | 207.9 | 1,787 |

- Clean is 13 to 20% faster. The 47.5 MB profile pair is not a fair comparison: its scoring stage, whose
  code did not change, took 14.8 s in the old run and 22.0 s in the new one.
- Peak memory is 8% lower on the big file and about 12% (50 MiB) higher on the small one (Parquet cache
  and distinct-value buffers). Change records were not the main cause of the peak after all: it now sits
  in the final quality scoring of clean (the whole table handed to DuckDB) and in the read itself.
- The biggest remaining cost is writing clean.xlsx with openpyxl: about half of clean on the big file.
  openpyxl itself takes about 90% of that (our own row building is 0.6 s of 21.5 s on 200,000 rows), so a
  real gain needs a faster Excel writer (for example xlsxwriter, a new dependency) or writing clean.xlsx
  only when it is downloaded. That is an owner decision.

### Supported size

- **Local:** up to 50 MB (`DC_MAX_UPLOAD_MB`). A 47.5 MB file takes about 4 to 5 minutes end to end on
  this machine and peaks at about 1.8 GB of memory.
- **Live site:** 4 MB (set in Part C, under Vercel's 4.5 MB request limit). A 4 MB file is about 75,000
  rows: about 20 to 30 seconds and under 0.5 GB.

## Reproduce

```
.venv/Scripts/python evaluation/timing.py --rows 100000
.venv/Scripts/python evaluation/timing.py --size-mb 48      # about 8 minutes; not part of pytest
.venv/Scripts/python evaluation/timing.py --rows 100000 --no-api --out-dir <folder>
```

The 100k case also runs inside pytest as `tests/engine/test_timing.py` (marker `slow`, about 25 s).
