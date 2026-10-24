# A 股多策略 Agent 量化平台：详细设计

## 1. 架构决策

采用“六边形领域核心 + 插件 + 事件运行时”。策略和 Agent 都是上层消费者；领域核心不依赖数据供应商、LLM 或命令行。

```text
数据供应商 / CSV / 现有 westock
          │ adapters
          ▼
 Raw Store → Data Quality → PIT Data Portal ─┬→ Strategy Plugins
                                              │       │ Signal
                                              └→ Feature Store
                                                      ▼
                   Agent Workspace ← Audit ← Signal Composer → Portfolio & Risk
                                                              │ Target / Order
                                                              ▼
                                                  Backtest / Paper Broker
                                                              │
                                                Ledger + Metrics + Reports
```

## 2. 推荐目录与依赖方向

```text
src/quant_agent/
  domain/        # 值对象、订单状态、规则接口；零 IO
  application/   # 用例：运行策略、回测、模拟盘、生成报告
  ports/         # MarketData、Calendar、Broker、Artifact、Agent 接口
  adapters/      # westock、文件、DuckDB/Parquet、报告、LLM
  strategies/    # 内置策略插件；每个策略独立目录
  rules/         # A 股市场与交易规则插件
  agents/        # 有界工具、提示模板、审计记录
  cli/           # Typer 命令
tests/
  unit/ contract/ integration/ regression/ fixtures/
configs/
  environments/ strategies/ portfolios/ rules/
```

依赖只能从外向内。`domain` 不得 import `pandas`、数据库 SDK、HTTP、LLM SDK 或当前遗留脚本。

## 3. 领域模型

| 模型 | 关键字段 | 不变量 |
|---|---|---|
| `Instrument` | symbol、board、status、listing_date、tick、lot_size | 市场和板块不可为空 |
| `Bar` | instrument、timestamp、open/high/low/close、volume、amount、as_of | `as_of >= timestamp`；不接受未来可见数据 |
| `Signal` | strategy_id、version、symbol、side、target_weight、confidence、valid_from/to、evidence | 权重在 [-1,1]；首期 long-only |
| `Order` | id、symbol、side、quantity、limit_price、created_at | 数量为整手；卖出不超过可卖数量 |
| `Fill` | order_id、price、quantity、fee、timestamp | 成交价在规则允许范围内 |
| `Position` | symbol、settled_qty、unsettled_buy_qty、cost | 当日买入进入不可卖队列 |
| `RunManifest` | run_id、git_sha、config_hash、data_snapshot、seed | 产物不可脱离清单存在 |

## 4. 插件契约

用 Python entry point 或显式注册表发现插件；首期选择显式注册表以便 Vibe Coding 审查清晰，后续再升级 entry point。策略绝不直接读文件或发网络请求。

```python
class Strategy(Protocol):
    metadata: StrategyMetadata

    def validate(self, config: Mapping[str, object]) -> None: ...
    def warmup(self, config: Mapping[str, object]) -> int: ...
    def on_snapshot(self, ctx: StrategyContext) -> list[Signal]: ...

class TradingRules(Protocol):
    def session(self, instrument: Instrument, day: date) -> TradingSession: ...
    def tradeability(self, instrument: Instrument, as_of: datetime) -> Decision: ...
    def price_limits(self, instrument: Instrument, previous_close: Decimal,
                     day: date) -> PriceBand | None: ...
    def validate_order(self, order: Order, portfolio: Portfolio,
                       market: MarketSnapshot) -> list[Rejection]: ...
```

`StrategyContext` 仅提供经过 `as_of` 截断的只读数据查询；记录每次查询的字段和时间范围，作为反未来函数审计证据。

## 5. 数据、特征和 Point-in-Time

1. Raw：原始响应不可改写，按 `source/date/request_hash` 保存。
2. Normalized：统一代码、交易所时区、复权和字段单位，保留 `source_timestamp`、`ingested_at`、`available_at`。
3. Curated：经质量规则通过的可回测数据，使用 Parquet 分区；元数据和运行索引用 DuckDB。
4. Feature：`feature_name`、参数哈希、计算时点、输入数据版本；禁止覆盖不同定义的同名特征。
5. 旧版 `westock` 只作为 `WestockMarketDataAdapter`，其 Markdown 解析和缓存响应被契约测试锁定。

数据质量状态为 `pass/warn/block`。`block` 会阻止信号进入组合层；`warn` 需在报告显著展示。

## 6. 策略与组合

每个策略目录包含 `strategy.py`、`config.schema.json`、`README.md`、单元测试和基准夹具。初始策略序列：

1. `tail_momentum_overnight`：把当前策略改为纯信号插件，不带报告和 CLI。
2. `trend_breakout`：日频趋势/突破，持有期多日。
3. `mean_reversion_liquid`：高流动性股票短周期均值回归。
4. `low_vol_quality` 或 `industry_rotation`：作为与动量低相关的中低频策略。

`SignalComposer` 先做标准化，再按策略预算、状态门控、置信度和相关性预算形成 `TargetPosition`。`RiskManager` 是最终否决者，输出 `accepted/reduced/rejected` 和原因码；执行层只能接收已批准目标。

## 7. 回测与模拟成交

回测按事件时钟推进：`SESSION_OPEN → BAR_AVAILABLE → STRATEGY_RUN → TARGET → RISK → ORDER → FILL → SESSION_CLOSE`。每一步都以当前 `as_of` 构造数据视图。

成交器配置可替换：下一根开盘、VWAP、参与率限制和保守滑点。无交易、停牌、封板、价格带、整手、T+1、费用和现金不足均由规则层决定。回测严禁“当根收盘生成且按当根收盘成交”，除非策略显式在该收盘前可观察且成交模型有该能力。

## 8. Agent 设计与权限

| Agent | 允许工具/输出 | 明确禁止 |
|---|---|---|
| 研究 Agent | 读取已批准数据集；生成实验草案、解释 | 写生产配置、下单 |
| 数据质量 Agent | 读取质量报告；创建质量事件 | 修改原始数据、静默放行 block |
| 风险审阅 Agent | 读取信号、组合和规则；给出说明 | 覆盖风险决策 |
| 开发 Agent | 在开发分支创建插件草案、测试、文档 | 合并、发布、访问密钥 |

所有 Agent 调用都通过 `AgentGateway`：输入脱敏、工具 allowlist、预算/超时、结构化输出 Schema、审计事件。生产运行只接受人工批准的策略/配置版本；Agent 输出的自然语言不是执行指令。

## 9. 配置、可观测性和安全

- 每次运行写 `RunManifest`、事件日志、数据血缘、配置快照、指标和报告。
- `dev`、`research`、`paper`、`prod` 四套环境；`prod` 即使未来启用，也默认 dry-run。
- 密钥来自环境变量或密钥管理服务；日志不得打印令牌、账户、完整持仓或个人资料。
- 部署开始采用单机 Docker Compose；任务调度和数据存储接口预留，避免过早引入微服务。

## 10. 技术选型

Python 3.11+、`pytest`、`hypothesis`、`pydantic`、`polars`、`DuckDB`、`Typer`、`structlog`。将这些显式声明到新依赖文件并锁定版本；不要让现有“标准库零依赖”的遗留脚本被悄然改变。测试夹具可用 CSV/Parquet，小样本优先。

## 11. 迁移路径

1. 为现有脚本提取固定输入/输出夹具，先锁住当前可接受行为。
2. 先建领域值对象、时间数据门户和 A 股规则，再建回测器。
3. 仅迁移尾盘策略的纯计算逻辑，结果与遗留样本逐项比对。
4. 在新平台稳定后，把遗留脚本降级为兼容入口；不要一次性删除。
