from pathlib import Path

from tail_momentum_selector import (
    compute_intraday,
    compute_daily_indicators,
    compute_volume_surge,
    parse_changedist,
    parse_kline_batch,
    parse_minute,
    parse_quote_batch,
    score_market_env,
    slice_minute_up_to,
)


FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "legacy"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_snapshot_slice_excludes_minutes_after_1430():
    minute = parse_minute(read("minute_sh600176.md"))

    sliced = slice_minute_up_to(minute, "1430")

    assert sliced[-1]["time"] == "1430"
    assert all(row["time"] <= "1430" for row in sliced)


def test_stock_indicators_use_snapshot_minute_close():
    quote = parse_quote_batch(read("quote_sh600176.md"))["sh600176"]
    minute = parse_minute(read("minute_sh600176.md"))
    bars = parse_kline_batch(read("kline_sh600176.md"), default_code="sh600176")["sh600176"]

    intraday = compute_intraday(minute, "1430", quote["prev_close"], quote["open"])
    series = [{"date": row["date"], "close": row["close"], "high": row["high"], "low": row["low"], "volume": row["volume"]} for row in bars]
    daily = compute_daily_indicators(series)
    daily["close_proxy"] = intraday["cur"]
    volume_surge = compute_volume_surge(intraday, daily, "1430")

    assert intraday["cur"] == 46.82
    assert intraday["amount_cur"] == 12958892047.7
    assert daily["atr"] > 0
    assert volume_surge == 1.3225497468029523


def test_market_environment_uses_fixed_breadth_snapshot():
    breadth = parse_changedist(read("changedist.md"))

    label, points, detail = score_market_env(
        {"sh000300": -0.0067, "sh000852": -0.0041}, breadth
    )

    assert label == "Bear"
    assert points == 0
    assert detail["breadth_ratio"] == 20.4
