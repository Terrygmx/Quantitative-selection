# 工作交接（Handover）

更新时间：2026-10-25。当前 HEAD：`786f4a1`，工作树干净，分支 `main`。

## 工作循环约定（必须遵守）

1. 从 `docs/TODO.md` 按顺序选取下一个未完成项，一次只做一个最小纵向切片。
2. 严格 TDD：先写失败测试（Red），再写最小实现（Green），必要时重构（Refactor）。不得修改测试去迎合错误实现；发现测试期望写错时要说明理由后修正测试。
3. 切片完成后必须 review：对照 `docs/DETAILED_DESIGN.md` 与 `docs/TDD_VIBE_CODING_PLAN.md` 检查 TDD 顺序、领域零 IO、费用/规则复用是否一致。review 发现的问题用新的 Red 测试驱动修复。
4. 修不了的写入 `docs/TODO.md`，不要静默跳过。
5. 每个完成的切片用独立非 amend 提交，提交信息说明测试证据（Red → Green）。
6. 不做破坏性 git 操作，不删遗留代码 `src/tail_momentum_selector.py`，不访问网络。

## 验证命令（每次提交前全跑）

```bash
python3 -m pytest --ignore=tests/performance
python3 -m coverage run -m pytest --ignore=tests/performance
python3 -m coverage report --fail-under=90
python3 -m ruff check src/quant_agent tests
python3 -m mypy src/quant_agent   # CI 不跑；要求不引入新错误
```

当前基线：245 个测试全绿，覆盖率 94%，Ruff 全绿。Mypy 遗留错误约 41 个（7 个文件，多为 `Mapping[str, object]` 的未收窄访问与 `backtest.py` 金样引擎的旧代码），为历史存量，CI 不阻断；本轮所有切片经前后 diff 证明零新增 mypy 错误。新增代码不允许引入新的 mypy 错误。

## 最近完成的工作（本次会话：TODO 清零循环）

按「实现 → review → 修复」循环完成原剩余 4 项 TODO：

- `b1f709e` M7 共享成交内核：新增 `src/quant_agent/application/execution.py`（`ExecutionCore`/`ExecutionCosts`/`ExecutionOutcome`），`SimulatedPaperExecution` 与 `MultiInstrumentBacktestEngine` 全部订单经同一通道。Red 是 4 个跨引擎等价测试，暴露并修复三处回测特权：滑点价不按 tick 取整、现金按滑点前价格检查（现金可为负）、现金检查遮蔽规则拒绝。
- `a6e6268` 上一项 review 修复：基准回归 12.4%（94.1s vs 同机基线提交 83.7s），热点为买单的 Portfolio/Position 无谓分配与 `BacktestConfig.costs` 每单重建；买入共享空持仓视图 + 缓存 costs 后回到 84.0s。RUNBOOK 基线更新（同日漂移 67–84s 已注明）。
- `a8256ba` + `0bf11b8` M2 交易日历外部数据源：`rules/calendar.parse_trading_days`（每行一个 ISO 日期，空/非法 fail closed）+ `StaticTradingCalendar.union` + `adapters/calendar.FileCalendarSource`（`load()`/`extend_builtin()`）。2027+ 节假日未发布，不猜测，以数据文件供给；RUNBOOK 补格式说明。
- `27174aa` M5 金样 `excluded_count=1`：当日抓取失败标的原始响应未保存（离线不可补录），固定夹具以合成标的（分时为空 → `NO_MINUTE_DATA`）建模，金样锁定测试改为与 `results/signals_2026-09-15.json` 逐字段相等；来源在 `tests/fixtures/README.md` 披露。
- `8a28efb` M2 盘后定价交易：科创板/创业板 15:05–15:30 时段可交易（`tradeability`），规则强制申报价等于当日收盘价（`INVALID_AFTER_HOURS_PRICE`）。
- `786f4a1` 上一项 review 修复：执行器仍按滑点定价导致盘后单全被拒；规则公开 `is_after_hours_fixed_price_session`，`ExecutionCore.order_price` 成为两引擎唯一定价入口（盘后=收盘价无滑点，盘中=滑点价）。

## 剩余 TODO（建议顺序）

`docs/TODO.md` 原有 4 项已全部闭环。当前记录在案的新缺口：

1. **盘中提前提交盘后定价单**（M2 备注）：真实市场允许盘中申报、盘后以收盘价撮合；当前模型只支持盘后时段内直接下单。
2. **收盘价恰为涨跌停价时的盘后申报**（M2 备注）：当前保守拒绝，真实市场允许排队。
3. **真实交易所规则引用适配**（M2 未闭环项）：为涨跌幅、时段、盘后规则补充官方文件引用与逐年核对。
4. **数据层适配器**（M3 未闭环项）：CSV/Parquet/DuckDB 适配器按 `tests/contract/test_market_data_port.py` 契约参数化接入。
5. **实盘接口**：按 PRD 仍为非目标；需模拟盘稳定运行与人工审批流程验收后另立评审。

## 关键文件与约束

- 领域层（`src/quant_agent/domain/`）必须零 IO。规则层（`src/quant_agent/rules/`）是涨跌停、T+1、整手、时段（含盘后定价）的唯一裁决者；模拟盘和回测都不允许绕过它。
- 成交、费用、滑点、tick 取整、现金与 T+1 账本只在 `application/execution.py` 的 `ExecutionCore` 中存在一份；两引擎定价都必须走 `ExecutionCore.order_price`。冻结的单票金样引擎 `BacktestEngine`（`application/backtest.py` 内）保留自有费用计算作为回归夹具，勿迁移。
- 测试可导入遗留 `src/tail_momentum_selector.py` 做夹具解析/等价对照，但不修改它。
- `SimulatedPaperExecution` 的市场快照解析约定：非法数值 → `INVALID_PRICE` 拒绝；`previous_close` 缺失/非法 → 回退为 `last`；`universe` 必填（缺失 ValueError，退出码 2）；snapshot 中 `universe` 之外的标的只是参考数据，绝不下单。
- 配置的 `execution` 段结构见 `docs/RUNBOOK.md`；审批账本 `state/paper-approvals.json` 与 `config_hash` 绑定，任何人不得绕过。
- 外部交易日历数据文件格式与加载方式见 `docs/RUNBOOK.md`「外部交易日历」一节。
