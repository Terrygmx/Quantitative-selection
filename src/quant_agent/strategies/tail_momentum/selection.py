from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from quant_agent.strategies.tail_momentum.scoring import (
    FactorScore,
    StockInput,
    TailMomentumMarket,
    build_daily_series,
    compute_daily_indicators,
    compute_intraday,
    compute_volume_surge,
    score_market_env,
    score_stock,
)


BEAR_THRESHOLD = 80.0
NORMAL_THRESHOLD = 70.0
MIN_AFTERNOON_SCORE = 12.0
MIN_VOLUME_SURGE = 1.0
MIN_AMOUNT_YI = 1.0


@dataclass(frozen=True, slots=True)
class CandidateResult:
    symbol: str
    name: str
    score: FactorScore
    day_chg_pct: float
    morning_return: float
    afternoon_1400: float
    volume_surge: float | None
    atr: float | None
    passed: bool
    miss_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExcludedResult:
    symbol: str
    reason_code: str
    message: str


@dataclass(frozen=True, slots=True)
class TailMomentumSelection:
    date: date
    snapshot: str
    environment_label: str
    environment_points: float
    environment_detail: Mapping[str, object]
    threshold: float
    results: tuple[CandidateResult, ...]
    signals: tuple[CandidateResult, ...]
    excluded: tuple[ExcludedResult, ...] = ()

    def to_signal_document(self) -> dict[str, object]:
        return {
            "date": self.date.isoformat(),
            "snapshot": self.snapshot,
            "env_label": self.environment_label,
            "env_points": int(self.environment_points),
            "threshold": int(self.threshold),
            "candidates": [
                {
                    "code": result.symbol,
                    "name": result.name,
                    "total": result.score.total,
                    "snapshot_close": result.score.snapshot_close,
                    "day_chg_pct": result.day_chg_pct,
                }
                for result in self.signals
            ],
            "excluded_count": len(self.excluded),
        }


def _exclusion_reason(stock: StockInput) -> ExcludedResult | None:
    name = stock.quote.name.upper()
    if "ST" in name or "*" in name:
        return ExcludedResult(stock.quote.symbol, "ST", "ST or delisting stock")
    if not stock.daily:
        return ExcludedResult(stock.quote.symbol, "INSUFFICIENT_HISTORY", "daily history is empty")
    if len(stock.daily) < 25:
        return ExcludedResult(
            stock.quote.symbol,
            "INSUFFICIENT_HISTORY",
            "at least 25 daily bars are required",
        )
    if not stock.minute:
        return ExcludedResult(stock.quote.symbol, "NO_MINUTE_DATA", "minute data is empty")
    return None


def _evaluate_stock(
    stock: StockInput,
    snapshot: str,
    index_changes: Mapping[str, float],
    environment_points: float,
    threshold: float,
) -> CandidateResult:
    intraday = compute_intraday(
        stock.minute, snapshot, stock.quote.previous_close, stock.quote.open
    )
    if intraday is None:
        raise ValueError(f"{stock.quote.symbol} has no visible minute data")
    daily = compute_daily_indicators(build_daily_series(stock.daily, intraday.cur))
    volume_surge = compute_volume_surge(intraday, daily, snapshot)
    score = score_stock(
        stock.quote,
        intraday,
        daily,
        volume_surge,
        index_changes,
        environment_points,
    )
    hs300_relative = score.relative_strength_detail.get("rs_hs300")
    zz1000_relative = score.relative_strength_detail.get("rs_zz1000")
    relative_strength_positive = (
        isinstance(hs300_relative, (int, float)) and hs300_relative > 0
    ) or (
        isinstance(zz1000_relative, (int, float)) and zz1000_relative > 0
    )
    near_limit_up = bool(score.risk_detail.get("near_limitup", False))
    checks = (
        (score.total >= threshold, "TOTAL_BELOW_THRESHOLD"),
        (
            score.afternoon >= MIN_AFTERNOON_SCORE,
            "AFTERNOON_MOMENTUM_BELOW_MINIMUM",
        ),
        (
            intraday.day_chg > 0
            and (volume_surge is None or volume_surge >= MIN_VOLUME_SURGE),
            "PRICE_VOLUME_DIRECTION_MISMATCH",
        ),
        (relative_strength_positive, "RELATIVE_STRENGTH_NOT_POSITIVE"),
        (
            (intraday.amount_cur or 0) / 1e8 >= MIN_AMOUNT_YI,
            "LIQUIDITY_BELOW_MINIMUM",
        ),
        (not near_limit_up, "NEAR_LIMIT_UP"),
    )
    misses = tuple(code for passed, code in checks if not passed)
    return CandidateResult(
        symbol=stock.quote.symbol,
        name=stock.quote.name,
        score=score,
        day_chg_pct=intraday.day_chg * 100,
        morning_return=intraday.morn_ret,
        afternoon_1400=intraday.aft_1400,
        volume_surge=volume_surge,
        atr=daily.atr,
        passed=not misses,
        miss_reasons=misses,
    )


def select_tail_momentum(
    market: TailMomentumMarket, snapshot: str
) -> TailMomentumSelection:
    index_changes = market.index_changes(snapshot)
    label, points, detail = score_market_env(index_changes, market.breadth)
    threshold = BEAR_THRESHOLD if label == "Bear" else NORMAL_THRESHOLD
    excluded = tuple(
        result
        for stock in market.stocks
        if (result := _exclusion_reason(stock)) is not None
    )
    results = tuple(
        _evaluate_stock(stock, snapshot, index_changes, points, threshold)
        for stock in market.stocks
        if _exclusion_reason(stock) is None
    )
    passed = tuple(sorted(
        (result for result in results if result.passed),
        key=lambda result: -result.score.total,
    ))
    return TailMomentumSelection(
        date=market.date,
        snapshot=snapshot,
        environment_label=label,
        environment_points=points,
        environment_detail=detail,
        threshold=threshold,
        results=results,
        signals=passed,
        excluded=excluded,
    )
