from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from typing import Mapping

from quant_agent.domain.models import Instrument, Order
from quant_agent.rules.calendar import TradingCalendar


CHINEXT_20_PERCENT_START = date(2020, 8, 24)
CN_MARKET_TZ = ZoneInfo("Asia/Shanghai")
# After-hours fixed-price trading (盘后定价交易) exists on STAR/ChiNext only,
# 15:05-15:30, and fills at the day's closing price.
AFTER_HOURS_FIXED_PRICE_BOARDS = frozenset({"STAR", "ChiNext"})
AFTER_HOURS_START = time(15, 5)
AFTER_HOURS_END = time(15, 30)


@dataclass(frozen=True, slots=True)
class PriceBand:
    previous_close: Decimal
    floor: Decimal
    ceiling: Decimal


@dataclass(frozen=True, slots=True)
class Rejection:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Tradeability:
    tradable: bool
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    instrument: Instrument
    last: Decimal
    previous_close: Decimal
    tradable: bool = True


@dataclass(frozen=True, slots=True)
class Position:
    settled_qty: int = 0
    unsettled_buy_qty: int = 0


@dataclass(frozen=True, slots=True)
class Portfolio:
    positions: Mapping[str, Position]

    def position(self, symbol: str) -> Position:
        return self.positions.get(symbol, Position())


class TradingRulesPlugin:
    def __init__(self, calendar: TradingCalendar | None = None):
        self.calendar = calendar

    def _new_listing_without_limit(self, instrument: Instrument, day: date) -> bool:
        if not self._is_trading_day(day):
            return False
        if instrument.board not in ("STAR", "ChiNext"):
            return False
        trading_days = 0
        current = instrument.listing_date
        while current <= day:
            if self._is_trading_day(current):
                trading_days += 1
                if current == day:
                    return trading_days <= 5
            current += timedelta(days=1)
        return False

    def _is_trading_day(self, day: date) -> bool:
        return self.calendar.is_trading_day(day) if self.calendar else day.weekday() < 5

    @staticmethod
    def _in_after_hours_fixed_price_session(instrument: Instrument, clock: time) -> bool:
        return (
            instrument.board in AFTER_HOURS_FIXED_PRICE_BOARDS
            and AFTER_HOURS_START <= clock <= AFTER_HOURS_END
        )

    def is_after_hours_fixed_price_session(
        self, instrument: Instrument, as_of: datetime
    ) -> bool:
        """Whether `as_of` falls in the STAR/ChiNext after-hours fixed-price
        session, where fills happen exactly at the closing price."""
        local_clock = (
            as_of.astimezone(CN_MARKET_TZ).time().replace(tzinfo=None)
        )
        return self._in_after_hours_fixed_price_session(instrument, local_clock)

    def after_hours_submission_gate(
        self, instrument: Instrument, as_of: datetime
    ) -> Rejection | None:
        """Orders explicitly marked after_hours_fixed may be submitted from
        9:30-11:30 and 13:00-15:30 and match later at the close."""
        local = as_of.astimezone(CN_MARKET_TZ)
        if instrument.status != "Active":
            return Rejection("INSTRUMENT_NOT_ACTIVE", "")
        if not self._is_trading_day(local.date()):
            return Rejection("NON_TRADING_DAY", "")
        if instrument.board not in AFTER_HOURS_FIXED_PRICE_BOARDS:
            return Rejection(
                "AFTER_HOURS_BOARD_NOT_SUPPORTED",
                "after-hours fixed-price trading is STAR/ChiNext only",
            )
        clock = local.time().replace(tzinfo=None)
        morning = time(9, 30) <= clock <= time(11, 30)
        afternoon = time(13, 0) <= clock <= time(15, 30)
        if not (morning or afternoon):
            return Rejection(
                "OUTSIDE_AFTER_HOURS_SUBMISSION_WINDOW",
                "after-hours orders may be submitted 9:30-11:30 and 13:00-15:30",
            )
        return None

    def tradeability(self, instrument: Instrument, as_of: datetime) -> Tradeability:
        local_time = as_of.astimezone(CN_MARKET_TZ)
        if instrument.status != "Active":
            return Tradeability(False, "INSTRUMENT_NOT_ACTIVE")
        if not self._is_trading_day(local_time.date()):
            return Tradeability(False, "NON_TRADING_DAY")
        local_clock = local_time.time().replace(tzinfo=None)
        morning = time(9, 30) <= local_clock <= time(11, 30)
        afternoon = time(13, 0) <= local_clock <= time(15, 0)
        if morning or afternoon:
            return Tradeability(True)
        if self._in_after_hours_fixed_price_session(instrument, local_clock):
            return Tradeability(True)
        return Tradeability(False, "OUTSIDE_CONTINUOUS_AUCTION")

    def valid_price(self, instrument: Instrument, price: Decimal) -> bool:
        return price % instrument.tick == 0

    def _limit_percent(self, instrument: Instrument, day: date) -> Decimal:
        if instrument.board == "STAR":
            return Decimal("0.20")
        if instrument.board == "ChiNext" and day >= CHINEXT_20_PERCENT_START:
            return Decimal("0.20")
        return Decimal("0.10")

    def price_limits(self, instrument: Instrument, previous_close: Decimal, day: date) -> PriceBand | None:
        if self._new_listing_without_limit(instrument, day):
            return None
        percent = self._limit_percent(instrument, day)
        tick = instrument.tick
        floor = (previous_close * (1 - percent)).quantize(tick, rounding=ROUND_HALF_UP)
        ceiling = (previous_close * (1 + percent)).quantize(tick, rounding=ROUND_HALF_UP)
        return PriceBand(previous_close=previous_close, floor=floor, ceiling=ceiling)

    def validate_order(
        self,
        order: Order,
        portfolio: Portfolio,
        market: MarketSnapshot,
    ) -> list[Rejection]:
        if not isinstance(market, MarketSnapshot):
            raise TypeError("market must be a MarketSnapshot")
        if order.session == "after_hours_fixed":
            gate = self.after_hours_submission_gate(
                market.instrument, order.created_at
            )
            if gate is not None:
                return [gate]
        else:
            tradeability = self.tradeability(market.instrument, order.created_at)
            if not tradeability.tradable:
                return [Rejection(tradeability.reason_code or "NOT_TRADABLE", "")]
        if market.tradable is False:
            return [Rejection("SUSPENDED", "instrument is not tradable")]

        if order.side == "sell":
            position = portfolio.position(order.symbol)
            if order.quantity > position.settled_qty:
                return [Rejection("T1_UNSETTLED", "same-day bought quantity is not sellable")]

        instrument = market.instrument
        try:
            order.validate_quantity(
                instrument, allow_odd_lot=order.side == "sell"
            )
        except ValueError as exc:
            return [Rejection("INVALID_LOT", str(exc))]
        if not self.valid_price(instrument, order.limit_price):
            return [Rejection("INVALID_TICK", "limit price must follow instrument tick")]
        band = self.price_limits(
            instrument,
            market.previous_close,
            order.created_at.date(),
        )
        if band is not None:
            # Only the queueing side cannot fill at a locked band edge:
            # buyers queue at limit-up, sellers queue at limit-down; the
            # opposite side fills into that queue.
            if order.limit_price > band.ceiling:
                if order.side == "buy" and market.last == band.ceiling:
                    return [Rejection("LIMIT_UP", "buy orders queue at limit-up")]
                return [
                    Rejection("PRICE_BAND", "limit price is above the allowed price band")
                ]
            if order.limit_price < band.floor:
                if order.side == "sell" and market.last == band.floor:
                    return [Rejection("LIMIT_DOWN", "sell orders queue at limit-down")]
                return [
                    Rejection(
                        "PRICE_BAND", "limit price is below the allowed price band"
                    )
                ]
            if (
                order.limit_price == band.ceiling
                and market.last == band.ceiling
                and order.side == "buy"
            ):
                return [Rejection("LIMIT_UP", "buy orders queue at limit-up")]
            if (
                order.limit_price == band.floor
                and market.last == band.floor
                and order.side == "sell"
            ):
                return [Rejection("LIMIT_DOWN", "sell orders queue at limit-down")]
        local_clock = (
            order.created_at.astimezone(CN_MARKET_TZ).time().replace(tzinfo=None)
        )
        if (
            self._in_after_hours_fixed_price_session(instrument, local_clock)
            and order.limit_price != market.last
        ):
            return [
                Rejection(
                    "INVALID_AFTER_HOURS_PRICE",
                    "after-hours orders must price at the closing price",
                )
            ]
        return []

    def validate_fill_price(
        self,
        instrument: Instrument,
        previous_close: Decimal,
        fill_price: Decimal,
        day: date,
    ) -> bool:
        if instrument.status != "Active":
            return False
        band = self.price_limits(instrument, previous_close, day)
        return band is None or band.floor <= fill_price <= band.ceiling
        return []
