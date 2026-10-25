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
- [x] 已沉淀 `tests/contract/test_market_data_port.py`；CSV（标准库）、Parquet（可选 `pyarrow`）、DuckDB（可选 `duckdb`，`bars` 表 TIMESTAMPTZ 列）适配器均已按同一契约参数化接入（未来数据不可见、最新可见修订、缺数据 fail closed；文件/库解析按行号 fail closed）。

## M4 回测器

- [x] `MultiInstrumentBacktestEngine` 已按统一日期事件时钟驱动多标的订单、成交与状态机；旧单票金样本引擎保留为回归夹具。
- [x] 多标的买入/卖出、T+1 持仓账本、现金不足拒绝、`TradingRulesPlugin`、`MarketSnapshot` 与状态机均已接入统一事件引擎。
- [x] 基础净值、最大回撤、夏普、胜率、换手与逐笔成交数量已可计算，夏普支持声明样本频率并年化，回测可导出 JSON 兼容逐笔明细。

## M5 插件与尾盘动量

- [x] 插件已迁移下午动量、成交量、趋势、相对强弱、风险与市场环境完整评分链路，并通过 PIT 分钟数据生成标准信号；固定夹具评分与 `results/signals_2026-09-15.json` 的空候选、Bear 环境和门槛 80 对齐。
- [x] 金样 `excluded_count=1` 的排除路径已锁定：当日抓取失败标的的原始响应未保存（离线不可补录），固定夹具以合成标的（分时为空 → `NO_MINUTE_DATA`）建模该失败症状，金样锁定测试现与 `results/signals_2026-09-15.json` 逐字段一致；合成来源已在 `tests/fixtures/README.md` 披露。
- [x] `config.schema.json` 已接入零依赖运行时校验，覆盖非法配置测试矩阵；插件崩溃被隔离并生成 `PLUGIN_CRASH` 审计记录。

## M6 组合与风险

- [x] 流动性约束已使用目标金额、成交量和参与率计算容量。
- [x] 总仓位约束、黑名单生效日期、行业权重归因与基于跨策略协方差的相关性预算已具备。
- [x] 每个组合目标均生成不可变 `RiskDecision` 审计记录，统一携带状态、权重和原因码。

## M7 Agent 与模拟盘

- [x] `validate_output` 已通过锁定的 jsonschema 4.25.1 支持 JSON Schema Draft 2020-12。
- [x] 工具调用生成绑定 `RunManifest` 的不可变审计事件，记录输入摘要、模型标识、结构化输出，并支持 JSONL 持久化。
- [x] 模拟盘 Gateway 与调度器已具备配置哈希绑定的人工批准记录、dry-run 空订单计划、可注入的非 dry-run 执行器、运行时间传递和运行历史；`paper approve/run` 命令入口已提供并默认 fail closed。
- [x] 非 dry-run 默认执行器 `SimulatedPaperExecution` 已接入 `TradingRulesPlugin`、订单状态机与 `MarketSnapshot`，覆盖 T+1 结算、佣金、印花税、滑点、最小价位、现金不足、停牌、涨跌停、非整手和非连续竞价拒绝；CLI 可从配置 `execution` 段构造执行器，缺少该段仍 fail closed。
- [x] 默认模拟执行器与 `MultiInstrumentBacktestEngine` 已共用同一成交内核 `ExecutionCore`（`src/quant_agent/application/execution.py`）：规则校验、滑点、tick 取整、费用、现金与 T+1 账本单一来源，跨引擎等价测试锁定行为一致（成交价/费用/现金/持仓/拒绝优先级）。
- [x] `StaticTradingCalendar` 的 2027+ 与勘误已可通过 `FileCalendarSource` 外部供给（见 M2 与 RUNBOOK）。
- [x] 模拟执行器支持盘后定价会话：配置 `session: after_hours_fixed` 时盘中申报进延迟撮合队列（`QUEUED_AFTER_HOURS`），15:05–15:30 按收盘价无滑点撮合，跨日意图 `EXPIRED`；连续竞价会话行为不变。

## M8 质量闸门

- [x] 覆盖率阈值不低于 90% 已接入 CI，当前总覆盖率 96%。
- [x] Ruff 已锁定 0.13.3 并接入 CI；Mypy 1.18.2 已锁定，类型债务已全部清零（41 → 0）并作为 CI 阻断步骤接入。
- [x] 已建立 3000 只股票 × 5 年合成基准（本机约 70.5 秒）与 `docs/RUNBOOK.md`。
