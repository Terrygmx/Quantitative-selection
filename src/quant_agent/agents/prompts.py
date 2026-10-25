"""Prompt templates for the design-section-8 agent roles (FR-5). Every
prompt states the role's allowlist, its prohibitions, and that the
agent's natural-language output is never an execution instruction -
only human-approved configurations trigger execution."""

from __future__ import annotations

from typing import Mapping

from quant_agent.agents.roles import AGENT_ROLES, AgentRole


_TITLE = {
    "research": "研究 Agent",
    "data_quality": "数据质量 Agent",
    "risk_review": "风险审阅 Agent",
    "dev": "开发 Agent",
}

_OUTPUT_CONTRACT = {
    "research": '输出 JSON：{"summary": str, "confidence": float, "evidence": {...}}',
    "data_quality": '输出 JSON：{"summary": str, "events": [{"reason_code": str, "symbol": str}]}',
    "risk_review": '输出 JSON：{"summary": str, "explanations": [{"reason_code": str, "text": str}]}',
    "dev": '输出 JSON：{"summary": str, "artifacts": [{"path": str, "kind": str}]}',
}


def render_prompt(
    role_id: str,
    task: str = "",
    output_schema: str | None = None,
    extra_context: Mapping[str, str] | None = None,
) -> str:
    role: AgentRole = AGENT_ROLES[role_id]  # unknown roles fail closed
    allowed = "、".join(sorted(role.allowed_tools))
    forbidden = "、".join(sorted(role.forbidden_tools))
    schema = output_schema or _OUTPUT_CONTRACT[role_id]
    lines = [
        f"你是{_TITLE[role_id]}（{role_id}），运行于 A 股多策略量化平台。",
        "",
        f"允许使用的工具：{allowed}。",
        f"明确禁止：{forbidden}；任何越权请求都必须拒绝。",
        "",
        f"本次任务：{task or '（等待任务指派）'}",
        f"输出契约：{schema}",
    ]
    for key, value in (extra_context or {}).items():
        lines.append(f"{key}：{value}")
    lines += [
        "",
        "约束：你产出的自然语言只是研究/审阅产物，是非执行指令；",
        "只有经过人工审批的策略配置才会触发任何执行。所有调用都会",
        "记录审计（输入摘要、模型标识、输出），不要在输出中包含密钥、",
        "账户信息或完整持仓。",
    ]
    return "\n".join(lines)
