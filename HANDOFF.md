# HANDOFF.md

Progress and status only. Technical rules live in [docs/CONTRACT.md](docs/CONTRACT.md).
New session: read this file and CONTRACT.md first, before anything else.

## Project snapshot
Data Cleaner is a website where a user uploads a messy CSV or Excel file; the system profiles it, cleans it in the background using 10 standard data-cleaning rules, and returns a clean file, an HTML cleaning report, a reusable YAML recipe and a change log. Stack: a pure-Python engine (Python 3.12, Polars, DuckDB, pandas for Excel only, charset-normalizer, clevercsv, ftfy, rapidfuzz, pyyaml, pydantic), a FastAPI backend (BackgroundTasks, SQLite via SQLModel, files in `./storage` for 24 hours), and a React + TypeScript + Vite + Tailwind + shadcn/ui frontend. No login and no AI features in Phase 1. The owner is a Business Analyst who writes the BA documents in `docs/` personally.

## Current position
- **Phase:** 1, milestone M6, Part C. Step 13 (queue jobs, limits, cleanup, cron, frontend states) done. Not tagged.
- **Repo:** https://github.com/prince-092002/data-cleaner (private, `main`, CI green). Branch `spike-vercel` is the throwaway spike, never merged.
- **Vercel:** spike project `data-cleaner-spike` kept (Neon + private Blob, reused in Step 14), GitHub connection removed.
- **Waiting for:** the owner's "go" for Step 14 (deploy through GitHub on Vercel). Do not start it before.

## Last milestone summary (M6 Step 13, 2026-11-16)
- Jobs: in-process runner locally, Vercel Queues consumer with `DC_JOB_RUNNER=queue` (claim first, 240 s deadline, at most two retries counted in the database, timed-out jobs never publish). Stuck jobs fail on the next status read and in the daily cleanup.
- Cleanup and limits: `GET /api/cron/cleanup` (Bearer CRON_SECRET, daily in vercel.json), 800 MB stored-bytes guard (503 storage_full), daily caps on jobs and uploads (429 too_many_jobs / too_many_uploads), 4 MB live upload limit.
- Frontend: queued, running, failed and expired states, resume from `?d=&j=&s=`, polling 2 s then 5 s, focus moves to error messages, 24-hour notice on Upload.
- Chicago sample trimmed to the first 3,995 rows (3,999,150 bytes), byte-identical prefix. Scores unchanged (95.7 to 99.4).
- Review: 2 HIGH plus 2 must-fix MEDIUM fixed with tests; 4 deferred (below). Postgres tests pass on Neon (unpooled URL). Queues, Blob and Cron only tested with fakes.

Tests: **450 Python passed, 7 skipped (Postgres), 100 frontend passed**, build OK. Evaluation unchanged.

## Decisions made
- 2026-11-11 (M0, summarised) Repo root is the working folder. Change log has a `change_type` field. Auto fixes are listed and can be rejected; an unanswered suggestion is not applied. "Try a sample file" uses the normal upload endpoint. Added `engine/models.py`, `engine/rules/base.py`, `engine/errors.py`.
- 2026-11-11 (M1, summarised) `engine/parsing.py` shares value parsers between profiler and rules. CONTRACT changes: category similarity 90 -> 85 (values whose digits differ never merge); key candidate = id, integer or text with distinct/non-null >= 0.95; conformity divides by non-null + null-token cells; empty cells are null at ingest, Excel values are text, headers stay as uploaded until `normalize_headers`; type inference order written out.
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
- 2026-11-11 (M4, summarised) Frontend uses native selects for change-log filters and plain divs for dimension bars. Why: simpler, keyboard-friendly, easier to test. "Approve all safe fixes" = every proposal that is not destructive and not flag-mode. Auto and flag proposals run unless rejected; suggest proposals run only if approved (matches build_plan). Day-first/month-first is a one-click toggle on the parse_dates card, not hidden in the edit dialog. The Processing screen shows the server's `current_step` text only, no invented stage list.
- 2026-11-11 (pre-M5, summarised) Short-value guard reference list is built in (`north, south, east, west, usa, uk, eu, yes, no, male, hr, it`). Why: no user-supplied list exists in Phase 1. Side effect: "Wset" and similar short typos are still not merged. Unparseable values ("abc", "31/02/2024") are kept as text and warned about, never guessed. Sales sample realism over score: duplicates capped at about 6% and empty rows at 8, so the starting score stays near 78.
- 2026-11-11 (M5) Owner decision: the sales sample stays at a starting score of about 78; the score weights are not changed.
- 2026-11-11 (M5) Owner decision: success = per-dimension lift, recall on injected errors, zero damaged cells (CONTRACT section 11). Recall excludes errors that are not fixable by design, and they are listed separately.
- 2026-11-11 (M5) The real public dataset (Chicago) is outside the ground-truth evaluation. Its test tolerates a 0.5-point uniqueness drop because of the free-text key-candidate artifact; engine left unchanged.
- 2026-11-11 (M5) Reviewer findings on job overwrite and streaming size check were not fixed in M5 (demo scope); logged as known issues.
- 2026-11-12 (M6.1) Answer key: duplicate_row goes on every later identical row, not on the inserted copy. Why: the rule keeps the first occurrence; 16 "misses" were correct removals of the other row.
- 2026-11-12 (M6.1) Answer key: parentheses_negative expects -x (CONTRACT 2.3). Engine unchanged.
- 2026-11-12 (M6.2) Tier 1 category merges are auto through a new `Candidate.auto_safe` flag, so the rule stays one of the 10 and stays destructive for Tier 2.
- 2026-11-12 (M6.2) The old rapidfuzz ratio clustering and short-value guard are replaced by the Tier 2 tests. Side effect: "Cat" -> "Cats" style pairs can now be suggested (one letter away); they are suggestions only.
- 2026-11-12 (M6.2) Tier 2 targets must have more rows than the value they absorb; values are processed largest first, so merges never chain.
- 2026-11-12 (M6.2) "Fixed width" = every number in the column has the same length. Money = any value with a currency symbol (not the column name). standardize_categories and coerce_numeric bumped to 1.1.0.
- 2026-11-12 (M6.2) Owner decision: Tier 1 prefers an existing Title Case spelling, else the most frequent. It never invents a spelling, so acronyms such as USA stay as written.
- 2026-11-12 (M6.3) Left-alone values come from a separate `Rule.left_alone()` hook, not from params, so recipes stay clean. A rule whose dry run changes nothing makes no proposal, so its left-alone values are not shown.
- 2026-11-12 (M6.3) Headings stay in sentence case to match the rest of the site (the guidelines prefer Title Case).
- 2026-11-12 (M6.4) Generation counter is bumped by clean jobs too, so the newest clean wins when two overlap. Profile and results moved from files into the Dataset row so the save is one guarded UPDATE (also fits Postgres in Step 12).
- 2026-11-12 (M6.4) Old run folders go when a newer clean is saved or at the 24-hour cleanup; since M6.6 a folder of a clean job still queued or running is kept until that job removes it.
- 2026-11-12 (M6.4) The streaming cap allows 1 MB of multipart overhead on top of the file limit; the exact file-size check stays in `save_upload`.
- 2026-11-12 (M6.5) Name casing lives in rule 3 as a forced suggestion, not an 11th rule (CLAUDE.md: exactly 10 rules).
- 2026-11-12 (M6.5) "Mac" gets a second capital only before a consonant other than h, k or y, so Machado and Mackenzie stay as normal words; MacArthur becomes Macarthur (accepted: suggestion only).
- 2026-11-12 (M6.6) Code review before tagging: high-severity fixes applied; owner-spec and efficiency findings logged under known issues.
- 2026-11-15 (M6.7) Read-once cache keyed by file SHA-256 + sheet + header row + engine version, so a re-downloaded copy (Vercel later) still hits. Cache files live in the dataset folder.
- 2026-11-15 (M6.7) Change log stays on Python's csv module: Polars quotes empty strings differently and the gain was 1.6 s on 2.8 million rows.
- 2026-11-15 (M6.7) Timing compared only in back-to-back pairs because this machine's speed varies up to 4x between runs.
- 2026-11-15 (M6.7b) Owner decision: clean.xlsx is built on download, no new dependency. `pipeline.build_xlsx(out_dir)` builds from clean.csv + xlsx_spec.json, cached per clean run, atomic rename. Old-code fingerprints in tests/engine/fixtures/xlsx_old_code.json prove identical content.
- 2026-11-15 (M6.8) "Fixed" is strict: right value AND standard form; null tokens and placeholders must become real empty cells; no partial credit. Ambiguous dates count as detected, not fixed (right only by default order).
- 2026-11-15 (M6.8) Detection has two levels: cell (fixed, changed, flagged, listed as left alone) and column (profile issue). Both are reported; missing values are column level.
- 2026-11-15 (M6.8) No engine change in Step 8. Held-out misses are reported, not fixed.
- 2026-11-15 (M6.8b) Owner rule: 80% majority spelling wins automatically; Title Case only as a suggestion when there is no majority. Replaces the M6.2 "prefer Title Case" decision. Side effect: "New York" 2 / "new york" 9 now becomes "new york" automatically.
- 2026-11-15 (M6.8b) changelog.csv gained an 11th column `reason` (CONTRACT 5) to show why a category merge happened.
- 2026-11-15 (M6.8b) Owner's id-like token list applied as given. Risk: a real count column named like "Number of items" or "num_visits" is typed as id (no outlier flags, no numeric clean-up). No bundled file has one.
- 2026-11-15 (M6.9) Owner decision: a count-like token (count, qty, quantity, total, sum, amount, items, of) overrides an id token, so "Number of items" is a number. Replaces the risk noted above.
- 2026-11-15 (M6.9) Owner decisions: keep the `reason` column; keep lowercase majorities; keep Region case variants as a suggestion.
- 2026-11-15 (M6.9) CONTRACT change: the cache key also holds a hash of the engine source (`cache.ENGINE_FINGERPRINT`). Why: ENGINE_VERSION was never bumped, so an upgraded engine could serve cached column types from the old one. Any engine edit now costs one re-parse.
- 2026-11-15 (M6.9) Branch renamed from master to main before GitHub.
- 2026-11-15 (M6.10) Repo is private on the owner's account (`prince-092002/data-cleaner`); CI added because it took minutes. The gh token has no `workflow` scope, yet the first workflow push to a new repo was accepted; if a later workflow change is refused, run `gh auth refresh -s workflow`.
- 2026-11-12 (M6.1) Outlier method unchanged: the missed salary of 1 is inside the IQR fence. A plausibility floor would be a new rule, not a fix.
- 2026-11-15 (M6.11) Hosting decision: Vercel Hobby with Queues (push consumer) for jobs, Neon Postgres for rows, private Blob for files. Fallback: job inside the request with the same status row. Details and sources in docs/ADR-hosting-vercel.md.
- 2026-11-15 (M6.11) Pending CONTRACT change for Step 12 (owner to confirm): the deployed engine drops DuckDB, pandas, numpy and pyarrow (Polars + openpyxl do their work). Why: the bundle is 590 MB with them, 271 MB without; limit 500 MB.
- 2026-11-15 (M6.11) Step 12 rules from the spike: consumer stops itself at about 270 s and marks the job failed; messages sent with short retention; consumer checks the job row first (at-least-once delivery); live upload limit stays 4 MB unless the browser uploads straight to Blob.
- 2026-11-16 (M6.12) Owner confirmed: the production engine drops DuckDB, pandas, numpy and pyarrow (outputs byte-identical, evaluation unchanged). Excel is read with openpyxl, keeping the old pandas NA strings and trimming; `reset_dimensions()` guards against a wrong sheet dimension.
- 2026-11-16 (M6.12) Backends chosen by environment only: Postgres when DATABASE_URL is set, Blob only when DC_STORAGE_BACKEND=blob (never just because Vercel variables exist). API shows superseded and expired jobs as `failed` with that error code. User-chosen merges log the reason "merge chosen by the user".
- 2026-11-16 (M6.12) Owner decision: the live upload limit stays 4 MB (README known limit). Spike project's GitHub connection removed, project kept for Step 14.
- 2026-11-16 (M6.13) Job runner chosen by `DC_JOB_RUNNER` (inprocess default, queue in production). Deadline 240 s per attempt, lease 270 s; retries counted by the attempts column, never by the queue's max_attempts.
- 2026-11-16 (M6.13) Kept Vercel Cron (owner's spec) although Vercel now calls it legacy in favour of Schedules (beta). Daily caps count at POST profile/clean and upload; a missing x-forwarded-for means no per-visitor cap so nobody shares a bucket. IP hashes salted with DC_IP_HASH_SALT or CRON_SECRET.

## Open questions and known issues
- **Encoding:** Latin-script files are read as windows-1252, so Central European files (Polish, Czech) may show wrong accented letters. The profile screen shows the detected encoding.
- Ambiguous dates default to month-first if approved without editing; the UI forces a Day first / Month first click before Approve.
- The 500-distinct cap for Tier 2 is never reached in practice: the category test (<= 50 distinct) runs first.
- Outlier recall 66.7%: a salary of 1 sits inside the IQR fence (by design). Duplicate and "(123)" misses were answer-key errors, fixed in M6.1.
- Uniqueness can fall about 0.1 point on free-text columns that count as key candidates (Chicago sample). Candidate fix: exclude long free text from key candidates.
- Large files: 47.5 MB takes about 4 to 5 minutes and about 1.8 GB (M6.7). Writing clean.xlsx with openpyxl is about half of clean.
- Jobs run in the API process; two big files at once slow each other.
- Change-log filter on column fires a request per keystroke (no debounce); the change log re-reads `changelog.csv` on every page request.
- Samples shown after a Day first / Month first toggle still show the original suggestion.
- Review (M6.6), not fixed: an id column with leading zeros at mixed widths and no id-like name (cust_no: 00123, 045) is coerced to numbers automatically. Follows the owner's Step 2 rule; revisit if it bites.
- Review (M6.6), efficiency: Tier 2 category analysis runs up to 3 times per column (Step 7); every route loads profile/results JSON from the Dataset row (Step 12).
- With no 80% majority, case variants are no longer merged unless the user approves the suggestion (demo file Region: west 17, WEST 7, West 6 now needs one click).
- Held-out misses: "Northest" (tie between Northeast and Northwest), "Ctr" (not recognised as Central), one mojibake name ("Ã…berg"), emails in capitals, "unknown"/"n.a." placeholders, stray markers, synonyms.
- Review (M6.9), low, not fixed: the id tokens "no" and "key" catch names like "Amount (no tax)"; `evaluation/stage_timing.py` times a function clean no longer calls; a cache miss hashes the file twice.
- Review (M6.12), not fixed: local put_file not atomic; Excel waiter polls Blob list every 0.2 s; one failing prefix delete aborts the sweep; post-save cleanup errors mark a saved job failed; local list_keys walks the whole root; streams can leak a handle on disconnect; two cold starts can race in create_all. (Sweep and stuck jobs were fixed in Step 13.)
- Review (M6.13), medium, not fixed: a redelivery of a crashed job inside its 270 s lease is acknowledged, so a crashed worker is not retried (the job fails as job_timeout later); the global daily caps can be spent by one caller with many IPs, and a failed enqueue does not refund the slot.
- Review (M6.13), low, not fixed: a refused (429) profile request still saves the new sheet and header row; one failed status request stops polling and shows a failure for a job that may still finish.
- Not verified yet: real Vercel Queues send and push delivery, Blob SDK calls and Cron (fakes only); Postgres tests need the unpooled URL and leave their schema behind if engine creation fails.
- The `reason` is stored in changelog.csv only; the report and the UI table do not show it.
- Clean files keep unparseable values as text ("abc", "31/02/2024") by design.

## Next steps
1. Wait for the owner's "go". Then Step 14: deploy through GitHub on Vercel with the production variables listed in README (DC_JOB_RUNNER=queue, DC_STORAGE_BACKEND=blob, DC_MAX_UPLOAD_MB=4, CRON_SECRET, DC_IP_HASH_SALT); first real test of Queues, Blob and Cron on a preview.
2. Step 15: verify the live site. Later: show the `reason` column in the report and UI, narrow the "no"/"key" id tokens, move Cron to Schedules.
3. After the real deployment works: `vercel project remove data-cleaner-spike`, remove its Neon database and Blob store, delete branch `spike-vercel`.

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
The existing `.venv` has all Python dependencies. Storage location can be changed with `DC_STORAGE_DIR`; allowed browser origins with `DC_CORS_ORIGINS`; upload limit with `DC_MAX_UPLOAD_MB`.

## Milestone log
- 2026-11-11 | M0 Setup | Done. Structure, CLAUDE.md, CONTRACT.md v1.0, 5 agents, README skeleton, BA placeholders. No tests (no code).
- 2026-11-11 | M1 Ingest + profile + quality score | Done. 96 tests passing. 3 sample files score 83.1 / 91.5 / 86.3.
- 2026-11-11 | M2 Rules + change log + recipe + report | Done. 165 tests passing. Samples improve to 96.9 / 99.2 / 96.1.
- 2026-11-11 | M3 FastAPI backend | Done. 210 tests passing (165 engine + 45 API). Live upload-to-download flow checked with curl.
- 2026-11-11 | M4 Website | Done. 41 frontend tests passing, build OK. Live flow checked in the browser (sales sample 83.1 -> 96.6). Reviewer findings fixed.
- 2026-11-11 | Pre-M5 fixes | Done. Safe-approve rule, job lock, ground truth, messier sales sample (78.3, target missed), category guard, encoding fix. 228 Python + 46 frontend tests passing. Tagged phase1-m4.
- 2026-11-11 | M5 Evaluation, timing, review, README | Done. 239 Python + 50 frontend tests passing. Recall 98.8%, precision 100%, 0 damaged cells. Tagged phase1-m5.
- 2026-11-12 | M6 Step 1 Diagnosis | Done. 16 duplicate and 4 "(123)" misses were answer-key errors (fixed); 1 outlier inside the fence. 243 Python + 50 frontend tests passing.
- 2026-11-12 | M6 Step 2 Region, Quantity, money | Done. Category Tier 1/2, fixed-width leading zeros, money 2 decimals, demo regression test. 260 Python + 50 frontend tests passing.
- 2026-11-12 | M6 Step 3 Fixes screen | Done. Grouped by column, automatic merges with Undo, left-alone lists, label fix, 375 px and keyboard checked. 264 Python + 54 frontend tests passing.
- 2026-11-12 | M6 Step 4 Reviewer bugs | Done. Generation guard for stale jobs, streaming upload cap (DC_MAX_UPLOAD_MB), UI limit from /api/health. 270 Python + 56 frontend tests passing.
- 2026-11-12 | M6 Step 5 Name casing | Done. Suggest-only name capitals with Mc/Mac/O'/particles/numerals, business-name guard, excluded from approve-all-safe. 286 Python + 56 frontend tests passing.
- 2026-11-12 | M6 Step 6 Part A checkpoint | Done. Demo file 4 regions / 1 quantity format / 2 decimals, quality 80.5 -> 98.0; review: 5 fixes. 291 Python + 56 frontend tests passing. Tagged phase1-m6a.
- 2026-11-15 | M6 Step 7 Measure, then optimize | Done. Stage profiler, read-once Parquet cache, distinct-value map_values, streamed change log. Clean 13-20% faster, 47.5 MB peak -8%. 298 Python tests passing.
- 2026-11-15 | M6 Steps 7b + 8 | Done. Excel on download; held-out batch; detection 96.7%, fix recall 69.1%, precision 100%, 0 damaged; Chicago hand check 0 wrong. 312 Python + 58 frontend tests passing.
- 2026-11-15 | M6 Step 8b | Done. Majority spelling and id-like names (two subagents, round 1 each). Chicago: debatable 31 -> 0, useless flags 3 -> 0, 0 wrong; evaluation unchanged. 370 Python + 59 frontend tests passing.
- 2026-11-15 | M6 Step 9 | Done. Owner decisions, code review (1 high fixed, 6 deferred), fresh Chicago hand check 98 correct / 2 useful flags / 0 wrong; evaluation unchanged. 384 Python + 60 frontend tests passing. Tagged phase1-m6b, branch renamed to main.
- 2026-11-15 | M6 Step 10 GitHub | Done. Safety scan clean, private repo prince-092002/data-cleaner, main and 4 tags pushed, CI green (Python + frontend + build).
- 2026-11-15 | M6 Step 11 Vercel spike | Done. Go. Queues + Postgres + Blob work on Hobby; slim engine 271 MB (unmodified 590 MB fails); 4 MB Chicago cut 9 s warm, 198 MB; output identical to local. ADR written. No product code changed.
- 2026-11-16 | M6 Step 12 Slim engine + adapters | Done. No DuckDB/pandas/numpy/pyarrow (284.8 MB, outputs identical, evaluation unchanged); Blob/Postgres adapters, claim, lease; 3 deferred + 2 HIGH review fixes. 411 Python + 60 frontend tests passing, CI green.
- 2026-11-16 | M6 Step 13 Queue jobs, limits, cron | Done. Queue consumer with 240 s deadline and retries, cron cleanup, storage and daily caps, frontend states and URL resume, Chicago trimmed to 3,995 rows. 450 Python + 100 frontend tests, evaluation unchanged.
