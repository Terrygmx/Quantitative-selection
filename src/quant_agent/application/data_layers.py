"""Storage layers per DETAILED_DESIGN section 5: Raw archives original
vendor responses immutably by source/date/request-hash; Curated writes
Parquet partitions (one per trade date) with a DuckDB metadata index
carrying lineage (source + request hash) per dataset/date."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class RawRecord:
    source: str
    fetched_at: datetime
    request: str
    content: str


class RawStore:
    """Content-addressed, append-only archive of original responses."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def put(self, record: RawRecord, verify: bool = False) -> Path:
        date_text = record.fetched_at.date().isoformat()
        digest = hashlib.sha256(
            json.dumps(
                {
                    "source": record.source,
                    "fetched_at": record.fetched_at.isoformat(),
                    "request": record.request,
                    "content": record.content,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        target = self.root / record.source / date_text / f"{digest}.json"
        payload = {
            "source": record.source,
            "fetched_at": record.fetched_at.isoformat(),
            "request": record.request,
            "request_hash": digest,
            "content": record.content,
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
        # The path is the content hash: if what is on disk differs, it was
        # tampered with - restore the truth (or refuse, when asked to).
        if target.exists() and target.read_text(encoding="utf-8") == text:
            return target
        if verify and target.exists():
            raise ValueError(
                f"raw record {digest} has been tampered with: {target}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(target)
        return target

    def verify(self, record: RawRecord) -> bool:
        path = self.put(record)
        expected = json.loads(path.read_text(encoding="utf-8"))
        return expected["content"] == record.content


class CuratedStore:
    """Parquet partitions per dataset/date plus a DuckDB metadata index."""

    def __init__(self, root: str | Path, index_path: str | Path):
        self.root = Path(root)
        self.index_path = Path(index_path)

    def write_bars(
        self,
        dataset: str,
        trade_date: str,
        rows: Sequence[Mapping[str, object]],
        source: str = "",
        request_hash: str = "",
    ) -> Path:
        parquet = importlib.import_module("pyarrow.parquet")
        duckdb = importlib.import_module("duckdb")
        partition = self.root / f"dataset={dataset}" / f"trade_date={trade_date}"
        partition.mkdir(parents=True, exist_ok=True)
        path = partition / "data.parquet"
        parquet.write_table(_to_table(rows), path)

        connection = duckdb.connect(str(self.index_path))
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS datasets "
                "(dataset VARCHAR, trade_date VARCHAR, path VARCHAR, "
                "source VARCHAR, request_hash VARCHAR, written_at VARCHAR)"
            )
            connection.execute(
                "DELETE FROM datasets WHERE dataset = ? AND trade_date = ?",
                [dataset, trade_date],
            )
            connection.execute(
                "INSERT INTO datasets VALUES (?, ?, ?, ?, ?, ?)",
                [
                    dataset,
                    trade_date,
                    str(path),
                    source,
                    request_hash,
                    datetime.now().isoformat(),
                ],
            )
        finally:
            connection.close()
        return path

    def read_bars(self, dataset: str) -> list[dict[str, object]]:
        parquet = importlib.import_module("pyarrow.parquet")
        dataset_root = self.root / f"dataset={dataset}"
        if not dataset_root.exists():
            return []
        rows: list[dict[str, object]] = []
        for path in sorted(dataset_root.glob("trade_date=*/data.parquet")):
            table = parquet.read_table(path)
            rows.extend(table.to_pylist())
        return rows


def _to_table(rows: Sequence[Mapping[str, object]]):
    pa = importlib.import_module("pyarrow")
    if not rows:
        return pa.table({})
    columns = {key: [row.get(key) for row in rows] for key in rows[0]}
    return pa.table(columns)
