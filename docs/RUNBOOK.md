# 运行手册

## 环境准备

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
```

核心包运行时依赖仅 `jsonschema`（Agent 结构化输出校验）和 Python 标准库；测试、覆盖率、lint 和性能工具只属于开发依赖。

## 日常验证

```bash
python3 -m coverage run -m pytest --ignore=tests/performance
python3 -m coverage report --fail-under=90
python3 -m ruff check src/quant_agent tests
```

CI 使用相同流程，并额外编译遗留入口 `src/tail_momentum_selector.py` 和 `src/quant_agent` 全部源码。

## 模拟盘命令

模拟盘只接受已保存审批的策略配置。审批文件默认位于 `state/paper-approvals.json`，记录策略 ID、配置哈希和批准人；配置内容本身必须包含相同的 `config_hash`。

```bash
# 先检查及批准配置
PYTHONPATH=src python3 -m quant_agent.cli.paper \
  --approvals state/paper-approvals.json approve \
  --strategy tail_momentum_overnight \
  --config configs/tail_momentum.json \
  --approved-by operator

# 默认 dry-run：只返回空订单计划
PYTHONPATH=src python3 -m quant_agent.cli.paper \
  --approvals state/paper-approvals.json run \
  --strategy tail_momentum_overnight \
  --config configs/tail_momentum.json --dry-run

# 非 dry-run：必须由调用方注入执行器，否则 fail closed
PYTHONPATH=src python3 -m quant_agent.cli.paper \
  --approvals state/paper-approvals.json run \
  --strategy tail_momentum_overnight \
  --config configs/tail_momentum.json
```

`PaperGateway.run(dry_run=False)` 只有在构造时注入 `PaperExecution` 才会执行。非 dry-run 且未注入执行器时，CLI 会从配置的 `execution` 段构造 `SimulatedPaperExecution`；缺少该段则 fail closed，以免在没有交易通道和运行清单的情况下误发订单。退出码 `0` 表示成功，`2` 表示审批、配置或执行器错误。

### 默认模拟成交配置

非 dry-run 时配置需提供 `execution` 段，以及每个 `universe` 标的的 `market` 快照：

```json
{
  "config_hash": "hash-1",
  "universe": ["sh600176"],
  "market": {
    "sh600176": { "last": "10.05", "previous_close": "10.00", "tradable": true }
  },
  "execution": {
    "exchange": "SSE",
    "initial_cash": "100000.00",
    "commission_rate": "0.0003",
    "stamp_tax_rate": "0.0005",
    "slippage_rate": "0.001",
    "buy_quantity": 100,
    "instruments": [
      {
        "symbol": "sh600176",
        "exchange": "SSE",
        "board": "MainBoard",
        "status": "Active",
        "listing_date": "2010-01-01",
        "tick": "0.01",
        "lot_size": 100
      }
    ]
  }
}
```

模拟成交复用 `TradingRulesPlugin` 与订单状态机：非交易时段、停牌、涨跌停、非整手与 T+1 未结算卖出都会被拒绝并记录原因码；买入按滑点后价格并量化到最小价位，卖出额外计入印花税。只有配置 `universe` 内的标的会成为下单目标，`market` 中的额外标的只作为参考数据。

## 性能基准

基准用合成数据验证 3000 只股票 × 5 年（1260 个样本日）的多标的回测事件时钟：

```bash
python3 -m pytest tests/performance
```

当前基线（Apple Silicon 本机，2026-10-24）：约 70.5 秒。每次优化后重跑并更新本数字；如回归超过 10%，在合入前先定位热点。该测试不进入默认 CI，以免拖慢常规反馈。

## 测试分层

- `tests/unit`：领域规则、应用服务、策略插件、Agent 权限。
- `tests/contract`：Market Data Port 契约，后续 CSV/Parquet/DuckDB 适配器复用。
- `tests/performance`：规模化基准，显式单独运行。
- `tests/fixtures/legacy`：遗留策略行为锁定的脱敏夹具。
