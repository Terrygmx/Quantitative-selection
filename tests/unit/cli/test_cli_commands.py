"""FR-6 operator CLIs: `strategy list` and `backtest run`.

Both follow the paper CLI conventions: JSON on stdout, exit 0 on success,
exit 2 with `error: ...` on stderr for bad configuration."""

import csv
import json
from datetime import date, datetime, timezone

import pytest

from quant_agent.cli.backtest import main as backtest_main
from quant_agent.cli.strategy import main as strategy_main


UTC = timezone.utc
D1 = date(2026, 9, 14)
D2 = date(2026, 9, 15)


def test_strategy_list_prints_registered_plugins(capsys):
    exit_code = strategy_main(["list"])

    out = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert {
        "strategy_id": "tail_momentum_overnight",
        "version": "0.1.0",
        "frequency": "intraday",
    } in out


def write_bars_csv(path):
    rows = []
    for symbol, closes in (("sh600519", (10.0, 10.2)), ("sz000001", (12.0, 12.2))):
        for day, close in zip((D1, D2), closes):
            stamp = datetime(day.year, day.month, day.day, 15, 0, tzinfo=UTC)
            rows.append(
                {
                    "instrument": symbol,
                    "timestamp": stamp.isoformat(),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000.0,
                    "amount": close * 1000,
                    "available_at": stamp.isoformat(),
                }
            )
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def backtest_inputs(tmp_path):
    bars = tmp_path / "bars.csv"
    instruments = tmp_path / "instruments.json"
    config = tmp_path / "backtest.json"
    write_bars_csv(bars)
    write_json(
        instruments,
        [
            {
                "symbol": "sh600519",
                "exchange": "SSE",
                "board": "MainBoard",
                "status": "Active",
                "listing_date": "2010-01-01",
                "tick": "0.01",
                "lot_size": 100,
            },
            {
                "symbol": "sz000001",
                "exchange": "SZSE",
                "board": "MainBoard",
                "status": "Active",
                "listing_date": "1991-04-03",
                "tick": "0.01",
                "lot_size": 100,
            },
        ],
    )
    write_json(
        config,
        {
            "initial_cash": "100000.00",
            "buy_quantity": 100,
            "commission_rate": "0.0003",
            "stamp_tax_rate": "0.0005",
            "slippage_rate": "0.001",
        },
    )
    return bars, instruments, config


def test_backtest_run_reports_orders_fills_and_summary(backtest_inputs, capsys):
    bars, instruments, config = backtest_inputs

    exit_code = backtest_main(
        [
            "run",
            "--bars", str(bars),
            "--instruments", str(instruments),
            "--config", str(config),
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(report["orders"]) == 4  # two symbols x two days
    assert {order["symbol"] for order in report["orders"]} == {
        "sh600519",
        "sz000001",
    }
    assert report["summary"]["fill_count"] == 4
    assert report["summary"]["total_return"] > 0


def test_backtest_run_fails_closed_on_missing_inputs(tmp_path, capsys):
    exit_code = backtest_main(
        [
            "run",
            "--bars", str(tmp_path / "missing.csv"),
            "--instruments", str(tmp_path / "missing.json"),
            "--config", str(tmp_path / "missing.json"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err.startswith("error:")


def test_backtest_run_honors_the_end_date(backtest_inputs, capsys):
    bars, instruments, config = backtest_inputs

    exit_code = backtest_main(
        [
            "run",
            "--bars", str(bars),
            "--instruments", str(instruments),
            "--config", str(config),
            "--end", "2026-09-14",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(report["orders"]) == 2  # first day only
    assert report["summary"]["fill_count"] == 2


def test_backtest_run_splits_in_and_out_of_sample(backtest_inputs, capsys):
    bars, instruments, config = backtest_inputs

    exit_code = backtest_main(
        [
            "run",
            "--bars", str(bars),
            "--instruments", str(instruments),
            "--config", str(config),
            "--split", "2026-09-15",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert set(report) == {"in_sample", "out_of_sample"}
    assert report["in_sample"]["summary"]["fill_count"] == 2
    assert report["out_of_sample"]["summary"]["fill_count"] == 2


def test_backtest_run_rejects_a_split_before_the_start(backtest_inputs, capsys):
    bars, instruments, config = backtest_inputs

    exit_code = backtest_main(
        [
            "run",
            "--bars", str(bars),
            "--instruments", str(instruments),
            "--config", str(config),
            "--start", "2026-09-14",
            "--split", "2026-09-01",
        ]
    )

    assert exit_code == 2
    assert capsys.readouterr().err.startswith("error:")


def test_backtest_run_compares_against_a_benchmark(backtest_inputs, capsys):
    bars, instruments, config = backtest_inputs

    exit_code = backtest_main(
        ["run", "--bars", str(bars), "--instruments", str(instruments),
         "--config", str(config), "--benchmark", "sh600519"]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["benchmark"]["symbol"] == "sh600519"
    assert report["benchmark"]["return"] == pytest.approx(0.02)  # 10.0 -> 10.2
    assert report["summary"]["excess_return"] == pytest.approx(
        report["summary"]["total_return"] - 0.02
    )


def test_backtest_run_rejects_unknown_benchmark(backtest_inputs, capsys):
    bars, instruments, config = backtest_inputs

    exit_code = backtest_main(
        ["run", "--bars", str(bars), "--instruments", str(instruments),
         "--config", str(config), "--benchmark", "sh999999"]
    )

    assert exit_code == 2


def test_backtest_run_rolling_windows(backtest_inputs, capsys):
    bars, instruments, config = backtest_inputs

    exit_code = backtest_main(
        ["run", "--bars", str(bars), "--instruments", str(instruments),
         "--config", str(config), "--window", "1"]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(report["windows"]) == 2
    assert [w["summary"]["fill_count"] for w in report["windows"]] == [2, 2]


def test_backtest_run_window_and_split_are_exclusive(backtest_inputs, capsys):
    bars, instruments, config = backtest_inputs

    exit_code = backtest_main(
        ["run", "--bars", str(bars), "--instruments", str(instruments),
         "--config", str(config), "--window", "1", "--split", "2026-09-15"]
    )

    assert exit_code == 2


def write_minute_csv(path):
    from datetime import datetime, timezone

    rows = []
    for day, closes in ((D1, ("10.0", "10.5")), (D2, ("10.2", "10.7"))):
        for hhmm, close in zip(("0931", "1431"), closes):
            stamp = datetime(
                day.year, day.month, day.day,
                int(hhmm[:2]) + 8, int(hhmm[2:]), tzinfo=timezone.utc,
            )  # 09:31/14:31 Shanghai expressed in UTC
            rows.append(
                {
                    "instrument": "sh600519",
                    "timestamp": stamp.isoformat(),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000.0,
                    "amount": 0.0,
                    "available_at": stamp.isoformat(),
                }
            )
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_backtest_run_minute_frequency(backtest_inputs, tmp_path, capsys):
    _, instruments, config = backtest_inputs
    minute_bars = tmp_path / "minute.csv"
    write_minute_csv(minute_bars)

    exit_code = backtest_main(
        ["run", "--bars", str(minute_bars), "--instruments", str(instruments),
         "--config", str(config), "--frequency", "minute", "--decision", "1431"]
    )

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    # sz000001 has no minute bars: skipped; sh600519 fills at both decisions.
    assert report["summary"]["fill_count"] == 2
    assert {order["symbol"] for order in report["orders"]} == {"sh600519"}


def test_backtest_run_minute_rejects_daily_only_options(backtest_inputs, tmp_path, capsys):
    _, instruments, config = backtest_inputs
    minute_bars = tmp_path / "minute.csv"
    write_minute_csv(minute_bars)

    exit_code = backtest_main(
        ["run", "--bars", str(minute_bars), "--instruments", str(instruments),
         "--config", str(config), "--frequency", "minute", "--window", "1"]
    )

    assert exit_code == 2
