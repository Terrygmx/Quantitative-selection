from datetime import date

import pytest

from quant_agent.rules.calendar import StaticTradingCalendar


def test_calendar_uses_explicit_trading_days_only():
    trading_days = {
        date(2024, 1, 1),
        date(2024, 1, 2),
        date(2024, 1, 3),
    }
    calendar = StaticTradingCalendar(trading_days)

    assert calendar.is_trading_day(date(2024, 1, 1))
    assert calendar.next_trading_day(date(2024, 1, 1)) == date(2024, 1, 2)
    assert calendar.previous_trading_day(date(2024, 1, 3)) == date(2024, 1, 2)


def test_calendar_ignores_weekend_assumption_when_explicit_day_exists():
    calendar = StaticTradingCalendar({date(2024, 1, 6)})

    assert calendar.is_trading_day(date(2024, 1, 6))
    assert calendar.next_trading_day(date(2024, 1, 6)) is None


def test_calendar_returns_none_at_boundaries():
    calendar = StaticTradingCalendar({date(2024, 1, 2)})

    assert calendar.previous_trading_day(date(2024, 1, 2)) is None
    assert calendar.next_trading_day(date(2024, 1, 2)) is None


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2024, 1, 1), False),
        (date(2024, 1, 2), True),
        (date(2024, 2, 8), True),
        (date(2024, 2, 10), False),
        (date(2024, 2, 18), False),
        (date(2024, 12, 31), True),
    ],
)
def test_builtin_sse_calendar_holidays_keep_weekends_closed(day, expected):
    calendar = StaticTradingCalendar.for_sse_2024()

    assert calendar.is_trading_day(day) is expected


def test_trading_rules_use_calendar_not_weekend_approximation():
    from decimal import Decimal

    from quant_agent.domain.models import Instrument
    from quant_agent.rules.trading import TradingRulesPlugin

    calendar = StaticTradingCalendar.for_sse_2024()
    plugin = TradingRulesPlugin(calendar)

    assert plugin.price_limits(
        Instrument(
            symbol="sh688001",
            exchange="SSE",
            board="STAR",
            status="Active",
            listing_date=date(2024, 2, 5),
            tick=Decimal("0.01"),
            lot_size=100,
        ),
        Decimal("10.00"),
        date(2024, 2, 8),
    ) is None


def test_builtin_sse_calendar_spans_multiple_years_and_cross_year_boundaries():
    calendar = StaticTradingCalendar.for_sse()

    for day in (date(2023, 1, 3), date(2024, 1, 2), date(2025, 1, 2)):
        assert calendar.is_trading_day(day)
    assert calendar.next_trading_day(date(2024, 12, 31)) == date(2025, 1, 2)
    assert calendar.previous_trading_day(date(2024, 1, 2)) == date(2023, 12, 29)
    assert not calendar.is_trading_day(date(2023, 1, 1))
    assert not calendar.is_trading_day(date(2025, 10, 1))


def test_calendar_protocol_is_replaceable():
    class WeekdayCalendar:
        def is_trading_day(self, day):
            return day.weekday() < 5

        def next_trading_day(self, day):
            return None

        def previous_trading_day(self, day):
            return None

    from quant_agent.rules.trading import TradingRulesPlugin

    plugin = TradingRulesPlugin(WeekdayCalendar())
    assert plugin._is_trading_day(date(2024, 2, 12))


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 1, 1), False),
        (date(2026, 1, 2), False),
        (date(2026, 1, 5), True),
        (date(2026, 2, 13), True),
        (date(2026, 2, 16), False),
        (date(2026, 2, 20), False),
        # SSE 2026 closure announcement: Spring Festival closes Feb 15-23,
        # trading resumes Feb 24 (verified online 2026-10-25).
        (date(2026, 2, 23), False),
        (date(2026, 2, 24), True),
        (date(2026, 4, 3), True),
        (date(2026, 4, 6), False),
        (date(2026, 4, 7), True),
        (date(2026, 5, 1), False),
        (date(2026, 5, 4), False),
        (date(2026, 5, 5), False),
        (date(2026, 6, 19), False),
        (date(2026, 9, 25), False),
        (date(2026, 10, 1), False),
        (date(2026, 10, 7), False),
        (date(2026, 10, 8), True),
    ],
)
def test_builtin_calendar_covers_2026_holidays(day, expected):
    calendar = StaticTradingCalendar.for_cn_market()

    assert calendar.is_trading_day(day) is expected


def test_builtin_calendar_is_shared_by_sse_and_szse():
    from quant_agent.rules.calendar import StaticTradingCalendar

    sse = StaticTradingCalendar.for_exchange("SSE")
    szse = StaticTradingCalendar.for_exchange("SZSE")

    assert sse._days == szse._days
    # 2023-2026: both exchanges close on National Day and reopen on the following workday.
    assert not sse.is_trading_day(date(2023, 10, 2))
    assert sse.next_trading_day(date(2026, 9, 30)) == date(2026, 10, 8)
    assert szse.next_trading_day(date(2026, 9, 30)) == date(2026, 10, 8)


def test_parse_trading_days_accepts_one_iso_date_per_line():
    from quant_agent.rules.calendar import parse_trading_days

    days = parse_trading_days(
        [
            "2027-01-04",
            "",
            "# comment line",
            "  2027-01-05  ",
        ]
    )

    assert days == frozenset({date(2027, 1, 4), date(2027, 1, 5)})


def test_parse_trading_days_rejects_invalid_lines_with_line_number():
    from quant_agent.rules.calendar import parse_trading_days

    with pytest.raises(ValueError, match="line 3"):
        parse_trading_days(["2027-01-04", "", "not-a-date"])


def test_parse_trading_days_fails_closed_on_empty_dataset():
    from quant_agent.rules.calendar import parse_trading_days

    with pytest.raises(ValueError, match="no trading days"):
        parse_trading_days(["", "# nothing"])


def test_union_merges_builtin_years_with_external_2027_days():
    from quant_agent.rules.calendar import parse_trading_days

    builtin = StaticTradingCalendar.for_cn_market()
    external_2027 = StaticTradingCalendar(
        parse_trading_days(["2027-01-04", "2027-01-05"])
    )

    merged = builtin.union(external_2027)

    assert merged.is_trading_day(date(2026, 9, 30))
    assert merged.is_trading_day(date(2027, 1, 4))
    # Boundary navigation crosses the merged year.
    assert merged.next_trading_day(date(2026, 12, 31)) == date(2027, 1, 4)
    assert merged.previous_trading_day(date(2027, 1, 4)) == date(2026, 12, 31)
    # Non-holiday weekend in 2027 stays closed because only supplied days trade.
    assert not merged.is_trading_day(date(2027, 1, 9))
