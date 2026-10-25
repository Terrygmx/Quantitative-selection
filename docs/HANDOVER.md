# 工作交接（Handover）

更新时间：2026-10-25（第二轮）。当前 HEAD 见 `git log`，工作树干净，分支 `main`。

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

当前基线：276 个测试全绿，覆盖率 94%，Ruff 全绿。Mypy 遗留错误 35 个（本轮从 41 个降到 35 个：`rules/trading.py` 的 6 个 `PriceBand | None` union-attr 债务已随 None 守卫清零）；CI 不阻断，新增代码不允许引入新的 mypy 错误。

## 最近完成的工作（本次会话：M2/M3 剩余项循环）

按「实现 → review → 修复」循环完成 M2、M3 剩余项：

- `9f1f1d8` M2 盘中提前申报盘后定价单：`Order.session`（`continuous` 默认 / `after_hours_fixed` 校验，dict 往返保留）；规则层对标记订单执行申报窗口门（9:30–11:30、13:00–15:30 之外 `OUTSIDE_AFTER_HOURS_SUBMISSION_WINDOW`，非科创/创业板 `AFTER_HOURS_BOARD_NOT_SUPPORTED`）；`ExecutionCore.order_price` 对标记订单恒按 tick 收盘价定价。未标记订单行为不变。
- `6aba52e` M2 涨跌停方向语义（review 中由 mypy 净增错误追出）：涨停时仅买入排队拒绝（`LIMIT_UP`）、卖出可成交；跌停反之；带外价格两方向统一 `PRICE_BAND`。附带修复新股前五日 band=None 时 `validate_order` 的 AttributeError 崩溃（此前无测试路径），并因此清零 `rules/trading.py` 全部 6 个 mypy 遗留错误。
- `01e1f9a` M2 规则官方引用登记：`rules/references.py` 的 `RULE_REFERENCES` 覆盖全部已实现规则领域，测试锁定完整性；所有引用 `verified_online=False` 且必须附注（离线未核对原文，诚实披露），文档 `docs/RULES_REFERENCES.md`。
- `1c2db94` M3 数据适配器：`CsvMarketDataPort`（标准库）与 `ParquetMarketDataPort`（可选 `pyarrow` 惰性导入）委托 `InMemoryMarketDataPort` 复用 PIT 语义，接入 `tests/contract/test_market_data_port.py` 参数化（in-memory/csv/parquet 三套同契约）；文件解析按行号 fail closed（缺文件/缺列/坏数值/无时区时间戳）。

## 剩余 TODO（建议顺序）

1. **DuckDB 适配器**（M3）：依赖离线不可安装；依赖可用后按同一契约参数化接入即可（参考 csv/parquet 工厂写法）。
2. **规则引用在线核对**（M2）：联网后逐条打开 `RULE_REFERENCES` 来源核对条文与文号，确认后置 `verified_online=True`；2023–2026 节假日静态数据逐年核对。
3. **引擎侧盘后延迟撮合队列**（M7 备注）：规则与定价已支持 `after_hours_fixed` 标记订单，模拟执行器尚无「盘中提交、盘后撮合」的队列。
4. **实盘接口**：按 PRD 仍为非目标；需模拟盘稳定运行与人工审批流程验收后另立评审。

## 关键文件与约束

- 领域层（`src/quant_agent/domain/`）必须零 IO。规则层（`src/quant_agent/rules/`）是涨跌停（含方向语义）、T+1、整手、时段（连续竞价与盘后定价申报/撮合窗口）的唯一裁决者；模拟盘和回测都不允许绕过它。
- 成交、费用、滑点、tick 取整、现金与 T+1 账本只在 `application/execution.py` 的 `ExecutionCore` 中存在一份；两引擎定价必须走 `ExecutionCore.order_price`（含 `session` 参数）。冻结的单票金样引擎 `BacktestEngine` 保留自有费用计算作为回归夹具，勿迁移。
- 测试可导入遗留 `src/tail_momentum_selector.py` 做夹具解析/等价对照，但不修改它。
- `SimulatedPaperExecution` 的市场快照解析约定：非法数值 → `INVALID_PRICE` 拒绝；`previous_close` 缺失/非法 → 回退为 `last`；`universe` 必填（缺失 ValueError，退出码 2）；snapshot 中 `universe` 之外的标的只是参考数据，绝不下单。
- 配置的 `execution` 段结构见 `docs/RUNBOOK.md`；审批账本 `state/paper-approvals.json` 与 `config_hash` 绑定，任何人不得绕过。
- 外部交易日历数据文件格式见 `docs/RUNBOOK.md`「外部交易日历」；数据适配器契约与列要求见「数据适配器」一节。
