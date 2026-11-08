from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

from quant_agent.adapters.market_data import InMemoryMarketDataPort
from quant_agent.agents.paper import (
    ApprovalRecord,
    PaperExecution,
    PaperExecutionConfig,
    PaperGateway,
    SimulatedPaperExecution,
)
from quant_agent.application.paper_strategy import (
    CN_MARKET_TZ,
    StrategyPaperOrchestrator,
    validate_paper_config,
)
from quant_agent.application.quality import quality_event_dict
from quant_agent.application.identity import parse_decimal_string
from quant_agent.application.runs import RunManifestFactory
from quant_agent.domain.models import Instrument
from quant_agent.ports.clock import Clock, FixedClock, SystemClock
from quant_agent.ports.market_data import Bar
from quant_agent.ports.market_data import QualityEventCollector
from quant_agent.rules.calendar import StaticTradingCalendar
from quant_agent.rules.trading import TradingRulesPlugin
from quant_agent.strategies.factory import build_strategy_registry
from quant_agent.strategies.registry import StrategyRegistry

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
                    strategy_version=str(item["strategy_version"]),
                    config_hash=str(item["config_hash"]),
                    data_snapshot=str(item["data_snapshot"]),
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
                    "strategy_version": record.strategy_version,
                    "config_hash": record.config_hash,
                    "data_snapshot": record.data_snapshot,
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


def _decimal(
    value: object,
    field: str,
    *,
    minimum: Decimal,
    allow_zero: bool,
) -> Decimal:
    return parse_decimal_string(
        value,
        field,
        minimum=minimum,
        allow_zero=allow_zero,
    )


def _instruments_from_config(
    config: Mapping[str, object],
) -> dict[str, Instrument]:
    instruments: dict[str, Instrument] = {}
    raw_instruments = config.get("instruments")
    if not isinstance(raw_instruments, list) or not raw_instruments:
        raise ValueError("paper instruments are required")
    for item in raw_instruments:
        if not isinstance(item, Mapping):
            raise ValueError("paper instruments must be objects")
        try:
            tick = _decimal(
                item["tick"],
                "tick",
                minimum=Decimal("0"),
                allow_zero=False,
            )
            lot_size = item["lot_size"]
            if (
                isinstance(lot_size, bool)
                or not isinstance(lot_size, int)
                or lot_size <= 0
            ):
                raise ValueError("lot_size must be a positive integer")
            instruments[str(item["symbol"])] = Instrument(
                symbol=str(item["symbol"]),
                exchange=str(item["exchange"]),
                board=str(item["board"]),
                status=str(item["status"]),
                listing_date=date.fromisoformat(str(item["listing_date"])),
                tick=tick,
                lot_size=lot_size,
            )
        except KeyError as exc:
            raise ValueError(
                f"execution instrument missing {exc.args[0]}"
            ) from exc
    return instruments


def _execution_from_config(config: Mapping[str, object]) -> PaperExecution:
    section = config.get("execution")
    if not isinstance(section, Mapping):
        raise ValueError("paper execution is not configured")
    instruments = _instruments_from_config(config)
    exchange = str(section.get("exchange", "SSE"))
    try:
        calendar = StaticTradingCalendar.for_exchange(exchange)
    except ValueError as exc:
        raise ValueError(f"unsupported calendar exchange: {exchange}") from exc
    return SimulatedPaperExecution(
        config=PaperExecutionConfig(
            initial_cash=_decimal(
                section.get("initial_cash", "100000.00"),
                "initial_cash",
                minimum=Decimal("0"),
                allow_zero=False,
            ),
            commission_rate=_decimal(
                section.get("commission_rate", "0.0003"),
                "commission_rate",
                minimum=Decimal("0"),
                allow_zero=True,
            ),
            stamp_tax_rate=_decimal(
                section.get("stamp_tax_rate", "0.0005"),
                "stamp_tax_rate",
                minimum=Decimal("0"),
                allow_zero=True,
            ),
            slippage_rate=_decimal(
                section.get("slippage_rate", "0.001"),
                "slippage_rate",
                minimum=Decimal("0"),
                allow_zero=True,
            ),
            buy_quantity=_positive_int(
                section.get("buy_quantity", 100), "buy_quantity"
            ),
            fill_model=str(section.get("fill_model", "slippage")),
            board_queue_policy=str(
                section.get("board_queue_policy", "reject")
            ),
        ),
        instruments=instruments,
        rules=TradingRulesPlugin(calendar),
    )


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _data_port_from_config(
    config: Mapping[str, object],
    quality_events: QualityEventCollector,
) -> InMemoryMarketDataPort:
    data = config.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("paper config requires a data object")
    raw_bars = data.get("bars")
    if not isinstance(raw_bars, list) or not raw_bars:
        raise ValueError("paper config requires non-empty data.bars")
    bars: list[Bar] = []
    for index, item in enumerate(raw_bars):
        if not isinstance(item, Mapping):
            raise ValueError(f"data.bars[{index}] must be an object")
        try:
            timestamp = datetime.fromisoformat(str(item["timestamp"]))
            available_at = datetime.fromisoformat(str(item["available_at"]))
            if timestamp.tzinfo is None or available_at.tzinfo is None:
                raise ValueError("timestamps must include a timezone")
            bars.append(
                Bar(
                    instrument=str(item["instrument"]),
                    timestamp=timestamp,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item["volume"]),
                    amount=float(item.get("amount", 0)),
                    available_at=available_at,
                    adjustment=str(item.get("adjustment", "raw")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"data.bars[{index}] is invalid: {exc}") from exc
    return InMemoryMarketDataPort(
        bars,
        quality_events=quality_events,
    )


def _registry_from_config(
    strategy_id: str,
    config: Mapping[str, object],
) -> StrategyRegistry:
    strategy_config = config.get("strategy_config")
    if not isinstance(strategy_config, Mapping):
        raise ValueError("paper config requires a strategy_config object")
    return build_strategy_registry(
        (strategy_id,),
        {strategy_id: dict(strategy_config)},
    )


def _as_of(value: str, clock: Clock) -> datetime:
    try:
        result = (
            datetime.fromisoformat(value)
            if value
            else clock.now()
        )
    except ValueError as exc:
        raise ValueError("--as-of must be a timezone-aware ISO-8601 datetime") from exc
    if result.tzinfo is None:
        raise ValueError("--as-of must be a timezone-aware ISO-8601 datetime")
    return result.astimezone(CN_MARKET_TZ)


def _orchestrator(
    config: Mapping[str, object],
    registry: StrategyRegistry,
    *,
    exchange: str,
    as_of: datetime,
) -> StrategyPaperOrchestrator:
    try:
        calendar = StaticTradingCalendar.for_exchange(exchange)
    except ValueError as exc:
        raise ValueError(
            f"unsupported calendar exchange: {exchange}"
        ) from exc
    raw_industries = config.get("industry_by_symbol", {})
    raw_previous = config.get("previous_close_by_symbol", {})
    if not isinstance(raw_industries, Mapping):
        raise ValueError("industry_by_symbol must be an object")
    if not isinstance(raw_previous, Mapping):
        raise ValueError("previous_close_by_symbol must be an object")
    quality_events = QualityEventCollector()
    return StrategyPaperOrchestrator(
        port=_data_port_from_config(config, quality_events),
        instruments=_instruments_from_config(config),
        registry=registry,
        rules=TradingRulesPlugin(calendar),
        industry_by_symbol={
            str(symbol): str(industry)
            for symbol, industry in raw_industries.items()
        },
        previous_close_by_symbol={
            str(symbol): value for symbol, value in raw_previous.items()
        },
        manifest_factory=RunManifestFactory(
            clock=FixedClock(as_of),
        ),
        quality_events=quality_events,
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
    approve.add_argument("--as-of", required=True)

    run = commands.add_parser("run", help="run an approved strategy")
    run.add_argument("--strategy", required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--as-of", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    execution: PaperExecution | None = None,
    registry: StrategyRegistry | None = None,
    clock: Clock = SystemClock(),
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    approvals_path: Path = args.approvals
    try:
        if args.command == "approve":
            config = _load_config(args.config)
            validate_paper_config(config)
            strategy_registry = registry or _registry_from_config(
                args.strategy, config
            )
            as_of = _as_of(args.as_of, clock)
            execution_section = config.get("execution")
            exchange = (
                str(execution_section.get("exchange", "SSE"))
                if isinstance(execution_section, Mapping)
                else "SSE"
            )
            orchestrator = _orchestrator(
                config,
                strategy_registry,
                exchange=exchange,
                as_of=as_of,
            )
            identity = orchestrator.identity(
                args.strategy,
                config,
                as_of,
            )
            plan = orchestrator.evaluate(
                args.strategy,
                config,
                as_of,
            )
            records = _load_approvals(approvals_path)
            record = ApprovalRecord(
                strategy_id=args.strategy,
                strategy_version=identity.strategy_version,
                config_hash=identity.config_hash,
                data_snapshot=plan.data_snapshot,
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
                        "strategy_version": record.strategy_version,
                        "config_hash": record.config_hash,
                        "data_snapshot": record.data_snapshot,
                        "approved_by": record.approved_by,
                    }
                )
            )
            return 0

        config = _load_config(args.config)
        validate_paper_config(config)
        strategy_registry = registry or _registry_from_config(
            args.strategy, config
        )
        as_of = _as_of(args.as_of, clock)
        if execution is None and not args.dry_run:
            execution = _execution_from_config(config)
        execution_section = config.get("execution")
        exchange = (
            str(execution_section.get("exchange", "SSE"))
            if isinstance(execution_section, Mapping)
            else "SSE"
        )
        orchestrator = _orchestrator(
            config,
            strategy_registry,
            exchange=exchange,
            as_of=as_of,
        )
        gateway = PaperGateway(
            clock=clock,
            execution=execution,
            strategy_evaluator=orchestrator,
        )
        for record in _load_approvals(approvals_path):
            gateway.approve(record)
        result = gateway.run(
            args.strategy,
            config,
            dry_run=args.dry_run,
            run_at=as_of,
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "strategy_id": args.strategy,
                "strategy_version": result.strategy_version,
                "config_hash": result.config_hash,
                "data_snapshot": result.data_snapshot,
                "read_snapshot": result.read_snapshot,
                "status": result.status,
                "manifest": result.manifest.to_dict(),
                "signals": [dict(signal) for signal in result.signals],
                "decisions": [
                    asdict(decision) for decision in result.decisions
                ],
                "targets": [asdict(target) for target in result.targets],
                "quality_events": [
                    quality_event_dict(event)
                    for event in result.quality_events
                ],
                "quality_summary": result.quality_summary.to_dict(),
                "orders": result.orders,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
