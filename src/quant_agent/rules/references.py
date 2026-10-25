"""Registry mapping each implemented A-share rule area to its official
source document. Every citation here was recorded offline: `verified_online`
is False until someone opens the source and checks it (see M2 TODO), so the
platform never claims a verification that did not happen."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuleReference:
    area: str
    rule: str
    source_title: str
    issuer: str
    document_number: str = ""
    url: str = ""
    verified_online: bool = False
    note: str = ""


_SSE_TRADING_RULES_2026 = "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml"
_SZSE_CHINEXT_PROVISIONS = "https://www.szse.cn/lawrules/rule/repeal/rules/P020231230545310237980.pdf"

_UNVERIFIED = "离线环境记录，未在线核对原文；引用与条文需在线验证后置 verified_online=True"


RULE_REFERENCES: dict[str, RuleReference] = {
    ref.area: ref
    for ref in (
        RuleReference(
            area="price_limits_main_board",
            rule="主板股票涨跌幅限制 ±10%",
            source_title="上海证券交易所交易规则（2026年修订）/ 深圳证券交易所交易规则",
            issuer="SSE/SZSE",
            url=_SSE_TRADING_RULES_2026,
            note=_UNVERIFIED + "；URL 摘自 PRODUCT_REQUIREMENTS.md",
        ),
        RuleReference(
            area="price_limits_star_chinext",
            rule="科创板、创业板股票涨跌幅限制 ±20%（创业板自 2020-08-24 起）",
            source_title="上海证券交易所交易规则（科创板章节）/ 深圳证券交易所创业板交易特别规定",
            issuer="SSE/SZSE",
            url=_SZSE_CHINEXT_PROVISIONS,
            note=_UNVERIFIED + "；URL 摘自 PRODUCT_REQUIREMENTS.md",
        ),
        RuleReference(
            area="price_limits_new_listing",
            rule="科创板/创业板新股上市前 5 个交易日不设涨跌幅",
            source_title="上海证券交易所交易规则（科创板章节）/ 深圳证券交易所创业板交易特别规定",
            issuer="SSE/SZSE",
            url=_SZSE_CHINEXT_PROVISIONS,
            note=_UNVERIFIED,
        ),
        RuleReference(
            area="t_plus_one",
            rule="当日买入的股票不得当日卖出（T+1）",
            source_title="上海证券交易所交易规则 / 深圳证券交易所交易规则（回转交易限制章节）",
            issuer="SSE/SZSE",
            note=_UNVERIFIED,
        ),
        RuleReference(
            area="lot_and_tick",
            rule="买入申报为 100 股整数倍，卖出可含零股；最小价格变动 0.01 元",
            source_title="上海证券交易所交易规则 / 深圳证券交易所交易规则（申报数量与价格章节）",
            issuer="SSE/SZSE",
            note=_UNVERIFIED,
        ),
        RuleReference(
            area="continuous_auction_sessions",
            rule="连续竞价时段 9:30-11:30、13:00-15:00",
            source_title="上海证券交易所交易规则 / 深圳证券交易所交易规则（交易时段章节）",
            issuer="SSE/SZSE",
            note=_UNVERIFIED,
        ),
        RuleReference(
            area="after_hours_fixed_price",
            rule="科创板/创业板盘后固定价格交易：申报 9:30-11:30、13:00-15:30，15:05-15:30 按收盘价撮合",
            source_title="上海证券交易所科创板股票盘后固定价格交易指引 / 深圳证券交易所创业板交易特别规定",
            issuer="SSE/SZSE",
            document_number="上证发〔2019〕21号",
            note=_UNVERIFIED + "；时段与申报窗口以指引原文为准",
        ),
        RuleReference(
            area="trading_calendar_holidays",
            rule="周末与法定节假日休市；节假日安排按年发布",
            source_title="上海证券交易所交易规则 / 深圳证券交易所交易规则（休市安排）与国务院办公厅节假日安排通知",
            issuer="SSE/SZSE",
            note=_UNVERIFIED + "；2023-2026 静态数据需逐年核对，2027+ 由外部数据文件供给",
        ),
    )
}

IMPLEMENTED_RULE_AREAS = tuple(RULE_REFERENCES)
