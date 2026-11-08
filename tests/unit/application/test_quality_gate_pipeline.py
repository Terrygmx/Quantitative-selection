from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quant_agent.adapters.market_data import InMemoryMarketDataPort
from quant_agent.application.backtest import BacktestConfig
from quant_agent.application.paper_strategy import StrategyPaperOrchestrator
from quant_agent.application.strategy_backtest import StrategyBacktestOrchestrator
from quant_agent.domain.models import Instrument, Signal
from quant_agent.ports.market_data import (
    Bar,
    DataUnavailable,
    QualityEvent,
    QualityEventCollector,
)
from quant_agent.rules.trading import TradingRulesPlugin
from quant_agent.strategies.registry import StrategyMetadata, StrategyRegistry


CN_TZ = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 10, 26, 14, 45, tzinfo=CN_TZ)


def instrument(symbol: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        exchange="SSE",
        board="MainBoard",
        status="Active",
        listing_date=date(2010, 1, 1),
        tick=Decimal("0.01"),
        lot_size=100,
    )


def bar(symbol: str) -> Bar:
    return Bar(
        instrument=symbol,
        timestamp=AS_OF - timedelta(days=1),
        open=10,
        high=10,
        low=10,
        close=10,
        volume=1_000_000,
        amount=10_000_000,
        available_at=AS_OF - timedelta(days=1),
    )


class MissingDataThenSignalStrategy:
    metadata = StrategyMetadata(
        strategy_id="quality_sensitive",
        version="1.0.0",
        frequency="daily",
    )

    def _valid_signal(self, context) -> Signal:
        return Signal(
            strategy_id=self.metadata.strategy_id,
            version=self.metadata.version,
            symbol="sh600000",
            side="long",
            target_weight=0.1,
            confidence=1.0,
            valid_from=context.as_of,
            valid_to=context.as_of + timedelta(days=1),
            evidence={"industry": "Technology"},
        )

    def on_snapshot(self, context) -> list[Signal]:
        try:
            context.data_port.bars("missing", context.as_of)
        except DataUnavailable:
            pass
        return [self._valid_signal(context)]

    def config_fingerprint(self) -> dict[str, object]:
        return {"mode": "missing-data"}


class MissingDataRaisesStrategy(MissingDataThenSignalStrategy):
    def on_snapshot(self, context) -> list[Signal]:
        context.data_port.bars("missing", context.as_of)
        return []


class IntermittentDataStrategy(MissingDataThenSignalStrategy):
    def __init__(self) -> None:
        self.calls = 0

    def on_snapshot(self, context) -> list[Signal]:
        self.calls += 1
        if self.calls == 1:
            try:
                context.data_port.bars("missing", context.as_of)
            except DataUnavailable:
                pass
        return [self._valid_signal(context)]

    def config_fingerprint(self) -> dict[str, object]:
        return {"mode": "intermittent-data"}


class BlockThenCrashStrategy(MissingDataThenSignalStrategy):
    def on_snapshot(self, context) -> list[Signal]:
        try:
            context.data_port.bars("missing", context.as_of)
        except DataUnavailable:
            pass
        raise ZeroDivisionError("unrelated plugin bug")


class BlockedInvalidSignalStrategy(MissingDataThenSignalStrategy):
    def on_snapshot(self, context) -> list[Signal]:
        try:
            context.data_port.bars("sh600000", context.as_of)
        except DataUnavailable:
            pass
        signal = self._valid_signal(context)
        return [
            Signal(
                strategy_id=signal.strategy_id,
                version=signal.version,
                symbol=signal.symbol,
                side=signal.side,
                target_weight=signal.target_weight,
                confidence=signal.confidence,
                valid_from=signal.valid_from,
                valid_to=signal.valid_to,
                evidence={},
            )
        ]


class DirectSignalStrategy:
    metadata = StrategyMetadata(
        strategy_id="quality_sensitive",
        version="1.0.0",
        frequency="daily",
    )

    def on_snapshot(self, context) -> list[Signal]:
        return [
            Signal(
                strategy_id=self.metadata.strategy_id,
                version=self.metadata.version,
                symbol="sh600000",
                side="long",
                target_weight=0.1,
                confidence=1.0,
                valid_from=context.as_of,
                valid_to=context.as_of + timedelta(days=1),
                evidence={"industry": "Technology"},
            )
        ]

    def config_fingerprint(self) -> dict[str, object]:
        return {"mode": "direct"}


def registry(events: QualityEventCollector) -> StrategyRegistry:
    result = StrategyRegistry(quality_events=events)
    result.register(MissingDataThenSignalStrategy())
    return result


def paper_config() -> dict[str, object]:
    return {
        "strategy_config": {"universe": ["sh600000"]},
        "data": {
            "bars": [
                {
                    "instrument": "sh600000",
                    "timestamp": (AS_OF - timedelta(days=1)).isoformat(),
                    "available_at": (AS_OF - timedelta(days=1)).isoformat(),
                    "open": 10,
                    "high": 10,
                    "low": 10,
                    "close": 10,
                    "volume": 1_000_000,
                    "amount": 10_000_000,
                }
            ]
        },
        "instruments": [
            {
                "symbol": "sh600000",
                "exchange": "SSE",
                "board": "MainBoard",
                "status": "Active",
                "listing_date": "2010-01-01",
                "tick": "0.01",
                "lot_size": 100,
            }
        ],
        "market": {
            "sh600000": {
                "last": "10.00",
                "previous_close": "10.00",
                "tradable": True,
            }
        },
        "industry_by_symbol": {"sh600000": "Technology"},
    }


def test_collector_attributes_events_to_active_strategy():
    events = QualityEventCollector()
    collector_port = InMemoryMarketDataPort(
        [bar("sh600000")],
        quality_events=events,
    )
    strategy = MissingDataThenSignalStrategy()
    strategy_registry = StrategyRegistry(quality_events=events)
    strategy_registry.register(strategy)

    class Context:
        as_of = AS_OF
        data_port = collector_port

    strategy_registry.run_selected(("quality_sensitive",), Context())

    assert [event.level for event in events.events] == ["block"]
    assert events.events[0].strategy_id == "quality_sensitive"
    assert events.blocked_strategy_ids() == {"quality_sensitive"}


def test_backtest_pipeline_blocks_strategy_with_block_event():
    events = QualityEventCollector()
    orchestrator = StrategyBacktestOrchestrator(
        port=InMemoryMarketDataPort(
            [bar("sh600000")],
            quality_events=events,
        ),
        instruments={"sh600000": instrument("sh600000")},
        config=BacktestConfig(
            initial_cash=Decimal("100000.00"),
            buy_quantity=100,
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
        ),
        rules=TradingRulesPlugin(),
        registry=registry(events),
        strategy_ids=("quality_sensitive",),
        as_of=AS_OF,
        decision_time="1445",
        quality_events=events,
    )

    result = orchestrator.run()

    assert result["quality_events"][0]["strategy_id"] == "quality_sensitive"
    assert result["quality_summary"] == {
        "warn_count": 0,
        "block_count": 1,
        "blocked_strategies": ["quality_sensitive"],
    }
    assert any(
        decision["reason_code"] == "STRATEGY_BLOCKED"
        for decision in result["decisions"]
    )
    assert result["orders"] == []


def test_paper_pipeline_returns_block_decision_and_quality_summary():
    events = QualityEventCollector()
    orchestrator = StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(
            [bar("sh600000")],
            quality_events=events,
        ),
        instruments={"sh600000": instrument("sh600000")},
        registry=registry(events),
        rules=TradingRulesPlugin(),
        quality_events=events,
    )
    config = paper_config()

    plan = orchestrator.evaluate("quality_sensitive", config, AS_OF)

    assert plan.quality_summary.blocked_strategies == ("quality_sensitive",)
    assert plan.quality_summary.block_count == 1
    assert plan.execution_symbols == ()
    assert any(
        decision.reason_code == "STRATEGY_BLOCKED"
        for decision in plan.decisions
    )


def test_blocked_plugin_failure_does_not_abort_pipeline():
    events = QualityEventCollector()
    strategy_registry = StrategyRegistry(quality_events=events)
    strategy_registry.register(MissingDataRaisesStrategy())
    paper = StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(
            [bar("sh600000")],
            quality_events=events,
        ),
        instruments={"sh600000": instrument("sh600000")},
        registry=strategy_registry,
        rules=TradingRulesPlugin(),
        quality_events=events,
    )
    plan = paper.evaluate("quality_sensitive", paper_config(), AS_OF)

    assert plan.quality_summary.blocked_strategies == ("quality_sensitive",)
    assert plan.execution_symbols == ()
    assert any(
        decision.reason_code == "STRATEGY_BLOCKED"
        for decision in plan.decisions
    )


def test_pipeline_records_data_unavailable_from_unbound_port():
    class UnboundPort:
        def bars(self, symbol: str, as_of: datetime) -> list[Bar]:
            raise DataUnavailable(
                QualityEvent(
                    level="block",
                    reason_code="MISSING_REQUIRED_BAR",
                    symbol=symbol,
                    as_of=as_of,
                    message=f"missing {symbol}",
                    strategy_id="other",
                )
            )

    strategy_registry = StrategyRegistry()
    strategy_registry.register(MissingDataThenSignalStrategy())
    paper = StrategyPaperOrchestrator(
        port=UnboundPort(),
        instruments={"sh600000": instrument("sh600000")},
        registry=strategy_registry,
        rules=TradingRulesPlugin(),
    )

    plan = paper.evaluate("quality_sensitive", paper_config(), AS_OF)

    assert plan.quality_summary.blocked_strategies == ("quality_sensitive",)
    assert plan.quality_events[0].strategy_id == "quality_sensitive"
    assert plan.execution_symbols == ()
    assert any(
        decision.reason_code == "STRATEGY_BLOCKED"
        for decision in plan.decisions
    )


def test_unbound_port_emits_a_new_block_event_on_each_run():
    class UnboundPort:
        def bars(self, symbol: str, as_of: datetime) -> list[Bar]:
            raise DataUnavailable(
                QualityEvent(
                    level="block",
                    reason_code="MISSING_REQUIRED_BAR",
                    symbol=symbol,
                    as_of=as_of,
                    message=f"missing {symbol}",
                )
            )

    events = QualityEventCollector()
    strategy_registry = StrategyRegistry()
    strategy_registry.register(MissingDataThenSignalStrategy())
    paper = StrategyPaperOrchestrator(
        port=UnboundPort(),
        instruments={"sh600000": instrument("sh600000")},
        registry=strategy_registry,
        rules=TradingRulesPlugin(),
        quality_events=events,
    )

    first = paper.evaluate("quality_sensitive", paper_config(), AS_OF)
    second = paper.evaluate("quality_sensitive", paper_config(), AS_OF)

    assert first.quality_summary.block_count == 1
    assert second.quality_summary.block_count == 1
    assert first.quality_summary.blocked_strategies == (
        "quality_sensitive",
    )
    assert second.quality_summary.blocked_strategies == (
        "quality_sensitive",
    )
    assert first.execution_symbols == ()
    assert second.execution_symbols == ()
    assert len(events.events) == 2


def test_shared_registry_does_not_cross_bind_quality_collectors():
    first_events = QualityEventCollector()
    second_events = QualityEventCollector()
    strategy_registry = StrategyRegistry()
    strategy_registry.register(MissingDataThenSignalStrategy())
    first = StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(
            [bar("sh600000")],
            quality_events=first_events,
        ),
        instruments={"sh600000": instrument("sh600000")},
        registry=strategy_registry,
        rules=TradingRulesPlugin(),
        quality_events=first_events,
    )
    second = StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(
            [bar("sh600000")],
            quality_events=second_events,
        ),
        instruments={"sh600000": instrument("sh600000")},
        registry=strategy_registry,
        rules=TradingRulesPlugin(),
        quality_events=second_events,
    )

    first_plan = first.evaluate("quality_sensitive", paper_config(), AS_OF)
    second_plan = second.evaluate("quality_sensitive", paper_config(), AS_OF)

    assert first_plan.quality_summary.blocked_strategies == (
        "quality_sensitive",
    )
    assert second_plan.quality_summary.blocked_strategies == (
        "quality_sensitive",
    )
    assert first_events.events[0].strategy_id == "quality_sensitive"
    assert second_events.events[0].strategy_id == "quality_sensitive"


def test_previous_block_does_not_pollute_a_later_clean_run():
    events = QualityEventCollector()
    strategy_registry = StrategyRegistry()
    strategy_registry.register(IntermittentDataStrategy())
    paper = StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(
            [bar("sh600000")],
            quality_events=events,
        ),
        instruments={"sh600000": instrument("sh600000")},
        registry=strategy_registry,
        rules=TradingRulesPlugin(),
        quality_events=events,
    )

    first = paper.evaluate("quality_sensitive", paper_config(), AS_OF)
    second = paper.evaluate("quality_sensitive", paper_config(), AS_OF)

    assert first.quality_summary.blocked_strategies == ("quality_sensitive",)
    assert second.quality_summary.block_count == 0
    assert second.quality_summary.blocked_strategies == ()
    assert second.execution_symbols == ("sh600000",)


def test_block_event_does_not_hide_an_unrelated_plugin_crash():
    events = QualityEventCollector()
    strategy_registry = StrategyRegistry()
    strategy_registry.register(BlockThenCrashStrategy())
    paper = StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(
            [bar("sh600000")],
            quality_events=events,
        ),
        instruments={"sh600000": instrument("sh600000")},
        registry=strategy_registry,
        rules=TradingRulesPlugin(),
        quality_events=events,
    )

    with pytest.raises(ValueError, match="PLUGIN_CRASH"):
        paper.evaluate("quality_sensitive", paper_config(), AS_OF)


def test_strategy_block_decision_is_kept_alongside_other_rejections():
    events = QualityEventCollector()
    strategy_registry = StrategyRegistry()
    strategy_registry.register(BlockedInvalidSignalStrategy())
    paper = StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(
            [],
            quality_events=events,
        ),
        instruments={"sh600000": instrument("sh600000")},
        registry=strategy_registry,
        rules=TradingRulesPlugin(),
        quality_events=events,
    )

    plan = paper.evaluate("quality_sensitive", paper_config(), AS_OF)

    reasons = {decision.reason_code for decision in plan.decisions}
    assert "INDUSTRY_MISSING" in reasons
    assert "STRATEGY_BLOCKED" in reasons


def _direct_strategy_backtest(port, events):
    strategy_registry = StrategyRegistry()
    strategy_registry.register(DirectSignalStrategy())
    return StrategyBacktestOrchestrator(
        port=port,
        instruments={"sh600000": instrument("sh600000")},
        config=BacktestConfig(
            initial_cash=Decimal("100000.00"),
            buy_quantity=100,
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
        ),
        rules=TradingRulesPlugin(),
        registry=strategy_registry,
        strategy_ids=("quality_sensitive",),
        as_of=AS_OF,
        decision_time="1445",
        quality_events=events,
    )


def test_execution_read_block_fails_closed_before_order():
    events = QualityEventCollector()

    class BlockingBarPort:
        def __init__(self) -> None:
            self.quality_events = events

        def bars(self, symbol: str, as_of: datetime) -> list[Bar]:
            events.record(
                QualityEvent(
                    level="block",
                    reason_code="STALE_QUOTE",
                    symbol=symbol,
                    as_of=as_of,
                    message="execution data blocked",
                )
            )
            return [bar(symbol)]

    orchestrator = _direct_strategy_backtest(BlockingBarPort(), events)

    with pytest.raises(
        ValueError,
        match="data quality block during execution data read",
    ):
        orchestrator.run()


def test_execution_read_warn_is_included_in_quality_output():
    events = QualityEventCollector()

    class WarningBarPort:
        def __init__(self) -> None:
            self.quality_events = events

        def bars(self, symbol: str, as_of: datetime) -> list[Bar]:
            events.record(
                QualityEvent(
                    level="warn",
                    reason_code="STALE_QUOTE",
                    symbol=symbol,
                    as_of=as_of,
                    message="execution data warning",
                )
            )
            return [bar(symbol)]

    orchestrator = _direct_strategy_backtest(WarningBarPort(), events)

    result = orchestrator.run()

    assert result["quality_summary"] == {
        "warn_count": 1,
        "block_count": 0,
        "blocked_strategies": [],
    }
    assert result["quality_events"][0]["reason_code"] == "STALE_QUOTE"
    assert result["orders"][0]["status"] == "FILLED"
