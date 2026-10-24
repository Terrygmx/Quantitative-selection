import pytest

from datetime import datetime, timezone

from quant_agent.agents.paper import ApprovalRecord, PaperGateway
from quant_agent.domain.clock import FixedClock


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


def test_paper_scheduler_fails_closed_when_live_execution_is_not_configured():
    from quant_agent.agents.paper import PaperScheduler

    scheduler = PaperScheduler(gateway=PaperGateway(), dry_run=False)

    import pytest

    scheduler.gateway.approve(
        ApprovalRecord(
            strategy_id="strategy",
            config_hash="missing",
            approved_by="terry",
        )
    )
    with pytest.raises(ValueError, match="execution"):
        scheduler.run(
            "strategy",
            {"config_hash": "missing"},
            run_at=None,
        )


class RecordingExecution:
    def __init__(self):
        self.calls = []

    def execute(self, strategy_id, config, run_at):
        self.calls.append((strategy_id, dict(config), run_at))
        return [
            {
                "symbol": "sh600176",
                "side": "buy",
                "quantity": 100,
                "status": "FILLED",
            }
        ]


def test_non_dry_run_executes_only_after_approval():
    execution = RecordingExecution()
    gateway = PaperGateway(
        clock=FixedClock(datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)),
        execution=execution,
    )
    gateway.approve(
        ApprovalRecord(
            strategy_id="tail_momentum_overnight",
            config_hash="hash-1",
            approved_by="terry",
        )
    )

    result = gateway.run(
        "tail_momentum_overnight",
        {"universe": ["sh600176"], "config_hash": "hash-1"},
        dry_run=False,
    )

    assert result.status == "PAPER_EXECUTED"
    assert result.orders[0]["status"] == "FILLED"
    assert execution.calls[0][0] == "tail_momentum_overnight"
    assert execution.calls[0][2] == datetime(
        2026, 10, 24, 1, 0, tzinfo=timezone.utc
    )


def test_non_dry_run_fails_closed_without_executor():
    gateway = PaperGateway()
    gateway.approve(
        ApprovalRecord(
            strategy_id="tail_momentum_overnight",
            config_hash="hash-1",
            approved_by="terry",
        )
    )

    with pytest.raises(ValueError, match="execution"):
        gateway.run(
            "tail_momentum_overnight",
            {"config_hash": "hash-1"},
            dry_run=False,
        )


def test_scheduler_run_at_is_used_for_non_dry_run():
    from quant_agent.agents.paper import PaperScheduler

    execution = RecordingExecution()
    gateway = PaperGateway(execution=execution)
    gateway.approve(
        ApprovalRecord(
            strategy_id="tail_momentum_overnight",
            config_hash="hash-1",
            approved_by="terry",
        )
    )
    scheduler = PaperScheduler(gateway=gateway, dry_run=False)
    run_at = datetime(2026, 10, 26, 14, 45, tzinfo=timezone.utc)

    scheduler.run(
        "tail_momentum_overnight",
        {"config_hash": "hash-1"},
        run_at=run_at,
    )

    assert execution.calls[0][2] == run_at
