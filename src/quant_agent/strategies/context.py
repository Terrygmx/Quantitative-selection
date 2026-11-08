from __future__ import annotations

from datetime import datetime

from quant_agent.ports.market_data import MarketDataPort


class StrategyContext:
    def __init__(self, data_port: MarketDataPort, as_of: datetime):
        self.data_port = data_port
        self.as_of = as_of
