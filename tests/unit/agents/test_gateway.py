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
