"""Unit coverage for the shared execution core.s pricing entry."""

import pytest

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from quant_agent.application.execution import ExecutionCore, ExecutionCosts
from quant_agent.domain.models import Instrument
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin


CN_TZ = ZoneInfo("Asia/Shanghai")


def star_instrument():
    return Instrument(
        symbol="sh688001",
        exchange="SSE",
        board="STAR",
        status="Active",
        listing_date=date(2019, 7, 22),
        tick=Decimal("0.01"),
        lot_size=100,
    )


def core():
    return ExecutionCore(
        initial_cash=Decimal("100000.00"),
        costs=ExecutionCosts(
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
        ),
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )


def test_marked_after_hours_orders_price_at_close_intraday():
    """An order marked after_hours_fixed is priced at the (tick-quantized)
    close even when created during the continuous session, because matching
    happens later at the close."""
    instrument = star_instrument()
    intraday = datetime(2026, 9, 15, 14, 31, tzinfo=CN_TZ)

    price = core().order_price(
        instrument,
        Decimal("10.00"),
        "buy",
        intraday,
        session="after_hours_fixed",
    )

    assert price == Decimal("10.00")


def test_continuous_orders_price_with_slippage_intraday():
    instrument = star_instrument()
    intraday = datetime(2026, 9, 15, 14, 31, tzinfo=CN_TZ)

    price = core().order_price(instrument, Decimal("10.00"), "buy", intraday)

    assert price == Decimal("10.01")


def test_fill_model_must_be_a_known_name():
    from quant_agent.application.execution import ExecutionCosts

    with pytest.raises(ValueError, match="fill_model"):
        ExecutionCosts(
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
            fill_model="oracle",
        )


def test_next_open_model_fills_at_the_reference_without_slippage():
    core = ExecutionCore(
        initial_cash=Decimal("100000.00"),
        costs=ExecutionCosts(
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
            fill_model="next_open",
        ),
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )

    price = core.order_price(
        star_instrument(), Decimal("10.03"), "buy", datetime(2026, 9, 15, 9, 31, tzinfo=CN_TZ)
    )

    assert price == Decimal("10.03")


def test_vwap_model_fills_at_the_reference_price():
    core = ExecutionCore(
        initial_cash=Decimal("100000.00"),
        costs=ExecutionCosts(
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
            fill_model="vwap",
        ),
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )

    price = core.order_price(
        star_instrument(),
        Decimal("10.00"),
        "buy",
        datetime(2026, 9, 15, 9, 31, tzinfo=CN_TZ),
        reference=Decimal("10.176"),
    )

    assert price == Decimal("10.18")


def test_vwap_model_fails_closed_without_a_reference():
    core = ExecutionCore(
        initial_cash=Decimal("100000.00"),
        costs=ExecutionCosts(
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
            fill_model="vwap",
        ),
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
    )

    with pytest.raises(ValueError, match="reference"):
        core.order_price(
            star_instrument(),
            Decimal("10.00"),
            "buy",
            datetime(2026, 9, 15, 9, 31, tzinfo=CN_TZ),
        )


def main_board_instrument():
    from quant_agent.domain.models import Instrument

    return Instrument(
        symbol="sh600519",
        exchange="SSE",
        board="MainBoard",
        status="Active",
        listing_date=date(2001, 8, 27),
        tick=Decimal("0.01"),
        lot_size=100,
    )


def locked_market(board_volume=None, last="11.00"):
    from quant_agent.rules.trading import MarketSnapshot

    return MarketSnapshot(
        instrument=main_board_instrument(),
        last=Decimal(last),
        previous_close=Decimal("10.00"),
        board_volume=board_volume,
    )


def board_order(side="buy", price="11.00", quantity=100):
    from quant_agent.domain.models import Order

    return Order(
        id="ord-board-1",
        symbol="sh600519",
        side=side,
        quantity=quantity,
        limit_price=Decimal(price),
        created_at=datetime(2026, 9, 15, 14, 31, tzinfo=CN_TZ),
    )


def queue_core(policy):
    return ExecutionCore(
        initial_cash=Decimal("100000.00"),
        costs=ExecutionCosts(
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
        ),
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
        board_queue_policy=policy,
    )


def test_board_queue_policy_must_be_known():
    import pytest

    with pytest.raises(ValueError, match="board_queue_policy"):
        queue_core("oracle")


def test_queue_fill_fills_limit_up_buy_when_opposite_volume_covers():
    core = queue_core("queue_fill")

    outcome = core.execute_order(
        board_order(), main_board_instrument(), locked_market(board_volume=Decimal("500"))
    )

    assert outcome.status == "FILLED"
    assert outcome.price == Decimal("11.00")  # the board price, no slippage add-on
    assert core.position("sh600519").unsettled_buy_qty == 100


def test_queue_fill_rejects_when_opposite_volume_is_insufficient():
    core = queue_core("queue_fill")

    outcome = core.execute_order(
        board_order(), main_board_instrument(), locked_market(board_volume=Decimal("60"))
    )

    assert outcome.status == "REJECTED"
    assert outcome.reason_code == "BOARD_QUEUE_UNFILLED"
    assert core.cash == Decimal("100000.00")


def test_queue_fill_without_volume_data_stays_conservative():
    core = queue_core("queue_fill")

    outcome = core.execute_order(
        board_order(), main_board_instrument(), locked_market(board_volume=None)
    )

    assert outcome.status == "REJECTED"
    assert outcome.reason_code == "LIMIT_UP"


def test_default_policy_keeps_the_conservative_rejection():
    core = queue_core("reject")

    outcome = core.execute_order(
        board_order(), main_board_instrument(), locked_market(board_volume=Decimal("500"))
    )

    assert outcome.status == "REJECTED"
    assert outcome.reason_code == "LIMIT_UP"


def test_queue_fill_fills_limit_down_sell_with_volume():
    core = queue_core("queue_fill")
    core.position("sh600519").settled_qty = 100

    outcome = core.execute_order(
        board_order(side="sell", price="9.00"),
        main_board_instrument(),
        locked_market(board_volume=Decimal("300"), last="9.00"),
    )

    assert outcome.status == "FILLED"
    assert outcome.price == Decimal("9.00")
    assert core.position("sh600519").settled_qty == 0
