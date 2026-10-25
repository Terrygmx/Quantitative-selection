from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quant_agent.agents.paper import (
    PaperExecutionConfig,
    SimulatedPaperExecution,
)
from quant_agent.domain.models import Instrument
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin


CN_TZ = ZoneInfo("Asia/Shanghai")
RUN_AT = datetime(2026, 10, 26, 14, 45, tzinfo=CN_TZ)


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


def execution(**overrides):
    defaults = {
        "initial_cash": Decimal("100000.00"),
        "commission_rate": Decimal("0.0003"),
        "stamp_tax_rate": Decimal("0.0005"),
        "slippage_rate": Decimal("0.001"),
        "buy_quantity": 100,
    }
    defaults.update(overrides)
    config = PaperExecutionConfig(**defaults)
    return SimulatedPaperExecution(
        config=config,
        instruments={
            "sh600176": instrument("sh600176"),
            "sz000001": instrument("sz000001", exchange="SZSE"),
        },
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )


def market_config(symbol="sh600176", last="10.05", previous_close="10.00", cash=None):
    config = {
        "config_hash": "hash-1",
        "universe": [symbol],
        "market": {
            symbol: {
                "last": last,
                "previous_close": previous_close,
                "tradable": True,
            }
        },
    }
    if cash is not None:
        config["cash"] = cash
    return config


def test_simulated_execution_fills_approved_targets_with_fees():
    paper = execution()

    orders = paper.execute(
        "tail_momentum_overnight", market_config(), RUN_AT
    )

    assert orders[0]["symbol"] == "sh600176"
    assert orders[0]["side"] == "buy"
    assert orders[0]["quantity"] == 100
    assert orders[0]["status"] == "FILLED"
    assert Decimal(str(orders[0]["price"])) == Decimal("10.06")
    assert Decimal(str(orders[0]["fee"])) == Decimal("0.3018")
    assert paper.cash == Decimal("100000.00") - (
        Decimal("10.06") * 100 + Decimal("0.3018")
    )


def test_simulated_execution_rejects_orders_without_cash():
    paper = execution()

    orders = paper.execute(
        "tail_momentum_overnight",
        market_config(last="1200.00", previous_close="1200.00"),
        RUN_AT,
    )

    assert orders[0]["status"] == "REJECTED"
    assert orders[0]["reason_code"] == "INSUFFICIENT_CASH"
    assert paper.cash == Decimal("100000.00")
    assert paper.position("sh600176").unsettled_buy_qty == 0


def test_simulated_execution_rejects_non_tradable_instrument():
    paper = execution()
    config = market_config()
    config["market"]["sh600176"]["tradable"] = False

    orders = paper.execute("tail_momentum_overnight", config, RUN_AT)

    assert orders[0]["status"] == "REJECTED"
    assert orders[0]["reason_code"] == "SUSPENDED"


def test_simulated_execution_rejects_price_above_limit_band():
    paper = execution()

    orders = paper.execute(
        "tail_momentum_overnight",
        market_config(last="12.00", previous_close="10.00"),
        RUN_AT,
    )

    assert orders[0]["status"] == "REJECTED"
    assert orders[0]["reason_code"] == "PRICE_BAND"


def test_simulated_execution_blocks_same_day_sell_before_settlement():
    paper = execution()
    paper.execute("tail_momentum_overnight", market_config(), RUN_AT)

    orders = paper.sell_all(RUN_AT)

    assert orders == []
    assert paper.position("sh600176").settled_qty == 0


def test_simulated_execution_sells_after_settlement_with_stamp_tax():
    paper = execution()
    paper.execute("tail_momentum_overnight", market_config(), RUN_AT)
    settlement = datetime(2026, 10, 27, 9, 31, tzinfo=CN_TZ)
    cash_after_buy = paper.cash

    paper.settle()
    orders = paper.sell_all(settlement)

    assert orders[0]["status"] == "FILLED"
    assert paper.position("sh600176").settled_qty == 0
    assert paper.cash > cash_after_buy
    assert paper.order_states.get(orders[0]["order_id"]).status == "FILLED"


def test_simulated_execution_records_invalid_lot_quantity():
    paper = execution()
    orders = paper.execute(
        "tail_momentum_overnight",
        market_config(),
        RUN_AT,
        quantity=101,
    )

    assert orders[0]["status"] == "REJECTED"
    assert orders[0]["reason_code"] == "INVALID_LOT"


def test_simulated_execution_requires_instrument_metadata():
    paper = SimulatedPaperExecution(
        config=PaperExecutionConfig(initial_cash=Decimal("1000.00")),
        instruments={},
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )

    with pytest.raises(ValueError, match="instrument metadata"):
        paper.execute("tail_momentum_overnight", market_config(), RUN_AT)


def test_simulated_execution_rejects_orders_outside_continuous_auction():
    paper = execution()

    orders = paper.execute(
        "tail_momentum_overnight",
        market_config(),
        datetime(2026, 10, 26, 22, 45, tzinfo=CN_TZ),
    )

    assert orders[0]["status"] == "REJECTED"
    assert orders[0]["reason_code"] == "OUTSIDE_CONTINUOUS_AUCTION"


def test_simulated_execution_uses_latest_observed_price_for_sells():
    paper = execution()
    paper.execute(
        "tail_momentum_overnight", market_config(last="10.05"), RUN_AT
    )
    paper.settle()
    paper.execute(
        "tail_momentum_overnight",
        market_config(last="11.00", previous_close="11.00"),
        RUN_AT,
    )
    paper.settle()

    orders = paper.sell_all(datetime(2026, 10, 27, 9, 31, tzinfo=CN_TZ))

    assert orders[0]["quantity"] == 200
    assert Decimal(str(orders[0]["price"])) == Decimal("10.99")


def test_simulated_execution_sell_all_is_idempotent():
    paper = execution()
    paper.execute("tail_momentum_overnight", market_config(), RUN_AT)
    paper.settle()
    settlement = datetime(2026, 10, 27, 9, 31, tzinfo=CN_TZ)

    assert len(paper.sell_all(settlement)) == 1
    assert paper.sell_all(settlement) == []


def test_simulated_execution_only_trades_approved_universe():
    """Symbols present in the market snapshot but absent from `universe`
    must never be traded."""
    paper = execution()
    config = market_config()
    config["market"]["sz000001"] = {
        "last": "5.00",
        "previous_close": "5.00",
        "tradable": True,
    }

    orders = paper.execute("tail_momentum_overnight", config, RUN_AT)

    assert [order["symbol"] for order in orders] == ["sh600176"]


def test_simulated_execution_fails_closed_when_universe_symbol_has_no_snapshot():
    paper = execution()

    with pytest.raises(ValueError, match="market snapshot"):
        paper.execute(
            "tail_momentum_overnight",
            {"config_hash": "hash-1", "universe": ["sh600176"], "market": {}},
            RUN_AT,
        )


def test_simulated_execution_rejects_sell_below_limit_down_floor():
    """A sell must be priced against the real previous close, so a gap-down
    to the limit-down floor cannot fill below the band."""
    paper = execution()
    paper.execute(
        "tail_momentum_overnight", market_config(last="10.05"), RUN_AT
    )
    paper.settle()
    # Gap down to the limit-down floor: band floor is 10.00 * 0.9 == 9.00.
    paper.execute(
        "tail_momentum_overnight",
        market_config(last="9.00", previous_close="10.00"),
        RUN_AT,
    )
    paper.settle()

    orders = paper.sell_all(datetime(2026, 10, 27, 9, 31, tzinfo=CN_TZ))

    assert orders[0]["status"] == "REJECTED"
    # `market.last == band.floor`, so the rules layer reports the more
    # specific LIMIT_DOWN rather than a generic price-band breach.
    assert orders[0]["reason_code"] == "LIMIT_DOWN"
    assert paper.position("sh600176").settled_qty == 200


def test_simulated_execution_rejects_non_positive_snapshot_price():
    paper = execution()

    orders = paper.execute(
        "tail_momentum_overnight", market_config(last="0"), RUN_AT
    )

    assert orders[0]["status"] == "REJECTED"
    assert orders[0]["reason_code"] == "INVALID_PRICE"
    assert paper.cash == Decimal("100000.00")


def test_simulated_execution_rejects_unparseable_snapshot_price():
    """Malformed vendor data must fail closed, not raise a decimal error."""
    paper = execution()

    orders = paper.execute(
        "tail_momentum_overnight", market_config(last="not-a-price"), RUN_AT
    )

    assert orders[0]["status"] == "REJECTED"
    assert orders[0]["reason_code"] == "INVALID_PRICE"
    assert paper.cash == Decimal("100000.00")


def test_simulated_execution_requires_universe():
    paper = execution()

    with pytest.raises(ValueError, match="universe"):
        paper.execute(
            "tail_momentum_overnight",
            {"config_hash": "hash-1", "market": {"sh600176": {"last": "10.05"}}},
            RUN_AT,
        )


def test_simulated_execution_rejects_sell_while_suspended():
    paper = execution()
    paper.execute(
        "tail_momentum_overnight", market_config(last="10.05"), RUN_AT
    )
    paper.settle()
    # The stock is suspended and we never observe it resume trading, so the
    # sell must not assume tradability.
    suspended = market_config(last="10.05")
    suspended["market"]["sh600176"]["tradable"] = False
    paper.execute("tail_momentum_overnight", suspended, RUN_AT)
    paper.settle()

    orders = paper.sell_all(datetime(2026, 10, 27, 9, 31, tzinfo=CN_TZ))

    assert orders[0]["status"] == "REJECTED"
    assert orders[0]["reason_code"] == "SUSPENDED"
    assert paper.position("sh600176").settled_qty == 100


def test_simulated_execution_fills_after_hours_at_closing_price():
    """STAR/ChiNext after-hours orders fill exactly at the close, with no
    slippage: the rules layer is the single pricing adjudicator."""
    config = PaperExecutionConfig(
        initial_cash=Decimal("100000.00"),
        commission_rate=Decimal("0.0003"),
        stamp_tax_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.001"),
        buy_quantity=100,
    )
    star = Instrument(
        symbol="sh688001",
        exchange="SSE",
        board="STAR",
        status="Active",
        listing_date=date(2019, 7, 22),
        tick=Decimal("0.01"),
        lot_size=100,
    )
    paper = SimulatedPaperExecution(
        config=config,
        instruments={"sh688001": star},
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )
    strategy_config = {
        "config_hash": "hash-1",
        "universe": ["sh688001"],
        "market": {
            "sh688001": {
                "last": "10.00",
                "previous_close": "10.00",
                "tradable": True,
            }
        },
    }

    orders = paper.execute(
        "tail_momentum_overnight",
        strategy_config,
        datetime(2026, 10, 26, 15, 10, tzinfo=CN_TZ),
    )

    assert orders[0]["status"] == "FILLED"
    assert Decimal(str(orders[0]["price"])) == Decimal("10.00")
    assert Decimal(str(orders[0]["fee"])) == Decimal("0.3000")
    assert paper.cash == Decimal("100000.00") - (
        Decimal("10.00") * 100 + Decimal("0.3000")
    )


def star_execution(cash="100000.00"):
    config = PaperExecutionConfig(
        initial_cash=Decimal(cash),
        commission_rate=Decimal("0.0003"),
        stamp_tax_rate=Decimal("0.0005"),
        slippage_rate=Decimal("0.001"),
        buy_quantity=100,
    )
    star = Instrument(
        symbol="sh688001",
        exchange="SSE",
        board="STAR",
        status="Active",
        listing_date=date(2019, 7, 22),
        tick=Decimal("0.01"),
        lot_size=100,
    )
    return SimulatedPaperExecution(
        config=config,
        instruments={"sh688001": star},
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )


def after_hours_config(last="10.00", previous_close="10.00", tradable=True):
    return {
        "config_hash": "hash-1",
        "session": "after_hours_fixed",
        "universe": ["sh688001"],
        "market": {
            "sh688001": {
                "last": last,
                "previous_close": previous_close,
                "tradable": tradable,
            }
        },
    }


def test_paper_queues_intraday_after_hours_intents_without_filling():
    paper = star_execution()

    orders = paper.execute(
        "tail_momentum_overnight",
        after_hours_config(last="10.00"),
        datetime(2026, 10, 26, 14, 31, tzinfo=CN_TZ),
    )

    assert orders[0]["status"] == "QUEUED_AFTER_HOURS"
    assert orders[0]["symbol"] == "sh688001"
    assert paper.cash == Decimal("100000.00")
    assert paper.position("sh688001").unsettled_buy_qty == 0
    assert len(paper.after_hours_queue) == 1


def test_paper_matches_queued_intents_at_the_close():
    paper = star_execution()
    paper.execute(
        "tail_momentum_overnight",
        after_hours_config(last="10.00"),
        datetime(2026, 10, 26, 14, 31, tzinfo=CN_TZ),
    )

    orders = paper.execute(
        "tail_momentum_overnight",
        after_hours_config(last="10.05", previous_close="10.00"),
        datetime(2026, 10, 26, 15, 10, tzinfo=CN_TZ),
    )

    # The 15:10 run first matches the queued intent at the close, then the
    # fresh universe submission itself fills immediately (it is submitted
    # inside the matching window). Both fill at 10.05 without slippage.
    assert [order["status"] for order in orders] == ["FILLED", "FILLED"]
    matched = orders[0]
    assert matched["price"] == "10.05"
    assert Decimal(str(matched["fee"])) == Decimal("0.3015")
    assert "submitted_at" in matched
    per_fill = Decimal("10.05") * 100 + Decimal("0.3015")
    assert paper.cash == Decimal("100000.00") - 2 * per_fill
    assert paper.position("sh688001").unsettled_buy_qty == 200
    assert paper.after_hours_queue == []


def test_queued_after_hours_intents_never_fill_outside_the_matching_window():
    paper = star_execution()
    paper.execute(
        "tail_momentum_overnight",
        after_hours_config(last="10.00"),
        datetime(2026, 10, 26, 14, 31, tzinfo=CN_TZ),
    )

    orders = paper.execute(
        "tail_momentum_overnight",
        after_hours_config(last="10.00"),
        datetime(2026, 10, 26, 14, 45, tzinfo=CN_TZ),
    )

    assert orders[0]["status"] == "QUEUED_AFTER_HOURS"
    assert paper.cash == Decimal("100000.00")
    assert paper.position("sh688001").unsettled_buy_qty == 0
    # Both the 14:31 and the 14:45 intents wait for the matching window.
    assert len(paper.after_hours_queue) == 2


def test_stale_after_hours_intents_expire_next_day():
    paper = star_execution()
    paper.execute(
        "tail_momentum_overnight",
        after_hours_config(last="10.00"),
        datetime(2026, 10, 26, 14, 31, tzinfo=CN_TZ),
    )

    orders = paper.execute(
        "tail_momentum_overnight",
        after_hours_config(last="10.00"),
        datetime(2026, 10, 27, 14, 31, tzinfo=CN_TZ),
    )

    # The new intraday submission queues; yesterday's intent expires
    # (after-hours intents are day-scoped). A 15:10 run would instead fill
    # the new submission at the close, so cash assertions use 14:31.
    statuses = [order["status"] for order in orders]
    assert statuses == ["EXPIRED", "QUEUED_AFTER_HOURS"]
    expired = orders[0]
    assert expired["symbol"] == "sh688001"
    assert paper.cash == Decimal("100000.00")
    assert paper.position("sh688001").unsettled_buy_qty == 0
    assert len(paper.after_hours_queue) == 1


def test_after_hours_session_rejects_ineligible_submissions():
    paper = execution()  # MainBoard instruments
    config = {
        "config_hash": "hash-1",
        "session": "after_hours_fixed",
        "universe": ["sh600176"],
        "market": {
            "sh600176": {"last": "10.05", "previous_close": "10.00", "tradable": True}
        },
    }

    orders = paper.execute(
        "tail_momentum_overnight", config, RUN_AT
    )

    assert orders[0]["status"] == "REJECTED"
    assert orders[0]["reason_code"] == "AFTER_HOURS_BOARD_NOT_SUPPORTED"
