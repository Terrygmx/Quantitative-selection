from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Mapping, Protocol

from quant_agent.application.orders import OrderStateMachine, PendingOrder
from quant_agent.domain.clock import Clock, SystemClock
from quant_agent.domain.models import Instrument, Order
from quant_agent.rules.trading import (
    MarketSnapshot,
    Portfolio,
    Position,
    TradingRulesPlugin,
)


def _parse_price(value: object) -> Decimal:
    """Snapshot prices come from vendor data, so unparseable values collapse
    to zero and are rejected downstream instead of raising."""
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return price if price.is_finite() else Decimal("0")


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    strategy_id: str
    config_hash: str
    approved_by: str


@dataclass(frozen=True, slots=True)
class PaperRunResult:
    status: str
    orders: list[Mapping[str, object]]


class PaperExecution(Protocol):
    def execute(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        run_at: datetime,
    ) -> list[Mapping[str, object]]: ...


class PaperGateway:
    def __init__(
        self,
        clock: Clock = SystemClock(),
        execution: PaperExecution | None = None,
    ) -> None:
        self.approvals: dict[tuple[str, str], ApprovalRecord] = {}
        self.clock = clock
        self.execution = execution

    def approve(self, approval: ApprovalRecord) -> None:
        self.approvals[(approval.strategy_id, approval.config_hash)] = approval

    def run(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        dry_run: bool,
        run_at: datetime | None = None,
    ) -> PaperRunResult:
        key = (strategy_id, str(config.get("config_hash", "")))
        if key not in self.approvals:
            raise ValueError("strategy configuration approval is required")
        if dry_run:
            return PaperRunResult(status="DRY_RUN", orders=[])
        if self.execution is None:
            raise ValueError("paper execution is not configured")
        occurred_at = run_at if run_at is not None else self.clock.now()
        orders = self.execution.execute(strategy_id, config, occurred_at)
        return PaperRunResult(status="PAPER_EXECUTED", orders=list(orders))


class PaperScheduler:
    def __init__(self, gateway: PaperGateway, dry_run: bool = True):
        self.gateway = gateway
        self.dry_run = dry_run
        self.history: list[dict[str, str]] = []

    def run(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        run_at: datetime | None = None,
    ) -> PaperRunResult:
        result = self.gateway.run(
            strategy_id,
            config,
            dry_run=self.dry_run,
            run_at=run_at,
        )
        self.history.append(
            {
                "strategy_id": strategy_id,
                "config_hash": str(config.get("config_hash", "")),
                "status": result.status,
                "run_at": run_at.isoformat() if run_at else "",
            }
        )
        return result


@dataclass(frozen=True, slots=True)
class PaperExecutionConfig:
    initial_cash: Decimal = Decimal("100000.00")
    commission_rate: Decimal = Decimal("0.0003")
    stamp_tax_rate: Decimal = Decimal("0.0005")
    slippage_rate: Decimal = Decimal("0.001")
    buy_quantity: int = 100


@dataclass
class PaperPosition:
    settled_qty: int = 0
    unsettled_buy_qty: int = 0


class SimulatedPaperExecution:
    """Deterministic paper fills that reuse the A-share rules and order ledger."""

    def __init__(
        self,
        config: PaperExecutionConfig,
        instruments: Mapping[str, Instrument],
        rules: TradingRulesPlugin,
    ) -> None:
        self.config = config
        self.instruments = dict(instruments)
        self.rules = rules
        self.cash = config.initial_cash
        self.positions: dict[str, PaperPosition] = {}
        self.order_states = OrderStateMachine()
        self._order_id = 0
        self._last_prices: dict[str, Decimal] = {}
        self._previous_closes: dict[str, Decimal] = {}
        self._tradable: dict[str, bool] = {}

    def execute(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        run_at: datetime,
        quantity: int | None = None,
    ) -> list[Mapping[str, object]]:
        market = config.get("market")
        if not isinstance(market, Mapping):
            raise ValueError("strategy config requires a market snapshot mapping")
        universe = self._universe(config)
        orders = []
        for symbol in universe:
            if symbol not in market:
                raise ValueError(
                    f"{symbol} market snapshot is required to trade the universe"
                )
            instrument = self.instruments.get(symbol)
            if instrument is None:
                raise ValueError(f"{symbol} instrument metadata is required")
            snapshot_data = market[symbol]
            is_mapping = isinstance(snapshot_data, Mapping)
            # A suspension observed on any snapshot blocks sells until the
            # instrument is seen tradable again.
            self._tradable[symbol] = self._tradable.get(symbol, True) and (
                bool(snapshot_data.get("tradable", True)) if is_mapping else True
            )
            last = _parse_price(
                snapshot_data.get("last") if is_mapping else None
            )
            previous_close = _parse_price(
                snapshot_data.get("previous_close") if is_mapping else None
            )
            self._last_prices[symbol] = last
            self._previous_closes[symbol] = (
                previous_close if previous_close > 0 else last
            )
            orders.append(
                self._buy_symbol(instrument, market[symbol], run_at, quantity)
            )
        return orders

    @staticmethod
    def _universe(
        config: Mapping[str, object],
    ) -> list[str]:
        """Only configured universe symbols may trade; the snapshot may carry
        extra reference data that is never an order target."""
        raw = config.get("universe")
        if not isinstance(raw, list) or not raw:
            raise ValueError("strategy config requires a non-empty universe")
        return [str(symbol) for symbol in raw]

    def position(self, symbol: str) -> PaperPosition:
        return self.positions.setdefault(symbol, PaperPosition())

    def settle(self) -> None:
        for position in self.positions.values():
            position.settled_qty += position.unsettled_buy_qty
            position.unsettled_buy_qty = 0

    def sell_all(self, timestamp: datetime) -> list[Mapping[str, object]]:
        orders = []
        for symbol in sorted(self.positions):
            position = self.positions[symbol]
            if position.settled_qty <= 0:
                continue
            orders.append(
                self._sell_symbol(
                    self.instruments[symbol], position.settled_qty, timestamp
                )
            )
        return orders

    def _buy_symbol(
        self,
        instrument: Instrument,
        snapshot: object,
        timestamp: datetime,
        quantity: int | None,
    ) -> dict[str, object]:
        market = self._market_snapshot(instrument, snapshot)
        size = quantity if quantity is not None else self.config.buy_quantity
        if market.last <= 0:
            return self._reject_intent(
                instrument.symbol, "buy", size, "INVALID_PRICE", timestamp
            )
        fill_price = self._tick_price(
            instrument, market.last * (1 + self.config.slippage_rate)
        )
        order = self._create_order(
            instrument.symbol, "buy", size, fill_price, timestamp
        )
        return self._settle_order(
            order, market, timestamp, buy=True, price=fill_price
        )

    def _sell_symbol(
        self, instrument: Instrument, quantity: int, timestamp: datetime
    ) -> dict[str, object]:
        last = self._last_prices.get(instrument.symbol)
        if last is None:
            raise ValueError(
                f"{instrument.symbol} has no observed market price to sell"
            )
        snapshot = {
            "last": str(last),
            "previous_close": str(
                self._previous_closes.get(instrument.symbol, last)
            ),
            "tradable": self._tradable.get(instrument.symbol, True),
        }
        market = self._market_snapshot(instrument, snapshot)
        fill_price = self._tick_price(
            instrument, market.last * (1 - self.config.slippage_rate)
        )
        order = self._create_order(
            instrument.symbol, "sell", quantity, fill_price, timestamp
        )
        return self._settle_order(
            order, market, timestamp, buy=False, price=fill_price
        )

    def _settle_order(
        self,
        order: Order,
        market: MarketSnapshot,
        timestamp: datetime,
        *,
        buy: bool,
        price: Decimal,
    ) -> dict[str, object]:
        self.order_states.submit(PendingOrder(order.id, order.created_at))
        position = self.position(order.symbol)
        portfolio = Portfolio(
            {
                order.symbol: Position(
                    settled_qty=position.settled_qty,
                    unsettled_buy_qty=position.unsettled_buy_qty,
                )
            }
        )
        rejections = self.rules.validate_order(order, portfolio, market)
        if rejections:
            return self._reject(order, rejections[0].code, timestamp)
        gross = price * order.quantity
        fee = gross * self.config.commission_rate
        tax = gross * self.config.stamp_tax_rate if not buy else Decimal("0")
        if buy:
            if gross + fee > self.cash:
                return self._reject(order, "INSUFFICIENT_CASH", timestamp)
            self.cash -= gross + fee
            position.unsettled_buy_qty += order.quantity
        else:
            self.cash += gross - fee - tax
            position.settled_qty -= order.quantity
        self.order_states.fill(order.id, timestamp)
        return {
            "order_id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "price": str(price),
            "fee": str(fee + tax),
            "status": "FILLED",
            "timestamp": timestamp.isoformat(),
        }

    def _reject(
        self, order: Order, reason_code: str, timestamp: datetime
    ) -> dict[str, object]:
        self.order_states.reject(order.id, reason_code, timestamp)
        return {
            "order_id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "price": str(order.limit_price),
            "fee": "0",
            "status": "REJECTED",
            "reason_code": reason_code,
            "timestamp": timestamp.isoformat(),
        }

    def _reject_intent(
        self,
        symbol: str,
        side: str,
        quantity: int,
        reason_code: str,
        timestamp: datetime,
    ) -> dict[str, object]:
        """Reject an intent that never became a valid `Order` (e.g. a
        non-positive snapshot price), while keeping the audit ledger complete."""
        self._order_id += 1
        order_id = f"paper-{self._order_id}"
        self.order_states.submit(PendingOrder(order_id, timestamp))
        self.order_states.reject(order_id, reason_code, timestamp)
        return {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": "0",
            "fee": "0",
            "status": "REJECTED",
            "reason_code": reason_code,
            "timestamp": timestamp.isoformat(),
        }

    def _create_order(
        self, symbol: str, side: str, quantity: int, price: Decimal, timestamp: datetime
    ) -> Order:
        self._order_id += 1
        return Order(
            id=f"paper-{self._order_id}",
            symbol=symbol,
            side=side,
            quantity=quantity,
            limit_price=price,
            created_at=timestamp,
        )

    def _market_snapshot(
        self, instrument: Instrument, snapshot: object
    ) -> MarketSnapshot:
        data = snapshot if isinstance(snapshot, Mapping) else {}
        last = _parse_price(data.get("last"))
        previous_close = _parse_price(data.get("previous_close"))
        tradable = bool(data.get("tradable", True))
        return MarketSnapshot(
            instrument=instrument,
            last=last,
            previous_close=previous_close if previous_close > 0 else last,
            tradable=tradable,
        )

    @staticmethod
    def _tick_price(instrument: Instrument, price: Decimal) -> Decimal:
        # Order prices must respect the instrument tick, or rules reject them.
        return price.quantize(instrument.tick, rounding=ROUND_HALF_UP)
