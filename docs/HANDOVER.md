# 工作交接（Handover）

> 面向接手协作或继续开发的 agent。本文档自包含：读完即可按约定开工，无需 archaeology。
> 更新时间：2026-10-25。HEAD `0648baa`，分支 `feat/followup-integration`（领先 main 18 个提交，main 领先远端约 109 个），工作树干净。

## 1. 项目一句话

A 股多策略量化研究平台：策略以插件接入，经 PIT（Point-in-Time）数据门户 → 信号 → 组合风控 → 共享成交内核 → 回测/模拟盘，全链路 A 股规则保真（T+1、涨跌停、整手、时段、盘后定价）、防未来函数、可审计、fail closed。**实盘下单是 PRD 明确非目标**（已结构化锁定，见 §6）。

前身 `src/tail_momentum_selector.py`（1358 行单文件尾盘动量扫描器）已冻结为 legacy 基线：**只读不改**，测试可导入它做等价对照。

## 2. 当前状态（全部验证通过）

```bash
python3 -m pytest --ignore=tests/performance   # 407 passed, 1 skipped
python3 -m coverage run -m pytest --ignore=tests/performance
python3 -m coverage report --fail-under=90     # 93%
python3 -m ruff check src/quant_agent tests    # clean
python3 -m mypy src/quant_agent                # 0 errors（CI 阻断）
python3 -m pytest tests/performance            # 日频基准，单独跑
```

- 唯一 skip：`test_parser_output_matches_legacy_on_real_cached_response`（依赖本机 `cache/` 真实 westock 缓存，CI 无此目录）。
- 性能基准：3000 标的×5 年日频回测，空闲机 67–84s；同机对照法排除过一次伪回归（对照 `git worktree add /tmp/x <旧提交>` 跑同基准）。
- Docker 实机验证过：镜像构建、五 CLI 导入、无审批 fail closed（退出码 2）、approve→dry-run 全流程。
- westock CLI 在本机 `~/.local/bin/westock`（Go 二进制，PATH 可见），适配器已真实联调。

## 3. 工作循环约定（必须遵守）

1. 从 `docs/TODO.md` 选未完成项，一次一个最小纵向切片。
2. **严格 TDD**：先写失败测试（Red），最小实现（Green），按需重构。不改测试迎合实现；发现测试期望写错要说明理由后修正。
3. 切片完成必须 review：对照 `docs/DETAILED_DESIGN.md` 与 `docs/TDD_VIBE_CODING_PLAN.md` 检查 TDD 顺序、领域零 IO、费用/规则复用。review 问题用新 Red 测试驱动修复，再复审。
4. 修不了的写入 `docs/TODO.md`，不静默跳过。
5. 每切片独立非 amend 提交，提交信息带 Red→Green 证据。
6. 不做破坏性 git 操作；不删 legacy；**网络访问需用户明确授权**（本会话曾授权过：规则核对、duckdb 安装、westock 联调均在其下完成）。
7. 提交信息含反引号会被 shell 吞字——用引号包裹或避免反引号。
8. 文档（RUNBOOK/TODO/HANDOVER）随切片同步，这是合并检查清单要求。

## 4. 架构地图（src/quant_agent/）

```
domain/        零 IO：Instrument/Bar(adjustment)/Signal/Order(session)/RunManifest
rules/         唯一裁决者：trading.py（涨跌停方向语义/T+1/整手/时段/盘后定价/申报门/
               交易所区分窗口）、calendar.py（2023–2026 静态+外部文件源）、references.py
application/   execution.py（ExecutionCore：成交/费用/滑点/tick/现金/T+1 唯一份；
               fill_model=slippage|next_open|vwap；board_queue_policy=reject|queue_fill）
               backtest.py（日频多标的引擎；BacktestEngine 金样引擎冻结勿迁）
               intraday.py（分钟引擎 + prefetched() 游标优化工厂）
               grid.py（网格驻留限价单引擎，日界结算）
               portfolio.py（SignalComposer：blocked_strategies 质量门 + 风控约束）
               metrics.py / runs.py / features.py（FeatureStore 定义锁 + Persistent 持久化）
               data_layers.py（RawStore 内容寻址 + CuratedStore Parquet/DuckDB 血缘）
adapters/      market_data.py（InMemory/Csv/Parquet/DuckDB 四端口 + 质量事件）
               westock.py（Markdown 解析与 legacy 逐字段锁定；缓存/在线双源）
               normalize.py（规范化层：代码/时区/adjustment 不混用）
               calendar.py（外部交易日历文件源）
strategies/    5 插件：tail_momentum/ trend_breakout/ mean_reversion/ low_vol_quality/
               industry_rotation/（各含 strategy.py + config.schema.json + README）
               registry.py（启停/版本历史/回滚 + StrategyMetadata.turnover_cap/risk_exposure）
               reporting.py（文本 + 自包含 HTML）、context.py、schema.py
agents/        gateway.py（审计 + tool_executors 执行）、roles.py（四角色边界）、
               role_tools.py（工具执行体）、prompts.py（角色提示模板）、paper.py（模拟盘）
cli/           paper / strategy / backtest / report / agent 五入口
```

测试布局：`tests/unit/{domain,rules,application,strategies,agents,portfolio,backtest,data,configs,cli}`、`tests/contract/`（端口契约参数化 4 实现）、`tests/performance/`、`tests/fixtures/legacy/`（脱敏金样）。

## 5. 硬约束（违反即 review 打回）

1. **domain 零 IO**；**rules 是交易规则唯一裁决者**——任何引擎/执行器不得绕过（引擎只问「这单行不行」和「现在是不是某时段」两个公开 API）。
2. **成交账本只有一份**（ExecutionCore）：新增执行路径必须走它；冻结的 `BacktestEngine` 例外（金样回归夹具）。
3. **PIT 防未来由构造保证**：数据按 `as_of` 查询、`available_at >= timestamp` 不变量；日频收盘 bar 收盘后才可见；网格/分钟引擎的决策只用当前 bar 及之前。
4. **fail closed**：配置缺失/数据缺失/非法输入一律报错拒绝（退出码 2），绝不静默放行或猜测。
5. `universe` 必填；审批账本 `state/paper-approvals.json` 与 `config_hash` 绑定不可绕过；**prod 恒 dry-run**。
6. 引用诚实原则：`rules/references.py` 的 `verified_online=False` 必须附注；产物带免责声明。

## 6. 实盘非目标的锁定方式

`tests/unit/configs/test_environments.py` 锁定：agents 包仅暴露 `PaperExecution` 协议 + `SimulatedPaperExecution` 唯一具体执行器；全包禁止 Live/Real/Broker 执行器类名；网关拒绝 live 工具。未来做实盘 = 显式改这些测试 = 强制设计评审。不要绕开。

## 7. 剩余工作（按需项，无计划内欠账）

1. **合并分支**：`feat/followup-integration` → main → push（用户未授权 push；远端落后约 109 提交）。
2. 深交所静态日历独立逐年复核（历年公告一致，未逐份对深交所原文）。
3. 分钟频规模化基准（待真实分钟数据规模需求）。
4. 排队/网格模型的柜台级精细度（部分成交、挂单撤销）——待实盘需求。
5. 管线组装层接线：`compose(blocked_strategies=collector.blocked_strategy_ids())`（API 已就绪，调用点待建）。
6. 深化方向（PRD 内）：`Signal` 的置信度/相关性预算已在 composer 有接口，可做多策略实盘组合研究；数据侧可接更多源（照 CSV/Parquet 工厂模式）。

## 8. 历史速览（十轮循环，详见 git log）

M0 基线 → M1–M8 里程碑（域模型/规则/PIT/回测/插件/组合/模拟盘/质量闸门）→ 共享成交内核+性能回归修复 → 日历外部源 → 金样 excluded 路径 → 盘后定价（在线核对 2026 沪深新规并修复 4 处差异）→ Mypy 清零入 CI → DuckDB/CSV/Parquet 端口 → westock 适配器（真实联调）→ CLI 四入口 + 可替换成交模型 + trend_breakout → mean_reversion/low_vol_quality + block 门 + 角色边界 → 分钟频回测 + 游标优化 → 数据分层 + 角色工具 + industry_rotation + 四环境/Docker → 注册表生命周期 + Normalized 层 → HTML 报告 + 提示词模板 + 实盘锁定。

关键教训沉淀：mypy 净增错误两次追出真实 bug（新股无 band 崩溃、字符串价格字典序胜率）；TDD 夹具错误多次（时区 +8 方向、band 数学、锁板板块选择）——**测试失败先怀疑夹具语义再怀疑实现**。

## 9. 上手指引（新 agent 的第一个小时）

1. 跑 §2 全套验证命令，确认全绿。
2. 读 `docs/DETAILED_DESIGN.md`（§3 领域模型、§7 成交、§8 Agent）和本文件 §5。
3. 挑 `docs/TODO.md` 一项或 §7 一项，写 Red 测试，开始循环。
4. 有疑义看同类实现：端口适配器抄 `adapters/calendar.py`（最小）、策略抄 `strategies/trend_breakout/`（完整）、引擎改动先看 `application/execution.py` 的等价测试怎么写。
