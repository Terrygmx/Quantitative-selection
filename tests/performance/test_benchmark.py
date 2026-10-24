from datetime import date, timedelta
from decimal import Decimal

from quant_agent.application.backtest import (
    BacktestConfig,
    MultiInstrumentBacktestEngine,
)
from quant_agent.domain.models import Instrument
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin


def _bars(start: date, days: int, initial_price: Decimal):
    items = []
    current = start
    price = initial_price
    previous = price
    for _ in range(days):
        price = (price * Decimal("1.0001")).quantize(Decimal("0.01"))
        items.append(
            {
                "date": current,
                "open": str(previous),
                "close": str(price),
                "previous_close": str(previous),
            }
        )
        previous = price
        current += timedelta(days=1)
    return items


def test_multi_instrument_backtest_benchmark_3000_symbols_5_years(benchmark):
    symbols = [f"sh6{i:05d}" for i in range(3000)]
    instruments = {}
    bars = {}
    for index, symbol in enumerate(symbols):
        instruments[symbol] = Instrument(
            symbol=symbol,
            exchange="SSE",
            board="MainBoard",
            status="Active",
            listing_date=date(2010, 1, 1),
            tick=Decimal("0.01"),
            lot_size=100,
        )
        bars[symbol] = _bars(date(2021, 1, 1), 1260, Decimal("10.00") + Decimal(index) / Decimal("100"))

    engine = MultiInstrumentBacktestEngine(
        bars=bars,
        instruments=instruments,
        config=BacktestConfig(
            initial_cash=Decimal("1000000000.00"),
            buy_quantity=100,
            commission_rate=Decimal("0.0003"),
            stamp_tax_rate=Decimal("0.0005"),
            slippage_rate=Decimal("0.001"),
        ),
        rules=TradingRulesPlugin(StaticTradingCalendar.for_sse_2023()),
    )

    events = benchmark.pedantic(engine.run, rounds=1, iterations=1)

    assert len(events) > 0
    assert len(engine._orders) == len(symbols) * len(engine._ordered_dates())
