from datetime import datetime, timedelta, timezone

import pytest

from quant_agent.domain.models import Signal
from quant_agent.application.portfolio import (
    BlacklistConstraint,
    PortfolioRiskConfig,
    SignalAdapter,
    SignalComposer,
)


AS_OF = datetime(2026, 11, 8, 14, 30, tzinfo=timezone(timedelta(hours=8)))


def signal(
    symbol: str = "sh600519",
    strategy_id: str = "s1",
    version: str = "1.0.0",
    weight: float = 0.2,
    evidence: dict[str, object] | None = None,
    valid_from: datetime = AS_OF - timedelta(minutes=1),
    valid_to: datetime = AS_OF + timedelta(days=1),
) -> Signal:
    return Signal(
        strategy_id=strategy_id,
        version=version,
        symbol=symbol,
        side="long",
        target_weight=weight,
        confidence=0.8,
        valid_from=valid_from,
        valid_to=valid_to,
        evidence=evidence if evidence is not None else {"industry": "Alcohol"},
    )


def test_adapter_preserves_strategy_evidence_and_version():
    adapted = SignalAdapter().adapt([signal()], as_of=AS_OF)

    assert len(adapted.signals) == 1
    assert adapted.decisions == ()
    row = adapted.signals[0]
    assert row["strategy_id"] == "s1"
    assert row["version"] == "1.0.0"
    assert row["symbol"] == "sh600519"
    assert row["industry"] == "Alcohol"
    assert row["valid_from"] == (AS_OF - timedelta(minutes=1)).isoformat()
    assert row["valid_to"] == (AS_OF + timedelta(days=1)).isoformat()
    assert row["target_weight"] == 0.2
    assert row["evidence"] == {"industry": "Alcohol"}


def test_adapter_rejects_signal_with_missing_industry():
    adapted = SignalAdapter().adapt([signal(evidence={})], as_of=AS_OF)

    assert adapted.signals == ()
    assert [decision.reason_code for decision in adapted.decisions] == [
        "INDUSTRY_MISSING"
    ]
    assert [decision.symbol for decision in adapted.decisions] == [
        "sh600519"
    ]


def test_adapter_rejection_keeps_strategy_identity_traceable():
    adapted = SignalAdapter().adapt([signal(evidence={})], as_of=AS_OF)

    decision = adapted.decisions[0]
    assert decision.strategy_id == "s1"
    assert decision.version == "1.0.0"


def test_adapter_rejects_conflicting_industries_for_same_symbol():
    adapted = SignalAdapter().adapt(
        [
            signal(weight=0.1, evidence={"industry": "Alcohol"}),
            signal(
                strategy_id="s2",
                symbol="sh600519",
                weight=0.1,
                evidence={"industry": "Bank"},
            ),
        ],
        as_of=AS_OF,
    )

    assert adapted.signals == ()
    assert [decision.reason_code for decision in adapted.decisions] == [
        "INDUSTRY_CONFLICT",
        "INDUSTRY_CONFLICT",
    ]


def test_adapter_rejects_expired_signal():
    adapted = SignalAdapter().adapt([signal()], as_of=AS_OF + timedelta(days=1))

    assert adapted.signals == ()
    assert [decision.reason_code for decision in adapted.decisions] == [
        "SIGNAL_EXPIRED"
    ]


def test_adapter_rejects_not_yet_valid_signal():
    adapted = SignalAdapter().adapt([signal()], as_of=AS_OF - timedelta(minutes=2))

    assert adapted.signals == ()
    assert [decision.reason_code for decision in adapted.decisions] == [
        "SIGNAL_NOT_YET_VALID"
    ]


def test_adapter_rejects_duplicate_strategy_signal_for_same_symbol():
    adapted = SignalAdapter().adapt(
        [signal(weight=0.1), signal(weight=0.2)], as_of=AS_OF
    )

    assert adapted.signals == ()
    assert [decision.reason_code for decision in adapted.decisions] == [
        "DUPLICATE_STRATEGY_SIGNAL",
        "DUPLICATE_STRATEGY_SIGNAL",
    ]


def test_composer_uses_adapter_and_keeps_multi_strategy_weights_traceable():
    signals = [
        signal(weight=0.2),
        signal(
            strategy_id="s2",
            version="2.1.0",
            symbol="sh600519",
            weight=0.1,
            evidence={"industry": "Alcohol", "score": 3},
        ),
    ]
    composer = SignalComposer(PortfolioRiskConfig())

    result = composer.compose_domain(signals, as_of=AS_OF)

    assert len(result.targets) == 1
    target = result.targets[0]
    assert target.net_weight == pytest.approx(0.3)
    assert target.contributions == {"s1": 0.2, "s2": 0.1}
    assert target.strategy_versions == {"s1": "1.0.0", "s2": "2.1.0"}
    assert target.evidence == {
        "s1": {"industry": "Alcohol"},
        "s2": {"industry": "Alcohol", "score": 3},
    }


def test_composer_domain_uses_caller_decision_time_for_blacklist():
    domain_signal = signal(
        valid_from=AS_OF - timedelta(days=1),
        valid_to=AS_OF + timedelta(days=1),
    )
    composer = SignalComposer(
        PortfolioRiskConfig(
            constraints=[BlacklistConstraint(
                symbols={"sh600519"}, effective_from="2026-11-08"
            )]
        )
    )

    result = composer.compose_domain([domain_signal], as_of=AS_OF)

    assert result.targets[0].status == "rejected"
    assert result.targets[0].reason_code == "BLACKLIST"


def test_transitional_compose_rejects_non_mapping_evidence():
    composer = SignalComposer(PortfolioRiskConfig())

    with pytest.raises(ValueError, match="evidence must be a mapping"):
        composer.compose(
            [
                {
                    "strategy_id": "s1",
                    "symbol": "sh600519",
                    "industry": "Alcohol",
                    "target_weight": 0.2,
                    "valid_from": AS_OF.isoformat(),
                    "evidence": ["not-a-mapping"],
                }
            ]
        )
