# ADR: Hosting on Vercel (Hobby plan)

- Status: Accepted (owner's go for Step 12 on 2026-11-16)
- Date: 2026-11-15
- Evidence: a throwaway spike on branch `spike-vercel` (folder `spike/`, never merged), deployed as the separate Vercel project `data-cleaner-spike`.

## Context
The plan is to host the site for free: code on GitHub, site on Vercel Hobby. Today the backend runs cleaning jobs inside the API process (FastAPI BackgroundTasks), keeps jobs in SQLite and files under `./storage`. None of that survives on Vercel: functions are short-lived, the disk is temporary, and work started after the response is not guaranteed to finish. Step 11 tested whether the product fits, before any real code is changed.

## Decision
**Go.** Host on Vercel Hobby with these parts, all free:

| Need | Choice |
|---|---|
| Website | Static build of `frontend/` served by Vercel |
| API | FastAPI as one Vercel Function (Python 3.12) |
| Background jobs | **Vercel Queues, push consumer** (Beta). The API creates a job row and sends a message; a private consumer function runs the engine and writes progress to the job row; the browser polls the row as it does today. |
| Jobs and dataset rows | Neon Postgres (Vercel Marketplace, Free plan), replacing SQLite |
| Files (uploads, outputs, cache) | Vercel Blob, private store, replacing `./storage` |
| Engine | The slim dependency set (no DuckDB, pandas, numpy or pyarrow) |

**Fallback if Queues is withdrawn or changes:** run the job inside the request and keep the same job row for progress. It was tested and works (below), with the costs listed under Consequences.

## What was measured (2026-11-15)
Preview deployments, Deployment Protection left on, reached with `vercel curl`.
- Mechanism test: `https://data-cleaner-spike-5y9blxpsz-prince-092002s-projects.vercel.app`
- Real engine test: `https://data-cleaner-spike-8dd4bof5m-prince-092002s-projects.vercel.app`

"Re-checked" means the coordinator repeated the test after the agent's report.

| Test | Result | Re-checked |
|---|---|---|
| Queue job, 20 one-second steps written to Postgres | Step 1 arrived 1.9 s after the send; separate status requests saw steps 5, 12, 17, 20; finished on delivery 1 | Yes |
| Queue consumer running 90 s and 280 s | Both finished on the first delivery | Logs read |
| Queue consumer running 400 s | Killed at 300 s (`Task timed out after 300 seconds`), then redelivered about every 5 minutes from step 1. `max_attempts=2` did not stop it: delivery 3 is in the logs | Logs read |
| Fallback: job inside the request, client cut after 3 s | The job still reached step 20 | No |
| Blob: write, read, delete | All worked with a private store and no token (OIDC through `BLOB_STORE_ID`) | No |
| Postgres: connect, insert, read | Worked. Connect 26 to 29 ms warm, 81 to 82 ms on a new function instance | No |
| Neon wake after 7 minutes idle (measured 2026-11-16, three rounds 7 minutes apart, after the retrying deployment was deleted) | First connect 587, 600, 577 ms; a second connect right after 25, 23, 30 ms. Wake cost about 0.56 s. The first HTTP request took about 5 s in total, mostly function cold start | Results file read |
| Unmodified engine build | Failed: `Total bundle size (590.33 MB) exceeds the maximum function size (500 MB)` | Deployment status read |
| Slim engine build | 270.73 MB, passed. Above 250 MB Vercel ships a 65.42 MB function and installs the dependencies at cold start (2.46 s in the logs) | No |
| Chicago sample (3,995 rows, 3,999,150 bytes), warm | Profile 3.3 s, clean 5.8 s, total 9.2 s, peak memory 198 MB. Same machine locally: 2.0 s and 3.5 s | Yes |
| Chicago sample, cold (14 minutes idle) | 14.85 s for the whole request | No |
| Output equal to the local unmodified engine | Demo file: 120 rows, Region South 27 / North 19 / West 35 / East 33 / blank 6, clean.csv SHA-256 identical. Chicago cut: SHA-256 identical, score 95.7 to 99.4 | Yes |

Peak memory is the function's own `ru_maxrss` figure; Vercel's CLI logs show no memory number.

## Limits that shape the design
All read on 2026-11-15.

| Limit | Value | Source |
|---|---|---|
| Function duration, Hobby | 300 s maximum | https://vercel.com/docs/functions/limitations |
| Function memory, Hobby | 2 GB, 1 vCPU | https://vercel.com/docs/functions/limitations |
| Request and response body | 4.5 MB | https://vercel.com/docs/functions/limitations |
| Python function bundle | 500 MB uncompressed | https://vercel.com/docs/functions/limitations |
| Python version, FastAPI entrypoint, `public/` | 3.12, `app` in `main.py` | https://vercel.com/docs/functions/runtimes/python and https://vercel.com/docs/frameworks/backend/fastapi |
| Queues on Hobby | Beta, first 1,000,000 operations free, retention 24 hours by default (60 s to 7 days per message) | https://vercel.com/docs/queues/pricing and https://vercel.com/docs/queues/concepts |
| Queues retries | Retried until acknowledged or expired; a timed-out delivery is billed for the full duration; the documented way to stop a failing deployment's consumers is to delete the deployment | https://vercel.com/docs/queues/concepts |
| Queues Python SDK | `send`, `@subscribe`, `[[tool.vercel.subscribers]]` in `pyproject.toml`, `retention` on send, `RetryAfter` | https://vercel.com/docs/queues/python-sdk |
| Blob on Hobby | 1 GB storage, 10 GB transfer, 10,000 simple and 2,000 advanced operations a month | https://vercel.com/docs/vercel-blob/usage-and-pricing |
| Blob from Python | `put_blob`, `get_blob`, `delete_blob`, private access | https://vercel.com/kb/guide/python-and-vercel-blob |
| Neon Free | 1 GB, 100 compute-hours a month, sleeps after 5 minutes idle (cannot be turned off) | https://neon.com/docs/introduction/scale-to-zero |
| First deploy of a new project | Always production | https://vercel.com/docs/cli/deploy |
| Protected previews | `vercel curl` adds the bypass itself | https://vercel.com/docs/cli/curl |

## Consequences
1. **Engine dependencies change (CONTRACT change, owner decision).** DuckDB, pandas, numpy and pyarrow must go from the deployed engine; Polars and openpyxl cover their work. The slim copy passes the 326 engine tests and produced byte-identical output on both test files.
2. **Every job must finish well inside 300 s.** The consumer needs its own time budget (stop at about 270 s, mark the job failed, return normally so the message is acknowledged). Messages are sent with a short `retention` (for example 15 minutes) so a poisoned message dies quickly. `max_attempts` is not relied on.
3. **Consumers must be idempotent.** Delivery is at least once. A consumer first checks the job row and does nothing if the job is already finished or failed.
4. **Upload size on the live site stays at 4 MB** through the API (4.5 MB body limit). Raising it means uploading from the browser straight to Blob. Even then, time and memory cap it: 47.5 MB takes about 200 s and 1.8 GB locally, and Vercel ran about 1.6 times slower than the local machine, so that size does not fit. Local runs keep the 50 MB limit.
5. **No local disk between requests.** Profile and clean are separate invocations, so the upload, the Parquet cache and the outputs live in Blob, and the profile and results stay in the Dataset row (already done in M6.4). `/tmp` is working space only.
6. **Downloads over 4.5 MB cannot pass through the function.** They need a signed Blob link or a streamed response.
7. **First request after idle is slow** (about 15 s cold for a 4 MB file, plus the Neon wake). The UI already shows progress; the first status poll must tolerate it.
8. **If the fallback is used instead of Queues:** the job runs in the request that started it. It survived a dropped connection in one test, but that behaviour is not documented, there is no retry, and the request stays open for the whole job.

## What would make us revisit
- Queues leaves Beta with a price, a lower free allowance or a shorter consumer limit.
- Users need files larger than the limit above, or jobs approach 300 s or 2 GB.
- The bundle grows back toward 500 MB (a new heavy dependency).
- Neon compute-hours or Blob operations run out on the free plans.
- Any required feature turns out to need a paid plan. The project is free only.

## Update after Step 12 (2026-11-16)
- The engine no longer uses DuckDB, pandas, numpy or pyarrow. Outputs are byte-identical to the previous engine on all 14 bundled files (only ISO timestamps masked), and the evaluation numbers did not move.
- The deployed function's requirements (`requirements-vercel.txt`, now including the backend, `vercel` and `psycopg`) install to 284.8 MB on Linux, against the 500 MB limit.
- Postgres runs with prepared statements turned off (Neon's pooled URL goes through PgBouncer). The pooled URL also rejects the `search_path` startup option, so the Postgres tests, which use a throwaway schema, need the unpooled URL.
- The spike project's GitHub connection was removed on 2026-11-16. A push to the repo had created a deployment on it by itself.

## Update after Step 13 (2026-11-16)
- Jobs: `DC_JOB_RUNNER=queue` sends the job id to topic `dc-jobs` (15 minute retention). The consumer (`backend/worker.py`, listed in `pyproject.toml`) claims the job first, so a redelivery for a finished, failed, superseded or expired job does nothing. Each attempt has a 240 s deadline (claim lease 270 s, function limit 300 s); a job past it fails with `job_timeout` and the consumer returns normally, so the queue does not redeliver. Crashes not caused by the file are retried at most twice, counted in the database.
- Stuck jobs (queued or running past their deadline) are failed by the next status read and by the daily cleanup.
- Daily cleanup: `GET /api/cron/cleanup`, `Authorization: Bearer <CRON_SECRET>`, scheduled once a day in `vercel.json`. Vercel now calls Cron Jobs a legacy feature to be migrated to Schedules (beta), read 2026-11-16 at https://vercel.com/docs/cron-jobs. Cron still runs on Hobby once a day, anywhere within the scheduled hour, on production deployments only, with no retry. Revisit when Schedules leaves beta.
- Limits so the free plans are never exceeded: new uploads refused above 800 MB stored (Blob free store 1 GB); daily caps of 200 jobs and 5 uploads (interim, Step 14 sets it from the Blob measurement) for the site, 10 jobs and 20 uploads per visitor (salted hash of the `x-forwarded-for` address; no header means no per-visitor cap).
- Real Vercel Queues, Blob and Cron have only been exercised with fakes so far; the first real run is Step 14 on a preview deployment.
