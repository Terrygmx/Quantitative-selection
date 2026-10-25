"""File-backed MarketDataPort adapters: CSV (stdlib) and Parquet (pyarrow,
optional). Parsing must fail closed with row-level diagnostics."""

import csv
import os
import tempfile
from datetime import datetime, timezone

import pytest

from quant_agent.adapters.market_data import (
    CsvMarketDataPort,
    DataUnavailable,
    ParquetMarketDataPort,
)


AS_OF = datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc)


def write_csv(rows, header=None):
    if header is None:
        header = [
            "instrument",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "available_at",
        ]
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def sample_row(**overrides):
    row = [
        "sh600519",
        "2026-09-15T14:30:00+00:00",
        "10.0",
        "10.2",
        "9.9",
        "10.1",
        "1000.0",
        "2026-09-15T14:30:00+00:00",
    ]
    for index, value in overrides.items():
        row[int(index)] = value
    return row


def test_csv_port_loads_bars_and_serves_pit_queries():
    port = CsvMarketDataPort(write_csv([sample_row()]))

    bars = port.bars("sh600519", AS_OF)

    assert len(bars) == 1
    assert bars[0].close == pytest.approx(10.1)
    assert bars[0].amount == 0.0


def test_csv_port_fails_closed_on_missing_file(tmp_path):
    with pytest.raises(ValueError, match="cannot read"):
        CsvMarketDataPort(tmp_path / "missing.csv")


def test_csv_port_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="timezone"):
        CsvMarketDataPort(
            write_csv([sample_row(**{"1": "2026-09-15T14:30:00"})])
        )


def test_csv_port_rejects_malformed_rows_with_row_number():
    with pytest.raises(ValueError, match="row 2"):
        CsvMarketDataPort(write_csv([sample_row(**{"4": "not-a-number"})]))


def test_csv_port_rejects_missing_required_columns():
    with pytest.raises(ValueError, match="column"):
        CsvMarketDataPort(write_csv([sample_row()], header=["instrument", "close"]))


def test_csv_port_raises_data_unavailable_for_unknown_instrument():
    port = CsvMarketDataPort(write_csv([sample_row()]))

    with pytest.raises(DataUnavailable):
        port.bars("sh000001", AS_OF)


def write_parquet(rows):
    pytest.importorskip("pyarrow")
    import pyarrow as pa
    import pyarrow.parquet as pq

    fd, path = tempfile.mkstemp(suffix=".parquet")
    os.close(fd)
    table = pa.table(
        {
            "instrument": [row["instrument"] for row in rows],
            "timestamp": [row["timestamp"] for row in rows],
            "open": [row["open"] for row in rows],
            "high": [row["high"] for row in rows],
            "low": [row["low"] for row in rows],
            "close": [row["close"] for row in rows],
            "volume": [row["volume"] for row in rows],
            "amount": [row.get("amount", 0.0) for row in rows],
            "available_at": [row["available_at"] for row in rows],
        }
    )
    pq.write_table(table, path)
    return path


def parquet_rows():
    return [
        {
            "instrument": "sh600519",
            "timestamp": "2026-09-15T14:30:00+00:00",
            "open": 10.0,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "volume": 1000.0,
            "amount": 10100.0,
            "available_at": "2026-09-15T14:30:00+00:00",
        }
    ]


def test_parquet_port_loads_bars_and_serves_pit_queries():
    port = ParquetMarketDataPort(write_parquet(parquet_rows()))

    bars = port.bars("sh600519", AS_OF)

    assert len(bars) == 1
    assert bars[0].close == pytest.approx(10.1)
    assert bars[0].amount == pytest.approx(10100.0)


def test_parquet_port_fails_closed_on_missing_file(tmp_path):
    pytest.importorskip("pyarrow")

    with pytest.raises(ValueError, match="cannot read"):
        ParquetMarketDataPort(tmp_path / "missing.parquet")
