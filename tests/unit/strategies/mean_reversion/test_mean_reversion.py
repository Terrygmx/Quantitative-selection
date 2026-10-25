"""mean_reversion_liquid: short-period dip buying on liquid stocks
(DETAILED_DESIGN section 6, strategy #3)."""

from datetime import datetime, timedelta, timezone

import pytest

from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.mean_reversion.strategy import MeanReversionStrategy


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


def two_phase(base: float = 10.0, upper: float = 11.5, days: int = 30) -> list[Bar]:
    """`days` total bars: a flat base phase then an upper plateau, so ma5
    sits at `upper` while ma20 stays well below it."""
    flat = days - 8
    history = [bar(offset, base) for offset in range(days, days - flat, -1)]
    history += [bar(offset, upper) for offset in range(days - flat, 0, -1)]
    return history


def context(bars: list[Bar]) -> StrategyContext:
    return StrategyContext(InMemoryMarketDataPort(bars), AS_OF)


def test_oversold_dip_inside_an_uptrend_emits_long_signal():
    history = two_phase()
    dip = bar(0, close=11.5 * 0.95, amount=2e8)

    signals = MeanReversionStrategy(universe=["sh600519"]).on_snapshot(
        context(history + [dip])
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.side == "long"
    assert signal.target_weight == 1.0
    assert signal.evidence["deviation"] == pytest.approx(-0.05, abs=1e-9)
    assert signal.evidence["avg_amount_5d"] == pytest.approx(2e8)
    assert signal.evidence["above_ma20"] is True


def test_shallow_dip_below_the_deviation_threshold_is_skipped():
    history = two_phase()
    shallow = bar(0, close=11.3)

    signals = MeanReversionStrategy(universe=["sh600519"]).on_snapshot(
        context(history + [shallow])
    )

    assert signals == []


def test_dip_below_ma20_is_vetoed():
    history = two_phase(base=12.0, upper=11.5)
    dip = bar(0, close=10.9)

    signals = MeanReversionStrategy(universe=["sh600519"]).on_snapshot(
        context(history + [dip])
    )

    assert signals == []


def test_illiquid_dip_is_vetoed():
    history = [bar(offset, 11.5, amount=0.5e8) for offset in range(30, 0, -1)]
    dip = bar(0, close=11.5 * 0.95, amount=0.5e8)

    signals = MeanReversionStrategy(universe=["sh600519"]).on_snapshot(
        context(history + [dip])
    )

    assert signals == []


def test_warmup_covers_ma20_plus_one():
    strategy = MeanReversionStrategy(universe=["sh600519"])

    assert strategy.warmup() == 21
    with pytest.raises(ValueError, match="warmup"):
        strategy.on_snapshot(context(two_phase(days=15) + [bar(0, 10.9)]))


def test_validate_uses_the_config_schema():
    strategy = MeanReversionStrategy(universe=["sh600519"])

    strategy.validate({"universe": ["sh600519"], "deviation_threshold": 0.05})
    with pytest.raises(ValueError):
        strategy.validate({"universe": ["sh600519"], "deviation_threshold": 0.001})
    with pytest.raises(ValueError):
        strategy.validate({"universe": [], "deviation_threshold": 0.05})
    with pytest.raises(ValueError):
        strategy.validate({"universe": ["sh600519"], "holding_days": 0})
