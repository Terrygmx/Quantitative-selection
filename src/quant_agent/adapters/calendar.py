"""External trading-calendar data source.

The static dataset covers 2023-2026 only. Later years (and any correction
to published years) arrive as a data file with one ISO trading day per
line, so the calendar never guesses unpublished holidays."""

from __future__ import annotations

from pathlib import Path

from quant_agent.rules.calendar import StaticTradingCalendar, parse_trading_days


class FileCalendarSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> StaticTradingCalendar:
        """Build a calendar from the file alone."""
        return StaticTradingCalendar(self._parse_days())

    def extend_builtin(self) -> StaticTradingCalendar:
        """Merge the file's days into the 2023-2026 builtin dataset."""
        return StaticTradingCalendar.for_cn_market().union(
            StaticTradingCalendar(self._parse_days())
        )

    def _parse_days(self):
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ValueError(f"cannot read calendar source {self.path}: {exc}") from exc
        return parse_trading_days(lines)
