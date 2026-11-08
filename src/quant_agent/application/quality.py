"""Quality summaries shared by strategy backtest and paper pipelines."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from quant_agent.application.portfolio import RiskDecision
from quant_agent.ports.market_data import QualityEvent


@dataclass(frozen=True, slots=True)
class QualitySummary:
    warn_count: int
    block_count: int
    blocked_strategies: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "warn_count": self.warn_count,
            "block_count": self.block_count,
            "blocked_strategies": list(self.blocked_strategies),
        }


def summarize_quality(
    events: Iterable[QualityEvent],
    blocked_strategies: Iterable[str],
) -> QualitySummary:
    items = tuple(events)
    return QualitySummary(
        warn_count=sum(event.level == "warn" for event in items),
        block_count=sum(event.level == "block" for event in items),
        blocked_strategies=tuple(sorted(set(blocked_strategies))),
    )


def quality_event_dict(event: QualityEvent) -> dict[str, object]:
    row: dict[str, object] = {
        "level": event.level,
        "reason_code": event.reason_code,
        "symbol": event.symbol,
        "as_of": event.as_of.isoformat(),
        "message": event.message,
    }
    if event.strategy_id is not None:
        row["strategy_id"] = event.strategy_id
    return row


def blocked_quality_decisions(
    events: Iterable[QualityEvent],
    strategy_versions: Mapping[str, str],
    existing: Iterable[RiskDecision] = (),
) -> tuple[RiskDecision, ...]:
    seen = {
        (decision.strategy_id, decision.symbol)
        for decision in existing
        if decision.strategy_id is not None
        and decision.reason_code == "STRATEGY_BLOCKED"
    }
    decisions: list[RiskDecision] = []
    for event in events:
        if event.level != "block" or not event.strategy_id:
            continue
        key = (event.strategy_id, event.symbol)
        if key in seen:
            continue
        seen.add(key)
        decisions.append(
            RiskDecision(
                symbol=event.symbol,
                status="rejected",
                net_weight=0.0,
                reason_code="STRATEGY_BLOCKED",
                strategy_id=event.strategy_id,
                version=strategy_versions.get(event.strategy_id),
            )
        )
    return tuple(decisions)
