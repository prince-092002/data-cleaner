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

## Reproduce

```
.venv/Scripts/python evaluation/timing.py --rows 100000
.venv/Scripts/python evaluation/timing.py --size-mb 48      # about 8 minutes; not part of pytest
.venv/Scripts/python evaluation/timing.py --rows 100000 --no-api --out-dir <folder>
```

The 100k case also runs inside pytest as `tests/engine/test_timing.py` (marker `slow`, about 25 s).
