"""`quant-agent agent review`: summarize gateway audit JSONL for reviewers."""

import json

from quant_agent.cli.agent import main


def event(agent_id, tool, status, reason_code=None):
    return {
        "run_id": "run-1",
        "agent_id": agent_id,
        "tool": tool,
        "status": status,
        "occurred_at": "2026-09-15T14:30:00+00:00",
        "model_id": "m-1",
        "reason_code": reason_code,
    }


def write(tmp_path, events):
    path = tmp_path / "audit.jsonl"
    path.write_text(
        "".join(json.dumps(item) + "\n" for item in events), encoding="utf-8"
    )
    return path


def test_agent_review_summarizes_by_status_and_agent(tmp_path, capsys):
    path = write(
        tmp_path,
        [
            event("research-1", "read_approved_dataset", "allowed"),
            event("research-1", "submit_order", "denied", "TOOL_NOT_ALLOWED"),
            event("dq-1", "silence_block", "denied", "ROLE_TOOL_NOT_ALLOWED"),
        ],
    )

    exit_code = main(["review", "--audit", str(path)])

    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["total"] == 3
    assert report["by_status"] == {"allowed": 1, "denied": 2}
    assert report["by_agent"]["research-1"] == {"allowed": 1, "denied": 1}
    assert len(report["denials"]) == 2
    assert report["denials"][0]["reason_code"] == "TOOL_NOT_ALLOWED"


def test_agent_review_fails_closed_on_malformed_lines(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")

    exit_code = main(["review", "--audit", str(path)])

    assert exit_code == 2
    assert capsys.readouterr().err.startswith("error:")
