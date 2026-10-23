"""Briefs: the bundle of source facts a commentary is written from, and every number
a faithful commentary could legitimately derive from them."""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field

from .facts import US, FactStore
from .metrics import METRICS

TOPICS = {
    "company": ["revenue", "net_income", "eps"],
    "inflation": ["inflation", "core_inflation"],
    "labor": ["unemployment", "payrolls"],
    "rates": ["fed_funds", "yield_2y", "yield_10y"],
    "oil": ["oil"],
    "growth": ["gdp"],
}


@dataclass(frozen=True)
class Candidate:
    metric: str
    kind: str  # usd | pct | pp | count
    value: float
    what: str  # level | prior | change | pct_change | pp_change
    period: str | None = None


@dataclass
class Brief:
    id: str
    topic: str
    entity: str
    period: str
    prior: str
    values: dict[str, tuple[float, float]] = field(default_factory=dict)  # metric -> (current, prior)

    # ----- periods -------------------------------------------------------------------------
    def period_label(self, period: str | None = None) -> str:
        p = period or self.period
        if p.startswith("FY"):
            return f"fiscal {p[2:]}"
        if "Q" in p:
            y, q = p.split("Q")
            return f"Q{q} {y}"
        y, m = p.split("-")
        return f"{calendar.month_name[int(m)]} {y}"

    def allowed_years(self) -> set[int]:
        return {_year(self.period), _year(self.prior)}

    def allowed_months(self) -> set[int]:
        return {int(p.split("-")[1]) for p in (self.period, self.prior) if "-" in p}

    def allowed_quarters(self) -> set[int]:
        return {int(p.split("Q")[1]) for p in (self.period, self.prior) if "Q" in p}

    # ----- what a faithful text may say ---------------------------------------------------
    def candidates(self) -> list[Candidate]:
        out: list[Candidate] = []
        for metric, (cur, prev) in self.values.items():
            kind = METRICS[metric].kind
            out.append(Candidate(metric, kind, cur, "level", self.period))
            out.append(Candidate(metric, kind, prev, "prior", self.prior))
            if kind == "pct":
                out.append(Candidate(metric, "pp", cur - prev, "pp_change"))
            else:
                out.append(Candidate(metric, kind, cur - prev, "change"))
                if prev and metric != "payrolls":  # a % change of monthly job gains means nothing
                    out.append(Candidate(metric, "pct", (cur - prev) / abs(prev) * 100, "pct_change"))
        if self.topic == "company" and {"revenue", "net_income"} <= self.values.keys():
            (r, rp), (n, np_) = self.values["revenue"], self.values["net_income"]
            out.append(Candidate("net_margin", "pct", n / r * 100, "level", self.period))
            out.append(Candidate("net_margin", "pct", np_ / rp * 100, "prior", self.prior))
            out.append(Candidate("net_margin", "pp", n / r * 100 - np_ / rp * 100, "pp_change"))
        if self.topic == "rates":
            (y10, y10p), (y2, y2p) = self.values["yield_10y"], self.values["yield_2y"]
            out.append(Candidate("curve", "pp", y10 - y2, "level", self.period))
            out.append(Candidate("curve", "pp", y10p - y2p, "prior", self.prior))
            out.append(Candidate("curve", "pp", (y10 - y2) - (y10p - y2p), "pp_change"))
        return out

    def change(self, metric: str) -> float | None:
        if metric in self.values:
            cur, prev = self.values[metric]
            return cur - prev
        if metric == "net_margin" and {"revenue", "net_income"} <= self.values.keys():
            (r, rp), (n, np_) = self.values["revenue"], self.values["net_income"]
            return n / r - np_ / rp
        if metric == "curve" and {"yield_10y", "yield_2y"} <= self.values.keys():
            return (self.values["yield_10y"][0] - self.values["yield_2y"][0]) - (
                self.values["yield_10y"][1] - self.values["yield_2y"][1])
        return None

    def level(self, metric: str) -> float | None:
        return self.values[metric][0] if metric in self.values else None

    # ----- prompt ---------------------------------------------------------------------------
    def fact_lines(self) -> list[str]:
        lines = []
        who = "US" if self.entity == US else self.entity
        for metric, (cur, prev) in self.values.items():
            for period, v in ((self.period, cur), (self.prior, prev)):
                lines.append(f"{who} {METRICS[metric].label}, {self.period_label(period)}: "
                             f"{format_source_value(metric, v)}")
        return lines


def _year(period: str) -> int:
    return int(period[2:6]) if period.startswith("FY") else int(period[:4])


def format_source_value(metric: str, v: float) -> str:
    """How a value appears in the source table handed to a writer (human or LLM)."""
    kind = METRICS[metric].kind
    if metric == "eps":
        return f"USD {v:.2f} per share"
    if metric == "oil":
        return f"USD {v:.2f} per barrel"
    if kind == "usd":
        return f"USD {v / 1e6:,.0f} million"
    if kind == "count":
        return f"{v:+,.0f} jobs"
    return f"{v:.2f}%"


def _prev_month(p: str) -> str:
    y, m = map(int, p.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _prev_quarter(p: str) -> str:
    y, q = map(int, p.split("Q"))
    return f"{y - 1}Q4" if q == 1 else f"{y}Q{q - 1}"


def build_briefs(store: FactStore, first_month: str = "2023-01", first_fy: int = 2021) -> list[Brief]:
    briefs: list[Brief] = []
    for entity in store.entities():
        years = sorted({int(p[2:]) for m in TOPICS["company"] for p in store.series(entity, m)})
        for y in years:
            if y < first_fy:
                continue
            values = {}
            for metric in TOPICS["company"]:
                cur, prev = store.get(entity, metric, f"FY{y}"), store.get(entity, metric, f"FY{y - 1}")
                if cur is not None and prev is not None and (metric != "eps" or (cur and prev)):
                    values[metric] = (cur, prev)
            if "revenue" in values and "net_income" in values:
                briefs.append(Brief(f"{entity}-FY{y}".replace(" ", "_"), "company", entity,
                                    f"FY{y}", f"FY{y - 1}", values))
    months = sorted(p for p in store.series(US, "inflation") if p >= first_month)
    for topic in ("inflation", "labor", "rates", "oil"):
        for p in months:
            prev = _prev_month(p)
            values = {}
            for metric in TOPICS[topic]:
                cur, pv = store.get(US, metric, p), store.get(US, metric, prev)
                if cur is None or pv is None:
                    break
                values[metric] = (cur, pv)
            else:
                briefs.append(Brief(f"US-{topic}-{p}", topic, US, p, prev, values))
    for p in sorted(store.series(US, "gdp")):
        if p >= first_month[:4] and store.get(US, "gdp", _prev_quarter(p)) is not None:
            briefs.append(Brief(f"US-growth-{p}", "growth", US, p, _prev_quarter(p),
                                {"gdp": (store.get(US, "gdp", p), store.get(US, "gdp", _prev_quarter(p)))}))
    return briefs
