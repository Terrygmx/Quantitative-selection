"""Industry momentum rotation: rank configured industry proxies by their
`momentum_window` return and go long the top `top_n` industries with a
positive signal. Mid-frequency diversifier (design section 6 #4 alt)."""

from __future__ import annotations

from datetime import timedelta
from typing import Mapping

from quant_agent.domain.models import Signal
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.registry import StrategyMetadata
from quant_agent.strategies.schema import validate_config


DEFAULT_MOMENTUM_WINDOW = 20
DEFAULT_TOP_N = 2
DEFAULT_HOLDING_DAYS = 10


class IndustryRotationStrategy:
    metadata = StrategyMetadata(
        strategy_id="industry_rotation",
        version="0.1.0",
        frequency="daily",
    )

    def __init__(
        self,
        industry_universe: Mapping[str, str] | None = None,
        *,
        momentum_window: int = DEFAULT_MOMENTUM_WINDOW,
        top_n: int = DEFAULT_TOP_N,
        holding_days: int = DEFAULT_HOLDING_DAYS,
    ):
        self.industry_universe = dict(industry_universe or {})
        self.momentum_window = int(momentum_window)
        self.top_n = int(top_n)
        self.holding_days = int(holding_days)

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "IndustryRotationStrategy":
        industries = config.get("industry_universe", {})
        if not isinstance(industries, dict) or not industries:
            raise ValueError("industry_universe must be a non-empty mapping")
        validate_config(config, cls.config_schema())
        momentum = config.get("momentum_window", DEFAULT_MOMENTUM_WINDOW)
        top_n = config.get("top_n", DEFAULT_TOP_N)
        holding = config.get("holding_days", DEFAULT_HOLDING_DAYS)
        if not (
            isinstance(momentum, int)
            and isinstance(top_n, int)
            and isinstance(holding, int)
        ):
            raise ValueError("window/top_n/holding_days must be integers")
        return cls(
            industry_universe={
                str(key): str(value) for key, value in industries.items()
            },
            momentum_window=momentum,
            top_n=top_n,
            holding_days=holding,
        )

    def config_fingerprint(self) -> Mapping[str, object]:
        return {
            "industry_universe": dict(self.industry_universe),
            "momentum_window": self.momentum_window,
            "top_n": self.top_n,
            "holding_days": self.holding_days,
        }

    def validate(self, config: Mapping[str, object]) -> None:
        validate_config(config, self.config_schema())

    @staticmethod
    def config_schema() -> dict[str, object]:
        return {
            "type": "object",
            "required": ["industry_universe"],
            "properties": {
                "industry_universe": {
                    "type": "object",
                    "additionalProperties": {"type": "string", "minLength": 1},
                    "minProperties": 1,
                },
                "momentum_window": {"type": "integer", "minimum": 5},
                "top_n": {"type": "integer", "minimum": 1, "maximum": 10},
                "holding_days": {"type": "integer", "minimum": 1, "maximum": 60},
            },
            "additionalProperties": False,
        }

    def warmup(self) -> int:
        return self.momentum_window + 1

    def on_snapshot(self, ctx: StrategyContext) -> list[Signal]:
        ranked = self._ranked_industries(ctx)
        valid_to = ctx.as_of + timedelta(days=self.holding_days)
        signals: list[Signal] = []
        for rank, (industry, symbol, momentum) in enumerate(ranked[: self.top_n], 1):
            if momentum <= 0:
                continue
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
                        "industry": industry,
                        "proxy_symbol": symbol,
                        "momentum_window": self.momentum_window,
                        "momentum_20d": momentum,
                        "rank": rank,
                    },
                )
            )
        return signals

    def _ranked_industries(self, ctx: StrategyContext) -> list[tuple[str, str, float]]:
        scored: list[tuple[str, str, float]] = []
        for industry, symbol in sorted(self.industry_universe.items()):
            bars = ctx.data_port.bars(symbol, ctx.as_of)
            if len(bars) < self.warmup():
                raise ValueError(
                    f"{industry} ({symbol}) warmup requires at least "
                    f"{self.warmup()} bars"
                )
            closes = [bar.close for bar in bars]
            momentum = closes[-1] / closes[-self.momentum_window - 1] - 1
            scored.append((industry, symbol, momentum))
        scored.sort(key=lambda item: item[2], reverse=True)
        return scored
