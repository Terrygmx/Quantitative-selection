"""Shared identity binding for strategy-driven backtest and paper runs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from quant_agent.application.identity import canonical_hash
from quant_agent.application.portfolio import PortfolioRiskConfig
from quant_agent.domain.models import Instrument
from quant_agent.rules.trading import TradingRulesPlugin
from quant_agent.strategies.registry import Strategy


def strategy_state(strategy: Strategy) -> dict[str, object]:
    value = strategy.config_fingerprint()
    if not isinstance(value, Mapping):
        raise ValueError("strategy config_fingerprint() must return a mapping")
    return dict(value)


def rules_identity(rules: TradingRulesPlugin) -> dict[str, object]:
    calendar = rules.calendar
    if calendar is None:
        return {"calendar": "weekday"}
    fingerprint = getattr(calendar, "calendar_fingerprint", None)
    if not callable(fingerprint):
        raise ValueError("rules calendar must provide calendar_fingerprint()")
    return {"calendar": fingerprint()}


def validate_signal_provenance(
    signals: Sequence[object],
    strategy_versions: Mapping[str, str],
) -> None:
    for signal in signals:
        strategy_id = getattr(signal, "strategy_id", None)
        version = getattr(signal, "version", None)
        expected = strategy_versions.get(str(strategy_id))
        if expected is None or version != expected:
            raise ValueError(
                "strategy returned a signal with foreign strategy identity"
            )


def strategy_run_identity(
    *,
    as_of: datetime,
    strategy_versions: Mapping[str, str],
    strategy_states: Mapping[str, Mapping[str, object]],
    strategy_configs: Mapping[str, Mapping[str, object]],
    instruments: Mapping[str, Instrument],
    industry_by_symbol: Mapping[str, str],
    previous_close_by_symbol: Mapping[str, object],
    portfolio_risk: PortfolioRiskConfig,
    rules: TradingRulesPlugin,
    strategy_ids: Sequence[str],
    extra: Mapping[str, object] | None = None,
) -> str:
    if as_of.tzinfo is None:
        raise ValueError("strategy identity requires timezone-aware as_of")
    payload: dict[str, object] = {
        "as_of": as_of,
        "strategy_ids": tuple(strategy_ids),
        "strategy_versions": dict(strategy_versions),
        "strategy_states": {
            key: dict(value) for key, value in strategy_states.items()
        },
        "strategy_configs": {
            key: dict(value) for key, value in strategy_configs.items()
        },
        "instruments": dict(instruments),
        "industry_by_symbol": dict(industry_by_symbol),
        "previous_close_by_symbol": dict(previous_close_by_symbol),
        "portfolio_risk": portfolio_risk,
        "rules": rules_identity(rules),
    }
    if extra is not None:
        payload["extra"] = dict(extra)
    return canonical_hash(payload)
