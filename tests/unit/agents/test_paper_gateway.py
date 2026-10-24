import pytest

from quant_agent.agents.paper import ApprovalRecord, PaperGateway


@pytest.fixture
def gateway():
    return PaperGateway()


def test_unapproved_strategy_cannot_run(gateway):
    with pytest.raises(ValueError, match="approval"):
        gateway.run("tail_momentum_overnight", {"lookback": 2}, dry_run=True)


def test_dry_run_produces_plan_without_orders(gateway):
    gateway.approve(
        ApprovalRecord(
            strategy_id="tail_momentum_overnight",
            config_hash="hash-1",
            approved_by="terry",
        )
    )

    result = gateway.run(
        "tail_momentum_overnight",
        {"lookback": 2, "config_hash": "hash-1"},
        dry_run=True,
    )

    assert result.status == "DRY_RUN"
    assert result.orders == []
