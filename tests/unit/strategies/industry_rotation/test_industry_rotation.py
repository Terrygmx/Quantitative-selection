"""industry_rotation: rotate into industries with the strongest recent
momentum (DETAILED_DESIGN section 6, strategy #4 alternative)."""

from datetime import datetime, timedelta, timezone

import pytest

from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.industry_rotation.strategy import IndustryRotationStrategy


UTC = timezone.utc
AS_OF = datetime(2026, 9, 15, 15, 5, tzinfo=UTC)


def bars(symbol: str, returns: list[float]) -> list[Bar]:
    level = 10.0
    out = []
    for index, ret in enumerate(returns):
        level *= 1 + ret
        stamp = AS_OF - timedelta(days=len(returns) - index)
        out.append(
            Bar(
                instrument=symbol,
                timestamp=stamp,
                open=level,
                high=level,
                low=level,
                close=level,
                volume=1000.0,
                available_at=stamp,
            )
        )
    return out


def context(industries: dict[str, list[Bar]]) -> StrategyContext:
    merged: dict[str, Bar] = {}
    for series in industries.values():
        for bar in series:
            merged[bar.timestamp.isoformat() + bar.instrument] = bar
    return StrategyContext(InMemoryMarketDataPort(list(merged.values())), AS_OF)


def test_rotates_into_the_strongest_industry_only():
    hot = bars("bk_hot", [0.01] * 21)
    cold = bars("bk_cold", [-0.005] * 21)
    strategy = IndustryRotationStrategy(
        industry_universe={"tech": "bk_hot", "utility": "bk_cold"}, top_n=1
    )

    signals = strategy.on_snapshot(context({"bk_hot": hot, "bk_cold": cold}))

    assert [signal.symbol for signal in signals] == ["bk_hot"]
    assert signals[0].evidence["rank"] == 1
    # 21 bars -> the momentum spans exactly 20 compounding steps of +1%.
    assert signals[0].evidence["momentum_20d"] == pytest.approx(1.01**20 - 1, abs=1e-9)


def test_cold_industries_get_no_signal():
    cold = bars("bk_cold", [-0.005] * 21)
    strategy = IndustryRotationStrategy(
        industry_universe={"utility": "bk_cold"}, top_n=2
    )

    signals = strategy.on_snapshot(context({"bk_cold": cold}))

    assert signals == []


def test_warmup_enforced():
    short = bars("bk_hot", [0.01] * 5)
    strategy = IndustryRotationStrategy(
        industry_universe={"tech": "bk_hot"}, momentum_window=20
    )

    with pytest.raises(ValueError, match="warmup"):
        strategy.on_snapshot(context({"bk_hot": short}))


def test_validate_schema():
    strategy = IndustryRotationStrategy(industry_universe={"tech": "bk_hot"})

    strategy.validate({"industry_universe": {"tech": "bk_hot"}, "top_n": 1})
    with pytest.raises(ValueError):
        strategy.validate({"industry_universe": {"tech": "bk_hot"}, "top_n": 0})
    with pytest.raises(ValueError):
        strategy.validate({"industry_universe": {}, "top_n": 1})
