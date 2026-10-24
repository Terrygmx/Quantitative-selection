from datetime import datetime, timezone

import pytest

from quant_agent.adapters.market_data import Bar, DataUnavailable, InMemoryMarketDataPort


AS_OF = datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 15, 14, 31, tzinfo=timezone.utc)


def bar(timestamp, close=10.0, available_at=None):
    return Bar(
        instrument="sh600519",
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=100.0,
        available_at=available_at or timestamp,
    )


@pytest.mark.parametrize(
    "make_port",
    [
        lambda bars: InMemoryMarketDataPort(bars),
    ],
    ids=["in-memory"],
)
class TestMarketDataPortContract:
    def test_excludes_future_and_unavailable_bars(self, make_port):
        port = make_port([bar(AS_OF), bar(LATER), bar(AS_OF, available_at=LATER)])

        assert [item.timestamp for item in port.bars("sh600519", AS_OF)] == [AS_OF]

    def test_latest_visible_revision_wins(self, make_port):
        port = make_port(
            [
                bar(AS_OF, close=9.0),
                bar(AS_OF, close=9.1, available_at=AS_OF),
                bar(AS_OF, close=99.0, available_at=LATER),
            ]
        )

        assert [item.close for item in port.bars("sh600519", AS_OF)] == [9.1]

    def test_missing_required_bar_fails_closed(self, make_port):
        port = make_port([])

        with pytest.raises(DataUnavailable):
            port.bars("sh600519", AS_OF)
