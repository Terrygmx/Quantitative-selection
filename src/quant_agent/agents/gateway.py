from __future__ import annotations

from dataclasses import dataclass
import copy
import dataclasses
import hashlib
from datetime import datetime
import json
import logging
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from quant_agent.domain.clock import Clock, SystemClock
from quant_agent.domain.models import RunManifest


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


@dataclass(frozen=True, slots=True)
class AuditEvent:
    run_id: str
    manifest_hash: str
    agent_id: str
    tool: str
    status: str
    occurred_at: datetime | None = None
    model_id: str = ""
    arguments_sha256: str = ""
    arguments: Mapping[str, Any] | None = None
    output: Mapping[str, Any] | None = None
    reason_code: str | None = None


def _digest(data: Mapping[str, Any]) -> str:
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot(data: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: copy.deepcopy(value) for key, value in data.items()})


def _plain(data: Any) -> Any:
    if isinstance(data, MappingProxyType):
        return dict(data)
    return data


def json_audit_sink(path: str):
    def append(event: AuditEvent) -> None:
        record = {
            "run_id": event.run_id,
            "manifest_hash": event.manifest_hash,
            "agent_id": event.agent_id,
            "tool": event.tool,
            "status": event.status,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "model_id": event.model_id,
            "arguments_sha256": event.arguments_sha256,
            "arguments": _plain(event.arguments),
            "output": _plain(event.output),
            "reason_code": event.reason_code,
        }
        with open(path, "a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    return append


def memory_audit_sink(events: list[AuditEvent]) -> None:
    def append(event: AuditEvent) -> None:
        events.append(event)

    return append


def null_audit_sink(event: AuditEvent) -> None:
    """No-op sink for tests and callers that manage audit storage externally."""


class AgentGateway:
    def __init__(
        self,
        allowed_tools: set[str],
        manifest: RunManifest | None = None,
        model_id: str = "",
        audit_sink=None,
        clock: Clock = SystemClock(),
    ):
        self.allowed_tools = set(allowed_tools)
        self.manifest = manifest
        self.model_id = model_id
        self.audit_sink = audit_sink
        self.clock = clock
        self.audit_events: list[AuditEvent] = []

    def execute(self, request: AgentRequest) -> AgentResult:
        if request.tool in FORBIDDEN_ALWAYS:
            result = AgentResult(
                status="denied",
                agent_id=request.agent_id,
                tool=request.tool,
                reason_code=FORBIDDEN_ALWAYS[request.tool],
            )
            self._audit(request, result)
            return result
        if request.tool not in self.allowed_tools:
            result = AgentResult(
                status="denied",
                agent_id=request.agent_id,
                tool=request.tool,
                reason_code="TOOL_NOT_ALLOWED",
            )
            self._audit(request, result)
            return result
        result = AgentResult(
            status="allowed",
            agent_id=request.agent_id,
            tool=request.tool,
            output={**request.arguments, "mode": "read-only"},
        )
        self._audit(request, result)
        return result

    def _audit(self, request: AgentRequest, result: AgentResult) -> None:
        event = AuditEvent(
            run_id=self.manifest.run_id if self.manifest else "",
            manifest_hash=self.manifest.content_hash if self.manifest else "",
            agent_id=request.agent_id,
            tool=request.tool,
            status=result.status,
            occurred_at=self.clock.now(),
            model_id=self.model_id,
            arguments_sha256=_digest(request.arguments),
            arguments=_snapshot(request.arguments),
            output=_snapshot(result.output) if result.output is not None else None,
            reason_code=result.reason_code,
        )
        self.audit_events.append(event)
        if self.audit_sink is None:
            return
        try:
            self.audit_sink(event)
        except Exception:
            logging.exception("agent audit write failed")
            self.audit_events[-1] = dataclasses.replace(event, status="audit_write_failed")

    def validate_output(
        self,
        output: Mapping[str, Any] | None,
        schema: Mapping[str, Any] | None = None,
    ) -> None:
        if schema is None:
            if not isinstance(output, Mapping) or "summary" not in output:
                raise ValueError("structured output with summary is required")
            return

        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(output), key=lambda error: list(error.path))
        if errors:
            messages = "; ".join(error.message for error in errors)
            raise ValueError(f"JSON schema validation failed: {messages}")
