"""Data layers per DETAILED_DESIGN section 5: Raw stores original responses
by source/date/request-hash and is immutable; Curated writes Parquet
partitions with a DuckDB metadata index; every artifact carries lineage."""

import json
from datetime import datetime, timezone

import pytest

from quant_agent.application.data_layers import (
    CuratedStore,
    RawStore,
    RawRecord,
)


def record(source="westock", request="/kline sh600519"):
    return RawRecord(
        source=source,
        fetched_at=datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc),
        request=request,
        content="| date | last |\n| --- | --- |\n| 2026-09-15 | 47.09 |\n",
    )


def test_raw_store_archives_by_source_date_and_request_hash(tmp_path):
    store = RawStore(tmp_path / "raw")

    path = store.put(record())

    assert path.exists()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["source"] == "westock"
    assert stored["fetched_at"] == "2026-09-15T14:30:00+00:00"
    assert "2026-09-15" in str(path)
    assert "westock" in path.parts and path.parent.name == "2026-09-15"


def test_raw_store_is_content_addressed_and_idempotent(tmp_path):
    store = RawStore(tmp_path / "raw")

    first = store.put(record())
    second = store.put(record())
    first.write_text("tampered", encoding="utf-8")

    third = store.put(record())

    # Same content hashes to the same object; rewriting restores the truth.
    assert first == second == third
    assert json.loads(third.read_text(encoding="utf-8"))["content"].startswith("| date |")


def test_raw_store_refuses_overwrite_detection_bypass(tmp_path):
    store = RawStore(tmp_path / "raw")

    path = store.put(record())
    path.write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="tampered"):
        store.put(record(), verify=True)


def test_curated_store_writes_parquet_partition_per_day(tmp_path):
    pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    store = CuratedStore(tmp_path / "curated", index_path=tmp_path / "meta.duckdb")

    path = store.write_bars(
        dataset="kline_daily",
        trade_date="2026-09-15",
        rows=[
            {
                "instrument": "sh600519",
                "timestamp": "2026-09-15T15:00:00+08:00",
                "open": 45.19,
                "close": 47.09,
            }
        ],
    )

    assert path.exists()
    table = pq.read_table(path)
    assert table.column("close").to_pylist() == [47.09]
    assert "trade_date=2026-09-15" in str(path)


def test_curated_metadata_index_records_lineage(tmp_path):
    pytest.importorskip("duckdb")
    import duckdb

    store = CuratedStore(tmp_path / "curated", index_path=tmp_path / "meta.duckdb")

    store.write_bars(
        dataset="kline_daily",
        trade_date="2026-09-15",
        rows=[{"instrument": "sh600519", "close": 47.09}],
        source="westock",
        request_hash="abc123",
    )

    connection = duckdb.connect(str(tmp_path / "meta.duckdb"), read_only=True)
    rows = connection.execute(
        "SELECT dataset, trade_date, source, request_hash FROM datasets"
    ).fetchall()
    connection.close()
    assert rows == [("kline_daily", "2026-09-15", "westock", "abc123")]


def test_curated_read_rebuilds_a_dataset_from_parquet(tmp_path):
    pytest.importorskip("pyarrow")
    store = CuratedStore(tmp_path / "curated", index_path=tmp_path / "meta.duckdb")

    store.write_bars(
        dataset="kline_daily",
        trade_date="2026-09-15",
        rows=[{"instrument": "sh600519", "close": 47.09}],
    )
    store.write_bars(
        dataset="kline_daily",
        trade_date="2026-09-16",
        rows=[{"instrument": "sh600519", "close": 48.0}],
    )

    rows = store.read_bars("kline_daily")

    assert sorted(row["close"] for row in rows) == [47.09, 48.0]
