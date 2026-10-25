"""WestockMarketDataAdapter: markdown translation locked against the frozen
legacy fixtures (and the real cached responses when present); PIT semantics
follow the MarketDataPort contract."""

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from quant_agent.adapters.market_data import (
    DataUnavailable,
    QualityEventCollector,
)
from quant_agent.adapters.westock import (
    CachedKlineSource,
    WestockCliKlineSource,
    WestockMarketDataAdapter,
    parse_daily_kline_markdown,
)
from tail_momentum_selector import parse_kline_batch


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "legacy"
PROJECT_ROOT = Path(__file__).resolve().parents[4]
CN = ZoneInfo("Asia/Shanghai")
FETCHED_AT = datetime(2026, 9, 15, 14, 30, tzinfo=CN)


def fixture_kline(symbol="sh600176"):
    return (FIXTURES / f"kline_{symbol}.md").read_text(encoding="utf-8")


def fixture_fetch(symbol):
    return fixture_kline(symbol)


def test_parser_output_matches_legacy_on_frozen_fixture():
    text = fixture_kline()

    ours = parse_daily_kline_markdown(text, default_code="sh600176")
    legacy = parse_kline_batch(text, default_code="sh600176")

    assert ours == legacy
    assert len(ours["sh600176"]) >= 25


@pytest.mark.skipif(
    not (PROJECT_ROOT / "cache" / "k_sh600176.md").exists(),
    reason="real westock cache not present in this checkout",
)
def test_parser_output_matches_legacy_on_real_cached_response():
    text = (PROJECT_ROOT / "cache" / "k_sh600176.md").read_text(encoding="utf-8")

    ours = parse_daily_kline_markdown(text, default_code="sh600176")
    legacy = parse_kline_batch(text, default_code="sh600176")

    assert ours == legacy


def test_adapter_serves_bars_only_after_the_fetch_moment():
    port = WestockMarketDataAdapter(fixture_fetch, available_at=FETCHED_AT)

    with pytest.raises(DataUnavailable):
        port.bars("sh600176", FETCHED_AT - timedelta(minutes=1))


def test_adapter_stamps_daily_bars_at_cn_close_with_fetch_availability():
    port = WestockMarketDataAdapter(fixture_fetch, available_at=FETCHED_AT)

    bars = port.bars("sh600176", FETCHED_AT)

    assert len(bars) >= 25
    # The in-flight current-day row (fetched at 14:30) only becomes visible
    # once its close has actually happened; history is visible immediately.
    assert bars[-1].timestamp == datetime(2026, 9, 14, 15, 0, tzinfo=CN)
    assert all(bar.available_at == FETCHED_AT for bar in bars)
    assert [bar.timestamp for bar in bars] == sorted(bar.timestamp for bar in bars)


def test_adapter_reveals_the_close_bar_only_after_the_close():
    port = WestockMarketDataAdapter(fixture_fetch, available_at=FETCHED_AT)

    after_close = port.bars("sh600176", datetime(2026, 9, 15, 15, 0, tzinfo=CN))

    assert after_close[-1].timestamp == datetime(2026, 9, 15, 15, 0, tzinfo=CN)
    assert after_close[-1].close == pytest.approx(47.09)
    assert after_close[-1].amount == pytest.approx(0.0)  # masked vendor value
    assert after_close[-1].available_at == after_close[-1].timestamp


def test_adapter_emits_block_quality_event_when_unavailable():
    events = QualityEventCollector()
    port = WestockMarketDataAdapter(fixture_fetch, available_at=FETCHED_AT, quality_events=events)

    with pytest.raises(DataUnavailable):
        port.bars("sh600176", FETCHED_AT - timedelta(minutes=1))

    assert [event.level for event in events.events] == ["block"]
    assert events.events[0].reason_code == "MISSING_REQUIRED_BAR"


def test_cached_kline_source_reads_legacy_tag_scheme(tmp_path):
    (tmp_path / "k_sh600519.md").write_text(fixture_kline(), encoding="utf-8")
    source = CachedKlineSource(tmp_path)

    assert source("sh600519") == fixture_kline()

    with pytest.raises(FileNotFoundError):
        source("sh600999")


def test_cli_kline_source_composes_the_legacy_command(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        result = type("Result", (), {})()
        result.returncode = 0
        result.stdout = fixture_kline().encode("utf-8")
        result.stderr = b""
        return result

    monkeypatch.setattr("quant_agent.adapters.westock.subprocess.run", fake_run)
    source = WestockCliKlineSource(cli="westock")

    text = source("sh600176")

    assert captured["cmd"] == [
        "westock", "kline", "sh600176", "--period", "day",
        "--limit", "60", "--fq", "qfq",
    ]
    assert text == fixture_kline()
