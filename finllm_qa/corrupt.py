"""Inject one labelled, realistic LLM-style error into a correct commentary.

Each corruption returns the new text and a label with the character span it changed,
or None when the text offers nothing to corrupt in that way.
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass

from .briefs import Brief
from .checker import ENTITY_NAMES
from .metrics import METRICS, find_aliases, find_directions
from .numbers import find_numbers, find_periods, matches

_DIGITS = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
OPPOSITE = {
    "rose": "fell", "fell": "rose", "increased": "decreased", "decreased": "increased", "climbed": "dropped",
    "dropped": "climbed", "declined": "increased", "grew": "shrank", "shrank": "grew", "up": "down",
    "down": "up", "higher": "lower", "lower": "higher", "added": "cut", "cut": "added", "accelerated": "slowed",
    "slowed": "accelerated", "picked up": "slowed", "eased": "rose", "jumped": "slid", "slid": "jumped",
    "contracted": "grew", "ticked up": "ticked down", "ticked down": "ticked up",
}


@dataclass(frozen=True)
class Label:
    kind: str
    start: int
    end: int
    before: str
    after: str


def _splice(text: str, start: int, end: int, new: str, kind: str) -> tuple[str, Label]:
    return text[:start] + new + text[end:], Label(kind, start, start + len(new), text[start:end], new)


def _reformat(stated: str, new_value: float) -> str:
    """Write `new_value` in the place of the first number inside `stated`, same precision."""
    m = _DIGITS.search(stated)
    raw = m.group(0)
    dec = len(raw.split(".")[1]) if "." in raw else 0
    num = f"{new_value:,.{dec}f}" if "," in raw else f"{new_value:.{dec}f}"
    return stated[:m.start()] + num + stated[m.end():]


def _stated_number(stated: str) -> float:
    return float(_DIGITS.search(stated).group(0).replace(",", ""))


def value(text: str, b: Brief, rng: random.Random):
    nums = [n for n in find_numbers(text) if n.kind != "bare" and n.value > 0]
    if not nums:
        return None
    n = rng.choice(nums)
    cands = b.candidates()
    for _ in range(20):
        factor = 1 + rng.choice([-1, 1]) * rng.uniform(0.08, 0.35)
        new = _reformat(n.text, _stated_number(n.text) * factor)
        if new == n.text:
            continue
        probe = find_numbers(new)
        if probe and not any(matches(probe[0], c.value) for c in cands):
            return _splice(text, n.start, n.end, new, "value")
    return None


def scale(text: str, b: Brief, rng: random.Random):
    swaps = {"billion": "million", "million": "billion", "bn": "mn", "mn": "bn"}
    nums = [n for n in find_numbers(text) if n.kind == "usd" and re.search(r"billion|million|bn|mn", n.text)]
    if not nums:
        return None
    n = rng.choice(nums)
    word = re.search(r"billion|million|bn|mn", n.text).group(0)
    return _splice(text, n.start, n.end, n.text.replace(word, swaps[word]), "scale")


def direction(text: str, b: Brief, rng: random.Random):
    """Flip one direction word. Only used when every quantity in the brief moved (and sits)
    clearly away from zero, so any flipped word is false whatever it refers to."""
    if not _material(b):
        return None
    hits = [d for d in find_directions(text) if d.word in OPPOSITE]
    if not hits:
        return None
    d = rng.choice(hits)
    return _splice(text, d.start, d.end, _match_case(text[d.start:d.end], OPPOSITE[d.word]), "direction")


def _material(b: Brief) -> bool:
    for metric, (cur, prev) in b.values.items():
        m = METRICS[metric]
        tol = m.flat_tol * abs(prev) if m.kind == "usd" else m.flat_tol
        if abs(cur - prev) <= 2 * tol or abs(cur) <= 2 * tol:
            return False
    return True


def period_out(text: str, b: Brief, rng: random.Random):
    hits = find_periods(text)
    years = [h for h in hits if h.year is not None]
    if years:
        h = rng.choice(years)
        bad = h.year - 2 if rng.random() < 0.5 else min(b.allowed_years()) - 1
        new = re.sub(str(h.year), str(bad), h.text)
        return _splice(text, h.start, h.end, new, "period")
    months = [h for h in hits if h.month is not None]
    if months:
        h = rng.choice(months)
        bad = [m for m in range(1, 13) if m not in b.allowed_months()]
        new = h.text.replace(MONTHS[h.month - 1], MONTHS[rng.choice(bad) - 1])
        return _splice(text, h.start, h.end, new, "period")
    return None


def period_swap(text: str, b: Brief, rng: random.Random):
    """Attach the prior period's label to the current period's numbers."""
    cur_year = int(b.period[2:6]) if b.period.startswith("FY") else int(b.period[:4])
    for h in find_periods(text):
        if b.topic == "company" and h.year == cur_year:
            return _splice(text, h.start, h.end, h.text.replace(str(cur_year), str(cur_year - 1)), "period")
        if b.topic != "company" and h.month is not None and "-" in b.period and h.month == int(b.period[5:7]):
            prev_month = MONTHS[int(b.prior[5:7]) - 1]
            new = h.text.replace(MONTHS[h.month - 1], prev_month)
            if h.year is not None and b.prior[:4] != b.period[:4]:
                new = new.replace(str(h.year), b.prior[:4])
            return _splice(text, h.start, h.end, new, "period")
    return None


def arithmetic(text: str, b: Brief, rng: random.Random):
    pcs = [c for c in b.candidates() if c.what == "pct_change"]
    for n in find_numbers(text):
        if n.kind != "pct":
            continue
        for c in pcs:
            if matches(n, c.value):
                cur, prev = b.values[c.metric]
                wrong = abs((cur - prev) / cur * 100) if cur else None
                if wrong is None or matches(n, wrong):
                    wrong = abs(c.value) * rng.choice([0.5, 1.6])
                new = _reformat(n.text, wrong)
                if new != n.text:
                    return _splice(text, n.start, n.end, new, "arithmetic")
    return None


def entity(text: str, b: Brief, rng: random.Random):
    if b.topic == "company":
        names = sorted(ENTITY_NAMES.get(b.entity, [b.entity]), key=len, reverse=True)
        for name in names:
            i = text.find(name)
            if i >= 0:
                other = rng.choice([e for e in ENTITY_NAMES if e != b.entity])
                return _splice(text, i, i + len(name), other, "entity")
        return None
    m = re.search(r"\bUS\b", text)
    if m:
        return _splice(text, m.start(), m.end(), rng.choice(["Euro-area", "UK"]), "entity")
    return None


def unit(text: str, b: Brief, rng: random.Random):
    for n in find_numbers(text):
        if n.kind == "pp":
            new = f"{n.value:.2f}%" if re.search(r"basis|bp", n.text, re.I) else re.sub(
                r"\s?(percentage[- ]points?|pp|ppts?)", "%", n.text)
            if new != n.text:
                return _splice(text, n.start, n.end, new, "unit")
    return None


SWAP_ALIASES = {
    "revenue": "net income", "sales": "net income", "net income": "revenue", "net profit": "revenue",
    "10-year": "2-year", "2-year": "10-year", "ten-year": "two-year",
    "core inflation": "headline inflation", "core cpi": "headline CPI",
}


def metric(text: str, b: Brief, rng: random.Random):
    hits = [h for h in find_aliases(text) if h.alias.phrase in SWAP_ALIASES]
    if not hits:
        return None
    h = rng.choice(hits)
    new = _match_case(text[h.start:h.end], SWAP_ALIASES[h.alias.phrase])
    return _splice(text, h.start, h.end, new, "metric")


def unsupported(text: str, b: Brief, rng: random.Random):
    if b.topic == "company":
        r = b.values["revenue"][0]
        claim = f" That beat the consensus estimate of ${r * rng.uniform(0.95, 0.99) / 1e9:.1f} billion."
    elif b.topic == "inflation":
        claim = f" Economists had expected {b.values['inflation'][0] + rng.choice([-0.2, 0.1, 0.2]):.1f}%."
    elif b.topic == "labor":
        claim = f" Analysts had forecast {abs(b.values['payrolls'][0]) * rng.uniform(1.2, 1.6):,.0f} jobs."
    elif b.topic == "rates":
        claim = f" The 10-year yield touched its highest level since {rng.choice([2007, 2008, 2011])}."
    elif b.topic == "oil":
        claim = f" Prices were at their highest since {rng.choice([2014, 2015, 2018])}."
    else:
        claim = f" Economists had expected {b.values['gdp'][0] + rng.choice([-0.4, 0.3, 0.5]):.1f}%."
    return text + claim, Label("unsupported", len(text), len(text) + len(claim), "", claim)


def _match_case(old: str, new: str) -> str:
    return new[0].upper() + new[1:] if old[:1].isupper() else new


CORRUPTIONS = {
    "value": value, "scale": scale, "direction": direction, "period": period_out, "period_swap": period_swap,
    "arithmetic": arithmetic, "entity": entity, "unit": unit, "metric": metric, "unsupported": unsupported,
}
