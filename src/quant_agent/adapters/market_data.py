from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
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
    def __init__(self) -> None:
        self.events: list[QualityEvent] = []

    def record(self, event: QualityEvent) -> None:
        self.events.append(event)


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
