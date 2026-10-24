from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.tail_momentum import TailMomentumStrategy
from tail_momentum_selector import (
    parse_changedist,
    parse_kline_batch,
    parse_minute,
    parse_quote_batch,
)


FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "legacy"
AS_OF = datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc)


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def minute_bars(symbol: str) -> list[Bar]:
    rows = parse_minute(read(f"minute_{symbol}.md"))
    result = []
    for row in rows:
        clock = row["time"].zfill(4)
        timestamp = datetime(2026, 9, 15, tzinfo=timezone.utc) + timedelta(
            minutes=int(clock[:2]) * 60 + int(clock[2:])
        )
        result.append(
            Bar(
                instrument=symbol,
                timestamp=timestamp,
                open=row["price"],
                high=row["price"],
                low=row["price"],
                close=row["price"],
                volume=row["volume"],
                amount=row["amount"],
                available_at=timestamp,
            )
        )
    return result


def strategy_for_fixture() -> TailMomentumStrategy:
    quote = parse_quote_batch(read("quote_sh600176.md"))["sh600176"]
    kline = parse_kline_batch(
        read("kline_sh600176.md"), default_code="sh600176"
    )["sh600176"]
    index_quotes = parse_quote_batch(read("index_quote.md"))
    index_points = {}
    for code in ("sh000001", "sz399001", "sz399006", "sh000300", "sh000852"):
        points = []
        for index, row in enumerate(parse_minute(read(f"index_minute_{code}.md"))):
            timestamp = datetime(2026, 9, 15, 9, 30, tzinfo=timezone.utc) + timedelta(
                minutes=index
            )
            points.append(
                Bar(
                    instrument=code,
                    timestamp=timestamp,
                    open=row["price"],
                    high=row["price"],
                    low=row["price"],
                    close=row["price"],
                    volume=row["volume"],
                    amount=row["amount"],
                    available_at=timestamp,
                )
            )
        index_points[code] = (index_quotes[code]["prev_close"], tuple(points))
    return TailMomentumStrategy(
        universe=("sh600176",),
        history=tuple(kline),
        indices=index_points,
        breadth=parse_changedist(read("changedist.md")),
        quotes={"sh600176": quote},
    )


def context(bars):
    return StrategyContext(InMemoryMarketDataPort(bars), AS_OF)


def test_strategy_declares_warmup_and_fails_when_history_is_missing():
    strategy = TailMomentumStrategy(universe=("sh600176",))

    assert strategy.warmup() == 25
    with pytest.raises(ValueError, match="warmup"):
        strategy.on_snapshot(
            context(minute_bars("sh600176")[: strategy.warmup() - 1])
        )


def test_strategy_cannot_see_future_minutes():
    bars = minute_bars("sh600176")
    future = Bar(
        instrument="sh600176",
        timestamp=AS_OF + timedelta(minutes=1),
        open=99,
        high=99,
        low=99,
        close=99,
        volume=10_000_000,
        amount=1_000_000_000,
        available_at=AS_OF + timedelta(minutes=1),
    )
    strategy = strategy_for_fixture()

    strategy.on_snapshot(context([*bars, future]))

    assert strategy.last_selection.results[0].score.snapshot_close == 46.82


def test_strategy_scans_configured_universe_instead_of_hardcoded_symbol():
    strategy = strategy_for_fixture()
    signals = strategy.on_snapshot(context(minute_bars("sh600176")))

    assert signals == []
    assert strategy.last_selection.results[0].symbol == "sh600176"
    assert strategy.last_selection.environment_label == "Bear"
