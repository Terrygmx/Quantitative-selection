"""`quant-agent report show`: render a signals JSON file as text."""

import json

import pytest

from quant_agent.cli.report import main


def signal_dict(symbol="sh600519"):
    return {
        "strategy_id": "trend_breakout",
        "version": "0.1.0",
        "symbol": symbol,
        "side": "long",
        "target_weight": 1.0,
        "confidence": 1.0,
        "valid_from": "2026-09-15T15:05:00+00:00",
        "valid_to": "2026-10-05T15:05:00+00:00",
        "evidence": {"prior_high": 10.95},
    }


def test_report_show_renders_signals_file(tmp_path, capsys):
    path = tmp_path / "signals.json"
    path.write_text(json.dumps([signal_dict(), signal_dict("sz000001")]), encoding="utf-8")

    exit_code = main(["show", "--file", str(path)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "sh600519" in out and "sz000001" in out
    assert "long" in out


def test_report_show_renders_empty_file(tmp_path, capsys):
    path = tmp_path / "signals.json"
    path.write_text("[]", encoding="utf-8")

    exit_code = main(["show", "--file", str(path)])

    assert exit_code == 0
    assert "No signals." in capsys.readouterr().out


def test_report_show_fails_closed_on_invalid_signal(tmp_path, capsys):
    path = tmp_path / "signals.json"
    path.write_text(json.dumps([{"symbol": "sh600519"}]), encoding="utf-8")

    exit_code = main(["show", "--file", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err.startswith("error:")


def test_report_show_includes_quality_summary_from_report_object(
    tmp_path, capsys
):
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "signals": [signal_dict()],
                "quality_events": [
                    {
                        "level": "block",
                        "reason_code": "MISSING_REQUIRED_BAR",
                        "symbol": "<img src=x>",
                        "as_of": "2026-09-15T14:30:00+00:00",
                        "message": "<script>alert(1)</script>",
                        "strategy_id": "trend_breakout",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["show", "--file", str(path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Quality: warn=0 block=1" in output
    assert "MISSING_REQUIRED_BAR" in output


@pytest.mark.parametrize(
    "override",
    [
        {"strategy_id": None},
        {"symbol": 600000},
        {"message": True},
        {"unexpected": "field"},
    ],
)
def test_report_show_rejects_schema_invalid_quality_events(
    tmp_path, capsys, override
):
    event = {
        "level": "warn",
        "reason_code": "STALE_QUOTE",
        "symbol": "sh600000",
        "as_of": "2026-09-15T14:30:00+00:00",
        "message": "quote is stale",
        **override,
    }
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps({"signals": [], "quality_events": [event]}),
        encoding="utf-8",
    )

    exit_code = main(["show", "--file", str(path)])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err.startswith("error: invalid quality event")
