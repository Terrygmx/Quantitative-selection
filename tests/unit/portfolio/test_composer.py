from datetime import datetime, timedelta, timezone

import pytest

from quant_agent.application.portfolio import (
    BlacklistConstraint,
    DrawdownFuse,
    IndustryConstraint,
    LiquidityConstraint,
    PortfolioRiskConfig,
    SignalComposer,
    SinglePositionConstraint,
)


NOW = datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc)


def signal(symbol="sh600519", strategy_id="s1", weight=0.2, industry="Alcohol"):
    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "industry": industry,
        "target_weight": weight,
        "confidence": 0.8,
        "valid_from": NOW,
        "valid_to": NOW + timedelta(hours=1),
    }


def config(*constraints):
    return PortfolioRiskConfig(constraints=list(constraints))


def composer(*constraints):
    return SignalComposer(config(*constraints))


def test_opposite_signals_produce_one_audited_net_target():
    result = composer().compose(
        [signal(weight=0.3), signal(strategy_id="s2", weight=-0.1)]
    )

    assert [target.symbol for target in result.targets] == ["sh600519"]
    assert result.targets[0].net_weight == pytest.approx(0.2)
    assert result.targets[0].contributions == {"s1": 0.3, "s2": -0.1}


def test_single_position_constraint_reduces_with_reason_code():
    result = composer(SinglePositionConstraint(max_weight=0.1)).compose([signal(weight=0.3)])

    assert result.targets[0].status == "reduced"
    assert result.targets[0].net_weight == pytest.approx(0.1)
    assert result.targets[0].reason_code == "SINGLE_POSITION_LIMIT"


def test_industry_constraint_rejects_excess_industry_exposure():
    signals = [
        signal(symbol="sh600519", industry="Alcohol", weight=0.1),
        signal(symbol="sz000858", strategy_id="s2", industry="Alcohol", weight=0.2),
    ]

    result = composer(IndustryConstraint(max_weight=0.2)).compose(signals)

    assert all(target.status == "rejected" for target in result.targets)
    assert {target.reason_code for target in result.targets} == {"INDUSTRY_LIMIT"}


def test_liquidity_constraint_rejects_illiquid_target():
    result = composer(
        LiquidityConstraint(max_participation=0.1, daily_volume=100000)
    ).compose([signal(weight=0.2)])

    # A 20% target of a 100k-volume security cannot participate more than 10%.
    assert result.targets[0].status == "rejected"
    assert result.targets[0].reason_code == "LIQUIDITY_LIMIT"


def test_drawdown_fuse_rejects_all_targets():
    result = composer(DrawdownFuse(max_drawdown=0.1, current_drawdown=0.2)).compose(
        [signal()]
    )

    assert result.targets[0].status == "rejected"
    assert result.targets[0].reason_code == "DRAWDOWN_FUSE"


def test_blacklist_rejects_symbol():
    result = composer(BlacklistConstraint(symbols={"sh600519"})).compose([signal()])

    assert result.targets[0].status == "rejected"
    assert result.targets[0].reason_code == "BLACKLIST"
