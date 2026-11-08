"""Daily Donchian breakout with a rising-MA20 filter (multi-day holding):
go long when the latest close breaks the highest high of the previous
`breakout_window` bars while ma20 is still rising."""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Mapping, Sequence

from quant_agent.ports.market_data import Bar
from quant_agent.domain.models import Signal
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.registry import StrategyMetadata
from quant_agent.strategies.schema import validate_config


DEFAULT_BREAKOUT_WINDOW = 20
DEFAULT_TREND_WINDOW = 20


class TrendBreakoutStrategy:
    metadata = StrategyMetadata(
        strategy_id="trend_breakout",
        version="0.1.0",
        frequency="daily",
    )

    def __init__(
        self,
        universe: Iterable[str] = ("sh600519",),
        *,
        breakout_window: int = DEFAULT_BREAKOUT_WINDOW,
        trend_window: int = DEFAULT_TREND_WINDOW,
    ):
        self.universe = tuple(universe)
        self.breakout_window = int(breakout_window)
        self.trend_window = int(trend_window)

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "TrendBreakoutStrategy":
        universe = config["universe"]
        if not isinstance(universe, list):
            raise ValueError("universe must be a list")
        validate_config(config, cls.config_schema())
        breakout = config.get("breakout_window", DEFAULT_BREAKOUT_WINDOW)
        trend = config.get("trend_window", DEFAULT_TREND_WINDOW)
        if not isinstance(breakout, int) or not isinstance(trend, int):
            raise ValueError("window sizes must be integers")
        return cls(
            universe=[str(symbol) for symbol in universe],
            breakout_window=breakout,
            trend_window=trend,
        )

    def config_fingerprint(self) -> Mapping[str, object]:
        return {
            "universe": list(self.universe),
            "breakout_window": self.breakout_window,
            "trend_window": self.trend_window,
        }

    def validate(self, config: Mapping[str, object]) -> None:
        validate_config(config, self.config_schema())

    @staticmethod
    def config_schema() -> dict[str, object]:
        return {
            "type": "object",
            "required": ["universe"],
            "properties": {
                "universe": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "minItems": 1,
                },
                "breakout_window": {"type": "integer", "minimum": 5},
                "trend_window": {"type": "integer", "minimum": 5},
            },
            "additionalProperties": False,
        }

    def warmup(self) -> int:
        # breakout window of history + the breakout bar itself, plus one
        # extra history bar so the pre-breakout trend is comparable.
        return max(self.breakout_window, self.trend_window) + 2

    def on_snapshot(self, ctx: StrategyContext) -> list[Signal]:
        valid_to = ctx.as_of + timedelta(days=self.breakout_window)
        signals: list[Signal] = []
        for symbol in self.universe:
            bars = ctx.data_port.bars(symbol, ctx.as_of)
            if len(bars) < self.warmup():
                raise ValueError(
                    f"{symbol} warmup requires at least {self.warmup()} bars"
                )
            if self._breaks_out(bars):
                prior_high = max(
                    bar.high for bar in bars[-self.breakout_window - 1 : -1]
                )
                signals.append(
                    Signal(
                        strategy_id=self.metadata.strategy_id,
                        version=self.metadata.version,
                        symbol=symbol,
                        side="long",
                        target_weight=1.0,
                        confidence=1.0,
                        valid_from=ctx.as_of,
                        valid_to=valid_to,
                        evidence={
                            "breakout_window": self.breakout_window,
                            "prior_high": prior_high,
                            "close": bars[-1].close,
                            "ma20_rising": self._ma_rising(bars, self.trend_window),
                        },
                    )
                )
        return signals

    def _breaks_out(self, bars: Sequence[Bar]) -> bool:
        window = bars[-self.breakout_window - 1 : -1]
        prior_high = max(bar.high for bar in window)
        if bars[-1].close <= prior_high:
            return False
        # The trend must already be rising BEFORE the breakout bar: with
        # close-based breakouts the breakout close itself always lifts a
        # same-window MA, so the filter is computed on prior history only.
        return self._ma_rising(bars[:-1], self.trend_window)

    @staticmethod
    def _ma_rising(bars: Sequence[Bar], window: int) -> bool:
        closes = [bar.close for bar in bars]

        def ma(values: Sequence[float]) -> float:
            return sum(values[-window:]) / window

        return ma(closes) > ma(closes[:-1])
