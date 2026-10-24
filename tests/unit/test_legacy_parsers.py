from pathlib import Path

from tail_momentum_selector import (
    parse_changedist,
    parse_kline_batch,
    parse_md_tables,
    parse_minute,
    parse_quote_batch,
)


FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "legacy"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_md_tables_ignores_separator_rows():
    tables = parse_md_tables(read("quote_sh600176.md"))

    assert len(tables) == 1
    headers, rows = tables[0]
    assert headers[:4] == ["code", "market_type", "market_name", "name"]
    assert rows[0][0] == "sh600176"


def test_parse_quote_batch_reads_numeric_fields():
    quotes = parse_quote_batch(read("quote_sh600176.md"))

    assert quotes["sh600176"]["name"] == "中国巨石"
    assert quotes["sh600176"]["price"] == 47.09
    assert quotes["sh600176"]["prev_close"] == 45.29
    assert quotes["sh600176"]["change_percent"] == 3.97


def test_parse_kline_batch_sorts_dates_and_keeps_amount():
    bars = parse_kline_batch(read("kline_sh600176.md"), default_code="sh600176")["sh600176"]

    assert len(bars) == 30
    assert bars[0]["date"] == "2026-08-05"
    last = bars[-1]
    assert (last["date"], last["close"], last["volume"]) == ("2026-09-15", 47.09, 3114227.0)
    assert last["amount"] == 0.0


def test_parse_minute_sorts_and_reads_cumulative_fields():
    minute = parse_minute(read("minute_sh600176.md"))

    assert minute[0]["time"] == "0930"
    assert minute[-1]["time"] == "1430"
    assert minute[-1]["price"] > 0
    assert minute[-1]["volume"] >= minute[0]["volume"]


def test_parse_changedist_reads_market_breadth():
    breadth = parse_changedist(read("changedist.md"))

    assert breadth == {
        "up": 1120,
        "down": 4376,
        "flat": 66,
        "limitup": 32,
        "limitdown": 34,
        "total": 0,
    }
