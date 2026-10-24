from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Mapping, Sequence


TOTAL_TRADING_MIN = 240
MIN_POSITIVE_SCORE = 0.0
MAX_TREND_SCORE = 20.0
MAX_AFTERNOON_SCORE = 25.0
MAX_VOLUME_SCORE = 20.0
MAX_RELATIVE_STRENGTH_SCORE = 15.0
MAX_RISK_SCORE = 10.0


@dataclass(frozen=True, slots=True)
class MinutePoint:
    time: str
    price: float
    volume: float
    amount: float


@dataclass(frozen=True, slots=True)
class DailyBar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float


@dataclass(frozen=True, slots=True)
class QuoteSnapshot:
    symbol: str
    name: str
    previous_close: float
    open: float
    price_ceiling: float | None = None
    price_floor: float | None = None


@dataclass(frozen=True, slots=True)
class StockInput:
    quote: QuoteSnapshot
    daily: tuple[DailyBar, ...]
    minute: tuple[MinutePoint, ...]


@dataclass(frozen=True, slots=True)
class TailMomentumMarket:
    date: date
    stocks: tuple[StockInput, ...]
    indices: Mapping[str, tuple[float, tuple[MinutePoint, ...]]]
    breadth: Mapping[str, float | None] | None

    def index_changes(self, snapshot: str) -> dict[str, float]:
        changes = {}
        for key, (previous_close, points) in self.indices.items():
            visible = slice_minute_up_to(points, snapshot)
            if visible and previous_close:
                changes[key] = (visible[-1].price - previous_close) / previous_close
        return changes


@dataclass(frozen=True, slots=True)
class FactorScore:
    trend: float
    afternoon: float
    volume: float
    rs: float
    env: float
    risk: float
    total: float
    snapshot_close: float
    afternoon_detail: Mapping[str, object]
    volume_detail: Mapping[str, object]
    relative_strength_detail: Mapping[str, object]
    risk_detail: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class IntradayIndicators:
    cur: float
    p_open: float
    p_1130: float
    p_1300: float
    p_1400: float
    p_1430: float
    intraday_high: float
    intraday_low: float
    day_chg: float
    open_to_cur: float
    morn_ret: float
    aft_1300: float
    aft_1400: float
    aft_1430: float
    afternoon_ret_total: float
    break_morning_high: bool
    new_high_afternoon: bool
    vol_cur: float
    morn_vol: float
    aft_vol: float
    vol_pace_ratio: float
    amount_cur: float


@dataclass(frozen=True, slots=True)
class DailyIndicators:
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None
    r1: float | None
    r2: float | None
    r3: float | None
    r5: float | None
    r10: float | None
    r20: float | None
    atr: float | None
    ann_vol: float | None
    ma5_slope: float | None
    recent_up_streak: int
    avg_daily_volume: float
    snapshot_close: float | None = None


def clamp(value: float, low: float = MIN_POSITIVE_SCORE, high: float = 10.0) -> float:
    return max(low, min(high, value))


def hhmm_to_min(value: str) -> int:
    hour, minute = int(value[:2]), int(value[2:])
    if hour < 12:
        return (hour - 9) * 60 + minute - 30
    return 120 + (hour - 13) * 60 + minute


def elapsed_fraction(snapshot: str) -> float:
    return min(max(hhmm_to_min(snapshot), 1), TOTAL_TRADING_MIN) / TOTAL_TRADING_MIN


def slice_minute_up_to(
    rows: Sequence[MinutePoint], snapshot: str
) -> tuple[MinutePoint, ...]:
    visible = tuple(row for row in rows if row.time <= snapshot)
    if visible:
        return visible
    return tuple(rows[-1:]) if rows else ()


def _price_at(rows: Sequence[MinutePoint], at: str) -> float | None:
    visible = [row.price for row in rows if row.time <= at]
    return visible[-1] if visible else None


def compute_intraday(
    rows: Sequence[MinutePoint],
    snapshot: str,
    previous_close: float,
    open_price: float,
) -> IntradayIndicators | None:
    visible = slice_minute_up_to(rows, snapshot)
    if not visible:
        return None
    current = visible[-1].price
    p_open = open_price or visible[0].price
    p_1130 = _price_at(rows, "1130") or p_open
    p_1300 = _price_at(rows, "1300") or p_1130
    p_1330 = _price_at(rows, "1330") or p_1300
    p_1400 = _price_at(rows, "1400") or p_1330
    p_1430 = _price_at(rows, "1430") or current
    prices = [row.price for row in visible]
    intraday_high, intraday_low = max(prices), min(prices)
    afternoon_prices = [row.price for row in visible if row.time >= "1300"]
    day_chg = (current - previous_close) / previous_close if previous_close else 0.0
    morning_volume = next(
        (row.volume for row in visible if row.time <= "1130"), 0.0
    )
    volume_at_1300 = next(
        (row.volume for row in visible if row.time <= "1300"), morning_volume
    )
    afternoon_volume = visible[-1].volume - volume_at_1300
    afternoon_minutes = max(hhmm_to_min(snapshot) - 120, 1)
    morning_pace = morning_volume / 120.0
    afternoon_pace = afternoon_volume / afternoon_minutes
    pace_ratio = (
        afternoon_pace / morning_pace
        if morning_pace > 0
        else (2.0 if afternoon_pace > 0 else 0.0)
    )
    return IntradayIndicators(
        cur=current,
        p_open=p_open,
        p_1130=p_1130,
        p_1300=p_1300,
        p_1400=p_1400,
        p_1430=p_1430,
        intraday_high=intraday_high,
        intraday_low=intraday_low,
        day_chg=day_chg,
        open_to_cur=(current - p_open) / p_open if p_open else 0.0,
        morn_ret=(p_1130 - p_open) / p_open if p_open else 0.0,
        aft_1300=(current - p_1300) / p_1300 if p_1300 else 0.0,
        aft_1400=(current - p_1400) / p_1400 if p_1400 else 0.0,
        aft_1430=(current - p_1430) / p_1430 if p_1430 else 0.0,
        afternoon_ret_total=(current - p_1300) / p_1300 if p_1300 else 0.0,
        break_morning_high=current > intraday_high * 0.999,
        new_high_afternoon=current >= max(afternoon_prices) if afternoon_prices else False,
        vol_cur=visible[-1].volume,
        morn_vol=morning_volume,
        aft_vol=afternoon_volume,
        vol_pace_ratio=pace_ratio,
        amount_cur=visible[-1].amount,
    )


def build_daily_series(
    bars: Sequence[DailyBar], snapshot_close: float
) -> tuple[DailyBar, ...]:
    if not bars:
        return ()
    latest = bars[-1]
    return (*bars[:-1], DailyBar(
        date=latest.date,
        open=latest.open,
        high=latest.high,
        low=latest.low,
        close=snapshot_close,
        volume=latest.volume,
        amount=latest.amount,
    ))


def compute_daily_indicators(bars: Sequence[DailyBar]) -> DailyIndicators:
    closes = [bar.close for bar in bars]
    count = len(closes)

    def moving_average(window: int) -> float | None:
        return sum(closes[-window:]) / window if count >= window else None

    def return_back(days: int) -> float | None:
        if count - 1 - days < 0:
            return None
        base = closes[count - 1 - days]
        return closes[-1] / base - 1 if base else None

    ma5, ma10, ma20, ma60 = (
        moving_average(5),
        moving_average(10),
        moving_average(20),
        moving_average(60),
    )
    atr = None
    if count >= 15:
        true_ranges = [
            max(
                bars[index].high - bars[index].low,
                abs(bars[index].high - bars[index - 1].close),
                abs(bars[index].low - bars[index - 1].close),
            )
            for index in range(1, count)
        ]
        atr = sum(true_ranges[-14:]) / 14
    annualized_volatility = None
    if count >= 22:
        returns = [closes[index] / closes[index - 1] - 1 for index in range(1, count)]
        recent = returns[-20:]
        mean = sum(recent) / len(recent)
        variance = sum((value - mean) ** 2 for value in recent) / len(recent)
        annualized_volatility = variance**0.5 * (252**0.5)
    ma5_slope = None
    if count >= 6 and ma5 is not None:
        previous_ma5 = sum(closes[-6:-1]) / 5
        ma5_slope = ma5 / previous_ma5 - 1 if previous_ma5 else 0.0
    recent_up_streak = 0
    if count >= 4:
        # Preserve the legacy range end so exact fixture equivalence is auditable.
        for index in range(count - 1, max(count - 5, 0), -1):
            if closes[index] >= closes[index - 1]:
                recent_up_streak += 1
            else:
                break
    average_volume = (
        sum(bar.volume for bar in bars[:-1]) / max(count - 1, 1)
        if count > 1
        else (bars[0].volume if bars else 0.0)
    )
    return DailyIndicators(
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        ma60=ma60,
        r1=return_back(1),
        r2=return_back(2),
        r3=return_back(3),
        r5=return_back(5),
        r10=return_back(10),
        r20=return_back(20),
        atr=atr,
        ann_vol=annualized_volatility,
        ma5_slope=ma5_slope,
        recent_up_streak=recent_up_streak,
        avg_daily_volume=average_volume,
    )


def compute_volume_surge(
    intraday: IntradayIndicators | None,
    daily: DailyIndicators,
    snapshot: str,
) -> float | None:
    if intraday is None:
        return None
    expected = daily.avg_daily_volume * elapsed_fraction(snapshot)
    return intraday.vol_cur / expected if expected > 0 else None


def score_trend(daily: DailyIndicators) -> float:
    price = daily.snapshot_close
    if price is None:
        return 0.0
    score = 0.0
    if daily.ma5 is not None and price >= daily.ma5:
        score += 3
    if daily.ma10 is not None and price >= daily.ma10:
        score += 3
    if daily.ma20 is not None and price >= daily.ma20:
        score += 3
    if (
        daily.ma5 is not None
        and daily.ma10 is not None
        and daily.ma20 is not None
        and daily.ma5 > daily.ma10 > daily.ma20
    ):
        score += 4
    if daily.ma20 is not None and daily.ma60 is not None and daily.ma20 > daily.ma60:
        score += 3
    if daily.ma5_slope is not None and daily.ma5_slope > 0:
        score += 4
    return clamp(score, 0.0, MAX_TREND_SCORE)


def score_afternoon(
    intraday: IntradayIndicators | None,
) -> tuple[float, dict[str, object]]:
    if intraday is None:
        return 0.0, {}
    score = 0.0
    if intraday.aft_1400 > 0.003:
        score += 4
    elif intraday.aft_1400 > 0:
        score += 2
    elif intraday.aft_1400 >= -0.003:
        score += 1
    if intraday.afternoon_ret_total > intraday.morn_ret + 0.002:
        score += 5
    elif intraday.afternoon_ret_total > intraday.morn_ret:
        score += 3
    if intraday.break_morning_high:
        score += 5
    if intraday.vol_pace_ratio >= 1.1:
        score += 4
    elif intraday.vol_pace_ratio >= 1.0:
        score += 2
    if intraday.aft_1300 > 0 and intraday.aft_1400 >= 0:
        score += 4
    return clamp(score, 0.0, MAX_AFTERNOON_SCORE), {
        "aft_1400": intraday.aft_1400,
        "aft_vs_morn": intraday.afternoon_ret_total - intraday.morn_ret,
        "break_high": intraday.break_morning_high,
        "vol_pace_ratio": intraday.vol_pace_ratio,
        "aft_1300": intraday.aft_1300,
    }


def score_volume(
    intraday: IntradayIndicators | None, vol_surge: float | None
) -> tuple[float, dict[str, object]]:
    score = 0.0
    detail: dict[str, object] = {}
    if vol_surge is not None:
        detail["vol_surge"] = vol_surge
        if vol_surge >= 1.5:
            score += 8
        elif vol_surge >= 1.2:
            score += 6
        elif vol_surge >= 1.0:
            score += 3
    if intraday is not None:
        if intraday.vol_pace_ratio >= 1.3:
            score += 6
        elif intraday.vol_pace_ratio >= 1.1:
            score += 4
        elif intraday.vol_pace_ratio >= 1.0:
            score += 2
        if intraday.day_chg > 0 and (vol_surge is None or vol_surge >= 1.0):
            score += 6
        elif intraday.day_chg > 0:
            score += 3
    return clamp(score, 0.0, MAX_VOLUME_SCORE), detail


def score_relative_strength(
    stock_day_change: float,
    index_changes: Mapping[str, float],
    industry_change: float | None = None,
) -> tuple[float, dict[str, object]]:
    score = 0.0
    detail: dict[str, object] = {}
    industry_available = industry_change is not None
    for key, label, strong, medium, positive in (
        ("hs300", "rs_hs300", 5 if industry_available else 7, 4 if industry_available else 5, 2 if industry_available else 3),
        ("zz1000", "rs_zz1000", 5 if industry_available else 8, 4 if industry_available else 6, 2 if industry_available else 3),
    ):
        if key not in index_changes:
            continue
        relative = stock_day_change - index_changes[key]
        detail[label] = relative
        if relative >= 0.015:
            score += strong
        elif relative >= 0.005:
            score += medium
        elif relative >= 0:
            score += positive
    if industry_available:
        relative = stock_day_change - industry_change
        detail["rs_industry"] = relative
        if relative >= 0.015:
            score += 5
        elif relative >= 0.005:
            score += 4
        elif relative >= 0:
            score += 2
    detail["industry_available"] = industry_available
    return clamp(score, 0.0, MAX_RELATIVE_STRENGTH_SCORE), detail


def score_risk(
    intraday: IntradayIndicators | None,
    daily: DailyIndicators,
    quote: QuoteSnapshot,
    snapshot_close: float,
) -> tuple[float, dict[str, object]]:
    score = 10.0
    detail: dict[str, object] = {}
    if intraday is not None and intraday.amount_cur:
        amount_yi = intraday.amount_cur / 1e8
        detail["amount_yi"] = amount_yi
        if amount_yi < 1.0:
            score -= 4
        elif amount_yi < 3.0:
            score -= 2
    if quote.price_ceiling and snapshot_close >= quote.price_ceiling * 0.985:
        score -= 4
        detail["near_limitup"] = True
    elif intraday is not None and intraday.day_chg >= 0.095:
        score -= 3
        detail["near_limitup"] = True
    if daily.recent_up_streak >= 4 or (daily.r5 is not None and daily.r5 > 0.20):
        score -= 2
    if daily.r10 is not None and daily.r10 > 0.35:
        score -= 2
    if daily.ann_vol is not None and daily.ann_vol > 1.2:
        score -= 1
    detail["recent_up_streak"] = daily.recent_up_streak
    return clamp(score, 0.0, MAX_RISK_SCORE), detail


def score_stock(
    quote: QuoteSnapshot,
    intraday: IntradayIndicators | None,
    daily: DailyIndicators,
    vol_surge: float | None,
    index_changes: Mapping[str, float],
    environment_points: float,
    industry_change: float | None = None,
) -> FactorScore:
    snapshot_close = intraday.cur if intraday is not None else quote.price_ceiling
    if snapshot_close is None:
        raise ValueError("snapshot close is required")
    daily_with_snapshot = replace(daily, snapshot_close=snapshot_close)
    trend = score_trend(daily_with_snapshot)
    afternoon, afternoon_detail = score_afternoon(intraday)
    volume, volume_detail = score_volume(intraday, vol_surge)
    relative_strength, relative_detail = score_relative_strength(
        intraday.day_chg if intraday is not None else 0.0,
        index_changes,
        industry_change,
    )
    environment = clamp(environment_points, 0.0, 10.0)
    risk, risk_detail = score_risk(intraday, daily_with_snapshot, quote, snapshot_close)
    total = trend + afternoon + volume + relative_strength + environment + risk
    return FactorScore(
        trend=round(trend, 1),
        afternoon=round(afternoon, 1),
        volume=round(volume, 1),
        rs=round(relative_strength, 1),
        env=round(environment, 1),
        risk=round(risk, 1),
        total=round(total, 1),
        snapshot_close=snapshot_close,
        afternoon_detail=afternoon_detail,
        volume_detail=volume_detail,
        relative_strength_detail=relative_detail,
        risk_detail=risk_detail,
    )


def score_market_env(
    index_changes: Mapping[str, float],
    breadth: Mapping[str, float | None] | None,
) -> tuple[str, float, dict[str, object]]:
    values = [value for value in index_changes.values() if value is not None]
    average = sum(values) / len(values) if values else 0.0
    breadth_ratio = 0.5
    net_limit = 0.0
    detail: dict[str, object] = {"idx_avg_chg": round(average * 100, 2)}
    if breadth:
        total = (breadth.get("up") or 0) + (breadth.get("down") or 0)
        breadth_ratio = (breadth.get("up") or 0) / total if total else 0.5
        net_limit = (breadth.get("limitup") or 0) - (breadth.get("limitdown") or 0)
        detail.update(
            {
                "breadth_ratio": round(breadth_ratio * 100, 1),
                "limitup": breadth.get("limitup"),
                "limitdown": breadth.get("limitdown"),
            }
        )
    if average > 0.005 and breadth_ratio > 0.55 and net_limit > 0:
        label = "Bull"
        points = 7 + average * 100 * 1.5 + net_limit / 10.0
    elif average < -0.005 and breadth_ratio < 0.45:
        label = "Bear"
        points = (breadth_ratio - 0.5) * 10 + net_limit / 10.0
    else:
        label = "Neutral"
        points = 4 + (breadth_ratio - 0.5) * 10
    return label, round(clamp(points, 0.0, 10.0), 1), detail
