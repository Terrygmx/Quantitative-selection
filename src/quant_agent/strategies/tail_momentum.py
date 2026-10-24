from __future__ import annotations

from datetime import timedelta

from quant_agent.domain.models import Signal
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.registry import StrategyMetadata


class TailMomentumStrategy:
    metadata = StrategyMetadata(
        strategy_id="tail_momentum_overnight",
        version="0.1.0",
        frequency="intraday",
    )

    def __init__(self, lookback: int = 5):
        if not 1 <= lookback <= 5:
            raise ValueError("lookback must be between 1 and 5")
        self.lookback = lookback

    def warmup(self) -> int:
        return self.lookback

    def on_snapshot(self, ctx: StrategyContext) -> list[Signal]:
        bars = ctx.data_port.bars("sh600519", ctx.as_of)
        if len(bars) < self.warmup():
            raise ValueError(f"warmup requires at least {self.warmup()} bars")
        recent = bars[-self.lookback :]
        momentum = (recent[-1].close - recent[0].close) / recent[0].close
        if momentum <= 0:
            return []
        valid_from = ctx.as_of
        valid_to = ctx.as_of + timedelta(hours=19)
        return [
            Signal(
                strategy_id=self.metadata.strategy_id,
                version=self.metadata.version,
                symbol="sh600519",
                side="long",
                target_weight=0.2,
                confidence=0.8,
                valid_from=valid_from,
                valid_to=valid_to,
                evidence={
                    "last_close": recent[-1].close,
                    "momentum": momentum,
                    "lookback": self.lookback,
                },
            )
        ]
