"""low_vol_quality: low-volatility quality tilt, a mid/low-frequency
diversifier (DETAILED_DESIGN section 6, strategy #4)."""

from datetime import datetime, timedelta, timezone

import pytest

from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.low_vol_quality.strategy import LowVolQualityStrategy


UTC = timezone.utc
AS_OF = datetime(2026, 9, 15, 15, 5, tzinfo=UTC)


def bar(day_offset: int, close: float, amount: float = 2e8) -> Bar:
    stamp = AS_OF - timedelta(days=day_offset)
    return Bar(
        instrument="sh600519",
        timestamp=stamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000.0,
        available_at=stamp,
        amount=amount,
    )


def gentle_history(days: int = 65, start: float = 10.0, step: float = 0.05) -> list[Bar]:
    return [bar(offset, start + (days - offset) * step) for offset in range(days, 0, -1)]


def context(bars: list[Bar]) -> StrategyContext:
    return StrategyContext(InMemoryMarketDataPort(bars), AS_OF)


def test_calm_uptrend_above_ma60_emits_long_signal():
    history = gentle_history()

    signals = LowVolQualityStrategy(universe=["sh600519"]).on_snapshot(context(history))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.side == "long"
    assert signal.target_weight == 1.0
    assert signal.evidence["realized_vol"] < 0.015
    assert signal.evidence["vol_threshold"] == 0.015
    assert signal.evidence["above_trend"] is True


def test_volatile_history_is_vetoed():
    # Alternating +/-3% closes push daily-return volatility past 1.5%.
    closes = []
    level = 10.0
    for index in range(65):
        level *= 1.03 if index % 2 == 0 else 0.97
        closes.append(level)
    history = [
        bar(offset, close) for offset, close in zip(range(65, 0, -1), closes)
    ]

    signals = LowVolQualityStrategy(universe=["sh600519"]).on_snapshot(context(history))

    assert signals == []


def test_price_below_long_trend_is_vetoed():
    history = gentle_history(step=-0.05)

    signals = LowVolQualityStrategy(universe=["sh600519"]).on_snapshot(context(history))

    assert signals == []


def test_warmup_matches_trend_window_plus_one():
    strategy = LowVolQualityStrategy(universe=["sh600519"])

    assert strategy.warmup() == 61
    with pytest.raises(ValueError, match="warmup"):
        strategy.on_snapshot(context(gentle_history(days=30)))


def test_validate_uses_the_config_schema():
    strategy = LowVolQualityStrategy(universe=["sh600519"])

    strategy.validate({"universe": ["sh600519"], "vol_threshold": 0.02})
    with pytest.raises(ValueError):
        strategy.validate({"universe": ["sh600519"], "vol_window": 3})
    with pytest.raises(ValueError):
        strategy.validate({"universe": ["sh600519"], "trend_window": 10})
