from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class MarketDataPort(Protocol):
    """Point-in-time market data consumed by strategies and use cases."""

    def bars(self, instrument: str, as_of: datetime) -> list["Bar"]: ...


MarketDataPortLike = MarketDataPort


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
    amount: float = 0.0
    adjustment: str = "raw"

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
    strategy_id: str | None = None

    def __post_init__(self) -> None:
        if self.level not in {"pass", "warn", "block"}:
            raise ValueError(
                "quality level must be one of ['block', 'pass', 'warn']"
            )
        if self.as_of.tzinfo is None:
            raise ValueError("quality event as_of must be timezone-aware")
        if self.strategy_id is not None and not self.strategy_id.strip():
            raise ValueError("quality event strategy_id must be non-empty")


class DataUnavailable(Exception):
    def __init__(self, event: QualityEvent):
        self.event = event
        super().__init__(event.message)


class QualityEventCollector:
    QUALITY_LEVELS = frozenset({"pass", "warn", "block"})

    def __init__(self, persist_path: str | Path | None = None) -> None:
        self.events: list[QualityEvent] = []
        self._events_by_strategy: dict[str, list[QualityEvent]] = {}
        self._persist_path = (
            Path(persist_path) if persist_path is not None else None
        )
        self._active_strategy_id: str | None = None

    @contextmanager
    def strategy_scope(self, strategy_id: str) -> Iterator[None]:
        previous = self._active_strategy_id
        self._active_strategy_id = strategy_id
        try:
            yield
        finally:
            self._active_strategy_id = previous

    def _with_strategy(
        self,
        event: QualityEvent,
        strategy_id: str | None = None,
    ) -> QualityEvent:
        attributed = self._active_strategy_id or strategy_id
        if attributed and event.strategy_id != attributed:
            return replace(event, strategy_id=attributed)
        return event

    def record(
        self,
        event: QualityEvent,
        strategy_id: str | None = None,
    ) -> QualityEvent:
        if event.level not in self.QUALITY_LEVELS:
            raise ValueError(
                f"quality level must be one of {sorted(self.QUALITY_LEVELS)}"
            )
        event = self._with_strategy(event, strategy_id)
        self.events.append(event)
        if event.strategy_id is not None:
            self._events_by_strategy.setdefault(
                event.strategy_id, []
            ).append(event)
        if self._persist_path is not None:
            record: dict[str, object] = {
                "level": event.level,
                "reason_code": event.reason_code,
                "symbol": event.symbol,
                "as_of": event.as_of.isoformat(),
                "message": event.message,
            }
            if event.strategy_id is not None:
                record["strategy_id"] = event.strategy_id
            with self._persist_path.open("a", encoding="utf-8") as output:
                output.write(
                    json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                )
        return event

    def record_once(
        self,
        event: QualityEvent,
        strategy_id: str | None = None,
        *,
        since: int,
    ) -> bool:
        """Record an event unless it already exists at or after ``since``."""
        attributed = self._with_strategy(event, strategy_id)
        if attributed in self.events[since:]:
            return False
        self.record(attributed)
        return True

    def by_level(self) -> dict[str, list[QualityEvent]]:
        partitioned: dict[str, list[QualityEvent]] = {}
        for event in self.events:
            partitioned.setdefault(event.level, []).append(event)
        return partitioned

    def for_strategy(self, strategy_id: str) -> list[QualityEvent]:
        return list(self._events_by_strategy.get(strategy_id, ()))

    def blocked_strategy_ids(
        self,
        events: Iterable[QualityEvent] | None = None,
    ) -> set[str]:
        source = self.events if events is None else events
        return {
            event.strategy_id
            for event in source
            if event.level == "block" and event.strategy_id is not None
        }
