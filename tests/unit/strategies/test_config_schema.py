import json
from pathlib import Path

import pytest

from quant_agent.strategies.tail_momentum import TailMomentumStrategy


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

    assert TailMomentumStrategy.from_config(valid).lookback == 2
    with pytest.raises(ValueError, match="lookback"):
        TailMomentumStrategy.from_config(invalid)
