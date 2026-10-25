"""Unit coverage for the shared execution core's pricing entry."""

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
