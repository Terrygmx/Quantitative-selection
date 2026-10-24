from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class StrategyMetadata:
    strategy_id: str
    version: str
    frequency: str


@dataclass(frozen=True, slots=True)
class PluginFailure:
    strategy_id: str
    reason_code: str
    message: str


@dataclass(frozen=True, slots=True)
class PluginRunResult:
    signals: tuple[object, ...]
    failures: tuple[PluginFailure, ...]


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

    def run_all(self, context, on_failure: Callable[[PluginFailure], None] | None = None):
        if not self._strategies:
            raise ValueError("No registered strategies")

        signals = []
        failures = []
        for strategy_id, strategy in self._strategies.items():
            try:
                signals.extend(strategy.on_snapshot(context))
            except Exception as exc:
                failure = PluginFailure(
                    strategy_id=strategy_id,
                    reason_code="PLUGIN_CRASH",
                    message=str(exc),
                )
                failures.append(failure)
                if on_failure is not None:
                    on_failure(failure)
        return PluginRunResult(signals=tuple(signals), failures=tuple(failures))
