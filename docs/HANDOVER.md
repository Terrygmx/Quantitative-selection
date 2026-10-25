# 工作交接（Handover）

更新时间：2026-10-25。当前 HEAD：`e82976c`，工作树干净，分支 `main`。

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
```

当前基线：219 个测试全绿，覆盖率 93%，Ruff 全绿。Mypy 有 6 个遗留错误，全部在 `src/quant_agent/rules/trading.py`（`PriceBand | None` union-attr），属已知技术债，不阻塞 CI；新增代码不允许引入新的 mypy 错误。

## 最近完成的工作（本次会话）

- `bd958b3` M5 切片 1：遗留尾盘动量纯评分迁移到 `src/quant_agent/strategies/tail_momentum/scoring.py`，与遗留脚本在真实夹具 `sh600176` 上逐项对齐（总分 62.0，各分量一致）。
- `db6afaf` M5 切片 2：`selection.py` 接入 PIT `InMemoryMarketDataPort`；`Bar` 增加 `amount` 字段；策略配置移除 `lookback`（warmup 固定 25）；金样 `results/signals_2026-09-15.json` 空候选/Bear/门槛 80 等价已锁定。
- `fdd00e1` M7：`src/quant_agent/cli/paper.py` 提供 `approve`/`run` 命令，审批账本持久化，`run_at` 传递；CLI 只允许注入 executor+clock，注入的执行器无法绕过网关审批。
- `96ef408` 文档：记录 M5/M7 完成边界。
- `146f84c` M7 默认模拟执行器：`SimulatedPaperExecution`（`src/quant_agent/agents/paper.py`）复用 `TradingRulesPlugin` 与 `OrderStateMachine`，覆盖 T+1、佣金、印花税、滑点、最小价位、现金不足、停牌、涨跌停、非整手、非连续竞价拒绝；CLI 可从配置 `execution` 段构造执行器，缺该段 fail closed（退出码 2）。
- `2ceb4e1` + `e82976c` review 修复：只交易 `universe` 内标的；`universe` 必填；卖出使用真实昨收价（跳空跌破跌停板不再成交）；卖出可交易性按标的跟踪（停牌期间禁止卖出）；非法/非正价格统一走 `_parse_price` 失败关闭为 `INVALID_PRICE`；补 mypy 注解。
- 运行手册已同步 `execution` 段示例（`docs/RUNBOOK.md`），TODO 状态已更新（`docs/TODO.md`）。

## 剩余 TODO（建议顺序）

1. **共享成交内核**（M7 首项）：`SimulatedPaperExecution` 与 `MultiInstrumentBacktestEngine` 仍是两套独立成交账本，费用、滑点、拒绝逻辑有重复。设计文档要求模拟盘复用同一成交通道。建议：先写跨引擎等价测试（同一输入序列下两引擎的成交/现金/持仓一致，Red），再抽取共享成交器。这是下一个该做的切片。
2. **交易日历 2027+ 与外部数据源适配**（M2/M7 共同缺口）：`StaticTradingCalendar.for_exchange` 只有 2023–2026 数据。
3. **M5 金样 `excluded_count=1`**：当日被抓取失败标的未保存在固定夹具，无法验证该排除路径。
4. **盘后定价交易规则**（M2）：目前只覆盖连续竞价时段。

## 关键文件与约束

- 领域层（`src/quant_agent/domain/`）必须零 IO。规则层（`src/quant_agent/rules/`）是涨跌停、T+1、整手、时段的唯一裁决者；模拟盘和回测都不允许绕过它。
- 测试可导入遗留 `src/tail_momentum_selector.py` 做夹具解析/等价对照，但不修改它。
- `SimulatedPaperExecution` 的市场快照解析约定：非法数值 → `INVALID_PRICE` 拒绝；`previous_close` 缺失/非法 → 回退为 `last`；`universe` 缺失 → ValueError；snapshot 中 `universe` 之外的标的只是参考数据，绝不下单。
- 配置的 `execution` 段结构见 `docs/RUNBOOK.md` 示例；审批账本 `state/paper-approvals.json` 与 `config_hash` 绑定，任何人不得绕过。
- 用户已确认 `universe` 必填这一更严格行为（宁可退出码 2，也不静默交易整个快照）。
