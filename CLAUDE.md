# Data Cleaner (Phase 1 MVP)

A website where a user uploads a messy CSV or Excel file. The system profiles and cleans it in the background and returns a clean file, a cleaning report, a reusable recipe and a change log.

**The single source of truth for interfaces is [docs/CONTRACT.md](docs/CONTRACT.md). Read it before writing any code.** If code and contract disagree, stop and report; do not silently change either.

## Stack
- **Engine** (`engine/`): Python 3.12, Polars (transforms), DuckDB (profiling), pandas only at the edges (Excel reading). charset-normalizer, clevercsv, ftfy, rapidfuzz, pyyaml, pydantic.
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
- Work in milestones M0 to M5 (see README). After each milestone: STOP, summarise in under 150 words (files created, tests passing, open questions), wait for "go".
- The BA documents in `docs/` (BRD.md, USER_STORIES.md, PROCESS_MAPS.md) belong to the project owner. Never write or edit them.

## Commands
```bash
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -e ".[backend,dev]"
pytest -q                                           # engine + API tests
uvicorn backend.main:app --reload --port 8000       # from M3
cd frontend && npm install && npm run dev           # from M4
```
