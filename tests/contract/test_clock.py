from datetime import datetime, timezone

import pytest

from quant_agent.ports.clock import FixedClock, SystemClock


def test_fixed_clock_returns_the_injected_timezone_aware_instant():
    instant = datetime(2026, 11, 8, 14, 30, tzinfo=timezone.utc)

    assert FixedClock(instant).now() == instant


def test_fixed_clock_rejects_naive_time():
    with pytest.raises(ValueError, match="timezone-aware"):
        FixedClock(datetime(2026, 11, 8, 14, 30))


def test_system_clock_returns_timezone_aware_time():
    assert SystemClock().now().tzinfo is not None
