import json
from dataclasses import asdict
from datetime import datetime, timezone

import pytest

from quant_agent.agents.paper import ApprovalRecord
from quant_agent.cli.paper import build_parser, main
from quant_agent.domain.clock import FixedClock


@pytest.fixture
def approval():
    return ApprovalRecord(
        strategy_id="tail_momentum_overnight",
        config_hash="hash-1",
        approved_by="terry",
    )


def write_config(path, *, config_hash="hash-1", universe=None):
    path.write_text(
        json.dumps(
            {
                "config_hash": config_hash,
                "universe": universe or ["sh600176"],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_paper_cli_help_exposes_required_commands(capsys):
    parser = build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "approve" in help_text
    assert "run" in help_text
    assert "paper" in help_text


def test_paper_cli_approval_persists_strategy_and_config_hash(tmp_path):
    approval_file = tmp_path / "approvals.json"
    config_file = write_config(tmp_path / "config.json")

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "approve",
            "--strategy",
            "tail_momentum_overnight",
            "--config",
            str(config_file),
            "--approved-by",
            "terry",
        ]
    )

    assert exit_code == 0
    assert json.loads(approval_file.read_text(encoding="utf-8")) == [
        {
            "strategy_id": "tail_momentum_overnight",
            "config_hash": "hash-1",
            "approved_by": "terry",
        }
    ]


def test_paper_cli_dry_run_requires_persisted_approval(tmp_path, capsys):
    approval_file = tmp_path / "approvals.json"
    config_file = write_config(tmp_path / "config.json")

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            "tail_momentum_overnight",
            "--config",
            str(config_file),
            "--dry-run",
        ]
    )

    assert exit_code == 2
    assert "approval" in capsys.readouterr().err


def test_paper_cli_dry_run_returns_machine_readable_plan(tmp_path, capsys, approval):
    approval_file = tmp_path / "approvals.json"
    config_file = write_config(tmp_path / "config.json")
    approval_file.write_text(
        json.dumps([asdict(approval)]), encoding="utf-8"
    )

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            approval.strategy_id,
            "--config",
            str(config_file),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document == {
        "strategy_id": "tail_momentum_overnight",
        "config_hash": "hash-1",
        "status": "DRY_RUN",
        "orders": [],
    }


def test_paper_cli_non_dry_run_uses_injected_execution_and_reports_fills(
    tmp_path, capsys, approval
):
    approval_file = tmp_path / "approvals.json"
    config_file = write_config(tmp_path / "config.json")
    approval_file.write_text(json.dumps([asdict(approval)]), encoding="utf-8")
    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            approval.strategy_id,
            "--config",
            str(config_file),
        ],
        execution=FixedExecution(),
        clock=FixedClock(datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)),
    )

    assert exit_code == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "PAPER_EXECUTED"
    assert document["orders"] == [
        {
            "symbol": "sh600176",
            "side": "buy",
            "quantity": 100,
            "status": "FILLED",
        }
    ]


def test_paper_cli_execution_cannot_bypass_persisted_approval(
    tmp_path, capsys, approval
):
    approval_file = tmp_path / "approvals.json"
    config_file = write_config(tmp_path / "config.json")
    approval_file.write_text(json.dumps([]), encoding="utf-8")
    execution = RecordingExecution()
    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            approval.strategy_id,
            "--config",
            str(config_file),
        ],
        execution=execution,
    )

    assert exit_code == 2
    assert "approval" in capsys.readouterr().err
    assert execution.called is False


def test_paper_cli_non_dry_run_fails_closed_without_executor(
    tmp_path, capsys, approval
):
    approval_file = tmp_path / "approvals.json"
    config_file = write_config(tmp_path / "config.json")
    approval_file.write_text(json.dumps([asdict(approval)]), encoding="utf-8")

    exit_code = main(
        [
            "--approvals",
            str(approval_file),
            "run",
            "--strategy",
            approval.strategy_id,
            "--config",
            str(config_file),
        ]
    )

    assert exit_code == 2
    assert "execution is not configured" in capsys.readouterr().err


class FixedExecution:
    def execute(self, strategy_id, config, run_at):
        return [
            {
                "symbol": "sh600176",
                "side": "buy",
                "quantity": 100,
                "status": "FILLED",
            }
        ]


class RecordingExecution:
    def __init__(self):
        self.called = False

    def execute(self, strategy_id, config, run_at):
        self.called = True
        return []
