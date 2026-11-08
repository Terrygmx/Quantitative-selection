"""Explicit strategy plugin construction used by CLI entry points."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from quant_agent.strategies.industry_rotation.strategy import IndustryRotationStrategy
from quant_agent.strategies.low_vol_quality.strategy import LowVolQualityStrategy
from quant_agent.strategies.mean_reversion.strategy import MeanReversionStrategy
from quant_agent.strategies.registry import Strategy, StrategyRegistry
from quant_agent.strategies.trend_breakout.strategy import TrendBreakoutStrategy

DAILY_STRATEGY_FACTORIES = {
    "trend_breakout": TrendBreakoutStrategy.from_config,
    "mean_reversion_liquid": MeanReversionStrategy.from_config,
    "low_vol_quality": LowVolQualityStrategy.from_config,
    "industry_rotation": IndustryRotationStrategy.from_config,
}

def build_strategy_registry(
    strategy_ids: Sequence[str],
    strategy_configs: Mapping[str, Mapping[str, object]],
) -> StrategyRegistry:
    factories = DAILY_STRATEGY_FACTORIES
    unknown = [item for item in strategy_ids if item not in factories]
    if unknown:
        raise ValueError(
            "unsupported strategy ids: " + ", ".join(sorted(unknown))
        )
    missing = [
        item for item in strategy_ids if item not in strategy_configs
    ]
    if missing:
        raise ValueError(
            "strategy_configs is missing: " + ", ".join(sorted(missing))
        )
    registry = StrategyRegistry()
    for strategy_id in strategy_ids:
        plugin_config = strategy_configs[strategy_id]
        if not isinstance(plugin_config, Mapping):
            raise ValueError(
                f"strategy_configs.{strategy_id} must be an object"
            )
        try:
            strategy = factories[strategy_id](dict(plugin_config))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid config for strategy {strategy_id}: {exc}"
            ) from exc
        registry.register(cast(Strategy, strategy))
    return registry
