from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quant_agent.application.backtest import MultiInstrumentBacktestConfig, MultiInstrumentBacktestEngine
from quant_agent.domain.models import Instrument
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin


CN_TZ = ZoneInfo("Asia/Shanghai")
D1 = date(2026, 9, 14)
D2 = date(2026, 9, 15)


def instrument(symbol, exchange="SSE"):
    return Instrument(
        symbol=symbol,
        exchange=exchange,
        board="MainBoard",
        status="Active",
        listing_date=date(2010, 1, 1),
        tick=Decimal("0.01"),
        lot_size=100,
    )


@pytest.fixture
def engine():
    config = MultiInstrumentBacktestConfig(
        initial_cash=Decimal("10000.00"),
        buy_quantity=100,
        commission_rate=Decimal("0.0003"),
        stamp_tax_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.001"),
    )
    bars = {
        "sh600519": [
            {"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"},
            {"date": D2, "open": "10.20", "close": "10.30", "previous_close": "10.10"},
        ],
        "sz000001": [
            {"date": D1, "open": "12.00", "close": "12.10", "previous_close": "12.00"},
            {"date": D2, "open": "12.20", "close": "12.30", "previous_close": "12.10"},
        ],
    }
    instruments = {
        "sh600519": instrument("sh600519"),
        "sz000001": instrument("sz000001", exchange="SZSE"),
    }
    return MultiInstrumentBacktestEngine(
        bars=bars,
        instruments=instruments,
        config=config,
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )


def test_multi_instrument_engine_executes_one_order_per_symbol(engine):
    events = engine.run()

    assert [event.kind for event in events] == [
        "SESSION_OPEN",
        "ORDER", "FILL",
        "ORDER", "FILL",
        "SESSION_CLOSE",
        "SESSION_OPEN",
        "ORDER", "FILL",
        "ORDER", "FILL",
        "SESSION_CLOSE",
    ]
    assert events[0].as_of.date() == D1
    assert events[-1].as_of.date() == D2
    assert [event.order.symbol for event in events if event.order] == ["sh600519", "sz000001"] * 2
    assert [event.fill.order_id for event in events if event.fill] == [
        "order-sh600519-1", "order-sz000001-2", "order-sh600519-3", "order-sz000001-4"
    ]
    assert {event.order.symbol for event in events if event.order} == set(engine.bars)



def test_multi_instrument_engine_settles_and_sells_next_session(engine):
    engine.run()

    events = engine.sell_settled(
        timestamp=datetime(D2.year, D2.month, D2.day, 14, 45, tzinfo=CN_TZ)
    )

    assert [event.kind for event in events] == ["ORDER", "FILL", "ORDER", "FILL"]
    assert [event.order.symbol for event in events if event.order] == ["sh600519", "sz000001"]
    assert engine.position("sh600519").settled_qty == 0
    assert engine.position("sz000001").settled_qty == 0
    assert engine.cash > Decimal("10000.00")


def test_multi_instrument_engine_rejects_cash_insufficient_orders():
    config = MultiInstrumentBacktestConfig(
        initial_cash=Decimal("100.00"),
        buy_quantity=100,
        commission_rate=Decimal("0.0003"),
        stamp_tax_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.001"),
    )
    bars = {
        "sh600519": [
            {"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"},
        ],
        "sz000001": [
            {"date": D1, "open": "12.00", "close": "12.10", "previous_close": "12.00"},
        ],
    }
    engine = MultiInstrumentBacktestEngine(
        bars=bars,
        instruments={"sh600519": instrument("sh600519"), "sz000001": instrument("sz000001", "SZSE")},
        config=config,
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )

    events = engine.run()

    order_events = [event for event in events if event.kind == "ORDER"]
    fills = [event for event in events if event.kind == "FILL"]
    assert len(order_events) == 2
    assert len(fills) == 0
    assert engine.cash == config.initial_cash
    assert all(engine.order_states.get(event.order.id).status == "REJECTED" for event in order_events)


def test_daily_engine_queue_fill_reads_bar_board_volume():
    from decimal import Decimal

    config = MultiInstrumentBacktestConfig(
        initial_cash=Decimal("100000.00"),
        buy_quantity=100,
        commission_rate=Decimal("0.0003"),
        stamp_tax_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.001"),
        board_queue_policy="queue_fill",
    )
    bars = {
        # +10% over the previous close: a locked MainBoard board.
        "sh600519": [
            {
                "date": D1,
                "open": "11.00",
                "close": "11.00",
                "previous_close": "10.00",
                "board_volume": "800",
            }
        ],
    }
    engine = MultiInstrumentBacktestEngine(
        bars=bars,
        instruments={"sh600519": instrument("sh600519")},
        config=config,
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )

    events = engine.run()

    fills = [event.fill for event in events if event.fill is not None]
    assert [fill.price for fill in fills] == [Decimal("11.00")]
    # run() settles T+1 at session close: 100 settled shares, none unsettled.
    assert engine.position("sh600519").settled_qty == 100
