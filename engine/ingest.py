"""Ingest: encoding, delimiter, header row, Excel sheets; reads every cell as text.

The original file is opened read-only and never modified. See docs/CONTRACT.md section 1.
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import math
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from engine.errors import IngestError
from engine.models import FileInspection, SheetInspection, SourceInfo
from engine.parsing import parse_date, parse_number, unique_column_names

ROW_ID = "_row_id"
PREVIEW_ROWS = 10
HEADER_SCAN_ROWS = 20
_ENCODING_SAMPLE_BYTES = 200_000
_DIALECT_SAMPLE_CHARS = 8_000

Row = list[str | None]


@dataclass
class IngestResult:
    df: pl.DataFrame                 # every data column is Utf8, plus _row_id (Int64)
    source: SourceInfo
    source_names: dict[str, str]     # dataframe column -> header text exactly as uploaded


# --------------------------------------------------------------------------- file type

def file_type_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".csv":
        return "csv"
    if ext == ".xlsx":
        return "xlsx"
    raise IngestError("Only .csv and .xlsx files are supported.")


# --------------------------------------------------------------------------- CSV

_WESTERN_GUESSES = {
    "latin-1", "iso8859-1", "iso-8859-1", "cp1250", "cp1252", "iso8859-15", "ascii",
    "iso8859-2", "iso8859-4", "iso8859-9", "iso8859-10", "iso8859-13", "iso8859-14",
    "iso8859-16", "cp1254", "cp1257",
}


def detect_encoding(data: bytes) -> str:
    """UTF-8 (with or without BOM) if the bytes are valid UTF-8, else charset-normalizer's guess."""
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    from charset_normalizer import from_bytes

    best = from_bytes(data[:_ENCODING_SAMPLE_BYTES]).best()
    guess = (best.encoding if best else "cp1252").lower().replace("_", "-")
    # Western European single-byte guesses are near-identical; prefer the common superset.
    # Other Latin-script single-byte guesses (Latin-2/4/5/6/7/8 variants) are common mistakes for
    # accented Western text, so they get the same treatment. Cyrillic, Greek and Arabic do not.
    if guess in _WESTERN_GUESSES:
        try:
            data.decode("cp1252")
            return "windows-1252"
        except UnicodeDecodeError:
            return "latin-1"
    return guess


def detect_delimiter(text: str) -> str:
    sample = text[:_DIALECT_SAMPLE_CHARS]
    # Cut at the last full line so a half line does not confuse the sniffer.
    if len(text) > _DIALECT_SAMPLE_CHARS and "\n" in sample:
        sample = sample[: sample.rindex("\n")]
    candidates = [",", ";", "\t", "|"]
    try:
        import clevercsv

        dialect = clevercsv.Sniffer().sniff(sample, delimiters=candidates)
        if dialect and dialect.delimiter in candidates:
            return dialect.delimiter
    except Exception:
        pass
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(candidates)).delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample else ""
        return max(candidates, key=first.count)


def _read_csv(path: Path, max_rows: int | None = None) -> tuple[list[Row], str, str]:
    data = path.read_bytes()
    if not data.strip():
        raise IngestError("The file is empty.")
    encoding = detect_encoding(data)
    text = data.decode(encoding, errors="replace")
    delimiter = detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows: list[Row] = []
    for raw in reader:
        rows.append([cell if cell != "" else None for cell in raw])
        if max_rows is not None and len(rows) >= max_rows:
            break
    return rows, encoding, delimiter


# --------------------------------------------------------------------------- Excel

def _excel_cell(value: object) -> str | None:
    """Turn one Excel cell into text without inventing precision (1.0 -> '1')."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)
    if isinstance(value, _dt.datetime):
        if value.time() == _dt.time(0, 0):
            return value.date().isoformat()
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, (_dt.date, _dt.time)):
        return value.isoformat()
    text = str(value)
    return text if text != "" else None


def _excel_file(path: Path):
    import pandas as pd

    try:
        return pd.ExcelFile(path, engine="openpyxl")
    except Exception as exc:  # corrupt or not really an xlsx
        raise IngestError("This Excel file could not be opened.") from exc


def _read_excel_sheet(xl, sheet: str, max_rows: int | None = None) -> list[Row]:
    import pandas as pd

    frame = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=object, nrows=max_rows)
    return [[_excel_cell(v) for v in row] for row in frame.itertuples(index=False, name=None)]


# --------------------------------------------------------------------------- header row

def _filled(row: Row) -> list[str]:
    return [c for c in row if c is not None and c.strip() != ""]


def detect_header_row(rows: list[Row]) -> int:
    """First row that is well filled and contains only label-like cells (no numbers or dates)."""
    sample = rows[:HEADER_SCAN_ROWS]
    counts = sorted(len(_filled(r)) for r in sample if _filled(r))
    if not counts:
        return 0
    typical = counts[len(counts) // 2]
    need = max(1, math.ceil(0.6 * typical))
    for i, row in enumerate(sample):
        cells = _filled(row)
        if len(cells) < need:
            continue
        if any(parse_number(c) or parse_date(c) for c in cells):
            continue
        return i
    return 0


# --------------------------------------------------------------------------- public

def inspect(path: Path) -> FileInspection:
    """Cheap look at an upload: sheets, detected header row, first raw rows of each sheet."""
    path = Path(path)
    ftype = file_type_of(path)
    sheets: list[SheetInspection] = []
    if ftype == "csv":
        rows, _, _ = _read_csv(path, max_rows=HEADER_SCAN_ROWS)
        with path.open("rb") as fh:
            line_count = sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 20), b""))
        sheets.append(_sheet_inspection(None, rows, max(line_count, len(rows))))
    else:
        xl = _excel_file(path)
        try:
            for name in xl.sheet_names:
                rows = _read_excel_sheet(xl, name, max_rows=HEADER_SCAN_ROWS)
                estimate = getattr(xl.book[name], "max_row", None) or len(rows)
                sheets.append(_sheet_inspection(name, rows, estimate))
        finally:
            xl.close()
        if not sheets:
            raise IngestError("This Excel file has no sheets.")
    return FileInspection(
        filename=path.name, file_type=ftype, size_bytes=path.stat().st_size, sheets=sheets
    )


def _sheet_inspection(name: str | None, rows: list[Row], estimate: int) -> SheetInspection:
    width = max((len(r) for r in rows), default=0)
    preview = [[c or "" for c in r] + [""] * (width - len(r)) for r in rows[:PREVIEW_ROWS]]
    return SheetInspection(
        name=name,
        row_count_estimate=estimate,
        detected_header_row=detect_header_row(rows),
        preview=preview,
    )


def ingest(
    path: Path,
    sheet: str | None = None,
    header_row: int | None = None,
    display_name: str | None = None,
) -> IngestResult:
    """Read a CSV or Excel sheet into an all-text dataframe with a stable _row_id.

    display_name is the file name shown to the user (reports, recipes) when the file is
    stored under a different name on disk.
    """
    path = Path(path)
    ftype = file_type_of(path)
    encoding = delimiter = None
    if ftype == "csv":
        rows, encoding, delimiter = _read_csv(path)
        sheet = None
    else:
        xl = _excel_file(path)
        try:
            if sheet is None:
                sheet = xl.sheet_names[0]
            elif sheet not in xl.sheet_names:
                raise IngestError(f'Sheet "{sheet}" was not found in this file.')
            rows = _read_excel_sheet(xl, sheet)
        finally:
            xl.close()

    if not any(_filled(r) for r in rows):
        raise IngestError("The file has no data.")
    if header_row is None:
        header_row = detect_header_row(rows)
    if not 0 <= header_row < len(rows):
        raise IngestError("The header row is outside the file.")

    data_rows = rows[header_row + 1 :]
    width = max(len(r) for r in rows[header_row:])
    headers = [(c or "") for c in rows[header_row]] + [""] * (width - len(rows[header_row]))
    columns = unique_column_names(headers, reserved={ROW_ID})

    data: dict[str, list] = {ROW_ID: list(range(1, len(data_rows) + 1))}
    for j, col in enumerate(columns):
        data[col] = [r[j] if j < len(r) else None for r in data_rows]
    schema = {ROW_ID: pl.Int64, **{c: pl.Utf8 for c in columns}}
    df = pl.DataFrame(data, schema=schema)

    return IngestResult(
        df=df,
        source=SourceInfo(
            filename=display_name or path.name, file_type=ftype, encoding=encoding, delimiter=delimiter,
            sheet=sheet, header_row=header_row,
        ),
        source_names=dict(zip(columns, headers)),
    )
