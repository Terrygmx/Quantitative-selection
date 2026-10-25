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

    _FREQUENCIES = {252: "daily", 52: "weekly", 12: "monthly"}

    def summary(self, periods_per_year: int | None = None) -> dict[str, float | int]:
        if periods_per_year is None:
            periods_per_year = 1
            frequency = "sample"
        else:
            if periods_per_year not in self._FREQUENCIES:
                frequencies = ", ".join(str(item) for item in sorted(self._FREQUENCIES))
                raise ValueError(
                    f"unsupported sample frequency: {periods_per_year}; expected one of {frequencies}"
                )
            frequency = self._FREQUENCIES[periods_per_year]
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
                sell_price = fill["price"]
                buy_price = previous_fill["price"]
                if not (
                    isinstance(sell_price, (int, float, Decimal))
                    and isinstance(buy_price, (int, float, Decimal))
                ):
                    raise ValueError("fill prices must be numeric to compute win rate")
                if sell_price > buy_price:
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
            "sharpe": sharpe * periods_per_year**0.5,
            "sample_frequency": frequency,
            "win_rate": win_rate,
            "turnover": turnover,
            "fill_count": len(self.fills),
        }
