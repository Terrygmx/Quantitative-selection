from __future__ import annotations

from typing import Iterable

from quant_agent.domain.models import Signal


def render_signal_report(
    signals: Iterable[Signal], title: str | None = None
) -> str:
    items = list(signals)
    if title is None:
        empty_text, heading = "No tail-momentum signals.", "Tail momentum signals"
    else:
        empty_text, heading = "No signals.", title
    if not items:
        return empty_text
    lines = [heading]
    for signal in items:
        lines.append(
            f"- {signal.symbol} {signal.side} weight={signal.target_weight:.2f} "
            f"confidence={signal.confidence:.2f}"
        )
    return "\n".join(lines)
