# A 股多策略 Agent 量化平台：SDD 提案

> 文档版本：1.0.12
> 基线日期：2026-10-29
> 基线提交：`7052b7e`
> 最后复核：2026-11-08
> 状态：已实现基线，持续演进；P-001 策略回测与 P-002 策略驱动模拟盘端到端已交付
> 本文是范围与验收的最高优先级来源；实现或测试与本文冲突时，先修订本文，再修订设计、接口契约和任务清单。

## 1. 背景

项目最初是一个单文件 A 股尾盘动量扫描器。它验证了尾盘因子、防未来函数、文本报告和 HTML 看板，但把数据获取、评分、选股、报告和复盘耦合在一个脚本中，无法安全扩展到多策略、回测、组合风控和模拟盘。

当前仓库已经完成平台化迁移的第一阶段：保留 `src/tail_momentum_selector.py` 作为行为基线，同时建立 `src/quant_agent/` 的分层架构、五个策略插件、PIT 数据端口、A 股交易规则、共享成交内核、日频/分钟频回测、组合风控、Agent 权限边界和模拟盘审批链路。

本提案要解决的核心问题是：把“能算出候选股的研究脚本”升级为“可复现、可审计、可扩展、默认不触碰实盘”的 A 股多策略研究平台。

## 2. 产品定位

建设面向 A 股现货的研究、回测和模拟交易平台：

- 策略以插件方式接入，不修改领域核心即可扩展。
- 数据查询遵循 Point-in-Time（PIT），策略只能看到 `as_of` 时点已可获得的数据。
- A 股规则由确定性规则层统一裁决，包括交易日、交易时段、涨跌停、整手、tick、停牌和 T+1。
- 回测与模拟盘共用成交内核，避免模拟盘获得“回测特权”。
- Agent 只做研究辅助、解释、质量检查和开发协作，不拥有下单、改生产规则、发布策略或删除数据的权限。
- 所有结论、回测和模拟盘结果都是研究产物，不构成投资建议。

## 3. 目标

### 3.1 首期目标

1. 支持五个独立策略插件：尾盘动量隔夜、趋势突破、流动性均值回归、低波动质量、行业轮动。
2. 提供统一 PIT 数据端口，并支持内存、CSV、Parquet、DuckDB 和 westock 数据源。
3. 提供可复现的日频、分钟频、网格回测，以及样本内/样本外、滚动窗口和基准比较。
4. 提供信号合成与组合风险约束，输出不可变风险决策记录。
5. 提供模拟盘审批、dry-run、配置哈希绑定和 fail-closed 执行链路。
6. 提供 Agent 工具白名单、角色边界、结构化输出校验和 JSONL 审计。
7. 提供 CLI、JSON 产物、文本报告和自包含 HTML 报告。
8. 用测试、覆盖率、Ruff、Mypy 和性能基准形成可执行的质量闸门。

### 3.2 后续目标

1. 把策略插件输出接入模拟盘，而不是只执行配置中的直接买入计划。
2. 将质量门、`RunManifest`、数据血缘和审计产物接入生产管线。
3. 补齐分钟频规模化基准、部分成交/撤单模型和外部日历年度数据。

## 4. 非目标

首期明确不做以下事项：

- 不接券商真实下单、资金划转、实盘账户或自动交易。
- 不承诺收益，不把规则估计包装成历史统计概率。
- 不覆盖期权、期货、港股、B 股、北交所、可转债和融资融券。
- 不让 LLM 直接决定仓位、绕过风控或修改生产配置。
- 不提供 HTTP/Web 服务；当前对外接口是 CLI、Python 协议、配置文件和研究产物。
- 不在本阶段实现柜台级撮合、完整订单簿、盘中撤单和复杂部分成交。

## 5. 用户与场景

| 用户 | 场景 | 期望结果 |
|---|---|---|
| 研究员 | 用固定数据和参数比较策略 | 相同输入、版本和种子产生相同结果 |
| 策略开发者 | 新增插件、配置 Schema 和测试 | 不改领域核心即可注册、启停和回滚 |
| 风控/审阅者 | 审阅信号、订单、拒绝原因和 Agent 产物 | 能追溯数据、规则、版本、审批和否决原因 |
| 操作员 | 运行日终或盘中模拟盘 | 缺数据、越权、停牌或不合规订单自动拒绝并留痕 |

## 6. 范围

### 6.1 已实现基线

| 能力 | 当前实现 |
|---|---|
| 领域模型 | `Instrument`、`Bar`、`Signal`、`Order`、`RunManifest`、时钟协议 |
| 数据端口 | 内存、CSV、Parquet、DuckDB、westock；统一 PIT 契约 |
| 数据分层 | RawStore 内容寻址、CuratedStore Parquet + DuckDB 元数据 |
| 特征存储 | 定义哈希锁、值时间戳、Parquet 持久化 |
| A 股规则 | 2023–2026 静态日历、外部日历文件、T+1、整手、tick、涨跌停、时段、盘后定价 |
| 成交内核 | 滑点、tick 量化、佣金、印花税、现金、持仓、订单状态机 |
| 回测 | 多标的日频、分钟频、网格、样本切分、滚动窗口、基准、JSON 输出；策略驱动编排器与 CLI |
| 策略插件 | 五个插件、配置 Schema、注册表启停/版本历史/回滚、插件崩溃隔离 |
| 组合风控 | 单票、行业、总仓位、流动性、回撤、黑名单、相关性预算、质量门 |
| Agent | 四角色 allow/forbid、工具执行体、JSON Schema 输出校验、审计事件 |
| 模拟盘 | 策略插件决策、组合风控、审批账本、配置/版本/数据快照绑定、dry-run、默认模拟执行、盘后定价队列 |
| 报告 | 新平台文本信号报告、自包含 HTML、免责声明、动态文本转义；旧版看板仅自包含并带免责声明 |
| 运维 | 四套环境配置、Dockerfile、Compose、运行手册 |
| 质量闸门 | P-002 交付时 514 个测试通过、1 个环境相关跳过、覆盖率 92%、Ruff/Mypy 通过 |

### 6.2 当前未闭环

以下事项不应被误认为已完成：

- `backtest run` 的默认 `engine` 模式仍直接驱动回测引擎；策略插件端到端能力由显式 `strategy` 模式提供，以数据快照、策略和行业映射配置作为输入。
- `paper run` 的底层执行器仍保留 `universe` 白名单接口；CLI 必须先由注册表产生信号，经组合风控形成目标，且只把 accepted/reduced 正权重目标传给该接口。
- 质量门已按 P-004 接入策略回测与模拟盘；`RunManifest` 和审计产物尚未统一接入每个 CLI 运行。
- 环境配置尚未被 CLI 统一加载；部分高级成交参数只在 Python API 中可注入。
- 模拟盘现金、持仓和运行历史目前是进程内状态，尚未持久化为跨进程 paper account；审批账本是全量覆写而非原子追加。
- 全新隔离环境仅按现有开发依赖安装时，DuckDB/Parquet 可选适配器测试缺少 `pytz`/`pyarrow`；补齐后测试通过，依赖声明待锁定。
- 冻结的 `src/tail_momentum_selector.py` 旧 HTML 看板未对供应商名称和排除原因做 HTML 转义，存在不可信内容注入风险。
- `PaperExecution` 协议允许注入精简订单映射，CLI 会原样输出；完整订单字段只由默认模拟执行器保证。
- `.github/workflows/ci.yml` 包含性能基准，而 `docs/RUNBOOK.md` 称性能基准不进入默认 CI，策略待统一。
- 分钟频尚未建立与日频同等规模的性能基准。

这些差距在 `docs/sdd/task.md` 中以 `P-*` 任务登记。策略驱动模拟盘已由 P-002 交付；不得在 P-016 完成前宣称全平台 HTML 转义已交付。

## 7. 成功标准

### 7.1 功能成功标准

| 编号 | 标准 | 验收方式 |
|---|---|---|
| SC-01 | 策略在 `as_of` 后不可见数据上运行 | PIT 契约测试与分钟频决策测试 |
| SC-02 | 同日买入数量不可卖出 | T+1 规则测试 |
| SC-03 | 涨跌停、停牌、tick、整手、时段和价格带均由规则层拒绝或放行 | 规则测试与共享成交等价测试 |
| SC-04 | 日频、分钟频、网格回测均可输出订单、成交和指标；策略模式额外输出信号、目标、决策和运行清单 | CLI 集成测试与编排器测试 |
| SC-05 | 五个插件可注册、启停、升级、回滚且单个插件崩溃不拖垮其他插件 | 注册表与插件测试 |
| SC-06 | 组合层对同标的冲突输出唯一净目标，并记录风险决策 | 组合测试 |
| SC-07 | Agent 越权工具、未知角色、实时下单工具均被拒绝并审计 | Agent Gateway 测试 |
| SC-08 | 模拟盘由策略、组合风控和已审批 PIT 读取驱动；无审批、执行器或完整行情时 fail closed | Paper 编排、Gateway 与 CLI 测试 |
| SC-09 | 新平台信号 HTML 始终包含免责声明且动态文本转义 | `tests/unit/strategies/test_reporting.py` |
| SC-10 | 环境配置无密钥，`prod` 恒为 dry-run | 配置测试 |
| SC-11 | 四份 SDD 文档存在、可追溯且 `docs/sdd/api-spec.yaml` 可被 YAML 解析 | 文档校验命令 |
| SC-12 | 冻结旧看板的供应商动态文本转义 | 安全回归测试；当前未达成，见 `P-016` |

### 7.2 非功能成功标准

| 类别 | 门槛 | 当前基线 |
|---|---|---|
| 正确性 | 核心平台测试覆盖率 ≥ 90% | 93% |
| 静态质量 | Ruff 0 告警、Mypy 0 错误 | 通过 |
| 可复现 | 固定数据、配置、版本和种子可重放 | 测试与金样夹具 |
| 可靠性 | 缺关键数据、非法配置、无审批时 fail closed | 测试锁定 |
| 性能 | 3000 标的 × 5 年日频基准不退化超过 10% | 67–84 秒，本机基线 |
| 安全 | 无实盘执行器、无密钥入库、审计只追加 | 结构测试与配置测试 |

## 8. 验收场景

### AC-01 防未来函数

给定分钟数据，以 `backtest run --frequency minute --decision 1430` 构造 14:30 场景时，策略只能读取 14:30 及之前的 bar；14:31 之后的数据不得进入信号、订单或成交。`tests/contract/test_market_data_port.py` 验证通用 PIT 可见性，`tests/unit/backtest/test_minute_engine.py` 当前覆盖默认 `1431` 决策时刻；`P-009` 已登记 `1430` 专项回归用例，完成前不得宣称该场景已受测试锁定。

### AC-02 T+1

当日买入 100 股后，同日卖出订单必须被 `T1_UNSETTLED` 拒绝；下一交易日结算后才可卖。通过 `tests/unit/rules/test_trading_rules.py` 和共享成交等价测试验证。

### AC-03 A 股交易约束

停牌、非交易时段、非法 tick、非整手、涨停排队买入、跌停排队卖出和价格带越界必须返回机器可读拒绝码。通过 `tests/unit/rules/test_trading_rules.py`、`tests/unit/application/test_execution_core.py` 验证。

### AC-04 回测能力

日频回测支持日期过滤、样本切分、滚动窗口和基准；分钟频回测支持决策时刻；网格回测支持格位、T+1 和价格带拒绝。策略模式从 PIT 数据产生信号，经组合层形成目标，再由 `TradingRulesPlugin` 和 `ExecutionCore` 输出订单、成交、指标及 `RunManifest`；尾盘动量与趋势突破/行业轮动均有端到端夹具。通过 `tests/unit/cli/test_cli_commands.py`、`tests/unit/backtest/*`、`tests/unit/application/test_strategy_backtest_orchestrator.py` 验证。

### AC-05 插件隔离与生命周期

同一 `strategy_id` 的多个版本可注册、启停和回滚；`DataUnavailable` 必须转为 `DATA_UNAVAILABLE`，其他插件异常必须转为 `PLUGIN_CRASH`，且不得中断其他插件。通过 `tests/unit/strategies/test_registry.py`、`tests/unit/strategies/test_plugin_isolation.py` 验证。

### AC-06 组合与风险

同标的多个策略权重必须合成为唯一净目标；单票、行业、流动性、回撤、黑名单、总仓位、相关性预算和被质量门阻断的策略必须产生 `RiskDecision`。通过 `tests/unit/portfolio/test_composer.py` 验证。

### AC-07 Agent 边界

研究、数据质量、风险审阅和开发 Agent 只能调用各自白名单工具；`submit_order`、`write_production_config`、`skip_data_quality_block` 永远拒绝；每次调用必须产生审计事件。通过 `tests/unit/agents/test_gateway.py`、`tests/unit/agents/test_agent_roles.py` 验证。

### AC-08 模拟盘策略编排与 fail closed

模拟盘必须先调用已启用策略插件并绑定显式 `--as-of` 的 PIT 上下文，再经 `SignalAdapter` 和 `SignalComposer` 形成目标。只有 `accepted` 或 `reduced` 且净权重为正的目标可进入模拟执行；被风险层拒绝的标的不得下单。审批必须同时绑定策略版本、完整运行身份哈希和本次实际 PIT 读取快照。无有效目标时返回明确的 `NO_SIGNAL`；存在目标但被风险层拒绝时返回 `PAPER_EXECUTED` 空订单。dry-run 与真实模拟运行都必须返回同一策略审计证据，只有 dry-run 的订单列表为空。配置未审批、绑定不匹配、执行器不可用、数据或市场快照不完整时返回退出码 2。通过 `tests/unit/application/test_paper_strategy_orchestrator.py`、`tests/unit/agents/test_paper_gateway.py` 和 `tests/unit/agents/test_paper_cli.py` 验证。

### AC-09 报告安全

新平台文本和 HTML 报告不得输出未转义的动态文本；空信号必须返回明确结果；HTML 必须自包含并带免责声明。通过 `tests/unit/strategies/test_reporting.py` 验证。冻结旧看板不在此验收范围，见 `P-016`。

### AC-10 配置与部署

`dev`、`research`、`paper`、`prod` 四套配置必须合法；`paper` 是唯一默认非 dry-run 环境；`prod` 即使启用也保持 dry-run；配置文件不得包含密钥。通过 `tests/unit/configs/test_environments.py` 验证。

### AC-11 SDD 文档一致性

四份 SDD 文档存在，任务、验收编号、接口契约和验证证据可追溯；`P-*` 任务均有定义；`docs/sdd/api-spec.yaml` 的 YAML、JSON Schema、CLI 参数与当前实现一致。通过本次提交前复核和 `docs/sdd/task.md` 的 T-001/T-140 证据验证。

## 9. 风险与约束

| 风险 | 影响 | 缓解 |
|---|---|---|
| 数据供应商口径变化 | 因子和历史结果漂移 | Raw 原文留存、适配器契约测试、金样锁定 |
| 规则时效性 | 回测或模拟盘使用过期规则 | 规则引用表、生效日期、外部日历文件 |
| LLM 越权 | 产生不可审计订单或配置 | 工具白名单、角色边界、人工审批、默认无实盘 |
| 策略驱动模拟盘运行身份漂移 | 注入插件、风控或规则变化可能破坏审批可追溯性 | 共享 run identity + 显式 `--as-of` + 实际 PIT snapshot 校验 |
| 文档与实现漂移 | 误把设计目标当作现状 | 本文、`docs/sdd/design.md`、`docs/sdd/api-spec.yaml`、`docs/sdd/task.md` 同步更新 |

## 10. 变更治理

1. 范围变化先改本文，并更新成功标准或非目标。
2. 架构、边界或不变量变化先改 `docs/sdd/design.md`。
3. CLI、Python 协议、配置或产物格式变化先改 `docs/sdd/api-spec.yaml`。
4. 上述变更完成后更新 `docs/sdd/task.md`，补充任务、依赖和验收证据。
5. 代码实现与测试必须引用任务 ID 和验收编号；任务未通过验证不得标记完成。`docs/sdd/task.md` 新增“验收追溯”节，维护任务到 SC/AC、架构约束和契约条目的映射。
6. 历史文档 `docs/PRODUCT_REQUIREMENTS.md`、`docs/DETAILED_DESIGN.md`、`docs/ARCHITECTURE.md` 作为输入和背景，不再替代本目录的 SDD 基线。

## 11. 关联文档

- 架构与决策：`docs/sdd/design.md`
- 机器可读接口契约：`docs/sdd/api-spec.yaml`
- 任务清单与验证证据：`docs/sdd/task.md`
- 历史需求：`docs/PRODUCT_REQUIREMENTS.md`
- 历史详细设计：`docs/DETAILED_DESIGN.md`
- 运行手册：`docs/RUNBOOK.md`

> 研究产物，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
