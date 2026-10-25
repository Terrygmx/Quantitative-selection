"""`quant-agent agent` CLI: review gateway audit trails (FR-6)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


def _load_events(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    events = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"audit line {number} is not JSON: {exc}") from exc
        if not isinstance(item, dict) or "agent_id" not in item or "status" not in item:
            raise ValueError(f"audit line {number} lacks agent_id/status")
        events.append(item)
    return events


def _summarize(events: list[dict[str, object]]) -> dict[str, object]:
    by_status: dict[str, int] = {}
    by_agent: dict[str, dict[str, int]] = {}
    denials = []
    for item in events:
        status = str(item["status"])
        agent_id = str(item["agent_id"])
        by_status[status] = by_status.get(status, 0) + 1
        agent_counts = by_agent.setdefault(agent_id, {})
        agent_counts[status] = agent_counts.get(status, 0) + 1
        if status != "allowed":
            denials.append(
                {
                    "agent_id": agent_id,
                    "tool": str(item.get("tool", "")),
                    "reason_code": item.get("reason_code"),
                    "occurred_at": item.get("occurred_at"),
                }
            )
    return {
        "total": len(events),
        "by_status": by_status,
        "by_agent": by_agent,
        "denials": denials,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quant-agent agent",
        description="Review agent gateway activity.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    review = commands.add_parser("review", help="summarize an audit JSONL file")
    review.add_argument("--audit", type=Path, required=True, help="audit JSONL path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        events = _load_events(args.audit)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(_summarize(events), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
