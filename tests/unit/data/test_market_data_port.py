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


def test_quality_event_collector_validates_and_partitions_levels(tmp_path):
    from quant_agent.adapters.market_data import QualityEvent, QualityEventCollector

    collector = QualityEventCollector()
    warn = QualityEvent("warn", "LATE_DATA", "sh600519", AS_OF, "late")
    passed = QualityEvent("pass", "DATA_AVAILABLE", "sh600519", AS_OF, "available")

    collector.record(warn)
    collector.record(passed)

    assert collector.by_level() == {"pass": [passed], "warn": [warn]}
    with pytest.raises(ValueError, match="quality level"):
        collector.record(
            QualityEvent("invalid", "BAD_LEVEL", "sh600519", AS_OF, "invalid")
        )


def test_quality_events_persist_as_jsonl(tmp_path):
    import json
    import os

    from quant_agent.adapters.market_data import QualityEvent, QualityEventCollector

    path = os.path.join(tmp_path, "quality.jsonl")
    collector = QualityEventCollector(persist_path=path)
    event = QualityEvent("warn", "LATE_DATA", "sh600519", AS_OF, "late data")

    collector.record(event)

    with open(path, encoding="utf-8") as output:
        persisted = json.loads(output.read())
    assert persisted == {
        "level": "warn",
        "reason_code": "LATE_DATA",
        "symbol": "sh600519",
        "as_of": AS_OF.isoformat(),
        "message": "late data",
    }


def test_quality_events_are_isolated_by_strategy(tmp_path):
    import os

    from quant_agent.adapters.market_data import QualityEvent, QualityEventCollector

    path = os.path.join(tmp_path, "quality.jsonl")
    collector = QualityEventCollector(persist_path=path)
    tail = QualityEvent("warn", "LATE_DATA", "sh600519", AS_OF, "tail")
    risk = QualityEvent("pass", "DATA_AVAILABLE", "sh600519", AS_OF, "risk")

    collector.record(tail, strategy_id="tail_momentum_overnight")
    collector.record(risk, strategy_id="risk_review")

    tail_events = collector.for_strategy("tail_momentum_overnight")
    assert len(tail_events) == 1
    assert tail_events[0].strategy_id == "tail_momentum_overnight"
    assert tail_events[0].reason_code == "LATE_DATA"
    risk_events = collector.for_strategy("risk_review")
    assert len(risk_events) == 1
    assert risk_events[0].strategy_id == "risk_review"
    assert risk_events[0].reason_code == "DATA_AVAILABLE"
    assert collector.for_strategy("unknown") == []


def test_record_once_and_run_scoped_blocked_strategies():
    from quant_agent.adapters.market_data import QualityEvent, QualityEventCollector

    collector = QualityEventCollector()
    first = QualityEvent(
        "block",
        "MISSING_REQUIRED_BAR",
        "sh600519",
        AS_OF,
        "missing",
    )

    with collector.strategy_scope("first"):
        assert collector.record_once(first, since=0) is True
        assert collector.record_once(first, since=0) is False
        assert collector.record_once(first, since=1) is True

    second = QualityEvent(
        "warn",
        "STALE_QUOTE",
        "sh600519",
        AS_OF,
        "stale",
    )
    collector.record(second, strategy_id="second")

    assert len(collector.events) == 3
    assert collector.blocked_strategy_ids() == {"first"}
    assert collector.blocked_strategy_ids((second,)) == set()
