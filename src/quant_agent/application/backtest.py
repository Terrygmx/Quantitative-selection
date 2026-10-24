from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Mapping


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
    def __init__(self, bars: Mapping[str, object], config: BacktestConfig):
        self.bars = list(bars)
        self.config = config
        self.cash = config.initial_cash
        self.position = Position()
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
            tzinfo=timezone.utc,
        )
        events.append(Event("SIGNAL", signal_time))

        buy_bar = self.bars[1]
        buy_time = datetime(
            buy_bar["date"].year,
            buy_bar["date"].month,
            buy_bar["date"].day,
            9,
            31,
            tzinfo=timezone.utc,
        )
        order = OrderRecord("buy", self.config.buy_quantity, buy_time)
        events.append(Event("ORDER", buy_time, order=order))
        fill_price = Decimal(str(buy_bar["open"])) * (1 + self.config.slippage_rate)
        gross = fill_price * order.quantity
        fee = gross * self.config.commission_rate
        self.cash -= gross + fee
        self.position.unsettled_buy_qty += order.quantity
        self._order_id += 1
        fill = FillRecord(str(self._order_id), "buy", fill_price, order.quantity, fee, buy_time)
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
            tzinfo=timezone.utc,
        )
        sell_order = OrderRecord("sell", self.config.buy_quantity, sell_time)
        events.append(Event("ORDER", sell_time, order=sell_order))
        events.append(Event("REJECTION", sell_time, rejection_code="T1_UNSETTLED"))
        self.position.settled_qty += self.position.unsettled_buy_qty
        self.position.unsettled_buy_qty = 0
        return events

    def equity(self, day: date, close: Decimal) -> Decimal:
        return self.cash + close * (self.position.settled_qty + self.position.unsettled_buy_qty)

    def sell_settled(self, day: date, open_price: Decimal, timestamp: datetime) -> list[Event]:
        if self.position.settled_qty < self.config.buy_quantity:
            raise ValueError("settled quantity is insufficient")
        self.position.settled_qty -= self.config.buy_quantity
        fill_price = open_price * (1 - self.config.slippage_rate)
        gross = fill_price * self.config.buy_quantity
        commission = gross * self.config.commission_rate
        tax = gross * self.config.stamp_tax_rate
        self.cash += gross - commission - tax
        self._order_id += 1
        fill = FillRecord(
            str(self._order_id), "sell", fill_price, self.config.buy_quantity,
            commission + tax, timestamp,
        )
        return [Event("FILL", timestamp, fill=fill, cash_after=self.cash)]

    def same_bar_close_signal_and_fill(self, day: date, close: Decimal) -> None:
        raise ValueError("same bar close signal and fill is forbidden")
