from __future__ import annotations

import csv
import importlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Mapping, Protocol


class MarketDataPortLike(Protocol):
    """Structural PIT port surface used by agent role tools."""

    def bars(self, instrument: str, as_of: datetime) -> list[Bar]: ...


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

    def blocked_strategy_ids(self) -> set[str]:
        """Strategy ids with at least one block-level event: the set the
        portfolio layer must exclude (FR-2.3/FR-3 data-quality gate)."""
        return {
            strategy_id
            for strategy_id, events in self._events_by_strategy.items()
            if any(event.level == "block" for event in events)
        }


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


REQUIRED_BAR_COLUMNS: tuple[str, ...] = (
    "instrument",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)


def _to_float(value: object) -> float:
    if isinstance(value, (str, int, float, Decimal)):
        return float(value)
    raise ValueError(f"not a number: {value!r}")


def _bar_from_row(row: Mapping[str, object], origin: str, number: int) -> Bar:
    try:
        timestamp = datetime.fromisoformat(str(row["timestamp"]))
        raw_available = row.get("available_at")
        available_at = (
            datetime.fromisoformat(str(raw_available))
            if raw_available not in (None, "")
            else timestamp
        )
        if timestamp.tzinfo is None or available_at.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return Bar(
            instrument=str(row["instrument"]),
            timestamp=timestamp,
            open=_to_float(row["open"]),
            high=_to_float(row["high"]),
            low=_to_float(row["low"]),
            close=_to_float(row["close"]),
            volume=_to_float(row["volume"]),
            available_at=available_at,
            amount=_to_float(row.get("amount") or 0.0),
        )
    except KeyError as exc:
        raise ValueError(
            f"{origin} row {number} is missing column: {exc.args[0]}"
        ) from exc
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{origin} row {number} is invalid: {exc}") from exc


class CsvMarketDataPort:
    """MarketDataPort over a CSV file; PIT semantics are delegated to the
    in-memory store so file adapters cannot diverge from the contract."""

    DataUnavailable = DataUnavailable

    def __init__(self, path: str | Path):
        self.path = Path(path)
        try:
            with self.path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                headers = reader.fieldnames or []
                missing = [
                    column for column in REQUIRED_BAR_COLUMNS if column not in headers
                ]
                if missing:
                    raise ValueError(
                        f"missing required column(s): {', '.join(missing)}"
                    )
                bars = [
                    _bar_from_row(row, "csv", number)
                    for number, row in enumerate(reader, start=2)
                ]
        except OSError as exc:
            raise ValueError(f"cannot read {self.path}: {exc}") from exc
        self._port = InMemoryMarketDataPort(bars)
        self.quality_events = self._port.quality_events

    def bars(self, instrument: str, as_of: datetime) -> list[Bar]:
        return self._port.bars(instrument, as_of)


class ParquetMarketDataPort:
    """MarketDataPort over a Parquet file. pyarrow is an optional dependency
    and imported lazily so the package itself stays stdlib-only."""

    DataUnavailable = DataUnavailable

    def __init__(self, path: str | Path):
        try:
            parquet = importlib.import_module("pyarrow.parquet")
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ValueError(
                "ParquetMarketDataPort requires the optional pyarrow package"
            ) from exc
        self.path = Path(path)
        try:
            table = parquet.read_table(self.path)
        except OSError as exc:
            raise ValueError(f"cannot read {self.path}: {exc}") from exc
        rows: Sequence[Mapping[str, object]] = table.to_pylist()
        bars = [_bar_from_row(row, "parquet", index) for index, row in enumerate(rows, start=1)]
        self._port = InMemoryMarketDataPort(bars)
        self.quality_events = self._port.quality_events

    def bars(self, instrument: str, as_of: datetime) -> list[Bar]:
        return self._port.bars(instrument, as_of)


class DuckDBMarketDataPort:
    """MarketDataPort over a DuckDB database file holding a `bars` table
    (TIMESTAMPTZ columns). duckdb is an optional dependency imported
    lazily; every read error fails closed."""

    DataUnavailable = DataUnavailable

    _COLUMNS: tuple[str, ...] = (
        "instrument",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "available_at",
    )

    def __init__(self, path: str | Path):
        try:
            duckdb = importlib.import_module("duckdb")
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ValueError(
                "DuckDBMarketDataPort requires the optional duckdb package"
            ) from exc
        self.path = Path(path)
        columns = self._COLUMNS
        try:
            connection = duckdb.connect(str(self.path), read_only=True)
            try:
                rows = connection.execute(
                    f"SELECT {', '.join(columns)} FROM bars"
                ).fetchall()
            finally:
                connection.close()
        except (OSError, duckdb.Error) as exc:
            raise ValueError(f"cannot read {self.path}: {exc}") from exc
        bars = [
            _bar_from_row(dict(zip(columns, row)), "duckdb", index)
            for index, row in enumerate(rows, start=1)
        ]
        self._port = InMemoryMarketDataPort(bars)
        self.quality_events = self._port.quality_events

    def bars(self, instrument: str, as_of: datetime) -> list[Bar]:
        return self._port.bars(instrument, as_of)
