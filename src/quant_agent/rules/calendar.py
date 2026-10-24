from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


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
        days = set()
        current = date(2024, 1, 1)
        end = date(2024, 12, 31)
        while current <= end:
            if current.weekday() < 5 and current not in holidays:
                days.add(current)
            current += timedelta(days=1)
        return cls(days)
