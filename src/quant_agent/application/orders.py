from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PendingOrder:
    order_id: str
    submitted_at: datetime
    status: str = "PENDING"
    updated_at: datetime | None = None
    rejection_code: str | None = None

    def transition(self, status: str, updated_at: datetime, rejection_code: str | None = None) -> "PendingOrder":
        allowed = {"PENDING": {"FILLED", "REJECTED"}}
        if status not in allowed.get(self.status, set()):
            raise ValueError(f"invalid transition from {self.status} to {status}")
        return PendingOrder(
            order_id=self.order_id,
            submitted_at=self.submitted_at,
            status=status,
            updated_at=updated_at,
            rejection_code=rejection_code,
        )


class OrderStateMachine:
    def __init__(self) -> None:
        self._orders: dict[str, PendingOrder] = {}

    def submit(self, order: PendingOrder) -> None:
        if order.order_id in self._orders:
            raise ValueError(f"duplicate order id: {order.order_id}")
        self._orders[order.order_id] = order

    def get(self, order_id: str) -> PendingOrder:
        return self._orders[order_id]

    def fill(self, order_id: str, timestamp: datetime) -> None:
        self._transition(order_id, "FILLED", timestamp)

    def reject(self, order_id: str, reason_code: str, timestamp: datetime) -> None:
        self._transition(order_id, "REJECTED", timestamp, reason_code)

    def _transition(
        self,
        order_id: str,
        status: str,
        timestamp: datetime,
        reason_code: str | None = None,
    ) -> None:
        self._orders[order_id] = self._orders[order_id].transition(
            status, timestamp, reason_code
        )
