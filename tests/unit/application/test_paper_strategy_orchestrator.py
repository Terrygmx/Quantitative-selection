from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quant_agent.adapters.market_data import InMemoryMarketDataPort
from quant_agent.application.paper_strategy import (
    StrategyPaperOrchestrator,
    validate_paper_config,
)
from quant_agent.application.portfolio import (
    BlacklistConstraint,
    PortfolioRiskConfig,
)
from quant_agent.domain.models import Instrument, Signal
from quant_agent.ports.market_data import Bar
from quant_agent.rules.trading import TradingRulesPlugin
from quant_agent.strategies.registry import StrategyMetadata, StrategyRegistry

CN_TZ = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 10, 26, 14, 45, tzinfo=CN_TZ)
SYMBOL = "sh600000"


def instrument(symbol: str = SYMBOL) -> Instrument:
    return Instrument(
        symbol=symbol,
        exchange="SSE",
        board="MainBoard",
        status="Active",
        listing_date=date(2001, 1, 1),
        tick=Decimal("0.01"),
        lot_size=100,
    )


def bars(symbol: str = SYMBOL) -> list[Bar]:
    return [
        Bar(
            instrument=symbol,
            timestamp=AS_OF - timedelta(days=offset),
            open=10.0,
            high=10.2,
            low=9.8,
            close=10.0,
            volume=1_000_000,
            amount=10_000_000,
            available_at=AS_OF - timedelta(days=offset),
        )
        for offset in range(3)
    ]


def bar_rows(symbol: str = SYMBOL) -> list[dict[str, object]]:
    return [
        {
            "instrument": bar.instrument,
            "timestamp": bar.timestamp.isoformat(),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "amount": bar.amount,
            "available_at": bar.available_at.isoformat(),
        }
        for bar in bars(symbol)
    ]


def config(symbol: str = SYMBOL) -> dict[str, object]:
    return {
        "strategy_config": {"universe": [symbol]},
        "data": {"bars": bar_rows(symbol)},
        "instruments": [
            {
                "symbol": symbol,
                "exchange": "SSE",
                "board": "MainBoard",
                "status": "Active",
                "listing_date": "2001-01-01",
                "tick": "0.01",
                "lot_size": 100,
            }
        ],
        "market": {
            symbol: {
                "last": "10.05",
                "previous_close": "10.00",
                "tradable": True,
            }
        },
        "execution": {"initial_cash": "100000.00", "buy_quantity": 100},
        "industry_by_symbol": {symbol: "Technology"},
    }


class ManualStrategy:
    metadata = StrategyMetadata(
        strategy_id="manual",
        version="2.3.4",
        frequency="daily",
    )

    def __init__(
        self,
        *,
        symbol: str = SYMBOL,
        signals: bool = True,
        fingerprint: str = "manual-v1",
        signal_strategy_id: str = "manual",
        signal_version: str = "2.3.4",
    ):
        self.symbol = symbol
        self.has_signals = signals
        self.fingerprint = fingerprint
        self.signal_strategy_id = signal_strategy_id
        self.signal_version = signal_version
        self.contexts = []

    def on_snapshot(self, context) -> list[Signal]:
        self.contexts.append(context)
        context.data_port.bars(self.symbol, context.as_of)
        if not self.has_signals:
            return []
        return [
            Signal(
                strategy_id=self.signal_strategy_id,
                version=self.signal_version,
                symbol=self.symbol,
                side="long",
                target_weight=0.25,
                confidence=1.0,
                valid_from=context.as_of,
                valid_to=context.as_of + timedelta(days=1),
                evidence={"industry": "Technology"},
            )
        ]

    def config_fingerprint(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "has_signals": self.has_signals,
            "fingerprint": self.fingerprint,
        }


def orchestrator(
    *,
    strategy: ManualStrategy | None = None,
    risk: PortfolioRiskConfig | None = None,
    rules: TradingRulesPlugin | None = None,
) -> StrategyPaperOrchestrator:
    plugin = strategy or ManualStrategy()
    registry = StrategyRegistry()
    registry.register(plugin)
    return StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(bars(plugin.symbol)),
        instruments={plugin.symbol: instrument(plugin.symbol)},
        registry=registry,
        rules=rules or TradingRulesPlugin(),
        portfolio_risk=risk,
    )


def test_runs_registered_strategy_through_composition_and_records_manifest():
    strategy = ManualStrategy()
    paper = orchestrator(strategy=strategy)

    plan = paper.evaluate("manual", config(), AS_OF)

    assert strategy.contexts[0].as_of == AS_OF
    assert [signal["strategy_id"] for signal in plan.signals] == ["manual"]
    assert plan.targets[0].status == "accepted"
    assert plan.execution_symbols == (SYMBOL,)
    assert plan.source_signal_count == 1
    assert plan.strategy_version == "2.3.4"
    assert plan.manifest.config_hash == plan.config_hash
    assert plan.manifest.data_snapshot == plan.data_snapshot


def test_risk_rejected_target_is_not_forwarded_to_execution():
    paper = orchestrator(
        risk=PortfolioRiskConfig(
            constraints=(BlacklistConstraint(symbols={SYMBOL}),)
        )
    )

    plan = paper.evaluate("manual", config(), AS_OF)

    assert plan.targets[0].status == "rejected"
    assert plan.targets[0].reason_code == "BLACKLIST"
    assert plan.execution_symbols == ()
    assert any(
        decision.reason_code == "BLACKLIST" for decision in plan.decisions
    )


def test_no_signal_produces_an_empty_execution_plan():
    paper = orchestrator(strategy=ManualStrategy(signals=False))

    plan = paper.evaluate("manual", config(), AS_OF)

    assert plan.signals == ()
    assert plan.targets == ()
    assert plan.execution_symbols == ()
    assert plan.source_signal_count == 0


def test_future_data_access_fails_closed():
    class FutureStrategy(ManualStrategy):
        def on_snapshot(self, context) -> list[Signal]:
            context.data_port.bars(
                self.symbol, context.as_of + timedelta(minutes=1)
            )
            return []

    paper = orchestrator(strategy=FutureStrategy())

    with pytest.raises(ValueError, match="PIT violation"):
        paper.evaluate("manual", config(), AS_OF)


def test_strategy_signal_identity_must_match_registered_plugin():
    paper = orchestrator(
        strategy=ManualStrategy(
            signal_strategy_id="foreign",
            signal_version="9.9.9",
        )
    )

    with pytest.raises(ValueError, match="foreign strategy identity"):
        paper.evaluate("manual", config(), AS_OF)


def test_config_hash_and_data_snapshot_are_reproducible_and_enforced():
    paper = orchestrator()
    first = paper.identity("manual", config(), AS_OF).config_hash
    second = paper.identity("manual", config(), AS_OF).config_hash
    payload = config()
    payload["config_hash"] = first

    plan = paper.evaluate("manual", payload, AS_OF)

    assert first == second
    assert plan.config_hash == first
    assert plan.data_snapshot == plan.read_snapshot
    assert len(plan.data_snapshot) == 64
    payload["config_hash"] = "stale"
    with pytest.raises(ValueError, match="config_hash"):
        paper.evaluate("manual", payload, AS_OF)


def test_identity_binds_actual_plugin_risk_and_rules_state():
    baseline = orchestrator().identity("manual", config(), AS_OF).config_hash
    different_plugin = orchestrator(
        strategy=ManualStrategy(fingerprint="manual-v2")
    ).identity("manual", config(), AS_OF).config_hash
    different_risk = orchestrator(
        risk=PortfolioRiskConfig(
            constraints=(BlacklistConstraint(symbols={SYMBOL}),)
        )
    ).identity("manual", config(), AS_OF).config_hash
    from quant_agent.rules.calendar import StaticTradingCalendar

    different_rules = orchestrator(
        rules=TradingRulesPlugin(
            StaticTradingCalendar({date(2026, 10, 26)})
        )
    ).identity("manual", config(), AS_OF).config_hash

    assert len({baseline, different_plugin, different_risk, different_rules}) == 4


def test_equivalent_timezone_offsets_have_the_same_paper_identity():
    paper = orchestrator()

    local = paper.identity("manual", config(), AS_OF)
    utc = paper.identity("manual", config(), AS_OF.astimezone(timezone.utc))

    assert local.config_hash == utc.config_hash
    assert local.as_of == utc.as_of


def test_accepted_target_requires_positive_previous_close():
    payload = config()
    payload["market"] = {
        SYMBOL: {"last": "10.05", "tradable": True}
    }

    with pytest.raises(ValueError, match="previous_close"):
        orchestrator().evaluate("manual", payload, AS_OF)


def test_paper_config_rejects_unknown_keys_and_numeric_previous_close():
    payload = config()
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="unknown"):
        validate_paper_config(payload)

    payload = config()
    payload["previous_close_by_symbol"] = {SYMBOL: 10.0}
    with pytest.raises(ValueError, match="previous_close"):
        validate_paper_config(payload)


def test_same_identity_with_different_pit_reads_has_different_snapshot():
    strategy = ManualStrategy()
    registry = StrategyRegistry()
    registry.register(strategy)
    visible = bars()
    changed = [replace(bar, close=bar.close + 1) for bar in visible]
    kwargs = {
        "instruments": {SYMBOL: instrument()},
        "registry": registry,
        "rules": TradingRulesPlugin(),
    }
    first = StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(visible),
        **kwargs,
    )
    second = StrategyPaperOrchestrator(
        port=InMemoryMarketDataPort(changed),
        **kwargs,
    )

    first_plan = first.evaluate("manual", config(), AS_OF)
    second_plan = second.evaluate("manual", config(), AS_OF)

    assert first_plan.config_hash == second_plan.config_hash
    assert first_plan.data_snapshot != second_plan.data_snapshot
