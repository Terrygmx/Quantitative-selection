# 运行手册

## 环境准备

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
```

核心包运行时依赖仅 `jsonschema`（Agent 结构化输出校验）和 Python 标准库；测试、覆盖率、lint 和性能工具只属于开发依赖。

## 日常验证

```bash
python3 -m coverage run -m pytest --ignore=tests/performance
python3 -m coverage report --fail-under=90
python3 -m ruff check src/quant_agent tests
```

CI 使用相同流程，并额外编译遗留入口 `src/tail_momentum_selector.py` 和 `src/quant_agent` 全部源码。

## 模拟盘命令

模拟盘只接受已保存审批的策略配置。审批文件默认位于 `state/paper-approvals.json`，记录策略 ID、配置哈希和批准人；配置内容本身必须包含相同的 `config_hash`。

```bash
# 先检查及批准配置
PYTHONPATH=src python3 -m quant_agent.cli.paper \
  --approvals state/paper-approvals.json approve \
  --strategy tail_momentum_overnight \
  --config configs/tail_momentum.json \
  --approved-by operator

# 默认 dry-run：只返回空订单计划
PYTHONPATH=src python3 -m quant_agent.cli.paper \
  --approvals state/paper-approvals.json run \
  --strategy tail_momentum_overnight \
  --config configs/tail_momentum.json --dry-run

# 非 dry-run：必须由调用方注入执行器，否则 fail closed
```

`PaperGateway.run(dry_run=False)` 只有在构造时注入 `PaperExecution` 才会执行；CLI 默认不注入执行器，以免在没有交易通道和运行清单的情况下误发订单。退出码 `0` 表示成功，`2` 表示审批、配置或执行器错误。

## 性能基准

基准用合成数据验证 3000 只股票 × 5 年（1260 个样本日）的多标的回测事件时钟：

```bash
python3 -m pytest tests/performance
```

当前基线（Apple Silicon 本机，2026-10-24）：约 70.5 秒。每次优化后重跑并更新本数字；如回归超过 10%，在合入前先定位热点。该测试不进入默认 CI，以免拖慢常规反馈。

## 测试分层

- `tests/unit`：领域规则、应用服务、策略插件、Agent 权限。
- `tests/contract`：Market Data Port 契约，后续 CSV/Parquet/DuckDB 适配器复用。
- `tests/performance`：规模化基准，显式单独运行。
- `tests/fixtures/legacy`：遗留策略行为锁定的脱敏夹具。
