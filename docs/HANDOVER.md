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

当前基线（feat/followup-integration 分支）：402 个测试（401 通过；1 个 westock 真实缓存等价测试在无 cache/ 的环境跳过），覆盖率 93%，Ruff 全绿，**Mypy 0 错误并已接入 CI 阻断**；日频性能基准同机对照确认无回归（本时段 92.6–101.5s 属机器负载漂移，空闲带 67–84s）。注：westock 真实缓存等价测试在无 cache/ 的环境跳过；此前个别提交信息中的测试计数与反引号文本有误，以本条与 git diff 为准。

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

## 最近完成（第五轮）

- `d88dcea` 策略 #3 `mean_reversion_liquid`：跌前 MA5 超跌（跌幅不稀释自身度量）+ MA20 上方 + 5 日均额流动性门，持有 5 日。
- `5781af9`+`1df08a8` 策略 #4 `low_vol_quality`：20 日收益波动 ≤1.5% + 60 日均线上方 + 流动性门，持有 20 日；§6 四策略全齐。
- `e691512` CLI `report show`（信号 JSON→文本，reporting 支持自定义标题）+ 回测 `--start/--end/--split`（样本内/外两段独立回测，FR-3.1）。
- `05ec011` Agent 四角色工具边界（§8）：`agents/roles.py` 角色 allow/forbid 表，网关 `role_bindings` 强制执行（跨角色 `ROLE_TOOL_NOT_ALLOWED`、未知 Agent `AGENT_ROLE_UNKNOWN`，均审计；无绑定时行为不变）。

## 最近完成（第五轮续）

- `883043c` 回测 `--benchmark SYMBOL`（同一份 bars 的买入持有收益 + `excess_return`，未知标的 fail closed）与 `--window N`（连续滚动窗口逐段独立回测，与 `--split` 互斥）——FR-3.1 的滚动窗口/基准比较闭环。
- `76ebbb5` CLI `agent review`（审计 JSONL → 总量/按状态/按 Agent 计数 + 拒绝明细，坏行 fail closed，FR-6 全部四条命令齐备）；`application/features.py` Feature Store（§5.4：特征名绑定唯一参数哈希，同名不同定义拒绝，值按 (name, symbol, 计算时点) 存取）。

## 最近完成（feat/minute-backtest 分支）

- `fd7cffa` 分钟频回测（FR-3.1 最后一项）：`application/intraday.MinuteBacktestEngine` 每交易日按决策时刻（默认 14:31 尾盘快照语义）取最后可见分钟 bar 定价，PIT 防未来由端口构造保证，共享内核使分钟时间戳真实命中时段校验（午休决策被拒）；`backtest run --frequency minute --decision HHMM` 接入（CSV 需 available_at==bar 时间戳的重放约定；日频专用选项互斥）。review 修正 RUNBOOK/TODO 文档；FR-3.1 全部闭环。

## 最近完成（第六轮：五项剩余任务循环，main 分支）

- 分支合并：`feat/minute-backtest`（分钟频回测）已 no-ff 合回 main。
- `c3c9fd5` 数据分层：`RawStore`（内容寻址 sha256、source/date 分层、原子写、自愈恢复，verify=True 拒绝篡改）+ `CuratedStore`（Parquet 按 dataset/trade_date 分区 + DuckDB 元数据血缘）。
- `710a39f`+`8003692` Agent 角色工具执行体：`RoleToolbox`——read_approved_dataset（PIT bars，DataUnavailable 转错误载荷不越界）、draft_experiment（status=draft + 免责声明，永不生产）、create_quality_event（追加型 JSONL）、explain_signal/explain_rejection（规则原因码→人类解释，不覆盖决策）。
- `737b5e6` `industry_rotation`：行业动量排名取 top_n、仅正动量发信号（弱市空仓）；schema 校验器补 minProperties/additionalProperties(object)。
- `b3273ed` 四环境配置（paper 唯一非 dry-run 且强制审批；prod 恒 dry-run，§9；无密钥有测试锁定）+ Dockerfile + docker-compose（paper 服务 dry-run 命令 + 审批卷；Docker 守护进程未运行，构建契约以静态校验+YAML 验证覆盖）。

## 最近完成（第七轮：后续项循环，feat/followup-integration 分支）

- `e1f7ec7` 网关→工具箱集成：`AgentGateway(tool_executors=...)`，允许的角色工具真实执行（ISO/datetime 双形态参数），执行异常转审计型 `TOOL_FAILED` 拒绝不泄漏堆栈；审计序列化支持 datetime。review 修正两处测试角色前提（explain_signal/draft_experiment 属研究角色）。
- `916cd0a` `PersistentFeatureStore`：值落 Parquet + 定义哈希 JSON 侧车，load 后定义锁语义跨进程保持。
- `c8ffe58` 分钟引擎 `prefetched()` 工厂：每标的一次性按日分桶 + 日游标推进，消除 O(天数×标的×全历史) 重复查询，等价测试锁定结果一致；默认查询路径不变。
- `3816af8` 深交所 2026 规则全文 PDF 逐条核对（3.1.4/2.3.2/3.3.8/3.3.11/3.3.13/3.3.14/3.6.1–3.6.5）：涨跌幅/T+1/整手/时段与实现一致；**发现并修复**盘后申报窗口深市 9:15 起（`after_hours_submission_gate` 按交易所区分）。
- Docker 实机构建验证：镜像构建、五 CLI 导入、`strategy list` 五插件、无审批 fail closed（退出码 2）、`approve`→`run --dry-run` 全流程（退出码 0）全部通过。

## 最近完成（第八轮：两类策略建模扩展，feat/followup-integration 分支）

- `f4f6bc6`+`43b3484`+`2eabe5f` **涨跌停排队成交模型**（解锁打板/涨停动量类）：`ExecutionCore.board_queue_policy`（默认 reject 不变；queue_fill 下规则层裁决锁板 + 快照 `board_volume` 对手盘量证据覆盖整单则按板价成交，量不足 `BOARD_QUEUE_UNFILLED`，无量回退保守拒绝）；策略贯通两引擎配置与 CLI 数据列；无部分成交（状态机无该态，如实记录）。review 发现策略未贯通引擎（对照 fill_model 先例）并修复。
- `f9f95f6`+`c38100e` **网格引擎**（解锁网格类）：`GridBacktestEngine` 格位驻留限价单——下穿格位买入/上穿卖出（按格价成交、无滑点），跨多格逐格成交（最近格优先），卖出按整手提交由规则层裁决 T+1，日界结算，格位超当日价格带被规则层拒绝（band 参考价=上一**交易日**收盘，review 修正）；CLI `--grid-low/--grid-high/--grid-steps` 贯通；equity 按最后可见价计价。
- 两项 review 均以 Red 测试驱动修复；性能基准经同机对照（对照提交 101.5s vs HEAD 92.6s）确认无回归、波动属机器负载漂移。

## 最近完成（第九轮：PRD 功能点 #4/#1/#2/#3）

- `8427951` block 联动（FR-2.3/FR-3 硬门槛）：`QualityEventCollector.blocked_strategy_ids()` + `compose(blocked_strategies=...)`，被 block 策略的信号在约束评估前拒绝并审计 `STRATEGY_BLOCKED`（不影响净额计算）。复审记录：compose 的生产调用点在未来管线组装层。
- `d28fb31` 注册表生命周期（FR-1）：同 id 新版本升级 + 全版本历史 + disable/enable 门控 list/run_all + rollback 任意已注册版本（新版本保留可回滚前进）；`StrategyMetadata` 增 `turnover_cap`/`risk_exposure` 声明字段（FR-1.2）。
- `5f87208` Normalized 层（§5.2）：`normalize_bars` 规范代码/CN 时区/`adjustment` 模式不混用 fail closed；`Bar.adjustment` 字段；0xxxxx 前缀歧义（SZ 股 vs SH 指数）强制交易所。复审修正启发式（原把 0xxxxx 误判为可自动解析）。

## 剩余 TODO

1. 实盘接口：PRD 非目标；模拟盘稳定运行 + 人工审批验收后另立评审。
2. 深交所静态日历的独立逐年复核（历年公告一致，未逐份核对深交所原文）。
3. 分钟频规模化基准待真实分钟数据规模需求；排队/网格模型的柜台级精细度（部分成交、挂单撤销）待实盘需求。
4. HTML 报告与 Agent 提示词模板（FR-6.3/FR-5 次级条款）；compose 调用点在管线组装时接 blocked_strategy_ids。

## 关键文件与约束

- 领域层（`src/quant_agent/domain/`）必须零 IO。规则层（`src/quant_agent/rules/``）是涨跌停（含方向语义）、T+1、整手、时段（连续竞价、盘后定价申报/撮合窗口）的唯一裁决者；申报门 `after_hours_submission_gate` 与撮合窗口 `is_after_hours_fixed_price_session` 是引擎可调用的公开 API。
- 成交、费用、滑点、tick 取整、现金与 T+1 账本只在 `application/execution.py` 的 `ExecutionCore` 中存在一份；两引擎定价必须走 `ExecutionCore.order_price`（含 `session` 参数）。冻结的单票金样引擎 `BacktestEngine` 保留自有费用计算作为回归夹具，勿迁移。
- `SimulatedPaperExecution` 约定：`universe` 必填（缺失 ValueError/退出码 2）；非法价格 → `INVALID_PRICE`；`previous_close` 缺失/非法回退 `last`；`session` 键仅接受 `continuous`/`after_hours_fixed`；盘后意图按日有效、绝不以连续竞价价格成交。
- 审批账本 `state/paper-approvals.json` 与 `config_hash` 绑定（`session` 键随配置一并绑定审计），任何人不得绕过。
- 外部交易日历、数据适配器契约、盘后定价会话的配置与语义见 `docs/RUNBOOK.md` 对应章节。
