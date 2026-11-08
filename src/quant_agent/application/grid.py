"""Grid trading backtest (resting limit orders on a price grid).

Levels sit between `grid_low` and `grid_high`. A buy order at level L is
armed while the last seen price is above L and fires when a bar's price
falls to or below L (fill at exactly L, no slippage); the mirror sell
order fires when the price rises to or above L and sells only settled
shares (T+1 enforced by the shared core). Every fill goes through
ExecutionCore, so fees, lot rules, bands and the ledger are identical to
the other engines. Bars are processed in timestamp order and each bar's
decision uses only that bar and earlier ones."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from quant_agent.ports.market_data import DataUnavailable
from quant_agent.application.backtest import FillRecord, MultiInstrumentEvent
from quant_agent.application.execution import ExecutionCore, ExecutionCosts
from quant_agent.domain.models import Instrument, Order
from quant_agent.rules.trading import MarketSnapshot, TradingRulesPlugin


@dataclass(frozen=True, slots=True)
class GridConfig:
    initial_cash: Decimal
    buy_quantity: int
    commission_rate: Decimal
    stamp_tax_rate: Decimal

    @property
    def costs(self) -> ExecutionCosts:
        # Grid fills happen at the level itself; next_open with an explicit
        # reference models that exactly (no slippage component).
        return ExecutionCosts(
            commission_rate=self.commission_rate,
            stamp_tax_rate=self.stamp_tax_rate,
            slippage_rate=Decimal("0"),
            fill_model="next_open",
        )


class GridBacktestEngine:
    def __init__(
        self,
        port,
        instruments: Mapping[str, Instrument],
        config: GridConfig,
        rules: TradingRulesPlugin,
        grid_low: Decimal,
        grid_high: Decimal,
        grid_steps: int,
    ):
        if grid_low >= grid_high:
            raise ValueError("grid_low must be below grid_high")
        if grid_steps < 2:
            raise ValueError("grid_steps must allow at least one interior level")
        self.port = port
        self.instruments = dict(instruments)
        self.config = config
        self.rules = rules
        self.core = ExecutionCore(config.initial_cash, config.costs, rules)
        self.order_states = self.core.order_states
        self.grid_low = grid_low
        self.grid_high = grid_high
        self.grid_steps = grid_steps
        self._orders: list[Order] = []
        self._fills: list[FillRecord] = []
        self._order_seq = 0
        self._last_price: dict[str, Decimal] = {}
        self._previous_close: dict[str, Decimal] = {}

    @property
    def cash(self) -> Decimal:
        return self.core.cash

    def position(self, symbol: str):
        return self.core.position(symbol)

    def equity(self) -> Decimal:
        """Cash plus holdings marked at each symbol's last seen price."""
        total = self.cash
        for symbol, position in self.core.positions.items():
            quantity = position.settled_qty + position.unsettled_buy_qty
            if quantity <= 0:
                continue
            last_price = self._last_price.get(symbol)
            if last_price is not None:
                total += last_price * quantity
        return total

    def grid_levels(self) -> list[Decimal]:
        step = (self.grid_high - self.grid_low) / self.grid_steps
        return [
            (self.grid_low + step * index).quantize(self.instruments and next(iter(self.instruments.values())).tick or Decimal("0.01"))
            for index in range(1, self.grid_steps)
        ]

    def run(self) -> list[MultiInstrumentEvent]:
        events: list[MultiInstrumentEvent] = []
        for symbol in sorted(self.instruments):
            events.extend(self._run_symbol(symbol))
        self.core.settle()
        return events

    def _run_symbol(self, symbol: str) -> list[MultiInstrumentEvent]:
        horizon = datetime(2999, 1, 1, tzinfo=self._tz())
        try:
            bars = self.port.bars(symbol, horizon)
        except DataUnavailable:
            return []
        levels = self.grid_levels()
        events: list[MultiInstrumentEvent] = []
        previous_day = None
        for bar in bars:
            price = Decimal(str(bar.close))
            day = bar.timestamp.astimezone(self._tz()).date()
            if previous_day is not None and day != previous_day:
                # Overnight settlement: shares bought on the previous day
                # become sellable at the day boundary (T+1).
                self.core.settle()
                # The band reference is the previous SESSION's close, not
                # the previous bar's price.
                self._previous_close[symbol] = self._last_price.get(symbol, price)
            previous_day = day
            last_price = self._last_price.get(symbol)
            timestamp = bar.timestamp
            if last_price is not None:
                for level in sorted(levels, reverse=True):
                    if last_price > level >= price:
                        events.extend(
                            self._order_at(symbol, level, price, "buy", timestamp)
                        )
                for level in sorted(levels):
                    if last_price < level <= price:
                        # Submit at full size; the rules layer owns the T+1
                        # settled-quantity check and rejects T1_UNSETTLED.
                        events.extend(
                            self._order_at(
                                symbol, level, price, "sell", timestamp
                            )
                        )
            self._last_price[symbol] = price
        return events

    def _order_at(
        self,
        symbol: str,
        level: Decimal,
        market_price: Decimal,
        side: str,
        timestamp: datetime,
        quantity: int | None = None,
    ) -> list[MultiInstrumentEvent]:
        instrument = self.instruments[symbol]
        size = quantity if quantity is not None else self.config.buy_quantity
        fill_price = self.core.order_price(
            instrument, level, side, timestamp, reference=level
        )
        self._order_seq += 1
        order = Order(
            id=f"grid-{symbol}-{self._order_seq}",
            symbol=symbol,
            side=side,
            quantity=size,
            limit_price=fill_price,
            created_at=timestamp,
        )
        self._orders.append(order)
        events = [MultiInstrumentEvent("ORDER", timestamp, order=order)]
        previous_close = self._previous_close.get(symbol, market_price)
        market = MarketSnapshot(
            instrument=instrument,
            last=market_price,
            previous_close=previous_close,
            tradable=instrument.status == "Active",
        )
        outcome = self.core.execute_order(order, instrument, market)
        if outcome.status != "FILLED":
            return events
        fill = FillRecord(order.id, side, outcome.price, size, outcome.fee, timestamp)
        self._fills.append(fill)
        events.append(MultiInstrumentEvent("FILL", timestamp, fill=fill))
        return events

    def _tz(self):
        from zoneinfo import ZoneInfo

        return ZoneInfo("Asia/Shanghai")
