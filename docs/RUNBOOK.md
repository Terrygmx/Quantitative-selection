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
