"""Agent prompt templates (FR-5 / design section 8): each role gets a
prompt that states its allowed tools, its prohibitions, and the
non-executable nature of agent output."""

from quant_agent.agents.prompts import render_prompt
from quant_agent.agents.roles import AGENT_ROLES


def test_every_role_has_a_prompt_stating_boundaries():
    for role_id, role in AGENT_ROLES.items():
        prompt = render_prompt(role_id)

        assert role_id in prompt
        for tool in sorted(role.allowed_tools):
            assert tool in prompt, f"{role_id} prompt omits allowed tool {tool}"
        for tool in sorted(role.forbidden_tools):
            assert tool in prompt, f"{role_id} prompt omits forbidden tool {tool}"
        # FR-5.4: agent output is never an execution instruction.
        assert "非执行指令" in prompt or "not an execution instruction" in prompt.lower()


def test_prompt_includes_task_and_output_contract():
    prompt = render_prompt(
        "research",
        task="解释 sh600519 今日信号",
        output_schema='{"summary": str, "confidence": float}',
    )

    assert "解释 sh600519 今日信号" in prompt
    assert '{"summary": str, "confidence": float}' in prompt


def test_unknown_role_fails_closed():
    import pytest

    with pytest.raises(KeyError):
        render_prompt("superuser")
