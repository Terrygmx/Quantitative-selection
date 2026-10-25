"""`quant-agent report show`: render a signals JSON file as text."""

import json

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
