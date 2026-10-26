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


LABOR = Brief("US-labor-2024-05", "labor", "US economy", "2024-05", "2024-04", {
    "unemployment": (3.9, 3.9), "payrolls": (78_000, 64_000)})


def test_audit_regressions(check):
    # a period after a comma or "to" belongs to the next clause, not to this number
    assert check("Payrolls rose by +78,000 jobs in May 2024, while the April change was +64,000 jobs.", LABOR).findings == []
    # an adjective on something the brief does not cover is not a claim about the brief
    assert check("Revenue reached $416.2 billion in fiscal 2025 despite increased costs.", APPLE).findings == []
    # a percentage-point figure attached to job gains is borrowed from the unemployment rate
    unemp = Brief("US-labor-2024-06", "labor", "US economy", "2024-06", "2024-05", {
        "unemployment": (4.1, 3.9), "payrolls": (87_000, 78_000)})
    text = "The nonfarm payroll change saw a gain of 87,000 jobs, representing a 0.20 percentage point increase."
    assert "metric" in errors(check(text, unemp))
    # "increased" when nothing moved
    assert errors(check("Unemployment increased to 3.9% in May 2024.", LABOR)) == ["direction"]


def test_second_audit_regressions(check):
    oct24 = Brief("US-labor-2024-10", "labor", "US economy", "2024-10", "2024-09", {
        "unemployment": (4.1, 4.1), "payrolls": (33_000, 155_000)})
    # "a drop in the payroll change, from A to B" compares two readings
    text = ("There was a significant drop in the monthly nonfarm payroll change, "
            "from +155,000 jobs in September to +33,000 jobs in October.")
    assert check(text, oct24).findings == []
    # "slowing down" is one trend phrase, not "down" said of the level
    assert check("Nonfarm payrolls added 33,000 jobs, with job growth slowing down.", oct24).findings == []
    # a slowdown in the labor market says nothing about which way the unemployment rate moved
    feb26 = Brief("US-labor-2026-02", "labor", "US economy", "2026-02", "2026-01", {
        "unemployment": (4.4, 4.3), "payrolls": (-156_000, 160_000)})
    text = "The unemployment rate rose to 4.40% from 4.30%, signaling a potential slowdown in the labor market."
    assert check(text, feb26).findings == []
    # a period after "compared to" or "lower than" belongs to the comparison, not to the next number
    fy24 = Brief("Apple-FY2024", "company", "Apple", "FY2024", "FY2023", {
        "revenue": (60_922e6, 26_974e6), "eps": (2.46, 2.47)})
    assert check("Revenue rose 126% compared to fiscal 2023, reaching USD 60,922 million.", fy24).findings == []
    assert check("Diluted EPS was USD 2.46, slightly lower than the USD 2.47 in fiscal 2023.", fy24).findings == []
    # "dipped" is a direction word
    assert errors(check("The 10-year Treasury yield dipped slightly to 4.99% from 4.68%.", RATES)) == ["direction"]
