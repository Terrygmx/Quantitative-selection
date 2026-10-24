from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    initial_cash: Decimal
    final_equity: Decimal
    equity_curve: tuple[Decimal, ...] | list[Decimal]
    fills: tuple[Mapping[str, object], ...] | list[Mapping[str, object]]

    def summary(self) -> dict[str, float | int]:
        total_return = float((self.final_equity - self.initial_cash) / self.initial_cash)
        peak = self.equity_curve[0]
        max_drawdown = 0.0
        returns: list[float] = []
        previous = self.equity_curve[0]
        for equity in self.equity_curve[1:]:
            peak = max(peak, equity)
            drawdown = float((peak - equity) / peak)
            max_drawdown = max(max_drawdown, drawdown)
            returns.append(float((equity - previous) / previous))
            previous = equity
        mean_return = sum(returns) / len(returns) if returns else 0.0
        variance = (
            sum((item - mean_return) ** 2 for item in returns) / len(returns)
            if returns
            else 0.0
        )
        sharpe = mean_return / variance**0.5 if variance else 0.0

        profitable = 0
        considered = 0
        for index in range(1, len(self.fills)):
            previous_fill = self.fills[index - 1]
            fill = self.fills[index]
            if previous_fill["side"] == "buy" and fill["side"] == "sell":
                considered += 1
                if fill["price"] > previous_fill["price"]:
                    profitable += 1
        win_rate = profitable / considered if considered else 0.0

        traded_value = sum(
            Decimal(str(fill["quantity"])) * Decimal(str(fill["price"]))
            for fill in self.fills
        )
        turnover = float(traded_value / self.initial_cash)
        return {
            "total_return": total_return,
            "max_drawdown": max_drawdown,
            "sharpe": sharpe,
            "win_rate": win_rate,
            "turnover": turnover,
            "fill_count": len(self.fills),
        }
