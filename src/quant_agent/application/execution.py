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


FILL_MODELS = frozenset({"slippage", "next_open", "vwap"})
BOARD_QUEUE_POLICIES = frozenset({"reject", "queue_fill"})
BOARD_LOCK_CODES = frozenset({"LIMIT_UP", "LIMIT_DOWN"})


@dataclass(frozen=True, slots=True)
class ExecutionCosts:
    commission_rate: Decimal
    stamp_tax_rate: Decimal
    slippage_rate: Decimal
    fill_model: str = "slippage"

    def __post_init__(self) -> None:
        if self.fill_model not in FILL_MODELS:
            raise ValueError(
                f"fill_model must be one of {sorted(FILL_MODELS)}"
            )

    def commission(self, gross: Decimal) -> Decimal:
        return gross * self.commission_rate

    def stamp_tax(self, gross: Decimal) -> Decimal:
        return gross * self.stamp_tax_rate

    def fill_price(
        self,
        instrument: Instrument,
        base: Decimal,
        side: str,
        reference: Decimal | None = None,
    ) -> Decimal:
        """`slippage` fills at base x (1 +/- slippage); `next_open` and
        `vwap` fill exactly at the caller-supplied reference price
        (DETAILED_DESIGN section 7 makes the fill model replaceable)."""
        if self.fill_model == "next_open":
            price = reference if reference is not None else base
        elif self.fill_model == "vwap":
            if reference is None:
                raise ValueError("vwap fill model requires a reference price")
            price = reference
        else:
            factor = 1 + self.slippage_rate if side == "buy" else 1 - self.slippage_rate
            price = base * factor
        # Fill prices must respect the instrument tick, or rules reject them.
        return price.quantize(instrument.tick, rounding=ROUND_HALF_UP)


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
        board_queue_policy: str = "reject",
    ) -> None:
        if board_queue_policy not in BOARD_QUEUE_POLICIES:
            raise ValueError(
                f"board_queue_policy must be one of {sorted(BOARD_QUEUE_POLICIES)}"
            )
        self.cash = initial_cash
        self.costs = costs
        self.rules = rules
        self.board_queue_policy = board_queue_policy
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
        reference: Decimal | None = None,
    ) -> Decimal:
        """Single pricing entry for both engines: after-hours fixed-price
        orders (marked, or submitted inside the session) fill exactly at the
        close (rules decide); everything else uses the configured fill
        model, tick-quantized."""
        after_hours = (
            session == "after_hours_fixed"
            or self.rules.is_after_hours_fixed_price_session(instrument, as_of)
        )
        if after_hours:
            return base.quantize(instrument.tick, rounding=ROUND_HALF_UP)
        return self.costs.fill_price(instrument, base, side, reference=reference)

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
            code = rejections[0].code
            if code in BOARD_LOCK_CODES and self.board_queue_policy == "queue_fill":
                # Locked-board queue model: the rules layer still adjudicates
                # WHAT a locked board is; with opposite-side volume evidence
                # covering the full order, the queued order fills at the
                # board price (no partial fills - the order state machine has
                # no partial state), otherwise it stays unfilled.
                board_volume = market.board_volume
                if board_volume is not None and board_volume >= order.quantity:
                    return self._settle_fill(order, market.last)
                if board_volume is None:
                    return self._reject(order, code)
                return self._reject(order, "BOARD_QUEUE_UNFILLED")
            return self._reject(order, code)
        return self._settle_fill(order, order.limit_price)

    def _settle_fill(self, order: Order, price: Decimal) -> ExecutionOutcome:
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
