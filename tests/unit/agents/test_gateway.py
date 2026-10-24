import hashlib
import json
import os

import pytest

from quant_agent.agents.gateway import AgentGateway, AgentRequest


@pytest.fixture
def gateway():
    return AgentGateway(allowed_tools={"read_dataset", "draft_experiment"})


def test_read_only_tools_are_allowed(gateway):
    result = gateway.execute(
        AgentRequest(
            agent_id="research",
            tool="read_dataset",
            arguments={"dataset": "approved-snapshot"},
        )
    )

    assert result.status == "allowed"
    assert result.output == {"dataset": "approved-snapshot", "mode": "read-only"}


def test_order_submission_is_denied(gateway):
    result = gateway.execute(
        AgentRequest(
            agent_id="research",
            tool="submit_order",
            arguments={"symbol": "sh600519", "quantity": 100},
        )
    )

    assert result.status == "denied"
    assert result.reason_code == "TOOL_NOT_ALLOWED"


def test_production_config_write_is_denied(gateway):
    result = gateway.execute(
        AgentRequest(
            agent_id="research",
            tool="write_production_config",
            arguments={"risk": {"max_position": 1.0}},
        )
    )

    assert result.status == "denied"
    assert result.reason_code == "TOOL_NOT_ALLOWED"


def test_blocked_data_event_cannot_be_skipped(gateway):
    result = gateway.execute(
        AgentRequest(
            agent_id="research",
            tool="skip_data_quality_block",
            arguments={"dataset": "approved-snapshot"},
        )
    )

    assert result.status == "denied"
    assert result.reason_code == "BLOCK_CANNOT_BE_SKIPPED"


def test_invalid_structured_output_is_rejected(gateway):
    with pytest.raises(ValueError, match="structured output"):
        gateway.validate_output(None)

    with pytest.raises(ValueError, match="structured output"):
        gateway.validate_output({"unrecognized": True})


def test_structured_output_requires_schema_fields_and_types():
    gateway = AgentGateway(allowed_tools={"read_dataset"})
    valid = {
        "summary": "review complete",
        "findings": [{"code": "DATA_GAP", "severity": "warn"}],
        "artifacts": [],
    }

    gateway.validate_output(valid, schema={
        "type": "object",
        "required": ["summary", "findings", "artifacts"],
        "properties": {
            "summary": {"type": "string"},
            "findings": {"type": "array"},
            "artifacts": {"type": "array"},
        },
    })

    with pytest.raises(ValueError, match="type"):
        gateway.validate_output({**valid, "summary": 1}, schema={"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}})
    with pytest.raises(ValueError, match="required"):
        gateway.validate_output({"findings": []}, schema={"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}})


def test_agent_events_bind_to_run_manifest():
    from datetime import datetime, timezone

    from quant_agent.agents.gateway import AuditEvent
    from quant_agent.domain.models import RunManifest

    manifest = RunManifest(
        run_id="run-1",
        git_sha="a" * 40,
        config_hash="b" * 64,
        data_snapshot="snapshot-1",
        seed=1,
        created_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
    )
    gateway = AgentGateway(allowed_tools={"read_dataset"}, manifest=manifest)
    gateway.execute(
        AgentRequest(agent_id="research", tool="read_dataset", arguments={})
    )

    event = gateway.audit_events[0]
    assert isinstance(event, AuditEvent)
    assert event.run_id == manifest.run_id
    assert event.manifest_hash == manifest.content_hash
    assert event.status == "allowed"
    with pytest.raises(AttributeError):
        event.status = "denied"


def test_audit_event_captures_invocation_and_model_details():
    from datetime import datetime, timezone

    from quant_agent.agents.gateway import AuditEvent
    from quant_agent.domain.models import RunManifest

    manifest = RunManifest(
        run_id="run-audit",
        git_sha="a" * 40,
        config_hash="b" * 64,
        data_snapshot="snapshot-1",
        seed=7,
        created_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
    )
    gateway = AgentGateway(
        allowed_tools={"read_dataset"},
        manifest=manifest,
        model_id="research-model-1",
        audit_sink=lambda event: persisted.append(event),
    )
    persisted = []
    arguments = {"dataset": "approved-snapshot", "nested": {"limit": 3}}

    gateway.execute(AgentRequest(agent_id="research", tool="read_dataset", arguments=arguments))
    gateway.execute(AgentRequest(agent_id="research", tool="submit_order", arguments={"quantity": 100}))

    event = gateway.audit_events[0]
    assert isinstance(event, AuditEvent)
    assert event.model_id == "research-model-1"
    assert event.arguments == arguments
    assert event.arguments is not arguments
    assert event.arguments_sha256 == hashlib.sha256(
        json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert event.output == {"dataset": "approved-snapshot", "nested": {"limit": 3}, "mode": "read-only"}
    assert event.reason_code is None
    assert gateway.audit_events[1].reason_code == "TOOL_NOT_ALLOWED"
    assert gateway.audit_events[1].output is None
    assert persisted == gateway.audit_events


def test_audit_sink_failure_does_not_mask_agent_result():
    gateway = AgentGateway(
        allowed_tools={"read_dataset"},
        model_id="research-model-1",
        audit_sink=lambda event: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )

    result = gateway.execute(AgentRequest(agent_id="research", tool="read_dataset", arguments={}))

    assert result.status == "allowed"
    assert gateway.audit_events[-1].status == "audit_write_failed"


def test_json_audit_sink_persists_complete_records(tmp_path):
    from datetime import datetime, timezone

    from quant_agent.agents.gateway import json_audit_sink
    from quant_agent.domain.clock import FixedClock

    path = os.path.join(tmp_path, "agent-audit.jsonl")
    gateway = AgentGateway(
        allowed_tools={"read_dataset"},
        model_id="research-model-1",
        audit_sink=json_audit_sink(path),
        clock=FixedClock(datetime(2026, 10, 24, 9, 30, tzinfo=timezone.utc)),
    )
    arguments = {"dataset": "approved-snapshot"}

    result = gateway.execute(AgentRequest(agent_id="research", tool="read_dataset", arguments=arguments))

    with open(path, encoding="utf-8") as audit_file:
        persisted = json.loads(audit_file.read())
    assert persisted == {
        "run_id": "",
        "manifest_hash": "",
        "agent_id": "research",
        "tool": "read_dataset",
        "status": result.status,
        "occurred_at": "2026-10-24T09:30:00+00:00",
        "model_id": "research-model-1",
        "arguments_sha256": hashlib.sha256(
            json.dumps(arguments, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "arguments": arguments,
        "output": result.output,
        "reason_code": None,
    }


def test_audit_event_uses_injected_clock():
    from datetime import datetime, timezone

    from quant_agent.domain.clock import FixedClock

    clock = FixedClock(datetime(2026, 10, 24, 9, 31, tzinfo=timezone.utc))
    gateway = AgentGateway(allowed_tools={"read_dataset"}, clock=clock)

    gateway.execute(AgentRequest(agent_id="research", tool="read_dataset", arguments={}))

    assert gateway.audit_events[-1].occurred_at == clock.now()


def test_validate_output_uses_locked_jsonschema_draft2020():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string", "minLength": 1}},
        "additionalProperties": False,
    }
    gateway = AgentGateway(allowed_tools=set())

    gateway.validate_output({"summary": "ok"}, schema=schema)

    with pytest.raises(ValueError, match="JSON schema"):
        gateway.validate_output({"summary": ""}, schema=schema)
    with pytest.raises(ValueError, match="JSON schema"):
        gateway.validate_output({"summary": "ok", "extra": 1}, schema=schema)
