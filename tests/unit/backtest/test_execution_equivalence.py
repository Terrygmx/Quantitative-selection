"""Cross-engine equivalence: the paper executor and the multi-instrument
backtest engine must share one fill channel (DETAILED_DESIGN §7, FR-3.4).
The same economics fed to both engines must produce the same fill prices,
fees, cash and positions; the backtest must not grant itself privileges."""

import pytest
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from quant_agent.agents.paper import PaperExecutionConfig, SimulatedPaperExecution
from quant_agent.application.backtest import (
    MultiInstrumentBacktestConfig,
    MultiInstrumentBacktestEngine,
)
from quant_agent.domain.models import Instrument
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin


CN_TZ = ZoneInfo("Asia/Shanghai")
D1 = date(2026, 9, 14)
D2 = date(2026, 9, 15)
SYMBOL = "sh600519"


def instrument(symbol, status="Active"):
    return Instrument(
        symbol=symbol,
        exchange="SSE",
        board="MainBoard",
        status=status,
        listing_date=date(2010, 1, 1),
        tick=Decimal("0.01"),
        lot_size=100,
    )


def rules():
    return TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE"))


def economics(**overrides):
    defaults = {
        "initial_cash": Decimal("10000.00"),
        "commission_rate": Decimal("0.0003"),
        "stamp_tax_rate": Decimal("0.0005"),
        "slippage_rate": Decimal("0.001"),
    }
    defaults.update(overrides)
    return defaults


def paper_engine(costs, status="Active"):
    config = PaperExecutionConfig(buy_quantity=100, **costs)
    return SimulatedPaperExecution(
        config=config,
        instruments={SYMBOL: instrument(SYMBOL, status=status)},
        rules=rules(),
    )


def backtest_engine(costs, bars, status="Active"):
    return MultiInstrumentBacktestEngine(
        bars={SYMBOL: bars},
        instruments={SYMBOL: instrument(SYMBOL, status=status)},
        config=MultiInstrumentBacktestConfig(buy_quantity=100, **costs),
        rules=rules(),
    )


def buy_config(last, previous_close):
    return {
        "config_hash": "hash-1",
        "universe": [SYMBOL],
        "market": {
            SYMBOL: {
                "last": last,
                "previous_close": previous_close,
                "tradable": True,
            }
        },
    }


def _paper_buys(paper):
    day1 = paper.execute(
        "tail_momentum_overnight",
        buy_config("10.00", "10.00"),
        datetime(D1.year, D1.month, D1.day, 9, 31, tzinfo=CN_TZ),
    )
    day2 = paper.execute(
        "tail_momentum_overnight",
        buy_config("10.20", "10.10"),
        datetime(D2.year, D2.month, D2.day, 9, 31, tzinfo=CN_TZ),
    )
    return day1 + day2


def _backtest_buy_fills(engine):
    return [event.fill for event in engine.run() if event.fill is not None]


def test_paper_and_backtest_produce_identical_buy_fills_and_cash():
    bars = [
        {"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"},
        {"date": D2, "open": "10.20", "close": "10.30", "previous_close": "10.10"},
    ]
    paper = paper_engine(economics())
    backtest = backtest_engine(economics(), bars)

    paper_orders = _paper_buys(paper)
    backtest_fills = _backtest_buy_fills(backtest)

    paper_prices = [Decimal(str(order["price"])) for order in paper_orders]
    backtest_prices = [fill.price for fill in backtest_fills]
    assert paper_prices == backtest_prices == [Decimal("10.01"), Decimal("10.21")]

    paper_fees = [Decimal(str(order["fee"])) for order in paper_orders]
    backtest_fees = [fill.fee for fill in backtest_fills]
    assert paper_fees == backtest_fees

    assert paper.cash == backtest.cash
    # The backtest settles T+1 at each session close while the paper engine
    # settles manually, so compare settlement-independent total holdings.
    paper_holding = (
        paper.position(SYMBOL).settled_qty + paper.position(SYMBOL).unsettled_buy_qty
    )
    backtest_holding = (
        backtest.position(SYMBOL).settled_qty
        + backtest.position(SYMBOL).unsettled_buy_qty
    )
    assert paper_holding == backtest_holding == 200


def test_paper_and_backtest_produce_identical_sells_after_settlement():
    bars = [
        {"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"},
        {"date": D2, "open": "10.20", "close": "10.30", "previous_close": "10.10"},
    ]
    paper = paper_engine(economics())
    backtest = backtest_engine(economics(), bars)

    _paper_buys(paper)
    _backtest_buy_fills(backtest)

    paper.settle()
    sell_time = datetime(D2.year, D2.month, D2.day, 14, 45, tzinfo=CN_TZ)
    paper_orders = paper.sell_all(sell_time)
    backtest_events = backtest.sell_settled(sell_time)

    paper_sell = next(order for order in paper_orders if order["side"] == "sell")
    backtest_fill = next(
        event.fill for event in backtest_events if event.fill is not None
    )
    assert Decimal(str(paper_sell["price"])) == backtest_fill.price == Decimal("10.19")
    assert Decimal(str(paper_sell["fee"])) == backtest_fill.fee
    assert paper_sell["quantity"] == backtest_fill.quantity == 200

    assert paper.cash == backtest.cash
    assert paper.position(SYMBOL).settled_qty == backtest.position(SYMBOL).settled_qty == 0


def test_backtest_cannot_fill_when_slipped_cost_exceeds_cash():
    """The backtest used to debit cash by the slipped price while checking it
    against the un-slipped price, so cash could go negative. The paper channel
    rejects the same intent; both must agree."""
    # Pre-slippage cost 1000.00 + 0.30 commission fits in 1000.30, but the
    # slipped fill (10.01 -> 1001.00 + 0.3003) does not.
    costs = economics(initial_cash=Decimal("1000.30"))
    bars = [{"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"}]
    paper = paper_engine(costs)
    backtest = backtest_engine(costs, bars)

    paper_orders = paper.execute(
        "tail_momentum_overnight",
        buy_config("10.00", "10.00"),
        datetime(D1.year, D1.month, D1.day, 9, 31, tzinfo=CN_TZ),
    )
    backtest_events = backtest.run()

    assert paper_orders[0]["status"] == "REJECTED"
    assert paper_orders[0]["reason_code"] == "INSUFFICIENT_CASH"

    fills = [event for event in backtest_events if event.kind == "FILL"]
    assert fills == []
    order_events = [event for event in backtest_events if event.kind == "ORDER"]
    assert all(
        backtest.order_states.get(event.order.id).status == "REJECTED"
        for event in order_events
    )
    assert all(
        backtest.order_states.get(event.order.id).rejection_code
        == "INSUFFICIENT_CASH"
        for event in order_events
    )
    assert backtest.cash == costs["initial_cash"]
    assert backtest.position(SYMBOL).unsettled_buy_qty == 0


def test_backtest_rejection_precedence_matches_paper_rules_first():
    """When an order breaches both market rules and cash, both engines must
    report the rules rejection: `rules/` is the single adjudicator, so cash
    checks must not shadow it."""
    costs = economics(initial_cash=Decimal("100.00"))
    bars = [{"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"}]
    paper = paper_engine(costs, status="Suspended")
    backtest = backtest_engine(costs, bars, status="Suspended")

    paper_orders = paper.execute(
        "tail_momentum_overnight",
        buy_config("10.00", "10.00"),
        datetime(D1.year, D1.month, D1.day, 9, 31, tzinfo=CN_TZ),
    )
    backtest_events = backtest.run()

    assert paper_orders[0]["reason_code"] == "INSTRUMENT_NOT_ACTIVE"
    order_events = [event for event in backtest_events if event.kind == "ORDER"]
    assert order_events
    assert all(
        backtest.order_states.get(event.order.id).rejection_code
        == "INSTRUMENT_NOT_ACTIVE"
        for event in order_events
    )
    assert backtest.cash == costs["initial_cash"]


def test_engines_agree_under_the_next_open_fill_model():
    """The replaceable fill model must keep the two engines equivalent."""
    bars = [
        {"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"},
        {"date": D2, "open": "10.20", "close": "10.30", "previous_close": "10.10"},
    ]
    model = economics()
    model["fill_model"] = "next_open"
    paper = paper_engine(model)
    backtest = backtest_engine(model, bars)

    paper_orders = _paper_buys(paper)
    backtest_fills = _backtest_buy_fills(backtest)

    assert [Decimal(str(order["price"])) for order in paper_orders] == [
        fill.price for fill in backtest_fills
    ] == [Decimal("10.00"), Decimal("10.20")]
    assert paper.cash == backtest.cash


def test_backtest_vwap_model_fills_at_amount_over_volume():
    bars = [
        {
            "date": D1,
            "open": "10.00",
            "close": "10.10",
            "previous_close": "10.00",
            "amount": "1010000",
            "volume": "99400",
        },
    ]
    model = economics()
    model["fill_model"] = "vwap"
    engine = backtest_engine(model, bars)

    fills = [event.fill for event in engine.run() if event.fill is not None]

    assert fills[0].price == Decimal("10.16")  # 1010000 / 99400 = 10.1609...


def test_backtest_vwap_model_fails_closed_without_volume_data():
    bars = [
        {"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"},
    ]
    model = economics()
    model["fill_model"] = "vwap"

    with pytest.raises(ValueError, match="vwap"):
        backtest_engine(model, bars).run()
