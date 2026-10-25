"""`quant-agent report` CLI: render stored signal artifacts as text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from quant_agent.domain.models import Signal
from quant_agent.strategies.reporting import render_signal_report


def _load_signals(path: Path) -> list[Signal]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("signal file must contain a JSON array")
    try:
        return [Signal.from_dict(item) for item in data]
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid signal entry: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-agent report",
        description="Render stored artifacts as readable text.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="render a signals JSON file")
    show.add_argument("--file", type=Path, required=True, help="signals JSON array")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        signals = _load_signals(args.file)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(render_signal_report(signals, title="Strategy signals"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
