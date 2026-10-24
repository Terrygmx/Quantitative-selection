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

    def validate_output(self, output: Mapping[str, Any] | None) -> None:
        if not isinstance(output, Mapping) or "summary" not in output:
            raise ValueError("structured output with summary is required")
