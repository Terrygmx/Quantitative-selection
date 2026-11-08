"""`quant-agent report` CLI: render stored signal artifacts as text."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Sequence

from quant_agent.domain.models import Signal
from quant_agent.ports.market_data import QualityEvent
from quant_agent.strategies.reporting import render_signal_report


def _quality_string(item: dict[str, object], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _load_report(path: Path) -> tuple[list[Signal], list[QualityEvent]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    quality_rows: list[object] = []
    if isinstance(data, dict):
        signal_rows = data.get("signals")
        raw_quality = data.get("quality_events", [])
        if not isinstance(raw_quality, list):
            raise ValueError("quality_events must be a JSON array")
        quality_rows = raw_quality
    else:
        signal_rows = data
    if not isinstance(signal_rows, list):
        raise ValueError("signal file must contain a JSON array or report object")
    try:
        signals = [Signal.from_dict(item) for item in signal_rows]
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid signal entry: {exc}") from exc
    quality_events = []
    for item in quality_rows:
        if not isinstance(item, dict):
            raise ValueError("invalid quality event: entry must be an object")
        unknown = set(item) - {
            "level",
            "reason_code",
            "symbol",
            "as_of",
            "message",
            "strategy_id",
        }
        if unknown:
            raise ValueError(
                "invalid quality event: unknown field(s) "
                + ", ".join(sorted(unknown))
            )
        try:
            strategy_id = (
                _quality_string(item, "strategy_id")
                if "strategy_id" in item
                else None
            )
            quality_events.append(
                QualityEvent(
                    level=_quality_string(item, "level"),
                    reason_code=_quality_string(item, "reason_code"),
                    symbol=_quality_string(item, "symbol"),
                    as_of=datetime.fromisoformat(
                        _quality_string(item, "as_of")
                    ),
                    message=_quality_string(item, "message"),
                    strategy_id=strategy_id,
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid quality event: {exc}") from exc
    return signals, quality_events


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-agent report",
        description="Render stored artifacts as readable text.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="render a signals JSON file")
    show.add_argument(
        "--file",
        type=Path,
        required=True,
        help="signals JSON array or report object with quality_events",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        signals, quality_events = _load_report(args.file)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        render_signal_report(
            signals,
            title="Strategy signals",
            quality_events=quality_events,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
