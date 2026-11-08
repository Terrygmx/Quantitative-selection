import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from jsonschema import Draft202012Validator

from quant_agent.cli.paper import build_parser, main
from quant_agent.domain.clock import FixedClock
from quant_agent.domain.models import Signal
from quant_agent.strategies.registry import StrategyMetadata, StrategyRegistry

SYMBOL = "sh600000"
RUN_AT = datetime(2026, 10, 26, 6, 45, tzinfo=UTC)
AS_OF = "2026-10-26T14:45:00+08:00"
CN_TZ = ZoneInfo("Asia/Shanghai")


def assert_contract(document, schema_name):
    api = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "docs/sdd/api-spec.yaml")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator(
        {
            "$ref": f"#/components/schemas/{schema_name}",
            "components": api["components"],
        }
    ).validate(document)


def bar_rows(
    *,
    symbol: str = SYMBOL,
    closes: list[float] | None = None,
) -> list[dict[str, object]]:
    closes = closes or [10.0, 10.1, 10.2]
    end = datetime(2026, 10, 26, 14, 30, tzinfo=CN_TZ)
    return [
        {
            "instrument": symbol,
            "timestamp": (end - timedelta(days=len(closes) - index - 1)).isoformat(),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1_000_000,
            "amount": close * 1_000_000,
            "available_at": (
                end - timedelta(days=len(closes) - index - 1)
            ).isoformat(),
        }
        for index, close in enumerate(closes)
    ]


def paper_config(
    path,
    *,
    strategy_config: dict[str, object] | None = None,
    bars: list[dict[str, object]] | None = None,
    market: dict[str, object] | None = None,
    execution: dict[str, object] | None = None,
):
    payload = {
        "strategy_config": strategy_config or {"universe": [SYMBOL]},
        "data": {"bars": bars or bar_rows()},
        "instruments": [
            {
                "symbol": SYMBOL,
                "exchange": "SSE",
                "board": "MainBoard",
                "status": "Active",
                "listing_date": "2010-01-01",
                "tick": "0.01",
                "lot_size": 100,
            }
        ],
        "market": market
        if market is not None
        else {
            SYMBOL: {
                "last": "10.20",
                "previous_close": "10.00",
                "tradable": True,
            }
        },
        "industry_by_symbol": {SYMBOL: "Technology"},
        "execution": execution
        if execution is not None
        else {
            "initial_cash": "100000.00",
            "buy_quantity": 100,
            "exchange": "SSE",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class ManualStrategy:
    metadata = StrategyMetadata(
        strategy_id="manual",
        version="2.3.4",
        frequency="daily",
    )

    def __init__(
        self,
        signals: bool = True,
        request_missing: bool = False,
    ):
        self.has_signals = signals
        self.request_missing = request_missing

    def on_snapshot(self, context) -> list[Signal]:
        if self.request_missing:
            context.data_port.bars("missing", context.as_of)
        return (
            [
                Signal(
                    strategy_id=self.metadata.strategy_id,
                    version=self.metadata.version,
                    symbol=SYMBOL,
                    side="long",
                    target_weight=0.1,
                    confidence=1.0,
                    valid_from=context.as_of,
                    valid_to=context.as_of + timedelta(days=1),
                    evidence={"industry": "Technology"},
                )
            ]
            if self.has_signals
            else []
        )

    def config_fingerprint(self) -> dict[str, object]:
        return {
            "has_signals": self.has_signals,
            "request_missing": self.request_missing,
        }


def registry(
    *,
    signals: bool = True,
    request_missing: bool = False,
) -> StrategyRegistry:
    result = StrategyRegistry()
    result.register(
        ManualStrategy(
            signals=signals,
            request_missing=request_missing,
        )
    )
    return result


def approve(
    tmp_path,
    config_file,
    *,
    strategy_registry: StrategyRegistry | None = None,
):
    approval_file = tmp_path / "approvals.json"
    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "approve",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--approved-by",
            "terry",
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry or registry(),
    )
    assert exit_code == 0
    return approval_file


def test_paper_cli_help_exposes_required_commands(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "approve" in help_text
    assert "run" in help_text
    assert "paper" in help_text


def test_approval_binds_strategy_version_config_hash_and_data_snapshot(
    tmp_path, capsys
):
    config_file = paper_config(tmp_path / "config.json")

    approval_file = approve(tmp_path, config_file)

    document = json.loads(capsys.readouterr().out)
    records = json.loads(approval_file.read_text(encoding="utf-8"))
    assert document == records[0]
    assert document["strategy_id"] == "manual"
    assert document["strategy_version"] == "2.3.4"
    assert len(document["config_hash"]) == 64
    assert len(document["data_snapshot"]) == 64
    assert document["approved_by"] == "terry"


def test_dry_run_requires_persisted_approval(tmp_path, capsys):
    config_file = paper_config(tmp_path / "config.json")
    approval_file = tmp_path / "approvals.json"

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--dry-run",
            "--as-of",
            AS_OF,
        ],
        registry=registry(),
        clock=FixedClock(RUN_AT),
    )

    assert exit_code == 2
    assert "approval" in capsys.readouterr().err


def test_dry_run_returns_strategy_audit_and_empty_order_plan(
    tmp_path, capsys
):
    config_file = paper_config(tmp_path / "config.json")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--dry-run",
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
        clock=FixedClock(RUN_AT),
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "DRY_RUN"
    assert document["orders"] == []
    assert document["strategy_version"] == "2.3.4"
    assert document["signals"][0]["strategy_id"] == "manual"
    assert document["targets"][0]["symbol"] == SYMBOL
    assert document["manifest"]["config_hash"] == document["config_hash"]
    assert document["manifest"]["created_at"] == AS_OF
    assert document["manifest"]["data_snapshot"] == document["data_snapshot"]
    assert document["read_snapshot"] == document["data_snapshot"]
    assert_contract(document, "PaperRunOutput")


def test_non_dry_run_uses_injected_execution_after_strategy_composition(
    tmp_path, capsys
):
    config_file = paper_config(tmp_path / "config.json")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()
    execution = FixedExecution()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        execution=execution,
        registry=strategy_registry,
        clock=FixedClock(RUN_AT),
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "PAPER_EXECUTED"
    assert document["orders"] == [
        {
            "symbol": SYMBOL,
            "side": "buy",
            "quantity": 100,
            "status": "FILLED",
        }
    ]
    assert execution.calls[0][1]["universe"] == [SYMBOL]


def test_execution_cannot_bypass_persisted_approval(tmp_path, capsys):
    config_file = paper_config(tmp_path / "config.json")
    approval_file = tmp_path / "approvals.json"
    execution = RecordingExecution()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        execution=execution,
        registry=registry(),
        clock=FixedClock(RUN_AT),
    )

    assert exit_code == 2
    assert "approval" in capsys.readouterr().err
    assert execution.calls == []


def test_non_dry_run_fails_closed_without_executor(tmp_path, capsys):
    config_file = paper_config(tmp_path / "config.json")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    del payload["execution"]
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    # Re-approve the modified config; the executor remains absent.
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
        clock=FixedClock(RUN_AT),
    )

    assert exit_code == 2
    assert "execution is not configured" in capsys.readouterr().err


def test_default_simulated_execution_uses_only_accepted_targets(
    tmp_path, capsys
):
    config_file = paper_config(tmp_path / "config.json")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
        clock=FixedClock(RUN_AT),
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "PAPER_EXECUTED"
    assert document["orders"][0]["status"] == "FILLED"
    assert document["orders"][0]["price"] == "10.21"


def test_no_signal_returns_no_signal_without_calling_execution(tmp_path, capsys):
    config_file = paper_config(tmp_path / "config.json")
    strategy_registry = registry(signals=False)
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()
    execution = RecordingExecution()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        execution=execution,
        registry=strategy_registry,
        clock=FixedClock(RUN_AT),
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "NO_SIGNAL"
    assert document["orders"] == []
    assert execution.calls == []
    assert_contract(document, "PaperRunOutput")


def test_dry_run_without_signal_returns_no_signal(tmp_path, capsys):
    config_file = paper_config(tmp_path / "config.json")
    strategy_registry = registry(signals=False)
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--dry-run",
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "NO_SIGNAL"
    assert document["orders"] == []
    assert_contract(document, "PaperRunOutput")


def test_paper_cli_block_event_returns_strategy_blocked_decision(
    tmp_path, capsys
):
    config_file = paper_config(tmp_path / "config.json")
    strategy_registry = registry(request_missing=True)
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()
    execution = RecordingExecution()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        execution=execution,
        registry=strategy_registry,
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "NO_SIGNAL"
    assert document["quality_summary"] == {
        "warn_count": 0,
        "block_count": 1,
        "blocked_strategies": ["manual"],
    }
    assert any(
        decision["reason_code"] == "STRATEGY_BLOCKED"
        for decision in document["decisions"]
    )
    assert execution.calls == []
    assert_contract(document, "PaperRunOutput")


def test_explicit_previous_close_map_is_passed_to_execution(tmp_path, capsys):
    config_file = paper_config(
        tmp_path / "config.json",
        market={SYMBOL: {"last": "12.01", "tradable": True}},
    )
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    payload["previous_close_by_symbol"] = {SYMBOL: "10.00"}
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["orders"][0]["status"] == "REJECTED"
    assert document["orders"][0]["reason_code"] == "PRICE_BAND"


@pytest.mark.parametrize(
    ("fill_model", "market_extra", "expected_price"),
    [
        ("next_open", {}, "10.20"),
        ("vwap", {"amount": "1019.00", "volume": "100"}, "10.19"),
    ],
)
def test_cli_passes_fill_model_to_default_execution(
    tmp_path,
    capsys,
    fill_model,
    market_extra,
    expected_price,
):
    market = {
        SYMBOL: {
            "last": "10.20",
            "previous_close": "10.00",
            "tradable": True,
            **market_extra,
        }
    }
    config_file = paper_config(tmp_path / "config.json", market=market)
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    payload["execution"]["fill_model"] = fill_model
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["orders"][0]["price"] == expected_price
    assert_contract(document, "PaperRunOutput")
    assert_contract(
        json.loads(config_file.read_text(encoding="utf-8")),
        "PaperStrategyConfig",
    )


def test_cli_passes_queue_fill_policy_to_default_execution(tmp_path, capsys):
    config_file = paper_config(
        tmp_path / "config.json",
        market={
            SYMBOL: {
                "last": "11.00",
                "previous_close": "10.00",
                "tradable": True,
                "board_volume": "1000",
            }
        },
    )
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    payload["execution"]["board_queue_policy"] = "queue_fill"
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["orders"][0]["status"] == "FILLED"
    assert document["orders"][0]["price"] == "11.00"
    assert_contract(document, "PaperRunOutput")


def test_vwap_without_amount_volume_fails_closed(tmp_path, capsys):
    config_file = paper_config(tmp_path / "config.json")
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    payload["execution"]["fill_model"] = "vwap"
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
    )

    assert exit_code == 2
    assert "vwap" in capsys.readouterr().err


def test_paper_config_requires_available_at(tmp_path, capsys):
    config_file = paper_config(tmp_path / "config.json")
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    del payload["data"]["bars"][0]["available_at"]
    config_file.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(
        [
            "--approvals",
            str(tmp_path / "approvals.json"),
            "approve",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--approved-by",
            "terry",
            "--as-of",
            AS_OF,
        ],
        registry=registry(),
    )

    assert exit_code == 2
    assert "available_at" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("last", "0"),
        ("last", "-1"),
        ("last", "1e1"),
        ("last", "+10"),
        ("previous_close", "-1"),
        ("previous_close", ""),
        ("tradable", "false"),
        ("board_volume", "-1"),
        ("board_volume", "-0"),
        ("board_volume", "1e2"),
    ],
)
def test_invalid_market_snapshot_types_fail_closed(
    tmp_path, capsys, field, value
):
    market = {
        SYMBOL: {
            "last": "10.20",
            "previous_close": "10.00",
            "tradable": True,
        }
    }
    market[SYMBOL][field] = value
    config_file = paper_config(tmp_path / "config.json", market=market)

    exit_code = main(
        [
            "--approvals",
            str(tmp_path / "approvals.json"),
            "approve",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--approved-by",
            "terry",
            "--as-of",
            AS_OF,
        ],
        registry=registry(),
    )

    assert exit_code == 2
    assert "market" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("initial_cash", "NaN"),
        ("initial_cash", "Infinity"),
        ("initial_cash", "+100000"),
        ("commission_rate", "-0.1"),
        ("commission_rate", "-0.0"),
        ("commission_rate", "1e-4"),
        ("commission_rate", 0.0003),
        ("buy_quantity", 0),
        ("buy_quantity", True),
    ],
)
def test_invalid_execution_numbers_fail_closed(
    tmp_path, capsys, field, value
):
    config_file = paper_config(tmp_path / "config.json")
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    payload["execution"][field] = value
    config_file.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(
        [
            "--approvals",
            str(tmp_path / "approvals.json"),
            "approve",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--approved-by",
            "terry",
            "--as-of",
            AS_OF,
        ],
        registry=registry(),
    )

    assert exit_code == 2
    assert "execution" in capsys.readouterr().err


def test_paper_run_output_matches_machine_contract(tmp_path, capsys):
    config_file = paper_config(tmp_path / "config.json")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert_contract(document, "PaperRunOutput")
    assert_contract(
        json.loads(config_file.read_text(encoding="utf-8")),
        "PaperStrategyConfig",
    )


def test_config_hash_mismatch_fails_closed(tmp_path, capsys):
    config_file = paper_config(tmp_path / "config.json")
    strategy_registry = registry()
    approval_file = approve(
        tmp_path, config_file, strategy_registry=strategy_registry
    )
    payload = json.loads(config_file.read_text(encoding="utf-8"))
    payload["config_hash"] = "stale"
    config_file.write_text(json.dumps(payload), encoding="utf-8")

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "manual",
            "--config",
            str(config_file),
            "--dry-run",
            "--as-of",
            AS_OF,
        ],
        registry=strategy_registry,
        clock=FixedClock(RUN_AT),
    )

    assert exit_code == 2
    assert "config_hash" in capsys.readouterr().err


def test_default_registry_runs_daily_strategy_from_config(tmp_path, capsys):
    closes = [9.0 + index * 0.05 for index in range(22)] + [11.5]
    config_file = paper_config(
        tmp_path / "config.json",
        strategy_config={
            "universe": [SYMBOL],
            "breakout_window": 20,
            "trend_window": 20,
        },
        bars=bar_rows(closes=closes),
        market={
            SYMBOL: {
                "last": "11.50",
                "previous_close": "11.00",
                "tradable": True,
            }
        },
    )
    approval_file = tmp_path / "approvals.json"
    assert (
        main(
            [
                "--approvals",
                str(approval_file),
                "approve",
                "--strategy",
                "trend_breakout",
                "--config",
                str(config_file),
                "--approved-by",
                "terry",
                "--as-of",
                AS_OF,
            ]
        )
        == 0
    )
    capsys.readouterr()

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "trend_breakout",
            "--config",
            str(config_file),
            "--as-of",
            AS_OF,
        ],
        clock=FixedClock(RUN_AT),
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["strategy_id"] == "trend_breakout"
    assert document["signals"][0]["strategy_id"] == "trend_breakout"
    assert document["orders"][0]["status"] == "FILLED"


def test_tail_momentum_cli_fails_closed_without_full_input_hydration(
    tmp_path, capsys
):
    config_file = paper_config(
        tmp_path / "config.json",
        strategy_config={"universe": [SYMBOL]},
    )

    exit_code = main(
        [
            "--approvals",
            str(tmp_path / "approvals.json"),
            "approve",
            "--strategy",
            "tail_momentum_overnight",
            "--config",
            str(config_file),
            "--approved-by",
            "terry",
            "--as-of",
            AS_OF,
        ]
    )

    assert exit_code == 2
    assert "unsupported strategy" in capsys.readouterr().err


class FixedExecution:
    def __init__(self):
        self.calls = []

    def execute(self, strategy_id, config, run_at):
        self.calls.append((strategy_id, dict(config), run_at))
        return [
            {
                "symbol": SYMBOL,
                "side": "buy",
                "quantity": 100,
                "status": "FILLED",
            }
        ]


class RecordingExecution:
    def __init__(self):
        self.calls = []

    def execute(self, strategy_id, config, run_at):
        self.calls.append((strategy_id, dict(config), run_at))
        return []
