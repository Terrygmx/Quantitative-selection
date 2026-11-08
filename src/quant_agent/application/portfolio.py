from __future__ import annotations

from collections.abc import Sequence
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from math import copysign
from typing import Any, Mapping, TypedDict

from quant_agent.domain.models import Signal


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
class CorrelationBudget:
    max_correlation: float
    covariances: Mapping[tuple[str, str], float]

    def correlation(self, left: str, right: str) -> float | None:
        pair_variance = self.covariances.get((left, left))
        other_variance = self.covariances.get((right, right))
        covariance = self.covariances.get((left, right), self.covariances.get((right, left)))
        if pair_variance is None or other_variance is None or covariance is None:
            return None
        denominator = (pair_variance * other_variance) ** 0.5
        return covariance / denominator if denominator else None


@dataclass(frozen=True, slots=True)
class PortfolioRiskConfig:
    constraints: tuple[object, ...] = field(default_factory=tuple)


class ComposerSignal(TypedDict):
    strategy_id: str
    version: str
    symbol: str
    side: str
    target_weight: float
    confidence: float
    valid_from: str
    valid_to: str
    industry: str
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TargetPosition:
    symbol: str
    net_weight: float
    contributions: Mapping[str, float]
    industry: str
    strategy_versions: Mapping[str, str] = field(default_factory=dict)
    evidence: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    status: str = "accepted"
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class RiskDecision:
    symbol: str
    status: str
    net_weight: float
    reason_code: str | None = None
    strategy_id: str | None = None
    version: str | None = None


@dataclass(frozen=True, slots=True)
class SignalAdapterResult:
    signals: tuple[ComposerSignal, ...]
    decisions: tuple[RiskDecision, ...]


class SignalAdapter:
    """Convert domain signals into composer input without losing audit fields."""

    def adapt(
        self,
        signals: Sequence[Signal],
        *,
        as_of: datetime,
    ) -> SignalAdapterResult:
        validation_reasons: list[str | None] = []
        industries: list[str] = []
        candidate_keys: list[tuple[str, str]] = []

        for signal in signals:
            reason = self._validation_rejection(signal, as_of=as_of)
            validation_reasons.append(reason)
            industries.append(
                str(signal.evidence["industry"]).strip()
                if reason is None
                else ""
            )
            candidate_keys.append((signal.strategy_id, signal.symbol))

        key_counts = Counter(candidate_keys)
        industries_by_symbol: dict[str, set[str]] = {}
        for signal, industry in zip(signals, industries, strict=True):
            if industry:
                industries_by_symbol.setdefault(signal.symbol, set()).add(industry)
        industry_conflicts = {
            symbol
            for symbol, values in industries_by_symbol.items()
            if len(values) > 1
        }
        passed: list[ComposerSignal] = []
        decisions: list[RiskDecision] = []
        for signal, reason, industry, key in zip(
            signals,
            validation_reasons,
            industries,
            candidate_keys,
            strict=True,
        ):
            if reason is None and signal.symbol in industry_conflicts:
                reason = "INDUSTRY_CONFLICT"
            elif reason is None and key_counts[key] > 1:
                reason = "DUPLICATE_STRATEGY_SIGNAL"
            if reason is None:
                row: ComposerSignal = {
                    "strategy_id": signal.strategy_id,
                    "version": signal.version,
                    "symbol": signal.symbol,
                    "side": signal.side,
                    "target_weight": signal.target_weight,
                    "confidence": signal.confidence,
                    "valid_from": signal.valid_from.isoformat(),
                    "valid_to": signal.valid_to.isoformat(),
                    "industry": industry,
                    "evidence": dict(signal.evidence),
                }
                passed.append(row)
                continue

            decisions.append(
                RiskDecision(
                    symbol=signal.symbol,
                    status="rejected",
                    net_weight=0.0,
                    reason_code=reason,
                    strategy_id=signal.strategy_id,
                    version=signal.version,
                )
            )

        return SignalAdapterResult(
            signals=tuple(passed),
            decisions=tuple(decisions),
        )

    @staticmethod
    def _validation_rejection(signal: Signal, *, as_of: datetime) -> str | None:
        if not signal.valid_from <= as_of < signal.valid_to:
            return (
                "SIGNAL_EXPIRED"
                if as_of >= signal.valid_to
                else "SIGNAL_NOT_YET_VALID"
            )
        industry = signal.evidence.get("industry")
        if not isinstance(industry, str) or not industry.strip():
            return "INDUSTRY_MISSING"
        return None


@dataclass(frozen=True, slots=True)
class CompositionResult:
    targets: tuple[TargetPosition, ...]
    decisions: tuple[RiskDecision, ...] = field(default_factory=tuple)


class SignalComposer:
    def __init__(self, config: PortfolioRiskConfig):
        self.config = config

    def compose(
        self,
        signals: list[Mapping[str, object]],
        blocked_strategies: set[str] | None = None,
        *,
        as_of: datetime | None = None,
    ) -> CompositionResult:
        blocked = blocked_strategies or set()
        passed: list[Mapping[str, object]] = []
        blocked_decisions: list[RiskDecision] = []
        for signal in signals:
            if str(signal["strategy_id"]) in blocked:
                blocked_decisions.append(
                    RiskDecision(
                        symbol=str(signal["symbol"]),
                        status="rejected",
                        net_weight=0.0,
                        reason_code="STRATEGY_BLOCKED",
                        strategy_id=str(signal["strategy_id"]),
                        version=(
                            raw_version
                            if isinstance(
                                raw_version := signal.get("version"), str
                            )
                            and raw_version.strip()
                            else None
                        ),
                    )
                )
                continue
            passed.append(signal)
        signals = passed
        as_of = as_of or max(
            (datetime.fromisoformat(str(signal["valid_from"])) for signal in signals),
            default=None,
        )
        by_symbol: dict[str, dict[str, float]] = {}
        strategy_versions: dict[str, dict[str, str]] = {}
        evidence: dict[str, dict[str, Mapping[str, Any]]] = {}
        industries: dict[str, str] = {}
        for signal in signals:
            symbol = str(signal["symbol"])
            strategy_id = str(signal["strategy_id"])
            weight = signal["target_weight"]
            if not isinstance(weight, (int, float, str)):
                raise ValueError(f"{symbol} target_weight must be numeric")
            by_symbol.setdefault(symbol, {})[strategy_id] = float(weight)
            if "version" in signal:
                raw_version = signal["version"]
                if isinstance(raw_version, str) and raw_version.strip():
                    strategy_versions.setdefault(symbol, {})[strategy_id] = raw_version
            if "evidence" in signal:
                raw_evidence = signal["evidence"]
                if isinstance(raw_evidence, Mapping):
                    evidence.setdefault(symbol, {})[strategy_id] = dict(raw_evidence)
                else:
                    raise ValueError(f"{symbol} evidence must be a mapping")
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
                    strategy_versions=strategy_versions.get(symbol, {}),
                    evidence=evidence.get(symbol, {}),
                )
            )

        processed: list[TargetPosition] = []
        total_weight = sum(target.net_weight for target in targets)
        correlation_rejects = self._correlation_rejections(by_symbol)
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
                        strategy_versions=target.strategy_versions,
                        evidence=target.evidence,
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
                elif isinstance(constraint, CorrelationBudget) and target.symbol in correlation_rejects:
                    status, reason = "rejected", "CORRELATION_BUDGET"
            processed.append(
                TargetPosition(
                    symbol=target.symbol,
                    net_weight=target.net_weight,
                    contributions=target.contributions,
                    industry=target.industry,
                    strategy_versions=target.strategy_versions,
                    evidence=target.evidence,
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
        return CompositionResult(
            targets=tuple(processed),
            decisions=tuple(decisions) + tuple(blocked_decisions),
        )

    def compose_domain(
        self,
        signals: Sequence[Signal],
        *,
        as_of: datetime,
        blocked_strategies: set[str] | None = None,
    ) -> CompositionResult:
        adapted = SignalAdapter().adapt(signals, as_of=as_of)
        result = self.compose(
            list(adapted.signals), blocked_strategies, as_of=as_of
        )
        return CompositionResult(
            targets=result.targets,
            decisions=adapted.decisions + result.decisions,
        )

    def _correlation_rejections(
        self, by_symbol: Mapping[str, Mapping[str, float]]
    ) -> set[str]:
        constraints = [
            item for item in self.config.constraints if isinstance(item, CorrelationBudget)
        ]
        rejected: set[str] = set()
        for constraint in constraints:
            symbols = list(by_symbol)
            for index, left in enumerate(symbols):
                for right in symbols[index + 1 :]:
                    left_strategies = list(by_symbol[left])
                    right_strategies = list(by_symbol[right])
                    correlations = [
                        value
                        for left_strategy in left_strategies
                        for right_strategy in right_strategies
                        if (
                            value := constraint.correlation(left_strategy, right_strategy)
                        )
                        is not None
                    ]
                    if correlations and max(correlations) > constraint.max_correlation:
                        rejected.update((left, right))
        return rejected
