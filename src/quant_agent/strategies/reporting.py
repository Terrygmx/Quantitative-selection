from __future__ import annotations

import html as _html
from typing import Iterable

from quant_agent.domain.models import Signal


DISCLAIMER_ZH = "研究产物，不构成任何投资建议或个股推荐。"


def render_signal_report(signals: Iterable[Signal], title: str | None = None) -> str:
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


def render_signal_report_html(
    signals: Iterable[Signal], title: str = "Strategy signals"
) -> str:
    """Self-contained HTML report: no external resources, all dynamic text
    escaped, disclaimer always present (FR-6.3)."""
    items = list(signals)
    title_escaped = _html.escape(title)
    if items:
        rows = []
        for signal in items:
            rows.append(
                "<tr>"
                f"<td>{_html.escape(signal.symbol)}</td>"
                f"<td>{_html.escape(signal.strategy_id)}</td>"
                f"<td>{_html.escape(signal.side)}</td>"
                f"<td>{signal.target_weight:.2f}</td>"
                f"<td>{signal.confidence:.2f}</td>"
                "</tr>"
            )
        body = (
            "<table>"
            "<thead><tr><th>Symbol</th><th>Strategy</th><th>Side</th>"
            "<th>Weight</th><th>Confidence</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
    else:
        body = "<p>No signals.</p>"
    return (
        '<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">'
        f"<title>{title_escaped}</title>"
        "<style>body{font-family:sans-serif;margin:2rem}"
        "table{border-collapse:collapse}td,th{border:1px solid #ccc;"
        "padding:.4rem .8rem}</style></head><body>"
        f"<h1>{title_escaped}</h1>{body}"
        f'<p class="disclaimer">{_html.escape(DISCLAIMER_ZH)}</p>'
        "</body></html>"
    )
