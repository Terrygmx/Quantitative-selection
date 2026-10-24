from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from quant_agent.application.backtest import BacktestConfig, BacktestEngine
from quant_agent.domain.models import Instrument
from quant_agent.rules.trading import Portfolio as RulesPortfolio, Position as RulesPosition, TradingRulesPlugin


D1 = date(2026, 9, 14)
D2 = date(2026, 9, 15)
D3 = date(2026, 9, 16)
TS1 = datetime(2026, 9, 14, 14, 31, tzinfo=timezone.utc)
TS2 = datetime(2026, 9, 15, 9, 31, tzinfo=timezone.utc)
TS3 = datetime(2026, 9, 16, 9, 31, tzinfo=timezone.utc)


@pytest.fixture
def basic_config():
    return BacktestConfig(
        initial_cash=Decimal("10000.00"),
        buy_quantity=100,
        commission_rate=Decimal("0.0003"),
        stamp_tax_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.001"),
    )


@pytest.fixture
def engine(basic_config):
    bars = [
        {"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"},
        {"date": D2, "open": "10.20", "close": "10.30", "previous_close": "10.10"},
        {"date": D3, "open": "10.40", "close": "10.50", "previous_close": "10.30"},
    ]
    return BacktestEngine(
        bars=bars,
        config=basic_config,
        instrument=Instrument(
            symbol="sh600519",
            exchange="SSE",
            board="MainBoard",
            status="Active",
            listing_date=date(2001, 8, 27),
            tick=Decimal("0.01"),
            lot_size=100,
        ),
        rules=TradingRulesPlugin(),
    )


def test_buy_signal_fills_next_open_and_honors_t_plus_one(engine):
    events = engine.run()

    assert [event.kind for event in events] == [
        "SIGNAL",
        "ORDER",
        "FILL",
        "ORDER",
        "REJECTION",
        "SESSION_SETTLE",
    ]
    assert events[0].as_of == TS1
    assert events[1].order.side == "buy"
    assert events[2].fill.price == Decimal("10.21020")
    assert events[2].fill.quantity == 100
    assert events[2].cash_after == Decimal("8978.673694000")
    assert events[3].order.side == "sell"
    assert events[3].as_of == TS2
    assert events[4].rejection.code == "T1_UNSETTLED"
    assert engine.equity(D3, Decimal("10.50")) == Decimal("10028.673694000")


def test_after_settlement_sell_fills_next_open(engine):
    engine.run()
    events = engine.sell_settled(D3, Decimal("10.40"), timestamp=TS3)

    assert [event.kind for event in events] == ["ORDER", "FILL"]
    assert events[-1].fill.price == Decimal("10.38960")
    assert events[-1].cash_after == Decimal("10016.802526000")
    assert engine.position.settled_qty == 0


def test_engine_rejects_same_bar_close_signal_and_fill(engine):
    with pytest.raises(ValueError, match="same bar"):
        engine.same_bar_close_signal_and_fill(D1, Decimal("10.10"))


def test_engine_requires_rules_plugin(basic_config):
    with pytest.raises(ValueError, match="instrument"):
        BacktestEngine(bars=[], config=basic_config)


def test_engine_routes_orders_through_rules(engine):
    called = {}
    original_validate = engine.rules.validate_order

    def validate(order, portfolio, market):
        called[order.side] = True
        return original_validate(order, portfolio, market)

    engine.rules.validate_order = validate
    engine.run()

    assert called == {"buy": True, "sell": True}


def test_sell_settled_is_rejected_by_trading_rules(engine):
    from quant_agent.rules.trading import MarketSnapshot

    original_validate = engine.rules.validate_order

    def rejecting_validate(order, portfolio, market):
        if order.side == "sell":
            from quant_agent.rules.trading import Rejection

            return [Rejection("LIMIT_DOWN", "test rejection")]
        return original_validate(order, portfolio, market)

    engine.rules.validate_order = rejecting_validate
    events = engine.run()
    engine.rules.validate_order = rejecting_validate
    result = engine.sell_settled(D3, Decimal("10.40"), timestamp=TS3)

    assert [event.kind for event in result] == ["ORDER", "REJECTION"]
    assert result[-1].rejection.code == "LIMIT_DOWN"
    assert engine.position.settled_qty == 100


def test_sell_settled_routes_market_snapshot_through_rules(engine):
    captured = {}
    original_validate = engine.rules.validate_order

    def validate(order, portfolio, market):
        captured[order.side] = type(market).__name__
        return original_validate(order, portfolio, market)

    engine.rules.validate_order = validate
    engine.run()
    engine.sell_settled(D3, Decimal("10.40"), timestamp=TS3)

    assert captured == {"buy": "dict", "sell": "MarketSnapshot"}
