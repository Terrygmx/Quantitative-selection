"""Minute-frequency backtest engine (FR-3.1): per trading day, every
universe symbol is priced at the latest minute bar at or before the
decision time - the tail-momentum snapshot semantics - and executed
through the shared core, so bars after the decision moment are invisible
by PIT construction and minute-level timestamps hit the real session
validation (lunch break, auction windows)."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Mapping
from zoneinfo import ZoneInfo

from quant_agent.adapters.market_data import DataUnavailable
from quant_agent.application.backtest import BacktestConfig, FillRecord, MultiInstrumentEvent
from quant_agent.application.execution import ExecutionCore
from quant_agent.domain.models import Instrument, Order
from quant_agent.rules.trading import MarketSnapshot, TradingRulesPlugin


CN_MARKET_TZ = ZoneInfo("Asia/Shanghai")
_END_OF_DAY = time(23, 59)


class MinuteBacktestEngine:
    def __init__(
        self,
        port,
        instruments: Mapping[str, Instrument],
        config: BacktestConfig,
        rules: TradingRulesPlugin,
        decision_time: str = "1431",
    ):
        self.port = port
        self.instruments = dict(instruments)
        self.config = config
        self.rules = rules
        self.core = ExecutionCore(config.initial_cash, config.costs, rules)
        hour, minute = int(decision_time[:2]), int(decision_time[2:])
        self.decision_clock = time(hour, minute)
        self.order_states = self.core.order_states
        self._orders: list[Order] = []
        self._fills: list[FillRecord] = []
        self._session_closes: dict[tuple[str, date], Decimal] = {}
        self._order_seq = 0

    @property
    def cash(self) -> Decimal:
        return self.core.cash

    def position(self, symbol: str):
        return self.core.position(symbol)

    def equity(self) -> Decimal:
        """Cash plus holdings marked at each symbol's latest visible close."""
        horizon = datetime(2999, 1, 1, tzinfo=CN_MARKET_TZ)
        total = self.cash
        for symbol, position in self.core.positions.items():
            quantity = position.settled_qty + position.unsettled_buy_qty
            if quantity <= 0:
                continue
            try:
                bars = self.port.bars(symbol, horizon)
            except DataUnavailable:
                continue
            if bars:
                total += Decimal(str(bars[-1].close)) * quantity
        return total

    def run(self) -> list[MultiInstrumentEvent]:
        events: list[MultiInstrumentEvent] = []
        for day in self._trading_days():
            decision_at = datetime.combine(day, self.decision_clock, tzinfo=CN_MARKET_TZ)
            events.append(MultiInstrumentEvent("SESSION_OPEN", decision_at))
            for symbol in sorted(self.instruments):
                bar = self._decision_bar(symbol, decision_at)
                if bar is None:
                    continue
                events.extend(self._buy_at(symbol, bar, decision_at))
            events.append(MultiInstrumentEvent("SESSION_CLOSE", decision_at))
            self.core.settle()
        return events

    def sell_settled(self, timestamp: datetime) -> list[MultiInstrumentEvent]:
        events: list[MultiInstrumentEvent] = []
        for symbol in sorted(self.instruments):
            position = self.core.positions.get(symbol)
            if position is None or position.settled_qty <= 0:
                continue
            bar = self._decision_bar(
                symbol,
                timestamp.astimezone(CN_MARKET_TZ),
            )
            if bar is None:
                continue
            events.extend(
                self._order_at(symbol, bar, timestamp, side="sell", quantity=position.settled_qty)
            )
        return events

    def _trading_days(self) -> list[date]:
        days: set[date] = set()
        horizon = datetime(2999, 1, 1, tzinfo=CN_MARKET_TZ)
        for symbol in self.instruments:
            try:
                bars = self.port.bars(symbol, horizon)
            except DataUnavailable:
                continue
            for bar in bars:
                days.add(bar.timestamp.astimezone(CN_MARKET_TZ).date())
        return sorted(days)

    def _decision_bar(self, symbol: str, decision_at: datetime):
        """Latest bar at or before the decision moment on the same CN
        trading day; later bars never leak in (PIT by construction)."""
        try:
            bars = self.port.bars(symbol, decision_at)
        except DataUnavailable:
            return None
        for bar in reversed(bars):
            if bar.timestamp.astimezone(CN_MARKET_TZ).date() == decision_at.date():
                return bar
        return None

    def _session_close(self, symbol: str, day: date) -> Decimal | None:
        cached = self._session_closes.get((symbol, day))
        if cached is not None:
            return cached
        end_of_day = datetime.combine(day, _END_OF_DAY, tzinfo=CN_MARKET_TZ)
        try:
            bars = self.port.bars(symbol, end_of_day)
        except DataUnavailable:
            return None
        value = None
        for bar in reversed(bars):
            if bar.timestamp.astimezone(CN_MARKET_TZ).date() == day:
                value = Decimal(str(bar.close))
                break
        if value is not None:
            self._session_closes[(symbol, day)] = value
        return value

    def _previous_close(self, symbol: str, day: date, fallback: Decimal) -> Decimal:
        previous = day
        for _ in range(7):
            previous = previous.fromordinal(previous.toordinal() - 1)
            value = self._session_close(symbol, previous)
            if value is not None:
                return value
        return fallback

    def _buy_at(self, symbol: str, bar, decision_at: datetime) -> list[MultiInstrumentEvent]:
        return self._order_at(
            symbol, bar, decision_at, side="buy", quantity=self.config.buy_quantity
        )

    def _order_at(
        self,
        symbol: str,
        bar,
        timestamp: datetime,
        side: str,
        quantity: int,
    ) -> list[MultiInstrumentEvent]:
        instrument = self.instruments[symbol]
        price = Decimal(str(bar.close))
        day = timestamp.astimezone(CN_MARKET_TZ).date()
        previous_close = self._previous_close(symbol, day, price)
        fill_price = self.core.order_price(instrument, price, side, timestamp)
        self._order_seq += 1
        order = Order(
            id=f"morder-{symbol}-{self._order_seq}",
            symbol=symbol,
            side=side,
            quantity=quantity,
            limit_price=fill_price,
            created_at=timestamp,
        )
        self._orders.append(order)
        events = [MultiInstrumentEvent("ORDER", timestamp, order=order)]
        market = MarketSnapshot(
            instrument=instrument,
            last=price,
            previous_close=previous_close,
            tradable=instrument.status == "Active",
        )
        outcome = self.core.execute_order(order, instrument, market)
        if outcome.status != "FILLED":
            return events
        fill = FillRecord(
            order.id, side, outcome.price, quantity, outcome.fee, timestamp
        )
        self._fills.append(fill)
        events.append(MultiInstrumentEvent("FILL", timestamp, fill=fill))
        return events
