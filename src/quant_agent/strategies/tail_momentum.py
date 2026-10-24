from __future__ import annotations

from datetime import timedelta
from typing import Iterable

from quant_agent.domain.models import Signal
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.registry import StrategyMetadata


class TailMomentumStrategy:
    metadata = StrategyMetadata(
        strategy_id="tail_momentum_overnight",
        version="0.1.0",
        frequency="intraday",
    )

    def __init__(self, lookback: int = 5, universe: Iterable[str] = ("sh600519",)):
        if not 1 <= lookback <= 5:
            raise ValueError("lookback must be between 1 and 5")
        self.lookback = lookback
        self.universe = tuple(universe)

    def warmup(self) -> int:
        return self.lookback

    def on_snapshot(self, ctx: StrategyContext) -> list[Signal]:
        signals: list[Signal] = []
        valid_to = ctx.as_of + timedelta(hours=19)
        for symbol in self.universe:
            bars = ctx.data_port.bars(symbol, ctx.as_of)
            if len(bars) < self.warmup():
                raise ValueError(
                    f"{symbol} warmup requires at least {self.warmup()} bars"
                )
            recent = bars[-self.lookback :]
            momentum = (recent[-1].close - recent[0].close) / recent[0].close
            if momentum <= 0:
                continue
            signals.append(
                Signal(
                    strategy_id=self.metadata.strategy_id,
                    version=self.metadata.version,
                    symbol=symbol,
                    side="long",
                    target_weight=0.2,
                    confidence=0.8,
                    valid_from=ctx.as_of,
                    valid_to=valid_to,
                    evidence={
                        "last_close": recent[-1].close,
                        "momentum": momentum,
                        "lookback": self.lookback,
                    },
                )
            )
        return signals
