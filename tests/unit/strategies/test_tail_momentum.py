from datetime import datetime, timezone

import pytest

from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.tail_momentum import TailMomentumStrategy


AS_OF = datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc)


def bar(timestamp, close=10.0):
    return Bar("sh600519", timestamp, close, close, close, close, 100.0, timestamp)


def context(bars):
    return StrategyContext(InMemoryMarketDataPort(bars), AS_OF)


def test_strategy_declares_warmup_and_requires_enough_bars():
    strategy = TailMomentumStrategy(lookback=5)
    bars = [
        bar(datetime(2026, 9, 15, 9, 30 + i, tzinfo=timezone.utc), 10 + i)
        for i in range(4)
    ]

    assert strategy.warmup() == 5
    with pytest.raises(ValueError, match="warmup"):
        strategy.on_snapshot(context(bars))


def test_strategy_cannot_see_future_minutes():
    strategy = TailMomentumStrategy(lookback=2)
    bars = [
        bar(datetime(2026, 9, 15, 14, 29, tzinfo=timezone.utc), 10),
        bar(datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc), 11),
        bar(datetime(2026, 9, 15, 14, 31, tzinfo=timezone.utc), 99),
    ]
    signals = strategy.on_snapshot(context(bars))

    assert len(signals) == 1
    assert signals[0].symbol == "sh600519"
    assert signals[0].evidence["last_close"] == 11
