"""Agent role tool boundaries per DETAILED_DESIGN section 8: each role gets
its own allowlist; denials are auditable and unknown agents fail closed."""

from quant_agent.agents.gateway import AgentGateway, AgentRequest
from quant_agent.agents.roles import (
    AGENT_ROLES,
    role_for,
)


def request(agent_id="research-1", tool="read_approved_dataset"):
    return AgentRequest(agent_id=agent_id, tool=tool, arguments={})


def test_four_roles_exist_with_design_section_8_boundaries():
    assert set(AGENT_ROLES) == {
        "research",
        "data_quality",
        "risk_review",
        "dev",
    }
    research = AGENT_ROLES["research"]
    assert "read_approved_dataset" in research.allowed_tools
    assert "write_production_config" in research.forbidden_tools
    assert "submit_order" in research.forbidden_tools

    data_quality = AGENT_ROLES["data_quality"]
    assert "create_quality_event" in data_quality.allowed_tools
    assert "modify_raw_data" in data_quality.forbidden_tools
    assert "silence_block" in data_quality.forbidden_tools

    risk_review = AGENT_ROLES["risk_review"]
    assert "explain_rejection" in risk_review.allowed_tools
    assert "override_risk_decision" in risk_review.forbidden_tools

    dev = AGENT_ROLES["dev"]
    assert "create_plugin_draft" in dev.allowed_tools
    assert "merge_branch" in dev.forbidden_tools
    assert "access_secrets" in dev.forbidden_tools


def test_role_allows_only_its_own_tools():
    assert role_for("research").allows("read_approved_dataset") is True
    assert role_for("research").allows("create_quality_event") is False
    assert role_for("data_quality").allows("silence_block") is False


def gateway_with_roles():
    return AgentGateway(
        allowed_tools={
            tool
            for role in AGENT_ROLES.values()
            for tool in role.allowed_tools
        },
        role_bindings={
            "research-1": AGENT_ROLES["research"],
            "dq-1": AGENT_ROLES["data_quality"],
        },
    )


def test_gateway_enforces_role_allowlists_with_audit():
    gateway = gateway_with_roles()

    allowed = gateway.execute(request("research-1", "read_approved_dataset"))
    assert allowed.status == "allowed"

    cross_role = gateway.execute(request("research-1", "create_quality_event"))
    assert cross_role.status == "denied"
    assert cross_role.reason_code == "ROLE_TOOL_NOT_ALLOWED"

    forbidden = gateway.execute(request("dq-1", "silence_block"))
    assert forbidden.status == "denied"
    assert forbidden.reason_code == "ROLE_TOOL_NOT_ALLOWED"

    denials = [
        event for event in gateway.audit_events if event.status == "denied"
    ]
    assert len(denials) == 2


def test_gateway_fails_closed_for_unbound_agents():
    gateway = gateway_with_roles()

    result = gateway.execute(request("stranger-1", "read_approved_dataset"))

    assert result.status == "denied"
    assert result.reason_code == "AGENT_ROLE_UNKNOWN"


def test_gateway_without_bindings_keeps_legacy_behavior():
    gateway = AgentGateway(allowed_tools={"read_approved_dataset"})

    result = gateway.execute(request("anyone", "read_approved_dataset"))

    assert result.status == "allowed"
