# 开发待办（严格 TDD / 详细设计差距）

本文件记录已实现最小纵向能力与 `docs/DETAILED_DESIGN.md` 之间的未闭环差距。每项必须继续按 Red → Green → Refactor 处理，不得直接补实现。

## M1 领域核心

- [x] `RunManifest` 工厂与 Agent 审计事件均已接入可替换 `Clock`。
- [x] `Order.validate_quantity` 已接入交易规则与回测下单路径，覆盖非整手买入拒绝和卖出零股剩余量。

## M2 A 股规则

- [ ] 交易日历已提供可替换协议、2023–2026 沪深共用静态数据与 `for_exchange` 入口；仍需 2027 以后年份和外部数据源适配。
- [ ] 订单校验已覆盖集合竞价/午休/盘后拒绝、不同 tick 板块、涨跌停、停牌、T+1 与整手规则；仍需盘后定价交易与真实交易所规则引用适配。
- [x] `MarketSnapshot` 显式模型是订单校验唯一市场入参，旧映射兼容分支已删除。

## M3 数据门户

- [x] 同一时间戳多修订版本的 PIT 查询已按 `available_at` 取最新可见版本。
- [x] `QualityEventCollector` 已支持 pass/warn/block 分级校验、JSONL 持久化与按策略隔离查询。
- [x] 已沉淀 `tests/contract/test_market_data_port.py`，后续 CSV/Parquet/DuckDB 适配器可直接参数化接入。

## M4 回测器

- [x] `MultiInstrumentBacktestEngine` 已按统一日期事件时钟驱动多标的订单、成交与状态机；旧单票金样本引擎保留为回归夹具。
- [x] 多标的买入/卖出、T+1 持仓账本、现金不足拒绝、`TradingRulesPlugin`、`MarketSnapshot` 与状态机均已接入统一事件引擎。
- [x] 基础净值、最大回撤、夏普、胜率、换手与逐笔成交数量已可计算，夏普支持声明样本频率并年化，回测可导出 JSON 兼容逐笔明细。

## M5 插件与尾盘动量

- [ ] 插件已支持配置股票池和 PIT 分钟数据，但当前只迁移简单动量因子；仍需迁移遗留下午动量、成交量、趋势、相对强弱、风险与市场环境完整评分链路，并与 `results/signals_2026-09-15.json` 做端到端等价比较。
- [x] `config.schema.json` 已接入零依赖运行时校验，覆盖非法配置测试矩阵；插件崩溃被隔离并生成 `PLUGIN_CRASH` 审计记录。

## M6 组合与风险

- [x] 流动性约束已使用目标金额、成交量和参与率计算容量。
- [x] 总仓位约束、黑名单生效日期、行业权重归因与基于跨策略协方差的相关性预算已具备。
- [x] 每个组合目标均生成不可变 `RiskDecision` 审计记录，统一携带状态、权重和原因码。

## M7 Agent 与模拟盘

- [ ] `validate_output` 已通过锁定的 jsonschema 4.25.1 支持 JSON Schema Draft 2020-12。
- [x] 工具调用生成绑定 `RunManifest` 的不可变审计事件，记录输入摘要、模型标识、结构化输出，并支持 JSONL 持久化。
- [ ] 模拟盘 Gateway 与调度器已具备配置哈希绑定的人工批准记录、dry-run 空订单计划和运行历史；仍需命令入口与非 dry-run 执行。

## M8 质量闸门

- [x] 覆盖率阈值不低于 90% 已接入 CI，当前总覆盖率 96%。
- [x] Ruff 已锁定 0.13.3 并接入 CI；Mypy 1.18.2 已锁定但现存类型债务未清零，暂未作为 CI 阻断。
- [ ] 已建立 3000 只股票 × 5 年合成基准（本机约 70.5 秒）与 `docs/RUNBOOK.md`。
