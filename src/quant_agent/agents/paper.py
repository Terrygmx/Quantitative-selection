from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

from quant_agent.domain.clock import Clock, SystemClock


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    strategy_id: str
    config_hash: str
    approved_by: str


@dataclass(frozen=True, slots=True)
class PaperRunResult:
    status: str
    orders: list[Mapping[str, object]]


class PaperExecution(Protocol):
    def execute(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        run_at: datetime,
    ) -> list[Mapping[str, object]]: ...


class PaperGateway:
    def __init__(
        self,
        clock: Clock = SystemClock(),
        execution: PaperExecution | None = None,
    ) -> None:
        self.approvals: dict[tuple[str, str], ApprovalRecord] = {}
        self.clock = clock
        self.execution = execution

    def approve(self, approval: ApprovalRecord) -> None:
        self.approvals[(approval.strategy_id, approval.config_hash)] = approval

    def run(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        dry_run: bool,
        run_at: datetime | None = None,
    ) -> PaperRunResult:
        key = (strategy_id, str(config.get("config_hash", "")))
        if key not in self.approvals:
            raise ValueError("strategy configuration approval is required")
        if dry_run:
            return PaperRunResult(status="DRY_RUN", orders=[])
        if self.execution is None:
            raise ValueError("paper execution is not configured")
        occurred_at = run_at if run_at is not None else self.clock.now()
        orders = self.execution.execute(strategy_id, config, occurred_at)
        return PaperRunResult(status="PAPER_EXECUTED", orders=list(orders))


class PaperScheduler:
    def __init__(self, gateway: PaperGateway, dry_run: bool = True):
        self.gateway = gateway
        self.dry_run = dry_run
        self.history: list[dict[str, str]] = []

    def run(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        run_at: datetime | None = None,
    ) -> PaperRunResult:
        result = self.gateway.run(
            strategy_id,
            config,
            dry_run=self.dry_run,
            run_at=run_at,
        )
        self.history.append(
            {
                "strategy_id": strategy_id,
                "config_hash": str(config.get("config_hash", "")),
                "status": result.status,
                "run_at": run_at.isoformat() if run_at else "",
            }
        )
        return result
