"""Role tool executors: each design-section-8 role tool actually does its
job against injected ports/directories instead of echoing arguments."""

import json
from datetime import datetime, timezone


from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.agents.role_tools import RoleToolbox


def port():
    bars = [
        Bar(
            instrument="sh600519",
            timestamp=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
            open=45.0,
            high=46.0,
            low=44.5,
            close=45.8,
            volume=1000.0,
            available_at=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        )
    ]
    return InMemoryMarketDataPort(bars)


def toolbox(tmp_path, data_port=None):
    return RoleToolbox(
        data_port=data_port or port(),
        drafts_dir=tmp_path / "drafts",
        quality_events_path=tmp_path / "quality.jsonl",
    )


def test_read_approved_dataset_returns_pit_bars(tmp_path):
    box = toolbox(tmp_path)

    result = box.read_approved_dataset(
        symbol="sh600519",
        as_of=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
    )

    assert result["symbol"] == "sh600519"
    assert result["bars"][0]["close"] == 45.8


def test_read_approved_dataset_reports_unavailable_instead_of_raising(tmp_path):
    box = toolbox(tmp_path)

    result = box.read_approved_dataset(
        symbol="sh000001",
        as_of=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
    )

    assert result["error"] == "DATA_UNAVAILABLE"
    assert result["reason_code"] == "MISSING_REQUIRED_BAR"


def test_draft_experiment_writes_a_json_draft(tmp_path):
    box = toolbox(tmp_path)

    path = box.draft_experiment(
        strategy_id="trend_breakout",
        config={"universe": ["sh600519"], "breakout_window": 10},
        rationale="faster breakouts",
    )

    draft = json.loads(path.read_text(encoding="utf-8"))
    assert draft["strategy_id"] == "trend_breakout"
    assert draft["config"]["breakout_window"] == 10
    assert draft["status"] == "draft"  # never production
    assert path.parent == tmp_path / "drafts"


def test_create_quality_event_appends_jsonl(tmp_path):
    box = toolbox(tmp_path)

    path = box.create_quality_event(
        reason_code="STALE_BAR",
        symbol="sh600519",
        message="last bar older than one session",
    )

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    event = json.loads(lines[-1])
    assert event["reason_code"] == "STALE_BAR"
    assert event["symbol"] == "sh600519"


def test_explain_signal_combines_bars_and_research_note(tmp_path):
    box = toolbox(tmp_path)

    note = box.explain_signal(
        symbol="sh600519",
        as_of=datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc),
        thesis="breakout above 20d high",
    )

    assert note["symbol"] == "sh600519"
    assert note["last_close"] == 45.8
    assert note["thesis"] == "breakout above 20d high"
    assert note["disclaimer"]  # research output is never advice


def test_explain_rejection_reads_the_rules_reason(tmp_path):
    box = toolbox(tmp_path)

    note = box.explain_rejection(
        reason_code="T1_UNSETTLED", context={"symbol": "sh600519"}
    )

    assert "T+1" in note["explanation"] or "settle" in note["explanation"].lower()
    assert note["reason_code"] == "T1_UNSETTLED"
