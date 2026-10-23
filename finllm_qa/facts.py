"""Build the tidy fact table (entity, metric, period, value) from the raw downloads."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .sources import COMPANIES, ROOT, fetch_fred, fetch_sec

FACTS_CSV = ROOT / "data" / "facts.csv"
US = "US economy"

# XBRL tags tried in order; issuers changed tags over the years (ASC 606 in 2018).
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenuesNetOfInterestExpense",
    "SalesRevenueNet",
]
COMPANY_TAGS = {
    "revenue": (REVENUE_TAGS, "USD"),
    "net_income": (["NetIncomeLoss"], "USD"),
    "eps": (["EarningsPerShareDiluted"], "USD/shares"),
}
FIRST_FISCAL_YEAR = 2019
FIRST_MONTH = "2022-01"


def _annual_values(facts: dict, tags: list[str], unit: str) -> dict[int, float]:
    """Fiscal-year values from 10-K filings, keyed by the year the fiscal year ends.

    Keeps full-year durations only and, for restated years, the latest filing.
    Earlier tags in `tags` win when two tags report the same year.
    """
    out: dict[int, float] = {}
    gaap = facts["facts"].get("us-gaap", {})
    for tag in reversed(tags):  # later tags first, so earlier ones overwrite
        rows = gaap.get(tag, {}).get("units", {}).get(unit, [])
        best: dict[int, tuple[str, float]] = {}
        for r in rows:
            if r.get("form") != "10-K" or "start" not in r:
                continue
            days = (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days
            if not 350 <= days <= 380:
                continue
            end = date.fromisoformat(r["end"])
            # 52/53-week years ending in the first days of January belong to the prior year.
            year = end.year - 1 if end.month == 1 and end.day <= 7 else end.year
            if year not in best or r["filed"] > best[year][0]:
                best[year] = (r["filed"], float(r["val"]))
        out.update({y: v for y, (_, v) in best.items()})
    return out


def company_facts() -> pd.DataFrame:
    rows = []
    for name, cik in COMPANIES.items():
        facts = fetch_sec(cik)
        for metric, (tags, unit) in COMPANY_TAGS.items():
            for year, val in _annual_values(facts, tags, unit).items():
                if year >= FIRST_FISCAL_YEAR:
                    rows.append((name, metric, f"FY{year}", val, f"SEC XBRL CIK {cik}"))
    return pd.DataFrame(rows, columns=["entity", "metric", "period", "value", "source"])


def _monthly(s: pd.Series, how: str = "last") -> pd.Series:
    if how == "mean":  # daily series: average, dropping months with too few days so far
        m = s.resample("MS").mean()[s.resample("MS").count() >= 15]
    else:
        m = s.resample("MS").last()
    m.index = m.index.strftime("%Y-%m")
    return m


def macro_facts() -> pd.DataFrame:
    series = {
        "inflation": (_monthly(fetch_fred("CPIAUCSL")).pct_change(12, fill_method=None) * 100).round(2),
        "core_inflation": (_monthly(fetch_fred("CPILFESL")).pct_change(12, fill_method=None) * 100).round(2),
        "unemployment": _monthly(fetch_fred("UNRATE")).round(1),
        "payrolls": (_monthly(fetch_fred("PAYEMS")).diff() * 1000).round(0),
        "fed_funds": _monthly(fetch_fred("FEDFUNDS")).round(2),
        "yield_2y": _monthly(fetch_fred("DGS2"), "mean").round(2),
        "yield_10y": _monthly(fetch_fred("DGS10"), "mean").round(2),
        "oil": _monthly(fetch_fred("DCOILWTICO"), "mean").round(2),
    }
    rows = []
    for metric, s in series.items():
        for period, val in s.dropna().items():
            if period >= FIRST_MONTH:
                rows.append((US, metric, period, float(val), "FRED"))
    gdp = fetch_fred("A191RL1Q225SBEA")
    for ts, val in gdp.items():
        period = f"{ts.year}Q{(ts.month - 1) // 3 + 1}"
        if period >= FIRST_MONTH[:4]:
            rows.append((US, "gdp", period, round(float(val), 1), "FRED A191RL1Q225SBEA"))
    return pd.DataFrame(rows, columns=["entity", "metric", "period", "value", "source"])


def build_facts(path: Path = FACTS_CSV) -> pd.DataFrame:
    df = pd.concat([company_facts(), macro_facts()], ignore_index=True)
    df = df.sort_values(["entity", "metric", "period"]).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def load_facts(path: Path = FACTS_CSV) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"period": str})


class FactStore:
    """Lookup of (entity, metric, period) -> value, used to diagnose wrong numbers."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self._map = {(r.entity, r.metric, r.period): r.value for r in df.itertuples()}

    def get(self, entity: str, metric: str, period: str) -> float | None:
        return self._map.get((entity, metric, period))

    def series(self, entity: str, metric: str) -> dict[str, float]:
        sub = self.df[(self.df.entity == entity) & (self.df.metric == metric)]
        return dict(zip(sub.period, sub.value))

    def entities(self) -> list[str]:
        return sorted(e for e in self.df.entity.unique() if e != US)
