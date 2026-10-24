from __future__ import annotations

from datetime import datetime

from quant_agent.adapters.market_data import InMemoryMarketDataPort


class StrategyContext:
    def __init__(self, data_port: InMemoryMarketDataPort, as_of: datetime):
        self.data_port = data_port
        self.as_of = as_of
