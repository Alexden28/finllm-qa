"""Reference commentary written from a brief: correct by construction.

Two template sets: DEV was used while building the checker; HELDOUT was written in a
different house style and kept out of development, to show how much the checker relies
on familiar phrasing.
"""
from __future__ import annotations

import calendar
import random

from .briefs import Brief

ORDINAL = {1: "first", 2: "second", 3: "third", 4: "fourth"}


# ----- formatting ---------------------------------------------------------------------------
def usd(v: float, rng: random.Random) -> str:
    a = abs(v)
    if a < 1e3:
        return f"${a:,.2f}"
    scale, words = ((1e12, ("trillion", "tn")) if a >= 1e12 else
                    (1e9, ("billion", "bn")) if a >= 1e9 else (1e6, ("million", "mn")))
    word = rng.choice(words)
    dec = rng.choice([1, 1, 2]) if a / scale < 100 else rng.choice([0, 1, 1])
    num = f"{a / scale:,.{dec}f}"
    return f"${num} {word}" if len(word) > 2 else f"${num}{word}"


def pct(v: float, rng: random.Random, dec: int | None = None) -> str:
    dec = rng.choice([1, 1, 2]) if dec is None else dec
    return f"{abs(v):.{dec}f}" + rng.choice(["%", "%", " percent"])


def pp(v: float, rng: random.Random, bp_ok: bool = False) -> str:
    if bp_ok and rng.random() < 0.6:
        return f"{abs(v) * 100:.0f} " + rng.choice(["basis points", "bp"])
    return f"{abs(v):.2f} percentage points"


def jobs(v: float, rng: random.Random) -> str:
    a = abs(v)
    style = rng.choice(["comma", "comma", "k"])
    return f"{a:,.0f}" if style == "comma" else f"{a / 1000:.0f}k"


def up_down(delta: float, rng: random.Random, up=("rose", "increased", "climbed"),
            down=("fell", "declined", "dropped")) -> str:
    return rng.choice(up if delta > 0 else down)


def month(p: str) -> str:
    return calendar.month_name[int(p.split("-")[1])]


def month_year(p: str) -> str:
    return f"{month(p)} {p[:4]}"


# ----- company -----------------------------------------------------------------------------
def _ni_clause(n: float, n_prev: float, rng: random.Random) -> str:
    if n < 0:
        return f"it posted a net loss of {usd(n, rng)}"
    if n_prev <= 0:
        return f"it returned to a net profit of {usd(n, rng)}"
    return f"net income {up_down(n - n_prev, rng)} to {usd(n, rng)}"


def company_dev(b: Brief, rng: random.Random) -> str:
    E, Y = b.entity, b.period[2:]
    (r, rp), (n, np_) = b.values["revenue"], b.values["net_income"]
    eps = b.values.get("eps")
    g = (r - rp) / rp * 100
    v = rng.randrange(4)
    if v == 0:
        s = (f"{E} reported revenue of {usd(r, rng)} for fiscal {Y}, {'up' if g > 0 else 'down'} "
             f"{pct(g, rng)} from {usd(rp, rng)} a year earlier. ")
        s += _ni_clause(n, np_, rng).capitalize()
        if eps:
            s += f", and diluted EPS came in at {usd(eps[0], rng)} versus {usd(eps[1], rng)}"
        return s + "."
    if v == 1:
        s = (f"In fiscal {Y}, {E}'s sales {up_down(g, rng, ('grew', 'rose'), ('declined', 'fell'))} "
             f"{pct(g, rng)} to {usd(r, rng)}. ")
        s += (f"Net profit was {usd(n, rng)}, compared with {usd(np_, rng)} in fiscal {int(Y) - 1}." if n > 0 and np_ > 0
              else _ni_clause(n, np_, rng).capitalize() + ".")
        if eps and eps[0] > 0 and eps[1] > 0:
            s += f" Earnings per share {up_down(eps[0] - eps[1], rng, ('increased',), ('decreased',))} to {usd(eps[0], rng)}."
        return s
    if v == 2:
        loss = n < 0
        s = (f"{E} posted fiscal {Y} {'a net loss' if loss else 'net income'} of {usd(n, rng)} on revenue of "
             f"{usd(r, rng)}, a net margin of {'-' if loss else ''}{pct(n / r * 100, rng)}. ")
        return s + f"Revenue was {'up' if g > 0 else 'down'} {pct(g, rng)} year over year."
    s = f"{E}'s top line {up_down(g, rng)} {usd(r - rp, rng)} to {usd(r, rng)} in fiscal {Y}."
    if eps and eps[1] > 0:
        ge = (eps[0] - eps[1]) / eps[1] * 100
        s += f" Diluted earnings per share {up_down(ge, rng)} {pct(ge, rng)} to {usd(eps[0], rng)}."
    else:
        s += f" Net income came to {usd(n, rng)}." if n > 0 else f" It reported a net loss of {usd(n, rng)}."
    return s


def company_heldout(b: Brief, rng: random.Random) -> str:
    E, Y = b.entity, b.period[2:]
    (r, rp), (n, np_) = b.values["revenue"], b.values["net_income"]
    eps = b.values.get("eps")
    g = (r - rp) / rp * 100
    v = rng.randrange(3)
    if v == 0 or n <= 0 or np_ <= 0:
        sign = "+" if g > 0 else "-"
        tail = f"{usd(n, rng)} in net income" if n > 0 else f"a net loss of {usd(n, rng)}"
        return f"For the fiscal year {Y}, {E} generated {usd(r, rng)} in revenue ({sign}{pct(g, rng)} y/y) and {tail}."
    if v == 1:
        gn = (n - np_) / np_ * 100
        return (f"Fiscal {Y} was a {'stronger' if gn > 0 else 'weaker'} year for {E}: net income "
                f"{up_down(gn, rng, ('climbed', 'jumped'), ('dropped', 'slid'))} {pct(gn, rng)}, to {usd(n, rng)}, "
                f"while revenue reached {usd(r, rng)}.")
    s = f"{E} closed fiscal {Y} with {usd(r, rng)} of revenue versus {usd(rp, rng)} the year before"
    if eps:
        s += f"; EPS came in at {usd(eps[0], rng)} against {usd(eps[1], rng)}"
    return s + "."


# ----- macro -------------------------------------------------------------------------------
def inflation_dev(b: Brief, rng: random.Random) -> str:
    (i, ip), (c, cp) = b.values["inflation"], b.values["core_inflation"]
    M, P = month_year(b.period), month(b.prior)
    v = rng.randrange(3)
    if v == 0:
        rel = ("up from" if i - ip >= 0.05 else "down from" if ip - i >= 0.05 else "compared with")
        core = (f"Core inflation {up_down(c - cp, rng, ('rose', 'climbed'), ('eased', 'slowed'))} to {pct(c, rng, 2)}"
                if abs(c - cp) >= 0.05 else f"Core inflation was little changed at {pct(c, rng, 2)}")
        return f"US consumer prices rose {pct(i, rng, 2)} in the year to {M}, {rel} {pct(ip, rng, 2)} in {P}. {core}."
    if v == 1 and abs(i - ip) >= 0.05:
        verb = "accelerated" if i > ip else "slowed"
        return (f"Annual CPI inflation {verb} to {pct(i, rng, 2)} in {month(b.period)}, from {pct(ip, rng, 2)} "
                f"the month before, while core CPI stood at {pct(c, rng, 2)}.")
    return (f"Inflation came in at {pct(i, rng, 2)} year on year in {M}. Excluding food and energy, "
            f"prices were up {pct(c, rng, 2)} from a year earlier.")


def inflation_heldout(b: Brief, rng: random.Random) -> str:
    (i, ip), (c, cp) = b.values["inflation"], b.values["core_inflation"]
    if rng.random() < 0.5:
        return (f"{month(b.period)}'s CPI report showed headline inflation of {pct(i, rng, 2)} and core inflation of "
                f"{pct(c, rng, 2)}, versus {pct(ip, rng, 2)} and {pct(cp, rng, 2)} in {month(b.prior)}.")
    return (f"Price pressures {'built' if i > ip else 'faded'} in {month_year(b.period)}: the CPI rose {pct(i, rng, 2)} "
            f"from a year earlier, against {pct(ip, rng, 2)} a month before, and the core measure was {pct(c, rng, 2)}.")


def labor_dev(b: Brief, rng: random.Random) -> str:
    (u, up), (j, jp) = b.values["unemployment"], b.values["payrolls"]
    M, P = month_year(b.period), month(b.prior)
    v = rng.randrange(3)
    if v == 2 and j > 0 and jp > 0 and abs(j - jp) > 1000:
        verb = "picked up" if j > jp else "slowed"
        return (f"Payroll growth {verb} to {jobs(j, rng)} in {M} from {jobs(jp, rng)} in {P}; "
                f"unemployment was {pct(u, rng, 1)}.")
    if v == 1:
        verb = "added" if j > 0 else "cut"
        rate = (f"rose to {pct(u, rng, 1)}" if u > up else f"fell to {pct(u, rng, 1)}" if u < up
                else f"held at {pct(u, rng, 1)}")
        return f"Employers {verb} {jobs(j, rng)} jobs in {M}, and the jobless rate {rate}."
    if u == up:
        rate = f"The US unemployment rate was unchanged at {pct(u, rng, 1)} in {M}"
    else:
        rate = f"The US unemployment rate {up_down(u - up, rng)} to {pct(u, rng, 1)} in {M} from {pct(up, rng, 1)}"
    pay = f"nonfarm payrolls {'increased' if j > 0 else 'decreased'} by {jobs(j, rng)}"
    return f"{rate}, while {pay}."


def labor_heldout(b: Brief, rng: random.Random) -> str:
    (u, up), (j, jp) = b.values["unemployment"], b.values["payrolls"]
    if rng.random() < 0.5:
        what = "net new jobs" if j > 0 else "jobs lost"
        return (f"{month_year(b.period)} jobs report: {jobs(j, rng)} {what}, unemployment at {pct(u, rng, 1)} "
                f"({u - up:+.1f} pp on the month).")
    move = "ticked up to" if u > up else "ticked down to" if u < up else "held steady at"
    return (f"Payrolls {'grew' if j > 0 else 'shrank'} by {jobs(j, rng)} in {month(b.period)}, and the unemployment "
            f"rate {move} {pct(u, rng, 1)}.")


def rates_dev(b: Brief, rng: random.Random) -> str:
    (f, fp), (y2, y2p), (y10, y10p) = b.values["fed_funds"], b.values["yield_2y"], b.values["yield_10y"]
    M = month_year(b.period)
    v = rng.randrange(3)
    ff = (f"The effective fed funds rate averaged {pct(f, rng, 2)} in {M}." if abs(f - fp) < 0.005 else
          f"The effective fed funds rate {up_down(f - fp, rng)} to {pct(f, rng, 2)} in {M} from {pct(fp, rng, 2)}.")
    if v == 1 and (y2 - y2p) * (y10 - y10p) > 0 and abs(y2 - y2p) >= 0.01:
        spread = (y10 - y2) * 100
        return (f"Treasury yields moved {'higher' if y2 > y2p else 'lower'} in {month(b.period)}: the 2-year "
                f"averaged {pct(y2, rng, 2)} and the 10-year {pct(y10, rng, 2)}, leaving the 10s-2s spread at "
                f"{'-' if spread < 0 else ''}{abs(spread):.0f} basis points.")
    if v == 2 and abs(y10 - y10p) >= 0.01:
        return (f"With the policy rate at {pct(f, rng, 2)}, ten-year yields {up_down(y10 - y10p, rng)} "
                f"{pp(y10 - y10p, rng)} to {pct(y10, rng, 2)} in {M}.")
    ten = (f"The 10-year Treasury yield was unchanged at {pct(y10, rng, 2)}" if abs(y10 - y10p) < 0.005 else
           f"The 10-year Treasury yield {up_down(y10 - y10p, rng)} {pp(y10 - y10p, rng, bp_ok=True)} to {pct(y10, rng, 2)}")
    two = (f"the 2-year yield was unchanged at {pct(y2, rng, 2)}" if abs(y2 - y2p) < 0.005 else
           f"the 2-year yield {up_down(y2 - y2p, rng)} to {pct(y2, rng, 2)}")
    return f"{ff} {ten}, while {two}."


def rates_heldout(b: Brief, rng: random.Random) -> str:
    (f, fp), (y2, y2p), (y10, y10p) = b.values["fed_funds"], b.values["yield_2y"], b.values["yield_10y"]
    if rng.random() < 0.5:
        return (f"Rates recap, {month_year(b.period)}: fed funds {pct(f, rng, 2)}, 2y {pct(y2, rng, 2)} "
                f"({(y2 - y2p) * 100:+.0f} bp m/m), 10y {pct(y10, rng, 2)} ({(y10 - y10p) * 100:+.0f} bp m/m).")
    s, sp = y10 - y2, y10p - y2p
    shape = "steepened" if s > sp else "flattened"
    return (f"The curve {shape} in {month(b.period)}, with the 10-year minus 2-year spread moving to "
            f"{s:.2f} percentage points from {sp:.2f}.")


def oil_dev(b: Brief, rng: random.Random) -> str:
    o, op = b.values["oil"]
    g = (o - op) / op * 100
    if rng.random() < 0.5:
        return (f"WTI crude averaged {usd(o, rng)} a barrel in {month_year(b.period)}, {'up' if g > 0 else 'down'} "
                f"{pct(g, rng)} from {usd(op, rng)} in {month(b.prior)}.")
    return (f"Oil prices {up_down(g, rng)} {usd(o - op, rng)} to an average of {usd(o, rng)} per barrel "
            f"in {month(b.period)}.")


def oil_heldout(b: Brief, rng: random.Random) -> str:
    o, op = b.values["oil"]
    g = (o - op) / op * 100
    return (f"In {month_year(b.period)} the average WTI price was {usd(o, rng)}/bbl versus {usd(op, rng)}/bbl a month "
            f"earlier ({'+' if g > 0 else '-'}{pct(g, rng)}).")


def growth_dev(b: Brief, rng: random.Random) -> str:
    g, gp = b.values["gdp"]
    y, q = b.period.split("Q")
    if rng.random() < 0.5 or g < 0 or gp < 0 or g == gp:
        verb = "grew" if g > 0 else "contracted"
        return (f"US real GDP {verb} at an annualized {pct(g, rng, 1)} rate in the {ORDINAL[int(q)]} quarter of {y}, "
                f"compared with {pct(gp, rng, 1)} in the previous quarter.")
    verb = "accelerated" if g > gp else "slowed"
    return f"Economic growth {verb} to {pct(g, rng, 1)} in Q{q} {y} from {pct(gp, rng, 1)}."


def growth_heldout(b: Brief, rng: random.Random) -> str:
    g, gp = b.values["gdp"]
    y, q = b.period.split("Q")
    py, pq = b.prior.split("Q")
    return f"GDP, annualized: {'-' if g < 0 else ''}{pct(g, rng, 1)} in Q{q} {y} after {'-' if gp < 0 else ''}{pct(gp, rng, 1)} in Q{pq} {py}."


WRITERS = {
    "dev": {"company": company_dev, "inflation": inflation_dev, "labor": labor_dev,
            "rates": rates_dev, "oil": oil_dev, "growth": growth_dev},
    "heldout": {"company": company_heldout, "inflation": inflation_heldout, "labor": labor_heldout,
                "rates": rates_heldout, "oil": oil_heldout, "growth": growth_heldout},
}


def write(b: Brief, rng: random.Random, style: str = "dev") -> str:
    return WRITERS[style][b.topic](b, rng)
