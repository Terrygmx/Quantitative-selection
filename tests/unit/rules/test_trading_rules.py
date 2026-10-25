from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quant_agent.domain.models import Instrument, Order
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import MarketSnapshot, Portfolio, Position, TradingRulesPlugin


CN_TZ = ZoneInfo("Asia/Shanghai")


def instrument(**overrides):
    values = {
        "symbol": "sh600519",
        "exchange": "SSE",
        "board": "MainBoard",
        "status": "Active",
        "listing_date": date(2001, 8, 27),
        "tick": Decimal("0.01"),
        "lot_size": 100,
    }
    values.update(overrides)
    return Instrument(**values)


def order(**overrides):
    values = {
        "id": "ord-1",
        "symbol": "sh600519",
        "side": "buy",
        "quantity": 100,
        "limit_price": Decimal("10.00"),
        "created_at": datetime(2026, 9, 15, 14, 31, tzinfo=CN_TZ),
    }
    values.update(overrides)
    return Order(**values)


def portfolio(symbol="sh600519", settled=0, unsettled=0):
    return Portfolio({symbol: Position(settled_qty=settled, unsettled_buy_qty=unsettled)})

def snapshot(item=None, **overrides):
    values = {
        "instrument": item or instrument(),
        "last": Decimal("11.00"),
        "previous_close": Decimal("10.00"),
    }
    values.update(overrides)
    return MarketSnapshot(**values)


@pytest.mark.parametrize(
    ("instrument", "day", "expected"),
    [
        (instrument(), date(2024, 6, 3), (Decimal("9.00"), Decimal("11.00"))),
        (
            instrument(board="ChiNext", listing_date=date(2010, 6, 1)),
            date(2020, 8, 21),
            (Decimal("9.00"), Decimal("11.00")),
        ),
        (
            instrument(board="ChiNext", listing_date=date(2010, 6, 1)),
            date(2020, 8, 24),
            (Decimal("8.00"), Decimal("12.00")),
        ),
        (
            instrument(board="STAR", listing_date=date(2019, 7, 22)),
            date(2024, 6, 3),
            (Decimal("8.00"), Decimal("12.00")),
        ),
    ],
)
def test_price_limits_are_board_and_date_effective(instrument, day, expected):
    band = TradingRulesPlugin().price_limits(instrument, Decimal("10.00"), day)

    assert (band.floor, band.ceiling) == expected


@pytest.mark.parametrize(
    "instrument",
    [
        instrument(board="STAR", listing_date=date(2024, 1, 2)),
        instrument(exchange="SZSE", board="ChiNext", listing_date=date(2024, 1, 2)),
    ],
)
def test_new_star_and_chinext_listing_has_no_price_limit_for_first_5_trading_days(instrument):
    rules = TradingRulesPlugin()

    assert rules.price_limits(instrument, Decimal("10.00"), date(2024, 1, 2)) is None
    assert rules.price_limits(instrument, Decimal("10.00"), date(2024, 1, 5)) is None
    assert rules.price_limits(instrument, Decimal("10.00"), date(2024, 1, 8)) is None

    band = rules.price_limits(instrument, Decimal("10.00"), date(2024, 1, 9))
    assert band is not None
    assert band.floor == Decimal("8.00")
    assert band.ceiling == Decimal("12.00")


def test_same_day_sell_is_rejected_for_t_plus_one():
    rejections = TradingRulesPlugin().validate_order(
        order(side="sell", limit_price=Decimal("10.00")),
        portfolio(settled=0, unsettled=100),
        snapshot(),
    )

    assert [r.code for r in rejections] == ["T1_UNSETTLED"]


def test_buy_and_settled_sell_are_lot_valid():
    rules = TradingRulesPlugin()
    market = snapshot()

    assert rules.validate_order(order(), portfolio(), market) == []
    assert (
        rules.validate_order(
            order(side="sell"), portfolio(settled=100), market
        )
        == []
    )

    invalid = rules.validate_order(order(quantity=150), portfolio(), market)
    assert [item.code for item in invalid] == ["INVALID_LOT"]


def test_suspended_limit_board_and_price_band_reject_orders():
    rules = TradingRulesPlugin()
    market = snapshot()

    suspended = rules.validate_order(
        order(),
        portfolio(),
        MarketSnapshot(
            instrument=market.instrument,
            last=market.last,
            previous_close=market.previous_close,
            tradable=False,
        ),
    )
    assert [r.code for r in suspended] == ["SUSPENDED"]

    limit_up = rules.validate_order(
        order(side="buy", limit_price=Decimal("11.00")),
        portfolio(),
        market,
    )
    assert [r.code for r in limit_up] == ["LIMIT_UP"]

    unlocked_market = MarketSnapshot(
        instrument=market.instrument,
        last=Decimal("10.00"),
        previous_close=market.previous_close,
    )
    outside_band = rules.validate_order(
        order(limit_price=Decimal("11.01")), portfolio(), unlocked_market
    )
    assert [r.code for r in outside_band] == ["PRICE_BAND"]


def test_invalid_fill_price_is_rejected():
    rules = TradingRulesPlugin()

    assert rules.validate_fill_price(instrument(), Decimal("10.00"), Decimal("10.01"), date(2024, 6, 3))
    assert not rules.validate_fill_price(instrument(), Decimal("10.00"), Decimal("11.01"), date(2024, 6, 3))
    assert not rules.validate_fill_price(
        instrument(status="Suspended"), Decimal("10.00"), Decimal("10.01"), date(2024, 6, 3)
    )


def test_order_execution_conserves_cash_and_position():
    rules = TradingRulesPlugin()
    instrument_item = instrument()
    market = snapshot(instrument_item, last=Decimal("10.00"))
    cash = Decimal("10000.00")
    position = Position()
    quantity = 100

    buy = order(quantity=quantity, limit_price=Decimal("10.00"))
    assert rules.validate_order(buy, Portfolio({"sh600519": position}), market) == []
    cash -= buy.limit_price * quantity
    position = Position(unsettled_buy_qty=position.unsettled_buy_qty + quantity)

    sell = order(side="sell", quantity=quantity, limit_price=Decimal("10.00"))
    settled_portfolio = Portfolio({"sh600519": Position(settled_qty=quantity)})
    assert rules.validate_order(sell, settled_portfolio, market) == []
    cash += sell.limit_price * quantity
    position = Position(settled_qty=position.settled_qty)

    assert cash == Decimal("10000.00")
    assert position.settled_qty >= 0


@pytest.mark.parametrize(
    ("item", "time", "tradable"),
    [
        (instrument(), datetime(2026, 9, 15, 9, 20, tzinfo=CN_TZ), False),
        (instrument(), datetime(2026, 9, 15, 9, 30, tzinfo=CN_TZ), True),
        (instrument(), datetime(2026, 9, 15, 11, 30, tzinfo=CN_TZ), True),
        (instrument(), datetime(2026, 9, 15, 12, 30, tzinfo=CN_TZ), False),
        (instrument(), datetime(2026, 9, 15, 15, 0, tzinfo=CN_TZ), True),
    ],
)
def test_continuous_auction_session_matrix(item, time, tradable):
    assert TradingRulesPlugin().tradeability(item, time).tradable is tradable


@pytest.mark.parametrize(
    ("price", "valid"),
    [
        (Decimal("10.00"), True),
        (Decimal("10.01"), True),
        (Decimal("10.005"), False),
        (Decimal("10"), True),
    ],
)
def test_order_price_must_follow_tick(price, valid):
    assert TradingRulesPlugin().valid_price(instrument(), price) is valid


def test_market_snapshot_model_replaces_implicit_mapping():
    item = MarketSnapshot(
        instrument=instrument(),
        last=Decimal("10.00"),
        previous_close=Decimal("10.00"),
        tradable=True,
    )

    assert item.instrument.symbol == "sh600519"
    assert TradingRulesPlugin().validate_order(order(), portfolio(), item) == []


@pytest.mark.parametrize(
    ("created_at", "expected_code"),
    [
        (datetime(2026, 9, 15, 9, 20, tzinfo=CN_TZ), "OUTSIDE_CONTINUOUS_AUCTION"),
        (datetime(2026, 9, 15, 9, 25, tzinfo=CN_TZ), "OUTSIDE_CONTINUOUS_AUCTION"),
        (datetime(2026, 9, 15, 11, 31, tzinfo=CN_TZ), "OUTSIDE_CONTINUOUS_AUCTION"),
        (datetime(2026, 9, 15, 12, 30, tzinfo=CN_TZ), "OUTSIDE_CONTINUOUS_AUCTION"),
        (datetime(2026, 9, 15, 15, 1, tzinfo=CN_TZ), "OUTSIDE_CONTINUOUS_AUCTION"),
        (datetime(2026, 9, 15, 9, 45, tzinfo=CN_TZ), None),
    ],
)
def test_order_rejection_matrix_includes_session_times(created_at, expected_code):
    from quant_agent.rules.trading import MarketSnapshot

    rules = TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE"))
    snapshot = MarketSnapshot(
        instrument=instrument(),
        last=Decimal("10.00"),
        previous_close=Decimal("10.00"),
    )
    rejections = rules.validate_order(order(created_at=created_at), portfolio(), snapshot)

    codes = [item.code for item in rejections]
    assert (expected_code in codes) is (expected_code is not None)
    if expected_code is None:
        assert codes == []


def test_order_rejection_matrix_includes_board_tick_sizes():
    from quant_agent.rules.trading import MarketSnapshot

    rules = TradingRulesPlugin()
    star = instrument(symbol="sh688001", board="STAR", tick=Decimal("0.01"))
    main = instrument(symbol="sh600519", board="MainBoard", tick=Decimal("0.01"))

    star_snapshot = MarketSnapshot(
        instrument=star,
        last=Decimal("10.00"),
        previous_close=Decimal("10.00"),
    )
    main_snapshot = MarketSnapshot(
        instrument=main,
        last=Decimal("10.00"),
        previous_close=Decimal("10.00"),
    )

    invalid_star = rules.validate_order(
        order(symbol="sh688001", limit_price=Decimal("10.005")),
        portfolio("sh688001"),
        star_snapshot,
    )
    valid_main = rules.validate_order(
        order(symbol="sh600519", limit_price=Decimal("10.01")),
        portfolio("sh600519"),
        main_snapshot,
    )

    assert [item.code for item in invalid_star] == ["INVALID_TICK"]
    assert valid_main == []


def test_validate_order_rejects_legacy_market_mapping():
    with pytest.raises(TypeError, match="MarketSnapshot"):
        TradingRulesPlugin().validate_order(
            order(),
            portfolio(),
            {
                "sh600519": {
                    "last": Decimal("10.00"),
                    "previous_close": Decimal("10.00"),
                    "instrument": instrument(),
                }
            },
        )


@pytest.mark.parametrize(
    ("board", "exchange", "moment", "tradable"),
    [
        # After-hours fixed-price session is STAR/ChiNext only, 15:05-15:30.
        ("STAR", "SSE", datetime(2026, 9, 15, 15, 5, tzinfo=CN_TZ), True),
        ("STAR", "SSE", datetime(2026, 9, 15, 15, 20, tzinfo=CN_TZ), True),
        ("STAR", "SSE", datetime(2026, 9, 15, 15, 30, tzinfo=CN_TZ), True),
        ("ChiNext", "SZSE", datetime(2026, 9, 15, 15, 10, tzinfo=CN_TZ), True),
        ("MainBoard", "SSE", datetime(2026, 9, 15, 15, 10, tzinfo=CN_TZ), False),
        ("STAR", "SSE", datetime(2026, 9, 15, 15, 4, tzinfo=CN_TZ), False),
        ("STAR", "SSE", datetime(2026, 9, 15, 15, 31, tzinfo=CN_TZ), False),
        # Continuous auction keeps its own boundaries for every board.
        ("MainBoard", "SSE", datetime(2026, 9, 15, 9, 30, tzinfo=CN_TZ), True),
        ("STAR", "SSE", datetime(2026, 9, 15, 15, 1, tzinfo=CN_TZ), False),
    ],
)
def test_after_hours_fixed_price_session_matrix(board, exchange, moment, tradable):
    rules = TradingRulesPlugin(StaticTradingCalendar.for_exchange(exchange))
    item = instrument(board=board, exchange=exchange)

    assert rules.tradeability(item, moment).tradable is tradable


def test_after_hours_order_fills_only_at_closing_price():
    rules = TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE"))
    star = instrument(symbol="sh688001", board="STAR", exchange="SSE")
    market = MarketSnapshot(
        instrument=star,
        last=Decimal("10.00"),
        previous_close=Decimal("10.00"),
    )

    def after_hours_order(price):
        return order(
            symbol="sh688001",
            limit_price=price,
            created_at=datetime(2026, 9, 15, 15, 10, tzinfo=CN_TZ),
        )

    at_close = rules.validate_order(
        after_hours_order(Decimal("10.00")), portfolio("sh688001"), market
    )
    assert at_close == []

    off_close = rules.validate_order(
        after_hours_order(Decimal("10.01")), portfolio("sh688001"), market
    )
    assert [item.code for item in off_close] == ["INVALID_AFTER_HOURS_PRICE"]


def test_continuous_auction_orders_are_not_bound_to_closing_price():
    rules = TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE"))
    star = instrument(symbol="sh688001", board="STAR", exchange="SSE")
    market = MarketSnapshot(
        instrument=star,
        last=Decimal("10.00"),
        previous_close=Decimal("10.00"),
    )

    rejections = rules.validate_order(
        order(
            symbol="sh688001",
            limit_price=Decimal("10.01"),
            created_at=datetime(2026, 9, 15, 14, 31, tzinfo=CN_TZ),
        ),
        portfolio("sh688001"),
        market,
    )

    assert rejections == []


def after_hours_marked_order(moment, price=Decimal("10.01"), symbol="sh688001", board="STAR", exchange="SSE"):
    return order(
        symbol=symbol,
        limit_price=price,
        created_at=moment,
        session="after_hours_fixed",
    )


def test_after_hours_marked_orders_follow_submission_window():
    rules = TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE"))
    star = instrument(symbol="sh688001", board="STAR", exchange="SSE")
    market = MarketSnapshot(
        instrument=star, last=Decimal("10.00"), previous_close=Decimal("10.00")
    )

    # Intraday submission is allowed for STAR/ChiNext; the matching price is
    # the close, so the limit is not bound to the current last.
    intraday = rules.validate_order(
        after_hours_marked_order(datetime(2026, 9, 15, 14, 31, tzinfo=CN_TZ)),
        portfolio("sh688001"),
        market,
    )
    assert intraday == []

    lunch_break = rules.validate_order(
        after_hours_marked_order(datetime(2026, 9, 15, 12, 30, tzinfo=CN_TZ)),
        portfolio("sh688001"),
        market,
    )
    assert [item.code for item in lunch_break] == ["OUTSIDE_AFTER_HOURS_SUBMISSION_WINDOW"]

    pre_open = rules.validate_order(
        after_hours_marked_order(datetime(2026, 9, 15, 9, 20, tzinfo=CN_TZ)),
        portfolio("sh688001"),
        market,
    )
    assert [item.code for item in pre_open] == ["OUTSIDE_AFTER_HOURS_SUBMISSION_WINDOW"]

    late = rules.validate_order(
        after_hours_marked_order(datetime(2026, 9, 15, 15, 35, tzinfo=CN_TZ)),
        portfolio("sh688001"),
        market,
    )
    assert [item.code for item in late] == ["OUTSIDE_AFTER_HOURS_SUBMISSION_WINDOW"]


def test_after_hours_marked_orders_reject_non_eligible_boards():
    rules = TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE"))
    main = instrument(symbol="sh600519", board="MainBoard", exchange="SSE")
    market = MarketSnapshot(
        instrument=main, last=Decimal("10.00"), previous_close=Decimal("10.00")
    )

    rejections = rules.validate_order(
        after_hours_marked_order(
            datetime(2026, 9, 15, 14, 31, tzinfo=CN_TZ),
            symbol="sh600519",
            board="MainBoard",
        ),
        portfolio(),
        market,
    )

    assert [item.code for item in rejections] == ["AFTER_HOURS_BOARD_NOT_SUPPORTED"]


def test_after_hours_marked_orders_in_session_still_need_closing_price():
    rules = TradingRulesPlugin(StaticTradingCalendar.for_exchange("SSE"))
    star = instrument(symbol="sh688001", board="STAR", exchange="SSE")
    market = MarketSnapshot(
        instrument=star, last=Decimal("10.00"), previous_close=Decimal("10.00")
    )

    off_close = rules.validate_order(
        after_hours_marked_order(datetime(2026, 9, 15, 15, 10, tzinfo=CN_TZ)),
        portfolio("sh688001"),
        market,
    )
    assert [item.code for item in off_close] == ["INVALID_AFTER_HOURS_PRICE"]

    at_close = rules.validate_order(
        after_hours_marked_order(
            datetime(2026, 9, 15, 15, 10, tzinfo=CN_TZ), price=Decimal("10.00")
        ),
        portfolio("sh688001"),
        market,
    )
    assert at_close == []


def test_limit_board_rejections_are_side_aware():
    """Market mechanics at the band edges: at limit-up only buyers queue
    (sell fills into the buy queue); at limit-down only sellers queue."""
    rules = TradingRulesPlugin()
    at_limit_up = MarketSnapshot(
        instrument=instrument(),
        last=Decimal("11.00"),
        previous_close=Decimal("10.00"),
    )
    at_limit_down = MarketSnapshot(
        instrument=instrument(),
        last=Decimal("9.00"),
        previous_close=Decimal("10.00"),
    )

    sell_into_buy_queue = rules.validate_order(
        order(side="sell", limit_price=Decimal("11.00")),
        portfolio(settled=100),
        at_limit_up,
    )
    assert sell_into_buy_queue == []

    buy_into_sell_queue = rules.validate_order(
        order(limit_price=Decimal("9.00")),
        portfolio(),
        at_limit_down,
    )
    assert buy_into_sell_queue == []

    buy_at_limit_up = rules.validate_order(
        order(limit_price=Decimal("11.00")), portfolio(), at_limit_up
    )
    assert [item.code for item in buy_at_limit_up] == ["LIMIT_UP"]

    sell_at_limit_down = rules.validate_order(
        order(side="sell", limit_price=Decimal("9.00")),
        portfolio(settled=100),
        at_limit_down,
    )
    assert [item.code for item in sell_at_limit_down] == ["LIMIT_DOWN"]


def test_out_of_band_breach_keeps_price_band_code_per_side():
    """An out-of-band price is a band breach; the limit-up/limit-down queue
    codes belong to the queueing side only."""
    rules = TradingRulesPlugin()
    at_limit_up = MarketSnapshot(
        instrument=instrument(),
        last=Decimal("11.00"),
        previous_close=Decimal("10.00"),
    )
    at_limit_down = MarketSnapshot(
        instrument=instrument(),
        last=Decimal("9.00"),
        previous_close=Decimal("10.00"),
    )

    sell_above_ceiling = rules.validate_order(
        order(side="sell", limit_price=Decimal("11.01")),
        portfolio(settled=100),
        at_limit_up,
    )
    assert [item.code for item in sell_above_ceiling] == ["PRICE_BAND"]

    buy_below_floor = rules.validate_order(
        order(limit_price=Decimal("8.99")),
        portfolio(),
        at_limit_down,
    )
    assert [item.code for item in buy_below_floor] == ["PRICE_BAND"]


def test_new_listing_without_price_band_validates_orders_without_crashing():
    """First-five-day STAR/ChiNext listings have no price band; validating an
    order for them must skip band checks, not crash on the None band."""
    rules = TradingRulesPlugin()
    new_listing = instrument(
        symbol="sh688001",
        board="STAR",
        exchange="SSE",
        listing_date=date(2024, 1, 2),
    )
    market = MarketSnapshot(
        instrument=new_listing,
        last=Decimal("12.00"),
        previous_close=Decimal("10.00"),
    )

    rejections = rules.validate_order(
        order(
            symbol="sh688001",
            limit_price=Decimal("12.00"),
            created_at=datetime(2024, 1, 2, 14, 31, tzinfo=CN_TZ),
        ),
        portfolio("sh688001"),
        market,
    )

    assert rejections == []
