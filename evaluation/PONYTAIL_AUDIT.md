# Ponytail audit: Data Cleaner before the Vercel deployment

Date: 2026-11-16. Commit audited: c13780e (main). Report only: no code, test or doc was changed.
Method: read the backend, the engine entry points, the config and deploy files, the Step 12 and 13 tests by name, and searched the tree for every "unused" claim. Nothing was run.

## 1. Map

**What the repo does.** A visitor uploads a messy CSV or Excel file (4 MB at most on the live site). The engine finds problems, the visitor approves fixes, and the site returns a clean file, a report, a recipe and a change log.

**Entry points**

| Entry | File | What it does |
|---|---|---|
| Website | `frontend/src/App.tsx`, six screens | Upload, profile, fixes, processing, results, downloads. Polls the job every 2 s, then 5 s. |
| API | `backend/main.py` (`app`), `backend/routes.py` | Upload, start profile, start clean, job status, results, downloads. |
| Queue consumer | `backend/worker.py` (`consume`) | Runs one job per message. Listed in `pyproject.toml` under `[[tool.vercel.subscribers]]`. |
| Cron | `backend/cron.py` (`/api/cron/cleanup`) | Daily: delete expired data, fail stuck jobs, recount stored bytes. |
| Engine | `engine/pipeline.py` (`inspect`, `profile`, `build_plan`, `clean`, `build_xlsx`) | The only surface the backend calls. |
| Evaluation | `evaluation/run_evaluation.py` | Recall and precision numbers. Also run by `tests/engine/test_evaluation.py`. |

**Data flow.** Upload (checked on a temp file, then stored) → `POST /profile` writes a job row and sends a queue message → the consumer downloads the original, profiles it, saves the profile in the database and the parsed table (Parquet cache) in storage → the visitor decides → `POST /clean` stores `plan.json`, writes a job row, sends a message → the consumer replays the plan and uploads five files → `GET /results` and downloads read them. Excel is built on the first download request.

**Assumed load.** A portfolio demo: a few visitors a day, one file each, 4 MB, no logins. Bursts are one person clicking twice. Platform limits that matter (from `docs/ADR-hosting-vercel.md`): 300 s per function, 2 GB memory, 4.5 MB request body, 500 MB bundle, Blob free store 1 GB with 10,000 simple and 2,000 advanced operations a month, Neon free 1 GB, Cron once a day. Going over a Hobby limit locks the feature for 30 days.

**Size.** Backend 1,821 lines, engine about 3,000, evaluation scripts 1,564, frontend about 3,900 (screens and tests), 450 Python tests.

## 2. Findings, ranked by what to fix first

Buckets: **KEEP** (a documented limit, correctness or security, or a test that fails without it), **SIMPLIFY** (justified but heavier than needed), **CUT** (unused or duplicate). A missing guard that should be added is marked "KEEP, add".

### Must fix before deploy

**1. The Blob operations budget is not guarded, and the code spends it fast.** Bucket: SIMPLIFY (the calls) plus KEEP, add (the guard).
- Where: `backend/storage.py:271-284` (`exists`, `list_keys`, `delete_prefix` all call the list API), `backend/limits.py:89-93` (`MeteredStorage.delete_prefix` lists twice), `backend/routes.py:296,307` (every download calls `exists`), `backend/jobs.py:250-253` (lists runs after each clean), `backend/cleanup.py:34`.
- Why it matters: The ADR says Hobby gives 2,000 advanced Blob operations a month. As I understand Vercel's pricing, uploads and list calls are the advanced kind (I did not confirm this; check the Blob usage page after one full run). One visit (upload, profile, clean, download all five files, build Excel) is roughly 25 or more of them by my count of the code paths. That is about 80 visits a month. The caps in the code (300 uploads and 200 jobs a day, 20 uploads a day per visitor) allow about 6,000 uploads a month, so they never protect this quota. The project rule is that the app must refuse politely before a firm limit.
- Fix: (a) In one test with the fake Blob client, count calls for one full visit and print them. (b) Replace `exists` with a direct head or get call, and make `MeteredStorage.delete_prefix` list once (list, sum sizes, delete). (c) Set `DC_DAILY_UPLOAD_CAP` from the measured number (budget divided by calls per visit, for example 1,500 divided by 15 is 100 visits a month, so about 3 a day). (d) Optionally add a monthly counter in the existing `Counter` table keyed by month. No schema change.

**2. The development cleanup loop also starts in production.** Bucket: SIMPLIFY.
- Where: `backend/main.py:91-92`. The comment says "Development only", but nothing checks it. `backend/cleanup.py:34` lists the whole store.
- Why it matters: If Vercel runs the app's startup hook, every new function instance runs `cleanup_expired` at once. That is one full Blob listing per cold start (finding 1), and it races the daily cron. I did not verify whether Vercel's Python runtime runs lifespan.
- Fix: start the loop only when `settings.job_runner == "inprocess"`. One line. Production cleanup stays with the cron.

**3. One failed status request stops polling for good.** Bucket: KEEP, add.
- Where: `frontend/src/lib/useJobPolling.ts:41-43`.
- Why it matters: On Vercel the first request after idle takes about 15 s with a cold function plus Neon wake (ADR measurements). A single 502 or timeout calls `onError` and the visitor sees a failure for a job that is still running. This was deferred in HANDOFF; production makes it real.
- Fix: in `tick`, count consecutive failures and call `onError` only after 3. About 8 lines plus one test in `ProcessingScreen.test.tsx`.

### Should fix

**4. A small Excel file can expand to a huge table.** Bucket: KEEP, add.
- Where: `backend/storage.py:303-307` (`looks_like`) checks only that the zip has the right parts. `engine/ingest.py` has no row or cell cap outside the header scan.
- Why it matters: A 4 MB .xlsx can hold hundreds of MB of XML. The profile job loads the whole sheet as text into memory (2 GB limit). When the function dies, the job waits for its lease, is claimed again, and can crash three times (`job_max_attempts = 3`), burning about 15 minutes of function time per bad file.
- Fix: in `looks_like`, sum `ZipInfo.file_size` over the entries and reject above a set size (for example 60 MB uncompressed). About 5 lines. The 14 bundled files are far below it, so outputs do not change.

**5. The daily cron has no time budget.** Bucket: KEEP, add.
- Where: `backend/cron.py:36`, `backend/cleanup.py:25-45`. Deletes run one dataset at a time, each with several Blob calls.
- Why it matters: At the daily upload cap, a day's worth of deletes could approach the 300 s function limit and the run would be cut. It is safe to resume (the next run continues) but the cut-off is silent.
- Fix: stop after about 200 s and return `{"partial": true}`. About 4 lines. Becomes unimportant once finding 1 lowers the cap.

**6. The Excel wait can outlast the function.** Bucket: SIMPLIFY.
- Where: `backend/jobs.py:277` (`give_up = 3 * 120 s = 360 s`) in a synchronous request that sleeps in a loop.
- Why it matters: Vercel stops the function at 300 s. A request waiting on another builder gets a platform timeout instead of the clean `excel_failed` message. Building a 4 MB Excel file takes seconds.
- Fix: `give_up = time.monotonic() + XLSX_LEASE_SECONDS`. One line.

**7. The deployed bundle is just over Vercel's 250 MB mark.** Bucket: SIMPLIFY.
- Where: `requirements.txt:50-58` pins the `vercel` meta package and everything it pulls (`vercel-sandbox`, `vercel-workflow`, `vercel-cache`, `cryptography`, `cbor2`, `websockets`, `zstandard`, `h2`).
- Why it matters: The ADR measured 284.8 MB. Above 250 MB Vercel installs the dependencies at cold start, which cost 2.46 s in the spike logs. Code only imports `vercel.blob` and `vercel.queue`.
- Fix: try `vercel-blob` and `vercel-queue` alone (they are already listed as separate pins) and measure the install size. If the import paths still work and the size drops under 250 MB, keep it. This is unverified: if `vercel.blob` needs the meta package, drop the idea. Estimated gain: about 2.5 s on cold starts.

**8. A refused profile request still changes the dataset.** Bucket: SIMPLIFY.
- Where: `backend/routes.py:160-168`. The sheet and header row are saved, then `count_job` can answer 429.
- Why it matters: A visitor who hits the daily cap on a re-profile with a new sheet has silently changed the stored sheet. Deferred in HANDOFF.
- Fix: call `count_job` before the write. Swap two blocks, no new code.

**9. The clean-run folder cleanup is the most complex 25 lines in the backend.** Bucket: SIMPLIFY.
- Where: `backend/jobs.py:98-108` (`_active_clean_runs`) and `backend/jobs.py:248-256`.
- Why it matters: Every saved clean lists the runs folder, works out which other jobs might still be writing, and deletes the rest. Starting a profile already deletes old runs at once (`routes.py:170`).
- Fix: do the same in `start_clean` (delete the runs prefix before writing `plan.json`) and drop `_active_clean_runs` and the loop. A running older job removes its own folder when it learns it was superseded. Tests that must still pass: `test_old_clean_job_finishing_late_is_discarded`, `test_newest_clean_wins_when_two_cleans_overlap`. Not before deploy: medium risk.

**10. Old-database migration code that deletes tables.** Bucket: CUT.
- Where: `backend/db.py:117-121`. It inspects the database on every start and calls `drop_all` if the `job` table has no `attempts` column.
- Why it matters: The only old databases are local SQLite files that live 24 hours. In production it costs two extra round trips on each cold start, and `drop_all` on a shared database that happens to have a table called `job` is a trap. No test covers it (searched).
- Fix: delete the five lines. Developers delete `storage/app.db` once.

**11. Unused storage helpers.** Bucket: CUT.
- Where: `backend/storage.py:147-154` (`dataset_dir`, `original`, `file`) and `backend/storage.py:291` (`Storage = LocalStorage`, "the pre-Step-12 name"). Searched `backend`, `tests`: no caller. `run_dir` (line 156) is used by tests, so it stays.
- Fix: delete about 12 lines.

**12. Unused frontend files and a stray dependency.** Bucket: CUT.
- Where: `frontend/src/components/ui/checkbox.tsx` (28 lines) and `tabs.tsx` (81 lines) have no importer. `frontend/src/assets/react.svg`, `vite.svg`, `hero.png` are template leftovers, not imported anywhere in `frontend/src`. `frontend/package.json:22` lists `shadcn` (the code generator) under `dependencies`; nothing imports it.
- Fix: delete the files and move `shadcn` out. Run `npm run build` and `npm test` to confirm. About 110 lines and 3 assets.

**13. A timing script that its own notes call stale.** Bucket: CUT.
- Where: `evaluation/stage_timing.py` (179 lines). `HANDOFF.md:101` says it "times a function clean no longer calls". It has no test. `evaluation/timing.py` (tested by `tests/engine/test_timing.py`) covers the same ground.
- Fix: delete it and the two sentences in `evaluation/TIMING.md` that mention it.

### Nice to have

**14. Every status poll runs two writes for everyone's jobs.** Bucket: SIMPLIFY.
- Where: `backend/routes.py:181`, `backend/db.py:195-208`. Each `GET /jobs/{id}` expires all stuck jobs in the database.
- Fix: expire only the polled job (add `Job.id == job_id`); the cron still does the global sweep. Keep `test_cron_expires_a_stuck_running_job`.

**15. `counter_set` catches the error in the wrong place.** Bucket: SIMPLIFY.
- Where: `backend/db.py:272-279`. `session.add` does not raise; the `IntegrityError` appears at `commit()`, outside the `try`. Two simultaneous first-time calls could fail the cron run (it recovers the next day).
- Fix: move `commit()` inside the `try` and roll back. Two lines.

**16. `MeteredStorage` copies `upload_dir`.** Bucket: SIMPLIFY.
- Where: `backend/limits.py:95-99` duplicates `StorageBackend.upload_dir` (`storage.py:119-123`) only because the wrapper delegates by `__getattr__`.
- Fix: make the base `upload_dir` call `self.put_file` (it already does) and have `MeteredStorage` subclass `StorageBackend` instead of using `__getattr__`. About 8 lines. Low value, do after launch.

**17. Cache keys are versioned three ways.** Bucket: SIMPLIFY.
- Where: `engine/cache.py:28-32,41`. `CACHE_VERSION`, `ENGINE_VERSION` and the source-code fingerprint are all in the key; the fingerprint alone already changes on any code change. A cache miss also hashes the file twice (noted in HANDOFF).
- Fix: drop the two manual versions. Keep `tests/engine/test_ingest_cache.py` passing. Not worth touching before deploy.

Smaller items left out (3): the CORS list is not needed on Vercel's same-origin setup but is harmless; the `cn` npm package name (`frontend/src/lib/utils.ts`) should be double-checked; the `Settings` dataclass has 15 fields, all used.

### KEEP list (looked heavy, but required)

| Thing | Where | Why it stays |
|---|---|---|
| Claim, lease, deadline, retry, superseded | `backend/db.py:126-208`, `jobs.py:111-178`, `worker.py` | ADR consequences 2 and 3 (300 s limit, at-least-once delivery). Tests: `test_job_claim.py` (6), `test_queue_worker.py` (22). |
| Dataset generation guard (`save_if_current`) | `backend/db.py:135-144` | An old job must never overwrite a newer result. `test_old_*_job_finishing_late_is_discarded`. |
| 4 MB limit, early rejection middleware | `backend/main.py:25-77`, `storage.py:126` | Chunked uploads have no Content-Length. `test_upload_without_content_length_stops_once_over_the_limit`. |
| Content sniffing for uploads | `backend/storage.py:298-313` | A renamed file must not pass on its extension. Security. |
| 800 MB storage guard and byte counter | `backend/limits.py`, `cron.py` | Blob free store is 1 GB. `test_upload_refused_when_storage_is_full`, `test_cron_recomputes_the_byte_total`. |
| Per-visitor daily caps with hashed IP | `backend/limits.py:36-53` | Firm Hobby limits. `test_ip_key_hides_the_address_and_changes_with_the_salt`. |
| Cron secret check | `backend/cron.py:21-27` | Security. `test_cron_rejects_missing_wrong_and_unset_secret`. |
| Excel built on demand under a lease | `backend/jobs.py:270-293` | Excel writing was half the clean time; the lease stops double builds across instances. `test_xlsx_on_download.py`, `test_excel_is_built_on_first_request_and_kept_for_the_run`. |
| Postgres adapter details (`prepare_threshold=None`, URL normalising) | `backend/db.py:101-116` | Neon pooled URL (ADR update after Step 12). `test_step12_adapters.py`. |
| Parquet read-once cache | `engine/cache.py` | Profile and clean run in separate invocations; saves a full re-parse. `test_ingest_cache.py`, `test_cache_concurrency.py`. |
| Engine libraries (charset-normalizer, clevercsv, ftfy, rapidfuzz) | `engine/ingest.py`, `parsing.py`, `rules/` | Named in CLAUDE.md as the chosen stack. Swapping them risks the byte-identical outputs. |
| Evaluation harness and `results.json` | `evaluation/run_evaluation.py` | The "zero damaged cells" proof. `test_evaluation_guard_rails`. |
| Sample copies in `frontend/public/samples` | `frontend/public/samples/` | "Try a sample file". `tests/engine/test_frontend_samples.py`. |
| Report HTML escaping | `engine/report.py` | Checked: values go through `escape`. Security. |

### Shortcut ledger (/ponytail-debt)

`git grep` for `shortcut:` and `ponytail:` comment markers found **0 markers, 0 with no trigger.** There is no marked debt, but several deliberate shortcuts carry no marker: the stored-bytes counter drifts until the cron recounts (`limits.py:72-73` says so in prose), the polling stop (finding 3), the per-IP cap that skips requests without a forwarded address (`limits.py:29-33`). Each should get a one-line `shortcut:` comment with its ceiling and trigger when touched.

## 3. Verdict

**Yes, the backend control layer is over-built for a portfolio project on a free plan, but the engine is not.** The API and job layer is 1,821 lines, about 60 percent of the size of the cleaning engine, and the evaluation scripts add 1,564 more. Three biggest reasons: (1) The job machinery (claims, leases, generations, deadlines, retries, supersede logic, a copy of it for the Excel build) is built for concurrency a site with a few visitors a day will not see; most of it is justified by Queues' at-least-once delivery, so it stays, but finding 9 shows it keeps growing. (2) Four layers of guards protect quotas that will not bind (daily job and upload caps) while the quota most likely to bite, Blob advanced operations, has none (finding 1). (3) Dead weight keeps accumulating: unused UI parts, template assets, a stale timing script, migration code for databases that no longer exist (findings 10 to 13). Nothing here is dangerous to ship; the work is to measure Blob use first, then delete.

## 4. Changes to make before the Vercel deployment

All keep: all tests passing, byte-identical outputs on the 14 bundled files, unchanged evaluation numbers, the 4 MB limit. None of them touches `engine/`; finding 17 is deliberately left for later.

| Order | Change | Finding | Effort | Risk |
|---|---|---|---|---|
| 1 | Count Blob calls for one full visit in a test, then cut list-based `exists` and the double list in `MeteredStorage.delete_prefix`, then set the daily upload cap from the budget | 1 | 3 to 4 h | Low to medium (storage tests catch it) |
| 2 | Start the cleanup loop only for the in-process runner | 2 | 15 min | Very low |
| 3 | Poll retry (3 consecutive failures) with one test | 3 | 1 h | Low |
| 4 | Reject zip files that expand past a set size | 4 | 1 h | Low |
| 5 | Excel wait limit 360 s to 120 s | 6 | 10 min | Very low |
| 6 | Cron stops after about 200 s | 5 | 1 h | Low |
| 7 | Count the job before writing sheet and header row | 8 | 20 min | Very low |
| 8 | Delete the dead code in findings 10 to 13, then run all suites and `npm run build` | 10 to 13 | 1 h | Low (grep shows no callers) |
| 9 | Try the slimmer Vercel dependencies and measure the size | 7 | 2 h | Medium, may give nothing, so time-box it |

Total about 10 to 11 hours. Steps 1 to 3 matter most. Also for Step 14 itself (not an audit finding): `vercel.json` today holds only the cron entry, and `backend/main.py` is not one of the default FastAPI entrypoint locations Vercel looks for, so routing the website, the API and the entrypoint needs to be copied from the spike. I did not check the spike folder for how it was solved.

## Not checked

- `engine/parsing.py`, `engine/profile.py`, `engine/ingest.py` (beyond the lines cited) and the ten rule files: read only by name and size. The engine's correctness is covered by the evaluation, not by this audit.
- The frontend screens (`FixesScreen.tsx`, `ResultsScreen.tsx`, `UploadScreen.tsx`) and their tests: only `useJobPolling.ts` and the dependency list were read.
- `docs/` and the BA documents (owned by the project owner), `evaluation/RESULTS.md` and the Chicago hand-check.
- Nothing was run: the call counts in finding 1 come from reading the code, and the Blob "advanced operation" classification and the lifespan behaviour on Vercel are unconfirmed.
