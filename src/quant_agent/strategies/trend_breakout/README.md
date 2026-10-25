# trend_breakout

日频趋势/突破策略（DETAILED_DESIGN §6 初始策略序列第 2 个），持有期多日。

## 规则

对 universe 中每只标的，用日频 bars 判定：

- **突破**：最新收盘价 > 前 `breakout_window`（默认 20）根 bar 的最高价（唐奇安上轨）；
- **趋势过滤**：`trend_window`（默认 20）日均线仍在上行（当期均线 > 上一期均线）。

两者同时成立才发出 `long` 信号：`target_weight=1.0`，`valid_to = as_of + breakout_window` 天（多日持有语义）。warmup 为 `max(breakout_window, trend_window) + 1` 根 bar，不足按符号抛错（fail closed）。

## 配置（config.schema.json）

```json
{"universe": ["sh600519"], "breakout_window": 20, "trend_window": 20}
```

## 证据字段

`evidence` 携带 `breakout_window`、`prior_high`（被突破的前高）、`close`、`ma20_rising`，供组合层与审计追溯。
