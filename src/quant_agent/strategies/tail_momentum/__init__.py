from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from quant_agent.strategies.schema import validate_config
from quant_agent.strategies.tail_momentum.strategy import TailMomentumStrategy


SCHEMA_PATH = Path(__file__).with_name("config.schema.json")


def load_schema() -> dict[str, object]:
    with SCHEMA_PATH.open(encoding="utf-8") as schema_file:
        return json.load(schema_file)


def strategy_from_config(config: Mapping[str, object]) -> TailMomentumStrategy:
    validate_config(config, load_schema())
    return TailMomentumStrategy.from_config(config)
