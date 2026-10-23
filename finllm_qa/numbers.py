"""Find the numbers in financial prose and read them with their unit, scale and precision."""
from __future__ import annotations

import re
from dataclasses import dataclass

SCALES = {
    "trillion": 1e12, "tn": 1e12, "t": 1e12,
    "billion": 1e9, "bn": 1e9, "b": 1e9,
    "million": 1e6, "mn": 1e6, "mln": 1e6, "m": 1e6,
    "thousand": 1e3, "k": 1e3,
}

_NUM = r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_SCALE = r"(?:\s?(?P<scale>trillion|billion|million|thousand|tn|bn|mn|mln|[mbkt])(?![\w-]))"
_NEG = r"(?P<neg>[-−])?"

# Ordered: earlier patterns claim their span first.
PATTERNS = [
    # $416.2 billion, US$3.1bn, USD 72.35, $7.46 per share
    ("usd", re.compile(_NEG + r"(?:US\$|USD\s?|\$)\s?" + _NUM + _SCALE + "?", re.IGNORECASE)),
    # 416.2 billion dollars / 416.2bn
    ("usd", re.compile(_NUM + r"\s?(?P<scale>trillion|billion|million|bn|mn)(?:\s+(?:US\s)?dollars)?(?![\w-])",
                       re.IGNORECASE)),
    # 7.46 per share
    ("usd", re.compile(_NUM + r"(?P<scale>)\s?(?:per|a) share", re.IGNORECASE)),
    # 25 basis points / 25bp
    ("bp", re.compile(_NEG + _NUM + r"(?P<scale>)\s?(?:bps?|basis[- ]points?)(?![\w-])", re.IGNORECASE)),
    # 0.2 percentage points / 0.2pp
    ("pp", re.compile(_NEG + _NUM + r"(?P<scale>)\s?(?:percentage[- ]points?|pp|ppts?)(?![\w-])", re.IGNORECASE)),
    # 3.1% / 3.1 percent
    ("pct", re.compile(_NEG + _NUM + r"(?P<scale>)\s?(?:%|percent(?![\w-])|per cent(?![\w-]))", re.IGNORECASE)),
    # 151,000 jobs / 151k jobs / 151 thousand
    ("count", re.compile(_NEG + _NUM + r"\s?(?P<scale>thousand|k)?\s+(?:new\s+|net\s+)?"
                         r"(?:jobs|positions|payrolls|workers|roles)(?![\w-])", re.IGNORECASE)),
    ("count", re.compile(_NEG + _NUM + r"\s?(?P<scale>thousand|k)(?![\w-])", re.IGNORECASE)),
    ("count", re.compile(_NEG + r"(?P<num>\d{1,3}(?:,\d{3})+)(?P<scale>)(?![\d.%])")),
    # a bare decimal such as a yield written without "%": 4.25
    ("bare", re.compile(r"(?<![\w.$])" + _NEG + r"(?P<num>\d+\.\d+)(?P<scale>)(?![\w%.\d])")),
]

HEDGES = re.compile(
    r"(?:about|around|roughly|approximately|approx\.|nearly|almost|close to|some|just over|just under|"
    r"more than|over|less than|under|above|below|~)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Mention:
    start: int
    end: int
    text: str
    kind: str  # usd | pct | pp | count | bare (bp is read as pp)
    value: float  # absolute value in base units: USD, percent, percentage points, jobs
    tol: float  # half a unit of the last digit written, in base units
    negative: bool
    hedged: bool

    @property
    def stated(self) -> str:
        return self.text.strip()


def _parse(kind: str, m: re.Match, text: str) -> Mention:
    raw = m.group("num")
    num = float(raw.replace(",", ""))
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    scale_word = (m.groupdict().get("scale") or "").lower()
    scale = SCALES.get(scale_word, 1.0)
    if kind == "bp":
        kind, scale = "pp", 0.01
    value = num * scale
    tol = 0.5 * 10 ** (-decimals) * scale
    if kind == "count" and not scale_word and "," not in raw:
        tol = max(tol, 0.5)
    neg = bool(m.groupdict().get("neg"))
    hedged = bool(HEDGES.search(text[max(0, m.start() - 20): m.start()]))
    return Mention(m.start(), m.end(), m.group(0), kind, value, tol, neg, hedged)


def find_numbers(text: str) -> list[Mention]:
    """Every number with a recognisable unit, left to right, without overlaps."""
    taken: list[tuple[int, int]] = []
    found: list[Mention] = []
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            if kind in ("count", "bare") and not m.groupdict().get("scale")                     and re.fullmatch(r"(?:19|20)\d{2}", m.group("num")):
                continue  # "2025 jobs report": a year, not a count
            taken.append((m.start(), m.end()))
            found.append(_parse(kind, m, text))
    return sorted(found, key=lambda x: x.start)


def matches(mention: Mention, value: float, slack: float = 0.0) -> bool:
    """Does the written number agree with `value` once rounding is allowed for?

    Signs are compared separately (direction checks), so magnitudes are compared here.
    Hedged numbers ("about $390 billion") get 3% relative slack.
    """
    target = abs(value)
    allowed = mention.tol * 1.001 + 1e-9 + slack * target
    if mention.hedged:
        allowed = max(allowed, 0.03 * target)
    return abs(mention.value - target) <= allowed


# Period expressions
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]
_MONTH_RE = re.compile(r"(?<![\w-])(" + "|".join(MONTHS) + r"|sept?|jan|feb|mar|apr|jun|jul|aug|oct|nov|dec)\.?"
                       r"(?:\s+(?P<year>(?:19|20)\d{2}))?(?![\w-])", re.IGNORECASE)
_YEAR_RE = re.compile(r"(?<![\w$.,-])(?:FY\s?|fiscal(?: year)?\s)?(?P<year>(?:19|20)\d{2})(?![\w%,.]\d|\d|%)",
                      re.IGNORECASE)
_FY_SHORT_RE = re.compile(r"(?<![\w-])FY\s?'?(?P<yy>\d{2})(?!\d)", re.IGNORECASE)
_QUARTER_RE = re.compile(r"(?<![\w-])(?:Q(?P<q>[1-4])|(?P<word>first|second|third|fourth) quarter)"
                         r"(?:\s+(?:of\s+)?(?P<year>(?:19|20)\d{2}))?", re.IGNORECASE)
_Q_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_MONTH_ABBR = {m[:3]: i + 1 for i, m in enumerate(MONTHS)}


@dataclass(frozen=True)
class PeriodHit:
    start: int
    end: int
    text: str
    year: int | None = None
    month: int | None = None
    quarter: int | None = None


def find_periods(text: str) -> list[PeriodHit]:
    hits: list[PeriodHit] = []
    taken: list[tuple[int, int]] = []

    def add(h: PeriodHit) -> None:
        if not any(h.start < e and s < h.end for s, e in taken):
            taken.append((h.start, h.end))
            hits.append(h)

    for m in _QUARTER_RE.finditer(text):
        q = int(m.group("q")) if m.group("q") else _Q_WORDS[m.group("word").lower()]
        add(PeriodHit(m.start(), m.end(), m.group(0), int(m.group("year")) if m.group("year") else None, None, q))
    for m in _MONTH_RE.finditer(text):
        word = m.group(1).lower()
        if word == "may" and not m.group("year"):
            continue  # "may" is usually the verb
        if word in ("mar", "jan", "jun", "jul", "aug", "oct", "nov", "dec", "feb", "apr", "sep", "sept") \
                and not m.group(0).endswith(".") and not m.group("year"):
            continue  # bare abbreviations are too ambiguous without a year
        month = _MONTH_ABBR[word[:3]]
        add(PeriodHit(m.start(), m.end(), m.group(0), int(m.group("year")) if m.group("year") else None, month))
    for m in _FY_SHORT_RE.finditer(text):
        add(PeriodHit(m.start(), m.end(), m.group(0), 2000 + int(m.group("yy"))))
    for m in _YEAR_RE.finditer(text):
        add(PeriodHit(m.start(), m.end(), m.group(0), int(m.group("year"))))
    return sorted(hits, key=lambda h: h.start)
