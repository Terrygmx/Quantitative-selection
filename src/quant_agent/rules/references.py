"""Registry mapping each implemented A-share rule area to its official
source document. Entries verified against the source on 2026-10-25 carry
`verified_online=True` plus the clause evidence in their note; anything not
yet checked against an original source stays False and must explain why."""

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
_SSE_CLOSURE_PAGE = "https://www.sse.com.cn/disclosure/dealinstruc/closed"

_VERIFIED = "2026-10-25 在线核对原文"


RULE_REFERENCES: dict[str, RuleReference] = {
    ref.area: ref
    for ref in (
        RuleReference(
            area="price_limits_main_board",
            rule="主板股票涨跌幅限制 ±10%（涨跌幅限制价格=前收盘价×(1±比例)）",
            source_title="上海证券交易所交易规则（2026年修订）3.3.13",
            issuer="SSE/SZSE",
            document_number="上证发〔2026〕41号，2026-07-06 施行",
            url=_SSE_TRADING_RULES_2026,
            verified_online=True,
            note=_VERIFIED + "：3.3.13 原文“涨跌幅限制比例为10%”及计算公式；深交所对应条文未逐字取原文",
        ),
        RuleReference(
            area="price_limits_star_chinext",
            rule="科创板 ±20%（交易规则 6.6）；创业板 ±20% 自 2020-08-24 注册制改革起",
            source_title="上海证券交易所交易规则（2026年修订）6.6 / 深交所创业板注册制改革配套规则",
            issuer="SSE/SZSE",
            document_number="上证发〔2026〕41号",
            url=_SSE_TRADING_RULES_2026,
            verified_online=True,
            note=_VERIFIED + "：科创板 20% 见 6.6 原文；创业板 2020-08-24 起 20% 经人民网当日报道核实；2026 修订后创业板维持 20%，经证监会官方发布（csrc.gov.cn 2026-07-06）确认沪深一致",
        ),
        RuleReference(
            area="price_limits_new_listing",
            rule="IPO 股票上市后前 5 个交易日不设涨跌幅（主板自 2023-02-17 全面注册制起适用）",
            source_title="上海证券交易所交易规则（2026年修订）3.3.13 豁免清单(一) / 全面注册制制度规则",
            issuer="SSE/SZSE",
            document_number="上证发〔2026〕41号；主板适用起点为证监会 2023-02-17 全面注册制规则发布",
            url=_SSE_TRADING_RULES_2026,
            verified_online=True,
            note=_VERIFIED + "：3.3.13“属于下列情形之一的股票，不实行价格涨跌幅限制：（一）首次公开发行上市的股票上市后的前5个交易日”为全市场条款；主板 2023-02-17 起点经上海市金融委等公开来源核实",
        ),
        RuleReference(
            area="t_plus_one",
            rule="投资者买入的证券，在交收前不得卖出（回转交易品种除外）",
            source_title="上海证券交易所交易规则（2026年修订）3.1.4",
            issuer="SSE/SZSE",
            document_number="上证发〔2026〕41号",
            url=_SSE_TRADING_RULES_2026,
            verified_online=True,
            note=_VERIFIED + "：SSE 3.1.4 原文；SZSE 3.1.4 原文逐条一致（2026-10-25）",
        ),
        RuleReference(
            area="lot_and_tick",
            rule="竞价买入申报为 100 股或其整数倍，卖出余额不足 100 股须一次性申报；A 股最小价格变动单位 0.01 元",
            source_title="上海证券交易所交易规则（2026年修订）3.3.8 / 3.3.11",
            issuer="SSE/SZSE",
            document_number="上证发〔2026〕41号",
            url=_SSE_TRADING_RULES_2026,
            verified_online=True,
            note=_VERIFIED + "：SSE 3.3.8 与 3.3.11 原文；SZSE 3.3.8 与 3.3.11 原文逐条一致（2026-10-25）",
        ),
        RuleReference(
            area="continuous_auction_sessions",
            rule="申报接受 9:15-9:25、9:30-11:30、13:00-15:00；连续竞价撮合 9:30-11:30、13:00-14:57，14:57-15:00 为收盘集合竞价",
            source_title="上海证券交易所交易规则（2026年修订）3.3.1 / 2.4.2",
            issuer="SSE/SZSE",
            document_number="上证发〔2026〕41号",
            url=_SSE_TRADING_RULES_2026,
            verified_online=True,
            note=_VERIFIED
            + "：SSE 3.3.1 与 2.4.2 原文；SZSE 2.3.2 原文逐条一致（9:30-11:30、13:00-14:57 连续竞价，14:57-15:00 收盘集合竞价）；本平台以申报接受窗口判定可交易，收盘集合竞价按连续撮合近似（建模简化）",
        ),
        RuleReference(
            area="after_hours_fixed_price",
            rule="盘后固定价格交易适用全部 A 股与 ETF：申报 9:30-11:30、13:00-15:30（当日有效），15:05-15:30 以收盘价按时间优先撮合；收盘价高于买入限价或低于卖出限价的申报无效；15:00 仍停牌不参与",
            source_title="上海证券交易所交易规则（2026年修订）3.7.1-3.7.11",
            issuer="SSE/SZSE",
            document_number="上证发〔2026〕41号（已取代科创板盘后固定价格交易指引〔2019〕21号的板块限制，暂缓实施条文仅涉大宗交易 3.6.x）",
            url=_SSE_TRADING_RULES_2026,
            verified_online=True,
            note=_VERIFIED
            + "：3.7.1 适用范围、3.7.2 时段与停牌、3.7.3 申报窗口与撤销、3.7.5 限价不等式、3.7.7 当日有效、3.7.8 收盘价逐笔撮合原文；扩至全部 A 股与沪深 ETF 另经证监会官方发布确认；深交所原文 3.6.1–3.6.5 已逐条核对（SZSE 2026 修订 PDF，2026-10-25），申报窗口深市自 9:15 起（已按交易所区分实现）",
        ),
        RuleReference(
            area="trading_calendar_holidays",
            rule="周末与法定节假日休市，按国务院办公厅年度通知与交易所休市安排执行",
            source_title="上交所 2026 年休市安排公告 / 国务院办公厅节假日安排通知",
            issuer="SSE/SZSE",
            document_number="国办发明电〔2025〕7号",
            url=_SSE_CLOSURE_PAGE,
            verified_online=True,
            note=_VERIFIED
            + "：2023–2026 四年均已逐日对照上交所休市公告（修正 2024-02-12/13/14、2025-10-08、2026-02-23 遗漏）；主板风险警示股 5%→10% 的 2026 变化不适用（ST 在 PRD 排除范围）",
        ),
    )
}

IMPLEMENTED_RULE_AREAS = tuple(RULE_REFERENCES)
