from __future__ import annotations

from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Mapping, Protocol

from quant_agent.domain.models import Signal
from quant_agent.ports.market_data import DataUnavailable, QualityEventCollector

if TYPE_CHECKING:
    from quant_agent.strategies.context import StrategyContext


@dataclass(frozen=True, slots=True)
class StrategyMetadata:
    """FR-1.2: plugins declare their turnover ceiling and risk exposure so
    the portfolio layer can constrain by declaration."""

    strategy_id: str
    version: str
    frequency: str
    turnover_cap: float | None = None
    risk_exposure: str | None = None


class Strategy(Protocol):
    """Minimal structural contract the registry relies on (DETAILED_DESIGN
    §4 keeps discovery explicit rather than entry-point based)."""

    metadata: StrategyMetadata

    def on_snapshot(self, context: "StrategyContext") -> Sequence[Signal]: ...

    def config_fingerprint(self) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class PluginFailure:
    strategy_id: str
    reason_code: str
    message: str


@dataclass(frozen=True, slots=True)
class PluginRunResult:
    signals: tuple[Signal, ...]
    failures: tuple[PluginFailure, ...]


class StrategyRegistry:
    def __init__(
        self,
        quality_events: QualityEventCollector | None = None,
    ):
        self._strategies: dict[str, Strategy] = {}
        self._version_history: dict[str, dict[str, Strategy]] = {}
        self._enabled: set[str] = set()
        self.quality_events = quality_events

    def _quality_scope(
        self,
        strategy_id: str,
        quality_events: QualityEventCollector | None,
    ):
        if quality_events is None:
            return nullcontext()
        return quality_events.strategy_scope(strategy_id)

    @staticmethod
    def _require_shared_collector(
        context,
        quality_events: QualityEventCollector | None,
    ) -> None:
        if quality_events is None:
            return
        data_port = getattr(context, "data_port", None)
        if data_port is None:
            return
        if getattr(data_port, "quality_events", None) is not quality_events:
            raise ValueError(
                "quality collector must be shared with the context data port"
            )

    def register(self, strategy: Strategy) -> None:
        metadata = getattr(strategy, "metadata", None)
        if metadata is None or not getattr(metadata, "strategy_id", ""):
            raise ValueError("strategy metadata with strategy_id is required")
        if not callable(getattr(strategy, "on_snapshot", None)):
            raise ValueError("strategy must implement on_snapshot()")
        if not callable(getattr(strategy, "config_fingerprint", None)):
            raise ValueError("strategy must implement config_fingerprint()")
        strategy_id = metadata.strategy_id
        if strategy_id in self._strategies and (
            self._strategies[strategy_id].metadata.version
            == metadata.version
        ):
            raise ValueError(f"duplicate strategy id: {strategy_id}")
        # FR-1: keep every registered version for rollback; the live slot
        # holds the newest, enabled by default (FR-1 启停).
        self._version_history.setdefault(strategy_id, {})[metadata.version] = strategy
        self._strategies[strategy_id] = strategy
        self._enabled.add(strategy_id)

    def get(self, strategy_id: str) -> Strategy:
        try:
            return self._strategies[strategy_id]
        except KeyError:
            raise KeyError(f"unknown strategy: {strategy_id}") from None

    def disable(self, strategy_id: str) -> None:
        self._require_known(strategy_id)
        self._enabled.discard(strategy_id)

    def enable(self, strategy_id: str) -> None:
        self._require_known(strategy_id)
        self._enabled.add(strategy_id)

    def rollback(self, strategy_id: str, version: str) -> None:
        """Point the live slot at a previously registered version; the
        newer version stays in history for a later rollback forward."""
        self._require_known(strategy_id)
        history = self._version_history[strategy_id]
        if version not in history:
            raise KeyError(f"unknown version {version} for {strategy_id}")
        self._strategies[strategy_id] = history[version]

    def _require_known(self, strategy_id: str) -> None:
        if strategy_id not in self._strategies:
            raise KeyError(f"unknown strategy: {strategy_id}")

    def list(self) -> list[StrategyMetadata]:
        return [
            strategy.metadata
            for strategy_id, strategy in self._strategies.items()
            if strategy_id in self._enabled and hasattr(strategy, "metadata")
        ]

    def run_all(
        self,
        context,
        on_failure: Callable[[PluginFailure], None] | None = None,
        *,
        quality_events: QualityEventCollector | None = None,
    ):
        if not self._strategies:
            raise ValueError("No registered strategies")
        if not self._enabled:
            raise ValueError("all strategies are disabled")

        collector = quality_events or self.quality_events
        self._require_shared_collector(context, collector)
        signals: list[Signal] = []
        failures = []
        for strategy_id, strategy in self._strategies.items():
            if strategy_id not in self._enabled:
                continue
            with self._quality_scope(strategy_id, collector):
                try:
                    signals.extend(strategy.on_snapshot(context))
                except Exception as exc:
                    failure = PluginFailure(
                        strategy_id=strategy_id,
                        reason_code=(
                            "DATA_UNAVAILABLE"
                            if isinstance(exc, DataUnavailable)
                            else "PLUGIN_CRASH"
                        ),
                        message=str(exc),
                    )
                    failures.append(failure)
                    if on_failure is not None:
                        on_failure(failure)
        return PluginRunResult(signals=tuple(signals), failures=tuple(failures))

    def run_selected(
        self,
        strategy_ids: Sequence[str],
        context,
        on_failure: Callable[[PluginFailure], None] | None = None,
        *,
        quality_events: QualityEventCollector | None = None,
    ) -> PluginRunResult:
        selected = tuple(strategy_ids)
        if not selected:
            raise ValueError("No strategies selected")
        collector = quality_events or self.quality_events
        self._require_shared_collector(context, collector)
        signals: list[Signal] = []
        failures: list[PluginFailure] = []
        for strategy_id in selected:
            strategy = self.get(strategy_id)
            if strategy_id not in self._enabled:
                raise ValueError(f"strategy is disabled: {strategy_id}")
            with self._quality_scope(strategy_id, collector):
                try:
                    signals.extend(strategy.on_snapshot(context))
                except Exception as exc:
                    failure = PluginFailure(
                        strategy_id=strategy_id,
                        reason_code=(
                            "DATA_UNAVAILABLE"
                            if isinstance(exc, DataUnavailable)
                            else "PLUGIN_CRASH"
                        ),
                        message=str(exc),
                    )
                    failures.append(failure)
                    if on_failure is not None:
                        on_failure(failure)
        return PluginRunResult(signals=tuple(signals), failures=tuple(failures))
