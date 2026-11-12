import pytest

from engine import parsing as P


@pytest.mark.parametrize("value", ["", "NA", "n/a", "NULL", "-", "?", "#N/A", "tbd", "  N/A  "])
def test_null_tokens(value):
    assert P.is_null_token(value)


@pytest.mark.parametrize("value", ["0", "none at all", "N", "--"])
def test_not_null_tokens(value):
    assert not P.is_null_token(value)


def test_normalize_header_names():
    headers = ["Order ID", " Customer Name ", "Amount (USD)", "", "Comments", "Comments", "unitPrice", "Café"]
    assert P.normalize_header_names(headers) == [
        "order_id", "customer_name", "amount_usd", "column_4", "comments", "comments_2",
        "unit_price", "cafe",
    ]


@pytest.mark.parametrize(
    "raw, canonical",
    [
        ("$1,234.50", "1234.50"),
        ("(123)", "-123"),
        ("45%", "45"),
        (" 12.5 ", "12.5"),
        ("-7", "-7"),
        ("€ 1,000", "1000"),
        (".5", "0.5"),
    ],
)
def test_parse_number(raw, canonical):
    assert P.parse_number(raw).canonical == canonical


@pytest.mark.parametrize("raw", ["abc", "12/05/2024", "1,23", "1.2.3", "$", "12 apples", "--5"])
def test_parse_number_rejects(raw):
    assert P.parse_number(raw) is None


def test_leading_zero_detection():
    assert P.parse_number("00123").leading_zero
    assert not P.parse_number("0").leading_zero
    assert not P.parse_number("0.5").leading_zero


def test_id_like_names():
    assert P.is_id_like_name("ZIP Code")
    assert P.is_id_like_name("customer_id")
    assert not P.is_id_like_name("amount")
    assert not P.is_id_like_name("paid")


@pytest.mark.parametrize(
    "raw, expected", [("Yes", True), ("n", False), ("TRUE", True), ("0", False), ("off", False)]
)
def test_parse_bool(raw, expected):
    assert P.parse_bool(raw).value is expected


def test_parse_bool_rejects():
    assert P.parse_bool("maybe") is None


@pytest.mark.parametrize(
    "raw, dayfirst, iso",
    [
        ("2024-04-03", False, "2024-04-03"),
        ("2024/4/3", False, "2024-04-03"),
        ("03/04/2024", True, "2024-04-03"),
        ("03/04/2024", False, "2024-03-04"),
        ("5 Apr 2024", False, "2024-04-05"),
        ("April 5, 2024", False, "2024-04-05"),
        ("5-Apr-24", False, "2024-04-05"),
        ("2024-04-03 14:05", False, "2024-04-03T14:05:00"),
        ("3/4/24 2:30 PM", True, "2024-04-03T14:30:00"),
    ],
)
def test_parse_date(raw, dayfirst, iso):
    assert P.parse_date(raw).to_iso(dayfirst) == iso


@pytest.mark.parametrize("raw", ["hello", "12345", "2024-13-40", "31/31/2024", "5 Foo 2024", "1.5"])
def test_parse_date_rejects(raw):
    assert P.parse_date(raw) is None


def _order(values):
    return P.decide_date_order({v: (P.parse_date(v), 1) for v in values})


def test_date_order_dayfirst_when_a_day_exceeds_12():
    order = _order(["03/04/2024", "25/12/2024"])
    assert order.dayfirst and not order.ambiguous


def test_date_order_monthfirst():
    order = _order(["03/04/2024", "12/25/2024"])
    assert not order.dayfirst and not order.ambiguous


def test_date_order_ambiguous():
    assert _order(["03/04/2024", "05/06/2024"]).ambiguous
    assert not _order(["2024-04-03"]).ambiguous


def test_cluster_categories_merges_spellings_to_most_common():
    counts = {"North": 50, "north": 4, "NORTH": 3, "Nrth": 2, "South": 40, "South ": 3}
    mapping, score = P.cluster_categories(counts)
    assert {mapping[v] for v in ("North", "north", "NORTH", "Nrth")} == {"North"}
    assert mapping["South "] == "South"
    assert 80 <= score <= 100


def test_cluster_categories_keeps_distinct_values_apart():
    mapping, _ = P.cluster_categories({"Type 1": 5, "Type 2": 5, "Male": 9, "Female": 9, "East": 7, "West": 7})
    assert len(set(mapping.values())) == 6


def test_short_values_need_reference_match_or_score_95():
    # "Cats" vs "Cat" scores 85.7 but neither is a known category: not merged
    mapping, _ = P.cluster_categories({"Cats": 20, "Cat": 9})
    assert mapping["Cat"] == "Cat" and mapping["Cats"] == "Cats"
    # a 4-letter typo of a reference value ("Sout" of "South") is still merged
    mapping, _ = P.cluster_categories({"South": 30, "Sout": 2})
    assert mapping["Sout"] == "South"
    # a 4-letter non-reference pair scoring 95+ is merged (identical after normalisation)
    mapping, _ = P.cluster_categories({"Blue": 10, "blue": 3})
    assert mapping["blue"] == "Blue"
    # values of 5+ characters are unaffected by the guard
    mapping, _ = P.cluster_categories({"Green": 20, "Gren": 1, "Greeen": 2})
    assert mapping["Greeen"] == "Green"


def test_format_pattern():
    assert P.format_pattern("03/04/2024") == "99/99/9999"
    assert P.format_pattern("AB-12") == "AA-99"


def test_tidy_text():
    assert P.tidy_text("  José  García​ ") == "José García"
