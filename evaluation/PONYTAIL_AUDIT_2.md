# Ponytail audit 2: delta against the first audit

Date: 2026-11-16. Code audited: main at eadc4fc (all pre-deploy fixes merged, not pushed). Report only: no code, test or doc was changed. Nothing was run; every status below comes from reading the code and the test names.
Load assumed: same as audit 1, a demo with a few visitors a day, one 4 MB file each, on Vercel Hobby limits (Blob 2,000 advanced operations a month, 300 s functions).

## 1. Status of the 17 findings

Totals: 14 CLOSED, 1 PARTLY CLOSED, 2 DEFERRED.

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | Blob budget unguarded | PARTLY CLOSED | Done: `exists` is `head_blob` (`backend/storage.py:266-271`); `delete_prefix` lists once (`storage.py:279-284`); calls are counted and capped in `tests/api/test_blob_calls.py:16`. Open: the caps are not derived from the budget (new finding N1); the monthly counter was skipped on purpose. |
| 2 | Cleanup loop in production | CLOSED | `backend/main.py:92` starts it only when `job_runner == "inprocess"`; test `test_cleanup_loop_starts_only_for_the_inprocess_runner`. |
| 3 | One failed poll stops polling | CLOSED | `frontend/src/lib/useJobPolling.ts:33-48` (3 in a row, 404 fails at once); tests `does not show an error after two failed polls followed by a success` and `shows the error after three failed polls in a row` in `ProcessingScreen.test.tsx`. |
| 4 | Excel size bomb | CLOSED | `backend/storage.py:26,307` (60 MB uncompressed); test `test_xlsx_that_expands_past_the_limit_is_rejected`. |
| 5 | Cron has no time budget | CLOSED | `backend/cron.py:19,39-43` and `backend/cleanup.py:35,49`; test `test_cron_stops_at_its_budget_and_the_next_run_resumes`. |
| 6 | Excel wait outlasts the function | CLOSED | `backend/jobs.py:277` one lease of 120 s; test `test_excel_wait_is_one_lease_and_gives_the_clean_error`. |
| 7 | Bundle over 250 MB | DEFERRED | `requirements-vercel.txt` still pins `vercel`, `vercel-sandbox`, `vercel-workflow`, `vercel-cache`, `websockets`, `zstandard`. Known and accepted. |
| 8 | Refused profile changes the dataset | CLOSED | `backend/routes.py:160` calls `count_job` before the write; test `test_refused_profile_request_leaves_the_dataset_unchanged`. |
| 9 | Clean-run folder cleanup is complex | DEFERRED | `_active_clean_runs` and the listing loop are unchanged at `backend/jobs.py:98-108,248-256`. Known. |
| 10 | `drop_all` migration | CLOSED | No `drop_all` or `inspect` left in `backend/db.py` (grep). |
| 11 | Unused storage helpers | CLOSED | `dataset_dir`, `original`, `file` and `Storage =` are gone; grep over `backend` and `tests` finds no source match. `run_dir` kept (`storage.py:149`). |
| 12 | Unused frontend files and `shadcn` | CLOSED | `checkbox.tsx`, `tabs.tsx` and `src/assets/` are gone; each of the 9 remaining `components/ui` files has an importer; `shadcn` is a devDependency (`frontend/package.json:35`). |
| 13 | Stale timing script | CLOSED | `evaluation/stage_timing.py` is gone. One stale sentence remains in `HANDOFF.md:101` (see section 4). |
| 14 | Poll expires every job | CLOSED | `backend/routes.py:181` passes `job_id`; `backend/db.py:187-200` filters on it; test `test_job_poll_expires_only_that_job`. |
| 15 | `counter_set` wrong try | CLOSED | `backend/db.py:264-273` commits inside the `try` and rolls back; test `test_two_first_time_counter_set_calls_do_not_fail` (SQLite only, see section 4). |
| 16 | `MeteredStorage` copies `upload_dir` | CLOSED | `backend/limits.py:72` subclasses `StorageBackend`; `upload_dir` is no longer redefined, so the base one calls the metered `put_file`. |
| 17 | Cache keys versioned three ways | CLOSED | `engine/cache.py:27-53`: key is source fingerprint, sheet, header row and a content hash behind `lru_cache` on (path, size, mtime); no `CACHE_VERSION` or `ENGINE_VERSION` left. Tests `test_ingest_cache.py`, `test_cache_concurrency.py`. |

## 2. New findings

### Must fix (before or during Step 14)

**N1. The daily caps are not tied to the Blob budget, and the job cap is far above it.**
- Where: `backend/config.py:74-78` (jobs 200 a day, per visitor 10, uploads 5, per visitor 20); budget ceilings in `tests/api/test_blob_calls.py:16`.
- Case: one visit is at most 12 puts and 5 lists (4 in production, the fifth is the dev sweep). If puts and lists are the advanced kind (unconfirmed, check the Blob usage page), that is 16 to 17 operations. 5 uploads a day for 30 days is 150 visits, so about 2,400 to 2,550 operations, already over 2,000. Separately, re-cleaning one uploaded file costs about 9 of them each time (6 to 7 puts plus 2 lists), and 200 jobs a day are allowed, so a script that uploads once and re-cleans can spend about 1,800 in one day. Per-visitor caps do not help against it: see N3. Going over locks Blob for 30 days.
- Fix: in Step 14, set `DC_DAILY_UPLOAD_CAP` and `DC_DAILY_JOB_CAP` from the budget (for example 2 uploads and 10 jobs a day) and add one test that fails when `upload_cap * 30 * (put + list)` or `job_cap * 30 * 9` is above 2,000, using the numbers already in `MAX_CALLS`. No new code in the app.

### Should fix

**N2. Every page or filter click on the Results screen downloads and parses the whole change log.**
- Where: `backend/routes.py:233-252` (`_changes`), called from `get_results` (`routes.py:280`); the website calls it on each page and filter change (`frontend/src/screens/ResultsScreen.tsx:91`), and also from `ProcessingScreen.tsx:35` and `RestoreGate.tsx:31`.
- Case: the sample run in `storage/` turned a 7 KB file into a 62 KB change log, about 9 times. A 4 MB upload can therefore give a change log of about 35 MB. Each click then moves 35 MB from Blob and parses it row by row on a function with a 4.5 MB request limit but real latency of seconds. Ten clicks is 350 MB of Blob transfer (Hobby has a monthly transfer limit; check the number). `test_blob_calls.py` calls results once, so the budget test cannot see it.
- Fix: keep the downloaded file in the instance temp folder as `dc-changes/{run_id}.csv` and reuse it when present, deleting other run files first. Cold instances pay once, warm ones pay nothing. About 8 lines in `_changes`. Add one assertion to the blob test that a second results call adds no `get`.

**N3. One visitor can use all of the site's daily uploads, and the per-visitor cap is easy to dodge.**
- Where: `backend/config.py:77-78` (global 5, per visitor 20); `backend/limits.py:29-34,48`.
- Case: the per-visitor upload cap (20) is higher than the global one (5), so a single address that sends 5 small valid files makes the demo say "upload limit reached" for everyone until 00:00 UTC, every day. Also the key is the full address, so one IPv6 user has a new "visitor" per address in their block.
- Fix: set the per-visitor cap below the global one in Step 14 (for example 2 against 5), and key IPv6 by its first 4 groups: `ip = ":".join(ip.split(":")[:4]) if ":" in ip else ip`. One line, plus one test in `test_step13_limits.py`.

### Nice to have

**N4. A request that waits for the Excel build asks Blob and the database five times a second.**
- Where: `backend/jobs.py:278-293`.
- Case: a visitor double-clicks "Download Excel" while the first request builds the file. The second request loops every 0.2 s with two `head_blob` calls and one failing `INSERT` on the lease table each time (a duplicate-key error in the Neon log). A 10 s build is 100 Blob reads and 50 database errors.
- Fix: `time.sleep(1)` instead of `0.2`. The build takes seconds, so the wait grows by at most 1 s.

**N5. The daily cron lists the whole Blob store twice.**
- Where: `backend/cleanup.py:44` (`list_keys("")`) and `backend/cron.py:49` (`size_under("")`).
- Case: with 3,000 stored blobs that is 6 list calls a day, about 180 a month, around 9 percent of the advanced budget, to learn what one listing already shows.
- Fix: let the orphan sweep return the listing's total size and subtract what it deleted, or drop the recount to once a week. Small; do after N1.

**N6. A storage outage during a clean can hide its own error.**
- Where: `backend/jobs.py:240-247`.
- Case: Blob goes down while `upload_dir` runs. The `except BaseException` block then calls `_read_or_none` and `delete_prefix` on the same broken store; their errors replace the original `StorageError`, so `_run` does not fail the job with the clear "file store was not available" message and treats it as a crash to retry instead.
- Fix: wrap the cleanup lines in `contextlib.suppress(Exception)` and re-raise the original. Two lines.

## 3. Things that got worse

- Backend size grew from 1,821 to 1,843 lines even after the deletions: the new guards (cron budget, zip cap, lease deadline, failure counter) added more than the dead code removed. Fair trade, but audit finding 9 now sits beside more code.
- `frontend/package-lock.json` grew by 216 lines because `shadcn` moved to devDependencies. No runtime change.
- `HANDOFF.md:101` still lists the deleted `evaluation/stage_timing.py` as a known low issue. A documentation lie, no code impact.
- `README.md` and `docs/CONTRACT.md` have uncommitted edits (git status), so they can be lost if only the commits are pushed.
- The test for finding 15 runs on SQLite, which has a single writer, so it may pass even with the old bug; I did not run it against the old code to check.
- No new dependency was added to Python or the frontend runtime.

## Not checked

- The engine files, the other frontend screens, `errors.py`, and the real Blob and Queues behaviour (the fake in `tests/api/fake_blob.py` is the only thing tested; the "advanced operation" classification is unconfirmed).
- Nothing was run, including the tests.
