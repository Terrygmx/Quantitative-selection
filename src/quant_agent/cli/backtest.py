"""`quant-agent backtest` CLI: run the multi-instrument engine over a CSV
bar file and print an orders/fills/summary JSON report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence

from quant_agent.adapters.market_data import CsvMarketDataPort
from quant_agent.application.backtest import (
    BacktestConfig,
    MultiInstrumentBacktestEngine,
)
from quant_agent.application.grid import GridBacktestEngine, GridConfig
from quant_agent.application.intraday import MinuteBacktestEngine
from quant_agent.application.metrics import BacktestMetrics
from quant_agent.domain.models import Instrument
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc


def _decimal(value: object, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal string") from exc


def _bars_for_engine(
    port: CsvMarketDataPort,
    symbols: Sequence[str],
    start: date | None = None,
    end: date | None = None,
) -> dict[str, list[Mapping[str, object]]]:
    as_of = datetime.now(timezone.utc)
    bars: dict[str, list[Mapping[str, object]]] = {}
    for symbol in symbols:
        rows = port.bars(symbol, as_of)
        previous_close: float | None = None
        entries: list[Mapping[str, object]] = []
        for row in rows:
            day = row.timestamp.date()
            if start is not None and day < start:
                continue
            if end is not None and day > end:
                continue
            close = row.close
            entries.append(
                {
                    "date": day,
                    "open": str(row.open),
                    "close": str(close),
                    "previous_close": str(
                        previous_close if previous_close is not None else row.open
                    ),
                }
            )
            previous_close = close
        if entries:
            bars[symbol] = entries
    return bars


def _iso_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _run(args: argparse.Namespace) -> dict[str, object]:
    start = _iso_date(args.start, "--start") if args.start else None
    end = _iso_date(args.end, "--end") if args.end else None
    split = _iso_date(args.split, "--split") if args.split else None
    window = int(args.window) if args.window else 0
    if args.frequency == "minute":
        if split is not None or window or args.start or args.end:
            raise ValueError(
                "--frequency minute runs the full minute history; "
                "--start/--end/--split/--window are daily-frequency only"
            )
        if args.grid_steps:
            return _run_grid(args)
        return _run_minute(args)
    if split is not None and window:
        raise ValueError("--split and --window are mutually exclusive")
    if split is not None:
        if start is not None and split <= start:
            raise ValueError("--split must fall after --start")
        if end is not None and split > end:
            raise ValueError("--split must fall before or on --end")
        return {
            "in_sample": _run_once(args, start=start, end=_day_before(split)),
            "out_of_sample": _run_once(args, start=split, end=end),
        }
    if window:
        if window < 1:
            raise ValueError("--window must be a positive number of days")
        port = CsvMarketDataPort(args.bars)
        symbols = sorted(_instrument_symbols(args))
        trading_days: set[date] = set()
        for entries in _bars_for_engine(port, symbols).values():
            for entry in entries:
                day = entry["date"]
                if isinstance(day, date):
                    trading_days.add(day)
        dates = sorted(trading_days)
        windows = []
        for index in range(0, len(dates), window):
            chunk = dates[index : index + window]
            windows.append(_run_once(args, start=chunk[0], end=chunk[-1]))
        return {"windows": windows}
    return _run_once(args, start=start, end=end)


def _day_before(day: date) -> date:
    from datetime import timedelta

    return day - timedelta(days=1)


def _load_instruments(args: argparse.Namespace) -> dict[str, Instrument]:
    instruments_data = _load_json(args.instruments)
    if not isinstance(instruments_data, list) or not instruments_data:
        raise ValueError("instruments must be a non-empty JSON array")
    instruments: dict[str, Instrument] = {}
    for item in instruments_data:
        if not isinstance(item, Mapping):
            raise ValueError("instrument entries must be objects")
        try:
            instrument = Instrument.from_dict(item)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"invalid instrument entry: {exc}") from exc
        instruments[instrument.symbol] = instrument
    return instruments


def _backtest_config(config_data: Mapping[str, object]) -> BacktestConfig:
    buy_quantity = config_data.get("buy_quantity", 100)
    if not isinstance(buy_quantity, int):
        raise ValueError("buy_quantity must be an integer")
    return BacktestConfig(
        initial_cash=_decimal(config_data.get("initial_cash"), "initial_cash"),
        buy_quantity=buy_quantity,
        commission_rate=_decimal(
            config_data.get("commission_rate", "0.0003"), "commission_rate"
        ),
        stamp_tax_rate=_decimal(
            config_data.get("stamp_tax_rate", "0.0005"), "stamp_tax_rate"
        ),
        slippage_rate=_decimal(
            config_data.get("slippage_rate", "0.001"), "slippage_rate"
        ),
        fill_model=str(config_data.get("fill_model", "slippage")),
    )


def _order_rows(events, engine) -> list[dict[str, object]]:
    orders: list[dict[str, object]] = []
    for event in events:
        if event.order is not None:
            state = engine.order_states.get(event.order.id)
            orders.append(
                {
                    "id": event.order.id,
                    "symbol": event.order.symbol,
                    "side": event.order.side,
                    "quantity": event.order.quantity,
                    "status": state.status,
                    **(
                        {"rejection_code": state.rejection_code}
                        if state.rejection_code
                        else {}
                    ),
                }
            )
    return orders


def _fill_rows(events) -> list[Mapping[str, object]]:
    fills: list[Mapping[str, object]] = []
    for event in events:
        if event.fill is not None:
            fills.append(
                {
                    "order_id": event.fill.order_id,
                    "side": event.fill.side,
                    "price": str(event.fill.price),
                    "quantity": event.fill.quantity,
                    "fee": str(event.fill.fee),
                    "timestamp": event.fill.timestamp.isoformat(),
                }
            )
    return fills


def _run_grid(args: argparse.Namespace) -> dict[str, object]:
    config_data = _load_json(args.config)
    if not isinstance(config_data, Mapping):
        raise ValueError("backtest config must be a JSON object")
    engine = GridBacktestEngine(
        port=CsvMarketDataPort(args.bars),
        instruments=_load_instruments(args),
        config=GridConfig(
            initial_cash=_decimal(config_data.get("initial_cash"), "initial_cash"),
            buy_quantity=_backtest_config(config_data).buy_quantity,
            commission_rate=_decimal(
                config_data.get("commission_rate", "0.0003"), "commission_rate"
            ),
            stamp_tax_rate=_decimal(
                config_data.get("stamp_tax_rate", "0.0005"), "stamp_tax_rate"
            ),
        ),
        rules=TradingRulesPlugin(
            StaticTradingCalendar.for_exchange(str(args.exchange))
        ),
        grid_low=_decimal(args.grid_low, "--grid-low"),
        grid_high=_decimal(args.grid_high, "--grid-high"),
        grid_steps=int(args.grid_steps),
    )
    events = engine.run()
    return {
        "orders": _order_rows(events, engine),
        "fills": _fill_rows(events),
        "summary": _final_metrics(engine, events),
    }


def _run_minute(args: argparse.Namespace) -> dict[str, object]:
    config_data = _load_json(args.config)
    if not isinstance(config_data, Mapping):
        raise ValueError("backtest config must be a JSON object")
    engine = MinuteBacktestEngine(
        port=CsvMarketDataPort(args.bars),
        instruments=_load_instruments(args),
        config=_backtest_config(config_data),
        rules=TradingRulesPlugin(
            StaticTradingCalendar.for_exchange(str(args.exchange))
        ),
        decision_time=str(args.decision),
    )
    events = engine.run()
    return {
        "orders": _order_rows(events, engine),
        "fills": _fill_rows(events),
        "summary": _final_metrics(engine, events),
    }


def _final_metrics(engine, events) -> dict[str, float | int]:
    fills = _fill_rows(events)
    if hasattr(engine, "bars"):
        holding_value = Decimal("0")
        for symbol, instrument_bars in engine.bars.items():
            last_close = Decimal(str(instrument_bars[-1]["close"]))
            position = engine.position(symbol)
            holding_value += last_close * (
                position.settled_qty + position.unsettled_buy_qty
            )
        final_equity = engine.cash + holding_value
    else:
        final_equity = engine.equity()
    metrics = BacktestMetrics(
        initial_cash=engine.config.initial_cash,
        final_equity=final_equity,
        equity_curve=(engine.config.initial_cash, final_equity),
        fills=fills,
    )
    return metrics.summary()


def _instrument_symbols(args: argparse.Namespace) -> list[str]:
    instruments_data = _load_json(args.instruments)
    if not isinstance(instruments_data, list) or not instruments_data:
        raise ValueError("instruments must be a non-empty JSON array")
    symbols = []
    for item in instruments_data:
        if not isinstance(item, Mapping):
            raise ValueError("instrument entries must be objects")
        symbols.append(str(item["symbol"]))
    return symbols


def _benchmark_report(
    engine: MultiInstrumentBacktestEngine, symbol: str
) -> dict[str, float | str]:
    entries = engine.bars.get(symbol)
    if not entries:
        raise ValueError(f"benchmark symbol {symbol} has no bars in range")
    first = Decimal(str(entries[0]["close"]))
    last = Decimal(str(entries[-1]["close"]))
    benchmark_return = float(last / first - 1)
    return {"symbol": symbol, "return": benchmark_return}


def _run_once(
    args: argparse.Namespace, start: date | None, end: date | None
) -> dict[str, object]:
    config_data = _load_json(args.config)
    if not isinstance(config_data, Mapping):
        raise ValueError("backtest config must be a JSON object")
    instruments = _load_instruments(args)
    engine = MultiInstrumentBacktestEngine(
        bars=_bars_for_engine(
            CsvMarketDataPort(args.bars), sorted(instruments), start, end
        ),
        instruments=instruments,
        config=_backtest_config(config_data),
        rules=TradingRulesPlugin(
            StaticTradingCalendar.for_exchange(str(args.exchange))
        ),
    )
    events = engine.run()
    orders = _order_rows(events, engine)
    fills = _fill_rows(events)
    report: dict[str, object] = {
        "orders": orders,
        "fills": fills,
        "summary": _final_metrics(engine, events),
    }
    if args.benchmark:
        benchmark = _benchmark_report(engine, str(args.benchmark))
        report["benchmark"] = benchmark
        summary: dict[str, float | int] = dict(
            engine_summary(report["summary"])
        )
        summary["excess_return"] = summary["total_return"] - float(
            benchmark["return"]
        )
        report["summary"] = summary
    return report


def engine_summary(summary: object) -> dict[str, float | int]:
    if not isinstance(summary, dict):
        raise ValueError("engine summary must be a mapping")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-agent backtest",
        description="Run the multi-instrument backtest engine over a CSV bar file.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a backtest")
    run.add_argument("--bars", type=Path, required=True, help="CSV bar file")
    run.add_argument(
        "--frequency",
        choices=["daily", "minute"],
        default="daily",
        help="bar frequency of the CSV file",
    )
    run.add_argument(
        "--decision",
        default="1431",
        help="minute-frequency decision time HHMM (default 1431)",
    )
    run.add_argument("--grid-low", default="", help="grid strategy: lowest grid level")
    run.add_argument("--grid-high", default="", help="grid strategy: highest grid level")
    run.add_argument(
        "--grid-steps",
        type=int,
        default=0,
        help="grid strategy: number of price bands between low and high",
    )
    run.add_argument(
        "--instruments", type=Path, required=True, help="JSON array of instruments"
    )
    run.add_argument("--config", type=Path, required=True, help="JSON cost config")
    run.add_argument(
        "--exchange", default="SSE", help="calendar exchange (SSE or SZSE)"
    )
    run.add_argument("--start", default="", help="ISO date bound (inclusive)")
    run.add_argument("--end", default="", help="ISO date bound (inclusive)")
    run.add_argument(
        "--split",
        default="",
        help="ISO date splitting in-sample (< split) from out-of-sample (>= split)",
    )
    run.add_argument(
        "--window",
        type=int,
        default=0,
        help="run consecutive rolling windows of this many trading days",
    )
    run.add_argument(
        "--benchmark",
        default="",
        help="symbol from the bar file to compare buy-and-hold returns against",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = _run(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
