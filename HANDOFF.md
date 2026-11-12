# HANDOFF.md

Progress and status only. Technical rules live in [docs/CONTRACT.md](docs/CONTRACT.md).
New session: read this file and CONTRACT.md first, before anything else.

## Project snapshot
Data Cleaner is a website where a user uploads a messy CSV or Excel file; the system profiles it, cleans it in the background using 10 standard data-cleaning rules, and returns a clean file, an HTML cleaning report, a reusable YAML recipe and a change log. Stack: a pure-Python engine (Python 3.12, Polars, DuckDB, pandas for Excel only, charset-normalizer, clevercsv, ftfy, rapidfuzz, pyyaml, pydantic), a FastAPI backend (BackgroundTasks, SQLite via SQLModel, files in `./storage` for 24 hours), and a React + TypeScript + Vite + Tailwind + shadcn/ui frontend. No login and no AI features in Phase 1. The owner is a Business Analyst who writes the BA documents in `docs/` personally.

## Current position
- **Phase:** 1 (MVP)
- **Milestone:** M4 finished and hardened (pre-M5 fixes done). Committed and tagged `phase1-m4`. Waiting for the owner's "go" to start M5.
- **Done:** M0 to M4.
- **Next:** M5 = end-to-end test, evaluation (precision/recall against `sample_data/ground_truth.csv`), reviewer pass, README with setup steps and screenshots. Added by the owner: a 100k-row timing test and a mobile + keyboard-only check with screenshots.

## Last milestone summary (pre-M5 fixes on top of M4, 2026-11-11)
- "Approve all safe fixes" now skips category merges, ambiguous dates, destructive and flag-only fixes; ambiguous dates need a Day first / Month first click before Approve works. Test added.
- Start cleaning and the stepper are disabled while a job runs (`jobRunning` in app state). Tests added.
- `make_samples.py` now writes `sample_data/ground_truth.csv` (file, row, column, error_type, original_value, injected_value; about 2,900 entries). Test added.
- Sales sample made messier (433 rows incl. 25 duplicates, 8 empty rows). Starting score **78.3**, after cleaning 92.0. The owner's target was 55 to 65: NOT reached (see Open questions).
- Short-value guard in `standardize_categories` (values under 5 characters need a reference-list match or similarity of 95+).
- Bug found by the new sample: iso8859-10 guess for a cp1252 file. Encoding detection now maps Latin-script guesses to windows-1252. CONTRACT section 10 added.
- New tests: `test_quality_scores.py` (each dimension drops when its errors are injected; no dimension drops after cleaning), `test_ground_truth.py`.

Tests: **228 Python passed, 46 frontend passed**, frontend build OK.

| File | Before | After |
|---|---|---|
| sales_orders_messy.csv | 78.3 | 92.0 |
| customers_messy.xlsx | 91.5 | 99.2 |
| hr_survey_messy.csv | 86.3 | 96.1 |

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

## Open questions and known issues
- Ambiguous dates default to month-first when approved without editing. The UI (M4) must make the day-first/month-first choice obvious on that suggestion.
- Category clustering does not catch swapped letters in short words ("Wset" vs "West"). Expect missed recall in the M5 evaluation.
- Profiling runs the dry run, and cleaning re-reads and re-profiles the file, so each file is processed about three times. Fine for the samples (under 1 second); not yet timed on a 50 MB file.
- Change records are held in memory until written. A very large, very dirty file could use a lot of memory.
- Every header that is not already snake_case counts as `messy_header`, so conformity tops out at 80 before cleaning. Intended.
- Background jobs run in the API process (FastAPI BackgroundTasks). Two large files at once will slow each other; fine for a demo.
- Two clean jobs started at the same moment on one dataset would overwrite each other's files. The UI should disable the button while a job runs.
- The change log table re-reads `changelog.csv` on every page request. Fine for the samples; slow for millions of changes.
- Sales sample starts at 78.3, not the 55 to 65 the owner asked for. Quality dimensions are column means, so a realistic file (about 6% duplicates) cannot go lower; reaching 65 needed about 40% duplicate or empty rows. Owner to decide: accept about 78, change the score weights, or allow an unrealistic file.
- Clean-file test: invalid values stay as text in clean output by design.

## Next steps
M5, one agent call each (after the owner says "go"):
1. test-data-qa: run all three sample files end to end through the API and check outputs.
2. test-data-qa: evaluation table (precision/recall per rule against `ground_truth.csv`).
3. test-data-qa: 100k-row timing test (profile + clean), report seconds and memory.
4. web-ui-builder / main session: mobile layout and keyboard-only check, screenshots.
5. reviewer-explainer: final pass over engine, backend and frontend against CONTRACT.md.
6. Main session: README (setup steps, screenshots, evaluation table), milestone tick.
Known gaps: category recall on swapped letters in short words, 50 MB timing, change-log column filter fires per keystroke (no debounce), samples after a day-first toggle still show the original suggestion.

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
