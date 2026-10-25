from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping


def _require_non_empty(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _parse_decimal(value: str | Decimal) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    exchange: str
    board: str
    status: str
    listing_date: date
    tick: Decimal
    lot_size: int

    def __post_init__(self) -> None:
        _require_non_empty(self.symbol, "symbol")
        _require_non_empty(self.exchange, "exchange")
        _require_non_empty(self.board, "board")
        _require_non_empty(self.status, "status")
        object.__setattr__(self, "tick", _parse_decimal(self.tick))
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "board": self.board,
            "status": self.status,
            "listing_date": self.listing_date.isoformat(),
            "tick": str(self.tick),
            "lot_size": self.lot_size,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Instrument":
        return cls(
            symbol=data["symbol"],
            exchange=data["exchange"],
            board=data["board"],
            status=data["status"],
            listing_date=date.fromisoformat(data["listing_date"]),
            tick=Decimal(data["tick"]),
            lot_size=int(data["lot_size"]),
        )


@dataclass(frozen=True, slots=True)
class Signal:
    strategy_id: str
    version: str
    symbol: str
    side: str
    target_weight: float
    confidence: float
    valid_from: datetime
    valid_to: datetime
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field in ("strategy_id", "version", "symbol", "side"):
            _require_non_empty(getattr(self, field), field)
        if self.side not in ("long", "short"):
            raise ValueError("side must be long or short")
        if not -1 <= self.target_weight <= 1:
            raise ValueError("target_weight must be in [-1, 1]")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if self.valid_from >= self.valid_to:
            raise ValueError("valid_from must be before valid_to")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "valid_from": self.valid_from.isoformat(),
            "valid_to": self.valid_to.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Signal":
        return cls(
            strategy_id=data["strategy_id"],
            version=data["version"],
            symbol=data["symbol"],
            side=data["side"],
            target_weight=float(data["target_weight"]),
            confidence=float(data["confidence"]),
            valid_from=_parse_datetime(data["valid_from"]),
            valid_to=_parse_datetime(data["valid_to"]),
            evidence=dict(data.get("evidence", {})),
        )


@dataclass(frozen=True, slots=True)
class Order:
    id: str
    symbol: str
    side: str
    quantity: int
    limit_price: Decimal
    created_at: datetime
    session: str = "continuous"

    def __post_init__(self) -> None:
        _require_non_empty(self.id, "id")
        _require_non_empty(self.symbol, "symbol")
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be buy or sell")
        if self.session not in ("continuous", "after_hours_fixed"):
            raise ValueError("session must be continuous or after_hours_fixed")
        object.__setattr__(self, "limit_price", _parse_decimal(self.limit_price))
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.limit_price <= 0:
            raise ValueError("limit_price must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "limit_price": str(self.limit_price),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Order":
        return cls(
            id=data["id"],
            symbol=data["symbol"],
            side=data["side"],
            quantity=int(data["quantity"]),
            limit_price=Decimal(data["limit_price"]),
            created_at=_parse_datetime(data["created_at"]),
            session=str(data.get("session", "continuous")),
        )

    def validate_quantity(self, instrument: Instrument, allow_odd_lot: bool = False) -> None:
        if self.quantity % instrument.lot_size and not (allow_odd_lot and self.side == "sell"):
            raise ValueError(
                f"quantity must be a multiple of lot size {instrument.lot_size}"
            )
        if allow_odd_lot and self.side != "sell":
            raise ValueError("odd lot sells are the only permitted odd-lot orders")


def _canonical_json(data: Mapping[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    git_sha: str
    config_hash: str
    data_snapshot: str
    seed: int
    created_at: datetime
    _content_hash: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.run_id, "run_id")
        _require_non_empty(self.git_sha, "git_sha")
        _require_non_empty(self.config_hash, "config_hash")
        _require_non_empty(self.data_snapshot, "data_snapshot")
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(self, "_content_hash", self._compute_content_hash())

    @property
    def content_hash(self) -> str:
        return self._content_hash or ""

    def _identity(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "git_sha": self.git_sha,
            "config_hash": self.config_hash,
            "data_snapshot": self.data_snapshot,
            "seed": self.seed,
            "created_at": self.created_at.isoformat(),
        }

    def _compute_content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self._identity())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._identity(), "content_hash": self.content_hash}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunManifest":
        manifest = cls(
            run_id=data["run_id"],
            git_sha=data["git_sha"],
            config_hash=data["config_hash"],
            data_snapshot=data["data_snapshot"],
            seed=int(data["seed"]),
            created_at=_parse_datetime(data["created_at"]),
        )
        supplied_hash = data.get("content_hash")
        if supplied_hash is not None and supplied_hash != manifest.content_hash:
            raise ValueError("content_hash does not match manifest contents")
        return manifest
