from datetime import datetime, timezone

import pytest

from quant_agent.application.orders import OrderStateMachine, PendingOrder


TS1 = datetime(2026, 9, 15, 9, 31, tzinfo=timezone.utc)
TS2 = datetime(2026, 9, 15, 9, 32, tzinfo=timezone.utc)


def machine():
    state = OrderStateMachine()
    order = PendingOrder(order_id="o1", submitted_at=TS1)
    state.submit(order)
    return state


def test_pending_order_can_fill():
    state = machine()

    state.fill("o1", TS2)

    assert state.get("o1").status == "FILLED"
    assert state.get("o1").updated_at == TS2


def test_order_cannot_fill_after_rejection():
    state = machine()
    state.reject("o1", "LIMIT_UP", TS2)

    with pytest.raises(ValueError, match="transition"):
        state.fill("o1", TS2)
