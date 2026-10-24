from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Bar:
    instrument: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    available_at: datetime

    def __post_init__(self) -> None:
        if self.available_at < self.timestamp:
            raise ValueError("available_at cannot be earlier than timestamp")


@dataclass(frozen=True, slots=True)
class QualityEvent:
    level: str
    reason_code: str
    symbol: str
    as_of: datetime
    message: str


class DataUnavailable(Exception):
    def __init__(self, event: QualityEvent):
        self.event = event
        super().__init__(event.message)


class QualityEventCollector:
    QUALITY_LEVELS = frozenset({"pass", "warn", "block"})

    def __init__(self, persist_path: str | Path | None = None) -> None:
        self.events: list[QualityEvent] = []
        self._events_by_strategy: dict[str, list[QualityEvent]] = {}
        self._persist_path = Path(persist_path) if persist_path is not None else None

    def record(self, event: QualityEvent, strategy_id: str | None = None) -> None:
        if event.level not in self.QUALITY_LEVELS:
            raise ValueError(f"quality level must be one of {sorted(self.QUALITY_LEVELS)}")
        self.events.append(event)
        if strategy_id is not None:
            self._events_by_strategy.setdefault(strategy_id, []).append(event)
        if self._persist_path is not None:
            record = {
                "level": event.level,
                "reason_code": event.reason_code,
                "symbol": event.symbol,
                "as_of": event.as_of.isoformat(),
                "message": event.message,
            }
            if strategy_id is not None:
                record["strategy_id"] = strategy_id
            with self._persist_path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def by_level(self) -> dict[str, list[QualityEvent]]:
        partitioned: dict[str, list[QualityEvent]] = {}
        for event in self.events:
            partitioned.setdefault(event.level, []).append(event)
        return partitioned

    def for_strategy(self, strategy_id: str) -> list[QualityEvent]:
        return list(self._events_by_strategy.get(strategy_id, ()))


class InMemoryMarketDataPort:
    DataUnavailable = DataUnavailable

    def __init__(self, bars: Iterable[Bar], quality_events: QualityEventCollector | None = None):
        self._bars: Mapping[str, list[Bar]] = {}
        self.quality_events = quality_events
        for item in bars:
            self._bars.setdefault(item.instrument, []).append(item)
        for items in self._bars.values():
            items.sort(key=lambda item: (item.timestamp, item.available_at))

    def bars(self, instrument: str, as_of: datetime) -> list[Bar]:
        visible = [
            item
            for item in self._bars.get(instrument, [])
            if item.timestamp <= as_of and item.available_at <= as_of
        ]
        latest_by_timestamp: dict[datetime, Bar] = {}
        for item in visible:
            latest_by_timestamp[item.timestamp] = item
        if not visible:
            event = QualityEvent(
                level="block",
                reason_code="MISSING_REQUIRED_BAR",
                symbol=instrument,
                as_of=as_of,
                message=f"No bar available for {instrument} as of {as_of.isoformat()}",
            )
            if self.quality_events is not None:
                self.quality_events.record(event)
            raise DataUnavailable(event)
        return [latest_by_timestamp[timestamp] for timestamp in sorted(latest_by_timestamp)]
