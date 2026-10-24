from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from quant_agent.application.backtest import BacktestConfig, BacktestEngine


D1 = date(2026, 9, 14)
D2 = date(2026, 9, 15)
D3 = date(2026, 9, 16)
TS1 = datetime(2026, 9, 14, 14, 31, tzinfo=timezone.utc)
TS2 = datetime(2026, 9, 15, 9, 31, tzinfo=timezone.utc)
TS3 = datetime(2026, 9, 16, 9, 31, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    bars = [
        {"date": D1, "open": "10.00", "close": "10.10", "previous_close": "10.00"},
        {"date": D2, "open": "10.20", "close": "10.30", "previous_close": "10.10"},
        {"date": D3, "open": "10.40", "close": "10.50", "previous_close": "10.30"},
    ]
    return BacktestEngine(
        bars=bars,
        config=BacktestConfig(
            initial_cash=Decimal("10000.00"),
            buy_quantity=100,
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
        ),
    )


def test_buy_signal_fills_next_open_and_honors_t_plus_one(engine):
    events = engine.run()

    assert [event.kind for event in events] == [
        "SIGNAL",
        "ORDER",
        "FILL",
        "ORDER",
        "REJECTION",
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

    assert events[0].kind == "FILL"
    assert events[0].fill.price == Decimal("10.38960")
    assert events[0].cash_after == Decimal("10016.802526000")
    assert engine.position.settled_qty == 0


def test_engine_rejects_same_bar_close_signal_and_fill(engine):
    with pytest.raises(ValueError, match="same bar"):
        engine.same_bar_close_signal_and_fill(D1, Decimal("10.10"))
