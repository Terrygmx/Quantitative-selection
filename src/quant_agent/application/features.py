"""Feature registry with definition hashing (DETAILED_DESIGN section 5.4):
every feature name binds to exactly one parameterization; a different
definition may never silently overwrite an existing name. Values are
stamped with their computation moment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
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
