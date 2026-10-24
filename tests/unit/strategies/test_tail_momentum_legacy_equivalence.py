from datetime import date
from pathlib import Path

import pytest

from quant_agent.strategies.tail_momentum.scoring import (
    DailyBar,
    MinutePoint,
    QuoteSnapshot,
    StockInput,
    TailMomentumMarket,
    build_daily_series,
    compute_daily_indicators,
    compute_intraday,
    compute_volume_surge,
    score_market_env,
    score_stock,
)
from tail_momentum_selector import (
    parse_changedist,
    parse_kline_batch,
    parse_minute,
    parse_quote_batch,
)


FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "legacy"
INDEX_KEYS = (
    ("sh000001", "sh000001"),
    ("sz399001", "sz399001"),
    ("sz399006", "sz399006"),
    ("sh000300", "hs300"),
    ("sh000852", "zz1000"),
)


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def minute_points(rows) -> tuple[MinutePoint, ...]:
    return tuple(
        MinutePoint(
            time=row["time"],
            price=row["price"],
            volume=row["volume"],
            amount=row["amount"],
        )
        for row in rows
    )


def fixture_inputs():
    quote = parse_quote_batch(read("quote_sh600176.md"))["sh600176"]
    kline = parse_kline_batch(
        read("kline_sh600176.md"), default_code="sh600176"
    )["sh600176"]
    stock = StockInput(
        quote=QuoteSnapshot(
            symbol="sh600176",
            name=quote["name"],
            previous_close=quote["prev_close"],
            open=quote["open"],
            price_ceiling=quote["price_ceiling"],
            price_floor=quote["price_floor"],
        ),
        daily=tuple(
            DailyBar(
                date=date.fromisoformat(row["date"]),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                amount=row["amount"],
            )
            for row in kline
        ),
        minute=minute_points(parse_minute(read("minute_sh600176.md"))),
    )
    index_quotes = parse_quote_batch(read("index_quote.md"))
    index_inputs = {}
    for code, key in INDEX_KEYS:
        index_inputs[key] = (
            index_quotes[code]["prev_close"],
            minute_points(parse_minute(read(f"index_minute_{code}.md"))),
        )
    return TailMomentumMarket(
        date=date(2026, 9, 15),
        stocks=(stock,),
        indices=index_inputs,
        breadth=parse_changedist(read("changedist.md")),
    )


def fixture_score():
    market = fixture_inputs()
    stock = market.stocks[0]
    intraday = compute_intraday(
        stock.minute, "1430", stock.quote.previous_close, stock.quote.open
    )
    daily = compute_daily_indicators(build_daily_series(stock.daily, intraday.cur))
    volume_surge = compute_volume_surge(intraday, daily, "1430")
    index_changes = market.index_changes("1430")
    label, points, detail = score_market_env(index_changes, market.breadth)
    score = score_stock(
        stock.quote,
        intraday,
        daily,
        volume_surge,
        index_changes,
        points,
    )
    return score, label, points, detail


def test_tail_momentum_scoring_matches_legacy_fixed_fixture():
    score, label, points, detail = fixture_score()

    assert (label, points) == ("Bear", 0)
    assert detail["idx_avg_chg"] == -0.62
    assert detail["breadth_ratio"] == 20.4
    assert score.snapshot_close == 46.82
    assert {
        key: getattr(score, key)
        for key in ("trend", "afternoon", "volume", "rs", "env", "risk", "total")
    } == {
        "trend": 17.0,
        "afternoon": 4.0,
        "volume": 18.0,
        "rs": 15.0,
        "env": 0.0,
        "risk": 8.0,
        "total": 62.0,
    }
    assert score.risk_detail["recent_up_streak"] == 4
    assert score.volume_detail["vol_surge"] == pytest.approx(1.3225497468029523)


def test_fixed_fixture_is_rejected_with_explicit_miss_reasons():
    score, label, _, _ = fixture_score()
    threshold = 80 if label == "Bear" else 70

    assert score.total < threshold
    assert score.afternoon < 12
