"""Check a piece of financial commentary against the brief it was written from.

Every number must be traceable to the brief (a level, the prior value, or a change derived
from them), every direction word must agree with the data, and every period and company
named must be the ones the brief covers. Anything else is reported as a finding:

* contradicted  - the text says something the data shows to be false
* unverifiable  - the text asserts something the brief does not contain
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .briefs import Brief, Candidate
from .facts import US, FactStore
from .metrics import METRICS, AliasHit, find_aliases, find_directions
from .numbers import Mention, find_numbers, find_periods, matches

ENTITY_NAMES = {
    "Apple": ["Apple"],
    "Microsoft": ["Microsoft"],
    "Alphabet": ["Alphabet", "Google"],
    "Amazon": ["Amazon"],
    "NVIDIA": ["NVIDIA", "Nvidia"],
    "Meta Platforms": ["Meta Platforms", "Meta", "Facebook"],
    "Tesla": ["Tesla"],
    "JPMorgan Chase": ["JPMorgan Chase", "JPMorgan", "JP Morgan", "J.P. Morgan"],
    "Visa": ["Visa"],
    "Exxon Mobil": ["Exxon Mobil", "ExxonMobil", "Exxon"],
    "Walmart": ["Walmart"],
    "Johnson & Johnson": ["Johnson & Johnson", "J&J"],
    "Procter & Gamble": ["Procter & Gamble", "P&G"],
    "Coca-Cola": ["Coca-Cola", "Coca Cola", "Coke"],
    "Intel": ["Intel"],
}
FOREIGN = ["euro area", "euro-area", "eurozone", "euro zone", "European Central Bank", "ECB", "Bank of England", "BoE",
           "Bank of Japan", "BoJ", "China", "Japan", "Germany", "United Kingdom", "UK", "Britain", "Brent"]
_NAME_RE = {
    e: re.compile(r"(?<![\w&-])(" + "|".join(re.escape(n) for n in names) + r")(?![\w&-])")
    for e, names in ENTITY_NAMES.items()
}
_FOREIGN_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in FOREIGN) + r")(?![\w-])", re.IGNORECASE)
UNSUPPORTED_RE = re.compile(
    r"(?<![\w-])(analysts?|consensus|expectations?|expected|estimates?|forecasts?|guidance|record|all-time|"
    r"(?:highest|lowest|strongest|weakest|fastest|slowest) (?:level |pace |reading )?since|beat|beats|missed)(?![\w-])",
    re.IGNORECASE,
)
# Phrases that point at the prior period, so a sentence naming one period may still quote both.
PRIOR_REF_RE = re.compile(
    r"(?<![\w-])(from|versus|vs\.?|compared (?:with|to)|against|a year (?:earlier|ago|before)|"
    r"(?:the )?(?:previous|prior|preceding) (?:year|month|quarter|fiscal year|reading|period)|last year|"
    r"the year before|the month before|a month (?:earlier|ago|before)|the quarter before|a quarter earlier)"
    r"(?![\w-])",
    re.IGNORECASE,
)
_RANGE_START_RE = re.compile(r"(?:since|from|between|through|until|over)\s+(?:the\s+)?$", re.IGNORECASE)
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(“])")


@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    text: str
    verdict: str  # contradicted | unverifiable
    error: str  # value | scale | unit | period | entity | metric | direction | arithmetic | unsupported
    detail: str


@dataclass
class CheckResult:
    text: str
    findings: list[Finding] = field(default_factory=list)
    n_numbers: int = 0
    n_supported: int = 0

    @property
    def flagged(self) -> bool:
        return bool(self.findings)

    def errors(self) -> set[str]:
        return {f.error for f in self.findings}


def sentence_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENT_RE.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def _in(span: tuple[int, int], pos: int) -> bool:
    return span[0] <= pos < span[1]


def _link(pos: int, hits: list[AliasHit], sent: tuple[int, int], max_after: int = 40,
          text: str = "", end: int | None = None) -> AliasHit | None:
    """The metric a number or direction word at `pos` most likely refers to."""
    if end is not None:  # "$30.4bn in net income", "$416bn of revenue"
        for h in hits:
            if h.start >= end and text[end:h.start].strip().lower() in ("in", "of", "in net", "of net"):
                return h
    before = [h for h in hits if _in(sent, h.start) and h.end <= pos]
    if before:
        return max(before, key=lambda h: h.end)
    after = [h for h in hits if _in(sent, h.start) and h.start >= pos and h.start - pos <= max_after]
    return min(after, key=lambda h: h.start) if after else None


def _compatible(m: Mention, c: Candidate) -> bool:
    return m.kind == "bare" or m.kind == c.kind


def _bound_period(num: Mention, periods, numbers, sent, brief: Brief, text: str = "") -> str | None:
    """The brief period written right next to a number ("$307bn ... in fiscal 2022",
    "fiscal 2022, ... generated $307bn"), with no other number in between."""
    best = None
    for p in periods:
        if not _in(sent, p.start) or _starts_range(text, p):
            continue
        lo, hi = (p.end, num.start) if p.end <= num.start else (num.end, p.start)
        gap = hi - lo
        if gap > (30 if p.end <= num.start else 25) or any(lo <= o.start < hi for o in numbers if o is not num):
            continue
        if ";" in text[lo:hi] or ":" in text[lo:hi]:
            continue  # never across clauses
        if p.end <= num.start and PRIOR_REF_RE.search(text[lo:hi]):
            continue  # "in January, from 6.40%": the number is the earlier reading
        if p.end <= num.start and any(0 <= p.start - o.end <= 6 for o in numbers if o is not num):
            continue  # "from 241k in April; ...": April already belongs to 241k
        if p.end <= num.start and re.search(r"\bto\b", text[lo:hi]):
            continue  # "from $91 in March to $100": March is the start, not this number's period
        resolved = _resolve_period(brief, p)
        after = p.start >= num.end  # "$100 a barrel in April": a period right after wins
        if resolved is not None and (best is None or (after, -gap) > (best[0], -best[1])):
            best = (after, gap, resolved)
    return best[2] if best else None


def _starts_range(text: str, p) -> bool:
    return bool(_RANGE_START_RE.search(text[max(0, p.start - 14):p.start]))


def _resolve_period(brief: Brief, ph) -> str | None:
    """Map a period expression onto one of the brief's two periods, if it names one."""
    for p in (brief.period, brief.prior):
        if p.startswith("FY"):
            if ph.year == int(p[2:]) and ph.month is None and ph.quarter is None:
                return p
        elif "Q" in p:
            y, q = map(int, p.split("Q"))
            if ph.quarter == q and ph.year in (None, y):
                return p
        else:
            y, mo = map(int, p.split("-"))
            if ph.month == mo and ph.year in (None, y):
                return p
    return None


class Checker:
    def __init__(self, store: FactStore | None = None):
        self.store = store

    def check(self, text: str, brief: Brief) -> CheckResult:
        res = CheckResult(text)
        sents = sentence_spans(text)
        aliases = find_aliases(text)
        numbers = find_numbers(text)
        periods = find_periods(text)
        cands = brief.candidates()
        found: list[Finding] = []

        found += self._entities(text, brief)
        found += self._periods(periods, brief)
        for m in UNSUPPORTED_RE.finditer(text):
            found.append(Finding(m.start(), m.end(), m.group(0), "unverifiable", "unsupported",
                                 "claim about expectations or records the brief does not contain"))

        for num in numbers:
            sent = next(s for s in sents if _in(s, num.start))
            res.n_numbers += 1
            f = self._number(text, num, sent, aliases, periods, cands, brief)
            if f is None:
                res.n_supported += 1
            else:
                found.append(f)

        found += self._directions(text, sents, aliases, brief)

        seen: set[tuple[int, int]] = set()
        for f in sorted(found, key=lambda f: (f.start, f.verdict != "contradicted")):
            if (f.start, f.end) not in seen:
                seen.add((f.start, f.end))
                res.findings.append(f)
        return res

    # ----- entities and periods ---------------------------------------------------------
    def _entities(self, text: str, brief: Brief) -> list[Finding]:
        out = []
        own = ENTITY_NAMES.get(brief.entity, [])
        for entity, rx in _NAME_RE.items():
            if entity == brief.entity:
                continue
            for m in rx.finditer(text):
                if any(m.group(0) in n and n in text[max(0, m.start() - 20): m.end() + 20] for n in own):
                    continue  # part of the brief's own name
                out.append(Finding(m.start(), m.end(), m.group(0), "contradicted", "entity",
                                   f"brief is about {brief.entity}"))
        if brief.entity == US:
            for m in _FOREIGN_RE.finditer(text):
                out.append(Finding(m.start(), m.end(), m.group(0), "unverifiable", "entity",
                                   "brief covers the US only"))
        return out

    def _periods(self, periods, brief: Brief) -> list[Finding]:
        out = []
        years = brief.allowed_years()
        for ph in periods:
            if ph.year is not None and ph.year not in years:
                out.append(Finding(ph.start, ph.end, ph.text, "contradicted", "period",
                                   f"brief covers {brief.period_label(brief.prior)} and {brief.period_label()}"))
            elif brief.topic != "company" and ph.month is not None and brief.allowed_months() \
                    and ph.month not in brief.allowed_months():
                out.append(Finding(ph.start, ph.end, ph.text, "contradicted", "period",
                                   f"brief covers {brief.period_label(brief.prior)} and {brief.period_label()}"))
            elif ph.quarter is not None and ph.quarter not in brief.allowed_quarters():
                verdict = "contradicted" if brief.topic == "growth" else "unverifiable"
                out.append(Finding(ph.start, ph.end, ph.text, verdict, "period", "quarter not in the brief"))
        return out

    # ----- numbers ----------------------------------------------------------------------
    def _number(self, text, num: Mention, sent, aliases, periods, cands, brief: Brief) -> Finding | None:
        hit = _link(num.start, aliases, sent, text=text, end=num.end)
        metric = hit.alias.metric if hit else None
        pool = [c for c in cands if _compatible(num, c)]

        # A sentence that names exactly one of the brief's periods, and never points back to
        # the prior one, should quote that period's levels.
        sent_text = text[sent[0]:sent[1]]
        all_numbers = find_numbers(text)
        bound = _bound_period(num, periods, all_numbers, sent, brief, text)
        named = {_resolve_period(brief, p) for p in periods
                 if _in(sent, p.start) and not _starts_range(text, p)} - {None}
        if bound is None and len(named) == 1 and not PRIOR_REF_RE.search(sent_text):
            (bound,) = named
        if bound is not None:
            pool_p = [c for c in pool if c.what not in ("level", "prior") or c.period == bound]
        else:
            pool_p = pool

        any_match = [c for c in pool_p if matches(num, c.value)]
        same = [c for c in pool_p if c.metric == metric]
        same_match = [c for c in same if matches(num, c.value)]
        # An alias binds tightly only to the first number after it; in "headline 3.1% and
        # core 2.9%, versus 3.0% and 2.8%" the later numbers are only loosely linked.
        tight = hit is not None and not any(
            o is not num and hit.end <= o.start < num.start for o in all_numbers
        )

        if same_match or (any_match and not same):
            return None
        if any_match and same:
            if hit.alias.strong and tight:
                other = METRICS[any_match[0].metric].label
                return Finding(num.start, num.end, num.stated, "contradicted", "metric",
                               f"value belongs to {other}, not {METRICS[metric].label}")
            return None
        if not same and metric is None:
            err, why = self._diagnose(num, None, pool, brief)
            return Finding(num.start, num.end, num.stated, "unverifiable", err or "unsupported",
                           why or "number not found in the brief")
        err, why = self._diagnose(num, metric, pool, brief)
        if not same:
            return Finding(num.start, num.end, num.stated, "unverifiable", err or "unsupported",
                           why or f"no {num.kind} figure for {METRICS[metric].label} in the brief")
        expected = ", ".join(_fmt(c) for c in same[:4])
        if err is None and any(_truncated(num, c.value) for c in same):
            err, why = "rounding", f"truncated rather than rounded; brief has {expected}"
        return Finding(num.start, num.end, num.stated, "contradicted", err or "value",
                       why or f"brief has {expected}")

    def _diagnose(self, num: Mention, metric: str | None, pool: list[Candidate], brief: Brief):
        """Name the likely error behind a number that matches nothing in the brief."""
        same = [c for c in pool if metric is None or c.metric == metric]
        for factor in (1e3, 1e-3):
            if num.kind in ("usd", "count") and any(matches(num, c.value * factor) for c in same):
                return "scale", "off by a factor of 1,000 (million vs billion)"
        if num.kind in ("pct", "pp"):
            other = "pp" if num.kind == "pct" else "pct"
            for c in brief.candidates():
                if c.kind == other and (metric is None or c.metric == metric) and matches(num, c.value):
                    unit = "percentage points" if other == "pp" else "a percent"
                    return "unit", f"matches {_fmt(c)} written as {unit}"
            for c in brief.candidates():
                if c.what == "pct_change" and (metric is None or c.metric == metric):
                    cur, prev = brief.values[c.metric]
                    wrong = [(cur - prev) / cur * 100 if cur else None, cur / prev * 100 if prev else None]
                    if any(w is not None and matches(num, w) for w in wrong):
                        return "arithmetic", f"percent change miscomputed; correct is {c.value:.1f}%"
            for c in pool:
                if c.what == "pct_change" and (metric is None or c.metric == metric) \
                        and abs(num.value - abs(c.value)) <= max(1.0, 0.25 * abs(c.value)):
                    return "arithmetic", f"percent change should be {abs(c.value):.1f}%"
        for c in pool:  # right number, wrong period label ("$416bn in fiscal 2024")
            if c.metric == metric and c.what in ("level", "prior") and matches(num, c.value):
                return "period", f"matches {METRICS[metric].label} for {brief.period_label(c.period)}"
        if self.store is not None and metric in METRICS and _precise(num):
            for period, v in self.store.series(brief.entity, metric).items():
                if period not in (brief.period, brief.prior) and _kind_ok(num, metric) and matches(num, v):
                    return "period", f"matches {METRICS[metric].label} for {brief.period_label(period)}"
            if brief.topic == "company":
                for entity in self.store.entities():
                    v = self.store.get(entity, metric, brief.period)
                    if entity != brief.entity and v is not None and _kind_ok(num, metric) and matches(num, v):
                        return "entity", f"matches {entity}'s {METRICS[metric].label}"
        return None, None

    # ----- direction words --------------------------------------------------------------
    def _directions(self, text, sents, aliases, brief: Brief) -> list[Finding]:
        out = []
        numbers = find_numbers(text)
        for d in find_directions(text):
            sent = next(s for s in sents if _in(s, d.start))
            hit = _link(d.start, aliases, sent, max_after=30)
            if hit is None:
                continue
            metric = METRICS.get(hit.alias.metric)
            if metric is None:
                continue
            basis = "change" if d.trend else (hit.alias.basis or metric.basis)
            # "the CPI rose 3.7% from a year earlier": the verb describes the level it is
            # directly followed by, not the change versus the prior period.
            nxt = next((n for n in numbers if n.start >= d.end and text[d.end:n.start] in (" ", " by ")), None)
            if re.match(r"\s+(?:from|than)\b", text[d.end:]):
                basis = "change"  # "down from 6.3%", "higher than in August"
            elif not d.trend and d.sign != 0 and nxt is not None:
                own = [c for c in brief.candidates() if c.metric == metric.key and _compatible(nxt, c)]
                if any(matches(nxt, c.value) for c in own if c.what == "level") and \
                        not any(matches(nxt, c.value) for c in own if c.what not in ("level", "prior")):
                    basis = "level"
            if basis == "change":
                delta = brief.change(metric.key)
                ref = brief.values.get(metric.key, (None, None))[1]
            else:
                delta = brief.level(metric.key)
                ref = delta
            if delta is None:
                continue
            # "rose" is wrong as soon as the quantity fell at all ("rose slightly to 3.28% from
            # 3.29%"); "unchanged" is allowed a small tolerance for rounding.
            tol = metric.flat_tol * abs(ref) if metric.kind == "usd" and ref else metric.flat_tol
            eps = 1e-9 * max(1.0, abs(ref or 0))
            wrong = (d.sign > 0 and delta < -eps) or (d.sign < 0 and delta > eps) or (d.sign == 0 and abs(delta) > 2 * tol)
            if wrong:
                what = "change" if basis == "change" else "value"
                out.append(Finding(d.start, d.end, text[d.start:d.end], "contradicted", "direction",
                                   f"{metric.label} {what} is {delta:+,.4g}"))
        return out


def _truncated(num: Mention, value: float) -> bool:
    """Within one unit of the last digit written: rounded the wrong way, not made up."""
    return abs(num.value - abs(value)) <= 2 * num.tol * 1.001


def _precise(num: Mention) -> bool:
    """At least three significant digits, so a match elsewhere in the data is not luck."""
    return num.value > 0 and num.tol / num.value < 0.005


def _kind_ok(num: Mention, metric: str) -> bool:
    return num.kind == "bare" or num.kind == METRICS[metric].kind


def _fmt(c: Candidate) -> str:
    unit = {"usd": "USD", "pct": "%", "pp": "pp", "count": "jobs"}[c.kind]
    v = c.value
    if c.kind == "usd" and abs(v) >= 1e6:
        return f"{c.what} {v / 1e9:,.2f}bn USD"
    return f"{c.what} {v:,.2f} {unit}"
