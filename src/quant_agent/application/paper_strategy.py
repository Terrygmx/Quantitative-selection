"""Strategy-driven paper-trading decisions and audit evidence for P-002."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from quant_agent.application.identity import (
    canonical_hash,
    parse_decimal_string,
)
from quant_agent.application.portfolio import (
    ComposerSignal,
    PortfolioRiskConfig,
    RiskDecision,
    SignalAdapter,
    SignalComposer,
    TargetPosition,
)
from quant_agent.application.runs import RunManifestFactory
from quant_agent.application.strategy_identity import (
    strategy_run_identity,
    strategy_state,
    validate_signal_provenance,
)
from quant_agent.application.strategy_backtest import RunBoundMarketDataPort
from quant_agent.domain.models import Instrument, RunManifest, Signal
from quant_agent.ports.market_data import MarketDataPort
from quant_agent.rules.trading import TradingRulesPlugin
from quant_agent.strategies.context import StrategyContext
from quant_agent.strategies.registry import StrategyRegistry

CN_MARKET_TZ = ZoneInfo("Asia/Shanghai")


def _positive_decimal(value: object, field: str) -> Decimal:
    return parse_decimal_string(
        value,
        field,
        minimum=Decimal("0"),
        allow_zero=False,
    )


def _non_negative_decimal(value: object, field: str) -> Decimal:
    return parse_decimal_string(
        value,
        field,
        minimum=Decimal("0"),
        allow_zero=True,
    )


def _validate_market_snapshot(symbol: str, snapshot: object) -> None:
    if not isinstance(snapshot, Mapping):
        raise ValueError(f"market.{symbol} must be an object")
    _positive_decimal(snapshot.get("last"), f"market.{symbol}.last")
    if "previous_close" in snapshot:
        _positive_decimal(
            snapshot["previous_close"],
            f"market.{symbol}.previous_close",
        )
    tradable = snapshot.get("tradable", True)
    if not isinstance(tradable, bool):
        raise ValueError(f"market.{symbol}.tradable must be a boolean")
    if "board_volume" in snapshot:
        _non_negative_decimal(
            snapshot["board_volume"],
            f"market.{symbol}.board_volume",
        )


def validate_paper_config(config: Mapping[str, object]) -> None:
    allowed = {
        "config_hash",
        "strategy_config",
        "data",
        "market",
        "instruments",
        "execution",
        "industry_by_symbol",
        "previous_close_by_symbol",
        "session",
    }
    unknown = sorted(set(config) - allowed)
    if unknown:
        raise ValueError("unknown paper config keys: " + ", ".join(unknown))
    strategy_config = config.get("strategy_config")
    if not isinstance(strategy_config, Mapping):
        raise ValueError("paper config requires a strategy_config object")
    data = config.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("paper config requires a data object")
    bars = data.get("bars")
    if not isinstance(bars, list) or not bars:
        raise ValueError("paper config requires non-empty data.bars")
    market = config.get("market")
    if not isinstance(market, Mapping) or not market:
        raise ValueError("paper config requires a non-empty market object")
    for symbol, snapshot in market.items():
        if not isinstance(symbol, str) or not symbol:
            raise ValueError("market keys must be non-empty strings")
        _validate_market_snapshot(symbol, snapshot)
    instruments = config.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        raise ValueError("paper config requires non-empty instruments")
    session = config.get("session", "continuous")
    if session not in ("continuous", "after_hours_fixed"):
        raise ValueError("session must be continuous or after_hours_fixed")
    execution = config.get("execution")
    if execution is not None and not isinstance(execution, Mapping):
        raise ValueError("execution must be an object")
    if isinstance(execution, Mapping):
        execution_allowed = {
            "exchange",
            "initial_cash",
            "commission_rate",
            "stamp_tax_rate",
            "slippage_rate",
            "buy_quantity",
            "fill_model",
            "board_queue_policy",
        }
        unknown_execution = sorted(set(execution) - execution_allowed)
        if unknown_execution:
            raise ValueError(
                "unknown execution config keys: "
                + ", ".join(unknown_execution)
            )
        _positive_decimal(
            execution.get("initial_cash", "100000.00"),
            "execution.initial_cash",
        )
        for field in (
            "commission_rate",
            "stamp_tax_rate",
            "slippage_rate",
        ):
            _non_negative_decimal(
                execution.get(
                field,
                {
                    "commission_rate": "0.0003",
                    "stamp_tax_rate": "0.0005",
                    "slippage_rate": "0.001",
                }[field],
                ),
                f"execution.{field}",
            )
        quantity = execution.get("buy_quantity", 100)
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise ValueError(
                "execution.buy_quantity must be a positive integer"
            )
        if execution.get("exchange", "SSE") not in ("SSE", "SZSE"):
            raise ValueError("execution.exchange must be SSE or SZSE")
        if execution.get("fill_model", "slippage") not in {
            "slippage",
            "next_open",
            "vwap",
        }:
            raise ValueError(
                "execution.fill_model must be slippage, next_open or vwap"
            )
        if execution.get("board_queue_policy", "reject") not in {
            "reject",
            "queue_fill",
        }:
            raise ValueError(
                "execution.board_queue_policy must be reject or queue_fill"
            )
    industries = config.get("industry_by_symbol", {})
    if not isinstance(industries, Mapping):
        raise ValueError("industry_by_symbol must be an object")
    if not all(
        isinstance(symbol, str)
        and symbol
        and isinstance(industry, str)
        and industry.strip()
        for symbol, industry in industries.items()
    ):
        raise ValueError("industry_by_symbol values must be non-empty strings")
    previous = config.get("previous_close_by_symbol", {})
    if not isinstance(previous, Mapping):
        raise ValueError("previous_close_by_symbol must be an object")
    for symbol, value in previous.items():
        if not isinstance(symbol, str) or not symbol:
            raise ValueError(
                "previous_close_by_symbol keys must be non-empty strings"
            )
        _positive_decimal(value, f"previous_close_by_symbol.{symbol}")
    supplied_hash = config.get("config_hash")
    if supplied_hash is not None and not (
        isinstance(supplied_hash, str) and supplied_hash.strip()
    ):
        raise ValueError("config_hash must be a non-empty string")


@dataclass(frozen=True, slots=True)
class PaperStrategyIdentity:
    strategy_id: str
    strategy_version: str
    config_hash: str
    as_of: datetime


@dataclass(frozen=True, slots=True)
class PaperStrategyPlan:
    strategy_id: str
    strategy_version: str
    config_hash: str
    data_snapshot: str
    read_snapshot: str
    signals: tuple[ComposerSignal, ...]
    decisions: tuple[RiskDecision, ...]
    targets: tuple[TargetPosition, ...]
    execution_symbols: tuple[str, ...]
    source_signal_count: int
    manifest: RunManifest


class StrategyPaperOrchestrator:
    """Invoke one strategy plugin and stop before any paper order execution."""

    def __init__(
        self,
        *,
        port: MarketDataPort,
        instruments: Mapping[str, Instrument],
        registry: StrategyRegistry,
        rules: TradingRulesPlugin,
        industry_by_symbol: Mapping[str, str] | None = None,
        previous_close_by_symbol: Mapping[str, object] | None = None,
        portfolio_risk: PortfolioRiskConfig | None = None,
        manifest_factory: RunManifestFactory | None = None,
        git_sha: str = "working-tree",
    ) -> None:
        self.port = port
        self.instruments = dict(instruments)
        self.registry = registry
        self.rules = rules
        self.industry_by_symbol = dict(industry_by_symbol or {})
        if not all(
            isinstance(symbol, str)
            and symbol
            and isinstance(industry, str)
            and industry.strip()
            for symbol, industry in self.industry_by_symbol.items()
        ):
            raise ValueError("industry_by_symbol values must be non-empty strings")
        self.previous_close_by_symbol = {
            str(symbol): _positive_decimal(
                value, f"previous_close_by_symbol.{symbol}"
            )
            for symbol, value in (previous_close_by_symbol or {}).items()
            if str(symbol)
        }
        self.portfolio_risk = portfolio_risk or PortfolioRiskConfig()
        self.manifest_factory = manifest_factory or RunManifestFactory()
        self.git_sha = git_sha

    def evaluate(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        as_of: datetime,
    ) -> PaperStrategyPlan:
        identity = self.identity(strategy_id, config, as_of)
        normalized_as_of = identity.as_of
        bound_port = RunBoundMarketDataPort(self.port, normalized_as_of)
        context = StrategyContext(bound_port, normalized_as_of)
        plugin_result = self.registry.run_selected((strategy_id,), context)
        if plugin_result.failures:
            details = "; ".join(
                f"{failure.strategy_id}: {failure.reason_code}: {failure.message}"
                for failure in plugin_result.failures
            )
            raise ValueError(f"strategy plugins failed: {details}")
        if not all(
            isinstance(signal, Signal) for signal in plugin_result.signals
        ):
            raise ValueError("strategy plugins returned a non-Signal output")
        validate_signal_provenance(
            plugin_result.signals,
            {strategy_id: identity.strategy_version},
        )
        domain_signals = self._with_configured_industries(
            cast(list[Signal], list(plugin_result.signals))
        )
        adapted = SignalAdapter().adapt(
            domain_signals,
            as_of=normalized_as_of,
        )
        composition = SignalComposer(self.portfolio_risk).compose(
            list(adapted.signals),
            as_of=normalized_as_of,
        )
        accepted = tuple(
            target
            for target in composition.targets
            if target.status in ("accepted", "reduced")
            and target.net_weight > 0
        )
        missing = sorted(
            target.symbol
            for target in accepted
            if target.symbol not in self.instruments
        )
        if missing:
            raise ValueError(
                "signal symbols lack instrument metadata: " + ", ".join(missing)
            )
        market = cast(Mapping[str, object], config["market"])
        for target in accepted:
            snapshot = market.get(target.symbol)
            if not isinstance(snapshot, Mapping):
                raise ValueError(
                    f"accepted target requires a market snapshot: {target.symbol}"
                )
            _positive_decimal(
                snapshot.get("last"),
                f"market.{target.symbol}.last",
            )
            previous_close = snapshot.get("previous_close")
            if previous_close in (None, ""):
                previous_close = self.previous_close_by_symbol.get(
                    target.symbol
                )
                if previous_close is not None:
                    previous_close = str(previous_close)
            _positive_decimal(
                previous_close,
                f"market.{target.symbol}.previous_close",
            )
        data_snapshot = canonical_hash(
            {
                "as_of": normalized_as_of,
                "reads": bound_port.snapshot(),
            }
        )
        manifest = self.manifest_factory.create(
            git_sha=self.git_sha,
            config_hash=identity.config_hash,
            data_snapshot=data_snapshot,
            seed=0,
        )
        return PaperStrategyPlan(
            strategy_id=strategy_id,
            strategy_version=identity.strategy_version,
            config_hash=identity.config_hash,
            data_snapshot=data_snapshot,
            read_snapshot=data_snapshot,
            signals=adapted.signals,
            decisions=adapted.decisions + composition.decisions,
            targets=composition.targets,
            execution_symbols=tuple(
                target.symbol for target in accepted
            ),
            source_signal_count=len(domain_signals),
            manifest=manifest,
        )

    def identity(
        self,
        strategy_id: str,
        config: Mapping[str, object],
        as_of: datetime,
    ) -> PaperStrategyIdentity:
        if as_of.tzinfo is None:
            raise ValueError("paper as_of must be timezone-aware")
        normalized_as_of = as_of.astimezone(CN_MARKET_TZ)
        validate_paper_config(config)
        strategy_config = config.get("strategy_config")
        if not isinstance(strategy_config, Mapping):
            raise ValueError("paper config requires a strategy_config object")
        enabled = {
            metadata.strategy_id for metadata in self.registry.list()
        }
        if strategy_id not in enabled:
            raise ValueError(f"unknown or disabled strategy id: {strategy_id}")
        strategy = self.registry.get(strategy_id)
        version = strategy.metadata.version
        config_hash = strategy_run_identity(
            as_of=normalized_as_of,
            strategy_ids=(strategy_id,),
            strategy_versions={strategy_id: version},
            strategy_states={
                strategy_id: strategy_state(strategy),
            },
            strategy_configs={
                strategy_id: dict(strategy_config),
            },
            instruments=self.instruments,
            industry_by_symbol=self.industry_by_symbol,
            previous_close_by_symbol=self.previous_close_by_symbol,
            portfolio_risk=self.portfolio_risk,
            rules=self.rules,
            extra={
                "paper_config": {
                    key: value
                    for key, value in config.items()
                    if key != "config_hash"
                }
            },
        )
        supplied_hash = config.get("config_hash")
        if supplied_hash is not None and str(supplied_hash) != config_hash:
            raise ValueError("paper config_hash does not match computed config")
        return PaperStrategyIdentity(
            strategy_id=strategy_id,
            strategy_version=version,
            config_hash=config_hash,
            as_of=normalized_as_of,
        )

    def _with_configured_industries(
        self,
        signals: list[Signal],
    ) -> list[Signal]:
        enriched: list[Signal] = []
        for signal in signals:
            industry = signal.evidence.get("industry")
            if (
                isinstance(industry, str) and industry.strip()
            ) or signal.symbol not in self.industry_by_symbol:
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
