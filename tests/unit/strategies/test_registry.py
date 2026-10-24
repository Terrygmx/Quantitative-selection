
import pytest

from quant_agent.strategies.registry import StrategyRegistry
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
