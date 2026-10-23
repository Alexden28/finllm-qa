import pytest

from finllm_qa.numbers import find_numbers, find_periods, matches


@pytest.mark.parametrize("text,kind,value", [
    ("revenue of $416.2 billion", "usd", 416.2e9),
    ("revenue of $416.2bn", "usd", 416.2e9),
    ("USD 391,035 million", "usd", 391_035e6),
    ("EPS of $7.46", "usd", 7.46),
    ("a net loss of $267mn", "usd", 267e6),
    ("inflation of 3.72%", "pct", 3.72),
    ("up 6.4 percent", "pct", 6.4),
    ("rose 25 basis points", "pp", 0.25),
    ("rose 0.37 percentage points", "pp", 0.37),
    ("employers added 151,000 jobs", "count", 151_000),
    ("payrolls rose 151k", "count", 151_000),
])
def test_reads_number_with_unit(text, kind, value):
    (m,) = find_numbers(text)
    assert m.kind == kind
    assert m.value == pytest.approx(value)


def test_years_and_maturities_are_not_numbers():
    assert find_numbers("In fiscal 2025 the 10-year yield and the S&P 500 index; 2025 jobs report") == []


def test_rounding_tolerance_follows_written_precision():
    (m,) = find_numbers("$416.2 billion")
    assert matches(m, 416.161e9)
    assert not matches(m, 416.3e9)
    (m,) = find_numbers("$416 billion")
    assert matches(m, 416.161e9)


def test_hedged_numbers_get_slack():
    (m,) = find_numbers("about $410 billion")
    assert m.hedged and matches(m, 416.161e9)


def test_periods():
    hits = find_periods("In fiscal 2025, versus FY24, and in September 2026 and the third quarter of 2026")
    assert [(h.year, h.month, h.quarter) for h in hits] == [
        (2025, None, None), (2024, None, None), (2026, 9, None), (2026, None, 3)]
