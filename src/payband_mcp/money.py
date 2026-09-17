"""Reading a published pay range out of posting text, in any currency.

The first version of this understood exactly one shape: a leading dollar sign.
That is not a small gap. Monzo publishes a range on all 66 of its postings and
we reported pay on none of them, because the ranges read "£85,000 - £110,000".
NVIDIA writes "184,000 USD - 287,500 USD" with the code trailing and no symbol
at all, so every NVIDIA posting was silent too. A tool for comparing what the
same job pays in different countries cannot only read the United States.

Three things make this harder than finding two numbers:

* **The figure may not be salary.** Monzo postings also say "€1,200 a year for
  books, training courses and conferences". Requiring a range kills most of
  those; a per-currency floor and a keyword veto kill the rest.
* **The interval may not be a year.** Hourly contract rates appear in the same
  boards, and averaging $60/hr into a band of annual salaries produces a number
  that is wrong rather than merely imprecise.
* **Digit grouping is regional.** "65.000" is sixty-five thousand euros, and
  "₹25,00,000" is two and a half million rupees under Indian grouping.
"""

from __future__ import annotations

import html as _html
import re
from typing import Any

_TAG = re.compile(r"<[^>]+>")

# Symbols that are unambiguous, and symbols that are not. A bare "$" is USD
# unless a currency code nearby says otherwise -- Canadian, Australian and
# Singaporean postings usually do say so.
_SYMBOL = {
    "£": "GBP", "€": "EUR", "₹": "INR", "¥": "JPY", "₩": "KRW", "₪": "ILS",
    "C$": "CAD", "CA$": "CAD", "A$": "AUD", "AU$": "AUD", "S$": "SGD",
    "R$": "BRL", "US$": "USD", "$": "USD",
}
_CODES = (
    "USD GBP EUR INR JPY CAD AUD SGD CHF SEK NOK DKK PLN BRL MXN ILS AED "
    "HKD NZD ZAR KRW CNY PHP MYR THB IDR VND TRY CZK HUF RON"
).split()

# Below these a yearly figure is a stipend, a budget or a bonus, not a salary.
# Set low enough to admit a genuine junior salary in each market.
_ANNUAL_FLOOR = {
    "USD": 15_000, "GBP": 12_000, "EUR": 12_000, "CAD": 20_000, "AUD": 25_000,
    "SGD": 20_000, "CHF": 20_000, "NZD": 25_000, "ILS": 50_000, "AED": 40_000,
    "INR": 100_000, "JPY": 1_000_000, "KRW": 10_000_000, "HUF": 1_000_000,
    "PHP": 150_000, "THB": 150_000, "IDR": 30_000_000, "VND": 50_000_000,
    "MXN": 100_000, "BRL": 30_000, "ZAR": 100_000, "CNY": 50_000,
    "HKD": 100_000, "TRY": 100_000, "SEK": 150_000, "NOK": 150_000,
    "DKK": 100_000, "PLN": 40_000, "CZK": 200_000, "RON": 30_000,
}
_DEFAULT_FLOOR = 10_000

# A range this wide is not one job's band; it is a page listing several.
_MAX_RATIO = 6.0

_INTERVAL_PATTERNS = (
    ("hour", re.compile(r"\b(per|an|/|each)\s*hour|\bhourly\b|\b/\s*hr\b|\bp/?h\b", re.I)),
    ("month", re.compile(r"\b(per|a|/|each)\s*month|\bmonthly\b|\bp\.?m\.?\b|\b/\s*mo\b", re.I)),
    ("week", re.compile(r"\b(per|a|/|each)\s*week|\bweekly\b", re.I)),
    ("day", re.compile(r"\b(per|a|/|each)\s*day|\bdaily\b|\bday\s*rate\b", re.I)),
    # Year is also the fallback, so this pattern changes no interval value --
    # it exists so a posting that says "per year" is distinguishable from one
    # that says nothing, which is what interval_stated reports. Listed last so
    # every shorter period keeps priority and existing readings are untouched.
    # Bare "annual" is deliberately not enough: it attaches to bonuses and
    # allowances as readily as to the band.
    ("year", re.compile(
        r"\b(per|a|/|each)\s*(year|annum)\b|\byearly\b|\bannually\b"
        r"|\bp\.?a\.?\b|\b/\s*yr\b"
        r"|\bannual(?:ized|ised)?\s+(?:salary|base|compensation|pay|rate|range)\b",
        re.I,
    )),
)

_PLAUSIBLE = {
    "hour": (5, 2_000),
    "day": (50, 20_000),
    "week": (200, 100_000),
    "month": (500, 5_000_000),
}

# Words that mark a figure as something other than base pay. Checked in a
# narrow, asymmetric window: the qualifier almost always sits just before the
# number ("Learning budget of £1,000", "we raised $50M - $80M") or immediately
# after it ("£1,000 learning budget"). Scanning wider rejects real salaries,
# because a Monzo posting mentions its learning budget a paragraph below the
# range -- that one word was costing us 25 correctly-published bands.
_NOT_SALARY = re.compile(
    r"\b(book|books|learning|training|conference|stipend|budget|allowance|"
    r"reimburse\w*|referral|bonus\s+pool|equity\s+grant|401\s*\(?k\)?|"
    r"tuition|wellness|home\s*office|donation|match\w*\s+up\s+to|revenue|"
    r"funding|raised|valuation|arr\b|in\s+savings|discount)\b",
    re.I,
)
# Words that mark it as pay. A match near one of these wins ties.
_IS_SALARY = re.compile(
    r"\b(salary|salaries|base\s+pay|base\s+compensation|pay\s+range|"
    r"compensation\s+range|salary\s+range|annual\s+pay|target\s+earnings|"
    r"remuneration|total\s+cash|pay\s+band|zone\s*\d|on-?target|ote)\b",
    re.I,
)

# ...but on-target earnings are base plus commission, so a sales role's
# "£67,000 Total OTE" is not comparable with an engineer's base band. Monzo
# publishes both, and averaging them together overstates base pay.
_ON_TARGET = re.compile(
    r"\b(ote|on-?target\s+earnings|total\s+target\s+(?:cash|compensation)|"
    r"base\s*\+\s*commission|plus\s+commission|including\s+commission|"
    r"inclusive\s+of\s+commission)\b",
    re.I,
)

# NVIDIA and others put more than one band in a posting, tagged by level:
# "184,000 USD - 287,500 USD for Level 4, and 224,000 USD - 356,500 USD for
# Level 5". Reporting the union of those (184,000-356,500) would recreate
# exactly the mashed-together range that reporting per level was meant to fix.
_LEVEL_TAG = re.compile(
    r"\bfor\s+(level\s*\d+|l\d+|ic\d+|p\d+|e\d+|grade\s*\w+|"
    r"(?:senior|staff|principal|lead|junior|mid)[\w\s]{0,18}?)\b",
    re.I,
)

# The same idea, written the other way round. Atlassian publishes three
# geographic tiers per US role as "Zone A: $122,400 - $159,800", and its
# non-US roles as "Canada: CA$94,500 - CA$123,375". The label leads, so
# _LEVEL_TAG -- which reads forwards from the figure -- never sees it, and
# three zones collapse into one 1.6x range that belongs to no single hire.
_PREFIX_TAG = re.compile(
    r"(?:^|[>\s])((?:zone|tier|band|level|region)\s+[A-Z0-9]+|"
    r"[A-Z][A-Za-z.]*(?:\s+[A-Z][A-Za-z.]*){0,2})\s*:\s*$",
    re.I,
)

# Postings are typed by humans: "£150, 000 - £200, 000" appears verbatim on
# Monzo. Close the gap before matching rather than letting a space end a number.
_STRAY_SPACE = re.compile(r"(\d,)\s+(\d{3})\b")

# A qualifier belongs to the clause it sits in. "Base salary $120,000 -
# $150,000; OTE $200,000 - $250,000" publishes both, and a window that runs
# past the semicolon labels the base figure as on-target earnings.
_CLAUSE = re.compile(r"[.;|\n•·]|\s{3,}")


def _clause_around(text: str, start: int, end: int, back: int, fwd: int) -> str:
    left = text[max(0, start - back) : start]
    right = text[end : end + fwd]
    breaks = list(_CLAUSE.finditer(left))
    if breaks:
        left = left[breaks[-1].end():]
    stop = _CLAUSE.search(right)
    if stop:
        right = right[: stop.start()]
    return left + text[start:end] + right


_NUM = r"\d[\d.,]*"
_SYM_RE = "|".join(re.escape(s) for s in sorted(_SYMBOL, key=len, reverse=True))
_CODE_RE = "|".join(_CODES)


def _token(tag: str) -> str:
    return (
        rf"(?:(?P<sym{tag}>{_SYM_RE})\s*)?"
        rf"(?:(?P<pre{tag}>{_CODE_RE})\s*)?"
        rf"(?P<num{tag}>{_NUM})\s*"
        rf"(?P<k{tag}>k\b)?\s*"
        rf"(?:(?P<post{tag}>{_CODE_RE})\b)?"
    )


_RANGE = re.compile(
    _token("a") + r"\s*(?:-{1,2}|–|—|\bto\b|\bup\s+to\b)\s*" + _token("b"),
    re.I,
)

_EURO_THOUSANDS = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_COMMA_DECIMAL = re.compile(r"^\d+,\d{1,2}$")


def _to_float(raw: str) -> float | None:
    """Parse a grouped number without assuming which separator means what."""
    text = raw.strip().rstrip(".,")
    if not text:
        return None
    if _EURO_THOUSANDS.match(text):          # 65.000 -> 65000
        text = text.replace(".", "")
    elif _COMMA_DECIMAL.match(text):         # 65,50 -> 65.50
        text = text.replace(",", ".")
    else:                                    # 1,25,000 and 125,000 alike
        text = text.replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _currency(match: re.Match[str], window: str) -> str:
    """Prefer an explicit code over a symbol, since "$" is four currencies."""
    for group in ("posta", "postb", "prea", "preb"):
        if match.group(group):
            return match.group(group).upper()
    for group in ("syma", "symb"):
        sym = match.group(group)
        if sym and _SYMBOL[sym] != "USD":
            return _SYMBOL[sym]
    # A bare "$" with a code somewhere close by is that code.
    nearby = re.search(rf"\b({_CODE_RE})\b", window)
    if nearby and match.group("syma") in ("$", None):
        return nearby.group(1).upper()
    if match.group("syma") or match.group("symb"):
        return "USD"
    return ""


def _interval(window: str) -> tuple[str, bool]:
    """The period a figure covers, and whether the posting actually said so.

    Year is the only sane default for a salary band in prose, and `_plausible`
    keeps it from swallowing an hourly rate. But a default is not a statement,
    and a caller cannot tell them apart from the value alone -- so the second
    element says which one it is. Sources that publish a period explicitly
    (Keka sends one, and sends 0 for "not available") never reach the default.
    """
    for name, pattern in _INTERVAL_PATTERNS:
        if pattern.search(window):
            return name, True
    return "year", False


def _plausible(low: float, high: float, currency: str, interval: str) -> bool:
    if low <= 0 or high <= 0 or high < low:
        return False
    if high / low > _MAX_RATIO:
        return False
    if interval == "year":
        return low >= _ANNUAL_FLOOR.get(currency, _DEFAULT_FLOOR)
    floor, ceiling = _PLAUSIBLE[interval]
    return floor <= low <= ceiling


def _candidates(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for match in _RANGE.finditer(text):
        low, high = _to_float(match.group("numa")), _to_float(match.group("numb"))
        if low is None or high is None:
            continue
        window = text[max(0, match.start() - 180) : match.end() + 180]
        veto = text[max(0, match.start() - 60) : match.end() + 25]
        # Tighter still, and clause-bounded: "OTE" qualifies the figure it is
        # touching, not the one in the next clause along.
        basis_window = _clause_around(text, match.start(), match.end(), 30, 30)
        currency = _currency(match, window)
        if not currency:
            continue  # two bare numbers are a date range or a req id
        interval, stated = _interval(text[max(0, match.start() - 60) : match.end() + 60])
        if match.group("ka"):
            low *= 1000
        if match.group("kb"):
            high *= 1000
        # "$152 - $200" in an annual context is thousands written lazily.
        if interval == "year" and high < 1000 and not match.group("kb"):
            low, high = low * 1000, high * 1000
        if low > high:
            low, high = high, low
        if not _plausible(low, high, currency, interval):
            continue
        if _NOT_SALARY.search(veto) and not _IS_SALARY.search(veto):
            continue
        tag = _LEVEL_TAG.search(text[match.end() : match.end() + 60])
        if not tag:
            tag = _PREFIX_TAG.search(text[max(0, match.start() - 40) : match.start()])
        out.append({
            "min": low,
            "max": high,
            "currency": currency,
            "interval": interval,
            "interval_stated": stated,
            "salary_context": bool(_IS_SALARY.search(window)),
            "basis": "ote" if _ON_TARGET.search(basis_window) else "base",
            "label": " ".join(tag.group(1).split()).title() if tag else None,
            "at": match.start(),
        })
    return out


_SINGLE = re.compile(_token("s"), re.I)


def _points(text: str) -> list[dict[str, Any]]:
    """Postings that name one figure rather than a range.

    "£50,000 base salary" is a published number, and refusing to read it
    because it is not a range loses real data. The guard is that the figure
    must sit right next to a word like "salary" -- close enough that a
    learning budget or an equity grant a sentence away cannot be mistaken
    for one. Reported as a band of zero width, which `precision` already
    labels `point`.
    """
    out: list[dict[str, Any]] = []
    for match in _SINGLE.finditer(text):
        value = _to_float(match.group("nums"))
        if value is None:
            continue
        near = text[max(0, match.start() - 40) : match.end() + 40]
        basis_window = _clause_around(text, match.start(), match.end(), 30, 30)
        if not _IS_SALARY.search(near) or _NOT_SALARY.search(near):
            continue
        currency = _currency_single(match, near)
        if not currency:
            continue
        interval, stated = _interval(near)
        if match.group("ks"):
            value *= 1000
        if not _plausible(value, value, currency, interval):
            continue
        out.append({
            "min": value, "max": value, "currency": currency,
            "interval": interval, "interval_stated": stated,
            "salary_context": True,
            "basis": "ote" if _ON_TARGET.search(basis_window) else "base",
            "label": None, "at": match.start(),
        })
    return out


def _currency_single(match: re.Match[str], window: str) -> str:
    for group in ("posts", "pres"):
        if match.group(group):
            return match.group(group).upper()
    sym = match.group("syms")
    if sym and _SYMBOL[sym] != "USD":
        return _SYMBOL[sym]
    if sym:
        nearby = re.search(rf"\b({_CODE_RE})\b", window)
        return nearby.group(1).upper() if nearby else "USD"
    return ""


def normalise(content: str | None) -> str:
    """Boards escape their HTML, sometimes twice; unescape before stripping."""
    raw = _html.unescape(content or "")
    return _STRAY_SPACE.sub(r"\1\2", _html.unescape(_TAG.sub(" ", raw)))


def parse(content: str | None, prefer: str | None = None) -> dict[str, Any] | None:
    """Best published pay range in a posting, or None if it publishes none.

    `prefer` is a region of the posting the board has already identified as
    the pay field (Greenhouse renders one); a match there beats prose.
    """
    if prefer:
        for cand in _candidates(normalise(prefer)):
            return _finish(cand, [], "posting_pay_field")

    text = normalise(content)
    candidates = _candidates(text) or _points(text)
    if not candidates:
        return None

    # A figure the posting calls a salary beats one it does not, and an
    # earlier match beats a later one, since boilerplate trails the body.
    best = min(
        candidates,
        key=lambda c: (c["basis"] != "base", not c["salary_context"], c["at"]),
    )
    siblings = [
        c for c in candidates
        if c is not best
        and c["label"]
        and c["currency"] == best["currency"]
        and c["interval"] == best["interval"]
    ]
    return _finish(best, siblings, "posting_text")


def _finish(cand: dict[str, Any], siblings: list[dict[str, Any]], source: str) -> dict[str, Any]:
    pay = {
        "min": cand["min"],
        "max": cand["max"],
        "currency": cand["currency"],
        "interval": cand["interval"],
        # False means we defaulted, not that the posting said "year".
        "interval_stated": cand.get("interval_stated", False),
        "basis": cand.get("basis", "base"),
        "source": source,
    }
    if cand["label"] or siblings:
        bands = [cand, *siblings]
        pay["bands"] = [
            {"label": b["label"], "min": b["min"], "max": b["max"]} for b in bands
        ]
    return pay
