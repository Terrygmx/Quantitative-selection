"""Normalized layer (DETAILED_DESIGN section 5.2): canonical instrument
codes, Asia/Shanghai timestamps, and adjustment-mode consistency. Raw
vendor responses are never mutated; normalization produces new Bars with
preserved timestamps and an explicit ingested_at availability stamp."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from quant_agent.ports.market_data import Bar


CN_MARKET_TZ = ZoneInfo("Asia/Shanghai")
ADJUSTMENT_MODES = frozenset({"qfq", "hfq", "raw"})


class NormalizationError(ValueError):
    """Raised when vendor input cannot be normalized without guessing."""


def canonical_symbol(code: str, exchange: str | None) -> str:
    """Map vendor codes to the platform's sh/sz prefix convention."""
    code = code.strip().lower()
    if code[:2] in ("sh", "sz"):
        return code
    if exchange is None:
        # Only 6xxxxx (SH stocks) and 3xxxxx (ChiNext) are unambiguous:
        # 0xxxxx collides between SZ stocks and SH indices (000001 is both
        # Ping An Bank and the Shanghai Composite), so it needs exchange.
        if code[:1] == "6":
            return f"sh{code}"
        if code[:1] == "3":
            return f"sz{code}"
        raise NormalizationError(
            f"ambiguous instrument code {code!r}: exchange is required"
        )
    prefix = {"SSE": "sh", "SZSE": "sz"}.get(exchange)
    if prefix is None:
        raise NormalizationError(f"unsupported exchange: {exchange}")
    return f"{prefix}{code}"


def normalize_bars(
    bars: Iterable[Bar],
    *,
    exchange: str | None = None,
    ingested_at: datetime | None = None,
) -> list[Bar]:
    items: Sequence[Bar] = list(bars)
    modes = {getattr(bar, "adjustment", "raw") for bar in items}
    unknown = modes - ADJUSTMENT_MODES
    if unknown:
        raise NormalizationError(f"unknown adjustment mode(s): {sorted(unknown)}")
    if len(modes) > 1:
        raise NormalizationError(
            "adjustment modes must not be mixed inside one dataset: "
            f"{sorted(modes)}; normalize per mode and store separately"
        )
    stamped = ingested_at or (
        max((bar.available_at for bar in items), default=datetime.now(timezone.utc))
    )
    out: list[Bar] = []
    for bar in items:
        out.append(
            Bar(
                instrument=canonical_symbol(bar.instrument, exchange),
                timestamp=bar.timestamp.astimezone(CN_MARKET_TZ),
                open=bar.open,
                high=bar.high,
                low=bar.low,
                close=bar.close,
                volume=bar.volume,
                available_at=stamped,
                amount=bar.amount,
            )
        )
    return out
