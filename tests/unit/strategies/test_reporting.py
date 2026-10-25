from datetime import datetime, timedelta, timezone

from quant_agent.domain.models import Signal
from quant_agent.strategies.reporting import render_signal_report


def test_signal_report_is_empty_when_no_signals():
    assert render_signal_report([]) == "No tail-momentum signals."


def test_signal_report_contains_symbol_and_weights():
    now = datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc)
    signal = Signal(
        strategy_id="tail_momentum_overnight",
        version="0.1.0",
        symbol="sh600519",
        side="long",
        target_weight=0.2,
        confidence=0.8,
        valid_from=now,
        valid_to=now + timedelta(hours=1),
        evidence={},
    )

    report = render_signal_report([signal])

    assert "sh600519 long weight=0.20 confidence=0.80" in report


def test_render_supports_a_custom_title():
    from quant_agent.strategies.reporting import render_signal_report

    assert render_signal_report([], title="Strategy signals") == "No signals."
    text = render_signal_report(
        [Signal(
            strategy_id="s", version="1", symbol="sh600519", side="long",
            target_weight=0.5, confidence=0.9,
            valid_from=datetime(2026, 9, 15, tzinfo=timezone.utc),
            valid_to=datetime(2026, 9, 16, tzinfo=timezone.utc),
            evidence={},
        )],
        title="Daily report",
    )
    assert text.splitlines()[0] == "Daily report"
    assert "sh600519" in text
