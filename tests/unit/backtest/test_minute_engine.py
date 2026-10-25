"""Minute-frequency backtest: per trading day, each symbol trades at the
latest minute bar at or before the decision time (FR-3.1 last item). Bars
after the decision moment are invisible by PIT construction."""

from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo


from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.application.backtest import BacktestConfig
from quant_agent.application.intraday import MinuteBacktestEngine
from quant_agent.domain.models import Instrument
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin


CN_TZ = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc
D1 = date(2026, 9, 14)
D2 = date(2026, 9, 15)


def minute_bar(day: date, hhmm: str, close: float) -> Bar:
    stamp = datetime(
        day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[2:]), tzinfo=CN_TZ
    )
    return Bar(
        instrument="sh600519",
        timestamp=stamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000.0,
        available_at=stamp,
    )


def instrument(symbol="sh600519"):
    return Instrument(
        symbol=symbol,
        exchange="SSE",
        board="MainBoard",
        status="Active",
        listing_date=date(2010, 1, 1),
        tick=Decimal("0.01"),
        lot_size=100,
    )


def config(**overrides):
    values = {
        "initial_cash": Decimal("100000.00"),
        "buy_quantity": 100,
        "commission_rate": Decimal("0.0003"),
        "stamp_tax_rate": Decimal("0.0005"),
        "slippage_rate": Decimal("0.001"),
    }
    values.update(overrides)
    return BacktestConfig(**values)


def engine(bars, decision_time="1431", **config_overrides):
    return MinuteBacktestEngine(
        port=InMemoryMarketDataPort(bars),
        instruments={"sh600519": instrument()},
        config=config(**config_overrides),
        rules=TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE")),
        decision_time=decision_time,
    )


def test_buys_at_decision_minute_price_each_day():
    bars = [
        minute_bar(D1, "0931", 10.0),
        minute_bar(D1, "1431", 10.5),
        minute_bar(D1, "1500", 10.6),  # after the decision: invisible to it
        minute_bar(D2, "0931", 10.2),
        minute_bar(D2, "1431", 10.7),
    ]

    events = engine(bars).run()

    fills = [event.fill for event in events if event.fill is not None]
    assert [fill.price for fill in fills] == [Decimal("10.51"), Decimal("10.71")]
    assert all(fill.quantity == 100 for fill in fills)
    positions = engine(bars)
    positions.run()
    assert positions.position("sh600519").settled_qty == 200


def test_missing_decision_bar_uses_latest_earlier_bar_same_day():
    bars = [
        minute_bar(D1, "0931", 10.0),
        minute_bar(D1, "1400", 10.4),
        minute_bar(D2, "0931", 10.2),
        minute_bar(D2, "1400", 10.6),
    ]

    events = engine(bars).run()

    fills = [event.fill for event in events if event.fill is not None]
    assert [fill.price for fill in fills] == [Decimal("10.41"), Decimal("10.61")]


def test_day_without_bars_before_decision_is_skipped():
    bars = [
        minute_bar(D1, "1431", 10.5),
        # D2 has only post-decision bars: nothing tradable that day.
        minute_bar(D2, "1445", 10.9),
        minute_bar(D2, "1500", 11.0),
    ]

    events = engine(bars).run()

    fills = [event for event in events if event.fill is not None]
    assert len(fills) == 1


def test_decision_inside_lunch_break_is_rejected_by_rules():
    bars = [
        minute_bar(D1, "1200", 10.5),
        minute_bar(D2, "1200", 10.7),
    ]

    result = engine(bars, decision_time="1200")
    events = result.run()

    fills = [event for event in events if event.fill is not None]
    assert fills == []
    order_events = [event for event in events if event.order is not None]
    assert order_events
    assert all(
        result.order_states.get(event.order.id).rejection_code
        == "OUTSIDE_CONTINUOUS_AUCTION"
        for event in order_events
    )
    assert result.cash == Decimal("100000.00")


def test_sell_settled_uses_latest_minute_bar_and_respects_t1():
    bars = [
        minute_bar(D1, "1431", 10.5),
        minute_bar(D2, "1431", 10.7),
        minute_bar(D2, "1445", 10.9),
    ]
    backtest = engine(bars)
    backtest.run()

    # sell_settled trades from the post-run (settled) ledger; same-day
    # T+1 interception is owned by the shared core and rules layer and is
    # locked by the core/rules/paper tests.
    next_day = datetime(D2.year, D2.month, D2.day, 14, 45, tzinfo=CN_TZ)
    sell_events = backtest.sell_settled(next_day)

    fills = [event.fill for event in sell_events if event.fill is not None]
    assert [fill.price for fill in fills] == [Decimal("10.89")]
    assert backtest.position("sh600519").settled_qty == 0


def test_future_revisions_are_invisible_at_the_decision_moment():
    # The 14:45 bar exists with a wild price, but a 14:31 decision must not
    # see it even though the port would return it for a later as_of.
    bars = [minute_bar(D1, "1400", 10.4), minute_bar(D1, "1445", 50.0)]

    events = engine(bars).run()

    fills = [event.fill for event in events if event.fill is not None]
    assert fills[0].price == Decimal("10.41")


def test_prefetch_engine_produces_identical_results(tmp_path):
    """The per-day-cursor engine must match the query-per-day engine
    exactly on the same data (fills, cash, positions)."""
    from quant_agent.adapters.market_data import InMemoryMarketDataPort
    from quant_agent.application.intraday import MinuteBacktestEngine

    bars = []
    for day in (D1, D2):
        for hhmm, price in (("0931", 10.0), ("1200", 10.3), ("1431", 10.5), ("1500", 10.6)):
            bars.append(minute_bar(day, hhmm, price))
    bars = [
        Bar(
            instrument=bar.instrument,
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            available_at=bar.available_at,
        )
        for bar in bars
    ]
    bars += [
        Bar(
            instrument="sz000001",
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            available_at=bar.available_at,
        )
        for bar in bars
    ]
    port = InMemoryMarketDataPort(bars)
    instruments = {"sh600519": instrument(), "sz000001": instrument("sz000001", )}
    instruments["sz000001"] = Instrument(
        symbol="sz000001",
        exchange="SZSE",
        board="MainBoard",
        status="Active",
        listing_date=date(2010, 1, 1),
        tick=Decimal("0.01"),
        lot_size=100,
    )
    rules = TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE"))

    baseline = MinuteBacktestEngine(
        port=port, instruments=instruments, config=config(), rules=rules
    )
    baseline_events = baseline.run()

    cursor = MinuteBacktestEngine.prefetched(
        port=port, instruments=instruments, config=config(), rules=rules
    )
    cursor_events = cursor.run()

    assert [e.fill.price for e in baseline_events if e.fill] == [
        e.fill.price for e in cursor_events if e.fill
    ]
    assert baseline.cash == cursor.cash
    assert baseline.position("sh600519").settled_qty == cursor.position(
        "sh600519"
    ).settled_qty
    assert baseline.position("sz000001").settled_qty == cursor.position(
        "sz000001"
    ).settled_qty
