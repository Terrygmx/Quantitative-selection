from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping, Sequence

from quant_agent.agents.paper import (
    ApprovalRecord,
    PaperExecution,
    PaperGateway,
    PaperExecutionConfig,
    SimulatedPaperExecution,
)
from quant_agent.domain.clock import Clock, SystemClock
from quant_agent.domain.models import Instrument
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin


DEFAULT_APPROVALS = Path("state/paper-approvals.json")


def _load_approvals(path: Path) -> list[ApprovalRecord]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read approval file: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("approval file must contain a JSON array")
    records = []
    for item in data:
        if not isinstance(item, Mapping):
            raise ValueError("approval entries must be objects")
        try:
            records.append(
                ApprovalRecord(
                    strategy_id=str(item["strategy_id"]),
                    config_hash=str(item["config_hash"]),
                    approved_by=str(item["approved_by"]),
                )
            )
        except KeyError as exc:
            raise ValueError(f"approval entry missing field: {exc.args[0]}") from exc
    return records


def _save_approvals(path: Path, records: list[ApprovalRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [
                {
                    "strategy_id": record.strategy_id,
                    "config_hash": record.config_hash,
                    "approved_by": record.approved_by,
                }
                for record in records
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _load_config(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read strategy config: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("strategy config must be a JSON object")
    return data


def _decimal(value: object, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal string") from exc


def _execution_from_config(config: Mapping[str, object]) -> PaperExecution:
    section = config.get("execution")
    if not isinstance(section, Mapping):
        raise ValueError("paper execution is not configured")
    instruments: dict[str, Instrument] = {}
    raw_instruments = section.get("instruments")
    if not isinstance(raw_instruments, list) or not raw_instruments:
        raise ValueError("execution instruments are required")
    for item in raw_instruments:
        if not isinstance(item, Mapping):
            raise ValueError("execution instruments must be objects")
        try:
            instruments[str(item["symbol"])] = Instrument(
                symbol=str(item["symbol"]),
                exchange=str(item["exchange"]),
                board=str(item["board"]),
                status=str(item["status"]),
                listing_date=date.fromisoformat(str(item["listing_date"])),
                tick=_decimal(item["tick"], "tick"),
                lot_size=int(item["lot_size"]),
            )
        except KeyError as exc:
            raise ValueError(f"execution instrument missing {exc.args[0]}") from exc
    exchange = str(section.get("exchange", "SSE"))
    try:
        calendar = StaticTradingCalendar.for_exchange(exchange)
    except ValueError as exc:
        raise ValueError(f"unsupported calendar exchange: {exchange}") from exc
    return SimulatedPaperExecution(
        config=PaperExecutionConfig(
            initial_cash=_decimal(
                section.get("initial_cash", "100000.00"), "initial_cash"
            ),
            commission_rate=_decimal(
                section.get("commission_rate", "0.0003"), "commission_rate"
            ),
            stamp_tax_rate=_decimal(
                section.get("stamp_tax_rate", "0.0005"), "stamp_tax_rate"
            ),
            slippage_rate=_decimal(
                section.get("slippage_rate", "0.001"), "slippage_rate"
            ),
            buy_quantity=int(section.get("buy_quantity", 100)),
        ),
        instruments=instruments,
        rules=TradingRulesPlugin(calendar),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-agent paper",
        description="Approve and run approved paper-trading configurations.",
    )
    parser.add_argument(
        "--approvals",
        type=Path,
        default=DEFAULT_APPROVALS,
        help="approval ledger path",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    approve = commands.add_parser("approve", help="approve a strategy configuration")
    approve.add_argument("--strategy", required=True)
    approve.add_argument("--config", type=Path, required=True)
    approve.add_argument("--approved-by", required=True)

    run = commands.add_parser("run", help="run an approved strategy")
    run.add_argument("--strategy", required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--dry-run", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    execution: PaperExecution | None = None,
    clock: Clock = SystemClock(),
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    approvals_path: Path = args.approvals
    try:
        if args.command == "approve":
            config = _load_config(args.config)
            config_hash = str(config.get("config_hash", "")).strip()
            if not config_hash:
                raise ValueError("strategy config requires config_hash")
            records = _load_approvals(approvals_path)
            record = ApprovalRecord(
                strategy_id=args.strategy,
                config_hash=config_hash,
                approved_by=args.approved_by,
            )
            records = [
                item
                for item in records
                if (item.strategy_id, item.config_hash)
                != (record.strategy_id, record.config_hash)
            ]
            records.append(record)
            _save_approvals(approvals_path, records)
            print(
                json.dumps(
                    {
                        "strategy_id": record.strategy_id,
                        "config_hash": record.config_hash,
                        "approved_by": record.approved_by,
                    }
                )
            )
            return 0

        config = _load_config(args.config)
        if execution is None and not args.dry_run:
            execution = _execution_from_config(config)
        gateway = PaperGateway(clock=clock, execution=execution)
        for record in _load_approvals(approvals_path):
            gateway.approve(record)
        result = gateway.run(args.strategy, config, dry_run=args.dry_run)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "strategy_id": args.strategy,
                "config_hash": str(config.get("config_hash", "")),
                "status": result.status,
                "orders": result.orders,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
