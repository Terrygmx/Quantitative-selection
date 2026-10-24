from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    strategy_id: str
    config_hash: str
    approved_by: str


@dataclass(frozen=True, slots=True)
class PaperRunResult:
    status: str
    orders: list[Mapping[str, object]]


class PaperGateway:
    def __init__(self) -> None:
        self.approvals: dict[tuple[str, str], ApprovalRecord] = {}

    def approve(self, approval: ApprovalRecord) -> None:
        self.approvals[(approval.strategy_id, approval.config_hash)] = approval

    def run(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        dry_run: bool,
    ) -> PaperRunResult:
        key = (strategy_id, str(config.get("config_hash", "")))
        if key not in self.approvals:
            raise ValueError("strategy configuration approval is required")
        if not dry_run:
            raise ValueError("live paper execution is not implemented")
        return PaperRunResult(status="DRY_RUN", orders=[])
