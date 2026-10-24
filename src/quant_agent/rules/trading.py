from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from quant_agent.domain.models import Instrument, Order
from quant_agent.rules.calendar import TradingCalendar


CHINEXT_20_PERCENT_START = date(2020, 8, 24)


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
        market: Mapping[str, Mapping[str, object]],
    ) -> list[Rejection]:
        snapshot = market.get(order.symbol, {})
        if snapshot.get("tradable") is False:
            return [Rejection("SUSPENDED", "instrument is not tradable")]

        if order.side == "sell":
            position = portfolio.position(order.symbol)
            if order.quantity > position.settled_qty:
                return [Rejection("T1_UNSETTLED", "same-day bought quantity is not sellable")]

        instrument = snapshot.get("instrument")
        if not isinstance(instrument, Instrument):
            return [Rejection("MARKET_DATA_MISSING", "instrument metadata is required")]
        try:
            order.validate_quantity(
                instrument, allow_odd_lot=order.side == "sell"
            )
        except ValueError as exc:
            return [Rejection("INVALID_LOT", str(exc))]
        previous_close = snapshot.get("previous_close")
        if previous_close is None:
            return [Rejection("MARKET_DATA_MISSING", "previous close is required")]
        band = self.price_limits(
            instrument,
            Decimal(str(previous_close)),
            order.created_at.date(),
        )
        if order.limit_price > band.ceiling:
            if snapshot.get("last") == band.ceiling:
                return [Rejection("LIMIT_UP", "order cannot fill at limit-up price")]
            return [Rejection("PRICE_BAND", "limit price is above the allowed price band")]
        if order.limit_price < band.floor:
            if snapshot.get("last") == band.floor:
                return [Rejection("LIMIT_DOWN", "order cannot fill at limit-down price")]
            return [Rejection("PRICE_BAND", "limit price is below the allowed price band")]
        if order.limit_price == band.ceiling and snapshot.get("last") == band.ceiling:
            return [Rejection("LIMIT_UP", "order cannot fill at limit-up price")]
        if order.limit_price == band.floor and snapshot.get("last") == band.floor:
            return [Rejection("LIMIT_DOWN", "order cannot fill at limit-down price")]
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
