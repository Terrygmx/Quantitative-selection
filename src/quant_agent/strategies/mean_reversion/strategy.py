"""Short-period mean reversion on liquid stocks: buy a dip of at least
`deviation_threshold` below ma5 while price is still above ma20 (dip
inside an uptrend) and 5-day average turnover clears the liquidity
floor."""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable, Mapping, Sequence

from quant_agent.ports.market_data import Bar
from quant_agent.domain.models import Signal
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.registry import StrategyMetadata
from quant_agent.strategies.schema import validate_config


DEFAULT_DEVIATION_THRESHOLD = 0.03
DEFAULT_LIQUIDITY_AMOUNT_YI = 1.0
DEFAULT_HOLDING_DAYS = 5


class MeanReversionStrategy:
    metadata = StrategyMetadata(
        strategy_id="mean_reversion_liquid",
        version="0.1.0",
        frequency="daily",
    )

    def __init__(
        self,
        universe: Iterable[str] = ("sh600519",),
        *,
        deviation_threshold: float = DEFAULT_DEVIATION_THRESHOLD,
        liquidity_amount_yi: float = DEFAULT_LIQUIDITY_AMOUNT_YI,
        holding_days: int = DEFAULT_HOLDING_DAYS,
    ):
        self.universe = tuple(universe)
        self.deviation_threshold = float(deviation_threshold)
        self.liquidity_floor = float(liquidity_amount_yi) * 1e8
        self.holding_days = int(holding_days)

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "MeanReversionStrategy":
        universe = config["universe"]
        if not isinstance(universe, list):
            raise ValueError("universe must be a list")
        validate_config(config, cls.config_schema())
        deviation = config.get("deviation_threshold", DEFAULT_DEVIATION_THRESHOLD)
        liquidity = config.get("liquidity_amount_yi", DEFAULT_LIQUIDITY_AMOUNT_YI)
        holding = config.get("holding_days", DEFAULT_HOLDING_DAYS)
        if not isinstance(deviation, (int, float)) or not isinstance(
            liquidity, (int, float)
        ):
            raise ValueError("thresholds must be numbers")
        if not isinstance(holding, int):
            raise ValueError("holding_days must be an integer")
        return cls(
            universe=[str(symbol) for symbol in universe],
            deviation_threshold=float(deviation),
            liquidity_amount_yi=float(liquidity),
            holding_days=holding,
        )

    def config_fingerprint(self) -> Mapping[str, object]:
        return {
            "universe": list(self.universe),
            "deviation_threshold": self.deviation_threshold,
            "liquidity_floor": self.liquidity_floor,
            "holding_days": self.holding_days,
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
                "deviation_threshold": {"type": "number", "minimum": 0.005},
                "liquidity_amount_yi": {"type": "number", "minimum": 0},
                "holding_days": {"type": "integer", "minimum": 1, "maximum": 60},
            },
            "additionalProperties": False,
        }

    def warmup(self) -> int:
        return 21

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

    def _evaluate(
        self,
        symbol: str,
        bars: Sequence[Bar],
        as_of,
        valid_to,
    ) -> Signal | None:
        closes = [bar.close for bar in bars]
        # Reference level the price is reverting to: ma5 BEFORE the dip bar
        # (the dip itself would dilute its own deviation measure).
        ma5 = sum(closes[-6:-1]) / 5
        ma20 = sum(closes[-20:]) / 20
        close = closes[-1]
        deviation = close / ma5 - 1
        avg_amount_5d = sum(bar.amount for bar in bars[-5:]) / 5
        above_ma20 = close > ma20
        if -deviation < self.deviation_threshold:
            return None
        if not above_ma20:
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
                "deviation": deviation,
                "ma5": ma5,
                "ma20": ma20,
                "above_ma20": True,
                "avg_amount_5d": avg_amount_5d,
                "liquidity_floor": self.liquidity_floor,
                "deviation_threshold": self.deviation_threshold,
            },
        )
