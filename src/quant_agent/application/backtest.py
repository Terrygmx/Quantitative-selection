from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from typing import Mapping

from quant_agent.domain.models import Instrument, Order
from quant_agent.application.execution import (
    ExecutionCore,
    ExecutionCosts,
    ExecutionPosition,
)
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

    @property
    def costs(self) -> ExecutionCosts:
        return ExecutionCosts(
            commission_rate=self.commission_rate,
            stamp_tax_rate=self.stamp_tax_rate,
            slippage_rate=self.slippage_rate,
        )


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
class MultiInstrumentBacktestConfig(BacktestConfig):
    pass


@dataclass(frozen=True, slots=True)
class MultiInstrumentEvent:
    kind: str
    as_of: datetime
    order: Order | None = None
    fill: FillRecord | None = None


MultiBars = Mapping[str, list[Mapping[str, object]]]
MultiInstruments = Mapping[str, Instrument]


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
        self._orders: list[Order] = []
        self._fills: list[FillRecord] = []
        self._order_id = 0

    def execution_details(self) -> dict[str, list[dict[str, object]]]:
        orders = [
            {
                "id": order.id,
                "side": order.side,
                "quantity": order.quantity,
                "status": self.order_states.get(order.id).status,
                **(
                    {"rejection_code": self.order_states.get(order.id).rejection_code}
                    if self.order_states.get(order.id).rejection_code
                    else {}
                ),
            }
            for order in self._orders
        ]
        fills = [
            {
                "order_id": fill.order_id,
                "side": fill.side,
                "price": str(fill.price),
                "quantity": fill.quantity,
                "fee": str(fill.fee),
                "timestamp": fill.timestamp.isoformat(),
            }
            for fill in self._fills
        ]
        return {"orders": orders, "fills": fills}

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
        self._fills.append(fill)
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
        order = Order(
            id=f"order-{self._order_id}",
            symbol=self.instrument.symbol,
            side=side,
            quantity=self.config.buy_quantity,
            limit_price=price,
            created_at=timestamp,
        )
        self._orders.append(order)
        return order

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
            previous_close=Decimal(str(self.bars[-1].get("close", open_price)))
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
        self._fills.append(fill)
        events.append(Event("FILL", timestamp, fill=fill, cash_after=self.cash))
        return events

    def same_bar_close_signal_and_fill(self, day: date, close: Decimal) -> None:
        raise ValueError("same bar close signal and fill is forbidden")


class MultiInstrumentBacktestEngine:
    def __init__(
        self,
        bars: MultiBars,
        instruments: MultiInstruments,
        config: BacktestConfig,
        rules: TradingRulesPlugin,
    ):
        self.bars = {symbol: list(items) for symbol, items in bars.items()}
        self.instruments = dict(instruments)
        self.config = config
        self.rules = rules
        self._costs = config.costs
        self.core = ExecutionCore(config.initial_cash, self._costs, rules)
        self.order_states: OrderStateMachine = self.core.order_states
        self._orders: list[Order] = []
        self._fills: list[FillRecord] = []

    @property
    def cash(self) -> Decimal:
        return self.core.cash

    @property
    def positions(self) -> dict[str, ExecutionPosition]:
        return self.core.positions

    def run(self) -> list[MultiInstrumentEvent]:
        events: list[MultiInstrumentEvent] = []
        dates = self._ordered_dates()
        for day in dates:
            session_open = datetime(day.year, day.month, day.day, 9, 31, tzinfo=CN_MARKET_TZ)
            events.append(MultiInstrumentEvent("SESSION_OPEN", session_open))
            for symbol in sorted(self.bars):
                bar = next((item for item in self.bars[symbol] if item["date"] == day), None)
                if bar is None:
                    continue
                event = self._trade_symbol(symbol, bar, session_open)
                events.extend(event)
            events.append(MultiInstrumentEvent("SESSION_CLOSE", session_open))
            self.core.settle()
        return events

    def position(self, symbol: str) -> ExecutionPosition:
        return self.core.position(symbol)

    def _trade_symbol(
        self, symbol: str, bar: Mapping[str, object], timestamp: datetime
    ) -> list[MultiInstrumentEvent]:
        instrument = self.instruments[symbol]
        market = MarketSnapshot(
            instrument=instrument,
            last=Decimal(str(bar["open"])),
            previous_close=Decimal(str(bar["previous_close"])),
            tradable=instrument.status == "Active",
        )
        order = Order(
            id=f"order-{symbol}-{len(self._orders) + 1}",
            symbol=symbol,
            side="buy",
            quantity=self.config.buy_quantity,
            limit_price=self._costs.fill_price(
                instrument, market.last, "buy"
            ),
            created_at=timestamp,
        )
        self._orders.append(order)
        events = [MultiInstrumentEvent("ORDER", timestamp, order=order)]
        outcome = self.core.execute_order(order, instrument, market)
        if outcome.status != "FILLED":
            return events
        fill = FillRecord(
            order.id, "buy", outcome.price, order.quantity, outcome.fee, timestamp
        )
        self._fills.append(fill)
        events.append(MultiInstrumentEvent("FILL", timestamp, fill=fill))
        return events

    def _ordered_dates(self) -> list[date]:
        dates = {
            item["date"]
            for items in self.bars.values()
            for item in items
            if isinstance(item.get("date"), date)
        }
        return sorted(dates)

    def sell_settled(self, timestamp: datetime) -> list[MultiInstrumentEvent]:
        events: list[MultiInstrumentEvent] = []
        for symbol in sorted(self.bars):
            position = self.positions[symbol]
            if position.settled_qty <= 0:
                continue
            latest_bar = self._latest_bar_on_or_before(symbol, timestamp.date())
            if latest_bar is None:
                continue
            events.extend(self._sell_symbol(symbol, latest_bar, timestamp))
        return events

    def _sell_symbol(
        self, symbol: str, bar: Mapping[str, object], timestamp: datetime
    ) -> list[MultiInstrumentEvent]:
        instrument = self.instruments[symbol]
        quantity = self.positions[symbol].settled_qty
        market = MarketSnapshot(
            instrument=instrument,
            last=Decimal(str(bar["open"])),
            previous_close=Decimal(str(bar["previous_close"])),
            tradable=instrument.status == "Active",
        )
        order = Order(
            id=f"order-{symbol}-{len(self._orders) + 1}",
            symbol=symbol,
            side="sell",
            quantity=quantity,
            limit_price=self._costs.fill_price(
                instrument, market.last, "sell"
            ),
            created_at=timestamp,
        )
        self._orders.append(order)
        events = [MultiInstrumentEvent("ORDER", timestamp, order=order)]
        outcome = self.core.execute_order(order, instrument, market)
        if outcome.status != "FILLED":
            return events
        fill = FillRecord(
            order.id, "sell", outcome.price, quantity, outcome.fee, timestamp
        )
        self._fills.append(fill)
        events.append(MultiInstrumentEvent("FILL", timestamp, fill=fill))
        return events

    def _latest_bar_on_or_before(self, symbol: str, day: date) -> Mapping[str, object] | None:
        eligible = [item for item in self.bars[symbol] if item["date"] <= day]
        return eligible[-1] if eligible else None
