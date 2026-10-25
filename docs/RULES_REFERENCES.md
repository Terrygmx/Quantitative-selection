# 交易规则官方引用（M2 规则引用适配）

单一登记处为 `src/quant_agent/rules/references.py` 的 `RULE_REFERENCES`（`RuleReference` 数据类），
`tests/unit/rules/test_rule_references.py` 锁定：每个已实现规则领域都有引用、字段完整、未在线核对的引用必须显式说明。

## 状态声明

所有引用均在离线环境登记，`verified_online=False`：引用的文件名、文号与 URL **尚未在线核对原文**。
补齐方式：联网后逐条打开来源核对条文（涨跌幅、时段、T+1、整手/tick、盘后定价），确认后置 `verified_online=True` 并提交证据链接。
2023–2026 静态节假日数据同样需要逐年核对；2027 及以后由外部数据文件供给（见 RUNBOOK「外部交易日历」）。

## 已登记领域

| 领域 | 规则 | 来源 |
|---|---|---|
| `price_limits_main_board` | 主板 ±10% | 沪深交易所交易规则 |
| `price_limits_star_chinext` | 科创板/创业板 ±20%（创业板 2020-08-24 起） | 沪深交易所交易规则（科创板章节）/ 创业板交易特别规定 |
| `price_limits_new_listing` | 科创/创业新股前 5 日无涨跌幅 | 同上 |
| `t_plus_one` | 当日买入不得当日卖出 | 沪深交易所交易规则（回转交易限制） |
| `lot_and_tick` | 100 股整手、卖出可含零股、0.01 元最小价位 | 沪深交易所交易规则 |
| `continuous_auction_sessions` | 连续竞价 9:30–11:30、13:00–15:00 | 沪深交易所交易规则 |
| `after_hours_fixed_price` | 盘后定价交易申报与撮合窗口 | 上交所科创板盘后固定价格交易指引（上证发〔2019〕21号）等 |
| `trading_calendar_holidays` | 周末与法定节假日休市 | 沪深交易所交易规则 + 国务院办公厅年度通知 |
