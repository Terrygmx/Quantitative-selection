from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Protocol


class TradingCalendar(Protocol):
    def is_trading_day(self, day: date) -> bool: ...

    def next_trading_day(self, day: date) -> date | None: ...

    def previous_trading_day(self, day: date) -> date | None: ...


class StaticTradingCalendar:
    def __init__(self, trading_days: Iterable[date]):
        self._days = frozenset(trading_days)

    def is_trading_day(self, day: date) -> bool:
        return day in self._days

    def next_trading_day(self, day: date) -> date | None:
        return self._step(day, timedelta(days=1))

    def previous_trading_day(self, day: date) -> date | None:
        return self._step(day, timedelta(days=-1))

    def _step(self, day: date, delta: timedelta) -> date | None:
        ordered = sorted(self._days)
        if delta > timedelta(0):
            return next((item for item in ordered if item > day), None)
        return next((item for item in reversed(ordered) if item < day), None)

    @classmethod
    def _for_year(cls, year: int, holidays: set[date]) -> "StaticTradingCalendar":
        days = set()
        current = date(year, 1, 1)
        end = date(year, 12, 31)
        while current <= end:
            if current.weekday() < 5 and current not in holidays:
                days.add(current)
            current += timedelta(days=1)
        return cls(days)

    @classmethod
    def for_sse_2023(cls) -> "StaticTradingCalendar":
        holidays = {
            date(2023, 1, 2),
            date(2023, 1, 23),
            date(2023, 1, 24),
            date(2023, 1, 25),
            date(2023, 1, 26),
            date(2023, 1, 27),
            date(2023, 4, 5),
            date(2023, 5, 1),
            date(2023, 5, 2),
            date(2023, 5, 3),
            date(2023, 6, 22),
            date(2023, 6, 23),
            date(2023, 9, 29),
            date(2023, 10, 2),
            date(2023, 10, 3),
            date(2023, 10, 4),
            date(2023, 10, 5),
            date(2023, 10, 6),
        }
        return cls._for_year(2023, holidays)

    @classmethod
    def for_sse_2024(cls) -> "StaticTradingCalendar":
        holidays = {
            date(2024, 1, 1),
            date(2024, 2, 9),
            date(2024, 2, 15),
            date(2024, 2, 16),
            date(2024, 4, 4),
            date(2024, 4, 5),
            date(2024, 5, 1),
            date(2024, 5, 2),
            date(2024, 5, 3),
            date(2024, 6, 10),
            date(2024, 9, 16),
            date(2024, 9, 17),
            date(2024, 10, 1),
            date(2024, 10, 2),
            date(2024, 10, 3),
            date(2024, 10, 4),
            date(2024, 10, 7),
        }
        return cls._for_year(2024, holidays)

    @classmethod
    def for_sse_2025(cls) -> "StaticTradingCalendar":
        holidays = {
            date(2025, 1, 1),
            date(2025, 1, 28),
            date(2025, 1, 29),
            date(2025, 1, 30),
            date(2025, 1, 31),
            date(2025, 2, 3),
            date(2025, 2, 4),
            date(2025, 4, 4),
            date(2025, 5, 1),
            date(2025, 5, 2),
            date(2025, 5, 5),
            date(2025, 6, 2),
            date(2025, 10, 1),
            date(2025, 10, 2),
            date(2025, 10, 3),
            date(2025, 10, 6),
            date(2025, 10, 7),
        }
        return cls._for_year(2025, holidays)

    @classmethod
    def for_sse(cls) -> "StaticTradingCalendar":
        calendars = (cls.for_sse_2023(), cls.for_sse_2024(), cls.for_sse_2025())
        return cls(
            day
            for calendar in calendars
            for day in calendar._days
        )
