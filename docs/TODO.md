# 开发待办（严格 TDD / 详细设计差距）

本文件记录已实现最小纵向能力与 `docs/DETAILED_DESIGN.md` 之间的未闭环差距。每项必须继续按 Red → Green → Refactor 处理，不得直接补实现。

## M1 领域核心

- [x] `RunManifest` 工厂与 Agent 审计事件均已接入可替换 `Clock`。
- [x] `Order.validate_quantity` 已接入交易规则与回测下单路径，覆盖非整手买入拒绝和卖出零股剩余量。

## M2 A 股规则

- [ ] 交易日历已提供可替换协议、2023–2026 沪深共用静态数据与 `for_exchange` 入口；仍需 2027 以后年份和外部数据源适配。
- [ ] 订单校验已覆盖集合竞价/午休/盘后拒绝、不同 tick 板块、涨跌停、停牌、T+1 与整手规则；仍需盘后定价交易与真实交易所规则引用适配。
- [ ] `MarketSnapshot` 显式模型已接入回测全部下单路径；规则层旧映射兼容分支待所有调用方迁移后删除。

## M3 数据门户

- [x] 同一时间戳多修订版本的 PIT 查询已按 `available_at` 取最新可见版本。
- [ ] `QualityEventCollector` 已记录 block 事件；仍需接入 warn/pass 事件、持久化与策略隔离策略。
- [x] 已沉淀 `tests/contract/test_market_data_port.py`，后续 CSV/Parquet/DuckDB 适配器可直接参数化接入。

## M4 回测器

- [ ] 订单状态机已支持 `PENDING → FILLED/REJECTED`；`BacktestEngine` 仍是单票三日金样本，需改为多标的通用事件时钟并全面使用状态机。
- [ ] 卖出订单已接入 `TradingRulesPlugin`、`MarketSnapshot` 与显式 ORDER/REJECTION 事件；多标的订单状态机仍待迁移。
- [ ] 基础净值、最大回撤、夏普、胜率、换手与逐笔成交数量已可计算；仍需年化、样本频率、逐笔明细导出与回测事件接线。

## M5 插件与尾盘动量

- [ ] 插件已支持配置股票池和 PIT 分钟数据，但当前只迁移简单动量因子；仍需迁移遗留下午动量、成交量、趋势、相对强弱、风险与市场环境完整评分链路，并与 `results/signals_2026-09-15.json` 做端到端等价比较。
- [ ] `config.schema.json` 与基础参数校验已加入；仍需 JSON Schema 运行时校验、非法配置测试矩阵与插件失败隔离。

## M6 组合与风险

- [x] 流动性约束已使用目标金额、成交量和参与率计算容量。
- [ ] 总仓位约束、黑名单生效日期与行业权重归因已具备；仍需相关性预算和跨策略协方差数据接入。
- [x] 每个组合目标均生成不可变 `RiskDecision` 审计记录，统一携带状态、权重和原因码。

## M7 Agent 与模拟盘

- [ ] `validate_output` 已支持显式 object schema 的 required/type 校验；仍需完整 JSON Schema Draft 2020-12 实现或显式引入并锁定 jsonschema 依赖。
- [x] 工具调用生成绑定 `RunManifest` 的不可变审计事件，记录输入摘要、模型标识、结构化输出，并支持 JSONL 持久化。
- [ ] 模拟盘 Gateway 已具备配置哈希绑定的人工批准记录和 dry-run 空订单计划；仍需调度、命令入口与非 dry-run 执行。

## M8 质量闸门

- [ ] 增加覆盖率阈值（核心领域与策略不低于 90%）并接入 CI。
- [ ] 引入类型检查与格式化工具，锁定版本并保持遗留脚本零运行时依赖。
- [ ] 建立 3000 只股票、5 年日线的性能基准与运行手册。
