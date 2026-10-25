"""Agent roles and their tool boundaries (DETAILED_DESIGN section 8):
research, data quality, risk review and dev agents each get an explicit
allowlist plus role-specific denials on top of the gateway's global
forbidden tools."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentRole:
    role_id: str
    allowed_tools: frozenset[str]
    forbidden_tools: frozenset[str]

    def allows(self, tool: str) -> bool:
        return tool in self.allowed_tools and tool not in self.forbidden_tools


RESEARCH_AGENT = AgentRole(
    role_id="research",
    allowed_tools=frozenset(
        {"read_approved_dataset", "draft_experiment", "explain_signal"}
    ),
    forbidden_tools=frozenset({"write_production_config", "submit_order"}),
)

DATA_QUALITY_AGENT = AgentRole(
    role_id="data_quality",
    allowed_tools=frozenset({"read_quality_report", "create_quality_event"}),
    forbidden_tools=frozenset({"modify_raw_data", "silence_block"}),
)

RISK_REVIEW_AGENT = AgentRole(
    role_id="risk_review",
    allowed_tools=frozenset(
        {"read_signals", "read_portfolio", "explain_rejection"}
    ),
    forbidden_tools=frozenset({"override_risk_decision"}),
)

DEV_AGENT = AgentRole(
    role_id="dev",
    allowed_tools=frozenset(
        {"create_plugin_draft", "create_test_draft", "create_doc_draft"}
    ),
    forbidden_tools=frozenset(
        {"merge_branch", "publish_release", "access_secrets"}
    ),
)

AGENT_ROLES: dict[str, AgentRole] = {
    role.role_id: role
    for role in (RESEARCH_AGENT, DATA_QUALITY_AGENT, RISK_REVIEW_AGENT, DEV_AGENT)
}


def role_for(role_id: str) -> AgentRole:
    return AGENT_ROLES[role_id]
