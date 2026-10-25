"""Grid trading engine: resting limit orders on a price grid. Orders fill
when bar prices CROSS a grid level (buy at the level, sell at the level);
no slippage, real fees, T+1 via the shared core, no lookahead."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.application.grid import GridBacktestEngine
from quant_agent.domain.models import Instrument
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin


CN_TZ = ZoneInfo("Asia/Shanghai")
D1 = date(2026, 9, 14)
D2 = date(2026, 9, 15)


def minute_bar(day, hhmm, close):
    stamp = datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[2:]), tzinfo=CN_TZ)
    return Bar(
        instrument="sh600519",
        timestamp=stamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000.0,
        amount=close * 1000,
        available_at=stamp,
    )


def instrument():
    return Instrument(
        symbol="sh600519",
        exchange="SSE",
        board="MainBoard",
        status="Active",
        listing_date=date(2010, 1, 1),
        tick=Decimal("0.01"),
        lot_size=100,
    )


def config(**overrides):
    from quant_agent.application.grid import GridConfig

    values = {
        "initial_cash": Decimal("100000.00"),
        "buy_quantity": 100,
        "commission_rate": Decimal("0.0003"),
        "stamp_tax_rate": Decimal("0.0005"),
    }
    values.update(overrides)
    return GridConfig(**values)


def engine(bars, grid_low="9.00", grid_high="12.00", grid_steps=6, **cfg):
    return GridBacktestEngine(
        port=InMemoryMarketDataPort(bars),
        instruments={"sh600519": instrument()},
        config=config(**cfg),
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
        grid_low=Decimal(grid_low),
        grid_high=Decimal(grid_high),
        grid_steps=grid_steps,
    )


def test_grid_places_no_orders_inside_one_band():
    bars = [minute_bar(D1, "0931", 10.4), minute_bar(D1, "1500", 10.5)]

    events = engine(bars).run()

    assert [e for e in events if e.fill is not None] == []
    assert engine(bars).cash == Decimal("100000.00")


def test_dip_crossing_a_level_buys_at_that_level():
    bars = [
        minute_bar(D1, "0931", 10.4),
        minute_bar(D1, "1400", 9.85),  # crosses the 10.00 level downward
    ]

    events = engine(bars).run()

    fills = [e.fill for e in events if e.fill is not None]
    assert [fill.price for fill in fills] == [Decimal("10.00")]
    assert fills[0].side == "buy"
    assert fills[0].quantity == 100
    run = engine(bars)
    run.run()
    # run() settles at the end; the fill itself landed unsettled.
    assert run.position("sh600519").settled_qty == 100


def test_fast_fall_fires_every_crossed_level_within_the_band():
    bars = [
        minute_bar(D1, "0931", 10.4),
        minute_bar(D1, "1400", 9.85),   # buy at 10.00
        minute_bar(D1, "1500", 10.3),   # back above: no new buy (no new cross)
        # D2 falls from the previous close 10.30; the 10% band floor is
        # 9.27, so only the 10.00 and 9.50 levels are tradeable.
        minute_bar(D2, "1000", 9.4),
    ]

    run = engine(bars)
    events = run.run()

    # Every crossed level fires (descending: nearest first); grid levels
    # beyond the session band are rejected by the rules layer.
    buy_prices = [e.fill.price for e in events if e.fill is not None and e.fill.side == "buy"]
    assert buy_prices == [Decimal("10.00"), Decimal("10.00"), Decimal("9.50")]
    assert run.position("sh600519").settled_qty + run.position("sh600519").unsettled_buy_qty == 300


def test_rally_into_a_level_sells_only_settled_shares():
    bars = [
        minute_bar(D1, "0931", 10.4),
        minute_bar(D1, "1400", 9.85),   # buy at 10.00 (unsettled)
        minute_bar(D1, "1500", 10.4),   # cross 10.50? no; no sell yet
        minute_bar(D2, "1000", 10.6),   # settles overnight; crosses 10.50 -> sell
    ]

    run = engine(bars)
    events = run.run()

    sells = [e.fill for e in events if e.fill is not None and e.fill.side == "sell"]
    assert [fill.price for fill in sells] == [Decimal("10.50")]
    run2 = engine(bars)
    run2.run()
    assert run2.position("sh600519").settled_qty == 0


def test_sell_without_settled_shares_is_blocked_by_t1():
    bars = [
        minute_bar(D1, "0931", 10.4),
        minute_bar(D1, "1400", 9.85),   # buy at 10.00
        minute_bar(D1, "1500", 10.6),   # crosses 10.50 same day: T+1 blocks
    ]

    run = engine(bars)
    events = run.run()

    sells = [e.fill for e in events if e.fill is not None and e.fill.side == "sell"]
    assert sells == []
    order_events = [e.order for e in events if e.order is not None and e.order.side == "sell"]
    assert order_events
    assert all(
        run.order_states.get(order.id).rejection_code == "T1_UNSETTLED"
        for order in order_events
    )


def test_grid_levels_and_config_validation():
    with pytest.raises(ValueError, match="grid"):
        engine([], grid_low="12.00", grid_high="9.00")
    with pytest.raises(ValueError, match="grid"):
        engine([], grid_steps=1)
    levels = GridBacktestEngine(
        port=InMemoryMarketDataPort([]),
        instruments={"sh600519": instrument()},
        config=config(),
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
        grid_low=Decimal("9.00"),
        grid_high=Decimal("12.00"),
        grid_steps=6,
    ).grid_levels()
    assert len(levels) == 5
    assert levels[0] == Decimal("9.50") and levels[-1] == Decimal("11.50")
