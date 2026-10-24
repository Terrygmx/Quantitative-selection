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


def bars_for(quote):
    minute = parse_minute(read("minute_sh600176.md"))
    return [
        Bar(
            instrument="sh600176",
            timestamp=datetime(2026, 9, 15, tzinfo=timezone.utc)
            + timedelta(minutes=int(row["time"].zfill(4)[:2]) * 60 + int(row["time"].zfill(4)[2:])),
            open=quote["open"],
            high=quote["high"],
            low=quote["low"],
            close=row["price"],
            volume=row["volume"],
            amount=row["amount"],
            available_at=datetime(2026, 9, 15, tzinfo=timezone.utc)
            + timedelta(minutes=int(row["time"].zfill(4)[:2]) * 60 + int(row["time"].zfill(4)[2:])),
        )
        for row in minute
    ]


def test_strategy_uses_pit_minute_bars_for_full_tail_momentum_selection():
    quote = parse_quote_batch(read("quote_sh600176.md"))["sh600176"]
    kline = parse_kline_batch(
        read("kline_sh600176.md"), default_code="sh600176"
    )["sh600176"]
    minute = parse_minute(read("minute_sh600176.md"))
    target_times = []
    for row in minute:
        clock = row["time"].zfill(4)
        minutes = int(clock[:2]) * 60 + int(clock[2:])
        timestamp = datetime(2026, 9, 15, tzinfo=timezone.utc) + timedelta(
            minutes=minutes
        )
        target_times.append(timestamp)
    bars = []
    for timestamp, row in zip(target_times, minute):
        bars.append(
            Bar(
                instrument="sh600176",
                timestamp=timestamp,
                open=quote["open"],
                high=quote["high"],
                low=quote["low"],
                close=row["price"],
                volume=row["volume"],
                amount=row["amount"],
                available_at=timestamp,
            )
        )
    index_quotes = parse_quote_batch(read("index_quote.md"))
    indices = {
        key: (
            index_quotes[code]["prev_close"],
            tuple(
                Bar(
                    instrument=code,
                        timestamp=datetime(2026, 9, 15, 9, 30, tzinfo=timezone.utc)
                        + timedelta(minutes=index),
                    open=row["price"],
                    high=row["price"],
                    low=row["price"],
                    close=row["price"],
                    volume=row["volume"],
                    amount=row["amount"],
                    available_at=AS_OF,
                )
                    for index, row in enumerate(
                        parse_minute(read(f"index_minute_{code}.md"))
                    )
            ),
        )
        for code, key in (
            ("sh000001", "sh000001"),
            ("sz399001", "sz399001"),
            ("sz399006", "sz399006"),
            ("sh000300", "hs300"),
            ("sh000852", "zz1000"),
        )
    }
    strategy = TailMomentumStrategy(
        universe=("sh600176",),
        history=tuple(kline),
        breadth=parse_changedist(read("changedist.md")),
        indices=indices,
    )

    signals = strategy.on_snapshot(StrategyContext(InMemoryMarketDataPort(bars), AS_OF))

    assert signals == []
    assert strategy.last_selection.to_signal_document()["excluded_count"] == 0
    assert strategy.last_selection.results[0].score.total == 62.0


def test_strategy_fails_closed_when_required_history_is_missing():
    times = [
        AS_OF - timedelta(minutes=4 - index)
        for index in range(5)
    ]
    strategy = TailMomentumStrategy(
        universe=("sh600176",),
        breadth=parse_changedist(read("changedist.md")),
    )
    with pytest.raises(ValueError, match="warmup"):
        strategy.on_snapshot(
            StrategyContext(InMemoryMarketDataPort([
                Bar(
                    instrument="sh600176",
                    timestamp=timestamp,
                    open=10,
                    high=10,
                    low=10,
                    close=10,
                    volume=100,
                    amount=1000,
                    available_at=timestamp,
                )
                for timestamp in times
            ]), AS_OF)
        )


def test_strategy_rejects_non_numeric_quote_data():
    quote = parse_quote_batch(read("quote_sh600176.md"))["sh600176"]
    kline = parse_kline_batch(
        read("kline_sh600176.md"), default_code="sh600176"
    )["sh600176"]
    strategy = TailMomentumStrategy(
        universe=("sh600176",),
        history=tuple(kline),
        breadth=parse_changedist(read("changedist.md")),
        quotes={"sh600176": {**quote, "open": "not-a-number"}},
    )

    with pytest.raises(ValueError, match="open must be numeric"):
        strategy.on_snapshot(
            StrategyContext(InMemoryMarketDataPort(bars_for(quote)), AS_OF)
        )
