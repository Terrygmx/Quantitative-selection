from __future__ import annotations

import html as _html
from typing import Iterable

from quant_agent.domain.models import Signal
from quant_agent.ports.market_data import QualityEvent


DISCLAIMER_ZH = "研究产物，不构成任何投资建议或个股推荐。"


def render_signal_report(
    signals: Iterable[Signal],
    title: str | None = None,
    quality_events: Iterable[QualityEvent] = (),
) -> str:
    items = list(signals)
    quality = [
        event for event in quality_events if event.level in ("warn", "block")
    ]
    if title is None:
        empty_text, heading = "No tail-momentum signals.", "Tail momentum signals"
    else:
        empty_text, heading = "No signals.", title
    if not items and not quality:
        return empty_text
    lines = [heading] if items else [empty_text]
    for signal in items:
        lines.append(
            f"- {signal.symbol} {signal.side} weight={signal.target_weight:.2f} "
            f"confidence={signal.confidence:.2f}"
        )
    if quality:
        warn_count = sum(event.level == "warn" for event in quality)
        block_count = sum(event.level == "block" for event in quality)
        lines.append(f"Quality: warn={warn_count} block={block_count}")
        for event in quality:
            strategy_id = event.strategy_id or "-"
            lines.append(
                f"- {event.level.upper()} {strategy_id} {event.symbol} "
                f"{event.reason_code}: {event.message}"
            )
    return "\n".join(lines)


def render_signal_report_html(
    signals: Iterable[Signal],
    title: str = "Strategy signals",
    quality_events: Iterable[QualityEvent] = (),
) -> str:
    """Self-contained HTML report: no external resources, all dynamic text
    escaped, disclaimer always present (FR-6.3)."""
    items = list(signals)
    quality = [
        event for event in quality_events if event.level in ("warn", "block")
    ]
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
    if quality:
        warn_count = sum(event.level == "warn" for event in quality)
        block_count = sum(event.level == "block" for event in quality)
        quality_rows = []
        for event in quality:
            quality_rows.append(
                "<tr>"
                f"<td>{_html.escape(event.level.upper())}</td>"
                f"<td>{_html.escape(event.strategy_id or '-')}</td>"
                f"<td>{_html.escape(event.symbol)}</td>"
                f"<td>{_html.escape(event.reason_code)}</td>"
                f"<td>{_html.escape(event.message)}</td>"
                "</tr>"
            )
        body += (
            "<h2>Data quality</h2>"
            f"<p>Quality: warn={warn_count} block={block_count}</p>"
            "<table><thead><tr><th>Level</th><th>Strategy</th>"
            "<th>Symbol</th><th>Reason</th><th>Message</th></tr></thead>"
            f"<tbody>{''.join(quality_rows)}</tbody></table>"
        )
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
