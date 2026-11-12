"""HTML cleaning report: one self-contained file (inline CSS, no scripts, no external assets)."""

from __future__ import annotations

from html import escape

from engine import ENGINE_VERSION
from engine.changelog import ChangeRecord
from engine.models import WEIGHTS, CleanResult, DatasetProfile
from engine.rules.registry import RULES_BY_ID

SAMPLE_CHANGES = 50

_CSS = """
:root{--ink:#0f172a;--muted:#475569;--line:#e2e8f0;--bg:#f8fafc;--accent:#2563eb;--good:#15803d;--bad:#b91c1c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1000px;margin:0 auto;padding:32px 20px 64px}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:18px;margin:36px 0 12px}
p.meta{color:var(--muted);margin:0 0 24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px}
.card .label{color:var(--muted);font-size:13px}
.card .value{font-size:28px;font-weight:650;margin-top:2px}
.card .sub{color:var(--muted);font-size:13px}
.table-wrap{overflow-x:auto;background:#fff;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#f1f5f9;font-weight:600;white-space:nowrap}
tr:last-child td{border-bottom:0}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.up{color:var(--good);font-weight:600}.down{color:var(--bad);font-weight:600}.same{color:var(--muted)}
.bar{height:8px;background:var(--line);border-radius:4px;min-width:90px}
.bar span{display:block;height:8px;background:var(--accent);border-radius:4px}
.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;background:#e0e7ff;color:#3730a3}
.tag.approved{background:#dcfce7;color:#166534}
code{font-family:ui-monospace,Consolas,monospace;font-size:13px;background:#f1f5f9;padding:1px 5px;border-radius:4px;word-break:break-word}
.empty{color:var(--muted);font-style:italic}
ul.warn{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 12px 12px 32px}
footer{margin-top:40px;color:var(--muted);font-size:13px}
"""


def _delta(before: float | None, after: float | None) -> str:
    if before is None or after is None:
        return '<span class="same">-</span>'
    diff = round(after - before, 1)
    if diff > 0:
        return f'<span class="up">+{diff}</span>'
    if diff < 0:
        return f'<span class="down">{diff}</span>'
    return '<span class="same">0.0</span>'


def _cell(value: str | None) -> str:
    if value is None:
        return '<span class="empty">empty</span>'
    text = value if len(value) <= 120 else value[:120] + "..."
    return f"<code>{escape(text)}</code>"


def _table(headers: list[tuple[str, bool]], rows: list[list[str]]) -> str:
    head = "".join(f'<th scope="col"{" class=num" if num else ""}>{escape(h)}</th>' for h, num in headers)
    body = "".join(
        "<tr>"
        + "".join(f'<td{" class=num" if headers[i][1] else ""}>{cell}</td>' for i, cell in enumerate(row))
        + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _label(rule_id: str) -> str:
    rule = RULES_BY_ID.get(rule_id)
    return rule.label if rule else rule_id


def render(
    result: CleanResult,
    before: DatasetProfile,
    after: DatasetProfile,
    recipe,
    records: list[ChangeRecord],
) -> str:
    s = result.summary
    src = before.source
    details = [f"File: {escape(src.filename)}"]
    if src.sheet:
        details.append(f"Sheet: {escape(src.sheet)}")
    if src.encoding:
        details.append(f"Encoding: {escape(src.encoding)}")
    if src.delimiter:
        details.append(f"Delimiter: {escape(repr(src.delimiter))}")
    details.append(f"Created: {escape(recipe.created_at)}")
    details.append(f"Run: {escape(result.run_id)}")

    cards = f"""
<div class="cards">
  <div class="card"><div class="label">Quality score</div><div class="value">{result.after.overall}</div>
    <div class="sub">was {result.before.overall} ({_delta(result.before.overall, result.after.overall)})</div></div>
  <div class="card"><div class="label">Changes logged</div><div class="value">{s.total_changes:,}</div>
    <div class="sub">{s.cells_changed:,} cells changed</div></div>
  <div class="card"><div class="label">Rows</div><div class="value">{s.rows_after:,}</div>
    <div class="sub">was {s.rows_before:,} ({s.rows_removed:,} removed)</div></div>
  <div class="card"><div class="label">Columns</div><div class="value">{s.columns_after:,}</div>
    <div class="sub">was {s.columns_before:,} ({s.columns_removed} removed, {s.columns_added} added)</div></div>
</div>"""

    dims = [("overall", "Overall", None)] + [(d, d.capitalize(), w) for d, w in WEIGHTS.items()]
    dim_rows = []
    for key, label, weight in dims:
        b, a = getattr(result.before, key), getattr(result.after, key)
        dim_rows.append([
            f"<strong>{label}</strong>" if weight is None else label,
            "" if weight is None else f"{int(weight * 100)}%",
            str(b), str(a), _delta(b, a),
            f'<div class="bar" role="img" aria-label="{a} out of 100"><span style="width:{a}%"></span></div>',
        ])
    dim_table = _table(
        [("Dimension", False), ("Weight", True), ("Before", True), ("After", True), ("Change", True), ("After", False)],
        dim_rows,
    )

    rule_rows = [
        [
            escape(_label(r.rule_id)),
            f'<span class="tag {r.action}">{"approved by you" if r.action == "approved" else "automatic"}</span>',
            f"{r.changes:,}",
            escape(", ".join(r.columns)) or '<span class="empty">whole table</span>',
        ]
        for r in s.by_rule
    ]
    rule_table = (
        _table([("Fix", False), ("How", False), ("Changes", True), ("Columns", False)], rule_rows)
        if rule_rows
        else '<p class="empty">No changes were made.</p>'
    )

    col_rows = []
    for c in result.columns:
        b = c.before.score if c.before else None
        a = c.after.score if c.after else None
        note = "removed" if c.after is None else "added" if c.before is None else ""
        col_rows.append([
            f"<code>{escape(c.name)}</code>" + (f' <span class="tag">{note}</span>' if note else ""),
            "-" if b is None else str(b), "-" if a is None else str(a), _delta(b, a),
        ])
    col_table = _table([("Column", False), ("Before", True), ("After", True), ("Change", True)], col_rows)

    change_rows = [
        [
            escape(_label(r.rule_id)),
            "-" if r.row_id is None else str(r.row_id),
            f"<code>{escape(r.column)}</code>" if r.column else '<span class="empty">whole row</span>',
            escape(r.change_type.replace("_", " ")),
            _cell(r.old_value), _cell(r.new_value),
        ]
        for r in records[:SAMPLE_CHANGES]
    ]
    change_table = (
        _table([("Fix", False), ("Row", True), ("Column", False), ("Type", False), ("Before", False), ("After", False)],
               change_rows)
        if change_rows
        else '<p class="empty">No changes were made.</p>'
    )

    warnings = ""
    if result.warnings:
        items = "".join(f"<li>{escape(w)}</li>" for w in result.warnings)
        warnings = f'<h2>Warnings</h2><ul class="warn">{items}</ul>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cleaning report - {escape(src.filename)}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>Cleaning report</h1>
<p class="meta">{" &middot; ".join(details)}</p>
{cards}
<h2>Quality score, before and after</h2>
{dim_table}
<h2>What was fixed</h2>
{rule_table}
{warnings}
<h2>Score by column</h2>
{col_table}
<h2>Sample of changes (first {min(len(records), SAMPLE_CHANGES)} of {len(records):,})</h2>
{change_table}
<p class="meta" style="margin-top:12px">Every change is listed in changelog.csv. The original file was not modified.</p>
<footer>Data Cleaner engine {escape(ENGINE_VERSION)} &middot; Recipe: {escape(recipe.name)} ({len(recipe.steps)} steps)</footer>
</main>
</body>
</html>
"""
