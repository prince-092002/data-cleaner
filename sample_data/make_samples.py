"""Generate the three messy sample files and their ground truth. Deterministic: same seed, same files.

    python sample_data/make_samples.py

All data is synthetic. Files written next to this script:
  sales_orders_messy.csv   windows-1252, semicolon-delimited, currency, mixed dates, duplicates
  customers_messy.xlsx     two sheets, title rows above the header, hidden characters, outlier
  hr_survey_messy.csv      UTF-8 with BOM, quoted commas, ambiguous dates, duplicate/empty headers
  ground_truth.csv         one row per injected error, across all three files

ground_truth.csv columns: file, row, column, error_type, original_value, injected_value
  row              1-based data row in the final file (header not counted; for the xlsx, the
                   1-based row among the data rows below the header row of the Customers sheet).
                   0 for structural errors (header, title, encoding, delimiter, whole file).
  column           header exactly as written in the file. "" for row-level errors (duplicate_row,
                   empty_row) and for structural errors that are not about one column.
  original_value   the clean value before injection; "" when there is none.
  injected_value   what was written.

Error types
  Cell level:
    extra_whitespace            leading, trailing or doubled spaces
    non_breaking_space          U+00A0 inside a name
    zero_width_space            U+200B appended to a name
    case_variant                wrong letter case ("NORTH", "smb", "user1@EXAMPLE.COM")
    typo_category               misspelt category ("Nrth", "Enginering")
    category_synonym            valid but non-standard label ("U.S.A.", "Human Resources")
    null_token                  null spelling ("N/A", "NULL", "-", "?")
    missing_value               empty cell where the generator had a value or no value at all
    placeholder_token           non-null filler text ("unknown")
    invalid_value               text or an impossible date in a number or date column ("see note", "31/02/2024")
    stray_marker                unexplained mark in an unnamed column ("x")
    currency_symbol             "$" prefix on a number
    number_with_thousands_sep   "1,234" grouping
    parentheses_negative        "(123.45)" accounting negative
    percent_symbol              "10%" in a numeric column
    mixed_date_format           non-ISO date (dd/mm/yyyy, "1 Jan 2024", yyyy/mm/dd, "March 4, 2022")
    ambiguous_date              mm/dd/yyyy where day and month are both <= 12
    boolean_variant             "Y", "yes", "TRUE", "n" for a yes/no field
    mojibake                    UTF-8 text decoded as windows-1252 ("CafÃ©")
    outlier                     implausible numeric value
    duplicate_key               ID copied from the previous row
  Row level (column ""):
    duplicate_row               exact copy of an earlier row (copy keeps the cell errors it carries)
    empty_row                   row with no values
  Structural (row 0):
    header_whitespace           header with surrounding spaces
    duplicate_header            same header text used twice
    empty_header                column with no header text
    empty_column                column with no values at all
    title_row                   title line above the header
    blank_row_above_header      blank line between title and header
    non_default_encoding        windows-1252 instead of UTF-8
    non_default_delimiter       semicolon instead of comma
    utf8_bom                    UTF-8 byte order mark

Sheet "Notes" in the xlsx is documentation, not data, and has no entries.
"""

from __future__ import annotations

import csv
import datetime as dt
import random
from pathlib import Path

HERE = Path(__file__).parent
SEED = 42
GT_HEADER = ["file", "row", "column", "error_type", "original_value", "injected_value"]

FIRST = ["José", "Zoë", "Müller", "Anna", "Liam", "Chloé", "Noah", "Søren", "Mia", "Omar",
         "Ava", "Renée", "Lucas", "Iñaki", "Emma", "Jürgen", "Priya", "Wei", "Sofía", "Ethan"]
LAST = ["García", "Smith", "Nuñez", "O'Brien", "Schröder", "Lefèvre", "Khan", "Rossi",
        "Åberg", "Tanaka", "Brown", "Dubois", "Peña", "Novak", "Silva"]

MOJIBAKE = {  # text as written in the file -> clean text it was meant to be
    "CafÃ© area is too small": "Café area is too small",
    "I donâ€™t get enough feedback": "I don’t get enough feedback",
}


class Row(list):
    """One data row: cell values plus the injected errors it carries.

    errs entries are (column, error_type, original_value, injected_value).
    """

    def __init__(self, values=(), errs=()):
        super().__init__(values)
        self.errs = list(errs)

    def copy(self) -> "Row":
        return Row(self, self.errs)


def _txt(value) -> str:
    return "" if value is None else str(value)


def _name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def _currency_tags(amount: float) -> tuple[str, ...]:
    """A "$" prefix is a currency symbol; the generator adds thousands commas from 1,000 up."""
    if amount >= 1000:
        return ("currency_symbol", "number_with_thousands_sep")
    return ("currency_symbol",)


def _pick(rng: random.Random, options: list[tuple], clean) -> tuple[object, list[tuple]]:
    """Weighted choice (same random calls as rng.choices) plus the errors the choice injects.

    options are (value, weight) for clean values, or
    (value, weight, error_type_or_tuple, original) for injected errors. original None means `clean`.
    Returns (value, [(error_type, original_value, injected_value), ...]).
    """
    idx = rng.choices(range(len(options)), weights=[o[1] for o in options])[0]
    opt = options[idx]
    if len(opt) == 2:
        return opt[0], []
    tags = (opt[2],) if isinstance(opt[2], str) else opt[2]
    original = clean if opt[3] is None else opt[3]
    return opt[0], [(tag, _txt(original), _txt(opt[0])) for tag in tags]


def _add(errs: list, column: str, found: list[tuple]) -> None:
    errs.extend((column, *e) for e in found)


def _duplicate(src: Row) -> Row:
    dup = src.copy()
    dup.errs.append(("", "duplicate_row", "", ""))
    return dup


def _overwrite(row: Row, idx: int, column: str, value, error_type: str) -> None:
    """Replace one cell with an injected value. original_value stays the clean value."""
    earlier = [e[2] for e in row.errs if e[0] == column]
    original = earlier[0] if earlier else row[idx]
    row.errs = [e for e in row.errs if e[0] != column]
    row[idx] = value
    row.errs.append((column, error_type, _txt(original), _txt(value)))


def _label_duplicates(rows: list[Row]) -> None:
    """A copy can be inserted above the row it was copied from. remove_exact_duplicate_rows keeps
    the first occurrence, so the duplicate_row label belongs on every later identical row."""
    seen: set[tuple] = set()
    for row in rows:
        row.errs = [e for e in row.errs if e[1] != "duplicate_row"]
        if all(v in (None, "") for v in row):
            continue
        if tuple(row) in seen:
            row.errs.append(("", "duplicate_row", "", ""))
        seen.add(tuple(row))


def _records(file_name: str, rows: list[Row]) -> list[tuple]:
    _label_duplicates(rows)
    return [(file_name, n, col, tag, orig, inj)
            for n, row in enumerate(rows, 1) for col, tag, orig, inj in row.errs]


# --------------------------------------------------------------------------- 1. sales (CSV)

def _mojibake_name(name: str) -> str:
    """The name as a double-encoded export shows it: UTF-8 bytes read as windows-1252."""
    return name.encode("utf-8").decode("cp1252")


def make_sales(rng: random.Random, out_dir: Path) -> list[tuple]:
    name_file = "sales_orders_messy.csv"
    header = ["Order ID", " Customer Name ", "Order Date", "Amount (USD)", "Discount %",
              "Region", "Paid?", "ZIP Code", "Notes", "Unnamed"]
    rows: list[Row] = []
    start = dt.date(2024, 1, 1)
    for i in range(1, 401):
        errs: list[tuple] = []
        order_clean = f"ORD-{i:05d}"
        order_id, found = _pick(rng, [
            (order_clean, 60),
            ("", 14, "missing_value", None),
            (f" {order_clean}", 10, "extra_whitespace", None),
            ("N/A", 4, "null_token", None),
            ("TBD", 3, "null_token", None),
        ], order_clean)
        _add(errs, header[0], found)
        d = start + dt.timedelta(days=rng.randrange(0, 360))
        date, found = _pick(rng, [
            (d.isoformat(), 48),
            (d.strftime("%d/%m/%Y"), 14, "mixed_date_format", None),
            (f"{d.day} {d.strftime('%b')} {d.year}", 4, "mixed_date_format", None),
            (f"{d.year}/{d.month:02d}/{d.day:02d}", 3, "mixed_date_format", None),
            ("TBD", 3, "null_token", None),
            ("N/A", 3, "null_token", None),
            ("", 9, "missing_value", None),
            ("soon", 3, "invalid_value", None),
            ("31/02/2024", 2, "invalid_value", None),
            ("99/99/9999", 1, "invalid_value", None),
        ], d.isoformat())
        _add(errs, "Order Date", found)
        amount = round(rng.uniform(20, 5000), 2)
        amount_txt, found = _pick(rng, [
            (f"{amount:.2f}", 45),
            (f"${amount:,.2f}", 15, _currency_tags(amount), None),
            (f"({amount:.2f})", 2, "parentheses_negative", f"-{amount:.2f}"),  # CONTRACT 2.3: (x) = -x
            (f" {amount:.2f} ", 4, "extra_whitespace", None),
            ("N/A", 5, "null_token", None),
            ("TBD", 3, "null_token", None),
            ("", 10, "missing_value", None),
            ("abc", 3, "invalid_value", None),
            ("12..5", 1, "invalid_value", None),
            ("?", 2, "null_token", None),
        ], f"{amount:.2f}")
        _add(errs, "Amount (USD)", found)
        disc = rng.choice([0, 5, 10, 15, 20])
        discount, found = _pick(rng, [
            (str(disc), 45),
            (f"{disc}%", 15, "percent_symbol", None),
            ("", 16, "missing_value", None),
            ("N/A", 8, "null_token", None),
            ("TBD", 5, "null_token", None),
            ("?", 5, "null_token", None),
        ], str(disc))
        _add(errs, "Discount %", found)
        clean_region = rng.choice(["North", "South", "East", "West"])
        region, found = _pick(rng, [
            (clean_region, 50),
            ("north", 3, "case_variant", "North"),
            ("NORTH", 3, "case_variant", "North"),
            ("Nrth", 2, "typo_category", "North"),
            ("South ", 4, "extra_whitespace", "South"),
            ("Sout", 2, "typo_category", "South"),
            ("  east", 3, ("extra_whitespace", "case_variant"), "East"),
            ("EAST", 3, "case_variant", "East"),
            ("Wset", 2, "typo_category", "West"),
            ("west ", 3, ("extra_whitespace", "case_variant"), "West"),
            ("N/A", 3, "null_token", None),
            ("", 4, "missing_value", None),
            ("?", 2, "null_token", None),
        ], clean_region)
        _add(errs, "Region", found)
        paid, found = _pick(rng, [
            ("Yes", 26), ("No", 20),
            ("Y", 6, "boolean_variant", "Yes"),
            ("N", 5, "boolean_variant", "No"),
            ("TRUE", 4, "boolean_variant", "Yes"),
            ("false", 4, "boolean_variant", "No"),
            ("yes", 3, "boolean_variant", "Yes"),
            ("no", 2, "boolean_variant", "No"),
            ("", 6, "missing_value", None),
            ("N/A", 4, "null_token", None),
            ("?", 4, "null_token", None),
        ], None)
        _add(errs, "Paid?", found)
        name = _name(rng)
        moj = _mojibake_name(name)
        name, found = _pick(rng, [
            (name, 48),
            (f"  {name}", 4, "extra_whitespace", None),
            (name.upper(), 4, "case_variant", None),
            (name.replace(" ", "  "), 5, "extra_whitespace", None),
            (f"{name} ", 4, "extra_whitespace", None),
            (name.lower(), 2, "case_variant", None),
            (moj, 6 if moj != name else 0, "mojibake", None),
            ("", 10, "missing_value", None),
            ("unknown", 3, "placeholder_token", None),
        ], name)
        _add(errs, header[1], found)
        notes, found = _pick(rng, [
            ("", 68, "missing_value", None),
            ("-", 6, "null_token", None),
            ("?", 4, "null_token", None),
            ("N/A", 6, "null_token", None),
            ("TBD", 3, "null_token", None),
            ("priority", 5),
            ("gift wrap", 5),
            ("gift  wrap", 3, "extra_whitespace", "gift wrap"),
        ], "")
        _add(errs, "Notes", found)
        zip_clean = f"{rng.randrange(1000, 99999):05d}"
        zip_code, found = _pick(rng, [
            (zip_clean, 55),
            ("", 18, "missing_value", None),
            (f" {zip_clean}", 8, "extra_whitespace", None),
            ("N/A", 6, "null_token", None),
            ("?", 6, "null_token", None),
        ], zip_clean)
        _add(errs, "ZIP Code", found)
        rows.append(Row([order_id, name, date, amount_txt, discount, region, paid,
                         zip_code, notes, ""], errs))
    for _ in range(25):                                   # exact duplicate rows
        rows.insert(rng.randrange(len(rows)), _duplicate(rng.choice(rows)))
    for _ in range(8):                                    # completely empty rows
        rows.insert(rng.randrange(len(rows)), Row([""] * len(header), [("", "empty_row", "", "")]))

    with open(out_dir / name_file, "w", encoding="cp1252", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)

    structural = [
        (0, " Customer Name ", "header_whitespace", "Customer Name", " Customer Name "),
        (0, "Unnamed", "empty_column", "", ""),
        (0, "", "non_default_encoding", "utf-8", "windows-1252"),
        (0, "", "non_default_delimiter", ",", ";"),
    ]
    return [(name_file, *s) for s in structural] + _records(name_file, rows)


# --------------------------------------------------------------------------- 2. customers (XLSX)

def make_customers(rng: random.Random, out_dir: Path) -> list[tuple]:
    from openpyxl import Workbook

    name_file = "customers_messy.xlsx"
    header = ["CustomerID", "Full Name", "Email", "Phone", "Signup Date", "Lifetime Value",
              "Active", "Segment", "Country"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Customers"
    ws.append(["Customer export - generated for demo"])
    ws.append([])
    ws.append(header)
    rows: list[Row] = []
    for i in range(250):
        errs: list[tuple] = []
        name = _name(rng)
        name, found = _pick(rng, [
            (name, 78),
            (name.replace(" ", "\xa0"), 8, "non_breaking_space", None),
            (name + "​", 6, "zero_width_space", None),
            (f" {name}  ", 8, "extra_whitespace", None),
        ], name)
        _add(errs, header[1], found)
        email_user = f"user{i}"
        email, found = _pick(rng, [
            (f"{email_user}@example.com", 80),
            (f"{email_user.upper()}@Example.COM", 10, "case_variant", None),
            ("n/a", 5, "null_token", None),
            (None, 5, "missing_value", None),
        ], f"{email_user}@example.com")
        _add(errs, header[2], found)
        phone = f"({rng.randrange(200, 999)}) 555-{rng.randrange(0, 9999):04d}"
        d = dt.datetime(2022, 1, 1) + dt.timedelta(days=rng.randrange(0, 900))
        signup, found = _pick(rng, [
            (d, 75),
            (d.strftime("%Y/%m/%d"), 10, "mixed_date_format", None),
            (d.strftime("%B %d, %Y").replace(" 0", " "), 10, "mixed_date_format", None),
            (None, 5, "missing_value", None),
        ], d.strftime("%Y-%m-%d"))
        _add(errs, header[4], found)
        value = round(rng.uniform(100, 9000), 2)
        ltv, found = _pick(rng, [
            (value, 80),
            (f"${value:,.2f}", 12, _currency_tags(value), None),
            (None, 5, "missing_value", None),
            ("unknown", 3, "placeholder_token", None),
        ], value)
        _add(errs, header[5], found)
        active, found = _pick(rng, [
            (True, 45), (False, 30),
            ("yes", 10, "boolean_variant", "TRUE"),
            ("no", 8, "boolean_variant", "FALSE"),
            ("Y", 4, "boolean_variant", "TRUE"),
            (None, 3, "missing_value", None),
        ], None)
        _add(errs, header[6], found)
        segment, found = _pick(rng, [
            ("Enterprise", 30), ("SMB", 30), ("Consumer", 25),
            ("enterprise", 4, "case_variant", "Enterprise"),
            ("Enterprize", 3, "typo_category", "Enterprise"),
            ("smb", 4, "case_variant", "SMB"),
            ("Consumr", 2, "typo_category", "Consumer"),
            ("CONSUMER", 2, "case_variant", "Consumer"),
        ], None)
        _add(errs, header[7], found)
        country, found = _pick(rng, [
            ("USA", 50), ("UK", 20), ("Canada", 15),
            ("usa", 5, "case_variant", "USA"),
            ("U.S.A.", 4, "category_synonym", "USA"),
            ("Canda", 3, "typo_category", "Canada"),
            ("uk ", 3, ("case_variant", "extra_whitespace"), "UK"),
        ], None)
        _add(errs, header[8], found)
        rows.append(Row([1001 + i, name, email, phone, signup, ltv, active, segment, country], errs))
    _overwrite(rows[40], 5, header[5], 9_750_000.0, "outlier")
    _overwrite(rows[120], 0, header[0], rows[119][0], "duplicate_key")
    for _ in range(5):                                     # exact duplicate rows
        rows.insert(rng.randrange(len(rows)), _duplicate(rng.choice(rows)))
    for _ in range(2):                                     # empty rows
        rows.insert(rng.randrange(len(rows)), Row([None] * len(header), [("", "empty_row", "", "")]))
    for row in rows:
        ws.append(list(row))

    notes = wb.create_sheet("Notes")
    notes.append(["Topic", "Note"])
    notes.append(["Source", "Synthetic demo data"])
    notes.append(["Owner", "Data team"])
    wb.save(out_dir / name_file)

    structural = [
        (0, "", "title_row", "", "Customer export - generated for demo"),
        (0, "", "blank_row_above_header", "", ""),
    ]
    return [(name_file, *s) for s in structural] + _records(name_file, rows)


# --------------------------------------------------------------------------- 3. HR survey (CSV)

def make_hr(rng: random.Random, out_dir: Path) -> list[tuple]:
    name_file = "hr_survey_messy.csv"
    header = ["Employee ID", "Department", "Start Date", "Salary", "Remote", "Satisfaction",
              "Comments", "Comments", "", "Manager"]
    comments = ["Great team, good benefits", "Needs better tooling", "CafÃ© area is too small",
                "I donâ€™t get enough feedback", "Flexible hours, remote friendly", "", "", ""]
    rows: list[Row] = []
    for i in range(1, 301):
        errs: list[tuple] = []
        dept, found = _pick(rng, [
            (rng.choice(["Engineering", "Sales", "Marketing", "Finance", "HR"]), 82),
            ("Enginering", 3, "typo_category", "Engineering"),
            ("engineering ", 4, ("case_variant", "extra_whitespace"), "Engineering"),
            ("SALES", 3, "case_variant", "Sales"),
            ("Markting", 2, "typo_category", "Marketing"),
            ("finance", 3, "case_variant", "Finance"),
            ("Human Resources", 3, "category_synonym", "HR"),
        ], None)
        _add(errs, header[1], found)
        month, day, year = rng.randrange(1, 13), rng.randrange(1, 13), rng.randrange(2015, 2025)
        start = f"{month:02d}/{day:02d}/{year}"
        errs.append((header[2], "ambiguous_date", f"{year}-{month:02d}-{day:02d}", start))
        salary = rng.randrange(40, 140) * 1000
        salary_txt, found = _pick(rng, [
            (str(salary), 80),
            (f"${salary:,}", 10, ("currency_symbol", "number_with_thousands_sep"), None),
            (f"{salary:,}", 5, "number_with_thousands_sep", None),
            ("", 3, "missing_value", None),
            ("NULL", 2, "null_token", None),
        ], str(salary))
        _add(errs, header[3], found)
        remote, found = _pick(rng, [
            ("Y", 45), ("N", 45),
            ("y", 5, "boolean_variant", "Y"),
            ("n", 5, "boolean_variant", "N"),
        ], None)
        _add(errs, header[4], found)
        sat_clean = str(rng.randrange(1, 6))
        sat, found = _pick(rng, [
            (sat_clean, 92),
            ("?", 5, "null_token", None),
            ("", 3, "missing_value", None),
        ], sat_clean)
        _add(errs, header[5], found)
        name_a = _name(rng)
        name_b = _name(rng)
        manager, found = _pick(rng, [
            (name_a, 85),
            (name_b + " ", 10, "extra_whitespace", name_b),
            ("", 5, "missing_value", None),
        ], name_a)
        _add(errs, header[9], found)
        comment = rng.choice(comments)
        if comment in MOJIBAKE:
            errs.append((header[6], "mojibake", MOJIBAKE[comment], comment))
        stray, found = _pick(rng, [("", 90), ("x", 10, "stray_marker", "")], None)
        _add(errs, "", found)
        rows.append(Row([f"E{i:04d}", dept, start, salary_txt, remote, sat, comment, "", stray,
                         manager], errs))
    _overwrite(rows[17], 3, header[3], "9999999", "outlier")
    _overwrite(rows[203], 3, header[3], "1", "outlier")
    for _ in range(6):
        rows.insert(rng.randrange(len(rows)), _duplicate(rng.choice(rows)))

    with open(out_dir / name_file, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)

    structural = [
        (0, "Comments", "duplicate_header", "", "Comments"),
        (0, "", "empty_header", "", ""),
        (0, "", "utf8_bom", "", "UTF-8 BOM"),
    ]
    return [(name_file, *s) for s in structural] + _records(name_file, rows)


# --------------------------------------------------------------------------- 4. stores (held-out only)

def make_stores(rng: random.Random, out_dir: Path) -> list[tuple]:
    """Held-out file (M6 step 8). Region uses abbreviations the first batch never had
    (NE, NW, SE, SW, N.E., Ctr, Cent.). The engine was never tuned against this file."""
    name_file = "store_visits_messy.csv"
    header = ["Store ID", "Visit Date", "Region", "Revenue ($)", "Units", "Manager", "Open?"]
    regions = ["Northeast", "Northwest", "Southeast", "Southwest", "Central"]
    short = {"Northeast": "NE", "Northwest": "NW", "Southeast": "SE", "Southwest": "SW", "Central": "Ctr"}
    typo = {"Northeast": "Northest", "Northwest": "Nothwest", "Southeast": "Southeats",
            "Southwest": "Souhtwest", "Central": "Centrl"}
    rows: list[Row] = []
    start = dt.date(2025, 1, 1)
    for i in range(300):
        errs: list[tuple] = []
        store = f"{rng.randrange(1, 400):04d}"
        d = start + dt.timedelta(days=rng.randrange(0, 330))
        date, found = _pick(rng, [
            (d.isoformat(), 60),
            (d.strftime("%m/%d/%Y"), 20, "mixed_date_format", None),
            (d.strftime("%b %d, %Y").replace(" 0", " "), 8, "mixed_date_format", None),
            ("", 6, "missing_value", None),
            ("pending", 3, "invalid_value", None),
            ("N/A", 3, "null_token", None),
        ], d.isoformat())
        _add(errs, header[1], found)
        clean_region = rng.choice(regions)
        region, found = _pick(rng, [
            (clean_region, 52),
            (short[clean_region], 12, "category_abbreviation", None),
            ("N.E.", 2, "category_abbreviation", "Northeast"),
            ("Cent.", 2, "category_abbreviation", "Central"),
            (clean_region.lower(), 5, "case_variant", None),
            (clean_region.upper(), 5, "case_variant", None),
            (typo[clean_region], 6, "typo_category", None),
            (f" {clean_region} ", 5, "extra_whitespace", None),
            ("", 5, "missing_value", None),
            ("TBD", 3, "null_token", None),
            ("-", 3, "null_token", None),
        ], clean_region)
        _add(errs, header[2], found)
        revenue = round(rng.uniform(150, 9000), 2)
        revenue_txt, found = _pick(rng, [
            (f"{revenue:.2f}", 55),
            (f"${revenue:,.2f}", 18, _currency_tags(revenue), None),
            (f"({revenue:.2f})", 3, "parentheses_negative", f"-{revenue:.2f}"),
            (f"{revenue:.2f} ", 5, "extra_whitespace", None),
            ("", 8, "missing_value", None),
            ("N/A", 6, "null_token", None),
            ("n.a.", 3, "placeholder_token", None),
            ("free", 2, "invalid_value", None),
        ], f"{revenue:.2f}")
        _add(errs, header[3], found)
        units = rng.randrange(1, 10)
        units_txt, found = _pick(rng, [
            (str(units), 70),
            (f"0{units}", 10, "leading_zero", None),
            (f"{units} ", 8, "extra_whitespace", None),
            ("", 7, "missing_value", None),
            ("?", 5, "null_token", None),
        ], str(units))
        _add(errs, header[4], found)
        manager = _name(rng)
        manager, found = _pick(rng, [
            (manager, 62),
            (manager.upper(), 10, "case_variant", None),
            (manager.lower(), 6, "case_variant", None),
            (f"{manager}  ", 6, "extra_whitespace", None),
            ("", 10, "missing_value", None),
            ("unknown", 6, "placeholder_token", None),
        ], manager)
        _add(errs, header[5], found)
        is_open, found = _pick(rng, [
            ("Yes", 35), ("No", 25),
            ("Y", 8, "boolean_variant", "Yes"),
            ("N", 8, "boolean_variant", "No"),
            ("TRUE", 6, "boolean_variant", "Yes"),
            ("0", 4, "boolean_variant", "No"),
            ("", 8, "missing_value", None),
            ("N/A", 6, "null_token", None),
        ], None)
        _add(errs, header[6], found)
        rows.append(Row([store, date, region, revenue_txt, units_txt, manager, is_open], errs))
    _overwrite(rows[77], 3, header[3], "880000.00", "outlier")
    for _ in range(12):
        rows.insert(rng.randrange(len(rows)), _duplicate(rng.choice(rows)))
    for _ in range(4):
        rows.insert(rng.randrange(len(rows)), Row([""] * len(header), [("", "empty_row", "", "")]))

    with open(out_dir / name_file, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return _records(name_file, rows)


HELDOUT_SEED = 20261115      # never tune the engine against files made with this seed


def generate(out_dir: Path = HERE, seed: int = SEED, heldout: bool = False) -> Path:
    """Write the three sample files and ground_truth.csv into out_dir. Returns the ground truth path.
    heldout=True also writes store_visits_messy.csv (a file type the first batch does not have)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records = make_sales(random.Random(seed), out_dir)
    records += make_customers(random.Random(seed + 1), out_dir)
    records += make_hr(random.Random(seed + 2), out_dir)
    if heldout:
        records += make_stores(random.Random(seed + 3), out_dir)
    path = out_dir / "ground_truth.csv"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(GT_HEADER)
        writer.writerows(records)
    return path


def generate_heldout(out_dir: Path = HERE / "heldout") -> Path:
    """The held-out batch (M6 step 8): same generators, a different seed, plus the stores file."""
    return generate(out_dir, seed=HELDOUT_SEED, heldout=True)


if __name__ == "__main__":
    generate()
    generate_heldout()
    print("wrote 3 sample files and ground_truth.csv to", HERE, "and the held-out batch to", HERE / "heldout")
