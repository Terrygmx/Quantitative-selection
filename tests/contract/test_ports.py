from datetime import datetime, timezone

import pytest

from quant_agent.ports.market_data import (
    Bar,
    DataUnavailable,
    MarketDataPortLike,
    QualityEvent,
)


AS_OF = datetime(2026, 11, 8, 14, 30, tzinfo=timezone.utc)
LATER = datetime(2026, 11, 8, 14, 31, tzinfo=timezone.utc)


def bar(timestamp: datetime, available_at: datetime | None = None) -> Bar:
    return Bar(
        instrument="sh600519",
        timestamp=timestamp,
        open=10.0,
        high=10.0,
        low=10.0,
        close=10.0,
        volume=100.0,
        available_at=available_at or timestamp,
    )


class ContractPort:
    """Adapter-free fake that expresses the port contract, not storage policy."""

    def __init__(self, bars: list[Bar]):
        self._bars = bars

    def bars(self, instrument: str, as_of: datetime) -> list[Bar]:
        visible = [
            item
            for item in self._bars
            if item.instrument == instrument
            and item.timestamp <= as_of
            and item.available_at <= as_of
        ]
        if not visible:
            raise DataUnavailable(
                QualityEvent(
                    level="block",
                    reason_code="MISSING_REQUIRED_BAR",
                    symbol=instrument,
                    as_of=as_of,
                    message="bar unavailable",
                )
            )
        return visible


def test_market_data_port_is_structural_and_not_adapter_bound():
    assert isinstance(ContractPort([]), MarketDataPortLike)


def test_contract_port_excludes_future_or_unavailable_bars():
    port = ContractPort(
        [bar(AS_OF), bar(LATER), bar(AS_OF, available_at=LATER)]
    )

    assert port.bars("sh600519", AS_OF) == [bar(AS_OF)]


def test_contract_port_fails_closed_without_a_visible_bar():
    port = ContractPort([])

    with pytest.raises(DataUnavailable):
        port.bars("sh600519", AS_OF)


def test_bar_rejects_availability_before_timestamp():
    with pytest.raises(ValueError, match="available_at"):
        bar(AS_OF, available_at=AS_OF.replace(minute=29))


def test_data_unavailable_carries_a_quality_event():
    event = QualityEvent(
        level="block",
        reason_code="MISSING_REQUIRED_BAR",
        symbol="sh600519",
        as_of=AS_OF,
        message="bar unavailable",
    )

    error = DataUnavailable(event)

    assert error.event is event
