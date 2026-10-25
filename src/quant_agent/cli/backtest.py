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

    engine = MultiInstrumentBacktestEngine(
        bars=_bars_for_engine(
            CsvMarketDataPort(args.bars), sorted(instruments), start, end
        ),
        instruments=instruments,
        config=BacktestConfig(
            initial_cash=_decimal(config_data.get("initial_cash"), "initial_cash"),
            buy_quantity=int(config_data.get("buy_quantity", 100)),
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
        ),
        rules=TradingRulesPlugin(
            StaticTradingCalendar.for_exchange(str(args.exchange))
        ),
    )
    events = engine.run()

    orders: list[dict[str, object]] = []
    fills: list[Mapping[str, object]] = []
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

    holding_value = Decimal("0")
    for symbol, instrument_bars in engine.bars.items():
        last_close = Decimal(str(instrument_bars[-1]["close"]))
        position = engine.position(symbol)
        holding_value += last_close * (
            position.settled_qty + position.unsettled_buy_qty
        )
    final_equity = engine.cash + holding_value
    metrics = BacktestMetrics(
        initial_cash=engine.config.initial_cash,
        final_equity=final_equity,
        equity_curve=(engine.config.initial_cash, final_equity),
        fills=fills,
    )
    report: dict[str, object] = {
        "orders": orders,
        "fills": fills,
        "summary": metrics.summary(),
    }
    if args.benchmark:
        benchmark = _benchmark_report(engine, str(args.benchmark))
        report["benchmark"] = benchmark
        summary: dict[str, float | int] = dict(metrics.summary())
        summary["excess_return"] = summary["total_return"] - float(
            benchmark["return"]
        )
        report["summary"] = summary
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-agent backtest",
        description="Run the multi-instrument backtest engine over a CSV bar file.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a backtest")
    run.add_argument("--bars", type=Path, required=True, help="CSV bar file")
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
