# HANDOFF.md

Progress and status only. Technical rules live in [docs/CONTRACT.md](docs/CONTRACT.md).
New session: read this file and CONTRACT.md first, before anything else.

## Project snapshot
Data Cleaner is a website where a user uploads a messy CSV or Excel file; the system profiles it, cleans it in the background using 10 standard data-cleaning rules, and returns a clean file, an HTML cleaning report, a reusable YAML recipe and a change log. Stack: a pure-Python engine (Python 3.12, Polars, DuckDB, pandas for Excel only, charset-normalizer, clevercsv, ftfy, rapidfuzz, pyyaml, pydantic), a FastAPI backend (BackgroundTasks, SQLite via SQLModel, files in `./storage` for 24 hours), and a React + TypeScript + Vite + Tailwind + shadcn/ui frontend. No login and no AI features in Phase 1. The owner is a Business Analyst who writes the BA documents in `docs/` personally.

## Current position
- **Phase:** 1 (MVP) complete. All milestones M0 to M5 done.
- **Milestone:** M5 finished, committed and tagged `phase1-m5`. Waiting for the owner.
- **Next:** owner decides on Phase 2 or polish. Candidate fixes are under Open questions and known issues.

## Last milestone summary (M5, 2026-11-11)
- Success criteria replaced: per-dimension lift, recall on injected errors, zero damaged cells (CONTRACT section 11, README).
- Results screen shows overall + five dimensions with before, after and change. Profile screen shows detected encoding and delimiter, with a note for windows-1252.
- Fourth sample: Chicago Food Inspections, 5,000 real rows, outside the ground-truth evaluation (`sample_data/DATASETS.md`). Before 95.7, after 99.4.
- Evaluation (`evaluation/run_evaluation.py`, `evaluation/RESULTS.md`): recall 98.8% (1,721 of 1,742 fixable), precision 100%, damaged cells 0.
- Timing (`evaluation/TIMING.md`): 100k rows 23 s, 405 MB; 47.5 MB file (872k rows) 201 s, 2.0 GB.
- Mobile (375 px) and keyboard-only run through the whole flow: no page overflow, logical tab order, visible focus rings, Enter starts cleaning. One bug found and fixed (clipped text on Upload). 6 screenshots in `docs/screenshots/`.
- Bug found by the check: the website's bundled sales sample was a stale copy; resynced and guarded by `tests/engine/test_frontend_samples.py`.
- Reviewer pass: no high findings; fixed duplicate React keys on null `row_id`; rest listed below.

Tests: **239 Python passed, 50 frontend passed**, frontend build OK.

| File | Before | After | Recall | Damaged cells |
|---|---|---|---|---|
| sales_orders_messy.csv | 78.3 | 92.0 | 98.9% | 0 |
| customers_messy.xlsx | 91.5 | 99.2 | 98.7% | 0 |
| hr_survey_messy.csv | 86.3 | 96.1 | 98.6% | 0 |
| chicago_food_inspections.csv (no ground truth) | 95.7 | 99.4 | n/a | n/a |

## Decisions made
- 2026-11-11 (M0) Repo root is the working folder itself, not a nested `data-cleaner/`, so Claude Code finds `.claude/agents` and CLAUDE.md.
- 2026-11-11 (M0) Change log has an extra `change_type` field, to record removed rows, removed columns, renamed headers and added columns.
- 2026-11-11 (M0) Auto fixes are listed on the fixes screen and can be rejected; a suggestion with no answer is not applied.
- 2026-11-11 (M0) "Try a sample file" uploads a bundled file through the normal upload endpoint; no extra endpoint.
- 2026-11-11 (M0) Added `engine/models.py`, `engine/rules/base.py`, `engine/errors.py` to the layout.
- 2026-11-11 (M1) Added `engine/parsing.py` so the profiler and the rules share one set of value parsers and cannot disagree.
- 2026-11-11 (M1) CONTRACT change: category similarity threshold 90 -> 85. Why: a one-letter typo in a short word ("Nrth") scores 88.9 and was missed. Values whose digits differ are never merged.
- 2026-11-11 (M1) CONTRACT change: key candidate = type `id`, `integer` or `text` AND distinct/non-null >= 0.95. Why: repeating id columns (zip codes) looked like broken keys.
- 2026-11-11 (M1) CONTRACT change: conformity divides by (non-null + null-token cells). Why: otherwise fixing "N/A" placeholders would not move the score.
- 2026-11-11 (M1) CONTRACT change: empty cells are null at ingest; Excel values become text; dataframe columns keep the uploaded header until `normalize_headers`. Why: avoids pointless `"" -> null` log entries and keeps duplicate or empty headers addressable.
- 2026-11-11 (M1) CONTRACT clarification: type inference order written out; `id` needs numeric-looking values plus a leading zero or an id-like name.
- 2026-11-11 (M1, M2) M0 to M2 were built in the main session, not through the helper agents (agent files created mid-session load only in a new session).
- 2026-11-11 (M2) CONTRACT change: `trigger(profile)` returns lightweight candidates, and rules get an optional `prepare(df, column, params)`. Why: some params need the data, not just the profile (date order, category mapping), and must be computed after earlier fixes such as trimming.
- 2026-11-11 (M2) CONTRACT change: proposals come from a dry run of all candidates in rule order. Why: gives true `rows_affected` and before/after samples, and drops fixes that would change nothing.
- 2026-11-11 (M2) CONTRACT change: `parse_dates` params are `{dayfirst}` only (dropped `formats`); `flag_outliers` `k` is editable; `normalize_headers` mapping is keyed by the current dataframe column.
- 2026-11-11 (M2) Plan steps name columns by tidy name; if `normalize_headers` is rejected the pipeline maps names back, so other fixes still run.
- 2026-11-11 (M2) ChangeRecord is a plain dataclass, not Pydantic. Why: a run can log millions of records.
- 2026-11-11 (M2) ftfy runs in a conservative mode (repairs broken encoding only; curly quotes and ligatures are kept). Why: "auto" fixes must not change meaning or style.
- 2026-11-11 (M2) `remove_exact_duplicate_rows` is always a candidate. Why: trimming and date fixes can reveal duplicates the raw profile cannot see.
- 2026-11-11 (M3) Engine `profile()` and `clean()` take an optional `display_name`. Why: the backend stores uploads as `original.csv`, but reports and recipes should show the uploaded name.
- 2026-11-11 (M3) Upload size is checked twice (declared length, then while streaming); file type is checked by extension and content. Why: reject bad uploads before anything is queued.
- 2026-11-11 (M3) Starting a new profile deletes the old profile, plan, results and outputs. Why: results must never describe a different sheet or header row.
- 2026-11-11 (M3) An expired dataset answers 404 immediately; jobs left running by a server restart are marked failed (`interrupted`). Why: the UI must never poll forever.
- 2026-11-11 (M3) New CONTRACT items: `inspection.json` in storage, `internal_error` and `interrupted` codes, 409 for a download before cleaning, `/api/health`.
- 2026-11-11 (M3) M3 was also built in the main session; the helper agents are loaded now and can be used from M4.

- 2026-11-11 (M4) Frontend uses native selects for change-log filters and plain divs for dimension bars. Why: simpler, keyboard-friendly, easier to test.
- 2026-11-11 (M4) "Approve all safe fixes" = every proposal that is not destructive and not flag-mode. Auto and flag proposals run unless rejected; suggest proposals run only if approved (matches build_plan).
- 2026-11-11 (M4) Day-first/month-first is a one-click toggle on the parse_dates card, not hidden in the edit dialog.
- 2026-11-11 (M4) The Processing screen shows the server's `current_step` text only, no invented stage list.

- 2026-11-11 (pre-M5) Short-value guard reference list is built in (`north, south, east, west, usa, uk, eu, yes, no, male, hr, it`). Why: no user-supplied list exists in Phase 1. Side effect: "Wset" and similar short typos are still not merged.
- 2026-11-11 (pre-M5) Unparseable values ("abc", "31/02/2024") are kept as text and warned about, never guessed.
- 2026-11-11 (pre-M5) Sales sample realism over score: duplicates capped at about 6% and empty rows at 8, so the starting score stays near 78.

- 2026-11-11 (M5) Owner decision: the sales sample stays at a starting score of about 78; the score weights are not changed.
- 2026-11-11 (M5) Owner decision: success = per-dimension lift, recall on injected errors, zero damaged cells (CONTRACT section 11). Recall excludes errors that are not fixable by design, and they are listed separately.
- 2026-11-11 (M5) The real public dataset (Chicago) is outside the ground-truth evaluation. Its test tolerates a 0.5-point uniqueness drop because of the free-text key-candidate artifact; engine left unchanged.
- 2026-11-11 (M5) Reviewer findings on job overwrite and streaming size check were not fixed in M5 (demo scope); logged as known issues.

## Open questions and known issues
- **Encoding:** Latin-script files are read as windows-1252, so Central European files (Polish, Czech) may show wrong accented letters. The profile screen shows the detected encoding.
- Ambiguous dates default to month-first if approved without editing; the UI forces a Day first / Month first click before Approve.
- Category clustering misses swapped letters and short typos (under 5 characters need a reference-list match or 95+ similarity).
- Weakest recall: exact duplicates 55.6% (copies that carry a missing value the original lacks stop being identical), outliers 66.7% (one extreme value inside the IQR fence), "(123)" amounts become -123 by contract while the ground truth expected +123.
- Uniqueness can fall about 0.1 point on free-text columns that count as key candidates (Chicago sample). Candidate fix: exclude long free text from key candidates.
- Reviewer, medium: starting a new profile while a job is still running can let the old job write results after the cleanup (section 8.5). The UI blocks this in one browser; the API does not.
- Reviewer, low: the upload size limit is checked after FastAPI has spooled the upload to a temp file; an upload without Content-Length skips the early check. `engine/pipeline.py` lowercases the step label ("Applying <rule label>" in section 7).
- Large files: 47.5 MB takes about 3.5 minutes and 2 GB of memory; peak memory is 40 to 50 times the file size. Change records are held in memory.
- Jobs run in the API process; two big files at once slow each other.
- Change-log filter on column fires a request per keystroke (no debounce); the change log re-reads `changelog.csv` on every page request.
- Samples shown after a Day first / Month first toggle still show the original suggestion.
- Clean files keep unparseable values as text ("abc", "31/02/2024") by design.

## Next steps
Nothing is queued. Options for the owner, in rough order of value:
1. Fix the two reviewer findings (job overwrite after re-profile; streaming size check).
2. Exclude long free text from key candidates; recheck the Chicago uniqueness score.
3. Add the Chicago file as a fourth "Try a sample file" button.
4. Phase 2 scope (to be defined by the owner in the BRD).

## How to run
```bash
python -m venv .venv
.venv/Scripts/activate                               # Windows (Git Bash: source .venv/Scripts/activate)
pip install -e ".[backend,dev]"
pytest -q                                            # engine + API tests
python sample_data/make_samples.py                   # regenerate the 3 sample files
uvicorn backend.main:app --reload --port 8000        # backend (API docs at /docs)
cd frontend && npm install && npm run dev            # frontend on port 5173; npm run test -- --run
```
The existing `.venv` has all Python dependencies. Storage location can be changed with `DC_STORAGE_DIR`; allowed browser origins with `DC_CORS_ORIGINS`.

## Milestone log
- 2026-11-11 | M0 Setup | Done. Structure, CLAUDE.md, CONTRACT.md v1.0, 5 agents, README skeleton, BA placeholders. No tests (no code).
- 2026-11-11 | M1 Ingest + profile + quality score | Done. 96 tests passing. 3 sample files score 83.1 / 91.5 / 86.3.
- 2026-11-11 | M2 Rules + change log + recipe + report | Done. 165 tests passing. Samples improve to 96.9 / 99.2 / 96.1.
- 2026-11-11 | M3 FastAPI backend | Done. 210 tests passing (165 engine + 45 API). Live upload-to-download flow checked with curl.
- 2026-11-11 | M4 Website | Done. 41 frontend tests passing, build OK. Live flow checked in the browser (sales sample 83.1 -> 96.6). Reviewer findings fixed.
- 2026-11-11 | Pre-M5 fixes | Done. Safe-approve rule, job lock, ground truth, messier sales sample (78.3, target missed), category guard, encoding fix. 228 Python + 46 frontend tests passing. Tagged phase1-m4.
- 2026-11-11 | M5 Evaluation, timing, review, README | Done. 239 Python + 50 frontend tests passing. Recall 98.8%, precision 100%, 0 damaged cells. Tagged phase1-m5.
