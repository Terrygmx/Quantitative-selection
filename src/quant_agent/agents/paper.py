from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping, Protocol
from zoneinfo import ZoneInfo

from quant_agent.application.execution import (
    ExecutionCore,
    ExecutionCosts,
    ExecutionOutcome,
    ExecutionPosition,
)
from quant_agent.application.paper_strategy import PaperStrategyPlan
from quant_agent.application.paper_strategy import PaperStrategyIdentity
from quant_agent.application.portfolio import (
    ComposerSignal,
    RiskDecision,
    TargetPosition,
)
from quant_agent.domain.models import Instrument, Order, RunManifest
from quant_agent.ports.clock import Clock, SystemClock
from quant_agent.rules.trading import (
    MarketSnapshot,
    TradingRulesPlugin,
)

CN_MARKET_TZ = ZoneInfo("Asia/Shanghai")


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
    strategy_version: str
    config_hash: str
    data_snapshot: str
    approved_by: str

    def __post_init__(self) -> None:
        for field in (
            self.strategy_id,
            self.strategy_version,
            self.config_hash,
            self.data_snapshot,
            self.approved_by,
        ):
            if not field.strip():
                raise ValueError("approval fields must be non-empty")


@dataclass(frozen=True, slots=True)
class PaperRunResult:
    status: str
    orders: list[Mapping[str, object]]
    as_of: datetime
    strategy_version: str
    config_hash: str
    data_snapshot: str
    read_snapshot: str
    manifest: RunManifest
    signals: tuple[ComposerSignal, ...]
    decisions: tuple[RiskDecision, ...]
    targets: tuple[TargetPosition, ...]


class PaperExecution(Protocol):
    def execute(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        run_at: datetime,
    ) -> list[Mapping[str, object]]: ...


class PaperStrategyEvaluator(Protocol):
    def identity(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        as_of: datetime,
    ) -> PaperStrategyIdentity: ...

    def evaluate(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        as_of: datetime,
    ) -> PaperStrategyPlan: ...


class PaperGateway:
    def __init__(
        self,
        clock: Clock = SystemClock(),
        execution: PaperExecution | None = None,
        strategy_evaluator: PaperStrategyEvaluator | None = None,
    ) -> None:
        self.approvals: dict[tuple[str, str], ApprovalRecord] = {}
        self.clock = clock
        self.execution = execution
        self.strategy_evaluator = strategy_evaluator

    def approve(self, approval: ApprovalRecord) -> None:
        self.approvals[(approval.strategy_id, approval.config_hash)] = approval

    def run(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        dry_run: bool,
        run_at: datetime | None = None,
    ) -> PaperRunResult:
        if self.strategy_evaluator is None:
            raise ValueError("strategy evaluator is not configured")
        requested_at = run_at if run_at is not None else self.clock.now()
        if requested_at.tzinfo is None:
            raise ValueError("paper run time must be timezone-aware")
        occurred_at = requested_at.astimezone(CN_MARKET_TZ)
        identity = self.strategy_evaluator.identity(
            strategy_id,
            config,
            occurred_at,
        )
        if identity.strategy_id != strategy_id:
            raise ValueError(
                "strategy configuration approval binding does not match"
            )
        key = (strategy_id, identity.config_hash)
        approval = self.approvals.get(key)
        if approval is None:
            raise ValueError("strategy configuration approval is required")
        if approval.strategy_version != identity.strategy_version:
            raise ValueError(
                "strategy configuration approval binding does not match"
            )
        if not dry_run and self.execution is None:
            raise ValueError("paper execution is not configured")
        plan = self.strategy_evaluator.evaluate(
            strategy_id,
            config,
            occurred_at,
        )
        if (
            plan.strategy_id != strategy_id
            or plan.config_hash != identity.config_hash
            or plan.strategy_version != identity.strategy_version
            or plan.data_snapshot != approval.data_snapshot
        ):
            raise ValueError(
                "strategy configuration approval binding does not match"
            )
        if not plan.targets:
            return self._result("NO_SIGNAL", plan, [], occurred_at)
        if dry_run:
            return self._result("DRY_RUN", plan, [], occurred_at)
        if not plan.execution_symbols:
            return self._result("PAPER_EXECUTED", plan, [], occurred_at)
        execution_config = dict(config)
        execution_config["universe"] = list(plan.execution_symbols)
        execution = self.execution
        if execution is None:
            raise ValueError("paper execution is not configured")
        orders = execution.execute(
            strategy_id,
            execution_config,
            occurred_at,
        )
        for order in orders:
            self._validate_order(order, plan.execution_symbols)
        return self._result(
            "PAPER_EXECUTED", plan, list(orders), occurred_at
        )

    @staticmethod
    def _validate_order(
        order: Mapping[str, object],
        accepted_symbols: tuple[str, ...],
    ) -> None:
        if not isinstance(order, Mapping):
            raise ValueError("paper executor returned a non-object order")
        symbol = order.get("symbol")
        if not isinstance(symbol, str) or symbol not in accepted_symbols:
            raise ValueError(
                "paper executor returned an order outside accepted targets"
            )
        if order.get("side") != "buy":
            raise ValueError(
                "paper executor returned an unsupported order direction"
            )
        quantity = order.get("quantity")
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise ValueError(
                "paper executor returned an invalid order quantity"
            )
        status = order.get("status")
        if not isinstance(status, str) or status not in {
            "FILLED",
            "REJECTED",
            "QUEUED_AFTER_HOURS",
            "EXPIRED",
        }:
            raise ValueError("paper executor returned an invalid order status")

    @staticmethod
    def _result(
        status: str,
        plan: PaperStrategyPlan,
        orders: list[Mapping[str, object]],
        as_of: datetime,
    ) -> PaperRunResult:
        return PaperRunResult(
            status=status,
            orders=orders,
            as_of=as_of,
            strategy_version=plan.strategy_version,
            config_hash=plan.config_hash,
            data_snapshot=plan.data_snapshot,
            read_snapshot=plan.read_snapshot,
            manifest=plan.manifest,
            signals=plan.signals,
            decisions=plan.decisions,
            targets=plan.targets,
        )


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
                "strategy_version": result.strategy_version,
                "config_hash": result.config_hash,
                "data_snapshot": result.data_snapshot,
                "run_id": result.manifest.run_id,
                "status": result.status,
                "run_at": result.as_of.isoformat(),
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
    fill_model: str = "slippage"
    board_queue_policy: str = "reject"

    def __post_init__(self) -> None:
        decimals = (
            ("initial_cash", self.initial_cash, False),
            ("commission_rate", self.commission_rate, True),
            ("stamp_tax_rate", self.stamp_tax_rate, True),
            ("slippage_rate", self.slippage_rate, True),
        )
        for field, value, allow_zero in decimals:
            if not isinstance(value, Decimal):
                raise ValueError(f"{field} must be a Decimal")
            if not value.is_finite() or value < 0 or (
                not allow_zero and value == 0
            ):
                relation = "non-negative" if allow_zero else "positive"
                raise ValueError(f"{field} must be finite and {relation}")
        if (
            isinstance(self.buy_quantity, bool)
            or not isinstance(self.buy_quantity, int)
            or self.buy_quantity <= 0
        ):
            raise ValueError("buy_quantity must be a positive integer")
        if (
            not isinstance(self.fill_model, str)
            or self.fill_model not in {"slippage", "next_open", "vwap"}
        ):
            raise ValueError("fill_model must be slippage, next_open or vwap")
        if (
            not isinstance(self.board_queue_policy, str)
            or self.board_queue_policy not in {"reject", "queue_fill"}
        ):
            raise ValueError(
                "board_queue_policy must be reject or queue_fill"
            )

    @property
    def costs(self) -> ExecutionCosts:
        return ExecutionCosts(
            commission_rate=self.commission_rate,
            stamp_tax_rate=self.stamp_tax_rate,
            slippage_rate=self.slippage_rate,
            fill_model=self.fill_model,
        )


PaperPosition = ExecutionPosition


@dataclass
class AfterHoursIntent:
    """An after-hours fixed-price buy submitted intraday; it matches at the
    day's closing price during 15:05-15:30 and never fills otherwise."""

    intent_id: str
    symbol: str
    side: str
    quantity: int
    submitted_at: datetime


class SimulatedPaperExecution:
    """Deterministic paper fills routed through the shared execution core."""

    def __init__(
        self,
        config: PaperExecutionConfig,
        instruments: Mapping[str, Instrument],
        rules: TradingRulesPlugin,
    ) -> None:
        self.config = config
        self.instruments = dict(instruments)
        self.rules = rules
        self.core = ExecutionCore(
            config.initial_cash,
            config.costs,
            rules,
            board_queue_policy=config.board_queue_policy,
        )
        self._order_id = 0
        self._last_prices: dict[str, Decimal] = {}
        self._previous_closes: dict[str, Decimal] = {}
        self._tradable: dict[str, bool] = {}
        self._vwap_references: dict[str, Decimal] = {}
        self.after_hours_queue: list[AfterHoursIntent] = []

    @property
    def cash(self) -> Decimal:
        return self.core.cash

    @property
    def order_states(self):
        return self.core.order_states

    def position(self, symbol: str) -> PaperPosition:
        return self.core.position(symbol)

    def settle(self) -> None:
        self.core.settle()

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
        session = self._session(config)
        universe = self._universe(config)
        raw_previous = config.get("previous_close_by_symbol", {})
        if not isinstance(raw_previous, Mapping):
            raise ValueError("previous_close_by_symbol must be a mapping")
        previous_by_symbol = {
            str(symbol): _parse_price(value)
            for symbol, value in raw_previous.items()
        }
        prepared_market: dict[str, dict[str, object]] = {}
        for symbol in universe:
            snapshot_data = market.get(symbol)
            if not isinstance(snapshot_data, Mapping):
                raise ValueError(
                    f"{symbol} market snapshot is required to trade the universe"
                )
            last = _parse_price(snapshot_data.get("last"))
            previous_close = _parse_price(
                snapshot_data.get("previous_close")
            )
            if previous_close <= 0:
                previous_close = previous_by_symbol.get(symbol, Decimal("0"))
            if previous_close <= 0:
                raise ValueError(
                    f"{symbol} market snapshot requires a positive previous_close"
                )
            tradable = snapshot_data.get("tradable", True)
            if not isinstance(tradable, bool):
                raise ValueError(
                    f"{symbol} market snapshot tradable must be a boolean"
                )
            board_volume = snapshot_data.get("board_volume")
            if board_volume not in (None, ""):
                parsed_board = _parse_price(board_volume)
                if parsed_board < 0:
                    raise ValueError(
                        f"{symbol} market snapshot board_volume must be non-negative"
                    )
            prepared_market[symbol] = {
                **dict(snapshot_data),
                "last": str(last),
                "previous_close": str(previous_close),
            }
        market = prepared_market
        orders: list[Mapping[str, object]] = []
        if session == "after_hours_fixed":
            orders.extend(self._match_after_hours_queue(market, run_at))
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
            self._previous_closes[symbol] = previous_close
            if self.config.fill_model == "vwap":
                self._vwap_references[symbol] = self._vwap_reference(
                    snapshot_data, symbol
                )
            if session == "after_hours_fixed":
                orders.append(
                    self._after_hours_intent(
                        instrument, market[symbol], run_at, quantity
                    )
                )
            else:
                orders.append(
                    self._buy_symbol(instrument, market[symbol], run_at, quantity)
                )
        return orders

    @staticmethod
    def _session(config: Mapping[str, object]) -> str:
        session = str(config.get("session", "continuous"))
        if session not in ("continuous", "after_hours_fixed"):
            raise ValueError("session must be continuous or after_hours_fixed")
        return session

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

    def sell_all(self, timestamp: datetime) -> list[Mapping[str, object]]:
        orders: list[Mapping[str, object]] = []
        for symbol in sorted(self.core.positions):
            position = self.core.positions[symbol]
            if position.settled_qty <= 0:
                continue
            orders.append(
                self._sell_symbol(
                    self.instruments[symbol], position.settled_qty, timestamp
                )
            )
        return orders

    def _after_hours_intent(
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
        gate = self.rules.after_hours_submission_gate(instrument, timestamp)
        if gate is not None:
            return self._reject_intent(
                instrument.symbol, "buy", size, gate.code, timestamp
            )
        if self.rules.is_after_hours_fixed_price_session(instrument, timestamp):
            fill_price = self.core.order_price(
                instrument, market.last, "buy", timestamp, session="after_hours_fixed"
            )
            order = self._create_order(
                instrument.symbol, "buy", size, fill_price, timestamp,
                session="after_hours_fixed",
            )
            return self._execute(order, instrument, market)
        self._order_id += 1
        intent = AfterHoursIntent(
            intent_id=f"paper-{self._order_id}",
            symbol=instrument.symbol,
            side="buy",
            quantity=size,
            submitted_at=timestamp,
        )
        self.after_hours_queue.append(intent)
        return self._intent_result(intent, "QUEUED_AFTER_HOURS", timestamp)

    def _match_after_hours_queue(
        self, market: Mapping[str, object], run_at: datetime
    ) -> list[dict[str, object]]:
        """Match day-scoped queued intents at the close during the 15:05-15:30
        window; intents from an earlier day expire, everything else waits."""
        results: list[dict[str, object]] = []
        remaining: list[AfterHoursIntent] = []
        for intent in self.after_hours_queue:
            instrument = self.instruments.get(intent.symbol)
            if instrument is None:
                remaining.append(intent)
                continue
            if self._cn_date(intent.submitted_at) != self._cn_date(run_at):
                results.append(self._intent_result(intent, "EXPIRED", run_at))
                continue
            if not self.rules.is_after_hours_fixed_price_session(instrument, run_at):
                remaining.append(intent)
                continue
            snapshot = market.get(intent.symbol)
            if not isinstance(snapshot, Mapping):
                remaining.append(intent)
                continue
            market_view = self._market_snapshot(instrument, snapshot)
            if market_view.last <= 0:
                self.core.reject_intent(intent.intent_id, "INVALID_PRICE", run_at)
                rejected = self._intent_result(intent, "REJECTED", run_at)
                rejected["reason_code"] = "INVALID_PRICE"
                results.append(rejected)
                continue
            price = self.core.order_price(
                instrument, market_view.last, intent.side, run_at,
                session="after_hours_fixed",
            )
            order = Order(
                id=intent.intent_id,
                symbol=intent.symbol,
                side=intent.side,
                quantity=intent.quantity,
                limit_price=price,
                created_at=run_at,
                session="after_hours_fixed",
            )
            result = self._execute(order, instrument, market_view)
            result["submitted_at"] = intent.submitted_at.isoformat()
            results.append(result)
        self.after_hours_queue = remaining
        return results

    @staticmethod
    def _cn_date(moment: datetime) -> object:
        return moment.astimezone(CN_MARKET_TZ).date()

    def _intent_result(
        self, intent: AfterHoursIntent, status: str, timestamp: datetime
    ) -> dict[str, object]:
        return {
            "order_id": intent.intent_id,
            "symbol": intent.symbol,
            "side": intent.side,
            "quantity": intent.quantity,
            "price": "0",
            "fee": "0",
            "status": status,
            "submitted_at": intent.submitted_at.isoformat(),
            "timestamp": timestamp.isoformat(),
        }

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
        fill_price = self.core.order_price(
            instrument,
            market.last,
            "buy",
            timestamp,
            reference=(
                self._vwap_references.get(instrument.symbol)
                if self.config.fill_model == "vwap"
                else None
            ),
        )
        order = self._create_order(
            instrument.symbol, "buy", size, fill_price, timestamp
        )
        return self._execute(order, instrument, market)

    def _sell_symbol(
        self, instrument: Instrument, quantity: int, timestamp: datetime
    ) -> dict[str, object]:
        last = self._last_prices.get(instrument.symbol)
        if last is None:
            raise ValueError(
                f"{instrument.symbol} has no observed market price to sell"
            )
        previous_close = self._previous_closes.get(instrument.symbol)
        if previous_close is None:
            raise ValueError(
                f"{instrument.symbol} has no previous close to price a sell"
            )
        snapshot = {
            "last": str(last),
            "previous_close": str(previous_close),
            "tradable": self._tradable.get(instrument.symbol, True),
        }
        market = self._market_snapshot(instrument, snapshot)
        fill_price = self.core.order_price(
            instrument,
            market.last,
            "sell",
            timestamp,
            reference=(
                self._vwap_references.get(instrument.symbol)
                if self.config.fill_model == "vwap"
                else None
            ),
        )
        order = self._create_order(
            instrument.symbol, "sell", quantity, fill_price, timestamp
        )
        return self._execute(order, instrument, market)

    def _execute(
        self,
        order: Order,
        instrument: Instrument,
        market: MarketSnapshot,
    ) -> dict[str, object]:
        outcome = self.core.execute_order(order, instrument, market)
        return self._as_result(outcome)

    @staticmethod
    def _as_result(outcome: ExecutionOutcome) -> dict[str, object]:
        result: dict[str, object] = {
            "order_id": outcome.order_id,
            "symbol": outcome.symbol,
            "side": outcome.side,
            "quantity": outcome.quantity,
            "price": str(outcome.price),
            "fee": str(outcome.fee),
            "status": outcome.status,
            "timestamp": outcome.timestamp.isoformat(),
        }
        if outcome.reason_code is not None:
            result["reason_code"] = outcome.reason_code
        return result

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
        self.core.reject_intent(order_id, reason_code, timestamp)
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
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: Decimal,
        timestamp: datetime,
        session: str = "continuous",
    ) -> Order:
        self._order_id += 1
        return Order(
            id=f"paper-{self._order_id}",
            symbol=symbol,
            side=side,
            quantity=quantity,
            limit_price=price,
            created_at=timestamp,
            session=session,
        )

    def _market_snapshot(
        self, instrument: Instrument, snapshot: object
    ) -> MarketSnapshot:
        data = snapshot if isinstance(snapshot, Mapping) else {}
        last = _parse_price(data.get("last"))
        previous_close = _parse_price(data.get("previous_close"))
        tradable = data.get("tradable", True) is not False
        raw_board_volume = data.get("board_volume")
        board_volume = (
            _parse_price(raw_board_volume)
            if raw_board_volume not in (None, "")
            else None
        )
        return MarketSnapshot(
            instrument=instrument,
            last=last,
            previous_close=previous_close,
            tradable=tradable,
            board_volume=board_volume,
        )

    @staticmethod
    def _vwap_reference(snapshot: object, symbol: str) -> Decimal:
        data = snapshot if isinstance(snapshot, Mapping) else {}
        amount = _parse_price(data.get("amount"))
        volume = _parse_price(data.get("volume"))
        if amount <= 0 or volume <= 0:
            raise ValueError(
                f"{symbol} vwap fill requires positive amount and volume"
            )
        return amount / volume
