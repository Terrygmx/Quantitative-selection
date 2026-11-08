from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_agent.adapters.market_data import InMemoryMarketDataPort
from quant_agent.application.backtest import BacktestConfig
from quant_agent.application.portfolio import BlacklistConstraint, PortfolioRiskConfig
from quant_agent.application.strategy_backtest import StrategyBacktestOrchestrator
from quant_agent.domain.models import Instrument, Signal
from quant_agent.ports.market_data import Bar, DataUnavailable, QualityEvent
from quant_agent.rules.trading import TradingRulesPlugin
from quant_agent.strategies.industry_rotation.strategy import IndustryRotationStrategy
from quant_agent.strategies.registry import StrategyMetadata, StrategyRegistry
from quant_agent.strategies.tail_momentum.scoring import (
    MinutePoint,
    QuoteSnapshot,
    StockInput,
    TailMomentumMarket,
)
from quant_agent.strategies.tail_momentum.strategy import TailMomentumStrategy
from quant_agent.strategies.trend_breakout.strategy import TrendBreakoutStrategy
from tail_momentum_selector import hhmm_to_min, parse_kline_batch, parse_minute, parse_quote_batch


CN_TZ = ZoneInfo("Asia/Shanghai")
AS_OF = datetime(2026, 9, 15, 14, 30, tzinfo=CN_TZ)
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "legacy"
INDEX_KEYS = (
    ("sh000001", "sh000001"),
    ("sz399001", "sz399001"),
    ("sz399006", "sz399006"),
    ("sh000300", "hs300"),
    ("sh000852", "zz1000"),
)


def instrument(symbol: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        exchange="SSE",
        board="MainBoard",
        status="Active",
        listing_date=date(2001, 8, 27),
        tick=Decimal("0.01"),
        lot_size=100,
    )


def daily_bar(
    symbol: str,
    day_offset: int,
    close: float,
    *,
    hour: int = 9,
    minute: int = 31,
) -> Bar:
    timestamp = AS_OF.replace(hour=hour, minute=minute) - timedelta(days=day_offset)
    return Bar(
        instrument=symbol,
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1_000_000.0,
        amount=close * 1_000_000.0,
        available_at=timestamp,
    )


def minute_bar(symbol: str, clock: str, price: float, volume: float, amount: float) -> Bar:
    hour, minute = int(clock[:2]), int(clock[2:])
    timestamp = AS_OF.replace(hour=hour, minute=minute)
    return Bar(
        instrument=symbol,
        timestamp=timestamp,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=volume,
        available_at=timestamp,
        amount=amount,
    )


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_market() -> TailMomentumMarket:
    quote = parse_quote_batch(read_fixture("quote_sh600176.md"))[
        "sh600176"
    ]
    kline = parse_kline_batch(
        read_fixture("kline_sh600176.md"),
        default_code="sh600176",
    )["sh600176"]
    stock = StockInput(
        quote=QuoteSnapshot(
            symbol="sh600176",
            name=quote["name"],
            previous_close=quote["prev_close"],
            open=quote["open"],
            price_ceiling=quote["price_ceiling"],
            price_floor=quote["price_floor"],
        ),
        daily=tuple(kline),
        minute=tuple(
            MinutePoint(
                time=row["time"],
                price=row["price"],
                volume=row["volume"],
                amount=row["amount"],
            )
            for row in parse_minute(read_fixture("minute_sh600176.md"))
        ),
    )
    index_quotes = parse_quote_batch(read_fixture("index_quote.md"))
    indices = {}
    for code, key in INDEX_KEYS:
        indices[key] = (
            index_quotes[code]["prev_close"],
            tuple(
                minute_bar(
                    code,
                    row["time"],
                    row["price"],
                    row["volume"],
                    row["amount"],
                )
                for row in parse_minute(read_fixture(f"index_minute_{code}.md"))
            ),
        )
    return TailMomentumMarket(
        date=AS_OF.date(),
        stocks=(stock,),
        indices=indices,
        breadth={"up": 3000, "down": 3000, "limitup": 40, "limitdown": 20},
    )


def passing_tail_momentum_port(symbol: str) -> InMemoryMarketDataPort:
    stock = fixture_market().stocks[0]
    minute = tuple(
        replace(
            row,
            price=(
                45.2 + (47.31 - 45.2) * hhmm_to_min(row.time) / 120
                if row.time <= "1130"
                else 47.31
                if row.time <= "1300"
                else 47.31 + (49.5 - 47.31) * (hhmm_to_min(row.time) - 120) / 120
            ),
        )
        for row in stock.minute
    )
    bars = [
        minute_bar(symbol, row.time, row.price, row.volume, row.amount)
        for row in minute
    ]
    return InMemoryMarketDataPort(bars)


def port_with_future_bars(symbol: str, closes: list[float]) -> InMemoryMarketDataPort:
    visible = [daily_bar(symbol, offset, close) for offset, close in enumerate(reversed(closes))]
    future = daily_bar(symbol, -1, closes[-1] * 10, hour=15)
    return InMemoryMarketDataPort([*visible, future])


def config() -> BacktestConfig:
    return BacktestConfig(
        initial_cash=Decimal("1000000.00"),
        buy_quantity=100,
        commission_rate=Decimal("0.0003"),
        stamp_tax_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.001"),
    )


def test_orchestrates_trend_strategy_and_records_full_audit_trail():
    closes = [9.0 + index * 0.05 for index in range(40)] + [11.5]
    port = port_with_future_bars("sh600519", closes)
    registry = StrategyRegistry()
    registry.register(TrendBreakoutStrategy(universe=["sh600519"]))
    orchestrator = StrategyBacktestOrchestrator(
        port=port,
        instruments={"sh600519": instrument("sh600519")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("trend_breakout",),
        as_of=AS_OF,
        decision_time="1430",
        industry_by_symbol={"sh600519": "Technology"},
    )

    result = orchestrator.run()

    assert [signal["strategy_id"] for signal in result["signals"]] == ["trend_breakout"]
    assert result["targets"][0]["symbol"] == "sh600519"
    assert result["targets"][0]["strategy_versions"] == {"trend_breakout": "0.1.0"}
    assert result["manifest"]["config_hash"] == orchestrator.config_hash
    assert result["orders"][0]["symbol"] == "sh600519"
    assert result["orders"][0]["status"] == "FILLED"
    assert result["fills"][0]["quantity"] == 100
    assert result["fills"][0]["timestamp"] == AS_OF.isoformat()
    assert result["summary"]["fill_count"] == 1


def test_orchestration_is_reproducible_and_uses_only_visible_data():
    closes = [9.0 + index * 0.05 for index in range(40)] + [11.5]

    def build():
        registry = StrategyRegistry()
        registry.register(TrendBreakoutStrategy(universe=["sh600519"]))
        return StrategyBacktestOrchestrator(
            port=port_with_future_bars("sh600519", closes),
            instruments={"sh600519": instrument("sh600519")},
            config=config(),
            rules=TradingRulesPlugin(),
            registry=registry,
            strategy_ids=("trend_breakout",),
            as_of=AS_OF,
            decision_time="1430",
        ).run()

    first = build()
    second = build()

    assert first["signals"] == second["signals"]
    assert first["targets"] == second["targets"]
    assert first["orders"] == second["orders"]
    assert first["fills"] == second["fills"]


def test_orchestrator_runs_only_selected_strategies():
    class ManualStrategy:
        def __init__(self, strategy_id: str, symbol: str):
            self.metadata = StrategyMetadata(
                strategy_id=strategy_id,
                version="0.1.0",
                frequency="daily",
            )
            self.symbol = symbol
            self.calls = 0

        def on_snapshot(self, context) -> list[Signal]:
            self.calls += 1
            return [
                Signal(
                    strategy_id=self.metadata.strategy_id,
                    version=self.metadata.version,
                    symbol=self.symbol,
                    side="long",
                    target_weight=0.1,
                    confidence=1.0,
                    valid_from=AS_OF,
                    valid_to=AS_OF + timedelta(days=1),
                    evidence={"industry": "Technology"},
                )
            ]

        def config_fingerprint(self) -> dict[str, object]:
            return {"symbol": self.symbol, "target_weight": 0.1}

    selected = ManualStrategy("selected", "sh600519")
    other = ManualStrategy("other", "sz000001")
    registry = StrategyRegistry()
    registry.register(selected)
    registry.register(other)
    orchestrator = StrategyBacktestOrchestrator(
        port=port_with_future_bars("sh600519", [10.0] * 30),
        instruments={
            "sh600519": instrument("sh600519"),
            "sz000001": instrument("sz000001"),
        },
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("selected",),
        as_of=AS_OF,
    )

    result = orchestrator.run()

    assert selected.calls == 1
    assert other.calls == 0
    assert [signal["strategy_id"] for signal in result["signals"]] == ["selected"]


def test_backtest_rejects_signal_with_foreign_strategy_identity():
    class ForeignStrategy:
        metadata = StrategyMetadata(
            strategy_id="selected",
            version="0.1.0",
            frequency="daily",
        )

        def on_snapshot(self, context) -> list[Signal]:
            return [
                Signal(
                    strategy_id="foreign",
                    version="9.9.9",
                    symbol="sh600519",
                    side="long",
                    target_weight=0.1,
                    confidence=1.0,
                    valid_from=AS_OF,
                    valid_to=AS_OF + timedelta(days=1),
                    evidence={"industry": "Technology"},
                )
            ]

        def config_fingerprint(self) -> dict[str, object]:
            return {"selected": "foreign-test"}

    registry = StrategyRegistry()
    registry.register(ForeignStrategy())
    orchestrator = StrategyBacktestOrchestrator(
        port=port_with_future_bars(
            "sh600519",
            [10.0] * 30,
        ),
        instruments={
            "sh600519": instrument("sh600519")
        },
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("selected",),
        as_of=AS_OF,
    )

    with pytest.raises(ValueError, match="foreign strategy identity"):
        orchestrator.run()


def test_adapted_signals_include_industry_for_the_output_contract():
    closes = [9.0 + index * 0.05 for index in range(40)] + [11.5]
    registry = StrategyRegistry()
    registry.register(TrendBreakoutStrategy(universe=["sh600519"]))
    orchestrator = StrategyBacktestOrchestrator(
        port=port_with_future_bars("sh600519", closes),
        instruments={"sh600519": instrument("sh600519")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("trend_breakout",),
        as_of=AS_OF,
        industry_by_symbol={"sh600519": "Technology"},
    )

    result = orchestrator.run()

    assert result["signals"][0]["industry"] == "Technology"


def test_equivalent_timezone_offsets_produce_the_same_run_identity():
    closes = [9.0 + index * 0.05 for index in range(40)] + [11.5]

    def build(as_of: datetime):
        registry = StrategyRegistry()
        registry.register(TrendBreakoutStrategy(universe=["sh600519"]))
        return StrategyBacktestOrchestrator(
            port=port_with_future_bars("sh600519", closes),
            instruments={"sh600519": instrument("sh600519")},
            config=config(),
            rules=TradingRulesPlugin(),
            registry=registry,
            strategy_ids=("trend_breakout",),
            as_of=as_of,
            decision_time=as_of.astimezone(CN_TZ).strftime("%H%M"),
            industry_by_symbol={"sh600519": "Technology"},
        )

    local = build(AS_OF)
    utc = build(AS_OF.astimezone(timezone.utc))

    assert local.config_hash == utc.config_hash
    assert local.run()["signals"] == utc.run()["signals"]


def test_as_of_seconds_are_accepted_with_minute_decision_clock():
    closes = [9.0 + index * 0.05 for index in range(40)] + [11.5]
    as_of = AS_OF.replace(second=30)
    registry = StrategyRegistry()
    registry.register(TrendBreakoutStrategy(universe=["sh600519"]))
    orchestrator = StrategyBacktestOrchestrator(
        port=port_with_future_bars("sh600519", closes),
        instruments={"sh600519": instrument("sh600519")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("trend_breakout",),
        as_of=as_of,
        decision_time="1430",
        industry_by_symbol={"sh600519": "Technology"},
    )

    result = orchestrator.run()

    assert result["fills"][0]["timestamp"] == as_of.isoformat()


def test_strategy_config_and_version_are_bound_into_config_hash():
    closes = [9.0 + index * 0.05 for index in range(40)] + [11.5]

    def build(config_value: dict[str, object]):
        registry = StrategyRegistry()
        registry.register(TrendBreakoutStrategy(universe=["sh600519"]))
        return StrategyBacktestOrchestrator(
            port=port_with_future_bars("sh600519", closes),
            instruments={"sh600519": instrument("sh600519")},
            config=config(),
            rules=TradingRulesPlugin(),
            registry=registry,
            strategy_ids=("trend_breakout",),
            as_of=AS_OF,
            industry_by_symbol={"sh600519": "Technology"},
            strategy_configs={"trend_breakout": config_value},
        )

    first = build({"universe": ["sh600519"]})
    second = build({"universe": ["sh600519", "sz000001"]})

    assert first.config_hash != second.config_hash


def test_config_hash_is_stable_for_equivalent_sets():
    closes = [9.0 + index * 0.05 for index in range(40)] + [11.5]

    def build(symbols: set[str]):
        registry = StrategyRegistry()
        registry.register(TrendBreakoutStrategy(universe=["sh600519"]))
        return StrategyBacktestOrchestrator(
            port=port_with_future_bars("sh600519", closes),
            instruments={"sh600519": instrument("sh600519")},
            config=config(),
            rules=TradingRulesPlugin(),
            registry=registry,
            strategy_ids=("trend_breakout",),
            as_of=AS_OF,
            industry_by_symbol={"sh600519": "Technology"},
            portfolio_risk=PortfolioRiskConfig(
                constraints=(BlacklistConstraint(symbols=symbols),)
            ),
        )

    first = build({"AAPL", "MSFT", "NVDA"})
    second = build({"NVDA", "AAPL", "MSFT"})

    assert first.config_hash == second.config_hash


def test_limit_move_is_rejected_against_true_previous_close():
    class ManualStrategy:
        metadata = StrategyMetadata(
            strategy_id="manual_signal",
            version="0.1.0",
            frequency="daily",
        )

        def on_snapshot(self, context) -> list[Signal]:
            return [
                Signal(
                    strategy_id="manual_signal",
                    version="0.1.0",
                    symbol="AAPL",
                    side="long",
                    target_weight=0.2,
                    confidence=1.0,
                    valid_from=AS_OF,
                    valid_to=AS_OF + timedelta(days=1),
                    evidence={"industry": "Technology"},
                )
            ]

        def config_fingerprint(self) -> dict[str, object]:
            return {"target_weight": 0.2}

    registry = StrategyRegistry()
    registry.register(ManualStrategy())
    port = InMemoryMarketDataPort(
        [
            daily_bar("AAPL", 1, 10.0),
            daily_bar("AAPL", 0, 12.0),
        ]
    )
    orchestrator = StrategyBacktestOrchestrator(
        port=port,
        instruments={"AAPL": instrument("AAPL")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("manual_signal",),
        as_of=AS_OF,
    )

    result = orchestrator.run()

    assert result["orders"][0]["status"] == "REJECTED"
    assert result["orders"][0]["rejection_code"] == "PRICE_BAND"
    assert result["fills"] == []


def test_malformed_plugin_output_fails_closed():
    class InvalidStrategy:
        metadata = StrategyMetadata(
            strategy_id="invalid",
            version="0.1.0",
            frequency="daily",
        )

        def on_snapshot(self, context) -> list[object]:
            return [{"symbol": "AAPL"}]

        def config_fingerprint(self) -> dict[str, object]:
            return {}

    registry = StrategyRegistry()
    registry.register(InvalidStrategy())
    orchestrator = StrategyBacktestOrchestrator(
        port=InMemoryMarketDataPort([daily_bar("AAPL", 0, 10.0)]),
        instruments={"AAPL": instrument("AAPL")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("invalid",),
        as_of=AS_OF,
    )

    with pytest.raises(ValueError, match="non-Signal"):
        orchestrator.run()


def test_plugin_cannot_read_a_future_as_of():
    class FutureReadStrategy:
        metadata = StrategyMetadata(
            strategy_id="future_read",
            version="0.1.0",
            frequency="daily",
        )

        def on_snapshot(self, context) -> list[Signal]:
            context.data_port.bars("AAPL", context.as_of + timedelta(days=1))
            return []

        def config_fingerprint(self) -> dict[str, object]:
            return {}

    registry = StrategyRegistry()
    registry.register(FutureReadStrategy())
    orchestrator = StrategyBacktestOrchestrator(
        port=InMemoryMarketDataPort([daily_bar("AAPL", 0, 10.0)]),
        instruments={"AAPL": instrument("AAPL")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("future_read",),
        as_of=AS_OF,
    )

    with pytest.raises(ValueError, match="PIT violation"):
        orchestrator.run()


def test_data_snapshot_records_reads_outside_configured_instruments():
    class ReaderStrategy:
        metadata = StrategyMetadata(
            strategy_id="reader",
            version="0.1.0",
            frequency="daily",
        )

        def __init__(self, read_extra: bool):
            self.read_extra = read_extra

        def on_snapshot(self, context) -> list[Signal]:
            if self.read_extra:
                context.data_port.bars("EXTRA", context.as_of)
            return []

        def config_fingerprint(self) -> dict[str, object]:
            return {"read_extra": self.read_extra}

    def snapshot(read_extra: bool) -> str:
        registry = StrategyRegistry()
        registry.register(ReaderStrategy(read_extra))
        orchestrator = StrategyBacktestOrchestrator(
            port=InMemoryMarketDataPort(
                [
                    daily_bar("AAPL", 0, 10.0),
                    daily_bar("EXTRA", 0, 20.0),
                ]
            ),
            instruments={"AAPL": instrument("AAPL")},
            config=config(),
            rules=TradingRulesPlugin(),
            registry=registry,
            strategy_ids=("reader",),
            as_of=AS_OF,
        )
        return orchestrator.run()["manifest"]["data_snapshot"]

    assert snapshot(False) != snapshot(True)


def test_config_hash_excludes_runtime_state_and_supports_slotted_plugins():
    class SlottedStrategy:
        __slots__ = ("calls",)

        metadata = StrategyMetadata(
            strategy_id="slotted",
            version="0.1.0",
            frequency="daily",
        )

        def __init__(self):
            self.calls = 0

        def on_snapshot(self, context) -> list[Signal]:
            self.calls += 1
            return []

        def config_fingerprint(self) -> dict[str, object]:
            return {"stable": True}

    registry = StrategyRegistry()
    registry.register(SlottedStrategy())
    orchestrator = StrategyBacktestOrchestrator(
        port=InMemoryMarketDataPort([daily_bar("AAPL", 0, 10.0)]),
        instruments={"AAPL": instrument("AAPL")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("slotted",),
        as_of=AS_OF,
    )
    before = orchestrator.config_hash

    orchestrator.run()

    assert orchestrator.config_hash == before


def test_open_and_close_difference_uses_latest_close_for_execution():
    class ManualStrategy:
        metadata = StrategyMetadata(
            strategy_id="manual_signal",
            version="0.1.0",
            frequency="daily",
        )

        def on_snapshot(self, context) -> list[Signal]:
            return [
                Signal(
                    strategy_id="manual_signal",
                    version="0.1.0",
                    symbol="AAPL",
                    side="long",
                    target_weight=0.2,
                    confidence=1.0,
                    valid_from=AS_OF,
                    valid_to=AS_OF + timedelta(days=1),
                    evidence={"industry": "Technology"},
                )
            ]

        def config_fingerprint(self) -> dict[str, object]:
            return {"target_weight": 0.2}

    registry = StrategyRegistry()
    registry.register(ManualStrategy())
    previous = daily_bar("AAPL", 1, 11.9)
    latest = Bar(
        instrument="AAPL",
        timestamp=AS_OF.replace(hour=9, minute=31),
        open=10.0,
        high=12.0,
        low=10.0,
        close=12.0,
        volume=1_000_000.0,
        available_at=AS_OF.replace(hour=9, minute=31),
        amount=12_000_000.0,
    )
    orchestrator = StrategyBacktestOrchestrator(
        port=InMemoryMarketDataPort([previous, latest]),
        instruments={"AAPL": instrument("AAPL")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("manual_signal",),
        as_of=AS_OF,
    )

    result = orchestrator.run()

    assert Decimal(result["fills"][0]["price"]) > Decimal("12")


def test_latest_prior_daily_bar_is_used_as_previous_close():
    class ManualStrategy:
        metadata = StrategyMetadata(
            strategy_id="manual_signal",
            version="0.1.0",
            frequency="daily",
        )

        def on_snapshot(self, context) -> list[Signal]:
            return [
                Signal(
                    strategy_id="manual_signal",
                    version="0.1.0",
                    symbol="AAPL",
                    side="long",
                    target_weight=0.2,
                    confidence=1.0,
                    valid_from=AS_OF,
                    valid_to=AS_OF + timedelta(days=1),
                    evidence={"industry": "Technology"},
                )
            ]

        def config_fingerprint(self) -> dict[str, object]:
            return {"target_weight": 0.2}

    registry = StrategyRegistry()
    registry.register(ManualStrategy())
    orchestrator = StrategyBacktestOrchestrator(
        port=InMemoryMarketDataPort(
            [
                daily_bar("AAPL", 2, 5.0),
                daily_bar("AAPL", 1, 10.0),
            ]
        ),
        instruments={"AAPL": instrument("AAPL")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("manual_signal",),
        as_of=AS_OF,
    )

    result = orchestrator.run()

    assert result["orders"][0]["status"] == "FILLED"
    assert Decimal(result["fills"][0]["price"]) > Decimal("10")


def test_intraday_previous_close_uses_previous_trading_day_not_previous_minute():
    class ManualStrategy:
        metadata = StrategyMetadata(
            strategy_id="manual_signal",
            version="0.1.0",
            frequency="intraday",
        )

        def on_snapshot(self, context) -> list[Signal]:
            return [
                Signal(
                    strategy_id="manual_signal",
                    version="0.1.0",
                    symbol="AAPL",
                    side="long",
                    target_weight=0.2,
                    confidence=1.0,
                    valid_from=AS_OF,
                    valid_to=AS_OF + timedelta(hours=1),
                    evidence={"industry": "Technology"},
                )
            ]

        def config_fingerprint(self) -> dict[str, object]:
            return {"target_weight": 0.2}

    previous_day = Bar(
        instrument="AAPL",
        timestamp=AS_OF - timedelta(days=1),
        open=10.0,
        high=10.0,
        low=10.0,
        close=10.0,
        volume=1_000_000.0,
        available_at=AS_OF - timedelta(days=1),
        amount=10_000_000.0,
    )
    previous_minute = Bar(
        instrument="AAPL",
        timestamp=AS_OF.replace(hour=14, minute=29),
        open=19.9,
        high=19.9,
        low=19.9,
        close=19.9,
        volume=1_000_000.0,
        available_at=AS_OF.replace(hour=14, minute=29),
        amount=19_900_000.0,
    )
    latest = Bar(
        instrument="AAPL",
        timestamp=AS_OF,
        open=20.0,
        high=20.0,
        low=20.0,
        close=20.0,
        volume=1_000_000.0,
        available_at=AS_OF,
        amount=20_000_000.0,
    )
    registry = StrategyRegistry()
    registry.register(ManualStrategy())
    orchestrator = StrategyBacktestOrchestrator(
        port=InMemoryMarketDataPort([previous_day, previous_minute, latest]),
        instruments={"AAPL": instrument("AAPL")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("manual_signal",),
        as_of=AS_OF,
    )

    result = orchestrator.run()

    assert result["orders"][0]["status"] == "REJECTED"
    assert result["orders"][0]["rejection_code"] == "PRICE_BAND"


def test_adapter_rejects_trend_signal_without_industry():
    closes = [9.0 + index * 0.05 for index in range(40)] + [11.5]
    registry = StrategyRegistry()
    registry.register(TrendBreakoutStrategy(universe=["sh600519"]))
    orchestrator = StrategyBacktestOrchestrator(
        port=port_with_future_bars("sh600519", closes),
        instruments={"sh600519": instrument("sh600519")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("trend_breakout",),
        as_of=AS_OF,
        decision_time="1430",
    )

    assert orchestrator.industry_by_symbol == {}

    result = orchestrator.run()

    assert result["signals"] == []

    assert [decision["reason_code"] for decision in result["decisions"]] == [
        "INDUSTRY_MISSING"
    ]
    assert result["orders"] == []


def test_orchestrates_tail_momentum_strategy_end_to_end():
    symbol = "sh600176"
    market = fixture_market()
    stock = market.stocks[0]
    registry = StrategyRegistry()
    registry.register(
        TailMomentumStrategy(
            universe=[symbol],
            history=tuple(
                {
                    "date": row["date"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                    "amount": row["amount"],
                }
                for row in stock.daily
            ),
            indices=market.indices,
            breadth=market.breadth,
            quotes={
                symbol: {
                    "name": stock.quote.name,
                    "prev_close": stock.quote.previous_close,
                    "open": stock.quote.open,
                    "price_ceiling": stock.quote.price_ceiling,
                    "price_floor": stock.quote.price_floor,
                }
            },
        )
    )
    orchestrator = StrategyBacktestOrchestrator(
        port=passing_tail_momentum_port(symbol),
        instruments={symbol: instrument(symbol)},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("tail_momentum_overnight",),
        as_of=AS_OF,
        decision_time="1430",
        industry_by_symbol={symbol: "Technology"},
        previous_close_by_symbol={symbol: market.stocks[0].quote.previous_close},
    )

    result = orchestrator.run()

    assert [signal["strategy_id"] for signal in result["signals"]] == [
        "tail_momentum_overnight"
    ]
    assert result["targets"][0]["symbol"] == symbol
    assert result["orders"][0]["symbol"] == symbol
    assert result["orders"][0]["status"] == "FILLED"
    assert result["summary"]["fill_count"] == 1


def test_missing_visible_bar_fails_closed_before_execution():
    class EmptyPort:
        def bars(self, symbol: str, as_of: datetime) -> list[Bar]:
            raise DataUnavailable(
                QualityEvent(
                    level="block",
                    reason_code="MISSING_REQUIRED_BAR",
                    symbol=symbol,
                    as_of=as_of,
                    message="missing bar",
                )
            )

    registry = StrategyRegistry()
    registry.register(TrendBreakoutStrategy(universe=["sh600519"]))
    orchestrator = StrategyBacktestOrchestrator(
        port=EmptyPort(),
        instruments={"sh600519": instrument("sh600519")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("trend_breakout",),
        as_of=AS_OF,
    )

    with pytest.raises(ValueError, match="strategy plugins failed"):
        orchestrator.run()


def test_industry_rotation_strategy_can_be_orchestrated():
    hot = [10.0 * (1 + 0.01) ** index for index in range(21)]
    cold = [10.0 * (1 - 0.005) ** index for index in range(21)]
    port = InMemoryMarketDataPort(
        [daily_bar("bk_hot", offset, close) for offset, close in enumerate(reversed(hot))]
        + [daily_bar("bk_cold", offset, close) for offset, close in enumerate(reversed(cold))]
    )
    registry = StrategyRegistry()
    registry.register(
        IndustryRotationStrategy(
            industry_universe={"tech": "bk_hot", "utility": "bk_cold"},
            top_n=1,
        )
    )
    orchestrator = StrategyBacktestOrchestrator(
        port=port,
        instruments={symbol: instrument(symbol) for symbol in ("bk_hot", "bk_cold")},
        config=config(),
        rules=TradingRulesPlugin(),
        registry=registry,
        strategy_ids=("industry_rotation",),
        as_of=AS_OF,
        decision_time="1430",
        industry_by_symbol={"sh600519": "Technology"},
    )

    result = orchestrator.run()

    assert [signal["symbol"] for signal in result["signals"]] == ["bk_hot"]
    assert result["orders"][0]["symbol"] == "bk_hot"
    assert result["orders"][0]["status"] == "FILLED"
