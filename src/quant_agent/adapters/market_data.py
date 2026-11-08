from __future__ import annotations

import csv
import importlib
from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from quant_agent.ports.market_data import (  # noqa: F401
    Bar,
    DataUnavailable,
    MarketDataPortLike,
    QualityEvent,
    QualityEventCollector,
)


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

    def __init__(
        self,
        path: str | Path,
        quality_events: QualityEventCollector | None = None,
    ):
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
        self._port = InMemoryMarketDataPort(
            bars,
            quality_events=quality_events,
        )
        self.quality_events = self._port.quality_events

    def bars(self, instrument: str, as_of: datetime) -> list[Bar]:
        return self._port.bars(instrument, as_of)


class ParquetMarketDataPort:
    """MarketDataPort over a Parquet file. pyarrow is an optional dependency
    and imported lazily so the package itself stays stdlib-only."""

    DataUnavailable = DataUnavailable

    def __init__(
        self,
        path: str | Path,
        quality_events: QualityEventCollector | None = None,
    ):
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
        self._port = InMemoryMarketDataPort(
            bars,
            quality_events=quality_events,
        )
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

    def __init__(
        self,
        path: str | Path,
        quality_events: QualityEventCollector | None = None,
    ):
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
        self._port = InMemoryMarketDataPort(
            bars,
            quality_events=quality_events,
        )
        self.quality_events = self._port.quality_events

    def bars(self, instrument: str, as_of: datetime) -> list[Bar]:
        return self._port.bars(instrument, as_of)
