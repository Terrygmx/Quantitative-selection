"""Shared fill channel for backtest and paper trading.

DETAILED_DESIGN §7 and FR-3.4 require one execution channel: rules
validation, slippage, tick quantization, fees, cash and T+1 ledger updates
are decided here so neither engine can grant itself privileges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from quant_agent.application.orders import OrderStateMachine, PendingOrder
from quant_agent.domain.models import Instrument, Order
from quant_agent.rules.trading import (
    MarketSnapshot,
    Portfolio,
    Position,
    TradingRulesPlugin,
)


@dataclass(frozen=True, slots=True)
class ExecutionCosts:
    commission_rate: Decimal
    stamp_tax_rate: Decimal
    slippage_rate: Decimal

    def commission(self, gross: Decimal) -> Decimal:
        return gross * self.commission_rate

    def stamp_tax(self, gross: Decimal) -> Decimal:
        return gross * self.stamp_tax_rate

    def fill_price(self, instrument: Instrument, base: Decimal, side: str) -> Decimal:
        factor = 1 + self.slippage_rate if side == "buy" else 1 - self.slippage_rate
        # Fill prices must respect the instrument tick, or rules reject them.
        return (base * factor).quantize(instrument.tick, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    order_id: str
    symbol: str
    side: str
    quantity: int
    price: Decimal
    fee: Decimal
    status: str
    reason_code: str | None
    timestamp: datetime


@dataclass
class ExecutionPosition:
    settled_qty: int = 0
    unsettled_buy_qty: int = 0


# Rules never consult positions for buys, so buys share one empty view
# instead of allocating a portfolio per order.
_EMPTY_PORTFOLIO = Portfolio({})


class ExecutionCore:
    """Owns cash, the T+1 position ledger and the order state machine for one
    submitted order. Both the backtest and paper engines route every order
    through `execute_order`."""

    def __init__(
        self,
        initial_cash: Decimal,
        costs: ExecutionCosts,
        rules: TradingRulesPlugin,
    ) -> None:
        self.cash = initial_cash
        self.costs = costs
        self.rules = rules
        self.positions: dict[str, ExecutionPosition] = {}
        self.order_states = OrderStateMachine()

    def position(self, symbol: str) -> ExecutionPosition:
        return self.positions.setdefault(symbol, ExecutionPosition())

    def order_price(
        self,
        instrument: Instrument,
        base: Decimal,
        side: str,
        as_of: datetime,
        session: str = "continuous",
    ) -> Decimal:
        """Single pricing entry for both engines: after-hours fixed-price
        orders (marked, or submitted inside the session) fill exactly at the
        close (rules decide); everything else fills at the slipped,
        tick-quantized price."""
        after_hours = (
            session == "after_hours_fixed"
            or self.rules.is_after_hours_fixed_price_session(instrument, as_of)
        )
        if after_hours:
            return base.quantize(instrument.tick, rounding=ROUND_HALF_UP)
        return self.costs.fill_price(instrument, base, side)

    def settle(self) -> None:
        for position in self.positions.values():
            position.settled_qty += position.unsettled_buy_qty
            position.unsettled_buy_qty = 0

    def execute_order(
        self,
        order: Order,
        instrument: Instrument,
        market: MarketSnapshot,
    ) -> ExecutionOutcome:
        self.order_states.submit(PendingOrder(order.id, order.created_at))
        portfolio = (
            self._portfolio_view(order.symbol)
            if order.side == "sell"
            else _EMPTY_PORTFOLIO
        )
        rejections = self.rules.validate_order(order, portfolio, market)
        if rejections:
            return self._reject(order, rejections[0].code)
        price = order.limit_price
        gross = price * order.quantity
        fee = self.costs.commission(gross)
        tax = Decimal("0") if order.side == "buy" else self.costs.stamp_tax(gross)
        if order.side == "buy":
            if gross + fee > self.cash:
                return self._reject(order, "INSUFFICIENT_CASH")
            self.cash -= gross + fee
            self.position(order.symbol).unsettled_buy_qty += order.quantity
        else:
            self.cash += gross - fee - tax
            self.position(order.symbol).settled_qty -= order.quantity
        self.order_states.fill(order.id, order.created_at)
        return ExecutionOutcome(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            fee=fee + tax,
            status="FILLED",
            reason_code=None,
            timestamp=order.created_at,
        )

    def reject_intent(
        self, order_id: str, reason_code: str, timestamp: datetime
    ) -> None:
        """Record a rejected intent that never became a valid `Order` while
        keeping the audit ledger complete."""
        self.order_states.submit(PendingOrder(order_id, timestamp))
        self.order_states.reject(order_id, reason_code, timestamp)

    def _reject(self, order: Order, reason_code: str) -> ExecutionOutcome:
        self.order_states.reject(order.id, reason_code, order.created_at)
        return ExecutionOutcome(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=order.limit_price,
            fee=Decimal("0"),
            status="REJECTED",
            reason_code=reason_code,
            timestamp=order.created_at,
        )

    def _portfolio_view(self, symbol: str) -> Portfolio:
        position = self.position(symbol)
        return Portfolio(
            {
                symbol: Position(
                    settled_qty=position.settled_qty,
                    unsettled_buy_qty=position.unsettled_buy_qty,
                )
            }
        )
