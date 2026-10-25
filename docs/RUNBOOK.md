# 运行手册

## 环境准备

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
```

核心包运行时依赖仅 `jsonschema`（Agent 结构化输出校验）和 Python 标准库；测试、覆盖率、lint 和性能工具只属于开发依赖。Parquet 数据适配器需要可选依赖 `pyarrow`，DuckDB 适配器需要可选依赖 `duckdb`（缺失时对应构造抛 `ValueError`，CSV 与内存适配器不受影响）。

## 数据适配器

`InMemoryMarketDataPort`、`CsvMarketDataPort`、`ParquetMarketDataPort`、`DuckDBMarketDataPort` 实现同一 PIT 契约（`tests/contract/test_market_data_port.py` 参数化四套实现：未来数据不可见、同时间戳取最新可见修订、缺数据 fail closed 抛 `DataUnavailable`）。文件适配器的列要求：`instrument,timestamp,open,high,low,close,volume` 必填，`amount,available_at` 可选（时间戳必须带时区）；缺文件、缺列、坏数值、无时区时间戳均按行号报 `ValueError`。Parquet 需可选依赖 `pyarrow`，DuckDB 需可选依赖 `duckdb`（缺失时构造抛 `ValueError`；两者均已列入 requirements-dev 由 CI 覆盖；DuckDB 的 `bars` 表使用 TIMESTAMPTZ 列）。

## 日常验证

```bash
python3 -m coverage run -m pytest --ignore=tests/performance
python3 -m coverage report --fail-under=90
python3 -m ruff check src/quant_agent tests
python3 -m mypy src/quant_agent
```

CI 使用相同流程（含 mypy 阻断），并额外编译遗留入口 `src/tail_momentum_selector.py` 和 `src/quant_agent` 全部源码。

## 外部交易日历（2027 及以后）

内置静态日历只覆盖 2023–2026。之后的年份（以及对已发布年份的勘误）以数据文件供给，格式为每行一个 ISO 日期，空行与 `#` 注释行允许；空数据集、非法行、不可读文件都会 fail closed 抛 `ValueError`：

```text
# configs/calendars/sse-2027.txt
2027-01-04
2027-01-05
```

```python
from quant_agent.adapters.calendar import FileCalendarSource

calendar = FileCalendarSource("configs/calendars/sse-2027.txt").extend_builtin()
rules = TradingRulesPlugin(calendar)
```

`load()` 只用文件数据构建日历；`extend_builtin()` 把文件合并进内置 2023–2026 数据。未提供数据文件的年份保持「非交易日」而不是猜测节假日。

## 策略与回测命令

```bash
# 列出已注册的策略插件（显式注册表，JSON 输出）
PYTHONPATH=src python3 -m quant_agent.cli.strategy list

# 对 CSV 日线跑多标的回测（同一共享成交内核与 A 股规则）
PYTHONPATH=src python3 -m quant_agent.cli.backtest run \
  --bars bars.csv --instruments instruments.json --config costs.json \
  [--exchange SSE] [--start 2026-01-01] [--end 2026-06-30] [--split 2026-04-01]

# 渲染信号 JSON 产物为文本
PYTHONPATH=src python3 -m quant_agent.cli.report show --file signals.json

# 汇总 Agent 网关审计（按状态/Agent 计数 + 拒绝明细）
PYTHONPATH=src python3 -m quant_agent.cli.agent review --audit audit.jsonl
```

`--start/--end` 为闭区间日期过滤；`--split` 输出 `in_sample`（< split）/`out_of_sample`（≥ split）两段独立回测；`--window N` 输出连续滚动窗口逐段回测；`--benchmark SYMBOL` 用同一份 bars 计算该标的买入持有收益并给出 `excess_return`（FR-3.1）。

**分钟频模式**（FR-3.1）：`--frequency minute --decision HHMM`（默认 1431，尾盘动量快照语义）。每个交易日按决策时刻取**不晚于该时刻的最后一根分钟 bar** 定价（晚于决策时刻的 bar 由 PIT 构造保证不可见），经共享成交内核与规则校验（分钟级时间戳会真实命中午休/时段/盘后定价窗口）；当日决策前无 bar 的标的跳过。CSV 的 `available_at` 必须等于 bar 时间戳（事件时间可见性）方可重放；`--start/--end/--split/--window` 为日频专用，与分钟模式互斥。

`--bars` 使用数据适配器的 CSV 列契约（见「数据适配器」）；`--instruments` 为 `Instrument` 字段的 JSON 数组；`--config` 提供 `initial_cash/buy_quantity/commission_rate/stamp_tax_rate/slippage_rate`，可选 `fill_model`（`slippage` 默认／`next_open` 按参考开盘价无滑点／`vwap` 按成交额÷成交量、bar 缺 `amount`/`volume` 时 fail closed；模拟盘配置 `PaperExecutionConfig` 同名字段同语义，`vwap` 在仅有点位快照的模拟盘不可用）。输出 orders/fills/summary JSON；配置错误退出码 2。

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

### 涨跌停排队成交

`ExecutionCore` 支持锁板排队模型（`board_queue_policy`）：默认 `reject` 保持保守行为（排队侧拒绝对手侧可成交）；`queue_fill` 下规则层仍裁决锁板，快照带 `board_volume`（锁板期间对手盘量）且覆盖整单数量时按板价成交（正常费用/现金/T+1），量不足拒 `BOARD_QUEUE_UNFILLED`，无量数据回退原拒绝（fail closed）。日频引擎从 bar 的 `board_volume` 列读取，模拟盘从 market 快照的 `board_volume` 字段读取。无部分成交（订单状态机无该状态）；涨停买入排队需 T+1 才可卖出，与普通买入一致。解锁打板/涨停动量类策略的回测与模拟。

### 盘后定价交易

策略配置可加顶层 `"session": "after_hours_fixed"`（缺省 `continuous`，行为不变；非法值 fail closed 退出码 2）。该会话仅支持科创板/创业板标的：

- 盘中（9:30–11:30、13:00–15:30）申报进延迟撮合队列（`QUEUED_AFTER_HOURS`，不动现金持仓）；
- 15:05–15:30 内再次运行时按当时快照的 `last`（即收盘价）无滑点撮合，撮合结果带 `submitted_at` 与原意图 id；
- 意图按日有效：次日运行时报 `EXPIRED`；盘中运行不会触发撮合，队列意图绝不会以连续竞价价格成交。

## 环境与部署

四套环境配置在 `configs/environments/{dev,research,paper,prod}.json`：dev/research 免审批且恒 dry-run；paper 为唯一非 dry-run 环境且强制审批（`state/paper-approvals.json`）；**prod 即使启用也默认 dry-run**（§9），强制审批。配置文件不含密钥（有测试锁定）。

单机部署：`docker build -t quant-selection:paper . && docker compose up paper`（compose 默认执行 dry-run 命令；审批账本挂载于 `paper-state` 卷）。镜像内入口 fail closed：无审批账本则退出码 2。

实机构建已验证（2026-10-25，python:3.11-slim）：镜像构建成功；容器内五个 CLI 模块全部可导入；`strategy list` 输出五个插件；无审批运行 fail closed（退出码 2）；`approve` → `run --dry-run` 全流程闭环（DRY_RUN 空订单，退出码 0）。

## 性能基准

基准用合成数据验证 3000 只股票 × 5 年（1260 个样本日）的多标的回测事件时钟：

```bash
python3 -m pytest tests/performance
```

当前基线（Apple Silicon 本机，2026-10-25）：约 67–84 秒（同日多次测量随机器负载波动：空闲约 67 秒，繁忙约 84 秒；共享成交内核重构经热点定位后与重构前提交持平）。每次优化后重跑并更新本数字；如回归超过 10%，在合入前先定位热点。该测试不进入默认 CI，以免拖慢常规反馈。

## 测试分层

- `tests/unit`：领域规则、应用服务、策略插件、Agent 权限。
- `tests/contract`：Market Data Port 契约，后续 CSV/Parquet/DuckDB 适配器复用。
- `tests/performance`：规模化基准，显式单独运行。
- `tests/fixtures/legacy`：遗留策略行为锁定的脱敏夹具。
