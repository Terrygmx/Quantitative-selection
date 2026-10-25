"""Low-volatility quality tilt: hold calm names trading above their long
trend with adequate turnover - a mid/low-frequency diversifier against
the momentum strategies."""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Mapping, Sequence

from quant_agent.adapters.market_data import Bar
from quant_agent.domain.models import Signal
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.registry import StrategyMetadata
from quant_agent.strategies.schema import validate_config


DEFAULT_VOL_WINDOW = 20
DEFAULT_VOL_THRESHOLD = 0.015
DEFAULT_TREND_WINDOW = 60
DEFAULT_HOLDING_DAYS = 20
DEFAULT_LIQUIDITY_AMOUNT_YI = 1.0


class LowVolQualityStrategy:
    metadata = StrategyMetadata(
        strategy_id="low_vol_quality",
        version="0.1.0",
        frequency="daily",
    )

    def __init__(
        self,
        universe: Iterable[str] = ("sh600519",),
        *,
        vol_window: int = DEFAULT_VOL_WINDOW,
        vol_threshold: float = DEFAULT_VOL_THRESHOLD,
        trend_window: int = DEFAULT_TREND_WINDOW,
        holding_days: int = DEFAULT_HOLDING_DAYS,
        liquidity_amount_yi: float = DEFAULT_LIQUIDITY_AMOUNT_YI,
    ):
        self.universe = tuple(universe)
        self.vol_window = int(vol_window)
        self.vol_threshold = float(vol_threshold)
        self.trend_window = int(trend_window)
        self.holding_days = int(holding_days)
        self.liquidity_floor = float(liquidity_amount_yi) * 1e8

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "LowVolQualityStrategy":
        universe = config["universe"]
        if not isinstance(universe, list):
            raise ValueError("universe must be a list")
        validate_config(config, cls.config_schema())
        return cls(
            universe=[str(symbol) for symbol in universe],
            vol_window=int(config.get("vol_window", DEFAULT_VOL_WINDOW)),
            vol_threshold=float(config.get("vol_threshold", DEFAULT_VOL_THRESHOLD)),
            trend_window=int(config.get("trend_window", DEFAULT_TREND_WINDOW)),
            holding_days=int(config.get("holding_days", DEFAULT_HOLDING_DAYS)),
            liquidity_amount_yi=float(
                config.get("liquidity_amount_yi", DEFAULT_LIQUIDITY_AMOUNT_YI)
            ),
        )

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
                "vol_window": {"type": "integer", "minimum": 5, "maximum": 60},
                "vol_threshold": {"type": "number", "minimum": 0.001, "maximum": 1.0},
                "trend_window": {"type": "integer", "minimum": 20, "maximum": 250},
                "holding_days": {"type": "integer", "minimum": 5, "maximum": 120},
                "liquidity_amount_yi": {"type": "number", "minimum": 0},
            },
            "additionalProperties": False,
        }

    def warmup(self) -> int:
        return self.trend_window + 1

    def on_snapshot(self, ctx: StrategyContext) -> list[Signal]:
        valid_to = ctx.as_of + timedelta(days=self.holding_days)
        signals: list[Signal] = []
        for symbol in self.universe:
            bars = ctx.data_port.bars(symbol, ctx.as_of)
            if len(bars) < self.warmup():
                raise ValueError(
                    f"{symbol} warmup requires at least {self.warmup()} bars"
                )
            signal = self._evaluate(symbol, bars, ctx.as_of, valid_to)
            if signal is not None:
                signals.append(signal)
        return signals

    def _evaluate(self, symbol: str, bars: Sequence[Bar], as_of, valid_to) -> Signal | None:
        closes = [bar.close for bar in bars]
        returns = [
            closes[index] / closes[index - 1] - 1
            for index in range(len(closes) - self.vol_window, len(closes))
        ]
        mean_return = sum(returns) / len(returns)
        variance = sum((item - mean_return) ** 2 for item in returns) / len(returns)
        realized_vol = variance**0.5
        trend = sum(closes[-self.trend_window :]) / self.trend_window
        close = closes[-1]
        above_trend = close > trend
        avg_amount_5d = sum(bar.amount for bar in bars[-5:]) / 5
        if realized_vol > self.vol_threshold:
            return None
        if not above_trend:
            return None
        if avg_amount_5d < self.liquidity_floor:
            return None
        return Signal(
            strategy_id=self.metadata.strategy_id,
            version=self.metadata.version,
            symbol=symbol,
            side="long",
            target_weight=1.0,
            confidence=1.0,
            valid_from=as_of,
            valid_to=valid_to,
            evidence={
                "realized_vol": realized_vol,
                "vol_threshold": self.vol_threshold,
                "vol_window": self.vol_window,
                "trend": trend,
                "above_trend": True,
                "avg_amount_5d": avg_amount_5d,
            },
        )
