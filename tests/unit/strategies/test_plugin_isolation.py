from datetime import datetime, timezone

import pytest

from quant_agent.ports.market_data import (
    DataUnavailable,
    QualityEvent,
    QualityEventCollector,
)
from quant_agent.strategies.registry import StrategyRegistry


class GoodStrategy:
    from quant_agent.strategies.registry import StrategyMetadata

    metadata = StrategyMetadata("good", "1.0", "daily")

    def on_snapshot(self, context):
        return ["signal"]

    def config_fingerprint(self):
        return {"strategy_id": "good"}


class ExplodingStrategy:
    from quant_agent.strategies.registry import StrategyMetadata

    metadata = StrategyMetadata("bad", "1.0", "daily")

    def on_snapshot(self, context):
        raise RuntimeError("boom")

    def config_fingerprint(self):
        return {"strategy_id": "bad"}


class MissingDataStrategy:
    from quant_agent.strategies.registry import StrategyMetadata

    metadata = StrategyMetadata("missing", "1.0", "daily")

    def on_snapshot(self, context):
        now = datetime(2026, 9, 15, tzinfo=timezone.utc)
        raise DataUnavailable(
            QualityEvent(
                "block",
                "MISSING_REQUIRED_BAR",
                "sh600000",
                now,
                "missing",
            )
        )

    def config_fingerprint(self):
        return {"strategy_id": "missing"}


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


def test_registry_identifies_data_unavailable_failures():
    registry = StrategyRegistry()
    registry.register(MissingDataStrategy())

    result = registry.run_all(None)

    assert result.failures[0].reason_code == "DATA_UNAVAILABLE"


def test_registry_rejects_a_data_port_without_the_run_collector():
    class Context:
        data_port = object()

    registry = StrategyRegistry(quality_events=QualityEventCollector())
    registry.register(GoodStrategy())

    with pytest.raises(ValueError, match="quality collector must be shared"):
        registry.run_selected(("good",), Context())
