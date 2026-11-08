from dataclasses import replace
from datetime import UTC, datetime

import pytest

from quant_agent.agents.paper import (
    ApprovalRecord,
    PaperGateway,
    PaperScheduler,
)
from quant_agent.application.paper_strategy import (
    PaperStrategyIdentity,
    PaperStrategyPlan,
)
from quant_agent.application.portfolio import RiskDecision, TargetPosition
from quant_agent.application.runs import RunManifestFactory


def plan(
    *,
    symbols: tuple[str, ...] = ("sh600000",),
    signals: tuple[dict[str, object], ...] = (),
) -> PaperStrategyPlan:
    manifest = RunManifestFactory().create(
        git_sha="test",
        config_hash="config-1",
        data_snapshot="data-1",
        seed=0,
    )
    targets = tuple(
        TargetPosition(
            symbol=symbol,
            net_weight=0.1,
            contributions={"manual": 0.1},
            industry="Technology",
            status="accepted",
        )
        for symbol in symbols
    )
    decisions = tuple(
        RiskDecision(
            symbol=target.symbol,
            status=target.status,
            net_weight=target.net_weight,
        )
        for target in targets
    )
    return PaperStrategyPlan(
        strategy_id="manual",
        strategy_version="2.3.4",
        config_hash="config-1",
        data_snapshot="data-1",
        read_snapshot="read-1",
        signals=signals,
        decisions=decisions,
        targets=targets,
        execution_symbols=symbols,
        source_signal_count=len(signals) if signals else (1 if symbols else 0),
        manifest=manifest,
    )


class StaticEvaluator:
    def __init__(self, result: PaperStrategyPlan):
        self.result = result
        self.calls = []
        self.identity_calls = []

    def identity(self, strategy_id, config, as_of):
        self.identity_calls.append((strategy_id, dict(config), as_of))
        return PaperStrategyIdentity(
            strategy_id=strategy_id,
            strategy_version=self.result.strategy_version,
            config_hash=self.result.config_hash,
            as_of=as_of,
        )

    def evaluate(self, strategy_id, config, as_of):
        self.calls.append((strategy_id, dict(config), as_of))
        return self.result


def approval(overrides=None):
    values = {
        "strategy_id": "manual",
        "strategy_version": "2.3.4",
        "config_hash": "config-1",
        "data_snapshot": "data-1",
        "approved_by": "terry",
    }
    values.update(overrides or {})
    return ApprovalRecord(**values)


def gateway(
    *,
    strategy_plan: PaperStrategyPlan | None = None,
    execution=None,
):
    evaluator = StaticEvaluator(strategy_plan or plan())
    return (
        PaperGateway(
            strategy_evaluator=evaluator,
            execution=execution,
        ),
        evaluator,
    )


def test_unapproved_strategy_does_not_execute_plugin_evaluation():
    paper, evaluator = gateway()
    run_at = datetime(2026, 10, 26, 14, 45, tzinfo=UTC)

    with pytest.raises(ValueError, match="approval"):
        paper.run("manual", {}, dry_run=True, run_at=run_at)

    assert len(evaluator.identity_calls) == 1
    assert evaluator.calls == []


def test_dry_run_returns_strategy_audit_without_orders():
    signals = (
        {
            "strategy_id": "manual",
            "version": "2.3.4",
            "symbol": "sh600000",
            "side": "long",
            "target_weight": 0.1,
            "confidence": 1.0,
            "valid_from": "2026-10-26T14:45:00+08:00",
            "valid_to": "2026-10-27T14:45:00+08:00",
            "industry": "Technology",
            "evidence": {"industry": "Technology"},
        },
    )
    paper, _ = gateway(strategy_plan=plan(signals=signals))
    paper.approve(approval())

    result = paper.run("manual", {}, dry_run=True)

    assert result.status == "DRY_RUN"
    assert result.orders == []
    assert result.signals == signals
    assert result.targets[0].symbol == "sh600000"
    assert result.manifest.config_hash == "config-1"


def test_paper_scheduler_records_strategy_and_data_binding():
    paper, _ = gateway()
    paper.approve(approval())
    scheduler = PaperScheduler(gateway=paper, dry_run=True)
    run_at = datetime(2026, 10, 26, 6, 45, tzinfo=UTC)

    result = scheduler.run("manual", {}, run_at=run_at)

    assert result.status == "DRY_RUN"
    assert scheduler.history == [
        {
            "strategy_id": "manual",
            "strategy_version": "2.3.4",
            "config_hash": "config-1",
            "data_snapshot": "data-1",
            "run_id": result.manifest.run_id,
            "status": "DRY_RUN",
            "run_at": "2026-10-26T14:45:00+08:00",
        }
    ]


def test_no_signal_returns_no_signal_without_calling_execution():
    execution = RecordingExecution()
    paper, _ = gateway(
        strategy_plan=plan(symbols=(), signals=()), execution=execution
    )
    paper.approve(approval())

    result = paper.run("manual", {}, dry_run=False)

    assert result.status == "NO_SIGNAL"
    assert result.orders == []
    assert execution.calls == []


def test_rejected_signal_returns_executed_without_calling_execution():
    signal = {
        "strategy_id": "manual",
        "version": "2.3.4",
        "symbol": "sh600000",
        "side": "long",
        "target_weight": 0.1,
        "confidence": 1.0,
        "valid_from": "2026-10-26T14:45:00+08:00",
        "valid_to": "2026-10-27T14:45:00+08:00",
        "industry": "Technology",
        "evidence": {"industry": "Technology"},
    }
    execution = RecordingExecution()
    paper, _ = gateway(
        strategy_plan=replace(
            plan(symbols=("sh600000",), signals=(signal,)),
            execution_symbols=(),
        ),
        execution=execution,
    )
    paper.approve(approval())

    result = paper.run("manual", {}, dry_run=False)

    assert result.status == "PAPER_EXECUTED"
    assert result.orders == []
    assert execution.calls == []


class RecordingExecution:
    def __init__(self):
        self.calls = []

    def execute(self, strategy_id, config, run_at):
        self.calls.append((strategy_id, dict(config), run_at))
        return [
            {
                "symbol": "sh600000",
                "side": "buy",
                "quantity": 100,
                "status": "FILLED",
            }
        ]


def test_execution_receives_only_accepted_target_universe():
    execution = RecordingExecution()
    strategy_plan = plan(symbols=("sh600000",))
    paper, _ = gateway(
        strategy_plan=strategy_plan, execution=execution
    )
    paper.approve(approval())
    run_at = datetime(2026, 10, 26, 6, 45, tzinfo=UTC)
    config = {
        "universe": ["sh600000", "sz000001"],
        "market": {"sz000001": {"last": "10.00"}},
    }

    result = paper.run(
        "manual",
        config,
        dry_run=False,
        run_at=run_at,
    )

    assert result.status == "PAPER_EXECUTED"
    assert result.orders[0]["status"] == "FILLED"
    assert execution.calls[0][1]["universe"] == ["sh600000"]
    assert execution.calls[0][2].isoformat() == "2026-10-26T14:45:00+08:00"


def test_execution_is_required_for_non_dry_run():
    paper, _ = gateway()
    paper.approve(approval())

    with pytest.raises(ValueError, match="execution"):
        paper.run("manual", {}, dry_run=False)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("strategy_version", "stale-version"),
        ("data_snapshot", "stale-data"),
        ("config_hash", "stale-config"),
    ],
)
def test_approval_binding_mismatch_fails_closed(field, value):
    paper, _ = gateway()
    paper.approve(approval({field: value}))

    with pytest.raises(ValueError, match="approval"):
        paper.run("manual", {}, dry_run=True)


def test_scheduler_run_at_is_used_for_non_dry_run():
    execution = RecordingExecution()
    paper, _ = gateway(execution=execution)
    paper.approve(approval())
    scheduler = PaperScheduler(gateway=paper, dry_run=False)
    run_at = datetime(2026, 10, 26, 6, 45, tzinfo=UTC)

    scheduler.run("manual", {}, run_at=run_at)

    assert execution.calls[0][2].isoformat() == "2026-10-26T14:45:00+08:00"


def test_executor_cannot_return_orders_outside_accepted_targets():
    class OutOfScopeExecution:
        def execute(self, strategy_id, config, run_at):
            return [
                {
                    "symbol": "sz000001",
                    "side": "buy",
                    "quantity": 100,
                    "status": "FILLED",
                }
            ]

    paper, _ = gateway(execution=OutOfScopeExecution())
    paper.approve(approval())

    with pytest.raises(ValueError, match="outside accepted targets"):
        paper.run("manual", {}, dry_run=False)


def test_executor_cannot_return_non_mapping_orders():
    class MalformedExecution:
        def execute(self, strategy_id, config, run_at):
            return [None]  # type: ignore[list-item]

    paper, _ = gateway(execution=MalformedExecution())
    paper.approve(approval())

    with pytest.raises(ValueError, match="non-object order"):
        paper.run("manual", {}, dry_run=False)


def test_sell_order_and_non_decimal_execution_config_fail_closed():
    class SellExecution:
        def execute(self, strategy_id, config, run_at):
            return [
                {
                    "symbol": "sh600000",
                    "side": "sell",
                    "quantity": 100,
                    "status": "FILLED",
                }
            ]

    paper, _ = gateway(execution=SellExecution())
    paper.approve(approval())

    with pytest.raises(ValueError, match="direction"):
        paper.run("manual", {}, dry_run=False)

    from quant_agent.agents.paper import PaperExecutionConfig

    with pytest.raises(ValueError, match="Decimal"):
        PaperExecutionConfig(initial_cash="100000")


def test_evaluator_identity_must_match_requested_strategy():
    class WrongIdentityEvaluator(StaticEvaluator):
        def identity(self, strategy_id, config, as_of):
            return PaperStrategyIdentity(
                strategy_id="foreign",
                strategy_version=self.result.strategy_version,
                config_hash=self.result.config_hash,
                as_of=as_of,
            )

    evaluator = WrongIdentityEvaluator(plan())
    paper = PaperGateway(strategy_evaluator=evaluator)
    paper.approve(approval())

    with pytest.raises(ValueError, match="binding"):
        paper.run("manual", {}, dry_run=True)


def test_executor_rejects_non_string_status():
    class InvalidStatusExecution:
        def execute(self, strategy_id, config, run_at):
            return [
                {
                    "symbol": "sh600000",
                    "side": "buy",
                    "quantity": 100,
                    "status": [],
                }
            ]

    paper, _ = gateway(execution=InvalidStatusExecution())
    paper.approve(approval())

    with pytest.raises(ValueError, match="status"):
        paper.run("manual", {}, dry_run=False)
