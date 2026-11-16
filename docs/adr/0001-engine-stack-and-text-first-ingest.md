# ADR 0001: Engine stack and text-first ingest

- Status: Accepted. Partly superseded on 2026-11-16: DuckDB and pandas were removed from the engine (Polars counts and openpyxl reading instead), see docs/ADR-hosting-vercel.md.
- Date: 2026-11-11

## Context
Messy files lose information when a reader guesses types too early (leading zeros in zip codes, mixed date formats, "N/A" in numeric columns).

## Decision
- Read every cell as text at ingest. Type decisions are made later by rules, with a confidence score and a change log entry.
- Polars for transforms, DuckDB for profiling queries, pandas only to read Excel.
- The engine is a plain Python package with no web code. The backend calls `engine.pipeline` only.

## Consequences
- Nothing is silently converted; every type change is logged and reversible from the change log.
- Type inference is our own code (in profile and rules), so it needs good tests.
- The engine can be reused from a CLI or notebook without the website.
