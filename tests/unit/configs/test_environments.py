"""Environment configurations: four declared environments, prod never
enables live execution, no secrets committed."""

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3] / "configs" / "environments"


@pytest.mark.parametrize("env", ["dev", "research", "paper", "prod"])
def test_environment_file_is_valid_json_with_known_keys(env):
    data = json.loads((ROOT / f"{env}.json").read_text(encoding="utf-8"))

    assert data["environment"] == env
    assert set(data["defaults"]) <= {
        "dry_run",
        "require_approval",
        "approvals_path",
        "log_level",
        "audit_sink",
        "audit_path",
        "note",
    }


def test_paper_and_prod_require_approval_and_prod_stays_dry_run():
    paper = json.loads((ROOT / "paper.json").read_text(encoding="utf-8"))
    prod = json.loads((ROOT / "prod.json").read_text(encoding="utf-8"))

    assert paper["defaults"]["dry_run"] is False
    assert paper["defaults"]["require_approval"] is True
    # DETAILED_DESIGN section 9: prod defaults to dry-run even when enabled.
    assert prod["defaults"]["dry_run"] is True
    assert prod["defaults"]["require_approval"] is True


def test_no_secrets_in_environment_files():
    for path in ROOT.glob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in ("password", "token", "api_key", "secret"):
            assert forbidden not in text, f"{path.name} mentions {forbidden}"


def test_execution_layer_has_no_live_channel():
    """PRD non-goal made structural: the execution surface exposes the
    PaperExecution protocol and exactly one concrete simulated executor;
    no live/real/broker executor type exists anywhere in the package."""
    import inspect
    import pathlib

    import quant_agent.agents.paper as paper_module

    executor_classes = [
        name
        for name, obj in vars(paper_module).items()
        if inspect.isclass(obj) and hasattr(obj, "execute")
    ]
    assert set(executor_classes) == {"PaperExecution", "SimulatedPaperExecution"}

    package_root = pathlib.Path(paper_module.__file__).parent
    for path in package_root.glob("*.py"):
        for forbidden in ("LiveExecution", "RealExecution", "BrokerExecution"):
            assert forbidden not in path.read_text(encoding="utf-8"), (
                f"{path.name} mentions {forbidden}"
            )


def test_paper_gateway_rejects_live_session_markers():

    from quant_agent.agents.gateway import AgentGateway, AgentRequest

    gateway = AgentGateway(allowed_tools={"read_approved_dataset"})

    result = gateway.execute(
        AgentRequest(
            agent_id="any",
            tool="submit_live_order",
            arguments={},
        )
    )

    assert result.status == "denied"
