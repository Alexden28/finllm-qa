import pytest

from finllm_qa.briefs import Brief
from finllm_qa.checker import Checker

APPLE = Brief("Apple-FY2025", "company", "Apple", "FY2025", "FY2024", {
    "revenue": (416_161e6, 391_035e6),
    "net_income": (112_010e6, 93_736e6),
    "eps": (7.46, 6.08),
})
CPI = Brief("US-inflation-2026-09", "inflation", "US economy", "2026-09", "2026-08", {
    "inflation": (3.72, 3.35),
    "core_inflation": (2.57, 2.45),
})
RATES = Brief("US-rates-2026-09", "rates", "US economy", "2026-09", "2026-08", {
    "fed_funds": (3.75, 3.63), "yield_2y": (4.65, 4.22), "yield_10y": (4.99, 4.68),
})


@pytest.fixture
def check():
    return Checker().check


def errors(result):
    return sorted(f.error for f in result.findings)


def test_faithful_company_commentary_passes(check):
    text = ("Apple reported revenue of $416.2 billion for fiscal 2025, up 6.4% from $391.0 billion a year earlier. "
            "Net income rose to $112.0 billion, and diluted EPS came in at $7.46 versus $6.08.")
    assert check(text, APPLE).findings == []


def test_derived_numbers_are_accepted(check):
    text = "Apple's revenue grew $25.1bn in fiscal 2025, a net margin of 26.9%, with EPS up 22.7%."
    assert check(text, APPLE).findings == []


@pytest.mark.parametrize("text,expected", [
    ("Apple reported revenue of $461.2 billion for fiscal 2025.", "value"),
    ("Apple reported revenue of $416.2 million for fiscal 2025.", "scale"),
    ("Apple's revenue fell 6.4% in fiscal 2025.", "direction"),
    ("Apple reported revenue of $416.2 billion for fiscal 2023.", "period"),
    ("Apple reported revenue of $416.2 billion for fiscal 2024.", "period"),
    ("Microsoft reported revenue of $416.2 billion for fiscal 2025.", "entity"),
    ("Apple reported net income of $416.2 billion for fiscal 2025.", "metric"),
    ("Revenue rose 6.0% to $416.2 billion in fiscal 2025.", "arithmetic"),
    ("Apple's revenue beat the consensus estimate.", "unsupported"),
])
def test_company_errors(check, text, expected):
    assert expected in errors(check(text, APPLE))


def test_level_vs_change_verbs(check):
    # "consumer prices rose 3.72%" describes the level; "inflation rose to 3.72%" the change.
    assert check("US consumer prices rose 3.72% in the year to September 2026.", CPI).findings == []
    assert check("Inflation rose to 3.72% in September from 3.35% in August.", CPI).findings == []
    assert errors(check("Inflation fell to 3.72% in September.", CPI)) == ["direction"]


def test_respectively_lists_are_not_metric_swaps(check):
    text = "Headline inflation was 3.72% and core 2.57% in September, versus 3.35% and 2.45% in August."
    assert check(text, CPI).findings == []


def test_basis_points_and_units(check):
    assert check("The 10-year yield rose 31 basis points to 4.99% in September 2026.", RATES).findings == []
    assert errors(check("The 10-year yield rose 0.31% to 4.99% in September 2026.", RATES)) == ["unit"]


def test_since_does_not_bind_the_period(check):
    text = "Since August 2026 the 10-year yield has climbed to 4.99%."
    assert check(text, RATES).findings == []


def test_truncation_is_a_rounding_slip(check):
    assert errors(check("Apple's revenue was $416bn and net income $112bn in fiscal 2025.", APPLE)) == []
    assert errors(check("Apple's diluted EPS was $7.4 in fiscal 2025.", APPLE)) == ["rounding"]  # 7.46
    assert errors(check("Apple's revenue was $415 billion in fiscal 2025.", APPLE)) == ["value"]


OIL = Brief("US-oil-2026-04", "oil", "US economy", "2026-04", "2026-03", {"oil": (100.32, 91.38)})


def test_from_to_period_binding(check):
    text = "WTI rose from $91.38 per barrel in March to $100.32 per barrel by April 2026."
    assert check(text, OIL).findings == []


def test_bracketed_abbreviation_restates_the_metric(check):
    text = "The core consumer price index (CPI) inflation rate eased to 2.57% in September 2026 from 2.45%."
    assert errors(check(text, CPI)) == ["direction"]  # core rose 0.12 pp; "eased" is wrong, 2.57% is right
