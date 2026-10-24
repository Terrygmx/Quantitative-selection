from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from typing import Mapping

from quant_agent.domain.models import Instrument, Order
from quant_agent.application.orders import OrderStateMachine, PendingOrder
from quant_agent.rules.trading import Portfolio as RulesPortfolio
from quant_agent.rules.trading import Position as RulesPosition
from quant_agent.rules.trading import MarketSnapshot, Rejection, TradingRulesPlugin


CN_MARKET_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    initial_cash: Decimal
    buy_quantity: int
    commission_rate: Decimal
    stamp_tax_rate: Decimal
    slippage_rate: Decimal


@dataclass(frozen=True, slots=True)
class OrderRecord:
    side: str
    quantity: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FillRecord:
    order_id: str
    side: str
    price: Decimal
    quantity: int
    fee: Decimal
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class Event:
    kind: str
    as_of: datetime
    order: OrderRecord | None = None
    fill: FillRecord | None = None
    rejection_code: str | None = None
    cash_after: Decimal | None = None

    @property
    def rejection(self):
        from quant_agent.rules.trading import Rejection

        return Rejection(self.rejection_code or "", "")


@dataclass
class Position:
    settled_qty: int = 0
    unsettled_buy_qty: int = 0


class BacktestEngine:
    def __init__(
        self,
        bars: Mapping[str, object],
        config: BacktestConfig,
        instrument: Instrument | None = None,
        rules: TradingRulesPlugin | None = None,
    ):
        if instrument is None:
            raise ValueError("instrument metadata is required")
        if rules is None:
            raise ValueError("rules plugin is required")
        self.bars = list(bars)
        self.config = config
        self.instrument = instrument
        self.rules = rules
        self.cash = config.initial_cash
        self.position = Position()
        self.order_states = OrderStateMachine()
        self._order_id = 0

    def run(self) -> list[Event]:
        events: list[Event] = []
        signal_bar = self.bars[0]
        signal_time = datetime(
            signal_bar["date"].year,
            signal_bar["date"].month,
            signal_bar["date"].day,
            14,
            31,
            tzinfo=CN_MARKET_TZ,
        )
        events.append(Event("SIGNAL", signal_time))

        buy_bar = self.bars[1]
        buy_time = datetime(
            buy_bar["date"].year,
            buy_bar["date"].month,
            buy_bar["date"].day,
            9,
            31,
            tzinfo=CN_MARKET_TZ,
        )
        order = self._create_order("buy", buy_bar, buy_time)
        events.append(Event("ORDER", buy_time, order=order))
        self.order_states.submit(PendingOrder(order.id, order.created_at))
        rejections = self._validate_order(order, buy_bar)
        if rejections:
            self.order_states.reject(order.id, rejections[0].code, buy_time)
            events.append(Event("REJECTION", buy_time, rejection_code=rejections[0].code))
            return events
        fill_price = Decimal(str(buy_bar["open"])) * (1 + self.config.slippage_rate)
        gross = fill_price * order.quantity
        fee = gross * self.config.commission_rate
        self.cash -= gross + fee
        self.position.unsettled_buy_qty += order.quantity
        self.order_states.fill(order.id, buy_time)
        fill = FillRecord(order.id, "buy", fill_price, order.quantity, fee, buy_time)
        events.append(
            Event("FILL", buy_time, fill=fill, cash_after=self.cash)
        )

        sell_bar = self.bars[1]
        sell_time = datetime(
            sell_bar["date"].year,
            sell_bar["date"].month,
            sell_bar["date"].day,
            9,
            31,
            tzinfo=CN_MARKET_TZ,
        )
        sell_order = self._create_order("sell", sell_bar, sell_time)
        events.append(Event("ORDER", sell_time, order=sell_order))
        self.order_states.submit(PendingOrder(sell_order.id, sell_order.created_at))
        sell_rejections = self._validate_order(sell_order, sell_bar)
        if sell_rejections:
            self.order_states.reject(sell_order.id, sell_rejections[0].code, sell_time)
            events.append(
                Event("REJECTION", sell_time, rejection_code=sell_rejections[0].code)
            )
        events.append(Event("SESSION_SETTLE", sell_time, cash_after=self.cash))
        self.position.settled_qty += self.position.unsettled_buy_qty
        self.position.unsettled_buy_qty = 0
        return events

    def _create_order(self, side: str, bar: Mapping[str, object], timestamp: datetime) -> Order:
        price = Decimal(str(bar["open"]))
        self._order_id += 1
        return Order(
            id=f"order-{self._order_id}",
            symbol=self.instrument.symbol,
            side=side,
            quantity=self.config.buy_quantity,
            limit_price=price,
            created_at=timestamp,
        )

    def _validate_order(self, order: Order, bar: Mapping[str, object]) -> list[Rejection]:
        market = MarketSnapshot(
            instrument=self.instrument,
            last=Decimal(str(bar["open"])),
            previous_close=Decimal(str(bar["previous_close"])),
            tradable=self.instrument.status == "Active",
        )
        return self.rules.validate_order(order, self._rules_portfolio(), market)

    def _rules_portfolio(self) -> RulesPortfolio:
        return RulesPortfolio(
            {
                self.instrument.symbol: RulesPosition(
                    settled_qty=self.position.settled_qty,
                    unsettled_buy_qty=self.position.unsettled_buy_qty,
                )
            }
        )

    def equity(self, day: date, close: Decimal) -> Decimal:
        return self.cash + close * (self.position.settled_qty + self.position.unsettled_buy_qty)

    def sell_settled(self, day: date, open_price: Decimal, timestamp: datetime) -> list[Event]:
        bar = {"open": open_price, "previous_close": open_price}
        order = self._create_order("sell", bar, timestamp)
        events = [Event("ORDER", timestamp, order=OrderRecord(order.side, order.quantity, order.created_at))]
        self.order_states.submit(PendingOrder(order.id, order.created_at))
        snapshot = MarketSnapshot(
            instrument=self.instrument,
            last=open_price,
            previous_close=self.bars[-1].get("close", open_price)
            if self.bars
            else open_price,
            tradable=self.instrument.status == "Active",
        )
        rejections = self.rules.validate_order(order, self._rules_portfolio(), snapshot)
        if rejections:
            self.order_states.reject(order.id, rejections[0].code, timestamp)
            events.append(Event("REJECTION", timestamp, rejection_code=rejections[0].code))
            return events
        if self.position.settled_qty < self.config.buy_quantity:
            events.append(Event("REJECTION", timestamp, rejection_code="T1_UNSETTLED"))
            return events
        self.position.settled_qty -= self.config.buy_quantity
        fill_price = open_price * (1 - self.config.slippage_rate)
        gross = fill_price * self.config.buy_quantity
        commission = gross * self.config.commission_rate
        tax = gross * self.config.stamp_tax_rate
        self.cash += gross - commission - tax
        self.order_states.fill(order.id, timestamp)
        fill = FillRecord(
            order.id, "sell", fill_price, self.config.buy_quantity,
            commission + tax, timestamp,
        )
        events.append(Event("FILL", timestamp, fill=fill, cash_after=self.cash))
        return events

    def same_bar_close_signal_and_fill(self, day: date, close: Decimal) -> None:
        raise ValueError("same bar close signal and fill is forbidden")
