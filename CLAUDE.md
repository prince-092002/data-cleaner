# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Data Cleaner (Phase 1 MVP)

A website where a user uploads a messy CSV or Excel file. The system profiles and cleans it in the background and returns a clean file, a cleaning report, a reusable recipe and a change log.

**The single source of truth for interfaces is [docs/CONTRACT.md](docs/CONTRACT.md). Read it before writing any code.** If code and contract disagree, stop and report; do not silently change either.

## Stack
- **Engine** (`engine/`): Python 3.12, Polars (transforms and profiling counts), openpyxl read-only (Excel reading). No DuckDB, pandas, numpy or pyarrow at runtime. charset-normalizer, clevercsv, ftfy, rapidfuzz, pyyaml, pydantic.
- **Backend** (`backend/`): FastAPI + Pydantic, BackgroundTasks, SQLite via SQLModel (jobs table), files under `./storage`, deleted after 24 hours.
- **Frontend** (`frontend/`): React + TypeScript + Vite + Tailwind CSS + shadcn/ui. Not Streamlit.
- **Tests**: pytest (`tests/engine`, `tests/api`), Vitest (frontend logic).
- No login. No AI/LLM features in Phase 1.

## Core design rules (do not break these)
1. Never modify the original upload.
2. Every rule is a function: `(dataframe, column, params) -> (new dataframe, list of change records)`.
3. Each rule declares: `id`, `trigger(profile)`, `apply()`, `is_destructive`, `default_mode` (auto | suggest | flag).
4. Auto-apply only safe, reversible fixes. Anything destructive or judgment-based is a suggestion the user must approve.
5. Confidence thresholds: >= 0.98 auto, 0.80 to < 0.98 suggest, < 0.80 skip.
6. Every changed cell is logged: run_id, rule_id, rule_version, row_id, column, old_value, new_value, action (auto | approved), timestamp.
7. The engine has zero web code. The backend only calls `engine.pipeline`.

## Phase 1 rules (exactly these 10, no more)
normalize_headers, drop_empty_rows_and_columns, trim_and_normalize_text, standardize_null_tokens, coerce_numeric, parse_dates, standardize_booleans, remove_exact_duplicate_rows, standardize_categories, flag_outliers. Modes and behaviour are in CONTRACT.md section 2.

## Token rules
- One task per agent call. Never "build everything".
- Read CONTRACT.md plus only the files the task needs. Do not scan the whole repo.
- Look at data with `head` or a 50-row sample, never the full file.
- Verify by running tests, not by printing large outputs.
- Agents stop after about 20 steps and report back if stuck.
- No web searching; the libraries above are already chosen.

## Helper agents (`.claude/agents/`)
| Agent | Model | Job |
|---|---|---|
| engine-builder | sonnet | `engine/` modules with tests |
| api-builder | sonnet | `backend/` with tests |
| web-ui-builder | sonnet | `frontend/`, one screen at a time, API calls only |
| test-data-qa | haiku | sample files, error injection, test runs, evaluation |
| reviewer-explainer | opus | read-only review against CONTRACT.md, plain-language explanations |

Each agent works alone on one task, reads CONTRACT.md first, reads only the files named in its task, and replies in under 150 words.

## Handoff rules
- At the start of every new session, read [HANDOFF.md](HANDOFF.md) and docs/CONTRACT.md first, before anything else.
- Update HANDOFF.md at the end of EVERY milestone, before giving the owner the summary.
- Rewrite "Current position", "Last milestone summary" and "Next steps" each time. Append to "Decisions made" and "Milestone log"; never delete old entries.
- Keep HANDOFF.md under 150 lines. Summarize older decisions if it grows.
- CONTRACT.md holds the technical rules. HANDOFF.md holds progress and status. Do not mix them.

## Working agreement
- Work in milestones (M0 to M5 done, see README; M6 in progress, see HANDOFF.md). After each milestone: STOP, summarise in under 150 words (files created, tests passing, open questions), wait for "go".
- The BA documents in `docs/` (BRD.md, USER_STORIES.md, PROCESS_MAPS.md) belong to the project owner. Never write or edit them.

## Commands
```bash
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -e ".[backend,dev]"
pytest -q                                           # engine + API tests (~500; some are marked slow but still run by default)
pytest tests/engine/test_rules.py -q                # one file
pytest tests/engine/test_rules.py::test_name -q     # one test
pytest -q -m "not slow"                             # skip the 1-2 minute tests
python sample_data/make_samples.py                  # regenerate the 3 messy samples + ground_truth.csv
python evaluation/run_evaluation.py                 # recall / precision / damaged-cell evaluation
uvicorn backend.main:app --reload --port 8000       # API docs at /docs
cd frontend && npm install && npm run dev           # port 5173, proxies /api to 8000
cd frontend && npm test                             # Vitest, already "vitest run" (one file: npm test -- src/screens/FixesScreen.test.tsx)
cd frontend && npm run lint                         # oxlint
cd frontend && npm run build                        # tsc -b && vite build
cd frontend && npm run build:browser                # live-site build: bundles engine/ + browser/ into public/py/bundle.json, VITE_ENGINE=browser
```
Env vars: `DC_STORAGE_DIR` (default `./storage`), `DC_CORS_ORIGINS`. Server-mode deploy vars (`DATABASE_URL`, `DC_STORAGE_BACKEND`, `DC_JOB_RUNNER`, caps) are listed in README "Deploying" and `.env.example`.

## Architecture (the parts that span files)
- **Pipeline is the only engine surface.** `engine/pipeline.py` exposes `inspect` → `profile` → `build_plan` → `clean` (CONTRACT section 7). `backend/routes.py` and `backend/jobs.py` call only these.
- **Two-pass flow.** `profile()` runs a dry run of every rule's candidates in registry order (`engine/rules/registry.py`) to produce `Proposal`s with true `rows_affected` and before/after samples. The user's decisions go through `build_plan()` to an `ApprovedPlan`, which `clean()` replays, writing the clean file, change log CSV, recipe YAML and HTML report.
- **Read-once cache.** `engine/cache.py`: `profile()` saves the parsed all-text table as Parquet (keyed by content hash, sheet, header row, `ENGINE_VERSION` and a hash of the engine source, so any engine code change misses) and `clean()` reuses it.
- **Shared parsing.** `engine/parsing.py` holds the value parsers used by both the profiler and the rules so they cannot disagree. Add parsing logic there, not in a single rule.
- **Rules** live one per file in `engine/rules/`, share `engine/rules/base.py`, and may define an optional `prepare(df, column, params)` for params that depend on data (date order, category mapping).
- **Data conventions:** empty cells are null at ingest, Excel values are read as text, and columns keep the uploaded header until `normalize_headers` runs.
- **Backend:** upload → `POST /profile` job → `POST /clean` job; jobs are rows in SQLite polled via `GET /api/jobs/{id}`. Starting a new profile deletes the dataset's old results; expired datasets (24 h) return 404.
- **Two runtimes, one engine.** The live site (Vercel, static `vercel.json`) runs the unchanged engine in the visitor's browser: `frontend/src/worker/engine.worker.ts` loads Pyodide and calls `browser/adapter.py`, which must return the same JSON and error codes as `backend/routes.py`; `browser/shims/` replaces clevercsv and rapidfuzz. `api/client.ts` routes every call to `api/browserEngine.ts` when `VITE_ENGINE=browser`, otherwise to the server. A change to the route contract must be mirrored in the adapter. Server mode (local; SQLite/disk by default, Postgres/Vercel Blob/Queues via env vars) is unchanged. Details: README "Deploying", CONTRACT 8.12.
- **Frontend:** six screens in `frontend/src/screens/` driven by `state/AppState.tsx`; all HTTP goes through `api/client.ts` with types in `api/types.ts`. Bundled "Try a sample file" copies in `frontend/public/samples/` must match `sample_data/` (guarded by `tests/engine/test_frontend_samples.py`).
- **CONTRACT changes:** when a contract decision changes, record it under "Decisions made" in HANDOFF.md with the reason.
