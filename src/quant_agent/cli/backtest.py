"""`quant-agent backtest` CLI: run the multi-instrument engine over a CSV
bar file and print an orders/fills/summary JSON report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
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
    port: CsvMarketDataPort, symbols: Sequence[str]
) -> dict[str, list[dict[str, object]]]:
    as_of = datetime.now(timezone.utc)
    bars: dict[str, list[dict[str, object]]] = {}
    for symbol in symbols:
        rows = port.bars(symbol, as_of)
        previous_close: float | None = None
        entries = []
        for row in rows:
            close = row.close
            entries.append(
                {
                    "date": row.timestamp.date(),
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


def _run(args: argparse.Namespace) -> dict[str, object]:
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
        bars=_bars_for_engine(CsvMarketDataPort(args.bars), sorted(instruments)),
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
        ),
        rules=TradingRulesPlugin(
            StaticTradingCalendar.for_exchange(str(args.exchange))
        ),
    )
    events = engine.run()

    orders = []
    fills = []
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
    return {"orders": orders, "fills": fills, "summary": metrics.summary()}


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
