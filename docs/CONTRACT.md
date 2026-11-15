# CONTRACT.md

The single source of truth for interfaces between the engine, the backend and the frontend. Version 1.0 (Phase 1).

If code and this document disagree, stop and report. Changes to this file need the project owner's approval.

Contents: 1 Terms · 2 Rule interface · 3 Profile schema · 4 Quality score · 5 Change log · 6 Recipe YAML · 7 Pipeline API · 8 HTTP API · 9 Storage

---

## 1. Terms and global conventions

| Term | Meaning |
|---|---|
| dataset | One uploaded file. Id is a random UUID4. |
| job | One background run (profile or clean). Id is a random UUID4. |
| run_id | UUID4 of one clean run. Equals the clean job's id. |
| `_row_id` | Integer column added at ingest: 1-based position of the data row in the source (first row after the header = 1). Never changes, never reused. Not written to clean.csv / clean.xlsx. |
| proposal | One thing a rule wants to do to one column (or the whole table). Shown in the UI as a "suggested fix". |
| mode | `auto` (applied unless rejected), `suggest` (applied only if approved), `flag` (adds information, changes no existing value). |

Conventions:
- **Text-first.** Ingest reads every cell as a string (`pl.Utf8`). Empty cells are `null`; a cell holding only spaces stays text. Excel numbers, dates and booleans are turned into text (`1200.5`, `2024-04-03`, `TRUE`). Types are decided by rules, not by the reader.
- **Dataframe columns before `normalize_headers`** carry the header text as uploaded, made unique only where needed (empty becomes `column_<n>`, repeats get `_2`). `IngestResult.source_names` keeps the exact uploaded text.
- **The original upload is never modified.** All outputs are new files.
- **Column names.** Every column has a `source_name` (as uploaded) and a `name` (after `normalize_headers`). Profiles, proposals, the change log and recipes use `name`.
- **Timestamps** are UTC ISO 8601, e.g. `2026-11-11T14:03:22Z`.
- **Confidence thresholds:** `>= 0.98` auto · `0.80 <= c < 0.98` suggest · `< 0.80` skip (no proposal).
- **Null tokens** (case-insensitive, after trimming): `""`, `NA`, `N/A`, `null`, `-`, `?`, `#N/A`, `TBD`.
- All JSON models below are Pydantic v2 models in `engine/models.py`. The backend re-uses them; it does not redefine them.

---

## 2. Rule interface

### 2.1 Shape

```python
# engine/rules/base.py
@dataclass
class Candidate:            # "this rule wants to act here"
    column: str | None      # None for table-scope rules
    params: dict
    confidence: float | None
    force_suggest: bool     # e.g. ambiguous dates
    note: str | None        # extra sentence for the proposal description
    auto_safe: bool         # only removes differences of case, accents or spacing (added M6)
    title: str | None       # proposal title instead of the rule label (added M6, name casing)

class Rule:
    id: str                 # e.g. "coerce_numeric"
    version: str            # semver, e.g. "1.0.0"; bump when behaviour changes
    scope: str              # "column" | "table"; table rules get column=None
    is_destructive: bool    # True if information can be lost (rows/columns removed, values merged)
    default_mode: str       # "auto" | "suggest" | "flag"
    severity: str           # "high" | "medium" | "low"
    label: str              # short title shown to the user
    explain: str            # one plain-language sentence
    editable_params: tuple[str, ...]

    def trigger(self, profile: DatasetProfile) -> list[Candidate]:
        """Read-only. Decide where this rule applies, from the profile alone."""

    def prepare(self, df, column, params) -> tuple[dict, float | None]:
        """Optional. Fill in params that depend on the data (date order, category mapping).
        Called once at profile time, on the data as it stands after the earlier rules.
        Returns (params, confidence or None to keep the candidate's)."""

    def left_alone(self, df, column, params) -> list[LeftAlone]:
        """Optional (added M6). Values the rule saw but will not change, each with a reason.
        Called once at profile time, just before the dry-run apply. Default: []."""

    def apply(self, df: pl.DataFrame, column: str | None, params: dict
              ) -> tuple[pl.DataFrame, list[ChangeRecord]]:
        """Pure function. Returns a NEW dataframe and one change record per change.
        Must not mutate df, read files, or touch the network."""
```

How candidates become proposals (`pipeline.profile`): the pipeline does a **dry run**. In rule order, for each candidate it calls `prepare`, resolves the mode, then `apply` on a working copy. A candidate that changes nothing is dropped. The change records give `rows_affected` and the 5 samples. Each later rule therefore sees the data as it would look after the earlier fixes.

Rules for rules:
- `apply` is deterministic: same input and params give the same output.
- `apply` never raises on dirty data. A value it cannot fix is **left unchanged**, never nulled.
- `apply` fills only `rule_id`, `rule_version`, `row_id`, `column`, `change_type`, `old_value`, `new_value`. The pipeline stamps `run_id`, `action`, `timestamp`.
- `_row_id` must be preserved on every surviving row.
- Mode resolution, done by the pipeline, not the rule:
  0. A candidate with `auto_safe` starts as `auto` instead of the rule's `default_mode`, and step 2 does not apply to it.
  1. If the rule reports a `confidence`: `< 0.80` drop the proposal; `0.80 to < 0.98` mode = `suggest`; `>= 0.98` mode = `default_mode`.
  2. If `is_destructive` and the mode is `auto`, it stays `auto` only for the rules marked auto in the table below (these remove only provably empty or identical data). Otherwise it becomes `suggest`.

### 2.2 Registry and run order

`engine/rules/registry.py` exposes `RULES: list[Rule]` in this fixed order. The pipeline always runs in this order.

| # | id | scope | default_mode | destructive | severity | confidence |
|---|---|---|---|---|---|---|
| 1 | `normalize_headers` | table | auto | no | low | none |
| 2 | `drop_empty_rows_and_columns` | table | auto | yes (empty only) | low | none |
| 3 | `trim_and_normalize_text` | column | auto | no | low | none |
| 4 | `standardize_null_tokens` | column | auto | no | medium | none |
| 5 | `coerce_numeric` | column | auto | no | high | share of non-null values that parse as numbers |
| 6 | `parse_dates` | column | auto | no | high | share of non-null values that parse as dates; forced to suggest if day/month order is ambiguous |
| 7 | `standardize_booleans` | column | auto | no | medium | none (triggers only when all non-null values are known boolean tokens) |
| 8 | `remove_exact_duplicate_rows` | table | auto | yes (identical only) | high | none |
| 9 | `standardize_categories` | column | suggest (Tier 1: auto) | yes | medium | none |
| 10 | `flag_outliers` | column | flag | no | medium | none |

### 2.3 Behaviour and params per rule

| id | Behaviour | params |
|---|---|---|
| `normalize_headers` | snake_case, strip, ASCII-fold, empty header becomes `column_<n>`, duplicates get `_2`, `_3` | `{"mapping": {current dataframe column: name}}` |
| `drop_empty_rows_and_columns` | Removes rows and columns where every cell is null or a null token | `{"drop_rows": true, "drop_columns": true}` |
| `trim_and_normalize_text` | Trim, collapse inner whitespace, remove zero-width/control/non-breaking chars, Unicode NFC, `ftfy.fix_text`. **Name casing (M6, always a suggestion, `force_suggest`):** a second candidate on person-name columns (header has a `name`, `surname`, `firstname`, `lastname` or `fullname` token and no business word such as file, user, product, company, dba, aka, vendor, store). Only values written ALL CAPS or all lower case change (`JOHN O'BRIEN` becomes `John O'Brien`); mixed case is left alone. Keeps `Mc`, `Mac` (only before a consonant other than h, k, y, so `Machado` stays), `O'`, lower-case `van`, `de`, `von` after the first word, and `II`, `III`, `IV`. Skipped when more than 20% of values end in LLC, Inc, Ltd or Corp | `{}`; name casing `{"name_case": true, "mapping": {old: new}}` |
| `standardize_null_tokens` | Null tokens become `null` | `{"tokens": [...]}` |
| `coerce_numeric` | Strip `$ £ € ,` and spaces, `%` (value kept as written, e.g. `45%` becomes `45`), `(123)` becomes `-123`, a stray leading zero is dropped (`03` becomes `3`). Output is a plain decimal string. **Money columns** (any value written with a currency symbol) get exactly 2 decimals by padding only (`741.8` becomes `741.80`; `1.234` is never rounded), and clean.xlsx shows them with format `0.00`. **Never triggers** on an id column: one whose numbers have leading zeros and all share one fixed width (zip `02134`), or whose name has an id-like word as a whole token (the name is split into words on non-letters, digits and camelCase, case ignored): id, zip, zipcode, postal, postcode, code, sku, phone, account, ssn, license, licence, lic, permit, inspection, no, num, number, nbr, ref, key. So `License #`, `cust_no` and `licenseNo` match, but `notes`, `monkey` and `reference_text` do not. **A count-like word wins over an id word (M6 step 9):** a name that also has count, qty, quantity, total, sum, amount, items or of as a whole token is not id-like, so `Number of items`, `num_total` and `Qty No` are ordinary numbers while `Permit Number` and `Account Number` stay ids. An id-like name only keeps leading-zero text and skips outlier flags; it never stops date, boolean or category fixes | `{"decimal": ".", "thousands": ","}`, plus `"decimals": 2` for money columns |
| `parse_dates` | Output `YYYY-MM-DD` (or `YYYY-MM-DDTHH:MM:SS` when a time is present). Ambiguous when every value has day <= 12 and month <= 12 | `{"dayfirst": bool}`; user may edit `dayfirst` |
| `standardize_booleans` | `yes/no, y/n, true/false, t/f, 1/0, on/off` (any case) become `true` / `false` | `{"true_tokens": [...], "false_tokens": [...]}` |
| `remove_exact_duplicate_rows` | Keeps the first occurrence (lowest `_row_id`), compares all columns except `_row_id` | `{}` |
| `standardize_categories` | Only on low-cardinality text columns (<= 50 distinct and distinct/non-null <= 0.2). Three proposals per column, worked out on distinct values and mapped back to rows. Values that differ only by case, accents or whitespace (NFKC, accents removed, casefold; spellings counted on trimmed text) form a group of spellings of the same value. **Tier 1 (auto, `auto_safe`, M6b):** if one spelling holds 80% or more of the group's rows it is the canonical spelling: the other spellings merge into it and its own cells are untouched (4,953 `CHICAGO` and 20 `Chicago` give 20 changes to `CHICAGO`). **Case suggestion (suggest, M6b):** a group with no 80% spelling is never merged automatically; the suggestion is the most frequent Title Case spelling in the group if there is one, otherwise the most frequent spelling (never an invented spelling). Different values are never merged by these two steps (a column of 90% `Yes` and 10% `No` stays as is). **Tier 2 (suggest):** abbreviations and typos. A value is mapped to a target only when ALL hold: same first letter; the target has at least 3 rows, at least 5% of the column and more rows than the value; digits are the same; and one piece of evidence: the built-in abbreviation map (`N S E W NE NW SE SW` to the compass words), Damerau-Levenshtein distance 1 (a swap counts as 1), or the value's letters appear in order in the target and cover at least 50% of it. Evidence ranks abbreviation > distance 1 > letters in order; the best target must be strictly better than every other, so a value equally close to two targets (`N` to `NE` and `NW`) is never merged. Tier 2 targets are the groups' canonical spellings. Skipped above 500 distinct values. Each merge carries a plain-language reason, also written to the change log `reason` column (`majority spelling`; `Title Case spelling, no clear majority` or `most common spelling, no clear majority`; the Tier 2 reason; `merge chosen by the user` for a value added by editing) | Tier 1 `{"tier": 1, "mapping": {...}}`; case suggestion `{"case_suggestion": true, "mapping": {...}, "reasons": {old_value: text}}`; Tier 2 `{"tier": 2, "mapping": {...}, "reasons": {old_value: text}}`; user may edit the mapping |
| `flag_outliers` | Numeric columns with >= 20 non-null values; never an `id` column (license, permit and other id-like names, see `coerce_numeric`). Adds `<column>_outlier_flag` (`true`/`false`) for values outside `Q1 - k*IQR .. Q3 + k*IQR`. Never removes or changes a value | `{"k": 1.5}`; user may edit `k` |

### 2.4 Proposal

```json
{
  "id": "sug_3f9a1c20b7e4",
  "rule_id": "parse_dates",
  "rule_version": "1.0.0",
  "column": "order_date",
  "mode": "suggest",
  "severity": "high",
  "is_destructive": false,
  "confidence": 0.93,
  "title": "Convert order_date to ISO 8601 dates",
  "description": "93% of values look like dates. 12 values use a different format.",
  "rows_affected": 1840,
  "params": {"dayfirst": true},
  "editable_params": ["dayfirst"],
  "samples": [{"row_id": 4, "before": "03/04/2024", "after": "2024-04-03"}],
  "left_alone": [{"value": "31/02/2024", "count": 2, "reason": "Not a valid date, so it is kept as written."}]
}
```

- `id` = `"sug_"` + first 12 hex chars of `sha1(rule_id + "|" + (column or "") + "|" + canonical_json(params))`. Stable across re-profiling the same file.
- `column` is `null` for table-scope rules. `confidence` is `null` when the rule reports none.
- `samples`: up to 5.
- `left_alone` (added M6): up to 20 values the rule saw but will not change, most frequent first. `coerce_numeric` lists values that are not numbers, `parse_dates` values that are not valid dates, `standardize_categories` Tier 2 rare values with no single clear match (including ties). Other rules return `[]`.

---

## 3. Profile schema

`DatasetProfile` (returned by `pipeline.profile`, stored as `profile.json`):

```json
{
  "schema_version": "1.0",
  "source": {
    "filename": "sales.csv",
    "file_type": "csv",
    "encoding": "windows-1252",
    "delimiter": ";",
    "sheet": null,
    "header_row": 0
  },
  "row_count": 2000,
  "column_count": 12,
  "duplicate_row_count": 14,
  "empty_row_count": 3,
  "quality": { "...QualityScore, section 4..." },
  "columns": [ { "...ColumnProfile..." } ],
  "proposals": [ { "...Proposal, section 2.4..." } ]
}
```

`file_type`: `csv` | `xlsx`. `delimiter` and `encoding` are `null` for xlsx. `header_row` is the 0-based index of the header row in the raw file.

`ColumnProfile`:

```json
{
  "name": "order_date",
  "source_name": "Order Date ",
  "position": 3,
  "inferred_type": "date",
  "type_confidence": 0.93,
  "row_count": 2000,
  "null_count": 40,
  "null_pct": 2.0,
  "distinct_count": 611,
  "distinct_pct": 31.2,
  "is_key_candidate": false,
  "min": "2023-01-02",
  "max": "2024-12-30",
  "mean": null,
  "median": null,
  "min_length": 8,
  "max_length": 10,
  "top_values": [{"value": "2024-01-15", "count": 9}],
  "samples": ["03/04/2024", "2024-04-05", "5 Apr 24"],
  "format_patterns": [{"pattern": "99/99/9999", "count": 1700}],
  "issues": [{"code": "mixed_date_formats", "severity": "high", "message": "3 date formats found", "count": 260}],
  "quality": { "...ColumnQuality, section 4..." }
}
```

- `inferred_type`: `integer` | `decimal` | `date` | `datetime` | `boolean` | `category` | `text` | `id` | `empty`.
- Type inference, first match wins: `empty` (no values) · `date`/`datetime` (>= 0.80 of non-null values parse as dates) · `boolean` (>= 0.80 are boolean tokens, and at least as many as parse as numbers) · `id` (>= 0.80 look numeric **and** either leading zeros at one fixed width or an id-like name, see `coerce_numeric`; because dates and booleans are checked first, an id-like name such as `Inspection Date` still becomes `date`) · `integer`/`decimal` (>= 0.80 parse as numbers) · `category` (meets the `standardize_categories` cardinality test) · `text`. `type_confidence` is that share (1.0 for `id`, `category`, `text`, `empty`).
- `null_count` counts real nulls **and** null tokens. Percentages are 0 to 100, one decimal.
- `min`, `max` are strings; `mean`, `median` are numbers or `null` (numeric types only).
- `top_values`: up to 10. `samples`: up to 5 distinct raw non-null values. `format_patterns`: up to 5, where digits become `9`, letters `A`, everything else kept.
- `is_key_candidate`: `inferred_type` is `id`, `integer` or `text` **and** distinct/non-null >= 0.95.
- Issue `code` values: `missing_values`, `null_tokens`, `whitespace`, `hidden_characters`, `encoding_damage`, `mixed_types`, `numeric_as_text`, `mixed_date_formats`, `ambiguous_dates`, `inconsistent_booleans`, `inconsistent_categories`, `outliers`, `duplicate_keys`, `messy_header`, `empty_column`.

---

## 4. Quality score

Scores are 0 to 100, one decimal. Calculated identically before and after cleaning by `engine/profile.py`.

### 4.1 Weights

| Dimension | Weight |
|---|---|
| Completeness | 0.25 |
| Validity | 0.25 |
| Consistency | 0.20 |
| Uniqueness | 0.15 |
| Conformity | 0.15 |

### 4.2 Per-column dimension formulas (each gives 0 to 1)

Let `n` = rows, `nn` = non-null values (nulls include null tokens).

| Dimension | Formula |
|---|---|
| Completeness | `nn / n` |
| Validity | share of `nn` that parse as the column's `inferred_type`. For `text`, `category`, `id`: share with no control characters, replacement characters (U+FFFD) or mojibake detected by ftfy |
| Consistency | share of `nn` written in the column's **most common format**. Format = `format_pattern` for dates/numbers/ids, token pair for booleans, cluster canonical value for categories; for text: no leading/trailing/repeated whitespace |
| Uniqueness | key candidates: `distinct / nn`. All other columns: dataset row uniqueness `1 - duplicate_row_count / n` |
| Conformity | `0.2 * header_ok + 0.8 * (values in the standard form / (nn + null-token cells))`. `header_ok` = 1 if `source_name` is already unique snake_case. Standard form: ISO 8601 for dates, plain decimal string with no leading zero for numbers (`03` is not standard), `true`/`false` for booleans, trimmed NFC text with no null tokens for everything else |

Consistency asks "do the values agree with each other?"; Conformity asks "do they match the target standard?". A column entirely in `dd/mm/yyyy` is 100% consistent and 0% conforming.

Edge cases: if `nn == 0`, Completeness = 0 and the other four = 1. If `n == 0`, every score is 0.

### 4.3 Roll-up

```
column_score      = 100 * sum(weight_d * column_dimension_d)
dataset_dimension = mean of that dimension over all columns
overall           = 100 * sum(weight_d * dataset_dimension_d)
```

`_row_id` and `*_outlier_flag` columns are excluded from scoring.

```json
// ColumnQuality
{"score": 81.4, "completeness": 98.0, "validity": 93.0, "consistency": 85.0, "uniqueness": 99.3, "conformity": 20.0}
// QualityScore (dataset)
{"overall": 78.2, "completeness": 96.1, "validity": 88.0, "consistency": 74.5, "uniqueness": 99.3, "conformity": 41.0}
```

---

## 5. Change log schema

`ChangeRecord` is a plain dataclass in `engine/changelog.py` (not Pydantic: a run can produce millions). One `ChangeRecord` per changed cell (or per removed row / removed column / renamed header / added column).

| Field | Type | Notes |
|---|---|---|
| `run_id` | str (UUID4) | stamped by pipeline |
| `rule_id` | str | |
| `rule_version` | str | |
| `row_id` | int or null | `_row_id`; `null` for column-level changes |
| `column` | str or null | column `name`; `null` for row removal |
| `change_type` | str | `cell` · `row_removed` · `column_removed` · `header_renamed` · `column_added` |
| `old_value` | str or null | |
| `new_value` | str or null | |
| `action` | str | `auto` (mode auto or flag, not rejected) · `approved` (mode suggest, approved or edited by the user) |
| `timestamp` | str | UTC ISO 8601 |
| `reason` | str or null | short plain reason, filled by the rule (M6b); set for `standardize_categories` merges, empty for other records |

Conventions by `change_type`:

| change_type | row_id | column | old_value | new_value |
|---|---|---|---|---|
| `cell` | row | column | previous text | new text (`null` if set to null) |
| `row_removed` | row | null | the row as a JSON object string | null |
| `column_removed` | null | column | null | null |
| `header_renamed` | null | new name | previous dataframe column name | new name |
| `column_added` | null | new column | null | null |

`flag_outliers` logs one `column_added` plus one `cell` record per flagged row (`old_value` null, `new_value` `"true"`).

`changelog.csv` has exactly these 11 columns, in this order, UTF-8, with header (`reason` was added last in M6b).

---

## 6. Recipe YAML schema

A recipe is the approved plan, saved so it can be re-run on a similar file. `engine.recipe.load` validates it with Pydantic.

```yaml
recipe_version: "1.0"
name: "sales.csv cleaning recipe"
created_at: "2026-11-11T14:03:22Z"
engine_version: "0.1.0"
source:
  filename: "sales.csv"
  file_type: csv
  sheet: null
  header_row: 0
  encoding: windows-1252     # informational; re-detected on each run
  delimiter: ";"            # informational; re-detected on each run
steps:                       # in run order (section 2.2)
  - rule_id: normalize_headers
    rule_version: "1.0.0"
    column: null
    action: auto             # auto | approved
    params:
      mapping: {"Order Date ": order_date}
  - rule_id: parse_dates
    rule_version: "1.0.0"
    column: order_date
    action: approved
    params: {dayfirst: true}
```

Running a recipe (`recipe.run`):
- Steps run in file order. A step whose `column` is missing in the new file is skipped and reported as a warning, not an error.
- A step whose `rule_version` major number differs from the installed rule fails with a clear message.
- Rejected proposals are not written to the recipe.
- Plan steps name columns by their tidy `name`. If `normalize_headers` was rejected, the pipeline maps each name back to the current dataframe column, so the other steps still run.
- `recipe.run(recipe, path, out_dir, run_id)` takes sheet and header row from the recipe and re-detects encoding and delimiter.

---

## 7. Pipeline API (the only engine surface the backend may call)

```python
# engine/pipeline.py
ProgressFn = Callable[[int, str], None]      # (progress_pct 0-100, current_step label)

def inspect(path: Path) -> FileInspection
    """Cheap look at an upload: sheets, detected header row, first 10 raw rows per sheet."""

def profile(path: Path, sheet: str | None = None, header_row: int | None = None,
            progress: ProgressFn | None = None, display_name: str | None = None,
            cache_dir: Path | None = None) -> DatasetProfile

def build_plan(profile: DatasetProfile, decisions: Decisions) -> ApprovedPlan
    """Turn user decisions into the ordered list of steps to run."""

def clean(path: Path, approved_plan: ApprovedPlan, out_dir: Path, run_id: str,
          progress: ProgressFn | None = None, recipe_name: str | None = None,
          display_name: str | None = None, cache_dir: Path | None = None) -> CleanResult
    """Writes clean.csv, report.html, recipe.yaml, changelog.csv and xlsx_spec.json into out_dir."""

def build_xlsx(out_dir: Path) -> Path
    """Builds clean.xlsx in a clean job's out_dir from clean.csv and xlsx_spec.json (column
    types, money columns). First call builds, later calls return the same file. Written to a
    temporary name and renamed, so a failed build leaves no clean.xlsx."""
```

Models:

```python
class Decisions(BaseModel):
    approved: list[str] = []          # proposal ids
    rejected: list[str] = []
    edited: list[EditedProposal] = [] # {id: str, params: dict}; editing implies approval

class PlanStep(BaseModel):            # same shape as a recipe step
    rule_id: str; rule_version: str; column: str | None
    action: Literal["auto", "approved"]; params: dict
    proposal_id: str | None = None

class ApprovedPlan(BaseModel):
    source: SourceInfo                # as in profile.source
    steps: list[PlanStep]

class CleanResult(BaseModel):
    run_id: str
    before: QualityScore
    after: QualityScore
    columns: list[ColumnScoreChange]  # {name, before: ColumnQuality | None, after: ColumnQuality | None}; before is null for an added column, after is null for a removed one
    summary: ChangeSummary
    files: dict[str, str]             # download name -> file name in out_dir
    warnings: list[str]
```

`build_plan` decision logic:

| Proposal mode | In `rejected` | In `approved` or `edited` | In neither |
|---|---|---|---|
| auto | not run | run, action `auto` | run, action `auto` |
| flag | not run | run, action `auto` | run, action `auto` |
| suggest | not run | run, action `approved` | **not run** |

Unknown ids, or an id in both lists, raise `PlanError`. Edits may only change keys listed in `editable_params`.

`ChangeSummary`:

```json
{
  "total_changes": 5231,
  "cells_changed": 5180,
  "rows_removed": 17,
  "columns_removed": 1,
  "columns_added": 2,
  "rows_before": 2000, "rows_after": 1983,
  "columns_before": 12, "columns_after": 13,
  "by_rule": [{"rule_id": "trim_and_normalize_text", "action": "auto", "changes": 2110, "columns": ["name", "city"]}]
}
```

Progress step labels:
- profile: `Reading file` · `Detecting structure` · `Profiling columns` · `Scoring quality` · `Finding fixes` · `Done`
- clean: `Reading file` · one `Applying <rule label>` per step · `Scoring results` · `Writing files` · `Done`

`display_name` is the file name as uploaded. The backend stores files under fixed names, so it passes this for `source.filename`, the report and the recipe.

**Read-once cache (M6).** With `cache_dir`, `profile` saves the parsed all-text table as Parquet plus its own scores (`ingest-<key>.parquet`, `ingest-<key>.json`); `clean` with the same `cache_dir` reuses them instead of parsing the file and scoring "before" again. The key is the file's SHA-256 plus sheet, header row, engine version and a hash of the engine source code (`cache.ENGINE_FINGERPRINT`, worked out once at import), so any change to the file or to engine code misses. Profiling is never sampled and the dry run is never reused for the final clean. `clean` streams change records to `changelog.csv` after each step and keeps only counts and a 50-record sample in memory.

Engine errors: `engine.errors.IngestError` (unreadable or empty file), `engine.errors.PlanError` (bad decisions). Both carry a user-safe `message`.

---

## 8. HTTP API

Base path `/api`. JSON everywhere except upload (multipart) and downloads. Ids are random UUID4 strings. CORS allows the Vite dev origin.

Error body for every non-2xx response:

```json
{"error": {"code": "file_too_large", "message": "Files must be 50 MB or smaller."}}
```

| HTTP | code | When |
|---|---|---|
| 400 | `invalid_request` | bad body, unknown sheet, unknown proposal id |
| 404 | `not_found` | unknown dataset or job, or files already deleted |
| 409 | `not_ready` | profile or results requested before the job finished; clean requested before profile |
| 413 | `file_too_large` | upload over the limit (`DC_MAX_UPLOAD_MB`, default 50) |
| 415 | `unsupported_file_type` | not `.csv` or `.xlsx` (checked by extension **and** content sniffing) |
| 422 | `unreadable_file` | file passes type checks but cannot be parsed, or is empty |
| 500 | `internal_error` | unexpected server error (no internal details in the message) |
| 500 | `excel_failed` | clean.xlsx could not be built; the clean job and the other downloads are not affected |

A failed job's `error.code` is one of `unreadable_file`, `invalid_request`, `internal_error`, `interrupted` (the server restarted while the job was queued or running), or `superseded` (a newer profile or clean job was started for the same dataset, so this job's result was discarded).

`GET /api/health` returns `{"status": "ok", "max_upload_mb": 50}` (a number; `DC_MAX_UPLOAD_MB` may be a decimal such as 4.5, and a value that is not a positive number stops the server with a clear error); the website uses `max_upload_mb` for its own check and text.

### 8.1 `POST /api/datasets` (upload)

Multipart field `file`. Validates type and size before anything is queued. Response `201`:

```json
{
  "dataset_id": "uuid",
  "filename": "sales.xlsx",
  "file_type": "xlsx",
  "size_bytes": 482113,
  "expires_at": "2026-11-12T14:03:22Z",
  "sheets": [
    {"name": "Q1", "row_count_estimate": 2001, "detected_header_row": 0,
     "preview": [["Order Date ", "Amount"], ["03/04/2024", "$1,200.00"]]}
  ]
}
```

CSV files return exactly one sheet with `"name": null`. `preview` is the first 10 raw rows as strings.

### 8.2 `POST /api/datasets/{id}/profile`

Body: `{"sheet": "Q1" | null, "header_row": 0}` (both optional; defaults to the first sheet and the detected header row). Response `202`: `{"job_id": "uuid"}`.

### 8.3 `GET /api/jobs/{job_id}`

```json
{
  "job_id": "uuid", "dataset_id": "uuid", "type": "profile",
  "status": "running", "progress_pct": 40, "current_step": "Profiling columns",
  "error": null, "created_at": "...", "updated_at": "..."
}
```

`type`: `profile` | `clean`. `status`: `queued` | `running` | `done` | `failed`. `error` is `{code, message}` when failed. `progress_pct` reaches 100 only when `status` is `done` (outputs saved).

### 8.4 `GET /api/datasets/{id}/profile`

Response `200`: `DatasetProfile` (section 3) plus `"dataset_id"`. The UI reads column profiles from `columns`, the quality score from `quality`, and suggestions from `proposals`.

### 8.5 `POST /api/datasets/{id}/clean`

Body = `Decisions`:

```json
{"approved": ["sug_..."], "rejected": ["sug_..."], "edited": [{"id": "sug_...", "params": {"dayfirst": false}}]}
```

Response `202`: `{"job_id": "uuid"}`. The job id is also the `run_id`.

**Generations (M6).** Every new profile or clean job increases the dataset's `generation` and clears its results (a profile job also clears the profile). A job saves its result with one guarded `UPDATE ... WHERE id = :id AND generation = :g`; if a newer job has started, nothing is saved and the job ends `failed` / `superseded`. An old job can never overwrite a newer profile or result.

### 8.6 `GET /api/datasets/{id}/results`

```json
{
  "dataset_id": "uuid", "run_id": "uuid",
  "before": {"...QualityScore..."}, "after": {"...QualityScore..."},
  "columns": [{"name": "order_date", "before": {"...ColumnQuality..."}, "after": {"...ColumnQuality..."}}],
  "summary": {"...ChangeSummary..."},
  "changes": {"total": 5231, "limit": 100, "offset": 0, "items": [{"...ChangeRecord..."}]},
  "downloads": ["clean.csv", "clean.xlsx", "report.html", "recipe.yaml", "changelog.csv"],
  "warnings": []
}
```

Query params for the change log table: `limit` (default 100, max 500), `offset`, `rule_id`, `column`, `action`, `change_type`.

### 8.7 `GET /api/datasets/{id}/downloads/{name}`

`name` is one of `clean.csv`, `clean.xlsx`, `report.html`, `recipe.yaml`, `changelog.csv`; anything else is `404`; a valid name before cleaning has finished is `409 not_ready`.

**clean.xlsx is built on download (M6).** The clean job does not write it (it was about half of the job's time). `POST /api/datasets/{id}/downloads/clean.xlsx/prepare` builds it if needed and answers `200 {"ready": true}`; the website calls this, shows "Preparing your Excel file", then starts the normal download. `GET .../downloads/clean.xlsx` also builds it if it is missing. The built file is kept in the run folder, so repeat downloads are immediate. A build failure answers `500 excel_failed` and never changes the job status or the other downloads. Sent with `Content-Disposition: attachment` and the original file stem as a prefix (e.g. `sales_clean.csv`).

### 8.8 Jobs table (SQLModel)

`Job`: `id` (UUID4, pk), `dataset_id`, `type`, `status`, `progress_pct` (int), `current_step` (str), `error_code`, `error_message`, `generation` (int), `created_at`, `updated_at`.
`Dataset`: `id` (UUID4, pk), `filename`, `file_type`, `size_bytes`, `sheet`, `header_row`, `created_at`, `expires_at`, `generation` (int), `profile_json` (DatasetProfile or null), `results_json` (CleanResult or null), `results_run_id` (clean job whose folder holds the downloads, or null).

---

## 9. Storage and cleanup

```
storage/
  app.db                      # SQLite
  {dataset_id}/
    original.csv | original.xlsx   # never modified
    inspection.json                # sheets and header rows found at upload
    ingest-<key>.parquet / .json   # read-once cache (section 7), written by the profile job
    runs/{run_id}/                 # one folder per clean job (M6)
      plan.json
      clean.csv  report.html  recipe.yaml  changelog.csv  xlsx_spec.json
      clean.xlsx                   # only after the first Excel download or prepare call
```

The profile and results are stored in the `Dataset` row (section 8.8), not as files. Downloads come from `runs/{results_run_id}/`. When a clean job's result is saved, the other run folders of that dataset are deleted, except those of clean jobs still queued or running; a superseded or failed clean job deletes its own folder. A download whose file is missing answers `409 not_ready`.

- `clean.csv`: UTF-8, comma-delimited, header = column `name`s, no `_row_id`. `clean.xlsx`: one sheet named `clean`, numbers/dates/booleans written as real Excel types.
- A cleanup task runs at startup and every hour: deletes any dataset folder and its database rows where `expires_at` (upload time + 24 hours) has passed. An expired dataset answers `404` even before the task has run. Folders with no database row are removed once they are over an hour old.
- The upload limit (`DC_MAX_UPLOAD_MB`, default 50) is enforced twice: by an ASGI layer that counts body bytes as they arrive (refusing at once from a declared `Content-Length`, otherwise stopping as soon as the body passes the limit plus 1 MB of form overhead, so chunked uploads with no `Content-Length` are also refused before the form is parsed), and again on the file bytes while streaming to disk.
- Stored file names are fixed (above). User-supplied filenames are never used as paths.

## 10. Frontend rules and sample data (added after M4)

- **Approve all safe fixes** approves a proposal only if it is not destructive, its mode is not `flag`, its rule is not `standardize_categories`, it is not name casing (`params.name_case`), and it is not a `parse_dates` proposal on a column with the `ambiguous_dates` issue. Category merges and ambiguous dates need an explicit choice by the user (for dates: day-first or month-first). Auto and flag proposals still run unless rejected; suggest proposals run only if approved (section 7).
- **Fixes screen layout (M6):** Tier 1 category merges are shown in an "Automatic merges" section with an Undo per value. Undo removes that value from the proposal's mapping (sent as an edit); undoing every value rejects the proposal. The case suggestion (`params.case_suggestion`, no `tier`) is not in that section: it is a normal suggestion card with each value's reason. The other proposals are grouped as "Whole table" (no column) and one section per column, each with its `left_alone` values. Tier 2 merges show each value's reason.
- **One job at a time per browser session:** the UI disables "Start cleaning" and the stepper while a profile or clean job runs.
- **Encoding detection:** when charset-normalizer guesses a Latin-script single-byte encoding other than windows-1252 (iso8859-2/4/9/10/13/14/16, cp1254, cp1257) the file is read as windows-1252 if it decodes cleanly; Cyrillic, Greek and Arabic guesses are kept.
- **Ground truth:** `sample_data/make_samples.py` writes `sample_data/ground_truth.csv` with one row per injected error: `file, row, column, error_type, original_value, injected_value`. `row` is the 1-based data row (same as `_row_id`); structural errors use row 0.
- **Invalid values stay:** text that cannot be parsed (for example "abc" in a number column, "31/02/2024" in a date column) is left as it was and reported as a warning; it is never guessed.

## 11. Success criteria (Phase 1)

There is no single "average points lift" target. Phase 1 is judged on the measures below, computed by `evaluation/run_evaluation.py` with every proposal approved. Since M6 there are two batches: the **tuning batch** (`sample_data/`, three files) and the **held-out batch** (`sample_data/heldout/`: the same generators with seed `HELDOUT_SEED`, plus `store_visits_messy.csv`). The engine must never be tuned against the held-out batch; it is the batch to quote.

Both recalls are over **all** injected errors. An injection that changed nothing (original equals injected) is not an error and is left out.

1. **Detection recall.** Share of injected errors that were fixed, or changed, flagged or listed in a proposal's `left_alone` (cell level), or for which the column's profile carries the matching issue (column level: `missing_values`, `mixed_types`, `ambiguous_dates`, `duplicate_keys`, `inconsistent_categories`). Reported with the cell-level share next to it.
2. **Fix recall.** Share of injected errors that end up correct **and** in the standard form: a real empty cell for null tokens and placeholders, a plain number, an ISO date, `true`/`false`, tidy text. Also fixed: a row or column removed on purpose, a flagged outlier, and reading problems handled at ingest. Ambiguous dates count as detected, not fixed, because the engine cannot know the order; the figure "if the user picks the right order" is reported separately.
3. **Precision.** Changes on injected cells divided by all non-neutral changes.
4. **Zero damaged cells.** A cell with no injected error must keep its meaning after cleaning. Count must be 0 on both batches (`tests/engine/test_evaluation.py` asserts it).
5. **Per-dimension lift.** For each of the five quality dimensions (section 4) the after-score is not lower than the before-score, on every file of both batches. The Results screen shows the same table (before, after, change).

Measured at M6 step 8:

| Batch | Injected errors | Detection recall | of which cell level | Fix recall | Precision | Damaged cells |
|---|---|---|---|---|---|---|
| Held-out | 3,474 | 96.7% | 80.9% | 69.1% (77.7% with the right date order) | 100% | 0 |
| Tuning | 2,718 | 97.3% | 81.3% | 66.9% (77.9% with the right date order) | 100% | 0 |

The older measure, recall on the error types a rule is meant to fix, is 99.7% (held-out) and 99.9% (tuning); it is kept in `evaluation/RESULTS.md` for continuity with M5 (98.8% then, before the answer key was corrected in M6 step 1).

Timing and memory (M6 step 7, development machine, `evaluation/TIMING.md`): 100,000 rows (5.4 MB) profile about 12 s, clean about 12 s, peak about 0.46 GB; 872,050 rows (47.5 MB) profile about 60 to 80 s, clean about 90 s without Excel, peak about 1.8 GB. clean.xlsx is built on first download. Supported size: 50 MB locally, 4 MB on the live site.

The real public dataset (`sample_data/chicago_food_inspections.csv`) has no ground truth and is excluded from these measures; it is reported as before and after scores plus a hand check of 100 random changes (`evaluation/CHICAGO_HANDCHECK.md`: 0 wrong; after the M6 step 8b fixes the same 100 are 65 correct, 1 useful flag, 34 no longer made, 0 debatable, 0 useless flags; a second, fresh sample of 100 in M6 step 9, seed 20261115, is 98 correct, 2 useful flags, 0 debatable, 0 useless flags, 0 wrong). The step 8b fixes (majority spelling, id-like names) left every number in the table above unchanged. Its uniqueness score can fall by up to 0.1 point (long free text counts as a key candidate and trimming merges values that differed only by spaces); `tests/engine/test_real_dataset.py` tolerates at most 0.5.
