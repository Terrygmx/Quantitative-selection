from __future__ import annotations

from typing import Any, Mapping


TYPE_NAMES: Mapping[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def validate_config(config: Mapping[str, Any], schema: Mapping[str, Any]) -> None:
    if not isinstance(config, dict):
        raise ValueError("configuration must be an object")
    for field in schema.get("required", []):
        if field not in config:
            raise ValueError(f"{field} is required")

    properties = schema.get("properties", {})
    for field, value in config.items():
        if field not in properties:
            if schema.get("additionalProperties") is False:
                raise ValueError(f"unknown configuration keys: [{field!r}]")
            continue
        field_schema = properties[field]
        validate_value(field, value, field_schema)


def validate_value(field: str, value: Any, schema: Mapping[str, Any]) -> None:
    expected = schema.get("type")
    python_type: type | tuple[type, ...] | None = None
    if isinstance(expected, str):
        python_type = TYPE_NAMES.get(expected)
    if python_type is not None and not isinstance(value, python_type):
        raise ValueError(f"{field} must be {expected}")
    if expected == "integer" and isinstance(value, bool):
        raise ValueError(f"{field} must be integer")
    if "minimum" in schema and value < schema["minimum"]:
        raise ValueError(f"{field} must be >= minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        raise ValueError(f"{field} must be <= maximum {schema['maximum']}")
    if expected == "array":
        minimum_items = schema.get("minItems")
        if minimum_items is not None and len(value) < minimum_items:
            raise ValueError(f"{field} must contain at least minItems {minimum_items}")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_value(f"{field}[{index}]", item, item_schema)
    if expected == "string":
        minimum_length = schema.get("minLength")
        if minimum_length is not None and len(value) < minimum_length:
            raise ValueError(f"{field} must have length >= minLength {minimum_length}")
    if expected == "object":
        minimum_props = schema.get("minProperties")
        if minimum_props is not None and len(value) < minimum_props:
            raise ValueError(
                f"{field} must contain at least minProperties {minimum_props}"
            )
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            for key, item in value.items():
                validate_value(f"{field}.{key}", item, additional)
