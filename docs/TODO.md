# 开发待办（严格 TDD / 详细设计差距）

本文件记录已实现最小纵向能力与 `docs/DETAILED_DESIGN.md` 之间的未闭环差距。每项必须继续按 Red → Green → Refactor 处理，不得直接补实现。

## M1 领域核心

- [x] `RunManifest` 工厂与 Agent 审计事件均已接入可替换 `Clock`。
- [x] `Order.validate_quantity` 已接入交易规则与回测下单路径，覆盖非整手买入拒绝和卖出零股剩余量。

## M2 A 股规则

- [x] 交易日历已提供可替换协议、2023–2026 沪深共用静态数据与 `for_exchange` 入口；2027 及以后年份与勘误通过 `FileCalendarSource`（每行一个 ISO 日期的数据文件，`extend_builtin()` 合并内置数据，空/非法数据 fail closed）外部供给，不再猜测未发布节假日。
- [x] 订单校验已覆盖集合竞价/午休/盘后拒绝、不同 tick 板块、涨跌停（按买卖方向语义：排队侧拒绝、对手侧可成交）、停牌、T+1 与整手规则；盘后定价交易已覆盖科创板/创业板 15:05–15:30 时段，规则强制申报价等于当日收盘价（`INVALID_AFTER_HOURS_PRICE`），共享成交内核按收盘价无滑点定价（`ExecutionCore.order_price`）。盘中提前申报已建模：`Order.session="after_hours_fixed"` 标记的订单允许在 9:30–11:30、13:00–15:30 提交（`AFTER_HOURS_BOARD_NOT_SUPPORTED` / `OUTSIDE_AFTER_HOURS_SUBMISSION_WINDOW` 拒绝违规），撮合定价恒为收盘价；模拟执行器已接入延迟撮合队列（配置 `session` 键，盘中排队、15:05–15:30 按收盘价撮合、跨日报 `EXPIRED`，见 RUNBOOK「盘后定价交易」）。规则官方引用已登记于 `rules/references.py` 并由测试锁定完整性；2026-10-25 已联网逐条核对全部 8 个领域（上交所交易规则 2026 修订版原文条款）并修复四处实现差异（盘后定价全市场适用、限价不等式、主板新股前 5 日豁免、2026-02-23 休市），见 `docs/RULES_REFERENCES.md`；剩余：2023–2025 节假日逐年复核、深交所原文逐条取文。
- [x] `MarketSnapshot` 显式模型是订单校验唯一市场入参，旧映射兼容分支已删除。

## M3 数据门户

- [x] 同一时间戳多修订版本的 PIT 查询已按 `available_at` 取最新可见版本。
- [x] `QualityEventCollector` 已支持 pass/warn/block 分级校验、JSONL 持久化与按策略隔离查询。
- [x] Normalized 标准化层（§5.2）：`normalize_bars` 统一代码（歧义前缀强制交易所）、CN 时区、`adjustment` 模式不混用 fail closed、ingested_at 供给可见性。
- [x] 数据质量 block 联动（FR-2.3/FR-3 硬门槛）：`blocked_strategy_ids()` → `compose(blocked_strategies=...)` 拒绝并审计 `STRATEGY_BLOCKED`；生产管线组装时接入该调用点。
- [x] 已沉淀 `tests/contract/test_market_data_port.py`；CSV（标准库）、Parquet（可选 `pyarrow`）、DuckDB（可选 `duckdb`，`bars` 表 TIMESTAMPTZ 列）适配器均已按同一契约参数化接入（未来数据不可见、最新可见修订、缺数据 fail closed；文件/库解析按行号 fail closed）。westock 适配器（`adapters/westock.py`）已接入：Markdown 解析与 legacy 在固定夹具及真实缓存上逐字段锁定，`CachedKlineSource` 离线复用 `k_{symbol}.md` 缓存，`WestockCliKlineSource` 在线调用本机二进制（已用真实数据联调），日线收盘 bar 到收盘后才可见。

## M4 回测器

- [x] `MultiInstrumentBacktestEngine` 已按统一日期事件时钟驱动多标的订单、成交与状态机；旧单票金样本引擎保留为回归夹具。
- [x] 多标的买入/卖出、T+1 持仓账本、现金不足拒绝、`TradingRulesPlugin`、`MarketSnapshot` 与状态机均已接入统一事件引擎。
- [x] 基础净值、最大回撤、夏普、胜率、换手与逐笔成交数量已可计算，夏普支持声明样本频率并年化，回测可导出 JSON 兼容逐笔明细。
- [x] 分钟频回测已接入（`MinuteBacktestEngine` + `backtest run --frequency minute --decision HHMM`）：决策时刻取最后可见分钟 bar，PIT 防未来由端口构造保证，分钟级时段校验生效——FR-3.1 全部闭环。

## M5 插件与策略

- [x] §6 初始策略序列四个插件全部接入：`tail_momentum_overnight`（迁移+金样锁定）、`trend_breakout`（唐奇安突破+突破前 MA 上行过滤，避免同窗 MA 恒上行的空转）、`mean_reversion_liquid`（相对跌前 MA5 超跌 + MA20 上方 + 流动性门）、`low_vol_quality`（低波动 + 长均线上方 + 流动性门）；均含 config schema/README/注册与 fail-closed 校验。`industry_rotation` 作为 #4 的替代选项未做。

- [x] 插件已迁移下午动量、成交量、趋势、相对强弱、风险与市场环境完整评分链路，并通过 PIT 分钟数据生成标准信号；固定夹具评分与 `results/signals_2026-09-15.json` 的空候选、Bear 环境和门槛 80 对齐。
- [x] 金样 `excluded_count=1` 的排除路径已锁定：当日抓取失败标的的原始响应未保存（离线不可补录），固定夹具以合成标的（分时为空 → `NO_MINUTE_DATA`）建模该失败症状，金样锁定测试现与 `results/signals_2026-09-15.json` 逐字段一致；合成来源已在 `tests/fixtures/README.md` 披露。
- [x] `config.schema.json` 已接入零依赖运行时校验，覆盖非法配置测试矩阵；插件崩溃被隔离并生成 `PLUGIN_CRASH` 审计记录。
- [x] 注册表生命周期（FR-1 启停与版本回滚）：同 id 新版本升级、全版本历史、disable/enable 门控 list/run_all、rollback 到任意已注册版本；`StrategyMetadata` 增 `turnover_cap`/`risk_exposure` 声明字段（FR-1.2）。

## M6 组合与风险

- [x] 流动性约束已使用目标金额、成交量和参与率计算容量。
- [x] 总仓位约束、黑名单生效日期、行业权重归因与基于跨策略协方差的相关性预算已具备。
- [x] 每个组合目标均生成不可变 `RiskDecision` 审计记录，统一携带状态、权重和原因码。

## M7 Agent 与模拟盘

- [x] `validate_output` 已通过锁定的 jsonschema 4.25.1 支持 JSON Schema Draft 2020-12。
- [x] 工具调用生成绑定 `RunManifest` 的不可变审计事件，记录输入摘要、模型标识、结构化输出，并支持 JSONL 持久化。
- [x] 模拟盘 Gateway 与调度器已具备配置哈希绑定的人工批准记录、dry-run 空订单计划、可注入的非 dry-run 执行器、运行时间传递和运行历史；`paper approve/run` 命令入口已提供并默认 fail closed。
- [x] P-002：`paper run` 已接入策略注册表、PIT `StrategyContext`、Signal 适配与组合风控；审批绑定策略版本、完整运行身份和实际 PIT snapshot，只执行 accepted/reduced 正权重目标。
- [x] 非 dry-run 默认执行器 `SimulatedPaperExecution` 已接入 `TradingRulesPlugin`、订单状态机与 `MarketSnapshot`，覆盖 T+1 结算、佣金、印花税、滑点、最小价位、现金不足、停牌、涨跌停、非整手和非连续竞价拒绝；CLI 可从配置 `execution` 段构造执行器，缺少该段仍 fail closed。
- [x] 默认模拟执行器与 `MultiInstrumentBacktestEngine` 已共用同一成交内核 `ExecutionCore`（`src/quant_agent/application/execution.py`）：规则校验、滑点、tick 取整、费用、现金与 T+1 账本单一来源，跨引擎等价测试锁定行为一致（成交价/费用/现金/持仓/拒绝优先级）。
- [x] `StaticTradingCalendar` 的 2027+ 与勘误已可通过 `FileCalendarSource` 外部供给（见 M2 与 RUNBOOK）。
- [x] 模拟执行器支持盘后定价会话：配置 `session: after_hours_fixed` 时盘中申报进延迟撮合队列（`QUEUED_AFTER_HOURS`），15:05–15:30 按收盘价无滑点撮合，跨日意图 `EXPIRED`；连续竞价会话行为不变。

## M9 运维与第二阶段（原 HANDOVER 剩余项）

- [x] 数据分层：`RawStore`（内容寻址、追加-only、自愈恢复）+ `CuratedStore`（Parquet 按日分区 + DuckDB 元数据血缘）。
- [x] Agent 角色工具执行体：`RoleToolbox`（读 PIT 数据、写草稿、追加质量事件、解释信号/拒绝，全部注入式只读边界 + 免责声明）。
- [x] §6 策略序列全部五个插件：tail_momentum_overnight、trend_breakout、mean_reversion_liquid、low_vol_quality、industry_rotation。
- [x] 四环境配置（prod 恒 dry-run，无密钥有测试锁定）+ Dockerfile + docker-compose（paper 服务，dry-run 命令，审批卷）。
- [x] 网关→工具箱集成层：`tool_executors` 注入，允许的角色工具真实执行、异常转 `TOOL_FAILED` 审计拒绝，datetime/ISO 参数双形态。
- [x] Curated/Feature Store 持久化对接：`PersistentFeatureStore`（值落 Parquet、定义哈希落 JSON 侧车，load 后定义锁语义保持）。
- [x] 深交所 2026 规则原文逐条核对（发现并修复盘后申报窗口 SZSE 9:15 起）。
- [x] HTML 报告（FR-6.3）：`render_signal_report_html` 自包含、全转义、恒带免责声明。
- [x] Agent 提示词模板（FR-5）：`agents/prompts.render_prompt` 按角色 allow/forbid 集生成，任务+输出契约+非执行指令声明。
- [x] 实盘接口：PRD 非目标已**结构化锁定**——agents 包仅暴露 PaperExecution 协议 + SimulatedPaperExecution 唯一具体执行器、无 Live/Real/Broker 类、网关拒绝 live 工具（测试锁定；未来实盘须显式改这些测试并另立评审）。

## M8 质量闸门

- [x] 覆盖率阈值不低于 90% 已接入 CI，当前总覆盖率 96%。
- [x] Ruff 已锁定 0.13.3 并接入 CI；Mypy 1.18.2 已锁定，类型债务已全部清零（41 → 0）并作为 CI 阻断步骤接入。
- [x] 已建立 3000 只股票 × 5 年合成基准（本机约 70.5 秒）与 `docs/RUNBOOK.md`。
