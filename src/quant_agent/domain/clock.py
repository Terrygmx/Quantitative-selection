from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current timezone-aware datetime."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    def __init__(self, current_time: datetime):
        if current_time.tzinfo is None:
            raise ValueError("clock time must be timezone-aware")
        self.current_time = current_time

    def now(self) -> datetime:
        return self.current_time
