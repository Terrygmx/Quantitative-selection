# low_vol_quality

低波动质量策略（DETAILED_DESIGN §6 初始策略序列第 4 个），中低频、与动量类策略低相关的分散配置。

## 规则

对 universe 中每只标的，用日频 bars 判定，三者同时成立才发 `long` 信号：

- **低波动**：最近 `vol_window`（默认 20）日收益率标准差 ≤ `vol_threshold`（默认 1.5%/日）；
- **质量/趋势**：收盘价高于 `trend_window`（默认 60）日均线；
- **流动性**：最近 5 日平均成交额 ≥ `liquidity_amount_yi` 亿（默认 1 亿）。

`target_weight=1.0`，`valid_to = as_of + holding_days` 天（默认 20 日）。warmup = `trend_window + 1`，不足抛错（fail closed）。

## 配置（config.schema.json）

```json
{"universe": ["sh600519"], "vol_window": 20, "vol_threshold": 0.015, "trend_window": 60, "holding_days": 20}
```

## 证据字段

`evidence` 携带 `realized_vol`、`vol_threshold`、`vol_window`、`trend`、`above_trend`、`avg_amount_5d`。
