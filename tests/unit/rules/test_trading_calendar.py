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
