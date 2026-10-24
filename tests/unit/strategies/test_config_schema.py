import json
from pathlib import Path

import pytest

from quant_agent.strategies.tail_momentum import strategy_from_config


SCHEMA = Path("src/quant_agent/strategies/tail_momentum/config.schema.json")


def test_schema_exists_and_describes_parameters():
    data = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert data["type"] == "object"
    assert data["required"] == ["lookback", "universe"]
    assert data["properties"]["lookback"]["minimum"] == 1
    assert data["properties"]["lookback"]["maximum"] == 5
    assert data["properties"]["universe"]["type"] == "array"


def test_strategy_validates_schema_configuration():
    valid = {"lookback": 2, "universe": ["sh600519"]}
    invalid = {"lookback": 6, "universe": ["sh600519"]}

    assert strategy_from_config(valid).lookback == 2
    with pytest.raises(ValueError, match="lookback"):
        strategy_from_config(invalid)


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({"lookback": 2}, "universe"),
        ({"universe": ["sh600519"]}, "lookback"),
        ({"lookback": "2", "universe": ["sh600519"]}, "lookback.*integer"),
        ({"lookback": 0, "universe": ["sh600519"]}, "lookback.*minimum"),
        ({"lookback": 6, "universe": ["sh600519"]}, "lookback.*maximum"),
        ({"lookback": 2, "universe": []}, "universe.*minItems"),
        ({"lookback": 2, "universe": [""]}, "universe.*minLength"),
        ({"lookback": 2, "universe": "sh600519"}, "universe.*array"),
        ({"lookback": 2, "universe": ["sh600519"], "extra": 1}, "unknown configuration keys"),
    ],
)
def test_strategy_configuration_rejection_matrix(config, match):
    with pytest.raises(ValueError, match=match):
        strategy_from_config(config)
