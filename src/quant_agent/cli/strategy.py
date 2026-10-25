"""`quant-agent strategy` CLI: list registered strategy plugins."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from quant_agent.strategies.registry import StrategyRegistry
from quant_agent.strategies.industry_rotation.strategy import IndustryRotationStrategy
from quant_agent.strategies.low_vol_quality.strategy import LowVolQualityStrategy
from quant_agent.strategies.mean_reversion.strategy import MeanReversionStrategy
from quant_agent.strategies.tail_momentum.strategy import TailMomentumStrategy
from quant_agent.strategies.trend_breakout.strategy import TrendBreakoutStrategy


def default_registry() -> StrategyRegistry:
    """Explicit registration keeps plugin discovery reviewable
    (DETAILED_DESIGN §4 chooses a registry over entry points)."""
    registry = StrategyRegistry()
    registry.register(TailMomentumStrategy())
    registry.register(TrendBreakoutStrategy())
    registry.register(MeanReversionStrategy())
    registry.register(LowVolQualityStrategy())
    registry.register(IndustryRotationStrategy())
    return registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-agent strategy",
        description="Inspect registered strategy plugins.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list registered strategy plugins")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        plugins = [
            {
                "strategy_id": metadata.strategy_id,
                "version": metadata.version,
                "frequency": metadata.frequency,
            }
            for metadata in default_registry().list()
        ]
        print(json.dumps(plugins, ensure_ascii=False, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
