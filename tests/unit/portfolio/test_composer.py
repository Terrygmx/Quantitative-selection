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
        LiquidityConstraint(
            max_participation=0.1, daily_volume=100000, portfolio_value=100000
        )
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


def test_liquidity_constraint_uses_target_amount_and_daily_capacity():
    # 20% of 100000 portfolio = 20000 target, but capacity is 10000.
    result = composer(
        LiquidityConstraint(
            max_participation=0.1,
            daily_volume=100000,
            portfolio_value=100000,
        )
    ).compose([signal(weight=0.2)])

    assert result.targets[0].status == "rejected"
    assert result.targets[0].reason_code == "LIQUIDITY_LIMIT"


def test_liquidity_constraint_accepts_target_within_capacity():
    result = composer(
        LiquidityConstraint(
            max_participation=0.1,
            daily_volume=1_000_000,
            portfolio_value=100_000,
        )
    ).compose([signal(weight=0.05)])

    assert result.targets[0].status == "accepted"


def test_total_position_constraint_rejects_excess_exposure():
    from quant_agent.application.portfolio import TotalPositionConstraint

    signals = [
        signal(symbol="sh600519", weight=0.6),
        signal(symbol="sz000858", strategy_id="s2", weight=0.6),
    ]

    result = composer(TotalPositionConstraint(max_weight=1.0)).compose(signals)

    assert all(target.status == "rejected" for target in result.targets)
    assert {target.reason_code for target in result.targets} == {"TOTAL_POSITION_LIMIT"}


def test_blacklist_only_applies_on_and_after_effective_date():
    from quant_agent.application.portfolio import BlacklistConstraint

    active = composer(BlacklistConstraint(symbols={"sh600519"}, effective_from="2026-09-15")).compose([signal()])
    before = composer(BlacklistConstraint(symbols={"sh600519"}, effective_from="2026-09-16")).compose([signal()])

    assert active.targets[0].status == "rejected"
    assert before.targets[0].status == "accepted"


def test_risk_decisions_are_immutable_audit_records():
    result = composer(SinglePositionConstraint(max_weight=0.1)).compose(
        [signal(weight=0.3)]
    )

    decision = result.decisions[0]

    assert decision.status == "reduced"
    assert decision.reason_code == "SINGLE_POSITION_LIMIT"
    with pytest.raises(AttributeError):
        decision.status = "accepted"


def test_correlation_budget_rejects_highly_correlated_strategies():
    from quant_agent.application.portfolio import CorrelationBudget

    covariances = {
        ("s1", "s2"): 0.9,
        ("s1", "s1"): 1.0,
        ("s2", "s2"): 1.0,
    }
    result = composer(CorrelationBudget(max_correlation=0.8, covariances=covariances)).compose(
        [signal(weight=0.2), signal(strategy_id="s2", symbol="sz000858", industry="Bank", weight=0.2)]
    )

    assert all(target.status == "rejected" for target in result.targets)
    assert {target.reason_code for target in result.targets} == {"CORRELATION_BUDGET"}


def test_correlation_budget_accepts_uncorrelated_strategies():
    from quant_agent.application.portfolio import CorrelationBudget

    covariances = {("s1", "s2"): 0.1, ("s1", "s1"): 1.0, ("s2", "s2"): 1.0}
    result = composer(CorrelationBudget(max_correlation=0.8, covariances=covariances)).compose(
        [signal(weight=0.2), signal(strategy_id="s2", symbol="sz000858", industry="Bank", weight=0.2)]
    )

    assert all(target.status == "accepted" for target in result.targets)


def test_blocked_strategies_are_excluded_with_an_audit_record():
    """FR-3 data-quality gate: a block-level quality event must stop the
    affected strategy's signals from reaching the portfolio layer."""
    signals = [
        signal(strategy_id="healthy", symbol="sh600519", weight=0.5, industry="白酒"),
        signal(strategy_id="dirty", symbol="sz000001", weight=0.5, industry="银行"),
    ]

    result = composer().compose(signals, blocked_strategies={"dirty"})

    # Healthy signal survives; contributions carry the surviving strategy.
    assert [target.symbol for target in result.targets] == ["sh600519"]
    assert "healthy" in result.targets[0].contributions
    assert all("dirty" not in target.contributions for target in result.targets)
    blocked = [
        decision
        for decision in result.decisions
        if decision.reason_code == "STRATEGY_BLOCKED"
    ]
    assert [decision.symbol for decision in blocked] == ["sz000001"]
    assert all(decision.status == "rejected" for decision in blocked)
    assert all(decision.net_weight == 0.0 for decision in blocked)


def test_quality_block_events_derive_blocked_strategies():
    """The collector exposes the blocked strategy ids for the composer."""
    from datetime import datetime, timezone

    from quant_agent.adapters.market_data import (
        QualityEvent,
        QualityEventCollector,
    )

    collector = QualityEventCollector()
    collector.record(
        QualityEvent(
            level="block",
            reason_code="MISSING_REQUIRED_BAR",
            symbol="sh600519",
            as_of=datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc),
            message="no bar",
        ),
        strategy_id="dirty",
    )
    collector.record(
        QualityEvent(
            level="warn",
            reason_code="STALE",
            symbol="sh600519",
            as_of=datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc),
            message="stale",
        ),
        strategy_id="warned",
    )

    assert collector.blocked_strategy_ids() == {"dirty"}
