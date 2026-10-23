"""Download public financial data: FRED macro series and SEC XBRL company facts.

Raw downloads are cached in data/raw/ (git-ignored). `facts.build_facts()` turns them
into the tidy data/facts.csv that is committed, so tests and CI never need the network.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
SEC_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
# The SEC asks automated clients to identify themselves in the User-Agent.
SEC_USER_AGENT = os.environ.get("SEC_USER_AGENT", "finllm-qa research project")

# Public-domain US statistics (BLS, BEA, Federal Reserve, Treasury, EIA) served by FRED.
FRED_SERIES = {
    "CPIAUCSL": "Consumer Price Index, all items (BLS)",
    "CPILFESL": "Consumer Price Index excluding food and energy (BLS)",
    "UNRATE": "Unemployment rate (BLS)",
    "PAYEMS": "Total nonfarm payrolls, thousands (BLS)",
    "FEDFUNDS": "Effective federal funds rate (Federal Reserve)",
    "DGS2": "2-year Treasury constant-maturity yield (Treasury)",
    "DGS10": "10-year Treasury constant-maturity yield (Treasury)",
    "DCOILWTICO": "WTI crude oil spot price, USD per barrel (EIA)",
    "A191RL1Q225SBEA": "Real GDP growth, annualized q/q (BEA)",
}

# Large US issuers with a long XBRL history; CIKs from SEC EDGAR.
COMPANIES = {
    "Apple": 320193,
    "Microsoft": 789019,
    "Alphabet": 1652044,
    "Amazon": 1018724,
    "NVIDIA": 1045810,
    "Meta Platforms": 1326801,
    "Tesla": 1318605,
    "JPMorgan Chase": 19617,
    "Visa": 1403161,
    "Exxon Mobil": 34088,
    "Walmart": 104169,
    "Johnson & Johnson": 200406,
    "Procter & Gamble": 80424,
    "Coca-Cola": 21344,
    "Intel": 50863,
}


def fetch_fred(series: str, refresh: bool = False) -> pd.Series:
    """Return a FRED series as a float Series indexed by date (cached on disk)."""
    path = RAW / f"fred_{series}.csv"
    if refresh or not path.exists():
        resp = requests.get(FRED_URL.format(series=series), timeout=60)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.text, encoding="utf-8")
    df = pd.read_csv(path, parse_dates=["observation_date"], na_values=["."])
    s = df.set_index("observation_date").iloc[:, 0].astype(float).dropna()
    s.name = series
    return s


def fetch_sec(cik: int, refresh: bool = False) -> dict:
    """Return the SEC XBRL `companyfacts` JSON for one issuer (cached on disk)."""
    path = RAW / f"sec_{cik:010d}.json"
    if refresh or not path.exists():
        resp = requests.get(
            SEC_URL.format(cik=cik), headers={"User-Agent": SEC_USER_AGENT}, timeout=60
        )
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.text, encoding="utf-8")
        time.sleep(0.2)  # stay well under the SEC's 10 requests/second limit
    return json.loads(path.read_text(encoding="utf-8"))
