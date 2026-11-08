"""Canonical, stable fingerprints for run configuration and data artifacts."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, DecimalException


_PLAIN_DECIMAL = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?$")


def canonical_hash(value: object) -> str:
    payload = json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return canonical_value(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = [canonical_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        )
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def parse_decimal_string(
    value: object,
    field: str,
    *,
    minimum: Decimal,
    allow_zero: bool,
) -> Decimal:
    if not isinstance(value, str) or _PLAIN_DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{field} must be a plain decimal string")
    if value.startswith("-") and allow_zero:
        raise ValueError(f"{field} must be non-negative")
    try:
        result = Decimal(value)
    except DecimalException as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    valid = result >= minimum if allow_zero else result > minimum
    if not valid:
        relation = "at least" if allow_zero else "greater than"
        raise ValueError(f"{field} must be {relation} {minimum}")
    return result
