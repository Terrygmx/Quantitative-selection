import json
from pathlib import Path

import pytest

from quant_agent.strategies.tail_momentum import strategy_from_config


SCHEMA = Path("src/quant_agent/strategies/tail_momentum/config.schema.json")


def test_schema_exists_and_describes_parameters():
    data = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert data["type"] == "object"
    assert data["required"] == ["universe"]
    assert data["properties"]["universe"]["type"] == "array"


def test_strategy_validates_schema_configuration():
    valid = {"universe": ["sh600519"]}
    invalid = {"universe": []}

    assert strategy_from_config(valid).warmup() == 25
    with pytest.raises(ValueError, match="universe"):
        strategy_from_config(invalid)


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({}, "universe"),
        ({"universe": []}, "universe.*minItems"),
        ({"universe": [""]}, "universe.*minLength"),
        ({"universe": "sh600519"}, "universe.*array"),
        ({"universe": ["sh600519"], "lookback": 2}, "unknown configuration keys"),
    ],
)
def test_strategy_configuration_rejection_matrix(config, match):
    with pytest.raises(ValueError, match=match):
        strategy_from_config(config)
