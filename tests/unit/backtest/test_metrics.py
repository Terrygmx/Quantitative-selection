from decimal import Decimal

import pytest

from quant_agent.application.metrics import BacktestMetrics


@pytest.fixture
def metrics():
    return BacktestMetrics(
        initial_cash=Decimal("10000.00"),
        final_equity=Decimal("11000.00"),
        equity_curve=[
            Decimal("10000.00"),
            Decimal("10500.00"),
            Decimal("9900.00"),
            Decimal("11000.00"),
        ],
        fills=[
            {"side": "buy", "quantity": 100, "price": Decimal("10.00")},
            {"side": "sell", "quantity": 100, "price": Decimal("11.00")},
            {"side": "buy", "quantity": 100, "price": Decimal("10.00")},
            {"side": "sell", "quantity": 100, "price": Decimal("9.00")},
        ],
    )


def test_return_drawdown_and_sharpe(metrics):
    report = metrics.summary()

    assert report["total_return"] == pytest.approx(0.10)
    assert report["max_drawdown"] == pytest.approx(0.0571428571)
    assert report["sharpe"] > 0


def test_win_rate_turnover_and_fill_report(metrics):
    report = metrics.summary()

    assert report["win_rate"] == pytest.approx(0.5)
    assert report["turnover"] == pytest.approx(0.4)
    assert report["fill_count"] == 4
