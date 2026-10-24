from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from math import copysign
from typing import Mapping


@dataclass(frozen=True, slots=True)
class SinglePositionConstraint:
    max_weight: float


@dataclass(frozen=True, slots=True)
class IndustryConstraint:
    max_weight: float


@dataclass(frozen=True, slots=True)
class LiquidityConstraint:
    max_participation: float
    daily_volume: int
    portfolio_value: float


@dataclass(frozen=True, slots=True)
class DrawdownFuse:
    max_drawdown: float
    current_drawdown: float


@dataclass(frozen=True, slots=True)
class BlacklistConstraint:
    symbols: frozenset[str] | set[str]
    effective_from: str | None = None


@dataclass(frozen=True, slots=True)
class TotalPositionConstraint:
    max_weight: float


@dataclass(frozen=True, slots=True)
class PortfolioRiskConfig:
    constraints: tuple[object, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class TargetPosition:
    symbol: str
    net_weight: float
    contributions: Mapping[str, float]
    industry: str
    status: str = "accepted"
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class RiskDecision:
    symbol: str
    status: str
    net_weight: float
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class CompositionResult:
    targets: tuple[TargetPosition, ...]
    decisions: tuple[RiskDecision, ...] = field(default_factory=tuple)


class SignalComposer:
    def __init__(self, config: PortfolioRiskConfig):
        self.config = config

    def compose(self, signals: list[Mapping[str, object]]) -> CompositionResult:
        as_of = max(
            (datetime.fromisoformat(str(signal["valid_from"])) for signal in signals),
            default=None,
        )
        by_symbol: dict[str, dict[str, float]] = {}
        industries: dict[str, str] = {}
        for signal in signals:
            symbol = str(signal["symbol"])
            by_symbol.setdefault(symbol, {})[str(signal["strategy_id"])] = float(
                signal["target_weight"]
            )
            industries[symbol] = str(signal["industry"])

        targets: list[TargetPosition] = []
        industry_weights: dict[str, float] = {}
        for symbol, contributions in by_symbol.items():
            net_weight = sum(contributions.values())
            industry = industries[symbol]
            industry_weights[industry] = (
                industry_weights.get(industry, 0.0) + net_weight
            )
            targets.append(
                TargetPosition(
                    symbol=symbol,
                    net_weight=net_weight,
                    contributions=contributions,
                    industry=industry,
                )
            )

        processed: list[TargetPosition] = []
        total_weight = sum(target.net_weight for target in targets)
        for target in targets:
            status, reason = "accepted", None
            for constraint in self.config.constraints:
                if isinstance(constraint, SinglePositionConstraint) and abs(
                    target.net_weight
                ) > constraint.max_weight:
                    status, reason = (
                        "reduced",
                        "SINGLE_POSITION_LIMIT",
                    )
                    target = TargetPosition(
                        symbol=target.symbol,
                        net_weight=float(
                            copysign(constraint.max_weight, target.net_weight)
                        ),
                        contributions=target.contributions,
                        industry=target.industry,
                        status=status,
                        reason_code=reason,
                    )
                elif isinstance(constraint, IndustryConstraint) and abs(
                    industry_weights[target.industry]
                ) > constraint.max_weight:
                    status, reason = "rejected", "INDUSTRY_LIMIT"
                elif isinstance(constraint, LiquidityConstraint):
                    target_amount = abs(target.net_weight) * constraint.portfolio_value
                    capacity = constraint.daily_volume * constraint.max_participation
                    if target_amount > capacity:
                        status, reason = "rejected", "LIQUIDITY_LIMIT"
                elif isinstance(constraint, DrawdownFuse) and (
                    constraint.current_drawdown >= constraint.max_drawdown
                ):
                    status, reason = "rejected", "DRAWDOWN_FUSE"
                elif isinstance(constraint, BlacklistConstraint):
                    if (
                        constraint.effective_from
                        and as_of
                        and as_of.date() < date.fromisoformat(constraint.effective_from)
                    ):
                        continue
                    if target.symbol in constraint.symbols:
                        status, reason = "rejected", "BLACKLIST"
                elif isinstance(constraint, TotalPositionConstraint) and abs(
                    total_weight
                ) > constraint.max_weight:
                    status, reason = "rejected", "TOTAL_POSITION_LIMIT"
            processed.append(
                TargetPosition(
                    symbol=target.symbol,
                    net_weight=target.net_weight,
                    contributions=target.contributions,
                    industry=target.industry,
                    status=status,
                    reason_code=reason,
                )
            )
        decisions = tuple(
            RiskDecision(
                symbol=target.symbol,
                status=target.status,
                net_weight=target.net_weight,
                reason_code=target.reason_code,
            )
            for target in processed
        )
        return CompositionResult(targets=tuple(processed), decisions=decisions)
