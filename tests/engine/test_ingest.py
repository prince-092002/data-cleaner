import hashlib
from pathlib import Path

import polars as pl
import pytest

from engine import ingest
from engine.errors import IngestError

SAMPLES = Path(__file__).parents[2] / "sample_data"
SALES = SAMPLES / "sales_orders_messy.csv"
CUSTOMERS = SAMPLES / "customers_messy.xlsx"
HR = SAMPLES / "hr_survey_messy.csv"


def _write(tmp_path, name, text, encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def test_all_columns_are_text_with_row_id(tmp_path):
    path = _write(tmp_path, "a.csv", "id,amount,when\n001,12.50,2024-01-02\n002,,2024-01-03\n")
    result = ingest.ingest(path)
    df = result.df
    assert df.columns == ["_row_id", "id", "amount", "when"]
    assert df["_row_id"].to_list() == [1, 2]
    assert all(df.schema[c] == pl.Utf8 for c in ("id", "amount", "when"))
    assert df["id"].to_list() == ["001", "002"]          # leading zeros survive
    assert df["amount"].to_list() == ["12.50", None]     # empty cell is null


def test_original_file_is_not_modified():
    before = hashlib.sha256(SALES.read_bytes()).hexdigest()
    ingest.ingest(SALES)
    assert hashlib.sha256(SALES.read_bytes()).hexdigest() == before


def test_windows_1252_semicolon_csv():
    result = ingest.ingest(SALES)
    assert result.source.encoding == "windows-1252"
    assert result.source.delimiter == ";"
    assert result.source.header_row == 0
    assert result.df.width == 11
    names = " ".join(result.df[" Customer Name "].drop_nulls().to_list())
    assert "é" in names and "ñ" in names and "�" not in names


def test_utf8_bom_and_quoted_commas():
    result = ingest.ingest(HR)
    assert result.source.encoding == "utf-8-sig"
    assert result.source.delimiter == ","
    assert result.df.columns[1] == "Employee ID"         # BOM is not part of the header
    assert "Great team, good benefits" in result.df["Comments"].to_list()


def test_duplicate_and_empty_headers_stay_addressable():
    result = ingest.ingest(HR)
    assert {"Comments", "Comments_2", "column_9"} <= set(result.df.columns)
    assert result.source_names["Comments_2"] == "Comments"
    assert result.source_names["column_9"] == ""


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_delimiter_detection(tmp_path, delimiter):
    lines = [delimiter.join(r) for r in (["name", "city", "qty"], ["Ann", "Oslo", "3"], ["Bo", "Rome", "5"])]
    path = _write(tmp_path, "d.csv", "\n".join(lines) + "\n")
    result = ingest.ingest(path)
    assert result.source.delimiter == delimiter
    assert result.df["city"].to_list() == ["Oslo", "Rome"]


def test_ragged_rows_are_padded(tmp_path):
    path = _write(tmp_path, "r.csv", "a,b,c\n1,2\n1,2,3,4\n")
    df = ingest.ingest(path).df
    assert df.height == 2 and df.width == 5              # _row_id + a, b, c + extra column
    assert df["c"].to_list() == [None, "3"]


def test_excel_sheets_and_header_row_detection():
    info = ingest.inspect(CUSTOMERS)
    assert [s.name for s in info.sheets] == ["Customers", "Notes"]
    assert info.sheets[0].detected_header_row == 2
    assert info.sheets[0].preview[2][0] == "CustomerID"
    assert len(info.sheets[0].preview) == 10

    result = ingest.ingest(CUSTOMERS)
    assert result.source.sheet == "Customers" and result.source.header_row == 2
    assert result.df.columns[1:4] == ["CustomerID", "Full Name", "Email"]
    assert all(dtype == pl.Utf8 for name, dtype in result.df.schema.items() if name != "_row_id")


def test_excel_cells_become_clean_text():
    df = ingest.ingest(CUSTOMERS).df
    assert df["CustomerID"].drop_nulls()[0] == "1001"                     # not "1001.0"
    assert set(df["Active"].drop_nulls().unique()) >= {"TRUE", "FALSE"}
    assert df["Signup Date"].drop_nulls().str.contains(r"^\d{4}-\d{2}-\d{2}$").any()


def test_excel_pick_sheet_and_header_override():
    result = ingest.ingest(CUSTOMERS, sheet="Notes", header_row=0)
    assert result.df.columns == ["_row_id", "Topic", "Note"]
    assert result.df.height == 2


def test_csv_inspect():
    info = ingest.inspect(SALES)
    assert info.file_type == "csv" and len(info.sheets) == 1
    sheet = info.sheets[0]
    assert sheet.name is None and sheet.detected_header_row == 0
    assert sheet.preview[0][0] == "Order ID"
    assert sheet.row_count_estimate == 434


def test_errors(tmp_path):
    with pytest.raises(IngestError):
        ingest.ingest(_write(tmp_path, "x.txt", "a,b\n1,2\n"))
    with pytest.raises(IngestError):
        ingest.ingest(_write(tmp_path, "empty.csv", "  \n"))
    with pytest.raises(IngestError):
        ingest.ingest(_write(tmp_path, "fake.xlsx", "not really excel"))
    with pytest.raises(IngestError):
        ingest.ingest(CUSTOMERS, sheet="Nope")
