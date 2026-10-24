from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


FORBIDDEN_ALWAYS = {
    "submit_order": "TOOL_NOT_ALLOWED",
    "write_production_config": "TOOL_NOT_ALLOWED",
    "skip_data_quality_block": "BLOCK_CANNOT_BE_SKIPPED",
}


@dataclass(frozen=True, slots=True)
class AgentRequest:
    agent_id: str
    tool: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AgentResult:
    status: str
    agent_id: str
    tool: str
    output: Mapping[str, Any] | None = None
    reason_code: str | None = None


class AgentGateway:
    def __init__(self, allowed_tools: set[str]):
        self.allowed_tools = set(allowed_tools)

    def execute(self, request: AgentRequest) -> AgentResult:
        if request.tool in FORBIDDEN_ALWAYS:
            return AgentResult(
                status="denied",
                agent_id=request.agent_id,
                tool=request.tool,
                reason_code=FORBIDDEN_ALWAYS[request.tool],
            )
        if request.tool not in self.allowed_tools:
            return AgentResult(
                status="denied",
                agent_id=request.agent_id,
                tool=request.tool,
                reason_code="TOOL_NOT_ALLOWED",
            )
        return AgentResult(
            status="allowed",
            agent_id=request.agent_id,
            tool=request.tool,
            output={**request.arguments, "mode": "read-only"},
        )

    def validate_output(
        self,
        output: Mapping[str, Any] | None,
        schema: Mapping[str, Any] | None = None,
    ) -> None:
        if schema is None:
            if not isinstance(output, Mapping) or "summary" not in output:
                raise ValueError("structured output with summary is required")
            return

        expected_type = schema.get("type", "object")
        if expected_type != "object" or not isinstance(output, Mapping):
            raise ValueError("structured output type must be object")
        for field in schema.get("required", []):
            if field not in output:
                raise ValueError(f"structured output missing required field: {field}")
        properties = schema.get("properties", {})
        type_map = {
            "object": dict,
            "array": list,
            "string": str,
            "number": (int, float),
            "boolean": bool,
        }
        for field, field_schema in properties.items():
            if field not in output:
                continue
            expected = field_schema.get("type")
            python_type = type_map.get(expected)
            if python_type and not isinstance(output[field], python_type):
                raise ValueError(
                    f"structured output field {field} has invalid type {expected}"
                )
