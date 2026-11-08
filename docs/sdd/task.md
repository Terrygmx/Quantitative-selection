# A 股多策略 Agent 量化平台：任务清单

> 文档版本：1.0.7
> 基线日期：2026-10-29
> 基线提交：`7052b7e`
> 最后复核：2026-11-08
> 状态标记：`[x]` 已实现并验证；`[ ]` 未完成；`[!]` 阻塞
> 本文件是 SDD 的任务清单（`docs/sdd/task.md`）；部分规范称其为 `tasks.md`，两者指同一文件，不要求创建第二个文件。执行顺序按依赖从上到下，不得跳过未解除依赖的任务。

## 1. 验证基线

以下命令在 2026-10-29 的文档基线工作区和 2026-11-08 的提交前评审工作区执行通过；这是 SDD 文档验收命令，不等同于 `.github/workflows/ci.yml` 的全量 CI 命令：

```bash
python3 -m coverage run -m pytest --ignore=tests/performance
python3 -m coverage report
python3 -m ruff check src/quant_agent tests
python3 -m mypy src/quant_agent
python3 -m py_compile src/tail_momentum_selector.py $(find src/quant_agent -name '*.py')
```

结果：

- 2026-11-08 P-003/P-006 提交前复跑：`426 passed, 1 skipped`，总覆盖率 `93%`，Ruff 通过，Mypy 通过（56 个源文件），源码编译通过

本次运行的唯一跳过项是 `tests/unit/data/test_westock_adapter.py` 中依赖本机真实 westock 缓存的测试。跳过取决于本机 `cache/` 是否存在，不应表述为 CI 的普遍行为。`.github/workflows/ci.yml` 运行 `python -m coverage run -m pytest`（包含 `tests/performance/`），而 `docs/RUNBOOK.md:161` 称性能基准不进入默认 CI，二者存在策略冲突，登记为 `P-014`。

2026-11-08 评审使用 Python 3.11.9 隔离虚拟环境复跑。实际安装集合为 `requirements.txt`、`requirements-dev.txt`，再补装 `pytz==2026.6`、`pyarrow==26.0.1`、`pyyaml==6.0.3`。首次仅按前两个文件安装时出现 4 个可选适配器测试失败：`duckdb==2.0.0` 在该环境查询 `TIMESTAMPTZ` 时缺少 `pytz`，`pyarrow` 未声明在开发依赖中。补齐后结果为 `407 passed, 1 skipped`、`TOTAL 3565 253 93%`、Ruff `All checks passed!`、Mypy 通过、源码编译退出码 0。根因登记为 `P-014`，不混入本次文档提交。

## 2. 已完成任务

### T-001 建立 SDD 文档基线

- 依赖：无
- 范围：新增 `docs/sdd/proposal.md`、`docs/sdd/design.md`、`docs/sdd/api-spec.yaml`、`docs/sdd/task.md`，并建立文档变更治理。
- 验收标准（SC-11、AC-11）：四份文档存在；范围、非目标、成功标准、验收场景、架构决策、接口契约、任务依赖和验证证据齐全；YAML 可解析；文档之间的任务编号和验收编号可追溯。
- 状态：`[x]`
- 证据：
  - `docs/sdd/proposal.md`、`docs/sdd/design.md`、`docs/sdd/api-spec.yaml`、`docs/sdd/task.md`
  - 2026-11-08 提交前复核：YAML 唯一键解析通过，27 个 Schema、33 次 `$ref` 引用、10 个不同目标、0 个缺失目标
  - 17 个 `P-*` 任务均有定义；仓库相对文档引用均存在
  - 四份新增文件均以换行结尾、无 Tab、无行尾空格；暂存后使用 `git diff --cached --check` 复核

### T-010 冻结遗留尾盘扫描器

- 依赖：无
- 范围：保留 `src/tail_momentum_selector.py` 作为兼容入口和金样来源；不删除、不把旧脚本作为新平台内部依赖。
- 验收标准：旧 CLI 帮助可用；旧解析、报告、股票池和缓存夹具测试通过；尾盘策略金样与遗留结果逐字段对齐。
- 状态：`[x]`
- 证据：
  - `tests/unit/test_legacy_cli_help.py`
  - `tests/unit/test_legacy_market_data.py`
  - `tests/unit/test_legacy_parsers.py`
  - `tests/unit/test_legacy_report.py`
  - `tests/unit/test_legacy_universe.py`
  - `tests/unit/strategies/test_tail_momentum_legacy_equivalence.py`

### T-020 领域模型、时钟与运行清单

- 依赖：T-010
- 范围：`Instrument`、`Signal`、`Order`、`RunManifest`、`Clock` 和 `RunManifestFactory`。
- 验收标准：字段不变量可验证；时间必须为 timezone-aware；`RunManifest` 内容哈希可重算；固定时钟可注入。
- 状态：`[x]`
- 证据：
  - `tests/unit/domain/test_models.py`
  - `tests/unit/domain/test_clock.py`
  - `tests/unit/application/test_run_manifest_factory.py`

### T-030 建立 PIT 数据端口与适配器

- 依赖：T-020
- 范围：内存、CSV、Parquet、DuckDB、westock；原始响应缓存；规范化层；质量事件收集。
- 验收标准：未来数据不可见；同一时间戳取最新可见修订；无可见数据时 `DataUnavailable`；文件解析错误 fail closed；适配器共享契约测试。
- 状态：`[x]`
- 证据：
  - `tests/contract/test_market_data_port.py`
  - `tests/unit/data/test_market_data_port.py`
  - `tests/unit/data/test_file_market_data_ports.py`
  - `tests/unit/data/test_westock_adapter.py`
  - `tests/unit/data/test_normalize.py`
  - `tests/unit/application/test_data_layers.py`
  - `tests/unit/application/test_feature_store.py`

### T-040 实现 A 股规则与交易日历

- 依赖：T-020
- 范围：交易时段、连续竞价、盘后定价、停牌、涨跌停、tick、整手、T+1、新股豁免、静态和外部日历。
- 验收标准：规则拒绝返回机器可读原因码；主板/科创板/创业板涨跌幅正确；同日买入不可卖；2027+ 未提供外部日历时 fail closed。
- 状态：`[x]`
- 证据：
  - `tests/unit/rules/test_trading_rules.py`
  - `tests/unit/rules/test_trading_calendar.py`
  - `tests/unit/rules/test_rule_references.py`
  - `tests/unit/data/test_calendar_source.py`

### T-050 建立共享成交内核与订单状态机

- 依赖：T-040
- 范围：`ExecutionCore`、`ExecutionCosts`、订单状态机、滑点、tick 量化、佣金、印花税、现金、持仓、T+1。
- 验收标准：回测和模拟盘成交结果等价；所有非冻结路径必须走同一成交内核；非法状态迁移和重复订单拒绝。
- 状态：`[x]`
- 证据：
  - `tests/unit/application/test_execution_core.py`
  - `tests/unit/backtest/test_execution_equivalence.py`
  - `tests/unit/backtest/test_order_state.py`
  - `tests/unit/application/test_run_manifest_factory.py`

### T-060 实现日频、分钟频和网格回测

- 依赖：T-030、T-040、T-050
- 范围：多标的日频引擎、分钟频决策引擎、网格引擎、日期过滤、样本切分、滚动窗口、基准、指标和 JSON 输出。
- 验收标准：`backtest run` 可输出 orders/fills/summary；分钟频只使用决策时刻及之前的 bar；样本切分和滚动窗口互斥校验；网格成交经过规则层。
- 状态：`[x]`
- 证据：
  - `tests/unit/backtest/test_engine.py`
  - `tests/unit/backtest/test_minute_engine.py`
  - `tests/unit/backtest/test_multi_instrument_engine.py`
  - `tests/unit/backtest/test_grid_engine.py`
  - `tests/unit/backtest/test_metrics.py`
  - `tests/unit/cli/test_cli_commands.py`

### T-070 建立策略插件体系与五个策略

- 依赖：T-020、T-030
- 范围：`StrategyRegistry`、`StrategyMetadata`、配置 Schema、五个插件、启停、版本历史、回滚和插件崩溃隔离。
- 验收标准：插件可注册和列出；同 id 新版本可回滚；非法配置拒绝；插件异常转 `PLUGIN_CRASH` 且不中断其他插件；五个策略有固定夹具。
- 状态：`[x]`
- 证据：
  - `tests/unit/strategies/test_registry.py`
  - `tests/unit/strategies/test_config_schema.py`
  - `tests/unit/strategies/test_plugin_isolation.py`
  - `tests/unit/strategies/test_tail_momentum.py`
  - `tests/unit/strategies/test_tail_momentum_wiring.py`
  - `tests/unit/strategies/trend_breakout/test_trend_breakout.py`
  - `tests/unit/strategies/mean_reversion/test_mean_reversion.py`
  - `tests/unit/strategies/low_vol_quality/test_low_vol_quality.py`
  - `tests/unit/strategies/industry_rotation/test_industry_rotation.py`

### T-080 实现信号合成与组合风险

- 依赖：T-070、T-050
- 范围：同标的净目标、单票/行业/总仓位/流动性/回撤/黑名单/相关性预算、质量门阻断和不可变风险决策。
- 验收标准：冲突信号合成唯一净目标；每个目标有 `RiskDecision`；被阻断策略产生 `STRATEGY_BLOCKED`；拒绝原因机器可读。
- 状态：`[x]`
- 证据：
  - `tests/unit/portfolio/test_composer.py`
  - `tests/unit/strategies/test_reporting.py`

### T-090 建立 Agent 权限、工具与审计边界

- 依赖：T-020、T-030
- 范围：四角色 allow/forbid、Gateway、工具执行器、提示词模板、JSON Schema 输出校验、JSONL 审计。
- 验收标准：未知角色、越权工具、实时下单工具和跳过质量门全部拒绝；审计事件绑定运行清单；Agent 输出不是执行指令。
- 状态：`[x]`
- 证据：
  - `tests/unit/agents/test_agent_roles.py`
  - `tests/unit/agents/test_gateway.py`
  - `tests/unit/agents/test_gateway_integration.py`
  - `tests/unit/agents/test_role_tools.py`
  - `tests/unit/agents/test_prompts.py`
  - `tests/unit/cli/test_cli_agent_review.py`

### T-100 实现模拟盘审批与模拟成交

- 依赖：T-040、T-050、T-090
- 范围：审批账本、配置哈希绑定、dry-run、默认模拟执行器、盘后定价队列、T+1 和订单状态。
- 验收标准：无审批拒绝；dry-run 返回空计划；非 dry-run 无执行器/无市场数据 fail closed；模拟成交复用 `ExecutionCore`；`prod` 恒 dry-run。
- 状态：`[x]`
- 证据：
  - `tests/unit/agents/test_paper_gateway.py`
  - `tests/unit/agents/test_paper_execution.py`
  - `tests/unit/agents/test_paper_cli.py`
  - `tests/unit/configs/test_environments.py`

### T-110 实现文本/HTML 报告

- 依赖：T-020、T-070
- 范围：`src/quant_agent/strategies/reporting.py` 的新平台信号文本报告与自包含 HTML；动态文本转义、免责声明。
- 验收标准（SC-09、AC-09）：空信号有明确输出；新平台 HTML 无外部依赖；动态文本转义；免责声明始终存在。
- 状态：`[x]`
- 边界：冻结的 `src/tail_momentum_selector.py` 旧看板不属于本任务；其未转义风险登记为 `P-016`。
- 证据：
  - `tests/unit/strategies/test_reporting.py`
  - `tests/unit/cli/test_cli_report.py`

### T-120 配置、容器与运行手册

- 依赖：T-100、T-110
- 范围：四套环境配置、Dockerfile、Compose、RUNBOOK、fail-closed 容器入口。
- 验收标准：四套环境 JSON 合法；配置无密钥；`prod` 恒 dry-run；容器可构建；无审批账本时退出码 2；运行手册覆盖 CLI 和故障处理。
- 状态：`[x]`
- 证据：
  - `tests/unit/configs/test_environments.py`
  - `docs/RUNBOOK.md`
  - `Dockerfile`
  - `docker-compose.yml`

### T-130 建立质量闸门与性能基准

- 依赖：T-010 至 T-120
- 范围：pytest、覆盖率、Ruff、Mypy、源码编译、CI、日频性能基准。
- 验收标准：核心覆盖率 ≥ 90%；Ruff/Mypy 阻断；3000 标的 × 5 年日频基准可运行并记录回归阈值。
- 状态：`[x]`
- 证据：
  - `.github/workflows/ci.yml`
  - `.coveragerc`
  - `tests/performance/test_benchmark.py`
  - `docs/RUNBOOK.md` 的“性能基准”章节
  - 本次基线：407 passed / 1 skipped / 93% coverage / Ruff clean / Mypy clean

### T-140 校验机器可读接口契约

- 依赖：T-001
- 范围：检查 `docs/sdd/api-spec.yaml` 可解析、命令/模型引用存在、任务编号可追溯。
- 验收标准（SC-11、AC-11）：YAML 解析成功；引用的 `components.schemas` 均存在；文档中 `P-*` 任务均有定义；CLI 参数与当前 `build_parser()` 对齐。
- 状态：`[x]`
- 证据：
  - Python `yaml` 唯一键解析 + `$ref` 扫描：`schemas=27 refs=33 distinct_targets=10 missing=0`
  - `jsonschema.Draft202012Validator.check_schema`：27 个 Schema 语法全部通过
  - 关键产物样例：`StrategyList`、`ApprovalLedger`、`BacktestEnvelope`、`PaperRunOutput`（完整与精简订单）、`AgentReviewOutput`、`AuditEvent`（含 `output=null` 的拒绝事件）、`LegacySignalArtifact` 均通过
  - 任务编号扫描：`P tasks defined=17 referenced=17 missing=0`
  - CLI 参数按 `src/quant_agent/cli/` 五个模块的 `build_parser()` 对齐；数值均排除 `-h/--help`：`strategy.list=0`、`backtest.run=14`、`report.show=1`、`agent.review=1`、`paper.approve=4`（含全局 `--approvals`）、`paper.run=4`（含全局 `--approvals` 与 `--dry-run`）

## 3. 待完成任务

以下任务是当前架构差距，不代表现有能力失效。未完成前不得在提案或对外说明中宣称对应端到端能力已交付。

### P-001 策略插件接入回测

- 依赖：T-060、T-070、T-080、P-003
- 目标：新增一个确定性的策略回测编排器，读取策略配置和 PIT 数据，生成 `Signal`，经组合层转为目标，再由回测引擎生成订单和成交。
- 验收标准：
  1. 固定夹具上，同一配置产生可重复的信号序列。
  2. 信号只使用 `as_of` 可见数据。
  3. 订单经过 `TradingRulesPlugin` 和 `ExecutionCore`。
  4. 输出包含 `RunManifest`、信号摘要、目标仓位、订单、成交和指标。
  5. 至少覆盖尾盘动量与一个日频策略的端到端测试。
- 状态：`[ ]`
- 预计影响：`src/quant_agent/application/`、`src/quant_agent/cli/backtest.py`、测试夹具、`docs/sdd/api-spec.yaml`

### P-002 策略插件接入模拟盘

- 依赖：P-001、T-100
- 目标：模拟盘由策略输出驱动，不再把 `universe` 直接当作无条件买入列表。
- 验收标准：
  1. 模拟盘运行时先调用策略注册表和策略上下文。
  2. 只有通过组合与风险层的目标才进入模拟执行。
  3. 审批记录绑定策略版本、配置哈希和数据快照。
  4. 无信号时返回 `PAPER_EXECUTED` 或明确的 `NO_SIGNAL`，不得生成空买入。
  5. dry-run 和非 dry-run 都保留审计证据。
- 状态：`[ ]`
- 预计影响：`src/quant_agent/agents/paper.py`、`src/quant_agent/cli/paper.py`、`src/quant_agent/application/`、测试

### P-003 统一 Signal 到 Composer 的适配契约

- 依赖：T-080
- 目标：提供从 `Signal` 领域对象到 `SignalComposer` 输入的显式适配器，统一行业、有效期、证据和策略版本。
- 验收标准：
  1. 不在 Composer 中静默读取缺失的 `industry`。
  2. 过期信号被拒绝或忽略，并产生明确原因码。
  3. 多个策略的同一标的权重可追溯。
  4. 适配器有单元测试和 API 文档。
- 状态：`[x]`
- 证据：
  - `tests/unit/portfolio/test_signal_adapter.py` 覆盖保留版本/evidence、有效期校验、行业缺失/冲突、重复信号、拒绝决策追溯和 `compose_domain` 多策略权重。
  - `docs/sdd/design.md` 新增 `SignalAdapter` 契约；`docs/sdd/api-spec.yaml` 新增 `ComposerSignal`、`SignalAdapterResult`、`TargetPosition`、`RiskDecision`、`CompositionResult` 契约。
  - 本次验证：`426 passed, 1 skipped`，覆盖率 `93%`；Ruff/Mypy/源码编译通过；YAML 唯一键解析和 32 个 Schema 语法通过，`$ref` 目标缺失为 0。

### P-004 质量门接入生产管线

- 依赖：T-030、T-080
- 目标：所有策略运行前采集质量事件，`block` 自动阻断受影响策略；`warn` 在报告显著展示。
- 验收标准：
  1. `QualityEventCollector` 由数据端口和运行管线共享。
  2. `blocked_strategy_ids()` 自动传入 `compose()`。
  3. 被阻断策略产生 `STRATEGY_BLOCKED` 决策。
  4. 报告展示 warn/block 摘要。
  5. 有端到端测试。
- 状态：`[ ]`

### P-005 运行清单与审计产物接线

- 依赖：T-020、T-090
- 目标：每次 CLI 运行生成 `RunManifest`，并写入数据快照、配置哈希、策略版本和 Agent 审计。
- 验收标准：
  1. 回测、模拟盘、报告和 Agent 命令均能关联 `run_id`。
  2. 产物不可脱离 manifest 单独解释。
  3. 审计 sink 写入失败时运行标记为失败或显式告警。
  4. 测试覆盖 manifest 哈希、缺失字段和持久化。
- 状态：`[ ]`

### P-006 提取 ports 包并消除边界例外

- 依赖：T-030
- 目标：把 `MarketDataPort`、`DataUnavailable`、`Clock` 等协议/异常从 adapters/application 中抽出，形成稳定端口层。
- 验收标准：
  1. `application` 不再直接导入具体 adapter 异常。
  2. `StrategyContext` 使用协议而非具体 InMemory 实现。
  3. 端口契约测试不依赖具体适配器。
  4. `docs/sdd/design.md` 的依赖方向与实际 import 一致。
- 状态：`[x]`
- 证据：
  - `tests/contract/test_ports.py` 和 `tests/contract/test_clock.py` 使用适配器无关 fake 覆盖端口结构、PIT 可见性、缺数据 fail closed、`Bar` 可见性不变量和时钟契约。
  - `tests/unit/architecture/test_boundaries.py` 以 AST 检查 `application` 与 `strategies` 不得导入 `adapters.market_data`。
  - 旧路径 `quant_agent.adapters.market_data` 与 `quant_agent.domain.clock` 保留兼容导出。

### P-007 统一环境配置加载

- 依赖：T-120
- 目标：CLI 根据 `--environment` 或配置路径加载 `configs/environments/*.json`，并应用 dry-run、审批、日志和审计设置。
- 验收标准：
  1. `prod` 无法通过环境配置启用非 dry-run。
  2. `paper` 默认强制审批。
  3. 未识别环境 fail closed。
  4. 配置文件不读取密钥。
  5. CLI 测试覆盖四套环境。
- 状态：`[ ]`

### P-008 暴露高级成交配置

- 依赖：T-050、T-060、T-100
- 目标：让 CLI 配置支持 `fill_model`、`board_queue_policy`、`session` 和盘后定价参数，并与 Python API 行为一致。
- 验收标准：
  1. 回测和模拟盘的同一配置字段语义一致。
  2. 非法值 fail closed。
  3. `vwap` 缺 `amount/volume` 时拒绝。
  4. 锁板队列和盘后定价有 CLI 级测试。
- 状态：`[ ]`

### P-009 建立分钟频规模基准

- 依赖：T-060、T-130
- 目标：为分钟频回测定义可重复的规模、内存和耗时基准。
- 验收标准：
  1. 明确标的数、交易日数、每日 bar 数和数据规模。
  2. 记录基线耗时、峰值内存和失败阈值。
  3. 基准不进入常规 CI，但可在发布前执行。
  4. 与日频基准分开报告。
  5. 增加 `--decision 1430` 的分钟频防未来回归用例，覆盖 AC-01 的 14:30 场景。
- 状态：`[ ]`

### P-010 完成日历与规则年度复核

- 依赖：T-040
- 目标：以当前引用表为准，复核仍未逐字取文的交易所条款和必要的规则变更，不重复已经登记的年度核对。
- 验收标准：
  1. 以 `docs/RULES_REFERENCES.md` 和 `src/quant_agent/rules/references.py` 的当前备注为准，只复核仍未逐字取文的条款。
  2. 未核对项保留 `verified_online=False` 并写明原因。
  3. 规则变更通过新增测试锁定。
  4. `docs/RULES_REFERENCES.md` 与代码引用表一致。
- 状态：`[ ]`

### P-011 实现部分成交与撤单模型

- 依赖：T-050、T-060
- 目标：为未来更精细的模拟盘/回测增加 `PARTIALLY_FILLED`、撤单和剩余数量，不破坏现有 FILLED/REJECTED 行为。
- 验收标准：
  1. 状态机迁移完整且有非法迁移测试。
  2. 现金、持仓、费用和 T+1 账本在部分成交下仍一致。
  3. 回测和模拟盘共享同一实现。
  4. 默认关闭时现有金样不变。
- 状态：`[ ]`

### P-013 持久化模拟盘账本与运行历史

- 依赖：T-100、P-005
- 目标：把模拟盘现金、持仓、已结算数量、订单状态、运行历史和盘后意图持久化到可恢复的 paper account。
- 验收标准：
  1. 进程重启后能恢复现金、持仓、结算状态和未完成盘后意图。
  2. 每次运行写入 `run_id`、配置哈希、审批记录和成交摘要。
  3. 账本写入失败时 fail closed，不继续下单。
  4. 有并发写入保护或明确的单进程限制。
  5. 测试覆盖重启恢复、重复运行和损坏账本。
- 状态：`[ ]`

### P-014 锁定可选适配器开发依赖

- 依赖：T-030、T-130
- 目标：让全新 Python 3.11 虚拟环境只安装 `requirements.txt` 和 `requirements-dev.txt` 即可运行完整测试套件。
- 验收标准：
  1. `duckdb` 查询 `TIMESTAMPTZ` 所需的 `pytz` 被显式声明并锁定版本。
  2. `pyarrow` 被显式声明并锁定版本，或在测试缺依赖时统一 skip 而非 fail。
  3. `pyyaml` 如用于仓库内契约校验脚本，必须显式声明并锁定版本；否则注明仅供评审环境使用、不得成为 CI 前置条件。
  4. CI 使用干净环境执行全套测试并通过。
  5. `docs/RUNBOOK.md` 与依赖声明一致，修正“两者均已列入 requirements-dev”的不准确描述。
  6. 依赖变更后重跑覆盖率、Ruff、Mypy 和源码编译。
  7. 明确 CI 是否运行 `tests/performance/`，同步 `.github/workflows/ci.yml`、`pytest.ini`、`docs/RUNBOOK.md` 和干净环境的 skip/pass 矩阵。
- 状态：`[ ]`

### P-015 建立接口契约自动校验

- 依赖：T-140
- 目标：新增仓库内脚本和 CI 步骤，解析 `docs/sdd/api-spec.yaml`，校验全部 Schema、代表性 CLI/产物输出、所有本地路径、ID/数量追溯，并把结果写入 `docs/sdd/task.md`。
- 验收标准（SC-11、AC-11）：
  1. 默认模拟执行器输出满足 `PaperOrder`，注入式精简执行器输出满足 `PaperMinimalOrder`；若保留开放 `PaperExecution` 协议，必须在 CLI 归一化输出或把契约扩展为所有合法注入结果，并在 `P-015` 验收中锁定。
  2. `agent review` 的 null 字段、拒绝事件 `output=null`、`paper` 审批覆写语义、遗留 argparse 退出码 2、现代 CLI 参数错误退出码 2、遗留/现代未捕获异常退出码 1 均有契约样例。
  3. 校验命令在干净环境可执行，失败时阻断 CI。
  4. `docs/sdd/task.md` 中的数量由脚本生成或由脚本核对。
- 状态：`[ ]`

### P-016 修复冻结旧看板的 HTML 转义

- 依赖：T-010
- 目标：评估冻结遗留入口是否允许安全修复；在 `src/tail_momentum_selector.py` 的 `build_html` 中对供应商名称、代码、排除原因等动态文本转义，或明确废弃旧看板。
- 验收标准（SC-12）：
  1. 恶意字符串进入 `name`、`code`、`miss` 时不产生可执行 HTML。
  2. 自包含和免责声明不回退。
  3. 固定夹具的可见文本保持等价。
  4. `docs/sdd/api-spec.yaml` 的 `legacy_dashboard` 契约同步移除风险说明。
- 状态：`[ ]`

### P-017 加固模拟盘审批账本

- 依赖：T-100、P-013
- 目标：把审批账本改为原子替换或追加式审计，并定义并发写入约束。
- 验收标准：
  1. 写入过程中崩溃不留下半截 JSON。
  2. 同一 `(strategy_id, config_hash)` 重复审批的语义确定且可追溯。
  3. 并发写入被锁或明确限制为单进程。
  4. `docs/sdd/api-spec.yaml` 与 `docs/sdd/design.md` 同步描述真实语义。
- 状态：`[ ]`

### P-012 合并与发布准备

- 依赖：P-001、P-002、P-003、P-004、P-005、P-006、P-007、P-008、P-009、P-010、P-011、P-013、P-014、P-015、P-016、P-017
- 目标：将 `feat/followup-integration` 的变更按评审流程合入目标分支，更新交接文档和发布说明。
- 验收标准：
  1. 全套质量闸门通过。
  2. `docs/sdd/task.md` 状态和证据更新。
  3. 无未解释的工作区改动。
  4. 合并与推送获得明确授权。
- 状态：`[ ]`

## 4. 验收追溯

| 任务 | 提案验收 | 设计约束/ADR | 接口契约 | 验证证据 |
|---|---|---|---|---|
| T-001、T-140 | SC-11、AC-11 | 变更治理、验证矩阵 | 四份 SDD 契约 | 本节验证结果与 T-140 证据 |
| T-010 | AC-01 | ADR-001 兼容基线、遗留数据流 | `legacy.selector`、`LegacySignalArtifact` | 遗留夹具与金样测试 |
| T-020～T-050 | SC-01～SC-03、AC-01～AC-03 | 领域不变量、PIT、ADR-002/003 | `Bar`、`Order`、`MarketSnapshot`、`error_codes.order` | domain/rules/data/execution 测试 |
| T-060 | SC-04、AC-04 | 回测数据流、ADR-007 | `backtest.run`、`BacktestEnvelope` | CLI 与 backtest 测试 |
| T-070～T-080 | SC-05～SC-06、AC-05～AC-06 | 插件契约、组合风控、ADR-001 | `StrategyList`、`Signal`、组合原因码 | registry/portfolio 测试 |
| T-090～T-100 | SC-07～SC-08、AC-07～AC-08 | Agent 边界、模拟盘、ADR-005 | `AuditEvent`、`paper.*`、Agent 错误码 | Agent/Paper CLI 测试 |
| T-110～T-130 | SC-09～SC-10、AC-09～AC-10 | 报告安全、四环境、质量闸门 | `AgentReviewOutput`、HTML 契约、`EnvironmentConfig` | reporting/config/CI 证据 |
| P-001 | SC-01～SC-04、AC-01～AC-04 | G-01、ADR-002/003/007 | 端到端回测契约（待新增） | 各任务完成后回写 |
| P-002 | SC-08、AC-08 | G-02、ADR-005/007 | `paper.run` 扩展契约 | 各任务完成后回写 |
| P-003 | SC-06、AC-06 | 插件契约 | `SignalAdapter`、`ComposerSignal`、`SignalAdapterResult`、`TargetPosition`、`CompositionResult` | `tests/unit/portfolio/test_signal_adapter.py` |
| P-004 | SC-01、AC-01 | G-04、质量门 | `QualityEvent` 管线契约 | 各任务完成后回写 |
| P-005 | SC-11、AC-11 | G-05、可观测性 | `RunManifest` 产物契约 | 各任务完成后回写 |
| P-006 | SC-11 | 依赖方向/ADR-002 | `ports.market_data`、`ports.clock` | `tests/contract/test_ports.py`、`tests/contract/test_clock.py`、`tests/unit/architecture/test_boundaries.py` |
| P-007 | SC-10、AC-10 | G-07、四环境 | `EnvironmentConfig` CLI 契约 | 各任务完成后回写 |
| P-008 | SC-04、AC-04 | G-08、ADR-003 | `BacktestCostConfig` CLI 契约 | 各任务完成后回写 |
| P-009 | SC-01、AC-01 | NFR 性能、分钟频防未来 | 分钟频基准与 1430 用例 | 各任务完成后回写 |
| P-010 | SC-03、AC-03 | ADR-006、规则引用表 | `src/quant_agent/rules/references.py` | 各任务完成后回写 |
| P-011 | SC-03、AC-03 | ADR-003、订单状态机 | 订单状态契约 | 各任务完成后回写 |
| P-013 | SC-08、AC-08 | G-09、ADR-005 | paper account 产物契约 | 各任务完成后回写 |
| P-014 | SC-11、质量闸门 | G-10、NFR 可复现 | `requirements-dev.txt`/CI 策略 | 干净环境测试矩阵 |
| P-015 | SC-08、SC-11、AC-08、AC-11 | G-12、验证矩阵 | 全部 `components.schemas`、`PaperOrderEntry` | 契约校验脚本与 CI |
| P-016 | SC-12 | G-11 | `legacy_dashboard` | 恶意输入安全回归 |
| P-017 | SC-08、AC-08 | G-13、ADR-005 | `paper.approve` | 崩溃/并发/重复审批测试 |
| P-012 | 全部适用 SC/AC | 全部适用 G/ADR | 全部适用契约 | 全套质量闸门 |

## 5. 执行顺序

```text
T-001
  └── T-010
        ├── T-020 ── T-030 ── T-040
        │                 │       │
        │                 │       ├── T-050
        │                 │       │     ├── T-060
        │                 │       │     └── T-100
        │                 └── T-070 ── T-080
        ├── T-090 ── T-100
        └── T-110 ── T-120
                          └── T-130

P-001 ← T-060 + T-070 + T-080 + P-003
P-002 ← P-001 + T-100
P-004 ← T-030 + T-080
P-005 ← T-020 + T-090
P-006 ← T-030
P-007 ← T-120
P-008 ← T-050 + T-060 + T-100
P-009 ← T-060 + T-130
P-010 ← T-040
P-011 ← T-050 + T-060
P-013 ← T-100 + P-005
P-014 ← T-030 + T-130
P-015 ← T-140
P-016 ← T-010
P-017 ← T-100 + P-013
P-012 ← P-001, P-002, P-003, P-004, P-005, P-006, P-007, P-008, P-009, P-010, P-011, P-013, P-014, P-015, P-016, P-017
```

> 任务 ID 按登记顺序保留，不表示执行顺序；`P-012` 始终最后执行。

## 6. 任务完成规则

1. 先写或更新验收标准，再实现。
2. 每个任务先产生失败测试（Red），再最小实现（Green），最后重构。
3. 一个任务未通过验收，不得开始依赖它的任务。
4. 完成后必须回写状态、验证命令和证据路径。
5. 无法完成的项标记 `[!]` 并写明阻塞原因，不得静默删除。
6. 改变范围、设计或接口时，按 `docs/sdd/proposal.md` → `docs/sdd/design.md` → `docs/sdd/api-spec.yaml` → `docs/sdd/task.md` 的顺序更新。

## 7. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-10-29 | 1.0.0 | 建立四份 SDD 文档；登记已实现基线、架构差距和后续任务 |
| 2026-11-08 | 1.0.1 | 提交前评审：复核质量闸门；隔离环境依赖缺口登记为 P-014 |
| 2026-11-08 | 1.0.2 | 按提交前评审修正 HTML/契约/验证声明，新增 P-015～P-017 与验收追溯矩阵 |
| 2026-11-08 | 1.0.3 | 完成契约自检：27 Schema / 33 引用 / 17 个 P 任务 / CLI 参数与产物样例全部通过 |
| 2026-11-08 | 1.0.4 | 按第二轮评审补齐退出码、null 审计输出、追溯矩阵、路径和行尾空格修正 |
| 2026-11-08 | 1.0.5 | 按第三轮评审统一 per-command 退出码、G-10 映射与测试路径 |
| 2026-11-08 | 1.0.6 | 完成 P-003：Signal 适配、有效期/行业 fail closed、策略追溯、类型化 ComposerSignal 与评审修正 |
| 2026-11-08 | 1.0.7 | 完成 P-006：提取 ports 包并消除 adapter 边界例外 |

> 研究产物，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。
