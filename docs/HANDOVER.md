# 工作交接（Handover）

更新时间：2026-10-25（第三轮）。当前 HEAD 见 `git log`，工作树干净，分支 `main`。

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
python3 -m mypy src/quant_agent
```

当前基线：307 个测试（306 通过；1 个 westock 真实缓存等价测试在无 cache/ 的环境跳过），覆盖率 93%，Ruff 全绿，**Mypy 0 错误并已接入 CI 阻断**；性能基准 70.6s（带宽 67–84s 内）。注：westock 真实缓存等价测试在无 cache/ 的环境跳过；此前个别提交信息中的测试计数与反引号文本有误，以本条与 git diff 为准。

## 最近完成的工作（本次会话：M7 队列 + M8 类型债务）

- `dcf37e3` M7 盘后延迟撮合队列：策略配置顶层 `"session": "after_hours_fixed"`（默认 `continuous`，非法值 fail closed）；盘中申报先过（已公开的）规则申报门，进 `AfterHoursIntent` 日级队列（`QUEUED_AFTER_HOURS`，不动现金持仓）；15:05–15:30 内运行时按当时快照 `last`（收盘价）无滑点撮合，走共享内核、规则全量裁决；跨日意图 `EXPIRED`；撮合结果保留意图 id 并附 `submitted_at`。两次测试期望修正均附理由（15:10 运行会同时撮合排队意图并立即成交新申报；重复申报累积队列）。
- `72fa635` M8 类型债务清零：mypy 41（会话起点）→ 0 并入 CI。要点：金样引擎 `bars` 注解由错误的 `Mapping[str, object]` 改为 `Sequence[Mapping[str, object]]`（原注解使 `list(bars)` 成为键列表）、`_bar_date` 校验辅助、`Event` 携带 `OrderRecord`；registry 落实 DETAILED_DESIGN §4 的 `Strategy` 协议；portfolio/metrics 对非数值输入以 ValueError fail closed（修掉字符串价格字典序比较胜率的静默错误）；`memory_audit_sink` 去掉错误的 `-> None`。

## 最近完成（补：网络授权后的两项）

- `d08c681` + `26a7f64` DuckDB 适配器：`DuckDBMarketDataPort`（`bars` 表、TIMESTAMPTZ 列、只读连接、全部读错误 fail closed）接入契约套件第四套参数化实现；`duckdb==2.0.0` 列入 requirements-dev 由 CI 覆盖。
- `7fb758a` 规则引用在线核对：全部 8 个领域对照上交所《交易规则（2026 年修订）》（上证发〔2026〕41 号）原文与官方休市公告核实，登记表带条款号证据。
- `d90721f` 核对差异修复 1：盘后定价全市场适用（3.7.1，废除板块限制）+ 限价不等式（3.7.5，买：收盘价高于限价才无效；卖反之）。
- `20d9832` 核对差异修复 2：静态日历补 2026-02-23 春节休市（上交所公告逐日核对后唯一差异）。
- `f76d76d` 核对差异修复 3：新股前 5 日无涨跌幅按板块注册制落地日期建模（主板 2023-02-17、创业 2020-08-24、科创 2019-07-22）。

## 补：第 3 项 westock 适配器（`db8a41a`）

CLI 为本机 Go 二进制 `~/.local/bin/westock`（PATH 可见，无需 `WESTOCK_CLI`）。`adapters/westock.py`：解析与 legacy 在固定夹具及真实缓存 `k_sh600176.md` 上逐字段等价（运行时不 import legacy）；`WestockMarketDataAdapter` 走 PIT 契约（抓取时刻门 + 日线收盘 bar 收盘后可见 + block 质量事件）；`CachedKlineSource` 离线读 `k_{symbol}.md`，`WestockCliKlineSource` 在线组 legacy 命令行（字节读+显式 UTF-8）。已用真实二进制联调（60 根日线，PIT 门完整）。用法见 RUNBOOK「westock 适配器」。

## 最近完成（第四轮：剩余待办循环）

- `67b49c4` 日历逐年复核：2023 全对；2024 补 2/12–2/14（春节休市 2/9–2/17）、2025 补 10/8（国庆中秋休至 10/8），均对照交易所公告。
- `72bf64c` 深交所对齐经证监会官方发布确认（创业板 20% 维持、盘后定价扩全市场；深交所 docx 未逐行解析，已如实注明）。
- `0cfb5ea`+`704fb4a`+`61e9743` FR-6 CLI：`quant_agent.cli.strategy list`（显式注册表）与 `quant_agent.cli.backtest run`（CSV 日线→共享内核→orders/fills/summary JSON；退出码约定与 paper CLI 一致）；review 补 mypy 方差修复与 RUNBOOK。
- `989297c` 可替换成交模型（§7）：`fill_model = slippage（默认）/ next_open / vwap`，配置贯穿两引擎与回测 CLI，vwap 缺 amount/volume fail closed，新增跨引擎等价锁定。
- `a34d1bc` trend_breakout 日频策略插件（§6 #2）：唐奇安收盘突破 + 突破前 MA 上行过滤（同窗 MA 对收盘突破数学上恒上行，故过滤在突破前历史 上判定——TDD 逼出的设计修正），schema/README/注册齐备。

## 剩余 TODO

1. **策略序列 #3/#4**：`mean_reversion_liquid`、`low_vol_quality`/`industry_rotation`（照 trend_breakout 模式：目录+schema+README+测试+注册）。
2. **回测能力**：分钟频、滚动窗口、样本内/外划分、基准比较（FR-3.1）；CLI `report show`、`agent review`（FR-6）。
3. **数据分层**：Curated Parquet 分区 + DuckDB 元数据、Feature Store（参数哈希与版本）、Raw Store 按来源存档。
4. **Agent 工具集**：研究/数据质量/风险审阅/开发四个角色的有界工具（Gateway 与审计已就绪）。
5. **部署**：dev/research/paper/prod 四环境配置、Docker Compose。
6. **实盘接口**：PRD 非目标；另立评审。

## 关键文件与约束

- 领域层（`src/quant_agent/domain/`）必须零 IO。规则层（`src/quant_agent/rules/``）是涨跌停（含方向语义）、T+1、整手、时段（连续竞价、盘后定价申报/撮合窗口）的唯一裁决者；申报门 `after_hours_submission_gate` 与撮合窗口 `is_after_hours_fixed_price_session` 是引擎可调用的公开 API。
- 成交、费用、滑点、tick 取整、现金与 T+1 账本只在 `application/execution.py` 的 `ExecutionCore` 中存在一份；两引擎定价必须走 `ExecutionCore.order_price`（含 `session` 参数）。冻结的单票金样引擎 `BacktestEngine` 保留自有费用计算作为回归夹具，勿迁移。
- `SimulatedPaperExecution` 约定：`universe` 必填（缺失 ValueError/退出码 2）；非法价格 → `INVALID_PRICE`；`previous_close` 缺失/非法回退 `last`；`session` 键仅接受 `continuous`/`after_hours_fixed`；盘后意图按日有效、绝不以连续竞价价格成交。
- 审批账本 `state/paper-approvals.json` 与 `config_hash` 绑定（`session` 键随配置一并绑定审计），任何人不得绕过。
- 外部交易日历、数据适配器契约、盘后定价会话的配置与语义见 `docs/RUNBOOK.md` 对应章节。
