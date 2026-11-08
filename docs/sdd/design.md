# A 股多策略 Agent 量化平台：系统设计

> 文档版本：1.0.7
> 基线日期：2026-10-29
> 对应提案：`docs/sdd/proposal.md` 1.0.5
> 最后复核：2026-11-08
> 状态：已实现基线与目标边界并存；每个“当前实现”与“后续演进”均显式标注。

## 1. 设计目标

本设计把系统分为“确定性交易内核”和“有界智能层”：

- 确定性内核负责数据可见性、策略计算、规则裁决、成交、账本、指标和审计。
- 智能层负责研究辅助、解释、质量检查和开发协作，不能替代规则层或直接触发执行。
- 回测与模拟盘共享同一策略契约、规则插件和成交内核。
- 所有关键边界通过结构化对象和 fail-closed 行为表达，而不是依赖调用者自觉。

## 2. 总体架构

```text
                    ┌──────────────────────────────┐
                    │ CLI / Python 调用方           │
                    │ strategy/backtest/paper/...  │
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
     ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
     │ Strategy       │   │ Backtest /     │   │ Agent Gateway  │
     │ Registry       │   │ Paper Runner   │   │ + Roles        │
     └───────┬────────┘   └───────┬────────┘   └───────┬────────┘
             │                    │                    │
             ▼                    ▼                    ▼
     ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
     │ Strategy       │   │ ExecutionCore  │   │ Audit / Tools  │
     │ Plugins        │   │ + Order FSM    │   │ + Prompts      │
     └───────┬────────┘   └───────┬────────┘   └───────┬────────┘
             │                    │                    │
             └────────────┬───────┴────────────┬───────┘
                          ▼                    ▼
                 ┌────────────────┐   ┌────────────────┐
                 │ TradingRules   │   │ PIT Data Port  │
                 │ + Calendar     │   │ + Quality      │
                 └────────────────┘   └───────┬────────┘
                                              │
                          ┌───────────────────┼───────────────────┐
                          ▼                   ▼                   ▼
                    InMemory/CSV        Parquet/DuckDB        westock
                          │                   │                   │
                          └───────────────────┴───────────────────┘
                                              │
                                     Raw/Curated/Feature
```

### 2.1 依赖方向

目标依赖规则：

```text
domain       ← rules       ← application       ← cli
domain       ← strategies  ← application
domain       ← agents      ← cli
adapters     ← application/cli（只通过端口或稳定数据模型）
```

- `domain` 只包含值对象、协议和纯逻辑，不读文件、不发网络请求、不依赖数据库。
- `rules` 是交易规则的唯一裁决者，只依赖 `domain` 和日历协议。
- `application` 组织用例，不得复制规则或成交账本。
- `strategies` 只产生 `Signal`，不得直接下单或写生产配置。
- `agents` 通过 Gateway 和工具白名单访问只读数据或草稿区。
- `adapters` 负责供应商、文件格式、CLI 和持久化细节。
- `cli` 只做参数解析、依赖组装、JSON/文本输出和退出码映射。

### 2.2 端口边界

`ports` 包只承载跨层协议、端口数据契约和端口异常：

- `ports.market_data` 定义 `MarketDataPort`、`Bar`、`QualityEvent` 和 `DataUnavailable`。
- `ports.clock` 定义 `Clock`、`SystemClock` 和 `FixedClock`。
- `application` 与 `strategies` 只依赖端口或领域模型，不得直接导入 `adapters.market_data`。
- 适配器实现端口契约，并可从旧模块路径兼容导出，但对外新代码使用 `ports`。

## 3. 模块地图

```text
src/quant_agent/
  ports/
    market_data.py  # MarketDataPort、Bar、QualityEvent、DataUnavailable
    clock.py        # Clock、SystemClock、FixedClock
  domain/
    models.py       # Instrument、Signal、Order、RunManifest
  rules/
    calendar.py     # 交易日历协议、静态 2023–2026、外部文件日历
    trading.py      # 交易时段、涨跌停、T+1、整手、tick、盘后定价
    references.py   # 规则官方来源登记
  application/
    execution.py    # 共享成交内核、费用、滑点、现金、持仓
    orders.py       # 订单状态机
    backtest.py     # 日频多标的引擎与金样引擎
    intraday.py     # 分钟频引擎
    grid.py         # 网格驻留限价单引擎
    portfolio.py    # 信号合成与组合风险约束
    metrics.py      # 收益、回撤、夏普、胜率、换手
    data_layers.py  # RawStore, CuratedStore
    features.py     # FeatureStore, PersistentFeatureStore
    runs.py         # RunManifestFactory
    portfolio.py    # SignalAdapter、SignalComposer、组合风险约束
  adapters/
    market_data.py  # 内存/CSV/Parquet/DuckDB PIT 端口与质量事件
    westock.py      # westock Markdown/缓存/在线适配器
    normalize.py    # 代码、时区、复权口径标准化
    calendar.py     # 外部日历文件源
  strategies/
    registry.py     # 插件注册、启停、版本历史、回滚、崩溃隔离
    context.py      # 策略上下文
    schema.py       # 零依赖配置 Schema 校验
    reporting.py    # 文本/HTML 报告
    tail_momentum/  # 尾盘动量
    trend_breakout/
    mean_reversion/
    low_vol_quality/
    industry_rotation/
  agents/
    gateway.py      # 工具白名单、审计、输出校验
    roles.py        # 四角色权限边界
    role_tools.py   # 只读数据、草稿、质量事件、解释工具
    prompts.py      # 角色提示词模板
    paper.py        # 模拟盘审批、Gateway、模拟成交、盘后队列
  cli/
    strategy.py
    backtest.py
    paper.py
    report.py
    agent.py
```

`src/tail_momentum_selector.py` 是冻结的兼容入口和行为金样来源：

- 保留原 CLI、报告、看板和复盘能力。
- 新平台不得从旧脚本导入内部实现。
- 旧脚本输出可用于回归对照，但不得成为新领域模型的依赖。

## 4. 核心领域模型与不变量

| 模型 | 关键字段 | 不变量 |
|---|---|---|
| `Instrument` | symbol, exchange, board, status, listing_date, tick, lot_size | 标识非空；tick 为十进制；lot_size > 0 |
| `Bar` | instrument, timestamp, OHLCV, amount, available_at, adjustment | `available_at >= timestamp` |
| `Signal` | strategy_id, version, symbol, side, target_weight, confidence, valid_from/to, evidence | side 为 long/short；权重 [-1,1]；置信度 [0,1]；有效期有序 |
| `Order` | id, symbol, side, quantity, limit_price, created_at, session | 数量 > 0；价格 > 0；session 合法；数量满足整手或合法零股卖出 |
| `RunManifest` | run_id, git_sha, config_hash, data_snapshot, seed, created_at | 字段非空；内容哈希可重算并校验 |
| `MarketSnapshot` | instrument, last, previous_close, tradable, board_volume | 是订单校验的唯一市场入参 |
| `QualityEvent` | level, reason_code, symbol, as_of, message | level 为 pass/warn/block |
| `RiskDecision` | symbol, status, net_weight, reason_code | 每个目标都有不可变决策 |

核心账本中的金额和价格使用 `Decimal`；CLI 订单价格、费用和成本配置中的 Decimal 序列化为 JSON 字符串，避免二进制浮点误差。`Bar` 的 OHLCV、`Signal.target_weight`、`BacktestSummary` 的指标和遗留信号分数仍按现有契约使用 JSON number，详见 `docs/sdd/api-spec.yaml`。

## 5. 运行时数据流

### 5.1 遗留尾盘扫描

```text
westock-tool filter
        │ candidates
        ▼
westock quote/kline/minute/changedist/profile
        │
        ▼
快照截断 + 因子评分 + 硬条件过滤
        │
        ├── report_<date>.txt
        ├── signals_<date>.json
        └── dashboard_<date>.html
```

防未来规则：

- 决策时刻由 `--snapshot HHMM` 指定。
- 当日日线收盘行必须用快照时点的分时价格覆盖。
- 14:30 场景须显式指定 `--snapshot 1430`（遗留入口）或 `--decision 1430`（新回测 CLI）；新回测 CLI 的默认值是 `1431`。任何决策时刻都不得读取之后的数据。
- 收盘后运行是回放验证，不是使用未来数据的许可。

### 5.2 策略插件

```text
StrategyRegistry
    │ on_snapshot(StrategyContext)
    ▼
Strategy Plugin
    │ list[Signal]
    ▼
SignalAdapter
    │ ComposerSignal + adapter RiskDecision
    ▼
SignalComposer
    │ TargetPosition + RiskDecision
    ▼
Execution / Report / Audit
```

插件契约：

```python
class Strategy(Protocol):
    metadata: StrategyMetadata

    def on_snapshot(self, context: StrategyContext) -> Sequence[Signal]: ...
```

当前插件还必须提供：

- `from_config(config)`：配置解析与 Schema 校验。
- `warmup()`：最少历史窗口。
- 失败时抛出明确异常，由注册表隔离为 `PLUGIN_CRASH`。

当前五个插件：

| strategy_id | 频率 | 信号逻辑 |
|---|---|---|
| `tail_momentum_overnight` | intraday | 尾盘动量、量能、相对强弱、环境和风险综合评分 |
| `trend_breakout` | daily | 唐奇安突破 + 突破前 MA 上行过滤 |
| `mean_reversion_liquid` | daily | MA5 相对超跌、MA20 上方、流动性门槛 |
| `low_vol_quality` | daily | 低已实现波动、长均线上方、流动性门槛 |
| `industry_rotation` | daily | 行业代理动量排序，取正动量 Top-N |

`SignalAdapter` 是 `Signal` 进入组合层的唯一适配入口：

- 必须以关键字参数传入决策时刻 `as_of`，按 `valid_from <= as_of < valid_to` 过滤；未生效和过期信号分别产生 `SIGNAL_NOT_YET_VALID`、`SIGNAL_EXPIRED` 决策。
- 行业必须来自 `Signal.evidence["industry"]` 且为非空字符串；缺失时 fail closed，产生 `INDUSTRY_MISSING` 决策；输出行业去除首尾空白。
- 同一标的不同策略提供不同行业时，相关信号 fail closed，产生 `INDUSTRY_CONFLICT` 决策。
- 同一 `(strategy_id, symbol)` 只允许一条信号；重复时所有相关信号都产生 `DUPLICATE_STRATEGY_SIGNAL` 决策，避免覆盖权重导致追溯断裂。
- 适配后的输入保留 `strategy_id`、`version`、`symbol`、`side`、目标权重、有效期和 evidence；有效期为 ISO-8601 字符串。
- 适配决策携带 `strategy_id` 和 `version`，用于追溯被拒绝的信号。
- `SignalComposer.compose_domain()` 返回目标仓位、组合决策和适配决策；目标仓位额外携带每个策略的版本与 evidence。调用方 `as_of` 同时用于组合层时间敏感约束，不回退到 `max(valid_from)`。

### 5.3 回测

```text
bars.csv ──► CsvMarketDataPort ──► PIT visible bars
instruments.json ──► Instrument[]
costs.json ──► BacktestConfig
                    │
                    ▼
            日频 / 分钟频 / 网格引擎
                    │
                    ▼
               ExecutionCore
                    │
                    ▼
         orders + fills + summary JSON
```

当前 `backtest run` 是引擎级回测 CLI：

- 日频引擎按交易日推进，多标的在每个交易日产生买入订单。
- 分钟频引擎在每个交易日取不晚于 `--decision HHMM` 的最后一根 bar。
- 网格引擎在低高价之间驻留限价单。
- `--split`、`--window`、`--benchmark` 提供实验切分和比较。
- CLI 尚未读取策略插件，因此不能把当前命令描述为“策略插件端到端回测”。

### 5.4 模拟盘

```text
approval ledger ──┐
strategy config ──┼──► PaperGateway
config_hash ──────┘        │
                           ├── dry-run → DRY_RUN / []
                           └── execution
                                  │
                                  ▼
                         SimulatedPaperExecution
                                  │
                                  ▼
                            ExecutionCore
```

模拟盘约束：

1. 没有审批记录，拒绝。
2. 审批键是 `(strategy_id, config_hash)`，配置内容必须包含同一 `config_hash`。
3. dry-run 也必须有审批记录，只返回空订单计划。
4. 非 dry-run 必须有执行器；CLI 可从 `execution` 配置构造默认模拟执行器。
5. 配置缺 `universe`、`market`、instrument 元数据或执行参数时 fail closed。
6. 模拟盘和回测不得绕过 `TradingRulesPlugin` 或 `ExecutionCore`。

### 5.5 Agent

```text
AgentRequest
    │
    ▼
AgentGateway
    ├── 角色 allowlist
    ├── 全局 forbidden tools
    ├── 工具执行器
    ├── JSON Schema 输出校验
    └── AuditEvent → memory / JSONL
```

全局禁止工具：

- `submit_order`
- `write_production_config`
- `skip_data_quality_block`

角色边界：

| 角色 | 允许 | 禁止 |
|---|---|---|
| research | 读已批准数据、写实验草稿、解释信号 | 写生产配置、下单 |
| data_quality | 读质量报告、追加质量事件 | 修改原始数据、静默放行 block |
| risk_review | 读信号、读组合、解释拒绝 | 覆盖风险决策 |
| dev | 建插件/测试/文档草稿 | 合并、发布、访问密钥 |

Agent 的自然语言输出不是执行指令。任何执行都必须经过人工审批的配置和确定性规则层。

## 6. PIT、数据质量与存储

### 6.1 PIT 端口

统一接口：

```python
def bars(self, instrument: str, as_of: datetime) -> list[Bar]: ...
```

可见性规则：

- `bar.timestamp <= as_of`
- `bar.available_at <= as_of`
- 同一时间戳存在多个修订时，取 `available_at` 最新的可见版本
- 无可见数据时抛 `DataUnavailable`，不得返回空列表冒充成功

当前实现：

- `InMemoryMarketDataPort`
- `CsvMarketDataPort`
- `ParquetMarketDataPort`
- `DuckDBMarketDataPort`
- `WestockMarketDataAdapter`

CSV/Parquet/DuckDB 必填列：

```text
instrument,timestamp,open,high,low,close,volume
```

可选列：

```text
amount,available_at
```

时间戳必须带时区。文件/数据库解析错误按行号 fail closed。

### 6.2 数据分层

| 层 | 实现 | 责任 |
|---|---|---|
| Raw | `RawStore` | 原始响应按内容哈希追加存储，支持自愈与篡改检测 |
| Normalized | `src/quant_agent/adapters/normalize.py` | 统一代码、CN 时区、复权口径 |
| Curated | `CuratedStore` | 按 dataset/trade_date 写 Parquet，DuckDB 记录血缘 |
| Feature | `FeatureStore` | 定义哈希锁、值时间戳、持久化侧车 |

当前边界：

- 文件适配器尚未统一注入 `QualityEventCollector`。
- `warn` 级别事件尚未在所有报告中显著展示。
- 数据分层和特征存储尚未由 CLI 统一编排。

对应任务：`P-004`、`P-005`。

### 6.3 质量门

质量级别：

- `pass`：可用于信号。
- `warn`：允许继续，但报告必须提示。
- `block`：阻止受影响策略进入组合层。

`QualityEventCollector.blocked_strategy_ids()` 输出被阻断策略集合，`SignalComposer.compose(blocked_strategies=...)` 必须产生 `STRATEGY_BLOCKED` 决策。当前 API 已就绪，生产管线调用点仍待接线。

## 7. A 股规则与成交

### 7.1 规则唯一裁决

`TradingRulesPlugin` 负责：

- 交易日和交易时段
- 连续竞价与盘后固定价格交易
- 停牌/非活跃标的
- 最小价格变动 tick
- 买入整手、卖出零股剩余量
- 主板/科创板/创业板涨跌幅
- 新股前五个交易日无涨跌幅
- T+1 可卖数量
- 涨跌停排队语义

规则引用登记在 `src/quant_agent/rules/references.py`。未在线核对的规则必须保留 `verified_online=False` 和说明。

### 7.2 成交内核

`ExecutionCore` 是回测和模拟盘的唯一成交账本：

```text
submit → validate_order → fill/reject → cash/position update
```

费用：

- 买入：佣金
- 卖出：佣金 + 印花税

成交模型：

- `slippage`：按方向和滑点率调整，再量化到 tick。
- `next_open`：使用调用方给出的参考价。
- `vwap`：使用 `amount / volume`，缺字段 fail closed。

涨跌停队列：

- 默认 `reject`：排队侧拒绝。
- `queue_fill`：只有市场快照提供足够对手盘量时按板价成交，否则拒绝。

盘后定价：

- `session="after_hours_fixed"` 的订单可在规定申报窗口提交。
- 15:05–15:30 按收盘价无滑点撮合。
- 盘中只入队，跨日意图过期。

### 7.3 订单状态机

```text
PENDING ──► FILLED
   └─────► REJECTED
```

不允许从 FILLED/REJECTED 再次迁移，不允许同一 `order_id` 重复提交。当前不支持部分成交和撤单。

## 8. 组合与风险

`SignalComposer` 的处理顺序：

1. 过滤被质量门阻断的策略。
2. 按标的总和策略目标权重，形成唯一净目标。
3. 应用单票、行业、总仓位、流动性、回撤、黑名单和相关性预算。
4. 为每个目标生成不可变 `RiskDecision`。

决策状态：

- `accepted`
- `reduced`
- `rejected`

原因码包括：

```text
STRATEGY_BLOCKED
SINGLE_POSITION_LIMIT
INDUSTRY_LIMIT
LIQUIDITY_LIMIT
DRAWDOWN_FUSE
BLACKLIST
TOTAL_POSITION_LIMIT
CORRELATION_BUDGET
```

## 9. 配置与可观测性

### 9.1 配置

环境：

- `configs/environments/dev.json`
- `configs/environments/research.json`
- `configs/environments/paper.json`
- `configs/environments/prod.json`

策略：

- `configs/strategies/tail_momentum.json`
- `src/quant_agent/strategies/*/config.schema.json`

环境约束：

- `dev`/`research`：dry-run，免审批。
- `paper`：唯一默认非 dry-run，强制审批。
- `prod`：即使启用也默认 dry-run，强制审批。
- 环境配置不得包含密钥。

当前 CLI 尚未统一读取环境配置，环境文件主要由测试和部署入口使用。对应任务：`P-007`。

### 9.2 运行清单与审计

`RunManifest` 包含：

```text
run_id, git_sha, config_hash, data_snapshot, seed, created_at, content_hash
```

Agent 审计事件包含：

```text
run_id, manifest_hash, agent_id, tool, status, occurred_at,
model_id, arguments_sha256, arguments, output, reason_code
```

当前 `RunManifestFactory` 和审计 sink 已实现，但尚未强制接入每个 CLI 产物。对应任务：`P-005`。

## 10. 非功能设计

| 类别 | 设计 |
|---|---|
| 可复现 | 固定数据快照、配置哈希、版本、种子和 `RunManifest` |
| 可靠性 | 缺数据、非法配置、缺审批、缺执行器全部 fail closed |
| 安全 | 无实盘执行器；工具白名单；配置无密钥；审计只追加 |
| 性能 | 日频 3000×5 年基准；分钟频使用 prefetch 游标避免重复查询 |
| 可维护 | 显式注册表、配置 Schema、适配器契约测试、金样回归 |
| 可观测 | JSON CLI 输出、JSONL 审计、质量事件、报告免责声明 |

## 11. 关键设计决策（ADR）

### ADR-001 显式注册表优先于 entry point

- 决策：首期使用 `StrategyRegistry` 显式注册。
- 原因：审查路径清晰，测试可完全控制插件集合。
- 后果：新增插件需要修改默认注册函数；未来可增加 entry point 发现。

### ADR-002 规则层唯一裁决

- 决策：回测、网格、分钟频和模拟盘都必须调用 `TradingRulesPlugin`。
- 原因：避免各引擎复制或遗漏 A 股规则。
- 后果：新增交易能力先扩展规则和契约测试。

### ADR-003 成交账本单一来源

- 决策：所有非冻结执行路径使用 `ExecutionCore`。
- 原因：保证回测和模拟盘的费用、滑点、现金、持仓和 T+1 等价。
- 例外：`BacktestEngine` 金样引擎冻结为回归夹具。

### ADR-004 标准库优先，单一运行时依赖

- 决策：核心逻辑使用标准库；运行时第三方依赖仅 `jsonschema`。
- 原因：降低部署和审计成本。
- 可选依赖：Parquet 使用 `pyarrow`，DuckDB 使用 `duckdb`，缺失时对应适配器 fail closed。

### ADR-005 无实盘执行通道

- 决策：`agents` 包只暴露 `PaperExecution` 协议和 `SimulatedPaperExecution` 具体执行器。
- 原因：把 PRD 非目标变成结构约束。
- 后果：未来实盘必须显式修改测试并经过独立设计评审。

### ADR-006 静态日历加外部文件源

- 决策：内置 2023–2026 沪深共用日历；2027 及以后由文件提供。
- 原因：不猜测未公布节假日，同时保留可测试的默认行为。
- 后果：跨 2027 回测必须显式提供日历文件。

### ADR-007 回测与模拟盘共享内核，但不共享运行特权

- 决策：共享规则、成交和账本，不共享未来数据或回测便利接口。
- 原因：防止模拟盘依赖回测专属路径。
- 后果：模拟盘必须提供真实时点快照和配置审批。

## 12. 当前架构差距

| 编号 | 差距 | 影响 | 对应任务 |
|---|---|---|---|
| G-01 | 策略插件未接入回测 CLI | 无法端到端验证策略收益 | P-001 |
| G-02 | 策略插件未接入模拟盘 | 模拟盘只验证成交通道 | P-002 |
| G-04 | 质量事件未接入生产管线 | `block` 尚未自动阻断实际运行 | P-004 |
| G-05 | RunManifest/审计未强制写产物 | 运行级追溯不完整 | P-005 |
| G-07 | 环境配置未统一加载 | CLI 行为与声明环境可能不一致 | P-007 |
| G-08 | 高级成交参数未全部暴露到 CLI | Python API 与 CLI 能力不一致 | P-008 |
| G-09 | 模拟盘账本与运行历史未持久化 | 进程退出后无法恢复 paper account | P-013 |
| G-10 | 可选适配器开发依赖未锁定 | 全新隔离环境可能误报测试失败 | P-014 |
| G-11 | 旧 HTML 看板未转义供应商动态文本 | 不可信内容可注入结果页 | P-016 |
| G-12 | 注入式模拟执行器订单字段未归一化 | CLI 产物结构随执行器变化 | P-015 |
| G-13 | 审批账本覆写且无并发保护 | 审计历史与并发写入不可保证 | P-017 |

## 13. 验证矩阵

| 设计约束 | 测试证据 |
|---|---|
| PIT 可见性 | `tests/contract/test_market_data_port.py` |
| 端口结构契约 | `tests/contract/test_ports.py` |
| 分层边界 | `tests/unit/architecture/test_boundaries.py` |
| 分钟频防未来 | `tests/unit/backtest/test_minute_engine.py` |
| A 股规则 | `tests/unit/rules/test_trading_rules.py` |
| 共享成交 | `tests/unit/application/test_execution_core.py`、`tests/unit/backtest/test_execution_equivalence.py` |
| 组合风控 | `tests/unit/portfolio/test_composer.py` |
| Signal 适配契约 | `tests/unit/portfolio/test_signal_adapter.py` |
| 插件生命周期 | `tests/unit/strategies/test_registry.py`、`tests/unit/strategies/test_plugin_isolation.py` |
| Agent 边界 | `tests/unit/agents/test_gateway.py`、`tests/unit/agents/test_agent_roles.py` |
| 模拟盘审批 | `tests/unit/agents/test_paper_cli.py` |
| CLI 契约 | `tests/unit/cli/test_cli_commands.py` |
| 报告安全 | `tests/unit/strategies/test_reporting.py` |
| 环境与部署 | `tests/unit/configs/test_environments.py` |
| 性能 | `tests/performance/test_benchmark.py` |

## 14. 关联文档

- 范围与验收：`docs/sdd/proposal.md`
- 接口契约：`docs/sdd/api-spec.yaml`
- 任务与证据：`docs/sdd/task.md`
- 运行手册：`docs/RUNBOOK.md`

> 研究产物，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
