"""Westock CLI adapter: a MarketDataPort over westock daily-kline markdown.

The markdown translation is owned here (ported from the legacy script) and
locked against the frozen legacy fixtures by tests. Data sources are
injected so the translation is testable offline: `CachedKlineSource` reads
the legacy `k_{symbol}.md` cache scheme, `WestockCliKlineSource` shells out
to the westock binary (network)."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from quant_agent.adapters.market_data import (
    Bar,
    DataUnavailable,
    QualityEvent,
    QualityEventCollector,
)


CN_MARKET_TZ = ZoneInfo("Asia/Shanghai")
_DAILY_CLOSE = time(15, 0)


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.replace(",", "").replace("%", "").strip()
    if value in ("", "-", "None", "null"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_md_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """[(headers, rows)] over consecutive markdown table lines."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    header: list[str] | None = None
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            if header is not None:
                tables.append((header, rows))
                header, rows = None, []
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells if cell != ""):
            continue
        if header is None:
            header = cells
        else:
            rows.append(cells)
    if header is not None:
        tables.append((header, rows))
    return tables


def parse_daily_kline_markdown(
    text: str, default_code: str | None = None
) -> dict[str, list[dict[str, object]]]:
    """code -> ascending daily rows {date, open, high, low, close, volume,
    amount}; mirrors the legacy parse_kline_batch semantics."""
    parsed: dict[str, list[dict[str, object]]] = {}
    for headers, rows in _parse_md_tables(text):
        if "date" not in headers or "last" not in headers:
            continue
        has_symbol = "symbol" in headers
        try:
            di = headers.index("date")
            oi = headers.index("open")
            li = headers.index("low")
            hi = headers.index("high")
            ci = headers.index("last")
            vi = headers.index("volume")
            ai = headers.index("amount")
            si = headers.index("symbol") if has_symbol else None
        except ValueError:
            continue
        for row in rows:
            if len(row) <= max(di, oi, li, hi, ci, vi, ai):
                continue
            code = row[si] if has_symbol and si is not None else default_code
            record: dict[str, object] = {
                "date": row[di],
                "open": _to_float(row[oi]),
                "high": _to_float(row[hi]),
                "low": _to_float(row[li]),
                "close": _to_float(row[ci]),
                "volume": _to_float(row[vi]),
                "amount": _to_float(row[ai]),
            }
            if record["close"] is None or record["open"] is None:
                continue
            if code is None:
                continue
            parsed.setdefault(code, []).append(record)
    for code in parsed:
        parsed[code].sort(key=lambda item: str(item["date"]))
    return parsed


class CachedKlineSource:
    """Offline source over the legacy cache tag scheme `k_{symbol}.md`."""

    def __init__(self, cache_dir: str | Path):
        self.cache_dir = Path(cache_dir)

    def __call__(self, symbol: str) -> str:
        path = self.cache_dir / f"k_{symbol}.md"
        if not path.exists():
            raise FileNotFoundError(f"no cached kline for {symbol}: {path}")
        return path.read_text(encoding="utf-8")


class WestockCliKlineSource:
    """Online source shelling out to the westock binary with the legacy
    command line; output is read as bytes and decoded UTF-8 explicitly."""

    def __init__(self, cli: str = "westock", limit: int = 60, timeout: int = 120):
        self.cli = cli
        self.limit = limit
        self.timeout = timeout

    def __call__(self, symbol: str) -> str:
        cmd = [
            self.cli, "kline", symbol,
            "--period", "day", "--limit", str(self.limit), "--fq", "qfq",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"westock kline timed out for {symbol}") from exc
        text = (result.stdout or b"").decode("utf-8", errors="replace")
        if result.returncode != 0:
            error = (result.stderr or b"").decode("utf-8", errors="replace")
            raise RuntimeError(
                f"westock kline failed for {symbol} ({result.returncode}): "
                f"{error[:300]}"
            )
        return text


class WestockMarketDataAdapter:
    """MarketDataPort over westock daily-kline markdown. Every bar becomes
    visible only at the dataset's fetch moment (`available_at`), so an
    as_of before the fetch fails closed instead of leaking history the
    vendor had not returned yet."""

    DataUnavailable = DataUnavailable

    def __init__(
        self,
        kline_source: Callable[[str], str],
        available_at: datetime,
        quality_events: QualityEventCollector | None = None,
    ):
        self._kline_source = kline_source
        self._available_at = available_at
        self.quality_events = quality_events
        self._bars_by_symbol: dict[str, list[Bar]] = {}

    def bars(self, instrument: str, as_of: datetime) -> list[Bar]:
        visible = [
            bar
            for bar in self._daily_bars(instrument)
            if bar.timestamp <= as_of and bar.available_at <= as_of
        ]
        if not visible:
            event = QualityEvent(
                level="block",
                reason_code="MISSING_REQUIRED_BAR",
                symbol=instrument,
                as_of=as_of,
                message=(
                    f"No westock kline bar available for {instrument} "
                    f"as of {as_of.isoformat()} (dataset fetched "
                    f"{self._available_at.isoformat()})"
                ),
            )
            if self.quality_events is not None:
                self.quality_events.record(event)
            raise DataUnavailable(event)
        return visible

    def _daily_bars(self, symbol: str) -> list[Bar]:
        cached = self._bars_by_symbol.get(symbol)
        if cached is not None:
            return cached
        markdown = self._kline_source(symbol)
        rows = parse_daily_kline_markdown(markdown, default_code=symbol).get(
            symbol, []
        )
        bars: list[Bar] = []
        for row in rows:
            timestamp = datetime.combine(
                _bar_date(str(row["date"])), _DAILY_CLOSE, tzinfo=CN_MARKET_TZ
            )
            # A daily close bar only becomes genuinely available at its
            # close; an intraday fetch's in-flight current-day row stays
            # invisible until then (the legacy flow overrides it with the
            # snapshot minute price instead).
            available_at = max(self._available_at, timestamp)
            bars.append(
                Bar(
                    instrument=symbol,
                    timestamp=timestamp,
                    open=_require_float(row["open"]),
                    high=_require_float(row["high"]),
                    low=_require_float(row["low"]),
                    close=_require_float(row["close"]),
                    volume=_require_float(row["volume"] or 0.0),
                    available_at=available_at,
                    amount=_require_float(row["amount"] or 0.0),
                )
            )
        bars.sort(key=lambda bar: bar.timestamp)
        self._bars_by_symbol[symbol] = bars
        return bars


def _bar_date(value: str) -> date:
    return date.fromisoformat(value)


def _require_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"kline row has a non-numeric value: {value!r}")
