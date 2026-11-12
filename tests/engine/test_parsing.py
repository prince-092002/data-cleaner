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


# ---- Tier 1: case, accents, whitespace (automatic)

def test_tier1_merges_case_accent_and_space_variants_into_most_frequent_spelling():
    counts = {"North": 50, "north": 4, "NORTH": 3, "South": 40, "South ": 3, "Café": 6, "cafe": 2, "CAFÉ": 1}
    assert P.merge_case_variants(counts) == {
        "north": "North", "NORTH": "North", "South ": "South", "cafe": "Café", "CAFÉ": "Café",
    }


def test_tier1_prefers_an_existing_title_case_spelling():
    assert P.merge_case_variants({"west": 17, "WEST": 7, "West": 5}) == {"west": "West", "WEST": "West"}
    assert P.merge_case_variants({"New York": 2, "new york": 9}) == {"new york": "New York"}


def test_tier1_keeps_the_most_frequent_spelling_when_no_title_case_exists():
    assert P.merge_case_variants({"USA": 50, "usa": 5}) == {"usa": "USA"}
    assert P.merge_case_variants({"west": 9, "WEST": 3}) == {"WEST": "west"}


def test_tier1_leaves_typos_and_distinct_values_alone():
    assert P.merge_case_variants({"North": 9, "Nrth": 2, "Type 1": 3, "Type 2": 3}) == {}


# ---- Tier 2: abbreviations and typos (suggestions)

def _targets(counts):
    return {v: t for v, (t, _) in P.suggest_category_merges(counts).items()}


def test_tier2_maps_abbreviations_and_typos_to_established_values():
    counts = {"North": 20, "South": 20, "East": 20, "West": 20,
              "Wst": 3, "Sth": 3, "Eest": 3, "Nrth": 2, "N.": 2, "Wset": 1}
    assert _targets(counts) == {
        "Wst": "West", "Sth": "South", "Eest": "East", "Nrth": "North", "N.": "North", "Wset": "West",
    }


def test_tier2_gives_a_reason_for_each_merge():
    merges = P.suggest_category_merges({"North": 20, "N.": 2, "Nrth": 2, "Sth": 2, "South": 20})
    assert "abbreviation" in merges["N."][1]
    assert "one letter" in merges["Nrth"][1]
    assert "in order" in merges["Sth"][1]


def test_tier2_never_merges_a_value_equally_close_to_two_targets():
    assert _targets({"NE": 20, "NW": 20, "N": 2}) == {}


def test_tier2_needs_same_first_letter():
    assert _targets({"West": 20, "Est": 2}) == {}


def test_tier2_target_must_have_3_rows_and_5_percent():
    assert _targets({"North": 2, "Nrth": 1}) == {}                    # target under 3 rows
    assert _targets({"Other": 200, "North": 3, "Nrth": 1}) == {}      # target under 5%


def test_tier2_keeps_values_whose_digits_differ():
    assert _targets({"Type 1": 20, "Type 2": 2}) == {}


def test_tier2_skips_columns_with_more_than_500_distinct_values():
    counts = {f"v{i:04d}x": 1 for i in range(501)} | {"North": 600, "Nrth": 2}
    assert _targets(counts) == {}


def test_tier2_reports_values_it_left_alone_and_why():
    left = P.category_left_alone({"NE": 20, "NW": 20, "N": 2, "North": 20, "Zed": 1})
    assert set(left) == {"Zed"}                                   # "N" is an abbreviation of North
    left = P.category_left_alone({"NE": 20, "NW": 20, "N": 2, "Zed": 1})
    assert '"NE"' in left["N"] and '"NW"' in left["N"]
    assert "not" in left["Zed"]
    assert "NE" not in left                                         # established values are not listed


def test_cluster_categories_combines_both_tiers():
    mapping = P.cluster_categories({"North": 20, "north": 3, "Nrth": 2, "South": 20})
    assert mapping == {"North": "North", "north": "North", "Nrth": "North", "South": "South"}


def test_format_pattern():
    assert P.format_pattern("03/04/2024") == "99/99/9999"
    assert P.format_pattern("AB-12") == "AA-99"


def test_tidy_text():
    assert P.tidy_text("  José  García​ ") == "José García"


# ---- name casing (M6 step 5, suggestions only)

@pytest.mark.parametrize("raw, expected", [
    ("JOHN SMITH", "John Smith"),
    ("bob smith", "Bob Smith"),
    ("JOHN O'BRIEN", "John O'Brien"),
    ("mary mcdonald", "Mary McDonald"),
    ("ANGUS MACDONALD", "Angus MacDonald"),
    ("ANA MACHADO", "Ana Machado"),             # "Mac" only before a likely second capital
    ("LUDWIG VAN BEETHOVEN", "Ludwig van Beethoven"),
    ("ROBERTO DE NIRO", "Roberto de Niro"),
    ("HENRY FORD II", "Henry Ford II"),
    ("JAMES SMITH III", "James Smith III"),
    ("ANNE-MARIE DUPONT", "Anne-Marie Dupont"),
])
def test_proper_name(raw, expected):
    assert P.proper_name(raw) == expected


def test_name_case_changes_only_all_caps_or_all_lowercase_values():
    counts = {"JOHN SMITH": 2, "bob smith": 1, "Mary McDonald": 3, "deShawn Lee": 1, "O'Brien": 1}
    assert P.name_case_mapping(counts) == {"JOHN SMITH": "John Smith", "bob smith": "Bob Smith"}


def test_name_case_skips_columns_full_of_business_names():
    counts = {"ACME LLC": 1, "GLOBEX INC": 1, "JOHN SMITH": 3}           # 2 of 5 rows = 40%
    assert P.name_case_mapping(counts) == {}


def test_name_like_columns():
    assert all(P.is_name_column(n) for n in ["customer_name", "Full Name", "surname", "first_name"])
    assert not any(P.is_name_column(n) for n in ["filename", "file_name", "username", "city", "product_name",
                                               "dba_name", "aka_name", "vendor_name", "facility_name"])
