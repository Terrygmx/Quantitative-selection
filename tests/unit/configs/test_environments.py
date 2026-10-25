"""Environment configurations: four declared environments, prod never
enables live execution, no secrets committed."""

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3] / "configs" / "environments"


@pytest.mark.parametrize("env", ["dev", "research", "paper", "prod"])
def test_environment_file_is_valid_json_with_known_keys(env):
    data = json.loads((ROOT / f"{env}.json").read_text(encoding="utf-8"))

    assert data["environment"] == env
    assert set(data["defaults"]) <= {
        "dry_run",
        "require_approval",
        "approvals_path",
        "log_level",
        "audit_sink",
        "audit_path",
        "note",
    }


def test_paper_and_prod_require_approval_and_prod_stays_dry_run():
    paper = json.loads((ROOT / "paper.json").read_text(encoding="utf-8"))
    prod = json.loads((ROOT / "prod.json").read_text(encoding="utf-8"))

    assert paper["defaults"]["dry_run"] is False
    assert paper["defaults"]["require_approval"] is True
    # DETAILED_DESIGN section 9: prod defaults to dry-run even when enabled.
    assert prod["defaults"]["dry_run"] is True
    assert prod["defaults"]["require_approval"] is True


def test_no_secrets_in_environment_files():
    for path in ROOT.glob("*.json"):
        text = path.read_text(encoding="utf-8").lower()
        for forbidden in ("password", "token", "api_key", "secret"):
            assert forbidden not in text, f"{path.name} mentions {forbidden}"
