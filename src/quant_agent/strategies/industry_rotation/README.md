# industry_rotation

行业动量轮动（DETAILED_DESIGN §6 初始策略序列第 4 个的替代选项），中频、与个股策略低相关。

## 规则

配置 `industry_universe`（行业名 → 行业指数/代理标的代码）。每个快照时刻：

1. 对每个行业代理计算 `momentum_window`（默认 20）日收益率；
2. 按动量降序排名，取前 `top_n`（默认 2）；
3. 仅动量 > 0 的行业发 `long` 信号（全市场走弱时空仓，不做空）。

`target_weight=1.0`，`valid_to = as_of + holding_days` 天（默认 10 日）。warmup = `momentum_window + 1`。行业代理数据不足按符号抛错（fail closed）。

## 配置（config.schema.json）

```json
{"industry_universe": {"tech": "bk_tech", "utility": "bk_utility"}, "momentum_window": 20, "top_n": 2, "holding_days": 10}
```

## 证据字段

`evidence` 携带 `industry`、`proxy_symbol`、`momentum_window`、`momentum_20d`、`rank`。
