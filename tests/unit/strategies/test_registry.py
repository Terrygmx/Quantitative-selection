
import pytest

from quant_agent.strategies.registry import StrategyMetadata, StrategyRegistry
from quant_agent.strategies.tail_momentum import TailMomentumStrategy


@pytest.fixture
def registry():
    return StrategyRegistry()


def test_registry_discovers_registered_plugin(registry):
    strategy = TailMomentumStrategy()
    registry.register(strategy)

    assert registry.get("tail_momentum_overnight") is strategy
    assert [item.strategy_id for item in registry.list()] == [
        "tail_momentum_overnight"
    ]


def test_registry_rejects_duplicate_ids(registry):
    strategy = TailMomentumStrategy()
    registry.register(strategy)

    with pytest.raises(ValueError, match="duplicate"):
        registry.register(strategy)


def test_registry_unknown_strategy_fails_clearly(registry):
    with pytest.raises(KeyError, match="unknown strategy"):
        registry.get("missing")


def test_tail_momentum_declares_full_history_warmup():
    assert TailMomentumStrategy().warmup() == 25


def test_registry_supports_enable_disable_and_version_rollback():
    class Versioned:
        def __init__(self, version):
            self.metadata = StrategyMetadata(
                strategy_id="roll", version=version, frequency="daily",
                turnover_cap=0.3, risk_exposure="market_neutral",
            )

    registry = StrategyRegistry()
    registry.register(Versioned("1.0.0"))
    registry.register(Versioned("1.1.0"))

    # The registered instance is the newest version.
    assert registry.get("roll").metadata.version == "1.1.0"
    assert registry.list() == [
        StrategyMetadata("roll", "1.1.0", "daily", turnover_cap=0.3,
                         risk_exposure="market_neutral")
    ]

    # Disabled strategies stay registered but are excluded from listing/run.
    registry.disable("roll")
    assert registry.get("roll").metadata.version == "1.1.0"
    assert registry.list() == []
    with pytest.raises(ValueError, match="disabled"):
        registry.run_all(None)

    registry.enable("roll")
    assert registry.list() != []

    # Roll back to the earlier version: get/list/run use it, newest stays.
    registry.rollback("roll", "1.0.0")
    assert registry.get("roll").metadata.version == "1.0.0"
    assert registry.list()[0].version == "1.0.0"

    with pytest.raises(KeyError):
        registry.rollback("roll", "9.9.9")
