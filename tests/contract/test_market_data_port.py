from datetime import datetime, timezone
import csv
import os
import tempfile

import pytest

from quant_agent.adapters.market_data import (
    Bar,
    CsvMarketDataPort,
    DataUnavailable,
    InMemoryMarketDataPort,
    ParquetMarketDataPort,
)


AS_OF = datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 15, 14, 31, tzinfo=timezone.utc)


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


def _csv_port(bars):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "instrument",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "available_at",
            ]
        )
        for item in bars:
            writer.writerow(
                [
                    item.instrument,
                    item.timestamp.isoformat(),
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.volume,
                    item.amount,
                    item.available_at.isoformat(),
                ]
            )
    return CsvMarketDataPort(path)


def _parquet_port(bars):
    pytest.importorskip("pyarrow")
    import pyarrow as pa
    import pyarrow.parquet as pq

    fd, path = tempfile.mkstemp(suffix=".parquet")
    os.close(fd)
    table = pa.table(
        {
            "instrument": [item.instrument for item in bars],
            "timestamp": [item.timestamp.isoformat() for item in bars],
            "open": [item.open for item in bars],
            "high": [item.high for item in bars],
            "low": [item.low for item in bars],
            "close": [item.close for item in bars],
            "volume": [item.volume for item in bars],
            "amount": [item.amount for item in bars],
            "available_at": [item.available_at.isoformat() for item in bars],
        }
    )
    pq.write_table(table, path)
    return ParquetMarketDataPort(path)


def _duckdb_port(bars):
    pytest.importorskip("duckdb")
    import duckdb

    from quant_agent.adapters.market_data import DuckDBMarketDataPort

    fd, path = tempfile.mkstemp(suffix=".duckdb")
    os.close(fd)
    os.unlink(path)
    connection = duckdb.connect(path)
    connection.execute(
        """
        CREATE TABLE bars (
            instrument VARCHAR,
            timestamp TIMESTAMPTZ,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            amount DOUBLE,
            available_at TIMESTAMPTZ
        )
        """
    )
    for item in bars:
        connection.execute(
            "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                item.instrument,
                item.timestamp,
                item.open,
                item.high,
                item.low,
                item.close,
                item.volume,
                item.amount,
                item.available_at,
            ],
        )
    connection.close()
    return DuckDBMarketDataPort(path)


@pytest.mark.parametrize(
    "make_port",
    [
        lambda bars: InMemoryMarketDataPort(bars),
        _csv_port,
        _parquet_port,
        _duckdb_port,
    ],
    ids=["in-memory", "csv", "parquet", "duckdb"],
)
class TestMarketDataPortContract:
    def test_excludes_future_and_unavailable_bars(self, make_port):
        port = make_port([bar(AS_OF), bar(LATER), bar(AS_OF, available_at=LATER)])

        assert [item.timestamp for item in port.bars("sh600519", AS_OF)] == [AS_OF]

    def test_latest_visible_revision_wins(self, make_port):
        port = make_port(
            [
                bar(AS_OF, close=9.0),
                bar(AS_OF, close=9.1, available_at=AS_OF),
                bar(AS_OF, close=99.0, available_at=LATER),
            ]
        )

        assert [item.close for item in port.bars("sh600519", AS_OF)] == [9.1]

    def test_missing_required_bar_fails_closed(self, make_port):
        port = make_port([])

        with pytest.raises(DataUnavailable):
            port.bars("sh600519", AS_OF)
