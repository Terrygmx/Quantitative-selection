import pytest

from quant_agent.strategies.registry import StrategyRegistry


class GoodStrategy:
    from quant_agent.strategies.registry import StrategyMetadata

    metadata = StrategyMetadata("good", "1.0", "daily")

    def on_snapshot(self, context):
        return ["signal"]


class ExplodingStrategy:
    from quant_agent.strategies.registry import StrategyMetadata

    metadata = StrategyMetadata("bad", "1.0", "daily")

    def on_snapshot(self, context):
        raise RuntimeError("boom")


def test_registry_isolates_failing_plugins_and_audits_failure():
    registry = StrategyRegistry()
    registry.register(ExplodingStrategy())
    registry.register(GoodStrategy())

    result = registry.run_all(None)

    assert list(result.signals) == ["signal"]
    assert len(result.failures) == 1
    assert result.failures[0].strategy_id == "bad"
    assert result.failures[0].reason_code == "PLUGIN_CRASH"
    assert "boom" in result.failures[0].message


def test_registry_run_all_requires_registered_strategies():
    with pytest.raises(ValueError, match="No registered strategies"):
        StrategyRegistry().run_all(None)
