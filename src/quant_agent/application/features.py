"""Feature registry with definition hashing (DETAILED_DESIGN section 5.4):
every feature name binds to exactly one parameterization; a different
definition may never silently overwrite an existing name. Values are
stamped with their computation moment."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Union


FeatureValue = Union[int, float, str, bool, None]


@dataclass(frozen=True, slots=True)
class FeatureDefinition:
    name: str
    params: Mapping[str, FeatureValue]

    def definition_hash(self) -> str:
        canonical = json.dumps(
            {"name": self.name, "params": dict(self.params)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FeatureStore:
    def __init__(self) -> None:
        self._definitions: dict[str, str] = {}
        self._values: dict[tuple[str, str, datetime], FeatureValue] = {}
        self._stamps: dict[tuple[str, str, datetime], datetime] = {}

    def register(self, definition: FeatureDefinition) -> None:
        digest = definition.definition_hash()
        existing = self._definitions.get(definition.name)
        if existing is not None and existing != digest:
            raise ValueError(
                f"feature {definition.name} is already registered with a "
                "different definition; use a new name"
            )
        self._definitions[definition.name] = digest

    def definition_hash(self, name: str) -> str:
        try:
            return self._definitions[name]
        except KeyError:
            raise KeyError(f"feature {name} is not registered") from None

    def put(
        self,
        name: str,
        symbol: str,
        as_of: datetime,
        value: FeatureValue,
    ) -> None:
        if name not in self._definitions:
            raise ValueError(f"feature {name} is not registered")
        key = (name, symbol, as_of)
        self._values[key] = value
        self._stamps[key] = as_of

    def get(self, name: str, symbol: str, as_of: datetime) -> FeatureValue:
        try:
            return self._values[(name, symbol, as_of)]
        except KeyError:
            raise KeyError(
                f"feature {name} for {symbol} at {as_of.isoformat()} not found"
            ) from None

    def stamp(self, name: str, symbol: str, as_of: datetime) -> datetime:
        return self._stamps[(name, symbol, as_of)]


class PersistentFeatureStore:
    """FeatureStore whose values and definition hashes flush to a Curated
    Parquet partition; load() rebuilds an equivalent in-memory store and
    keeps the definition-lock semantics across processes."""

    def __init__(self, store: FeatureStore, root: str | Path):
        self.store = store
        self.root = Path(root)

    def __getattr__(self, name: str):
        return getattr(self.store, name)

    def flush(self) -> Path:
        """Write values as a Parquet partition plus definitions JSON."""
        parquet = importlib.import_module("pyarrow.parquet")
        self.root.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "feature": name,
                "symbol": symbol,
                "as_of": as_of.isoformat(),
                "value": value,
                "stamp": self.store.stamp(name, symbol, as_of).isoformat(),
            }
            for (name, symbol, as_of), value in sorted(
                self.store._values.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])
            )
        ]
        pa = importlib.import_module("pyarrow")
        table = pa.table(
            {
                "feature": [row["feature"] for row in rows],
                "symbol": [row["symbol"] for row in rows],
                "as_of": [row["as_of"] for row in rows],
                "value": [row["value"] for row in rows],
                "stamp": [row["stamp"] for row in rows],
            }
        )
        path = self.root / "values.parquet"
        parquet.write_table(table, path)
        (self.root / "definitions.json").write_text(
            json.dumps(self.store._definitions, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, root: str | Path) -> "PersistentFeatureStore":
        parquet = importlib.import_module("pyarrow.parquet")
        root_path = Path(root)
        definitions = json.loads(
            (root_path / "definitions.json").read_text(encoding="utf-8")
        )
        store = FeatureStore()
        for name, digest in definitions.items():
            store._definitions[name] = digest
        table = parquet.read_table(root_path / "values.parquet")
        for row in table.to_pylist():
            as_of = datetime.fromisoformat(row["as_of"])
            store._values[(row["feature"], row["symbol"], as_of)] = row["value"]
            store._stamps[(row["feature"], row["symbol"], as_of)] = datetime.fromisoformat(row["stamp"])
        return cls(store, root_path)
