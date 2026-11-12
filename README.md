# Data Cleaner

Upload a messy CSV or Excel file. Get back a clean file, a cleaning report, a reusable recipe and a full change log.

> Status: Phase 1 (MVP) in progress. Milestones 0 to 3 complete (engine and API finished).

## What it does
1. **Upload** a `.csv` or `.xlsx` file (up to 50 MB).
2. **Profile**: per-column statistics and a 0 to 100 quality score.
3. **Suggest fixes**: safe fixes are applied automatically; judgment calls wait for your approval.
4. **Clean** in the background with a progress bar.
5. **Results**: before/after quality score and a filterable change log.
6. **Download** the clean file, HTML report, YAML recipe and change log.

## Architecture
```
frontend/ (React + TS + Vite + Tailwind + shadcn/ui)
    |  HTTP (JSON)
backend/  (FastAPI, BackgroundTasks, SQLite jobs table, ./storage)
    |  Python calls to engine.pipeline only
engine/   (Polars + DuckDB, 10 cleaning rules, zero web code)
```
Interfaces are defined in [docs/CONTRACT.md](docs/CONTRACT.md).

## Repo layout
| Path | Purpose |
|---|---|
| `engine/` | Pure Python cleaning engine: ingest, profile, rules, change log, recipe, report, pipeline |
| `backend/` | FastAPI app: routes, jobs table, storage, 24-hour cleanup |
| `frontend/` | React website (6-step flow) |
| `tests/` | Engine and API tests (pytest) |
| `sample_data/` | Messy test files and the error-injection script |
| `docs/` | CONTRACT.md, ADRs, BRD, user stories, process maps |
| `.claude/agents/` | The 5 helper agents |

## Setup
_To be completed in M5._

## Screenshots
_To be added in M5._

## Evaluation results
_To be added in M5 (precision and recall on injected errors)._

## Milestones
- [x] M0 Setup: structure, contract, agents
- [x] M1 Ingest, profile, quality score
- [x] M2 The 10 rules, change log, recipe, HTML report
- [x] M3 FastAPI backend with background jobs
- [x] M4 Website: 6 screens
- [ ] M5 End-to-end test, evaluation, review, final README

## Documents
- [Contract](docs/CONTRACT.md)
- [Architecture decisions](docs/adr/)
- [BRD](docs/BRD.md), [User stories](docs/USER_STORIES.md), [Process maps](docs/PROCESS_MAPS.md)
