"""Public entry points: inspect(), profile(), build_plan(), clean().

The backend calls only this module. See docs/CONTRACT.md section 7.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Callable

import polars as pl

from engine import changelog as _changelog
from engine import ingest as _ingest
from engine import parsing as P
from engine import profile as _profile
from engine.changelog import ChangeRecord
from engine.errors import PlanError
from engine.models import (
    ApprovedPlan,
    ChangeSummary,
    CleanResult,
    ColumnScoreChange,
    DatasetProfile,
    Decisions,
    FileInspection,
    PlanStep,
    Proposal,
    ProposalSample,
    RuleSummary,
)
from engine.rules.base import ROW_ID, Rule, proposal_id, resolve_mode
from engine.rules.registry import ORDER, RULES, RULES_BY_ID

ProgressFn = Callable[[int, str], None]

OUTPUT_FILES = ("clean.csv", "clean.xlsx", "report.html", "recipe.yaml", "changelog.csv")
_SAMPLE_COUNT = 5
_SAMPLE_MAX_CHARS = 200


def _noop(pct: int, step: str) -> None:
    return None


# --------------------------------------------------------------------------- inspect / profile

def inspect(path: Path) -> FileInspection:
    """Cheap look at an upload: sheets, detected header row, first 10 raw rows per sheet."""
    return _ingest.inspect(Path(path))


def profile(
    path: Path,
    sheet: str | None = None,
    header_row: int | None = None,
    progress: ProgressFn | None = None,
    display_name: str | None = None,
) -> DatasetProfile:
    """Read the file (never modifying it); return column profiles, quality score and proposals."""
    report = progress or _noop
    report(5, "Reading file")
    loaded = _ingest.ingest(Path(path), sheet=sheet, header_row=header_row, display_name=display_name)
    report(25, "Detecting structure")
    result = _profile.profile_dataframe(loaded.df, loaded.source, loaded.source_names, progress=report)
    report(90, "Finding fixes")
    result.proposals = _propose(loaded.df, result)
    report(100, "Done")
    return result


def _short(value: str | None) -> str | None:
    if value is not None and len(value) > _SAMPLE_MAX_CHARS:
        return value[:_SAMPLE_MAX_CHARS] + "..."
    return value


def _samples(records: list[ChangeRecord]) -> list[ProposalSample]:
    out: list[ProposalSample] = []
    seen: set[tuple] = set()
    for r in records:
        if r.change_type == "column_removed":
            before, after = r.column, None
        elif r.change_type == "column_added":
            before, after = None, r.column
        else:
            before, after = r.old_value, r.new_value
        key = (before, after)
        if key in seen:
            continue
        seen.add(key)
        out.append(ProposalSample(row_id=r.row_id, before=_short(before), after=_short(after)))
        if len(out) == _SAMPLE_COUNT:
            break
    return out


def _propose(df: pl.DataFrame, prof: DatasetProfile) -> list[Proposal]:
    """Dry run: apply every candidate in rule order on a copy, to get real counts and samples.

    A candidate that would change nothing is dropped. Each later rule sees the data as it
    would look if the earlier fixes were applied.
    """
    proposals: list[Proposal] = []
    for rule in RULES:
        for cand in rule.trigger(prof):
            if cand.column is not None and cand.column not in df.columns:
                continue
            params, confidence = rule.prepare(df, cand.column, dict(cand.params))
            confidence = cand.confidence if confidence is None else confidence
            mode = resolve_mode(rule, confidence, cand.force_suggest, cand.auto_safe)
            if mode is None:
                continue
            left = rule.left_alone(df, cand.column, params)
            new_df, records = rule.apply(df, cand.column, params)
            if not records:
                continue
            df = new_df
            row_ids = {r.row_id for r in records if r.row_id is not None}
            # A candidate with its own title is a different kind of fix: its note is the whole story.
            description = " ".join(x for x in (None if cand.title else rule.explain, cand.note) if x)
            proposals.append(
                Proposal(
                    id=proposal_id(rule.id, cand.column, params),
                    rule_id=rule.id,
                    rule_version=rule.version,
                    column=cand.column,
                    mode=mode,
                    severity=rule.severity,
                    is_destructive=rule.is_destructive,
                    confidence=confidence,
                    title=(cand.title or rule.label) + (f": {cand.column}" if cand.column else ""),
                    description=description,
                    rows_affected=len(row_ids) if row_ids else len(records),
                    params=params,
                    editable_params=list(rule.editable_params),
                    samples=_samples(records),
                    left_alone=left,
                )
            )
    return proposals


# --------------------------------------------------------------------------- plan

def build_plan(profile: DatasetProfile, decisions: Decisions) -> ApprovedPlan:
    """Turn the user's decisions into the ordered list of steps to run (CONTRACT.md section 7)."""
    by_id = {p.id: p for p in profile.proposals}
    edits = {e.id: e.params for e in decisions.edited}
    approved = set(decisions.approved) | set(edits)
    rejected = set(decisions.rejected)

    unknown = (approved | rejected) - set(by_id)
    if unknown:
        raise PlanError(f"Unknown suggestion id: {sorted(unknown)[0]}")
    both = approved & rejected
    if both:
        raise PlanError(f"Suggestion {sorted(both)[0]} is both approved and rejected.")

    steps: list[PlanStep] = []
    for prop in profile.proposals:
        if prop.id in rejected:
            continue
        if prop.mode == "suggest" and prop.id not in approved:
            continue
        params = dict(prop.params)
        if prop.id in edits:
            not_allowed = set(edits[prop.id]) - set(prop.editable_params)
            if not_allowed:
                raise PlanError(f'"{sorted(not_allowed)[0]}" cannot be edited for this suggestion.')
            params.update(edits[prop.id])
        steps.append(
            PlanStep(
                rule_id=prop.rule_id,
                rule_version=prop.rule_version,
                column=prop.column,
                action="approved" if prop.mode == "suggest" else "auto",
                params=params,
                proposal_id=prop.id,
            )
        )
    return ApprovedPlan(source=profile.source, steps=steps)


# --------------------------------------------------------------------------- clean

def _check_version(rule: Rule, step: PlanStep) -> None:
    if step.rule_version.split(".")[0] != rule.version.split(".")[0]:
        raise PlanError(
            f"The recipe was made with {rule.id} version {step.rule_version}, "
            f"but version {rule.version} is installed."
        )


def _summarise(records: list[ChangeRecord], before: DatasetProfile, after: DatasetProfile) -> ChangeSummary:
    by_rule: dict[tuple[str, str], RuleSummary] = {}
    counts = dict.fromkeys(_changelog.CHANGE_TYPES, 0)
    for r in records:
        counts[r.change_type] += 1
        entry = by_rule.setdefault(
            (r.rule_id, r.action), RuleSummary(rule_id=r.rule_id, action=r.action, changes=0)
        )
        entry.changes += 1
        if r.column and r.column not in entry.columns:
            entry.columns.append(r.column)
    return ChangeSummary(
        total_changes=len(records),
        cells_changed=counts["cell"],
        rows_removed=counts["row_removed"],
        columns_removed=counts["column_removed"],
        columns_added=counts["column_added"],
        rows_before=before.row_count,
        rows_after=after.row_count,
        columns_before=before.column_count,
        columns_after=after.column_count,
        by_rule=sorted(by_rule.values(), key=lambda s: (ORDER.get(s.rule_id, 99), s.action)),
    )


def _typed(value: str | None, itype: str):
    """Turn clean text into a real Excel value where it is safe to do so."""
    if value is None:
        return None
    try:
        if itype == "integer" and P.PLAIN_NUMBER_RE.match(value) and len(value) <= 15:
            return int(value)
        if itype == "decimal" and P.PLAIN_NUMBER_RE.match(value):
            return float(value)
        if itype == "date" and len(value) == 10:
            return _dt.date.fromisoformat(value)
        if itype in ("date", "datetime") and P.ISO_DATE_RE.match(value):
            return _dt.datetime.fromisoformat(value)
        if itype == "boolean" and value in ("true", "false"):
            return value == "true"
    except ValueError:
        pass
    return value


def _write_xlsx(df: pl.DataFrame, types: dict[str, str], path: Path, money: set[str] = frozenset()) -> None:
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("clean")
    ws.append(df.columns)
    kinds = [types.get(c, "text") for c in df.columns]
    is_money = [c in money for c in df.columns]
    for row in df.iter_rows():
        cells = []
        for v, k, m in zip(row, kinds, is_money):
            value = _typed(v, k)
            if m and isinstance(value, (int, float)):
                cell = WriteOnlyCell(ws, value=float(value))
                cell.number_format = "0.00"            # money: shown with 2 decimals
                value = cell
            cells.append(value)
        ws.append(cells)
    wb.save(path)


def clean(
    path: Path,
    approved_plan: ApprovedPlan,
    out_dir: Path,
    run_id: str,
    progress: ProgressFn | None = None,
    recipe_name: str | None = None,
    display_name: str | None = None,
) -> CleanResult:
    """Run the approved steps on a fresh read of the file and write the five output files.

    The original file is only read. Outputs go to out_dir.
    """
    from engine import recipe as _recipe
    from engine import report as _report

    report = progress or _noop
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    report(3, "Reading file")
    src = approved_plan.source
    loaded = _ingest.ingest(
        Path(path), sheet=src.sheet, header_row=src.header_row, display_name=display_name
    )
    df = loaded.df
    before = _profile.profile_dataframe(df, loaded.source, loaded.source_names)

    # Steps name columns by their tidy name; map that to the current dataframe column.
    current = {col.name: raw for col, raw in zip(before.columns, [c for c in df.columns if c != ROW_ID])}
    records: list[ChangeRecord] = []
    warnings: list[str] = []
    steps = approved_plan.steps
    for i, step in enumerate(steps):
        rule = RULES_BY_ID.get(step.rule_id)
        if rule is None:
            raise PlanError(f'Unknown rule "{step.rule_id}".')
        _check_version(rule, step)
        report(10 + int(65 * i / max(len(steps), 1)), f"Applying {rule.label}")
        column = None
        if step.column is not None:
            column = current.get(step.column, step.column)
            if column not in df.columns:
                warnings.append(f'Skipped "{rule.label}": column "{step.column}" is not in this file.')
                continue
        df, changes = rule.apply(df, column, step.params)
        _changelog.stamp(changes, run_id, step.action)
        records += changes
        for change in changes:
            if change.change_type == "header_renamed":
                for name, col in current.items():
                    if col == change.old_value:
                        current[name] = change.new_value

    report(80, "Scoring results")
    after = _profile.profile_dataframe(df, loaded.source)
    after_by_col = {c.name: c for c in after.columns}
    columns = [
        ColumnScoreChange(
            name=col.name,
            before=col.quality,
            after=after_by_col[current[col.name]].quality if current[col.name] in after_by_col else None,
        )
        for col in before.columns
    ]
    known = {current[c.name] for c in before.columns}
    columns += [
        ColumnScoreChange(name=c.name, before=None, after=c.quality)
        for c in after.columns
        if c.name not in known
    ]
    summary = _summarise(records, before, after)
    result = CleanResult(
        run_id=run_id,
        before=before.quality,
        after=after.quality,
        columns=columns,
        summary=summary,
        files={name: name for name in OUTPUT_FILES},
        warnings=warnings,
    )

    report(88, "Writing files")
    output = df.drop(ROW_ID)
    output.write_csv(out_dir / "clean.csv")
    money = {current.get(s.column, s.column) for s in steps
             if s.rule_id == "coerce_numeric" and s.params.get("decimals")}
    _write_xlsx(output, {c.name: c.inferred_type for c in after.columns}, out_dir / "clean.xlsx", money)
    _changelog.write_csv(records, out_dir / "changelog.csv")
    saved = _recipe.from_plan(approved_plan, loaded.source, name=recipe_name)
    _recipe.save(saved, out_dir / "recipe.yaml")
    (out_dir / "report.html").write_text(
        _report.render(result, before, after, saved, records), encoding="utf-8"
    )
    report(100, "Done")
    return result
