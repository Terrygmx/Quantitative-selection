"""trend_breakout: daily Donchian breakout with a rising-MA filter and
multi-day holding (DETAILED_DESIGN section 6, strategy #2)."""

from datetime import datetime, timedelta, timezone
from typing import Sequence

import pytest

from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.trend_breakout.strategy import TrendBreakoutStrategy


UTC = timezone.utc
AS_OF = datetime(2026, 9, 15, 15, 5, tzinfo=UTC)


def bar(day_offset: int, close: float, high: float | None = None) -> Bar:
    stamp = AS_OF - timedelta(days=day_offset)
    return Bar(
        instrument="sh600519",
        timestamp=stamp,
        open=close,
        high=high if high is not None else close,
        low=close,
        close=close,
        volume=1000.0,
        available_at=stamp,
    )


def rising_history(days: int = 40, start: float = 9.0, step: float = 0.05) -> list[Bar]:
    return [bar(offset, start + (days - offset) * step) for offset in range(days, 0, -1)]


def context(bars: Sequence[Bar]) -> StrategyContext:
    return StrategyContext(InMemoryMarketDataPort(list(bars)), AS_OF)


def test_breakout_above_prior_highs_emits_long_signal():
    history = rising_history()
    breakout = bar(0, close=11.5, high=12.0)
    strategy = TrendBreakoutStrategy(universe=["sh600519"])

    signals = strategy.on_snapshot(context(history + [breakout]))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.symbol == "sh600519"
    assert signal.side == "long"
    assert signal.target_weight == 1.0
    assert signal.evidence["breakout_window"] == 20
    assert signal.evidence["prior_high"] == 10.95
    assert signal.evidence["ma20_rising"] is True


def test_intraday_spike_that_closes_back_inside_emits_no_signal():
    history = rising_history()
    # High pierces the prior high but the close falls back inside: the
    # breakout is defined on closes, so no signal.
    inside = bar(0, close=10.0, high=11.0)

    signals = TrendBreakoutStrategy(universe=["sh600519"]).on_snapshot(
        context(history + [inside])
    )

    assert signals == []


def test_breakout_requires_rising_ma20():
    # Closes decline steadily (12.0 -> 10.0); a marginal breakout close of
    # 11.1 clears the 11.0 prior high but cannot lift ma20 above the
    # previous window, so the trend filter vetoes it.
    history = [
        bar(offset, 12.0 - (40 - offset) * 0.05)
        for offset in range(40, 0, -1)
    ]
    breakout = bar(0, close=11.1, high=11.2)

    signals = TrendBreakoutStrategy(universe=["sh600519"]).on_snapshot(
        context(history + [breakout])
    )

    assert signals == []


def test_warmup_enforced_per_symbol():
    short_history = rising_history(days=10)

    with pytest.raises(ValueError, match="warmup"):
        TrendBreakoutStrategy(universe=["sh600519"]).on_snapshot(
            context(short_history)
        )


def test_validate_uses_the_config_schema():
    strategy = TrendBreakoutStrategy(universe=["sh600519"])

    strategy.validate({"universe": ["sh600519"], "breakout_window": 10})
    with pytest.raises(ValueError):
        strategy.validate({"universe": ["sh600519"], "breakout_window": 2})
    with pytest.raises(ValueError):
        strategy.validate({"universe": [], "breakout_window": 10})


def test_warmup_scales_with_windows():
    strategy = TrendBreakoutStrategy(
        universe=["sh600519"], breakout_window=30, trend_window=25
    )

    assert strategy.warmup() == 32
