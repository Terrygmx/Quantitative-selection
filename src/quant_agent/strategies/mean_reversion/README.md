# mean_reversion_liquid

高流动性股票短周期均值回归（DETAILED_DESIGN §6 初始策略序列第 3 个），持有期数日。

## 规则

对 universe 中每只标的，用日频 bars 判定，三者同时成立才发 `long` 信号：

- **超跌**：最新收盘价低于「跌之前的 MA5 参考位」（不含当根，避免跌幅稀释自身度量）至少 `deviation_threshold`（默认 3%）；
- **趋势内回调**：收盘价仍高于 MA20（不在下趋势中接刀）；
- **流动性**：最近 5 日平均成交额 ≥ `liquidity_amount_yi` 亿（默认 1 亿）。

`target_weight=1.0`，`valid_to = as_of + holding_days` 天（默认 5 日）。warmup 21 根 bar，不足抛错（fail closed）。

## 配置（config.schema.json）

```json
{"universe": ["sh600519"], "deviation_threshold": 0.03, "liquidity_amount_yi": 1.0, "holding_days": 5}
```

## 证据字段

`evidence` 携带 `deviation`（相对参考 MA5）、`ma5`、`ma20`、`above_ma20`、`avg_amount_5d`、`liquidity_floor`、`deviation_threshold`。
