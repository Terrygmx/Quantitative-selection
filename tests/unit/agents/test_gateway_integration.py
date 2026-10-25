"""Gateway-to-toolbox integration: allowed role tools actually execute and
their results ride in the AgentResult; executors' exceptions are converted
to audited denials (TOOL_FAILED), never leaked to callers."""

from datetime import datetime, timezone


from quant_agent.adapters.market_data import Bar, InMemoryMarketDataPort
from quant_agent.agents.gateway import AgentGateway, AgentRequest
from quant_agent.agents.role_tools import RoleToolbox
from quant_agent.agents.roles import AGENT_ROLES


UTC = timezone.utc
AS_OF = datetime(2026, 9, 15, 15, 0, tzinfo=UTC)


def build_gateway(tmp_path, data_port):
    toolbox = RoleToolbox(
        data_port=data_port,
        drafts_dir=tmp_path / "drafts",
        quality_events_path=tmp_path / "quality.jsonl",
    )
    return AgentGateway(
        allowed_tools={
            tool for role in AGENT_ROLES.values() for tool in role.allowed_tools
        },
        role_bindings={
            "research-1": AGENT_ROLES["research"],
            "dq-1": AGENT_ROLES["data_quality"],
            "risk-1": AGENT_ROLES["risk_review"],
            "dev-1": AGENT_ROLES["dev"],
        },
        tool_executors={
            "read_approved_dataset": toolbox.read_approved_dataset,
            "draft_experiment": toolbox.draft_experiment,
            "create_quality_event": toolbox.create_quality_event,
            "explain_signal": toolbox.explain_signal,
            "explain_rejection": toolbox.explain_rejection,
        },
    )


def bars():
    return [
        Bar(
            instrument="sh600519",
            timestamp=AS_OF,
            open=45.0,
            high=46.0,
            low=44.5,
            close=45.8,
            volume=1000.0,
            available_at=AS_OF,
        )
    ]


def test_allowed_role_tool_executes_and_returns_output(tmp_path):
    gw = build_gateway(tmp_path, InMemoryMarketDataPort(bars()))

    result = gw.execute(
        AgentRequest(
            agent_id="research-1",
            tool="read_approved_dataset",
            arguments={
                "symbol": "sh600519",
                "as_of": AS_OF.isoformat(),
            },
        )
    )

    assert result.status == "allowed"
    assert result.output["bars"][0]["close"] == 45.8
    # Execution is audited like any other call.
    assert gw.audit_events[-1].status == "allowed"


def test_denied_tools_never_execute(tmp_path):
    gw = build_gateway(tmp_path, InMemoryMarketDataPort(bars()))

    result = gw.execute(
        AgentRequest(
            agent_id="research-1",
            tool="create_quality_event",
            arguments={"reason_code": "X", "symbol": "s", "message": "m"},
        )
    )

    assert result.status == "denied"
    assert not (tmp_path / "quality.jsonl").exists()


def test_executor_errors_become_audited_denials(tmp_path):
    gw = build_gateway(tmp_path, InMemoryMarketDataPort([]))

    result = gw.execute(
        AgentRequest(
            agent_id="research-1",
            tool="explain_signal",
            arguments={
                "symbol": "sh600519",
                "as_of": AS_OF.isoformat(),
                "thesis": "x",
            },
        )
    )

    # explain_signal handles DataUnavailable internally, so it still passes,
    # but a broken executor must surface as an audited denial.
    assert result.status == "allowed"

    def exploding(**kwargs):
        raise RuntimeError("boom")

    gw.tool_executors["draft_experiment"] = exploding
    broken = gw.execute(
        AgentRequest(
            agent_id="research-1",
            tool="draft_experiment",
            arguments={"strategy_id": "s", "config": {}, "rationale": "r"},
        )
    )

    assert broken.status == "denied"
    assert broken.reason_code == "TOOL_FAILED"
    assert gw.audit_events[-1].reason_code == "TOOL_FAILED"


def test_datetime_arguments_are_accepted_for_tool_calls(tmp_path):
    box = build_gateway(tmp_path, InMemoryMarketDataPort(bars()))

    result = box.execute(
        AgentRequest(
            agent_id="research-1",
            tool="read_approved_dataset",
            arguments={"symbol": "sh600519", "as_of": AS_OF},
        )
    )

    assert result.status == "allowed"
    assert result.output["bars"]
