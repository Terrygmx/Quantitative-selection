from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class StrategyMetadata:
    strategy_id: str
    version: str
    frequency: str


class StrategyRegistry:
    def __init__(self):
        self._strategies: dict[str, object] = {}

    def register(self, strategy) -> None:
        metadata = getattr(strategy, "metadata", None)
        if metadata is None or not getattr(metadata, "strategy_id", ""):
            raise ValueError("strategy metadata with strategy_id is required")
        if metadata.strategy_id in self._strategies:
            raise ValueError(f"duplicate strategy id: {metadata.strategy_id}")
        self._strategies[metadata.strategy_id] = strategy

    def get(self, strategy_id: str):
        try:
            return self._strategies[strategy_id]
        except KeyError:
            raise KeyError(f"unknown strategy: {strategy_id}") from None

    def list(self) -> list[StrategyMetadata]:
        return [
            strategy.metadata
            for strategy in self._strategies.values()
            if hasattr(strategy, "metadata")
        ]
