from datetime import datetime, timezone

from quant_agent.domain.clock import FixedClock, SystemClock


def test_fixed_clock_returns_injected_time():
    now = datetime(2026, 10, 24, 10, 30, tzinfo=timezone.utc)
    clock = FixedClock(now)

    assert clock.now() == now


def test_system_clock_returns_current_utc_time():
    before = datetime.now(timezone.utc)
    now = SystemClock().now()
    after = datetime.now(timezone.utc)

    assert before <= now <= after
    assert now.tzinfo is timezone.utc
