"""The metrics a brief can contain, and the words commentary uses to refer to them."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    kind: str  # "usd" | "pct" | "pp" | "count": how its levels are written
    basis: str = "change"  # what a plain "rose"/"fell" describes: the change vs prior, or the level's sign
    flat_tol: float = 0.0  # changes smaller than this read as "unchanged"


METRICS = {
    m.key: m
    for m in [
        Metric("revenue", "revenue", "usd", flat_tol=0.0025),
        Metric("net_income", "net income", "usd", flat_tol=0.0025),
        Metric("eps", "diluted EPS", "usd", flat_tol=0.0025),
        Metric("net_margin", "net margin", "pct", flat_tol=0.05),
        Metric("inflation", "CPI inflation, y/y", "pct", flat_tol=0.05),
        Metric("core_inflation", "core CPI inflation, y/y", "pct", flat_tol=0.05),
        Metric("unemployment", "unemployment rate", "pct", flat_tol=0.05),
        Metric("payrolls", "nonfarm payroll change", "count", basis="level", flat_tol=1000),
        Metric("fed_funds", "effective fed funds rate", "pct", flat_tol=0.005),
        Metric("yield_2y", "2-year Treasury yield", "pct", flat_tol=0.005),
        Metric("yield_10y", "10-year Treasury yield", "pct", flat_tol=0.005),
        Metric("curve", "10-year minus 2-year spread", "pp", flat_tol=0.005),
        Metric("oil", "WTI crude price", "usd", flat_tol=0.0025),
        Metric("gdp", "real GDP growth, annualized", "pct", basis="level", flat_tol=0.05),
    ]
}


@dataclass(frozen=True)
class Alias:
    phrase: str
    metric: str
    strong: bool = True  # weak aliases are too generic to prove a metric swap
    basis: str | None = None  # overrides Metric.basis ("consumer prices rose" = level)


_ALIASES = [
    # company fundamentals
    *(Alias(p, "revenue") for p in ["revenue", "revenues", "sales", "top line", "top-line", "turnover"]),
    *(Alias(p, "net_income") for p in ["net income", "net profit", "profit", "profits", "net earnings", "bottom line"]),
    Alias("net loss", "net_income"),
    Alias("loss", "net_income", strong=False),
    Alias("earnings", "net_income", strong=False),
    *(Alias(p, "eps") for p in ["diluted eps", "eps", "earnings per share", "diluted earnings per share",
                                "per-share earnings", "diluted earnings"]),
    *(Alias(p, "net_margin") for p in ["net margin", "profit margin", "net profit margin", "margin"]),
    # inflation
    *(Alias(p, "inflation") for p in ["inflation", "headline inflation", "cpi", "headline cpi",
                                      "consumer price index", "consumer price inflation"]),
    Alias("consumer prices", "inflation", basis="level"),
    Alias("prices", "inflation", strong=False, basis="level"),
    *(Alias(p, "core_inflation") for p in ["core inflation", "core cpi", "core consumer prices",
                                           "core consumer price index", "core consumer price inflation",
                                           "core prices", "excluding food and energy",
                                           "excluding volatile food and energy",
                                           "ex food and energy", "core measure", "core index", "core rate"]),
    Alias("core", "core_inflation", strong=False),
    # labour market
    *(Alias(p, "unemployment") for p in ["unemployment rate", "unemployment", "jobless rate", "joblessness"]),
    *(Alias(p, "payrolls") for p in ["nonfarm payrolls", "non-farm payrolls", "payrolls", "payroll growth",
                                     "job gains", "job growth", "hiring", "employers"]),
    Alias("jobs", "payrolls", strong=False),
    Alias("employment", "payrolls", strong=False),
    # rates
    *(Alias(p, "fed_funds") for p in ["fed funds rate", "fed funds", "federal funds rate", "federal funds",
                                      "effective federal funds rate", "policy rate", "overnight rate"]),
    *(Alias(p, "yield_2y") for p in ["2-year yield", "2-year treasury yield", "2-year treasury", "2-year",
                                     "two-year yield", "two-year", "2y"]),
    *(Alias(p, "yield_10y") for p in ["10-year yield", "10-year treasury yield", "10-year treasury",
                                      "10-year", "ten-year yield", "ten-year", "10y", "benchmark yield"]),
    *(Alias(p, "curve") for p in ["yield curve", "curve", "spread", "10s-2s", "2s10s", "2s/10s", "10s2s"]),
    # commodities and growth
    *(Alias(p, "oil") for p in ["wti crude", "wti", "crude oil", "crude", "oil prices", "oil price", "oil"]),
    *(Alias(p, "gdp") for p in ["real gdp", "gdp", "economic growth", "the economy", "output"]),
    Alias("growth", "gdp", strong=False),
]

# Longest phrases first so "core inflation" wins over "inflation".
ALIASES = sorted(_ALIASES, key=lambda a: -len(a.phrase))
_ALIAS_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(a.phrase) for a in ALIASES) + r")(?![\w-])", re.IGNORECASE
)
_ALIAS_BY_PHRASE = {a.phrase: a for a in ALIASES}


@dataclass(frozen=True)
class AliasHit:
    start: int
    end: int
    alias: Alias


def find_aliases(text: str) -> list[AliasHit]:
    """All metric mentions in `text`, non-overlapping, longest phrase first.

    A mention glued to the previous one restates it and is dropped: the bracketed
    abbreviation in "core consumer price index (CPI)", and the head noun in "core CPI
    inflation" or "core consumer price index (CPI) inflation".
    """
    kept: list[AliasHit] = []
    for m in _ALIAS_RE.finditer(text):
        h = AliasHit(m.start(), m.end(), _ALIAS_BY_PHRASE[m.group(1).lower()])
        if kept:
            gap = text[kept[-1].end:h.start]
            if gap.strip() == "(" and text[h.end:h.end + 1] == ")":
                continue
            if h.alias.metric == "inflation" and kept[-1].alias.metric in ("inflation", "core_inflation") \
                    and _GLUE_RE.fullmatch(gap):
                continue
        kept.append(h)
    return kept


_GLUE_RE = re.compile(r"\s*(?:\([A-Za-z]{2,8}\))?\s*")


# Direction words. Plain verbs follow the metric's basis; trend verbs always describe
# the change versus the prior period ("growth slowed" even though "the economy grew").
UP = ["rose", "rise", "rises", "rising", "risen", "increased", "increase", "increases", "increasing",
      "grew", "grow", "grows", "growing", "climbed", "climbing", "jumped", "gained", "advanced", "higher",
      "up", "surged", "edged up", "ticked up", "added", "expanded", "rebounded", "firmed", "moved up",
      "jumping", "gaining", "surging", "soared", "soaring", "advancing", "rebounding"]
DOWN = ["fell", "fall", "falls", "falling", "fallen", "declined", "decline", "declines", "declining",
        "decreased", "decrease", "decreases", "dropped", "drop", "slipped", "slid", "lower", "down",
        "shrank", "contracted", "contraction", "plunged", "edged down", "ticked down", "cut", "lost",
        "retreated", "slumped", "tumbled", "moved down", "eased", "easing", "dropping", "decreasing",
        "sliding", "slipping", "shrinking", "slumping", "plunging", "tumbling", "sank", "sinking"]
TREND_UP = ["accelerated", "accelerating", "picked up", "quickened", "strengthened"]
TREND_DOWN = ["slowed", "slowing", "decelerated", "moderated", "cooled", "softened"]
FLAT = ["unchanged", "flat", "steady", "stable", "held at", "held steady"]

DIRECTION_WORDS = (
    [(w, +1, False) for w in UP] + [(w, -1, False) for w in DOWN]
    + [(w, +1, True) for w in TREND_UP] + [(w, -1, True) for w in TREND_DOWN]
    + [(w, 0, False) for w in FLAT]
)
_DIR_BY_WORD = {w: (sign, trend) for w, sign, trend in DIRECTION_WORDS}
_DIR_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(w) for w, *_ in sorted(DIRECTION_WORDS, key=lambda d: -len(d[0])))
    + r")(?![\w-])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DirectionHit:
    start: int
    end: int
    word: str
    sign: int  # +1 up, -1 down, 0 unchanged
    trend: bool


def find_directions(text: str) -> list[DirectionHit]:
    hits = []
    for m in _DIR_RE.finditer(text):
        word = m.group(1).lower()
        sign, trend = _DIR_BY_WORD[word]
        hits.append(DirectionHit(m.start(), m.end(), word, sign, trend))
    return hits
