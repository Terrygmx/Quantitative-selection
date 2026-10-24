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


def test_paper_scheduler_runs_only_approved_dry_runs():
    from datetime import datetime, timezone

    from quant_agent.agents.paper import PaperScheduler

    gateway = PaperGateway()
    gateway.approve(
        ApprovalRecord(
            strategy_id="tail_momentum_overnight",
            config_hash="hash-1",
            approved_by="terry",
        )
    )
    scheduler = PaperScheduler(gateway=gateway, dry_run=True)
    run_at = datetime(2026, 10, 26, 14, 45, tzinfo=timezone.utc)

    result = scheduler.run(
        "tail_momentum_overnight",
        {"lookback": 2, "config_hash": "hash-1"},
        run_at=run_at,
    )

    assert result.status == "DRY_RUN"
    assert scheduler.history == [
        {
            "strategy_id": "tail_momentum_overnight",
            "config_hash": "hash-1",
            "status": "DRY_RUN",
            "run_at": run_at.isoformat(),
        }
    ]


def test_paper_scheduler_will_not_run_live_without_future_requirement():
    from quant_agent.agents.paper import PaperScheduler

    scheduler = PaperScheduler(gateway=PaperGateway(), dry_run=False)

    import pytest

    with pytest.raises(ValueError, match="live paper execution"):
        scheduler.run(
            "strategy",
            {"config_hash": "missing"},
            run_at=None,
        )
