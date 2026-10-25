"""File-based external calendar source: 2027+ trading days are supplied as a
data file because those holidays are not published in the static dataset."""

from datetime import date

import pytest

from quant_agent.adapters.calendar import FileCalendarSource
from quant_agent.rules.calendar import StaticTradingCalendar


def test_loads_trading_days_from_file(tmp_path):
    path = tmp_path / "trading-days-2027.txt"
    path.write_text(
        "# SSE/SZSE trading days for 2027 (external dataset)\n"
        "2027-01-04\n"
        "2027-01-05\n"
        "2027-01-06\n",
        encoding="utf-8",
    )

    calendar = FileCalendarSource(path).load()

    assert isinstance(calendar, StaticTradingCalendar)
    assert calendar.is_trading_day(date(2027, 1, 4))
    assert calendar.next_trading_day(date(2027, 1, 4)) == date(2027, 1, 5)


def test_extends_builtin_calendar_with_external_years(tmp_path):
    path = tmp_path / "trading-days-2027.txt"
    path.write_text("2027-01-04\n2027-01-05\n", encoding="utf-8")

    calendar = FileCalendarSource(path).extend_builtin()

    assert calendar.is_trading_day(date(2026, 9, 30))
    assert calendar.is_trading_day(date(2027, 1, 4))
    assert not calendar.is_trading_day(date(2027, 1, 9))


def test_empty_source_file_fails_closed(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("# only comments\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no trading days"):
        FileCalendarSource(path).load()


def test_missing_source_file_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="cannot read calendar source"):
        FileCalendarSource(tmp_path / "missing.txt").load()
