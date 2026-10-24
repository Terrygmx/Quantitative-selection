from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping

from quant_agent.adapters.market_data import Bar
from quant_agent.domain.models import Signal
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.registry import StrategyMetadata
from quant_agent.strategies.tail_momentum.scoring import (
    DailyBar,
    MinutePoint,
    QuoteSnapshot,
    StockInput,
    TailMomentumMarket,
)
from quant_agent.strategies.tail_momentum.selection import (
    TailMomentumSelection,
    select_tail_momentum,
)


class TailMomentumStrategy:
    metadata = StrategyMetadata(
        strategy_id="tail_momentum_overnight",
        version="0.1.0",
        frequency="intraday",
    )

    def __init__(
        self,
        universe: Iterable[str] = ("sh600519",),
        *,
        history: Iterable[Mapping[str, object]] = (),
        indices: Mapping[
            str, tuple[float, Iterable[Bar]]
        ] | None = None,
        breadth: Mapping[str, object] | None = None,
        quotes: Mapping[str, Mapping[str, object]] | None = None,
    ):
        self.universe = tuple(universe)
        self.history = tuple(history)
        self.indices = indices or {}
        self.breadth = breadth
        self.quotes = quotes or {}
        self.last_selection: TailMomentumSelection | None = None

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "TailMomentumStrategy":
        universe = config["universe"]
        if not isinstance(universe, list):
            raise ValueError("universe must be a list")
        return cls(
            universe=universe,
        )

    def warmup(self) -> int:
        return 25

    def on_snapshot(self, ctx: StrategyContext) -> list[Signal]:
        market = self._market(ctx)
        self.last_selection = select_tail_momentum(
            market, snapshot=ctx.as_of.strftime("%H%M")
        )
        valid_to = ctx.as_of + timedelta(hours=19)
        return [
            Signal(
                strategy_id=self.metadata.strategy_id,
                version=self.metadata.version,
                symbol=result.symbol,
                side="long",
                target_weight=0.2,
                confidence=min(1.0, result.score.total / 100),
                valid_from=ctx.as_of,
                valid_to=valid_to,
                evidence={
                    "total": result.score.total,
                    "trend": result.score.trend,
                    "afternoon": result.score.afternoon,
                    "volume": result.score.volume,
                    "relative_strength": result.score.rs,
                    "environment": result.score.env,
                    "risk": result.score.risk,
                    "snapshot_close": result.score.snapshot_close,
                    "day_chg_pct": result.day_chg_pct,
                    "volume_surge": result.volume_surge,
                },
            )
            for result in self.last_selection.signals
        ]

    def _market(self, ctx: StrategyContext) -> TailMomentumMarket:
        stocks = []
        for symbol in self.universe:
            bars = ctx.data_port.bars(symbol, ctx.as_of)
            if len(bars) < self.warmup():
                raise ValueError(
                    f"{symbol} warmup requires at least {self.warmup()} bars"
                )
            quote_data = self.quotes.get(symbol, {})
            previous_close = _as_float(
                quote_data.get("prev_close", bars[0].open), "prev_close"
            )
            open_price = _as_float(quote_data.get("open", bars[0].open), "open")
            quote = QuoteSnapshot(
                symbol=symbol,
                name=str(quote_data.get("name", symbol)),
                previous_close=previous_close,
                open=open_price,
                price_ceiling=_optional_float(quote_data.get("price_ceiling")),
                price_floor=_optional_float(quote_data.get("price_floor")),
            )
            if not self.history:
                if len(bars) < 25:
                    raise ValueError(
                        f"{symbol} daily history requires at least 25 bars"
                    )
                daily_history = tuple(
                    DailyBar(
                        date=ctx.as_of.date(),
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                        amount=bar.amount,
                    )
                    for bar in bars
                )
            else:
                daily_history = tuple(
                    DailyBar(
                        date=_as_date(row.get("date")),
                        open=_as_float(row["open"], "open"),
                        high=_as_float(row["high"], "high"),
                        low=_as_float(row["low"], "low"),
                        close=_as_float(row["close"], "close"),
                        volume=_as_float(row["volume"], "volume"),
                        amount=_as_float(row.get("amount") or 0, "amount"),
                    )
                    for row in self.history
                )
            stocks.append(
                StockInput(
                    quote=quote,
                    daily=daily_history,
                    minute=tuple(
                        MinutePoint(
                            time=bar.timestamp.strftime("%H%M"),
                            price=bar.close,
                            volume=bar.volume,
                            amount=bar.amount,
                        )
                        for bar in bars
                    ),
                )
            )
        indices = {
            key: (
                previous_close,
                tuple(
                    MinutePoint(
                        time=point.timestamp.strftime("%H%M"),
                        price=point.close,
                        volume=point.volume,
                        amount=point.amount,
                    )
                    for point in points
                ),
            )
            for key, (previous_close, points) in self.indices.items()
        }
        return TailMomentumMarket(
            date=ctx.as_of.date(),
            stocks=tuple(stocks),
            indices=indices,
            breadth=_as_breadth(self.breadth),
        )


def _as_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _as_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field} must be numeric")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be numeric") from exc


def _optional_float(value: object) -> float | None:
    return None if value is None else _as_float(value, "quote value")


def _as_breadth(value: Mapping[str, object] | None) -> Mapping[str, float | None] | None:
    if value is None:
        return None
    return {key: _optional_float(item) for key, item in value.items()}
