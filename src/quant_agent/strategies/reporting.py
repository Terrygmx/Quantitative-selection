from __future__ import annotations

from typing import Iterable

from quant_agent.domain.models import Signal


def render_signal_report(signals: Iterable[Signal]) -> str:
    items = list(signals)
    if not items:
        return "No tail-momentum signals."
    lines = ["Tail momentum signals"]
    for signal in items:
        lines.append(
            f"- {signal.symbol} {signal.side} weight={signal.target_weight:.2f} "
            f"confidence={signal.confidence:.2f}"
        )
    return "\n".join(lines)
