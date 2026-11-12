"""Value-level parsing shared by the profiler and (from M2) the rules.

Everything here is a pure function on strings. No dataframes, no I/O.
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz.distance import OSA

# --------------------------------------------------------------------------- nulls / whitespace

NULL_TOKENS: frozenset[str] = frozenset({"", "na", "n/a", "null", "-", "?", "#n/a", "tbd"})

# Zero-width and control characters (tab/newline excluded: they are whitespace, handled by trim).
HIDDEN_RE = re.compile(r"[​‌‍⁠﻿­\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RUN_RE = re.compile(r"\s+")


def strip_hidden(value: str) -> str:
    """Remove hidden characters and surrounding whitespace (including non-breaking spaces)."""
    return HIDDEN_RE.sub("", value).strip()


def is_null_token(value: str) -> bool:
    return strip_hidden(value).casefold() in NULL_TOKENS


def tidy_text(value: str) -> str:
    """Trim, collapse inner whitespace, drop hidden chars, NFC. (ftfy is applied by the rule.)"""
    return unicodedata.normalize("NFC", _WS_RUN_RE.sub(" ", strip_hidden(value)))


def has_hidden_chars(value: str) -> bool:
    return bool(HIDDEN_RE.search(value)) or " " in value


def has_whitespace_issue(value: str) -> bool:
    return value != value.strip() or bool(re.search(r"\s{2,}", value))


# --------------------------------------------------------------------------- headers

ID_NAME_TOKENS = frozenset(
    {"id", "zip", "zipcode", "postal", "postcode", "phone", "code", "account", "ssn", "sku"}
)


def _snake(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)       # camelCase -> camel_Case
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)    # HTTPCode -> HTTP_Code
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text


def normalize_header_names(headers: list[str]) -> list[str]:
    """snake_case, ASCII-fold, empty -> column_<n>, duplicates get _2, _3."""
    out: list[str] = []
    seen: set[str] = set()
    for i, header in enumerate(headers, start=1):
        base = _snake(header or "") or f"column_{i}"
        name, k = base, 1
        while name in seen:
            k += 1
            name = f"{base}_{k}"
        seen.add(name)
        out.append(name)
    return out


def unique_column_names(headers: list[str], reserved: set[str] | None = None) -> list[str]:
    """Headers as uploaded, changed only where needed to be usable as dataframe columns:
    an empty header becomes column_<n>, a repeated one gets _2, _3."""
    out: list[str] = []
    seen: set[str] = set(reserved or ())
    for i, header in enumerate(headers, start=1):
        base = header if header.strip() else f"column_{i}"
        name, k = base, 1
        while name in seen:
            k += 1
            name = f"{base}_{k}"
        seen.add(name)
        out.append(name)
    return out


def is_id_like_name(name: str) -> bool:
    return any(tok in ID_NAME_TOKENS for tok in _snake(name).split("_"))


# --------------------------------------------------------------------------- numbers

_NUM_RE = re.compile(
    r"^(?P<s1>[-+]?)\s*(?P<c1>[$£€]?)\s*(?P<s2>[-+]?)"
    r"(?P<int>\d{1,3}(?:,\d{3})+|\d+)?(?P<frac>\.\d+)?"
    r"\s*(?P<c2>[$£€]?)\s*(?P<pct>%?)$"
)
PLAIN_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


@dataclass(frozen=True)
class NumberParse:
    canonical: str          # plain decimal string, e.g. "-1234.50"
    value: float
    style: str              # formatting signature, "" when plain
    leading_zero: bool      # e.g. "00123" (not "0" or "0.5")
    is_integer: bool


def parse_number(value: str) -> NumberParse | None:
    s = strip_hidden(value)
    negative = False
    parens = False
    if len(s) > 2 and s[0] == "(" and s[-1] == ")":
        s, negative, parens = s[1:-1].strip(), True, True
    m = _NUM_RE.match(s)
    if not m or (m["int"] is None and m["frac"] is None):
        return None
    if (m["s1"] and m["s2"]) or (m["c1"] and m["c2"]):
        return None
    if (m["s1"] or m["s2"]) == "-":
        negative = True
    int_raw = m["int"] or "0"
    int_digits = int_raw.replace(",", "")
    int_part = int_digits.lstrip("0") or "0"          # "03" -> "3"
    frac = m["frac"] or ""
    canonical = ("-" if negative else "") + int_part + frac
    style = "".join(
        flag
        for flag, on in (
            (m["c1"] or m["c2"], bool(m["c1"] or m["c2"])),
            (",", "," in int_raw),
            ("%", bool(m["pct"])),
            ("()", parens),
            ("+", "+" in (m["s1"], m["s2"])),
            (".x", m["int"] is None),
        )
        if on
    )
    return NumberParse(
        canonical=canonical,
        value=float(canonical),
        style=style,
        leading_zero=len(int_digits) > 1 and int_digits[0] == "0",
        is_integer=not frac,
    )


def leading_zeros_mean_id(nums: dict[str, NumberParse]) -> bool:
    """Leading zeros make a column an id only when every number has the same width
    (zip 02134, padded 00017). A stray "03" among 1, 2, 3 is just a number."""
    if not any(p.leading_zero for p in nums.values()):
        return False
    return len({len(strip_hidden(v).strip()) for v in nums}) == 1


# --------------------------------------------------------------------------- booleans

_BOOL_FAMILIES: dict[str, tuple[bool, str]] = {
    "yes": (True, "yes/no"), "no": (False, "yes/no"),
    "y": (True, "y/n"), "n": (False, "y/n"),
    "true": (True, "true/false"), "false": (False, "true/false"),
    "t": (True, "t/f"), "f": (False, "t/f"),
    "1": (True, "1/0"), "0": (False, "1/0"),
    "on": (True, "on/off"), "off": (False, "on/off"),
}
TRUE_TOKENS = sorted(k for k, (v, _) in _BOOL_FAMILIES.items() if v)
FALSE_TOKENS = sorted(k for k, (v, _) in _BOOL_FAMILIES.items() if not v)


@dataclass(frozen=True)
class BoolParse:
    value: bool
    style: str      # e.g. "yes/no:title"
    numeric: bool   # written as 1 / 0


def parse_bool(value: str) -> BoolParse | None:
    s = strip_hidden(value)
    hit = _BOOL_FAMILIES.get(s.casefold())
    if hit is None:
        return None
    case = "lower" if s == s.lower() else "upper" if s == s.upper() else "title"
    return BoolParse(value=hit[0], style=f"{hit[1]}:{case}", numeric=hit[1] == "1/0")


# --------------------------------------------------------------------------- dates

_MONTHS = {
    name: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_TIME = (
    r"(?:[T ]\s*(?P<h>\d{1,2}):(?P<mi>\d{2})(?::(?P<sec>\d{2}))?(?:\.\d+)?"
    r"\s*(?P<ampm>[AaPp][Mm])?\s*(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
_ISO_RE = re.compile(r"^(?P<y>\d{4})(?P<sep>[-/.])(?P<m>\d{1,2})(?P=sep)(?P<d>\d{1,2})" + _TIME)
_NUMERIC_RE = re.compile(
    r"^(?P<a>\d{1,2})(?P<sep>[-/.])(?P<b>\d{1,2})(?P=sep)(?P<y>\d{4}|\d{2})" + _TIME
)
_DMY_TEXT_RE = re.compile(
    r"^(?P<d>\d{1,2})(?:st|nd|rd|th)?[\s\-/.]+(?P<mon>[A-Za-z]{3,9})\.?,?[\s\-/.]+(?P<y>\d{4}|\d{2})"
    + _TIME
)
_MDY_TEXT_RE = re.compile(
    r"^(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})" + _TIME
)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?$")


@dataclass(frozen=True)
class DateParse:
    kind: str                       # "iso" | "numeric" | "text"
    fmt: str                        # format signature, e.g. "numeric/" or "iso-+time"
    year: int
    a: int                          # iso/text: month. numeric: first number
    b: int                          # iso/text: day.   numeric: second number
    time: tuple[int, int, int] | None

    @property
    def has_time(self) -> bool:
        return self.time is not None

    def to_iso(self, dayfirst: bool = False) -> str | None:
        if self.kind == "numeric":
            day, month = (self.a, self.b) if dayfirst else (self.b, self.a)
        else:
            month, day = self.a, self.b
        try:
            date = _dt.date(self.year, month, day)
        except ValueError:
            return None
        if self.time is None:
            return date.isoformat()
        return f"{date.isoformat()}T{self.time[0]:02d}:{self.time[1]:02d}:{self.time[2]:02d}"


def _year(text: str) -> int:
    y = int(text)
    if len(text) == 2:
        y += 2000 if y < 70 else 1900
    return y


def _time(m: re.Match) -> tuple[int, int, int] | None | bool:
    """Returns a time tuple, None (no time), or False (invalid time)."""
    if m["h"] is None:
        return None
    h, mi, sec = int(m["h"]), int(m["mi"]), int(m["sec"] or 0)
    if m["ampm"]:
        if not 1 <= h <= 12:
            return False
        h = h % 12 + (12 if m["ampm"].lower() == "pm" else 0)
    if h > 23 or mi > 59 or sec > 59:
        return False
    return (h, mi, sec)


def parse_date(value: str) -> DateParse | None:
    """Recognise a date. Day/month order of numeric dates is decided per column (to_iso)."""
    s = strip_hidden(value)
    if len(s) < 6 or not s[0].isalnum():
        return None
    for kind, regex in (
        ("iso", _ISO_RE), ("numeric", _NUMERIC_RE), ("text", _DMY_TEXT_RE), ("text", _MDY_TEXT_RE),
    ):
        m = regex.match(s)
        if not m:
            continue
        time = _time(m)
        if time is False:
            return None
        suffix = "+time" if time else ""
        if kind == "iso":
            parsed = DateParse("iso", f"iso{m['sep']}{suffix}", int(m["y"]), int(m["m"]), int(m["d"]), time)
        elif kind == "numeric":
            parsed = DateParse(
                "numeric", f"numeric{m['sep']}{len(m['y'])}{suffix}", _year(m["y"]),
                int(m["a"]), int(m["b"]), time,
            )
            if parsed.to_iso(True) is None and parsed.to_iso(False) is None:
                return None
            return parsed
        else:
            month = _MONTHS.get(m["mon"].lower())
            if month is None:
                return None
            sig = "text_dmy" if regex is _DMY_TEXT_RE else "text_mdy"
            parsed = DateParse("text", sig + suffix, _year(m["y"]), month, int(m["d"]), time)
        return parsed if parsed.to_iso() is not None else None
    return None


@dataclass(frozen=True)
class DateOrder:
    dayfirst: bool
    ambiguous: bool   # no numeric date in the column settles day/month order


def decide_date_order(parsed: dict[str, tuple[DateParse, int]]) -> DateOrder:
    """parsed: raw value -> (DateParse, count). Looks only at numeric dates like 03/04/2024."""
    day_first = month_first = numeric = 0
    for p, count in parsed.values():
        if p.kind != "numeric":
            continue
        numeric += count
        if p.a > 12:
            day_first += count
        elif p.b > 12:
            month_first += count
    if numeric == 0:
        return DateOrder(dayfirst=False, ambiguous=False)
    if day_first == 0 and month_first == 0:
        return DateOrder(dayfirst=False, ambiguous=True)
    return DateOrder(dayfirst=day_first >= month_first, ambiguous=False)


# --------------------------------------------------------------------------- categories

CATEGORY_MAX_DISTINCT = 50
CATEGORY_MAX_RATIO = 0.2
_DIGITS_RE = re.compile(r"\d+")


def looks_categorical(distinct: int, non_null: int) -> bool:
    return 0 < distinct <= CATEGORY_MAX_DISTINCT and distinct / non_null <= CATEGORY_MAX_RATIO


def category_key(value: str) -> str:
    """Tier 1 key: NFKC, accents removed, casefolded, whitespace tidied."""
    text = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", tidy_text(value)))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


def _is_title_case(value: str) -> bool:
    """"West", "New York"; not "WEST", "USA" or "west"."""
    return value == value.title() and value != value.upper()


def _variant_groups(counts: dict[str, int]) -> dict[str, tuple[str, int, list[str]]]:
    """key -> (most frequent tidy spelling, total count, raw values in the group)."""
    groups: dict[str, dict[str, int]] = {}
    for value, count in counts.items():
        groups.setdefault(category_key(value), {})[value] = count
    out = {}
    for key, members in groups.items():
        tidy_counts: dict[str, int] = {}
        for value, count in members.items():
            tidy_counts[tidy_text(value)] = tidy_counts.get(tidy_text(value), 0) + count
        title = [v for v in tidy_counts if _is_title_case(v)]
        pool = title or list(tidy_counts)        # prefer an existing Title Case spelling
        canonical = min(pool, key=lambda v: (-tidy_counts[v], v))
        out[key] = (canonical, sum(members.values()), sorted(members))
    return out


def merge_case_variants(counts: dict[str, int]) -> dict[str, str]:
    """Tier 1 (automatic): values that differ only by case, accents or whitespace are mapped to
    the most frequent spelling. Returns only the values that change."""
    return {
        value: canonical
        for canonical, _, members in _variant_groups(counts).values()
        for value in members
        if value != canonical
    }


CATEGORY_TIER2_MAX_DISTINCT = 500
CATEGORY_TARGET_MIN_COUNT = 3
CATEGORY_TARGET_MIN_SHARE = 0.05
# Common abbreviations -> the full value they stand for (compared without spaces, dots, hyphens).
CATEGORY_ABBREVIATIONS = {
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest", "se": "southeast", "sw": "southwest",
}
_NON_ALNUM_RE = re.compile(r"[\W_]+")


def _letters(key: str) -> str:
    return _NON_ALNUM_RE.sub("", key)


def _in_order(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def _evidence(src: str, tgt: str, src_text: str, tgt_text: str) -> tuple[int, str] | None:
    """How strongly src looks like a short form or typo of tgt: (strength, reason) or None."""
    a, b = _letters(src), _letters(tgt)
    if not a or not b or a[0] != b[0] or _DIGITS_RE.findall(src) != _DIGITS_RE.findall(tgt):
        return None
    if CATEGORY_ABBREVIATIONS.get(a) == b:
        return 3, f'"{src_text}" is a common abbreviation of "{tgt_text}"'
    if OSA.distance(src, tgt) == 1:
        return 2, f'"{src_text}" is one letter away from "{tgt_text}" (missing, extra, changed or swapped)'
    if len(a) < len(b) and len(a) / len(b) >= 0.5 and _in_order(a, b):
        return 1, f'the letters of "{src_text}" appear in order in "{tgt_text}"'
    return None


def _tier2(counts: dict[str, int]) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """(merges: raw value -> (target, reason), left alone: spelling -> reason)."""
    groups = _variant_groups(counts)
    if len(groups) > CATEGORY_TIER2_MAX_DISTINCT:
        return {}, {}
    total = sum(n for _, n, _ in groups.values())
    order = sorted(groups, key=lambda k: (-groups[k][1], k))
    targets: list[str] = []
    out: dict[str, tuple[str, str]] = {}
    left: dict[str, str] = {}
    for key in order:
        canonical, n, members = groups[key]
        found = [
            (ev, t) for t in targets
            if groups[t][1] > n and (ev := _evidence(key, t, canonical, groups[t][0]))
        ]
        winners = []
        if found:
            best = max(ev[0] for ev, _ in found)
            winners = [(ev, t) for ev, t in found if ev[0] == best]
            if len(winners) == 1:
                (_, reason), t = winners[0]
                for value in members:
                    out[value] = (groups[t][0], reason)
                continue
        if n >= CATEGORY_TARGET_MIN_COUNT and n / total >= CATEGORY_TARGET_MIN_SHARE:
            targets.append(key)
        elif winners:
            a, b = sorted(groups[t][0] for _, t in winners)[:2]
            left[canonical] = f'"{canonical}" is equally close to "{a}" and "{b}", so it was not merged'
        else:
            left[canonical] = f'"{canonical}" does not look like a short form or typo of a common value'
    return out, left


def suggest_category_merges(counts: dict[str, int]) -> dict[str, tuple[str, str]]:
    """Tier 2 (suggestions): abbreviations and typos of an established value.

    A value is mapped to a target only when the target has at least 3 rows and 5% of the
    column, more rows than the value, the same first letter, and the evidence (abbreviation map,
    one-letter difference, or letters in order covering half the target) is strictly stronger
    than for any other target. Works on Tier 1 groups, so every spelling of the value moves.
    Returns raw value -> (target spelling, reason).
    """
    return _tier2(counts)[0]


def category_left_alone(counts: dict[str, int]) -> dict[str, str]:
    """Rare values Tier 2 saw but did not merge (not established, no single clear match) -> reason."""
    return _tier2(counts)[1]


def cluster_categories(counts: dict[str, int]) -> dict[str, str]:
    """Both tiers together: raw value -> the value it would end up as (itself if unchanged).
    Used by the profiler to score consistency."""
    mapping = {v: v for v in counts}
    mapping.update(merge_case_variants(counts))
    mapping.update({v: t for v, (t, _) in suggest_category_merges(counts).items()})
    return mapping


# --------------------------------------------------------------------------- patterns

def format_pattern(value: str) -> str:
    """Digits become 9, letters become A, everything else is kept."""
    return "".join("9" if ch.isdigit() else "A" if ch.isalpha() else ch for ch in value)


def collapsed_pattern(value: str) -> str:
    """format_pattern with runs collapsed, so 'AB-123' and 'XYZ-9' share 'A-9'."""
    return re.sub(r"(9+|A+)", lambda m: m[0][0], format_pattern(strip_hidden(value)))
