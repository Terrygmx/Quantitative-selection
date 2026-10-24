from datetime import date, datetime, timezone

import pytest

from quant_agent.domain.models import Instrument, Order, RunManifest, Signal


def instrument(**overrides):
    values = {
        "symbol": "sh600519",
        "exchange": "SSE",
        "board": "MainBoard",
        "status": "Active",
        "listing_date": date(2001, 8, 27),
        "tick": "0.01",
        "lot_size": 100,
    }
    values.update(overrides)
    return Instrument(**values)


def test_instrument_requires_exchange_board_and_status():
    with pytest.raises(ValueError, match="exchange"):
        instrument(exchange="")
    with pytest.raises(ValueError, match="board"):
        instrument(board="")
    with pytest.raises(ValueError, match="status"):
        instrument(status="")


def test_instrument_round_trips_serialization():
    item = instrument()

    data = item.to_dict()

    assert Instrument.from_dict(data) == item


def test_signal_rejects_out_of_range_target_weight():
    signal = Signal(
        strategy_id="tail-momentum",
        version="1.0.0",
        symbol="sh600519",
        side="long",
        target_weight=0.2,
        confidence=0.8,
        valid_from=datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc),
        valid_to=datetime(2026, 9, 16, 9, 30, tzinfo=timezone.utc),
        evidence={},
    )

    assert signal.to_dict()["target_weight"] == 0.2
    assert Signal.from_dict(signal.to_dict()) == signal

    with pytest.raises(ValueError, match="target_weight"):
        signal.__class__.from_dict({**signal.to_dict(), "target_weight": 1.01})
    with pytest.raises(ValueError, match="target_weight"):
        signal.__class__.from_dict({**signal.to_dict(), "target_weight": -1.01})


def test_order_rejects_non_lot_quantity():
    order = Order(
        id="ord-1",
        symbol="sh600519",
        side="buy",
        quantity=100,
        limit_price="1800.00",
        created_at=datetime(2026, 9, 15, 14, 31, tzinfo=timezone.utc),
    )

    assert order.quantity == 100
    assert Order.from_dict(order.to_dict()) == order

    data = order.to_dict()
    data["quantity"] = 101
    with pytest.raises(ValueError, match="lot"):
        Order.from_dict(data)


def test_run_manifest_hash_is_deterministic_and_content_addressed():
    manifest = RunManifest(
        run_id="run-1",
        git_sha="a" * 40,
        config_hash="b" * 64,
        data_snapshot="snapshot-1",
        seed=42,
        created_at=datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc),
    )
    same_manifest = RunManifest(
        created_at=manifest.created_at,
        seed=42,
        data_snapshot="snapshot-1",
        config_hash="b" * 64,
        git_sha="a" * 40,
        run_id="run-1",
    )

    assert manifest.content_hash == same_manifest.content_hash
    assert manifest.content_hash == manifest.to_dict()["content_hash"]
    assert len(manifest.content_hash) == 64

    changed = RunManifest.from_dict({**manifest.to_dict(), "seed": 43, "content_hash": None})
    assert changed.content_hash != manifest.content_hash

    with pytest.raises(AttributeError):
        manifest.run_id = "changed"

    assert RunManifest.from_dict(manifest.to_dict()) == manifest


def test_signal_and_order_accept_decimal_serialized_numbers():
    signal = Signal.from_dict(
        {
            "strategy_id": "tail-momentum",
            "version": "1.0.0",
            "symbol": "sh600519",
            "side": "long",
            "target_weight": "0.2",
            "confidence": "0.8",
            "valid_from": "2026-09-15T14:30:00+00:00",
            "valid_to": "2026-09-16T09:30:00+00:00",
            "evidence": {},
        }
    )

    assert signal.target_weight == 0.2

    order = Order.from_dict(
        {
            "id": "ord-1",
            "symbol": "sh600519",
            "side": "buy",
            "quantity": "100",
            "limit_price": "1800.00",
            "created_at": "2026-09-15T14:31:00+00:00",
        }
    )

    assert order.quantity == 100
    assert str(order.limit_price) == "1800.00"
