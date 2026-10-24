from datetime import datetime, timezone

import pytest

from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort


AS_OF = datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 15, 14, 31, tzinfo=timezone.utc)
EARLIER = datetime(2026, 9, 15, 9, 30, tzinfo=timezone.utc)


def bar(timestamp, close=10.0, available_at=None):
    return Bar(
        instrument="sh600519",
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100.0,
        available_at=available_at or timestamp,
    )


def test_bars_as_of_exclude_later_timestamps_and_revisions():
    visible = bar(AS_OF)
    port = InMemoryMarketDataPort(
        bars=[
            visible,
            bar(LATER),
            bar(EARLIER, close=9.5, available_at=LATER),
        ]
    )

    result = port.bars("sh600519", as_of=AS_OF)

    assert [item.timestamp for item in result] == [AS_OF]
    assert result[0].available_at <= AS_OF


def test_bar_rejects_availability_before_timestamp():
    with pytest.raises(ValueError, match="available_at"):
        bar(LATER, available_at=EARLIER)


def test_missing_required_bars_emit_block_quality_event():
    port = InMemoryMarketDataPort(bars=[])

    with pytest.raises(port.DataUnavailable) as exc_info:
        port.bars("sh600519", as_of=AS_OF)

    event = exc_info.value.event
    assert event.level == "block"
    assert event.reason_code == "MISSING_REQUIRED_BAR"
    assert event.symbol == "sh600519"
    assert event.as_of == AS_OF


def test_latest_visible_revision_wins_for_same_timestamp():
    original = bar(EARLIER, close=9.0)
    correction_before_snapshot = bar(EARLIER, close=9.1, available_at=AS_OF)
    correction_after_snapshot = bar(EARLIER, close=99.0, available_at=LATER)
    port = InMemoryMarketDataPort(
        [original, correction_before_snapshot, correction_after_snapshot]
    )

    result = port.bars("sh600519", as_of=AS_OF)

    assert [item.close for item in result] == [9.1]


def test_quality_event_collector_records_block_event(tmp_path):
    from quant_agent.adapters.market_data import QualityEventCollector

    collector = QualityEventCollector()
    port = InMemoryMarketDataPort(bars=[], quality_events=collector)

    with pytest.raises(port.DataUnavailable):
        port.bars("sh600519", as_of=AS_OF)

    assert len(collector.events) == 1
    assert collector.events[0].reason_code == "MISSING_REQUIRED_BAR"
