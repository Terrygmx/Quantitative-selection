"""Deterministic strategy-to-backtest orchestration for P-001."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal, DecimalException
from typing import Any, cast
from zoneinfo import ZoneInfo

from quant_agent.application.backtest import (
    BacktestConfig,
    MultiInstrumentBacktestEngine,
)
from quant_agent.application.metrics import BacktestMetrics
from quant_agent.application.portfolio import PortfolioRiskConfig, SignalAdapter, SignalComposer
from quant_agent.application.runs import RunManifestFactory
from quant_agent.domain.models import Instrument, RunManifest, Signal
from quant_agent.ports.market_data import DataUnavailable, MarketDataPort
from quant_agent.rules.trading import TradingRulesPlugin
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.registry import StrategyRegistry


CN_MARKET_TZ = ZoneInfo("Asia/Shanghai")


class RunBoundMarketDataPort:
    """PIT-bound wrapper that records every read used by a strategy run."""

    def __init__(self, port: MarketDataPort, as_of: datetime):
        self._port = port
        self._as_of = as_of
        self._reads: dict[tuple[str, str], dict[str, object]] = {}

    def bars(self, instrument: str, as_of: datetime) -> list[Any]:
        if as_of.tzinfo is None:
            raise ValueError("PIT requests must use timezone-aware datetimes")
        requested = as_of.astimezone(CN_MARKET_TZ)
        if requested > self._as_of:
            raise ValueError(
                f"PIT violation: {instrument} requested {requested.isoformat()} "
                f"after {self._as_of.isoformat()}"
            )
        key = (instrument, requested.isoformat())
        try:
            bars = self._port.bars(instrument, requested)
        except DataUnavailable:
            self._reads[key] = {
                "instrument": instrument,
                "as_of": requested,
                "bars": [],
                "available": False,
            }
            raise
        self._reads[key] = {
            "instrument": instrument,
            "as_of": requested,
            "bars": bars,
            "available": True,
        }
        return bars

    def snapshot(self) -> list[dict[str, object]]:
        return [
            self._reads[key]
            for key in sorted(self._reads)
        ]


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_value(value: object) -> object:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        items = [_canonical_value(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _rules_identity(rules: TradingRulesPlugin) -> dict[str, object]:
    calendar = rules.calendar
    if calendar is None:
        return {"calendar": "weekday"}
    fingerprint = getattr(calendar, "calendar_fingerprint", None)
    if not callable(fingerprint):
        raise ValueError("rules calendar must provide calendar_fingerprint()")
    return {"calendar": fingerprint()}


def _strategy_state(strategy: object) -> dict[str, object]:
    fingerprint = getattr(strategy, "config_fingerprint", None)
    if not callable(fingerprint):
        raise ValueError("strategy must provide config_fingerprint()")
    value = fingerprint()
    if not isinstance(value, Mapping):
        raise ValueError("strategy config_fingerprint() must return a mapping")
    return dict(value)


class StrategyBacktestOrchestrator:
    """Compose strategy signals into targets, then execute one fixed-size buy."""

    def __init__(
        self,
        *,
        port: MarketDataPort,
        instruments: Mapping[str, Instrument],
        config: BacktestConfig,
        rules: TradingRulesPlugin,
        registry: StrategyRegistry,
        strategy_ids: tuple[str, ...],
        as_of: datetime,
        decision_time: str = "1430",
        industry_by_symbol: Mapping[str, str] | None = None,
        strategy_configs: Mapping[str, Mapping[str, object]] | None = None,
        previous_close_by_symbol: Mapping[str, object] | None = None,
        portfolio_risk: PortfolioRiskConfig | None = None,
        manifest_factory: RunManifestFactory | None = None,
        git_sha: str = "working-tree",
        manifest: RunManifest | None = None,
    ):
        self.port = port
        self.instruments = dict(instruments)
        self.config = config
        self.rules = rules
        self.registry = registry
        self.strategy_ids = tuple(strategy_ids)
        if not isinstance(as_of, datetime) or as_of.tzinfo is None:
            raise ValueError("as_of must be a timezone-aware datetime")
        self.as_of = as_of.astimezone(CN_MARKET_TZ)
        hour, minute = int(decision_time[:2]), int(decision_time[2:])
        self.decision_clock = time(hour, minute)
        if self.as_of.hour != hour or self.as_of.minute != minute:
            raise ValueError("decision_time must match the normalized as_of clock")
        self.portfolio_risk = portfolio_risk or PortfolioRiskConfig()
        self.strategy_configs = {
            str(strategy_id): dict(config)
            for strategy_id, config in (strategy_configs or {}).items()
        }
        try:
            self.previous_close_by_symbol = {
                str(symbol): Decimal(str(value))
                for symbol, value in (previous_close_by_symbol or {}).items()
            }
            if not all(
                value.is_finite() and value > 0
                for value in self.previous_close_by_symbol.values()
            ):
                raise ValueError("previous_close_by_symbol values must be positive")
        except (DecimalException, ValueError) as exc:
            raise ValueError(
                "previous_close_by_symbol values must be finite positive decimals"
            ) from exc
        self.industry_by_symbol = dict(industry_by_symbol or {})
        if not all(
            isinstance(symbol, str)
            and bool(symbol)
            and isinstance(industry, str)
            and bool(industry.strip())
            for symbol, industry in self.industry_by_symbol.items()
        ):
            raise ValueError("industry_by_symbol values must be non-empty strings")
        self.manifest_factory = manifest_factory or RunManifestFactory()
        self.git_sha = git_sha
        self.manifest = manifest
        self.strategy_versions: dict[str, str] = {}
        self.strategy_states: dict[str, dict[str, object]] = {}
        for strategy_id in self.strategy_ids:
            try:
                strategy = registry.get(strategy_id)
                self.strategy_versions[strategy_id] = strategy.metadata.version
                self.strategy_states[strategy_id] = _strategy_state(strategy)
            except KeyError as exc:
                raise ValueError(f"unknown strategy id: {strategy_id}") from exc
        self.config_hash = _canonical_hash(
            {
                "config": config,
                "as_of": self.as_of,
                "decision_time": decision_time,
                "portfolio_risk": self.portfolio_risk,
                "strategy_ids": self.strategy_ids,
                "strategy_versions": self.strategy_versions,
                "strategy_configs": self.strategy_configs,
                "strategy_states": self.strategy_states,
                "instruments": self.instruments,
                "industry_by_symbol": self.industry_by_symbol,
                "previous_close_by_symbol": self.previous_close_by_symbol,
                "rules": _rules_identity(rules),
            }
        )
        if manifest is not None and manifest.config_hash != self.config_hash:
            raise ValueError("supplied RunManifest config_hash does not match inputs")

    def run(self) -> dict[str, object]:
        bound_port = RunBoundMarketDataPort(self.port, self.as_of)
        context = StrategyContext(bound_port, self.as_of)
        enabled = self.registry.list()
        enabled_ids = {item.strategy_id for item in enabled}
        unknown = [item for item in self.strategy_ids if item not in enabled_ids]
        if unknown:
            raise ValueError(f"unknown or disabled strategy ids: {', '.join(unknown)}")
        plugin_result = self.registry.run_selected(self.strategy_ids, context)
        if plugin_result.failures:
            details = "; ".join(
                f"{failure.strategy_id}: {failure.reason_code}: {failure.message}"
                for failure in plugin_result.failures
            )
            raise ValueError(f"strategy plugins failed: {details}")
        if not all(isinstance(signal, Signal) for signal in plugin_result.signals):
            raise ValueError("strategy plugins returned a non-Signal output")
        domain_signals = cast(list[Signal], list(plugin_result.signals))
        domain_signals = self._with_configured_industries(domain_signals)

        adapted = SignalAdapter().adapt(domain_signals, as_of=self.as_of)
        composer = SignalComposer(self.portfolio_risk)
        composition = composer.compose(
            list(adapted.signals),
            as_of=self.as_of,
        )
        accepted = [
            target
            for target in composition.targets
            if target.status in ("accepted", "reduced") and target.net_weight > 0
        ]

        if accepted and any(
            target.symbol not in self.instruments for target in accepted
        ):
            missing = sorted(
                target.symbol
                for target in accepted
                if target.symbol not in self.instruments
            )
            raise ValueError(
                f"signal symbols lack instrument metadata: {', '.join(missing)}"
            )
        visible_by_symbol = self._visible_by_symbol(bound_port)
        engine = self._engine(accepted, visible_by_symbol)
        engine.run()
        orders = self._orders(engine)
        fills = self._fills(engine)
        data_snapshot = _canonical_hash(
            {"as_of": self.as_of, "reads": bound_port.snapshot()}
        )
        if self.manifest is not None:
            if self.manifest.data_snapshot != data_snapshot:
                raise ValueError("supplied RunManifest data_snapshot does not match inputs")
            manifest = self.manifest
        else:
            manifest = self.manifest_factory.create(
                git_sha=self.git_sha,
                config_hash=self.config_hash,
                data_snapshot=data_snapshot,
                seed=0,
            )
        final_equity = self._final_equity(engine, visible_by_symbol)
        metrics = BacktestMetrics(
            initial_cash=self.config.initial_cash,
            final_equity=final_equity,
            equity_curve=(self.config.initial_cash, final_equity),
            fills=fills,
        )
        return {
            "manifest": manifest.to_dict(),
            "signals": self._signals(adapted.signals),
            "decisions": self._decisions(adapted.decisions + composition.decisions),
            "targets": self._targets(composition.targets),
            "orders": orders,
            "fills": fills,
            "summary": metrics.summary(),
        }

    def _engine(
        self,
        accepted: Sequence[Any],
        visible_by_symbol: Mapping[str, Sequence[Any]],
    ) -> MultiInstrumentBacktestEngine:
        bars: dict[str, list[Mapping[str, object]]] = {}
        for target in accepted:
            symbol = target.symbol
            visible = list(visible_by_symbol[symbol])
            if not visible:
                raise ValueError(f"no visible bars for accepted target: {symbol}")
            bar = visible[-1]
            previous_close = self._previous_close(symbol, visible, bar)
            day = self.as_of.date()
            bars[symbol] = [
                {
                    "date": day,
                    "timestamp": self.as_of,
                    "open": str(bar.close),
                    "close": str(bar.close),
                    "previous_close": str(previous_close),
                    "amount": str(bar.amount),
                    "volume": str(bar.volume),
                }
            ]
        return MultiInstrumentBacktestEngine(
            bars=bars,
            instruments=self.instruments,
            config=self.config,
            rules=self.rules,
        )

    def _previous_close(
        self,
        symbol: str,
        visible: Sequence[Any],
        bar: Any,
    ) -> Decimal:
        if symbol in self.previous_close_by_symbol:
            return self.previous_close_by_symbol[symbol]
        bar_day = bar.timestamp.astimezone(CN_MARKET_TZ).date()
        if bar_day < self.as_of.date():
            return Decimal(str(bar.close))
        previous_day = [
            item
            for item in visible
            if item.timestamp.astimezone(CN_MARKET_TZ).date() < bar_day
        ]
        if not previous_day:
            raise ValueError(
                f"previous close unavailable for intraday target: {symbol}"
            )
        return Decimal(str(previous_day[-1].close))

    def _with_configured_industries(
        self, signals: Sequence[Signal]
    ) -> list[Signal]:
        enriched: list[Signal] = []
        for signal in signals:
            industry = signal.evidence.get("industry")
            if (
                (isinstance(industry, str) and bool(industry.strip()))
                or signal.symbol not in self.industry_by_symbol
            ):
                enriched.append(signal)
                continue
            evidence = dict(signal.evidence)
            evidence["industry"] = self.industry_by_symbol[signal.symbol]
            enriched.append(
                Signal(
                    strategy_id=signal.strategy_id,
                    version=signal.version,
                    symbol=signal.symbol,
                    side=signal.side,
                    target_weight=signal.target_weight,
                    confidence=signal.confidence,
                    valid_from=signal.valid_from,
                    valid_to=signal.valid_to,
                    evidence=evidence,
                )
            )
        return enriched

    def _visible_by_symbol(
        self, port: MarketDataPort
    ) -> dict[str, list[Any]]:
        visible: dict[str, list[Any]] = {}
        for symbol in sorted(self.instruments):
            try:
                visible[symbol] = port.bars(symbol, self.as_of)
            except DataUnavailable:
                visible[symbol] = []
        return visible

    @staticmethod
    def _signals(signals) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for signal in signals:
            rows.append(
                {
                    "strategy_id": signal["strategy_id"],
                    "version": signal["version"],
                    "symbol": signal["symbol"],
                    "side": signal["side"],
                    "target_weight": signal["target_weight"],
                    "confidence": signal["confidence"],
                    "valid_from": signal["valid_from"],
                    "valid_to": signal["valid_to"],
                    "industry": signal["industry"],
                    "evidence": dict(signal["evidence"]),
                }
            )
        return rows

    @staticmethod
    def _decisions(decisions) -> list[dict[str, object]]:
        return [
            {
                "symbol": decision.symbol,
                "status": decision.status,
                "net_weight": decision.net_weight,
                "reason_code": decision.reason_code,
                "strategy_id": decision.strategy_id,
                "version": decision.version,
            }
            for decision in decisions
        ]

    @staticmethod
    def _targets(targets) -> list[dict[str, object]]:
        return [
            {
                "symbol": target.symbol,
                "net_weight": target.net_weight,
                "contributions": dict(target.contributions),
                "industry": target.industry,
                "strategy_versions": dict(target.strategy_versions),
                "evidence": {
                    key: dict(value) for key, value in target.evidence.items()
                },
                "status": target.status,
                "reason_code": target.reason_code,
            }
            for target in targets
        ]

    @staticmethod
    def _orders(engine: MultiInstrumentBacktestEngine) -> list[dict[str, object]]:
        return [
            {
                "id": order.id,
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "status": engine.order_states.get(order.id).status,
                **(
                    {"rejection_code": engine.order_states.get(order.id).rejection_code}
                    if engine.order_states.get(order.id).rejection_code
                    else {}
                ),
            }
            for order in engine.orders
        ]

    @staticmethod
    def _fills(engine: MultiInstrumentBacktestEngine) -> list[Mapping[str, object]]:
        return [
            {
                "order_id": fill.order_id,
                "side": fill.side,
                "price": str(fill.price),
                "quantity": fill.quantity,
                "fee": str(fill.fee),
                "timestamp": fill.timestamp.isoformat(),
            }
            for fill in engine.fills
        ]

    def _final_equity(
        self,
        engine: MultiInstrumentBacktestEngine,
        visible_by_symbol: Mapping[str, Sequence[Any]],
    ) -> Decimal:
        holding_value = Decimal("0")
        for symbol in self.instruments:
            bars = visible_by_symbol[symbol]
            position = engine.position(symbol)
            quantity = position.settled_qty + position.unsettled_buy_qty
            if bars and quantity:
                holding_value += Decimal(str(bars[-1].close)) * quantity
        return engine.cash + holding_value
