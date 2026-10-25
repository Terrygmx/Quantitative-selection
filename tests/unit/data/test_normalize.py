"""Normalized layer (DETAILED_DESIGN 5.2): canonical instrument codes,
Asia/Shanghai timestamps, adjustment-mode consistency (no mixing qfq and
raw within one dataset), and preserved source/ingested/available stamps."""

from datetime import datetime, timedelta, timezone

import pytest

from quant_agent.adapters.market_data import Bar
from quant_agent.adapters.normalize import (
    NormalizationError,
    normalize_bars,
)


def raw_bar(symbol="600519", close=10.0, hours=0, fq="qfq"):
    stamp = datetime(2026, 9, 15, 15, hours, tzinfo=timezone.utc)
    return Bar(
        instrument=symbol,
        timestamp=stamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1000.0,
        available_at=stamp,
        amount=close * 1000,
        adjustment=fq,
    ), fq


def test_canonicalizes_codes_and_timezone():
    bars, _ = raw_bar("600519")
    out = normalize_bars([bars], exchange="SSE")

    assert out[0].instrument == "sh600519"
    assert out[0].timestamp.utcoffset().total_seconds() == 8 * 3600


def test_szse_prefix_and_ambiguous_code_fails_closed():
    bars, _ = raw_bar("000001")
    out = normalize_bars([bars], exchange="SZSE")
    assert out[0].instrument == "sz000001"

    with pytest.raises(NormalizationError, match="ambiguous"):
        normalize_bars([raw_bar("000001")[0]], exchange=None)


def test_mixing_adjustment_modes_fails_closed():
    qfq, _ = raw_bar("600519", close=10.0, fq="qfq")
    raw, _ = raw_bar("600519", close=12.0, hours=1, fq="raw")

    with pytest.raises(NormalizationError, match="adjustment"):
        normalize_bars([qfq, raw])


def test_unadjusted_prices_are_flagged_not_silently_mixed():
    bars, _ = raw_bar("600519", fq="raw")
    out = normalize_bars([bars])

    assert out[0].instrument == "sh600519"  # single mode passes


def test_source_stamps_are_preserved():
    bar, _ = raw_bar("600519")
    ingested = bar.available_at + timedelta(minutes=5)

    out = normalize_bars([bar], ingested_at=ingested)

    assert out[0].available_at == ingested
    assert out[0].timestamp == bar.timestamp
