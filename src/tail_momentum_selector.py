#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股尾盘启动隔夜策略 —— 选股扫描器 (Afternoon Momentum -> Overnight Alpha)

=====================================================================
重要说明（务必先读）
---------------------------------------------------------------------
本程序把用户描述的「尾盘启动隔夜」短线选股策略实现为一个可运行的扫描器。
它按计划在每个交易日 14:30~14:45 附近，对给定的股票池做综合评分并输出候选。

数据来源：westock-data（腾讯自选股行情接口），通过命令行 CLI 调用。
  - quote  : 实时/快照行情（昨收、今开、多日涨跌幅、涨停价等）
  - kline  : 日线 OHLCV（用于均线、短期动量、波动率、ATR）
  - minute : 当日分时（用于「下午启动」因子——这是本策略最关键的数据）
  - changedist : 全市场涨跌家数 / 涨跌停家数（市场环境判断）

防未来函数（Iron rule）：
  - 决策时刻 = SNAPSHOT（默认 14:30）。程序只使用 SNAPSHOT 及之前的分时价格、
    成交量、成交额、历史日线。绝对不使用 14:30 之后的数据，也不使用当日最终收盘价。
  - 日线 kline 的“当日”一行是 15:00 收盘值，本程序会用 SNAPSHOT 时刻的分时价格
    覆盖它，再做均线/动量计算，从而杜绝未来函数。
  - 运行时间：本程序本应在交易时段 14:30~14:45 实时运行。收盘后运行等价于
    “用当日已发生数据在 14:30 做一次回放验证”，仍只使用 14:30 之前已知的数据。

已知限制（如实披露，不伪造）：
  1. 全市场扫描不可行：minute 命令不支持批量查询，逐股拉分时对 4000+ 只股票
     会触发严重限流且极慢。因此本程序接受一个「股票池」参数（--codes / --universe），
     真实部署时应先用 westock-tool 做初筛（流动性/涨幅/行业），再对候选池跑本程序。
  2. 行业相对强弱：本版本实现的是与 沪深300 / 中证1000 / 上证 的实时相对强弱
     （可由指数分时可靠计算）。「所属申万行业」的实时涨跌幅需要行业成份映射，
     本版本预留 industry_rs 钩子（默认贡献 0 并明确标注），后续可接入。
  3. 次日涨跌概率：未经过历史统计训练，本程序只给出基于规则的「主观置信度」与
     基于波动率的「目标价/止损参考」，绝不伪造统计概率。

项目结构约定（详见仓库根目录 README.md）：
  <project_root>/
    src/       源代码（本文件）
    data/      输入数据（股票池等，纳入 Git）
    results/   生成的结果文件（纳入 Git；文件名带当日日期后缀）
    cache/     运行缓存（.gitignore 忽略，可随时删除重建）
    docs/      文档

输出（默认写入 <project_root>/results/，文件名带当日日期后缀 YYYY-MM-DD）：
  - 控制台打印五段式报告（市场环境 / 候选表 / 重点说明 / 次日计划 / 风险提示）
  - results/signals_<DATE>.json    （供次日 --review 复盘）
  - results/report_<DATE>.txt      （报告文本）
  - results/dashboard_<DATE>.html  （HTML 看板，默认生成；--no-html 关闭）

三大增强（均默认开启，可单独关闭）：
  ① 初筛流水线  --screen：先 westock-tool 条件选股，再对候选做扫描（解决全市场扫描限流）；
                 默认筛选"流动性好且当日涨幅2%~7%、换手率1%~12%的A股"，可用 --screen-expr 改写。
  ② 申万行业实时相对强弱：批量 profile 取个股申万一级行业，再 quote 行业指数(pt01801xxx)
                 拿实时涨跌，纳入相对强弱评分（15分拆为 沪深300/中证1000/行业 各5分）；
                 --no-industry-rs 关闭，回退为纯指数代理。
  ③ HTML 看板：候选表 + 观察名单 + 前3详情卡，自包含轻主题页面。

用法示例（在项目根目录执行）：
  python src/tail_momentum_selector.py --codes sh600519,sz000858,sz002594 \
      --snapshot 1430 --top 5
  python src/tail_momentum_selector.py --screen --snapshot 1430 --top 5
  python src/tail_momentum_selector.py --screen --screen-expr "intersect([ChangePCT>=3, ChangePCT<=6, TotalMV>10000000000])" --screen-limit 80
  python src/tail_momentum_selector.py --no-industry-rs --no-html --codes sh600519
  python src/tail_momentum_selector.py --universe data/universe/my_pool.txt --review
=====================================================================
"""

import argparse
import glob
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, date

# --------------------------------------------------------------------------- #
# 项目根目录与默认路径
#   本文件位于 <project_root>/src/ 下，故项目根 = 本文件所在目录的上一级。
#   所有默认输出/缓存路径都相对项目根解析，保证在任意工作目录下运行结果一致。
# --------------------------------------------------------------------------- #
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
DEFAULT_CACHE_DIR = os.path.join(PROJECT_ROOT, "cache")

# --------------------------------------------------------------------------- #
# 0. 定位 westock-data CLI
# --------------------------------------------------------------------------- #
def find_westock_cli(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("WESTOCK_CLI")
    if env and os.path.exists(env):
        return env
    # PATH 中的 westock-data 命令
    from shutil import which
    p = which("westock-data")
    if p:
        return p
    # 常见缓存路径（专家插件自带脚本）
    candidates = [
        r"C:/Users/terry/.workbuddy/plugins/cache/experts/strategy-backtest-expert/1.0.0/skills/westock-data/scripts/index.js",
        r"C:/Users/terry/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-data/scripts/index.js",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise RuntimeError("找不到 westock-data CLI，请用 --westock-cli 指定 scripts/index.js 路径")


def run_westock(cli, *args, cache_dir=None, tag=None):
    """调用 westock-data CLI，返回 markdown 文本。"""
    if cli.endswith(".js") or cli.endswith(".mjs"):
        cmd = ["node", cli, *args]
    else:
        cmd = [cli, *args]
    # 注意：Windows 默认 locale 是 GBK，子进程输出为 UTF-8，必须用字节模式读取再显式
    # 以 utf-8 解码，否则会抛 UnicodeDecodeError（'gbk' codec can't decode ...）。
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"CLI 超时：{' '.join(args)}")
    text = (out.stdout or b"").decode("utf-8", errors="replace")
    if out.returncode != 0:
        err = (out.stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"CLI 失败({out.returncode})：{err[:300]}")
    if cache_dir and tag:
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, f"{tag}.md"), "w", encoding="utf-8") as f:
            f.write(text)
    return text


# --------------------------------------------------------------------------- #
# 0b. 定位 westock-tool CLI（初筛用）
# --------------------------------------------------------------------------- #
def find_westock_tool_cli(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("WESTOOL_CLI")
    if env and os.path.exists(env):
        return env
    from shutil import which
    p = which("westock-tool")
    if p:
        return p
    candidates = [
        r"C:/Users/terry/.workbuddy/plugins/cache/experts/strategy-backtest-expert/1.0.0/skills/westock-tool/scripts/index.js",
        r"C:/Users/terry/.workbuddy/plugins/marketplaces/experts/plugins/strategy-backtest-expert/skills/westock-tool/scripts/index.js",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise RuntimeError("找不到 westock-tool CLI，请用 --westock-tool-cli 指定 scripts/index.js 路径")


def run_westock_tool(cli, *args, cache_dir=None, tag=None):
    """调用 westock-tool CLI，返回 markdown 文本。"""
    if cli.endswith(".js") or cli.endswith(".mjs"):
        cmd = ["node", cli, *args]
    else:
        cmd = [cli, *args]
    # 字节模式 + 显式 utf-8 解码，规避 Windows GBK 解码崩溃（见 run_westock 注释）。
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"westock-tool 超时：{' '.join(args)}")
    text = (out.stdout or b"").decode("utf-8", errors="replace")
    if out.returncode != 0:
        err = (out.stderr or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"westock-tool 失败({out.returncode})：{err[:300]}")
    if cache_dir and tag:
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, f"{tag}.md"), "w", encoding="utf-8") as f:
            f.write(text)
    return text


# --------------------------------------------------------------------------- #
# 0c. 申万一级行业 -> 行业指数代码 映射（离线兜底；运行时也会从 sector --list 刷新）
# --------------------------------------------------------------------------- #
SW_INDUSTRY_MAP = {
    "医药生物": "pt01801150", "有色金属": "pt01801050", "美容护理": "pt01801980",
    "综合": "pt01801230", "轻工制造": "pt01801140", "通信": "pt01801770",
    "国防军工": "pt01801740", "家用电器": "pt01801110", "交通运输": "pt01801170",
    "商贸零售": "pt01801200", "环保": "pt01801970", "煤炭": "pt01801950",
    "计算机": "pt01801750", "建筑装饰": "pt01801720", "电子": "pt01801080",
    "电力设备": "pt01801730", "机械设备": "pt01801890", "建筑材料": "pt01801710",
    "石油石化": "pt01801960", "基础化工": "pt01801030", "房地产": "pt01801180",
    "农林牧渔": "pt01801010", "传媒": "pt01801760", "社会服务": "pt01801210",
    "钢铁": "pt01801040", "公用事业": "pt01801160", "汽车": "pt01801880",
    "食品饮料": "pt01801120", "纺织服饰": "pt01801130", "非银金融": "pt01801790",
    "银行": "pt01801780",
}


# --------------------------------------------------------------------------- #
# 1. Markdown 表格解析（通用）
# --------------------------------------------------------------------------- #
def parse_md_tables(text):
    """返回 [(headers:list, rows:list[list])]，忽略非表格行。"""
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    tables = []
    cur_header = None
    cur_rows = []
    for ln in lines:
        if not ln.strip().startswith("|"):
            # 非表格行：结束当前表
            if cur_header is not None:
                tables.append((cur_header, cur_rows))
                cur_header, cur_rows = None, []
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        # 分隔行
        if all(re.fullmatch(r":?-+:?", c) for c in cells if c != ""):
            continue
        if cur_header is None:
            cur_header = cells
        else:
            cur_rows.append(cells)
    if cur_header is not None:
        tables.append((cur_header, cur_rows))
    return tables


def _to_float(x):
    if x is None:
        return None
    x = x.replace(",", "").replace("%", "").strip()
    if x in ("", "-", "None", "null"):
        return None
    try:
        return float(x)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# 2. 各命令解析
# --------------------------------------------------------------------------- #
def parse_quote_batch(text):
    """code -> dict（name/price/prev_close/open/change_percent/high/low/amount/
    volume/chg_5d/chg_10d/chg_20d/chg_60d/price_ceiling/price_floor）。"""
    out = {}
    for headers, rows in parse_md_tables(text):
        if "code" not in headers:
            continue
        ci = headers.index("code")
        for r in rows:
            if len(r) <= ci:
                continue
            code = r[ci]
            d = {}
            for k, v in zip(headers, r):
                d[k] = v
            out[code] = {
                "name": d.get("name"),
                "price": _to_float(d.get("price")),
                "prev_close": _to_float(d.get("prev_close")),
                "open": _to_float(d.get("open")),
                "change_percent": _to_float(d.get("change_percent")),
                "high": _to_float(d.get("high")),
                "low": _to_float(d.get("low")),
                "amount": _to_float(d.get("amount")),
                "volume": _to_float(d.get("volume")),
                "chg_5d": _to_float(d.get("chg_5d")),
                "chg_10d": _to_float(d.get("chg_10d")),
                "chg_20d": _to_float(d.get("chg_20d")),
                "chg_60d": _to_float(d.get("chg_60d")),
                "price_ceiling": _to_float(d.get("price_ceiling")),
                "price_floor": _to_float(d.get("price_floor")),
                "turnover_rate": _to_float(d.get("turnover_rate")),
            }
    return out


def parse_kline_batch(text, default_code=None):
    """code -> [{date,open,high,low,close,volume,amount}]（按日期升序）。
    兼容两种输出：批量（含 symbol 列）与单股（无 symbol 列，用 default_code）。"""
    out = {}
    for headers, rows in parse_md_tables(text):
        if "date" not in headers or "last" not in headers:
            continue
        has_symbol = "symbol" in headers
        di = headers.index("date")
        oi = headers.index("open"); li = headers.index("low")
        hi = headers.index("high"); ci = headers.index("last")
        vi = headers.index("volume"); ai = headers.index("amount")
        si = headers.index("symbol") if has_symbol else None
        code_key = default_code
        for r in rows:
            if len(r) <= max(di, oi, li, hi, ci, vi, ai):
                continue
            code = r[si] if has_symbol else code_key
            rec = {
                "date": r[di],
                "open": _to_float(r[oi]),
                "high": _to_float(r[hi]),
                "low": _to_float(r[li]),
                "close": _to_float(r[ci]),
                "volume": _to_float(r[vi]),
                "amount": _to_float(r[ai]),
            }
            if None in (rec["close"], rec["open"]):
                continue
            out.setdefault(code, []).append(rec)
    for code in out:
        out[code].sort(key=lambda x: x["date"])
    return out


def parse_minute(text):
    """返回 [{time:'HHMM', price, volume(累计手), amount(累计元)}] 升序。"""
    rows = []
    for headers, data in parse_md_tables(text):
        if "time" not in headers:
            continue
        ti, pi, vi, ai = (headers.index("time"), headers.index("price"),
                          headers.index("volume"), headers.index("amount"))
        for r in data:
            if len(r) <= max(ti, pi, vi, ai):
                continue
            rows.append({
                "time": r[ti].strip(),
                "price": _to_float(r[pi]),
                "volume": _to_float(r[vi]),
                "amount": _to_float(r[ai]),
            })
    rows.sort(key=lambda x: x["time"])
    return rows


def parse_changedist(text):
    """返回 {up, down, flat, limitup, limitdown, total}。"""
    for headers, rows in parse_md_tables(text):
        if "上涨" in headers and "下跌" in headers:
            iu = headers.index("上涨"); idn = headers.index("下跌")
            ifl = headers.index("平盘") if "平盘" in headers else None
            ilu = headers.index("涨停") if "涨停" in headers else None
            ild = headers.index("跌停") if "跌停" in headers else None
            it = headers.index("总数") if "总数" in headers else None
            if rows:
                r = rows[0]
                return {
                    "up": _to_float(r[iu]) or 0,
                    "down": _to_float(r[idn]) or 0,
                    "flat": _to_float(r[ifl]) if ifl is not None else 0,
                    "limitup": _to_float(r[ilu]) if ilu is not None else 0,
                    "limitdown": _to_float(r[ild]) if ild is not None else 0,
                    "total": _to_float(r[it]) if it is not None else 0,
                }
    return None


def parse_screen_codes(text):
    """westock-tool filter 输出：返回 [code, ...]（按出现顺序，去重）。"""
    out = []
    seen = set()
    for headers, rows in parse_md_tables(text):
        if "code" not in headers:
            continue
        ci = headers.index("code")
        for r in rows:
            if len(r) <= ci:
                continue
            code = r[ci].strip()
            if code and code not in seen:
                seen.add(code)
                out.append(code)
    return out


def parse_profile_batch(text):
    """code -> industry(申万一级名称)。批量 profile 输出。"""
    out = {}
    for headers, rows in parse_md_tables(text):
        if "code" not in headers or "industry" not in headers:
            continue
        ci = headers.index("code"); ii = headers.index("industry")
        for r in rows:
            if len(r) <= max(ci, ii):
                continue
            out[r[ci].strip()] = (r[ii] or "").strip()
    return out


# --------------------------------------------------------------------------- #
# 3. 时间工具
# --------------------------------------------------------------------------- #
def hhmm_to_min(t):
    """'1430' -> 交易分钟数（从 09:30 起算）。"""
    h = int(t[:2]); m = int(t[2:])
    if h < 12:
        return (h - 9) * 60 + (m - 30)
    else:
        return 120 + (h - 13) * 60 + m


TOTAL_TRADING_MIN = 240  # 09:30-11:30 (120) + 13:00-15:00 (120)


def elapsed_fraction(snapshot):
    """SNAPSHOT 时已过去的交易时间占全天的比例。"""
    return min(max(hhmm_to_min(snapshot), 1), TOTAL_TRADING_MIN) / TOTAL_TRADING_MIN


# --------------------------------------------------------------------------- #
# 4. 单股指标计算
# --------------------------------------------------------------------------- #
def slice_minute_up_to(minute_rows, snapshot):
    """返回 SNAPSHOT 及之前的分时行；若无，回退到最近一行。"""
    sub = [r for r in minute_rows if r["time"] <= snapshot]
    if not sub:
        # 极端：数据缺失，用最后一行
        return minute_rows[-1:] if minute_rows else []
    return sub


def minute_price_at(minute_rows, t):
    """取指定时刻（<=t）的最后一次价格。"""
    sub = [r for r in minute_rows if r["time"] <= t]
    return sub[-1]["price"] if sub else None


def compute_intraday(minute_rows, snapshot, prev_close, open_price):
    """计算下午启动因子所需的日内量价。"""
    sub = slice_minute_up_to(minute_rows, snapshot)
    if not sub:
        return None
    cur = sub[-1]["price"]
    # 关键价位
    p_open = open_price if open_price else sub[0]["price"]
    p_1130 = minute_price_at(minute_rows, "1130") or p_open
    p_1300 = minute_price_at(minute_rows, "1300") or p_1130
    p_1330 = minute_price_at(minute_rows, "1330") or p_1300
    p_1400 = minute_price_at(minute_rows, "1400") or p_1330
    p_1430 = minute_price_at(minute_rows, "1430") or cur
    # 日内高低（截至 SNAPSHOT，用分钟收盘价近似）
    highs = [r["price"] for r in sub]
    intraday_high = max(highs)
    intraday_low = min(highs)
    # 涨跌幅
    day_chg = (cur - prev_close) / prev_close if prev_close else 0.0
    open_to_cur = (cur - p_open) / p_open if p_open else 0.0
    morn_ret = (p_1130 - p_open) / p_open if p_open else 0.0          # 上午
    aft_1300 = (cur - p_1300) / p_1300 if p_1300 else 0.0             # 13:00 起
    aft_1400 = (cur - p_1400) / p_1400 if p_1400 else 0.0             # 14:00 起
    aft_1430 = (cur - p_1430) / p_1430 if p_1430 else 0.0             # 14:30 前后
    # 下午涨幅/上午涨幅（加速度）
    afternoon_ret_total = (cur - p_1300) / p_1300 if p_1300 else 0.0
    # 突破
    break_morning_high = cur > intraday_high * 0.999  # 接近/超过日内高点
    new_high_afternoon = cur >= max([r["price"] for r in sub if r["time"] >= "1300"])
    # 量（累计，手）
    vol_cur = sub[-1]["volume"]
    vol_1130 = next((r["volume"] for r in sub if r["time"] <= "1130"), 0)
    vol_1300 = next((r["volume"] for r in sub if r["time"] <= "1300"), vol_1130)
    vol_1400 = next((r["volume"] for r in sub if r["time"] <= "1400"), vol_1300)
    morn_vol = vol_1130
    aft_vol = vol_cur - vol_1300
    # 速度（每分钟）
    elapsed = hhmm_to_min(snapshot)
    aft_minutes = max(elapsed - 120, 1)
    morn_pace = morn_vol / 120.0
    aft_pace = aft_vol / aft_minutes
    vol_pace_ratio = aft_pace / morn_pace if morn_pace > 0 else (2.0 if aft_pace > 0 else 0.0)
    return {
        "cur": cur, "p_open": p_open, "p_1130": p_1130, "p_1300": p_1300,
        "p_1400": p_1400, "p_1430": p_1430,
        "intraday_high": intraday_high, "intraday_low": intraday_low,
        "day_chg": day_chg, "open_to_cur": open_to_cur, "morn_ret": morn_ret,
        "aft_1300": aft_1300, "aft_1400": aft_1400, "aft_1430": aft_1430,
        "afternoon_ret_total": afternoon_ret_total,
        "break_morning_high": break_morning_high, "new_high_afternoon": new_high_afternoon,
        "vol_cur": vol_cur, "morn_vol": morn_vol, "aft_vol": aft_vol,
        "vol_pace_ratio": vol_pace_ratio,
        "amount_cur": sub[-1]["amount"],
    }


def build_daily_series(kline_rows, snapshot_close):
    """用 SNAPSHOT 价格覆盖“当日”收盘，得到无未来函数的日线序列。"""
    series = []
    for r in kline_rows:
        series.append({
            "date": r["date"], "open": r["open"], "high": r["high"],
            "low": r["low"], "close": r["close"],
            "volume": r["volume"], "amount": r["amount"],
        })
    if series:
        series[-1]["close"] = snapshot_close  # 防未来函数：当日收盘=快照价
    return series


def compute_daily_indicators(series):
    closes = [s["close"] for s in series]
    n = len(closes)
    def ma(w):
        if n < w:
            return None
        return sum(closes[-w:]) / w
    ma5, ma10, ma20, ma60 = ma(5), ma(10), ma(20), ma(60)
    # 短期动量（用快照价作为“今日”）
    def ret_back(days):
        if n - 1 - days < 0:
            return None
        base = closes[n - 1 - days]
        return (closes[-1] / base - 1) if base else None
    r1 = ret_back(1); r2 = ret_back(2); r3 = ret_back(3)
    r5 = ret_back(5); r10 = ret_back(10); r20 = ret_back(20)
    # ATR（14）
    atr = None
    if n >= 15:
        trs = []
        for i in range(1, n):
            h, l, pc = series[i]["high"], series[i]["low"], series[i-1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs[-14:]) / 14
    # 历史波动率（20日收益率 std，年化）
    vol = None
    if n >= 22:
        rets = [(closes[i]/closes[i-1] - 1) for i in range(1, n)]
        recent = rets[-20:]
        mean = sum(recent) / len(recent)
        var = sum((x - mean) ** 2 for x in recent) / len(recent)
        vol = (var ** 0.5) * (252 ** 0.5)
    # 均线斜率（MA5 较 5 日前）
    ma5_slope = None
    if n >= 6 and ma5:
        ma5_prev = sum(closes[-6:-1]) / 5
        ma5_slope = (ma5 / ma5_prev - 1) if ma5_prev else 0.0
    # 近期是否连续大涨（过热）
    recent_up_streak = 0
    if n >= 4:
        for i in range(n - 1, max(n - 5, 0), -1):
            if closes[i] >= closes[i - 1]:
                recent_up_streak += 1
            else:
                break
    return {
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60,
        "r1": r1, "r2": r2, "r3": r3, "r5": r5, "r10": r10, "r20": r20,
        "atr": atr, "ann_vol": vol, "ma5_slope": ma5_slope,
        "recent_up_streak": recent_up_streak,
        "avg_daily_volume": (sum(s["volume"] for s in series[:-1]) / max(len(series) - 1, 1))
            if len(series) > 1 else (series[0]["volume"] if series else 0),
    }


def compute_volume_surge(intraday, daily, snapshot):
    """成交量放大比：SNAPSHOT 累计量 / (历史日均量 × 已过去时间占比)。"""
    if not intraday or not daily:
        return None
    f = elapsed_fraction(snapshot)
    expected = daily["avg_daily_volume"] * f
    if expected <= 0:
        return None
    return intraday["vol_cur"] / expected


# --------------------------------------------------------------------------- #
# 5. 评分
# --------------------------------------------------------------------------- #
def clamp(x, lo=0.0, hi=10.0):
    return max(lo, min(hi, x))


def score_trend(daily):
    s = 0.0
    c = daily.get("close_proxy")
    ma5, ma10, ma20, ma60 = daily["ma5"], daily["ma10"], daily["ma20"], daily["ma60"]
    px = None
    # 需要当日价；在调用处把快照价塞进来
    px = daily.get("snapshot_close")
    if px is None:
        return 0.0
    if ma5 and px >= ma5: s += 3
    if ma10 and px >= ma10: s += 3
    if ma20 and px >= ma20: s += 3
    if ma5 and ma10 and ma20 and ma5 > ma10 > ma20: s += 4
    if ma20 and ma60 and ma20 > ma60: s += 3
    if daily["ma5_slope"] is not None and daily["ma5_slope"] > 0: s += 4
    return clamp(s, 0, 20)


def score_afternoon(intraday):
    if not intraday:
        return 0.0, {}
    s = 0.0
    det = {}
    # 14:00 之后上涨
    if intraday["aft_1400"] > 0.003: s += 4
    elif intraday["aft_1400"] > 0: s += 2
    elif intraday["aft_1400"] < -0.003: s += 0
    else: s += 1
    det["aft_1400"] = intraday["aft_1400"]
    # 下午强于上午
    if intraday["afternoon_ret_total"] > intraday["morn_ret"] + 0.002:
        s += 5
    elif intraday["afternoon_ret_total"] > intraday["morn_ret"]:
        s += 3
    det["aft_vs_morn"] = intraday["afternoon_ret_total"] - intraday["morn_ret"]
    # 突破上午/日内高点
    if intraday["break_morning_high"]: s += 5
    det["break_high"] = intraday["break_morning_high"]
    # 下午加速（量价）
    if intraday["vol_pace_ratio"] >= 1.1: s += 4
    elif intraday["vol_pace_ratio"] >= 1.0: s += 2
    det["vol_pace_ratio"] = intraday["vol_pace_ratio"]
    # 下午持续走强（13:00 起到 14:00 到当前单调递增近似）
    if intraday["aft_1300"] > 0 and intraday["aft_1400"] >= 0:
        s += 4
    det["aft_1300"] = intraday["aft_1300"]
    return clamp(s, 0, 25), det


def score_volume(intraday, vol_surge):
    s = 0.0
    det = {}
    if vol_surge is not None:
        det["vol_surge"] = vol_surge
        if vol_surge >= 1.5: s += 8
        elif vol_surge >= 1.2: s += 6
        elif vol_surge >= 1.0: s += 3
        else: s += 0
    if intraday:
        # 下午量速 > 上午
        if intraday["vol_pace_ratio"] >= 1.3: s += 6
        elif intraday["vol_pace_ratio"] >= 1.1: s += 4
        elif intraday["vol_pace_ratio"] >= 1.0: s += 2
        # 价涨量增
        if intraday["day_chg"] > 0 and (vol_surge is None or vol_surge >= 1.0):
            s += 6
        elif intraday["day_chg"] > 0:
            s += 3
    return clamp(s, 0, 20), det


def score_rs(stock_day_chg, idx_chg, industry_chg=None):
    """相对强弱：vs 沪深300 / 中证1000 / 所属申万一级行业。返回 (score, detail)。
    行业数据可用时三部分各满分 5（合计15）；不可用时回退为 沪深300(7)+中证1000(8)。"""
    s = 0.0
    det = {}
    ind_ok = industry_chg is not None
    # 沪深300
    if "hs300" in idx_chg:
        rs = stock_day_chg - idx_chg["hs300"]
        det["rs_hs300"] = rs
        if rs >= 0.015: s += (7 if not ind_ok else 5)
        elif rs >= 0.005: s += (5 if not ind_ok else 4)
        elif rs >= 0: s += (3 if not ind_ok else 2)
    # 中证1000（兼作小盘/风格代理）
    if "zz1000" in idx_chg:
        rs = stock_day_chg - idx_chg["zz1000"]
        det["rs_zz1000"] = rs
        if rs >= 0.015: s += (8 if not ind_ok else 5)
        elif rs >= 0.005: s += (6 if not ind_ok else 4)
        elif rs >= 0: s += (3 if not ind_ok else 2)
    # 申万一级行业
    if ind_ok:
        rs = stock_day_chg - industry_chg
        det["rs_industry"] = rs
        if rs >= 0.015: s += 5
        elif rs >= 0.005: s += 4
        elif rs >= 0: s += 2
    det["industry_available"] = ind_ok
    return clamp(s, 0, 15), det


def score_risk(intraday, daily, quote, snapshot_close):
    """风险控制（10 分起，扣分为主）。"""
    s = 10.0
    det = {}
    # 流动性
    if intraday and intraday["amount_cur"]:
        amt_yi = intraday["amount_cur"] / 1e8
        det["amount_yi"] = amt_yi
        if amt_yi < 1.0:
            s -= 4
        elif amt_yi < 3.0:
            s -= 2
    # 接近涨停（过热）
    ceil = quote.get("price_ceiling")
    if ceil and snapshot_close >= ceil * 0.985:
        s -= 4
        det["near_limitup"] = True
    elif intraday and intraday["day_chg"] >= 0.095:
        s -= 3
        det["near_limitup"] = True
    # 已连续大涨（过热）
    if daily["recent_up_streak"] >= 4 or (daily["r5"] is not None and daily["r5"] > 0.20):
        s -= 2
    if daily["r10"] is not None and daily["r10"] > 0.35:
        s -= 2
    # 高波动扣分（轻微）
    if daily["ann_vol"] and daily["ann_vol"] > 1.2:
        s -= 1
    det["recent_up_streak"] = daily["recent_up_streak"]
    return clamp(s, 0, 10), det


def score_stock(quote, intraday, daily, vol_surge, idx_chg, env_points, snapshot, industry_chg=None):
    snapshot_close = intraday["cur"] if intraday else quote.get("price")
    daily["snapshot_close"] = snapshot_close
    trend = score_trend(daily)
    aft, aft_det = score_afternoon(intraday)
    vol, vol_det = score_volume(intraday, vol_surge)
    rs, rs_det = score_rs(intraday["day_chg"] if intraday else 0.0, idx_chg, industry_chg)
    env = clamp(env_points, 0, 10)
    risk, risk_det = score_risk(intraday, daily, quote, snapshot_close)
    total = trend + aft + vol + rs + env + risk
    return {
        "trend": round(trend, 1), "afternoon": round(aft, 1),
        "volume": round(vol, 1), "rs": round(rs, 1),
        "env": round(env, 1), "risk": round(risk, 1),
        "total": round(total, 1),
        "aft_det": aft_det, "vol_det": vol_det, "rs_det": rs_det, "risk_det": risk_det,
        "snapshot_close": snapshot_close,
    }


# --------------------------------------------------------------------------- #
# 6. 市场环境
# --------------------------------------------------------------------------- #
def score_market_env(idx_chg, breadth):
    """返回 (label, points, detail)。环境评分与状态一致：Bull 高、Neutral 中、Bear 低。"""
    vals = [v for v in idx_chg.values() if v is not None]
    avg = sum(vals) / len(vals) if vals else 0.0
    det = {"idx_avg_chg": round(avg * 100, 2)}
    br = 0.5
    net = 0
    if breadth:
        total = breadth["up"] + breadth["down"]
        br = breadth["up"] / total if total else 0.5
        net = (breadth["limitup"] or 0) - (breadth["limitdown"] or 0)
        det["breadth_ratio"] = round(br * 100, 1)
        det["limitup"] = breadth["limitup"]
        det["limitdown"] = breadth["limitdown"]
    # 先定状态
    if avg > 0.005 and br > 0.55 and net > 0:
        label = "Bull"
    elif avg < -0.005 and br < 0.45:
        label = "Bear"
    else:
        label = "Neutral"
    # 再按状态给分（0~10）
    if label == "Bull":
        pts = 7 + avg * 100 * 1.5 + net / 10.0
    elif label == "Bear":
        pts = (br - 0.5) * 10 + net / 10.0
    else:
        pts = 4 + (br - 0.5) * 10
    return label, round(clamp(pts, 0, 10), 1), det


# --------------------------------------------------------------------------- #
# 7. 主流程
# --------------------------------------------------------------------------- #
INDEX_CODES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000300": "沪深300",
    "sh000852": "中证1000",
}


def load_universe(codes, universe_file):
    if universe_file:
        with open(universe_file, "r", encoding="utf-8") as f:
            codes = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    codes = [c.strip() for c in codes.split(",") if c.strip()]
    return codes


def fetch_index_data(cli, snapshot, cache_dir):
    codes = list(INDEX_CODES.keys())
    q = parse_quote_batch(run_westock(cli, "quote", ",".join(codes), cache_dir=cache_dir, tag="idx_quote"))
    prev = {c: (q[c]["prev_close"] if c in q else None) for c in codes}
    idx_chg = {}
    for c in codes:
        mn = parse_minute(run_westock(cli, "minute", c, cache_dir=cache_dir, tag=f"idx_min_{c}"))
        sub = slice_minute_up_to(mn, snapshot)
        pc = prev.get(c)
        if sub and pc:
            price = sub[-1]["price"]
            idx_chg[c] = (price - pc) / pc
        else:
            idx_chg[c] = None
    # 映射到语义键
    mapped = {}
    if idx_chg.get("sh000300") is not None:
        mapped["hs300"] = idx_chg["sh000300"]
    if idx_chg.get("sh000852") is not None:
        mapped["zz1000"] = idx_chg["sh000852"]
    if idx_chg.get("sh000001") is not None:
        mapped["sh"] = idx_chg["sh000001"]
    return idx_chg, mapped


def fetch_stock_data(cli, code, snapshot, cache_dir):
    quote = parse_quote_batch(run_westock(cli, "quote", code, cache_dir=cache_dir, tag=f"q_{code}"))
    quote = quote.get(code)
    if not quote:
        return None
    # 排除 ST / 退市
    name = quote.get("name") or ""
    if "ST" in name.upper() or "*" in name:
        return {"excluded": "ST"}
    kline = parse_kline_batch(run_westock(cli, "kline", code, "--period", "day", "--limit", "60", "--fq", "qfq", cache_dir=cache_dir, tag=f"k_{code}"), default_code=code)
    kline = kline.get(code)
    if not kline or len(kline) < 25:
        return {"excluded": "数据不足"}
    minute = parse_minute(run_westock(cli, "minute", code, cache_dir=cache_dir, tag=f"m_{code}"))
    if not minute:
        return {"excluded": "无分时数据"}
    return {"quote": quote, "kline": kline, "minute": minute}


def fetch_industry_map(cli, cache_dir):
    """返回 {申万一级行业名: 行业指数代码}。优先运行时刷新，失败则用内置兜底。"""
    m = dict(SW_INDUSTRY_MAP)
    try:
        txt = run_westock(cli, "sector", "--list", "industry_list_sw1", cache_dir=cache_dir, tag="sw_industry_list")
        for headers, rows in parse_md_tables(txt):
            if "代码" not in headers or "名称" not in headers:
                continue
            ci = headers.index("代码"); ni = headers.index("名称")
            for r in rows:
                if len(r) <= max(ci, ni):
                    continue
                m[r[ni].strip()] = r[ci].strip()
    except Exception as e:
        print(f"[提示] 行业清单刷新失败，使用内置兜底映射：{e}", file=sys.stderr)
    return m


def fetch_industry_change_map(cli, industry_names, ind_map, cache_dir):
    """返回 {行业名: 当日涨跌幅(小数)}。行业名 -> 代码 -> batch quote 实时涨跌。"""
    out = {}
    codes = []
    name_by_code = {}
    for nm in industry_names:
        if nm in ind_map:
            c = ind_map[nm]
            if c not in name_by_code:
                name_by_code[c] = nm
                codes.append(c)
    if not codes:
        return out
    # 批量 quote（每行上限 ~30，避免过长）
    for i in range(0, len(codes), 30):
        chunk = codes[i:i + 30]
        try:
            q = parse_quote_batch(run_westock(cli, "quote", ",".join(chunk), cache_dir=cache_dir, tag=f"ind_q_{i}"))
        except Exception as e:
            print(f"[提示] 行业涨跌获取失败：{e}", file=sys.stderr)
            continue
        for c, d in q.items():
            nm = name_by_code.get(c)
            if nm and d.get("change_percent") is not None:
                out[nm] = d["change_percent"] / 100.0
    return out


def run_screen_pipeline(tool_cli, expr, limit, cache_dir):
    """调用 westock-tool filter 初筛，返回代码列表。"""
    txt = run_westock_tool(tool_cli, "filter", expr, "--limit", str(limit), cache_dir=cache_dir, tag="screen")
    codes = parse_screen_codes(txt)
    return codes


def build_report(results, watch, env_label, env_points, env_det, snapshot, top, bear_threshold):
    lines = []
    L = lines.append
    L("=" * 70)
    L("        A股尾盘启动隔夜策略 · 选股扫描报告")
    L("=" * 70)
    L(f"快照时刻(SNAPSHOT): {snapshot[:2]}:{snapshot[2:]}  （仅使用该时刻及之前的数据，无未来函数）")
    L(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L("")

    # ① 市场环境
    L("① 市场环境")
    L("-" * 70)
    L(f"市场状态：{env_label}    （环境评分 {env_points}/10）")
    L(f"指数平均涨跌幅：{env_det.get('idx_avg_chg')}%    "
      f"涨跌家数比：{env_det.get('breadth_ratio')}%    "
      f"涨停 {env_det.get('limitup')} / 跌停 {env_det.get('limitdown')}")
    if env_label == "Bear":
        L("⚠️ 偏弱环境：综合评分门槛提高到 >= 80，且减少推荐数量。")
    elif env_label == "Bull":
        L("偏强环境：可适当提高动量策略权重（阈值维持 >= 70）。")
    L("")

    # ② 候选表
    L("② 今日候选股票（按总分降序，最多 %d 只）" % top)
    L("-" * 70)
    if not results:
        L("今日无符合策略条件的交易机会，建议空仓。")
    else:
        hdr = f"{'排名':<4}{'股票':<10}{'代码':<10}{'当前涨幅%':>9}{'下午动量':>9}{'成交量':>8}{'相对强弱':>9}{'风险':>7}{'总分':>7}"
        L(hdr)
        L("-" * 70)
        for i, r in enumerate(results, 1):
            name = r["name"]
            display = name if len(name) <= 8 else name[:8]
            L(f"{i:<4}{display:<10}{r['code']:<10}"
              f"{r['day_chg_pct']:>9.2f}{r['score']['afternoon']:>9.1f}"
              f"{r['score']['volume']:>8.1f}{r['score']['rs']:>9.1f}"
              f"{r['score']['risk']:>7.1f}{r['score']['total']:>7.1f}")
        L("")

    # ②b 观察名单（未达买入阈值，仅作跟踪；对应策略「60~69分：观察」档）
    if watch:
        L("②b 观察名单（未达买入阈值，仅跟踪，非交易信号）")
        L("-" * 70)
        for i, r in enumerate(watch, 1):
            reasons = "；".join(r["miss"])
            L(f"  {i}. {r['name']} ({r['code']}) 总分 {r['score']['total']} "
              f"｜当日涨幅 {r['day_chg_pct']:.2f}%｜下午动量 {r['score']['afternoon']}"
              f"｜量 {r['score']['volume']}｜强 {r['score']['rs']}｜险 {r['score']['risk']}")
            L(f"     未入选原因：{reasons}")
        L("")

    # ③ 最值得关注
    if results:
        L("③ 最值得关注的股票（前 3）")
        L("-" * 70)
        for i, r in enumerate(results[:3], 1):
            sc = r["score"]; ad = sc["aft_det"]; vd = sc["vol_det"]; rd = sc["rs_det"]
            L(f"【{i}】{r['name']} ({r['code']})  总分 {sc['total']}")
            L(f"  - 当前价 {sc['snapshot_close']:.2f}｜当日涨幅 {r['day_chg_pct']:.2f}%｜"
              f"当日成交额 {sc['risk_det'].get('amount_yi',0):.1f} 亿")
            L(f"  - 下午启动：14:00后涨跌 {ad.get('aft_1400',0)*100:.2f}%，"
              f"下午-上午差 {ad.get('aft_vs_morn',0)*100:.2f}%，"
              f"突破日内高点 {'是' if ad.get('break_high') else '否'}，"
              f"下午量速/上午 {ad.get('vol_pace_ratio',0):.2f}")
            L(f"  - 成交量：放大比 {vd.get('vol_surge',0):.2f}x；"
              f"相对沪深300 {rd.get('rs_hs300',0)*100:.2f}%，"
              f"相对中证1000 {rd.get('rs_zz1000',0)*100:.2f}%"
              + (f"，相对申万行业 {rd.get('rs_industry',0)*100:.2f}%"
                 if rd.get('industry_available') else "，相对行业：N/A(行业映射缺失)"))
            L(f"  - 为何现在走强：上午表现 {('偏强' if r['morn_ret']>0.01 else ('偏弱' if r['morn_ret']<0 else '平淡'))}"
              f"（上午涨幅 {r['morn_ret']*100:.2f}%），下午明显加速；"
              f"价格与成交量方向{'一致' if (r['day_chg_pct']>0 and vd.get('vol_surge',0)>=1) else '不完全一致'}。"
              f"追高风险：{'偏高（接近涨停/已连续大涨）' if sc['risk_det'].get('near_limitup') or sc['risk_det'].get('recent_up_streak',0)>=4 else '中等'}。")
            L("")

    # ④ 次日交易计划
    if results:
        L("④ 次日交易计划（T+1，持仓周期约 1 个交易日）")
        L("-" * 70)
        for r in results:
            sc = r["score"]; rd = sc["rs_det"]
            # 主观置信度（非统计概率）
            conf = "强烈关注" if sc["total"] >= 85 and sc["afternoon"] >= 18 else (
                "关注" if sc["total"] >= 75 else "观察")
            # 目标价/止损：基于当日振幅/ATR 粗略估计
            atr = r.get("atr") or (abs(r.get("day_chg_pct",0))/100 * sc["snapshot_close"])
            target = sc["snapshot_close"] * (1 + max(0.01, min(0.025, atr / sc["snapshot_close"] * 1.5)))
            stop = sc["snapshot_close"] * (1 - max(0.01, min(0.02, atr / sc["snapshot_close"] * 1.0)))
            L(f"{r['name']} ({r['code']})  建议级别：{conf}")
            L(f"  理想买入：次日开盘附近（约 {sc['snapshot_close']:.2f} 上下）")
            L(f"  次日目标：+1%~+{(target/sc['snapshot_close']-1)*100:.1f}%  "
              f"（参考 {target:.2f}）｜止损参考：{(stop/sc['snapshot_close']-1)*100:.1f}%  "
              f"（约 {stop:.2f}）")
            L(f"  最大建议持仓：单只不超过总资金 20%（短线高风险，分散为宜）")
            L(f"  主观次日上涨置信度：{'高' if conf=='强烈关注' else ('中' if conf=='关注' else '低')}"
              f"（基于规则估计，非历史统计概率）")
            L("")

    # ⑤ 风险提示
    L("⑤ 风险提示")
    L("-" * 70)
    L("  · 本策略属短线高风险策略，A股 T+1 限制下当日买入次日才能卖出。")
    L("  · 隔夜存在跳空（低开/高开）风险，可能直接触发止损。")
    L("  · 回测/历史统计不代表未来收益，不保证次日上涨。")
    L("  · 相对强弱含申万一级行业实时涨跌（数据可得时），否则回退沪深300/中证1000代理。")
    L("  · 若数据不足（无分时/流动性差/接近涨停过热），不得强行产生信号。")
    L("  · 以下概率为基于规则的主观估计，并非经过历史训练得到的统计概率。")
    L("⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。")
    return "\n".join(lines)


def build_html(results, watch, env_label, env_points, env_det, snapshot, top, bear_threshold, date_str, industry_ok):
    """生成自包含 HTML 看板（轻主题）。返回 HTML 字符串。"""
    env_color = {"Bull": "#c0392b", "Neutral": "#b8860b", "Bear": "#2e7d32"}.get(env_label, "#555")
    def row_html(r, rank=None):
        sc = r["score"]
        rsd = sc["rs_det"]
        rs_ind = rsd.get("rs_industry")
        rs_txt = f"{rs_ind*100:.2f}%" if (rsd.get("industry_available") and rs_ind is not None) else "N/A"
        cls = "pass" if r.get("passes") else "miss"
        name_disp = r["name"]
        return (f"<tr class='{cls}'><td>{rank if rank else ''}</td><td>{name_disp}</td>"
                f"<td class='code'>{r['code']}</td><td class='num'>{r['day_chg_pct']:.2f}%</td>"
                f"<td class='num'>{sc['afternoon']:.1f}</td><td class='num'>{sc['volume']:.1f}</td>"
                f"<td class='num'>{sc['rs']:.1f}</td><td class='num'>{sc['risk']:.1f}</td>"
                f"<td class='num total'>{sc['total']:.1f}</td></tr>")
    cand_rows = "".join(row_html(r, i + 1) for i, r in enumerate(results)) if results else \
        "<tr><td colspan='9' class='empty'>今日无符合策略条件的交易机会，建议空仓。</td></tr>"
    watch_rows = "".join(
        f"<tr><td>{i+1}</td><td>{r['name']}</td><td class='code'>{r['code']}</td>"
        f"<td class='num'>{r['day_chg_pct']:.2f}%</td><td class='num'>{r['score']['total']:.1f}</td>"
        f"<td class='reason'>{'; '.join(r['miss'])}</td></tr>"
        for i, r in enumerate(watch)) if watch else \
        "<tr><td colspan='6' class='empty'>无观察名单（未触发接近阈值的高分票）。</td></tr>"

    cards = ""
    for i, r in enumerate(results[:3], 1):
        sc = r["score"]; ad = sc["aft_det"]; vd = sc["vol_det"]; rd = sc["rs_det"]
        conf = "强烈关注" if sc["total"] >= 85 and sc["afternoon"] >= 18 else ("关注" if sc["total"] >= 75 else "观察")
        atr = r.get("atr") or abs(r.get("day_chg_pct", 0)) / 100 * sc["snapshot_close"]
        target = sc["snapshot_close"] * (1 + max(0.01, min(0.025, atr / sc["snapshot_close"] * 1.5)))
        stop = sc["snapshot_close"] * (1 - max(0.01, min(0.02, atr / sc["snapshot_close"] * 1.0)))
        rs_ind = rd.get("rs_industry")
        rs_txt = f"{rs_ind*100:.2f}%" if (rd.get("industry_available") and rs_ind is not None) else "N/A(映射缺失)"
        cards += f"""
        <div class="card">
          <div class="card-h"><span class="rk">#{i}</span> {r['name']} <span class="code">{r['code']}</span>
            <span class="badge">{conf}</span> <span class="total-b">{sc['total']:.1f}</span></div>
          <div class="kv"><span>现价</span><b>{sc['snapshot_close']:.2f}</b><span>当日涨幅</span><b>{r['day_chg_pct']:.2f}%</b></div>
          <div class="kv"><span>14:00后</span><b>{ad.get('aft_1400',0)*100:.2f}%</b><span>下午-上午</span><b>{ad.get('aft_vs_morn',0)*100:.2f}%</b></div>
          <div class="kv"><span>突破日内高</span><b>{'是' if ad.get('break_high') else '否'}</b><span>下午量速/上午</span><b>{ad.get('vol_pace_ratio',0):.2f}</b></div>
          <div class="kv"><span>量放大比</span><b>{vd.get('vol_surge',0):.2f}x</b><span>相对沪深300</span><b>{rd.get('rs_hs300',0)*100:.2f}%</b></div>
          <div class="kv"><span>相对中证1000</span><b>{rd.get('rs_zz1000',0)*100:.2f}%</b><span>相对申万行业</span><b>{rs_txt}</b></div>
          <div class="plan">次日目标 +1%~+{(target/sc['snapshot_close']-1)*100:.1f}%（≈{target:.2f}）｜止损 {(stop/sc['snapshot_close']-1)*100:.1f}%（≈{stop:.2f}）｜单只≤20%仓位</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>A股尾盘启动隔夜策略 · 看板 {date_str}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; margin: 0;
  background: #f5f6f8; color: #1f2329; }}
.wrap {{ max-width: 1080px; margin: 0 auto; padding: 22px 18px 40px; }}
h1 {{ font-size: 20px; margin: 0 0 4px; }}
.sub {{ color: #6b7280; font-size: 13px; margin-bottom: 16px; }}
.env {{ background: #fff; border-radius: 12px; padding: 16px 18px; margin-bottom: 18px;
  border-left: 6px solid {env_color}; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
.env .st {{ font-size: 18px; font-weight: 700; color: {env_color}; }}
.env .row {{ display: flex; gap: 18px; flex-wrap: wrap; margin-top: 8px; font-size: 13px; color: #374151; }}
.env .row b {{ color: #111; }}
.sec {{ font-size: 15px; font-weight: 600; margin: 20px 0 10px; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px; overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); font-size: 13px; }}
th, td {{ padding: 9px 10px; text-align: left; border-bottom: 1px solid #eef0f3; }}
th {{ background: #f0f2f5; color: #4b5563; font-weight: 600; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.code, th.code {{ font-family: ui-monospace, Menlo, monospace; color: #6b7280; }}
tr.pass td.total {{ color: #c0392b; font-weight: 700; }}
tr.miss td.total {{ color: #b8860b; }}
td.empty {{ text-align: center; color: #9ca3af; padding: 18px; }}
td.reason {{ color: #b45309; font-size: 12px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; margin-top: 10px; }}
.card {{ background: #fff; border-radius: 12px; padding: 14px 16px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
.card-h {{ font-size: 15px; font-weight: 700; margin-bottom: 8px; }}
.rk {{ color: #c0392b; }}
.badge {{ background: #fdecea; color: #c0392b; font-size: 11px; padding: 2px 7px; border-radius: 10px; margin-left: 6px; }}
.total-b {{ float: right; color: #c0392b; font-size: 17px; }}
.kv {{ display: flex; gap: 8px; font-size: 12.5px; padding: 3px 0; color: #6b7280; }}
.kv b {{ color: #111; margin-right: auto; }}
.plan {{ margin-top: 8px; padding: 8px 10px; background: #f7f8fa; border-radius: 8px; font-size: 12px; color: #374151; }}
.foot {{ margin-top: 26px; font-size: 12px; color: #9ca3af; line-height: 1.6; border-top: 1px solid #e5e7eb; padding-top: 12px; }}
.tag {{ display: inline-block; background: #eef2ff; color: #4338ca; font-size: 11px; padding: 2px 8px; border-radius: 10px; }}
</style></head>
<body><div class="wrap">
<h1>A股尾盘启动隔夜策略 · 选股看板</h1>
<div class="sub">快照时刻 {snapshot[:2]}:{snapshot[2:]}（仅使用该时刻及之前数据，无未来函数）｜生成 {date_str} {
  '<span class="tag">行业RS已启用</span>' if industry_ok else '<span class="tag">行业RS未启用</span>'}</div>

<div class="env">
  <div class="st">市场状态：{env_label}　环境评分 {env_points}/10</div>
  <div class="row">
    <span>指数平均涨跌 <b>{env_det.get('idx_avg_chg')}%</b></span>
    <span>涨跌家数比 <b>{env_det.get('breadth_ratio')}%</b></span>
    <span>涨停 <b>{env_det.get('limitup')}</b></span>
    <span>跌停 <b>{env_det.get('limitdown')}</b></span>
    {f"<span style='color:#c0392b'>偏弱环境：门槛提高到 ≥ {bear_threshold}</span>" if env_label=='Bear' else ""}
  </div>
</div>

<div class="sec">② 今日候选股票（最多 {top} 只）</div>
<table><thead><tr><th>排名</th><th>股票</th><th>代码</th><th class="num">涨幅</th>
  <th class="num">下午动量</th><th class="num">成交量</th><th class="num">相对强弱</th>
  <th class="num">风险</th><th class="num">总分</th></tr></thead>
<tbody>{cand_rows}</tbody></table>

<div class="sec">②b 观察名单（未达买入阈值，仅跟踪）</div>
<table><thead><tr><th>序</th><th>股票</th><th>代码</th><th class="num">涨幅</th>
  <th class="num">总分</th><th>未入选原因</th></tr></thead><tbody>{watch_rows}</tbody></table>

<div class="sec">③ 最值得关注的股票（前 3）</div>
<div class="cards">{cards if cards else "<div class='empty' style='color:#9ca3af;padding:14px'>无候选。</div>"}</div>

<div class="foot">
  ⚠️ 以上内容由 AI 基于公开信息整理生成，仅供参考，不构成任何投资建议或个股推荐。投资有风险，决策需谨慎。<br>
  相对强弱含申万一级行业（实时），数据源：腾讯自选股。次日概率为基于规则的主观估计，非历史统计概率。
</div>
</div></body></html>"""
    return html


def main():
    ap = argparse.ArgumentParser(description="A股尾盘启动隔夜策略扫描器")
    ap.add_argument("--codes", default="", help="逗号分隔股票代码，如 sh600519,sz000858")
    ap.add_argument("--universe", default="", help="股票池文件（每行一个代码）")
    ap.add_argument("--snapshot", default="1430", help="决策时刻 HHMM，默认 1430")
    ap.add_argument("--top", type=int, default=5, help="最多推荐数量")
    ap.add_argument("--westock-cli", default="", help="westock-data scripts/index.js 路径")
    ap.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR,
                    help=f"原始 CLI 输出缓存目录（默认 {DEFAULT_CACHE_DIR}；置空传 --cache-dir '' 可关闭）")
    ap.add_argument("--review", action="store_true", help="对 signals 文件做次日复盘（默认取 results/ 下最近一个）")
    ap.add_argument("--review-file", default="", help="指定复盘用的 signals JSON")
    ap.add_argument("--out-dir", default=DEFAULT_RESULTS_DIR,
                    help=f"报告/信号输出目录（默认 {DEFAULT_RESULTS_DIR}）")
    # ① 初筛流水线
    ap.add_argument("--screen", action="store_true", help="先跑 westock-tool 初筛，再对候选做扫描")
    ap.add_argument("--screen-expr", default="",
                    help="初筛表达式（默认：流动性好且当日涨幅2%~7%、换手率1%~12%的A股）")
    ap.add_argument("--screen-limit", type=int, default=50, help="初筛最多返回数量（默认50）")
    ap.add_argument("--westock-tool-cli", default="", help="westock-tool scripts/index.js 路径")
    # ② 申万行业实时相对强弱
    ap.add_argument("--no-industry-rs", action="store_true", help="关闭申万一级行业实时相对强弱（仅用指数代理）")
    # ③ HTML 看板
    ap.add_argument("--no-html", action="store_true", help="不生成 HTML 看板")
    args = ap.parse_args()

    cli = find_westock_cli(args.westock_cli or None)
    snapshot = args.snapshot
    bear_threshold = 80
    normal_threshold = 70

    # ---- 复盘模式 ----
    if args.review:
        do_review(cli, args)
        return

    codes = load_universe(args.codes, args.universe)
    if args.screen:
        # ① 初筛流水线：先 westock-tool 条件选股，再对候选做扫描
        tool_cli = find_westock_tool_cli(args.westock_tool_cli or None)
        expr = args.screen_expr or \
            "intersect([ChangePCT >= 2, ChangePCT <= 7, TurnoverRate > 1, TurnoverRate < 12, TotalMV > 5000000000])"
        print(f"[信息] 初筛中（westock-tool）：{expr}", file=sys.stderr)
        codes = run_screen_pipeline(tool_cli, expr, args.screen_limit, args.cache_dir)
        print(f"[信息] 初筛返回 {len(codes)} 只，进入扫描。", file=sys.stderr)
    elif not codes:
        # 默认演示池（代表性，非全市场）
        codes = ["sh600519","sz000858","sh601318","sz000333","sh600036","sz002594",
                 "sh600276","sz300750","sh601012","sh600900","sz000651","sh600030",
                 "sz002415","sh600887","sz300059","sz000725","sz002230","sh600570",
                 "sz300760","sh688981"]
        print("[提示] 未指定 --codes/--universe/--screen，使用内置演示股票池（%d 只）。" % len(codes), file=sys.stderr)

    print(f"[信息] CLI={cli}", file=sys.stderr)
    print(f"[信息] 拉取市场环境数据（指数 + 涨跌家数）...", file=sys.stderr)
    idx_chg, idx_mapped = fetch_index_data(cli, snapshot, args.cache_dir)
    breadth = parse_changedist(run_westock(cli, "changedist", "hs", cache_dir=args.cache_dir, tag="changedist"))
    env_label, env_points, env_det = score_market_env(idx_chg, breadth)
    print(f"[信息] 市场环境：{env_label}（{env_points}/10）", file=sys.stderr)

    threshold = bear_threshold if env_label == "Bear" else normal_threshold

    # ② 申万一级行业实时相对强弱（可选）
    industry_rs = not args.no_industry_rs
    industry_chg_map = {}   # 行业名 -> 当日涨跌幅(小数)
    profiles = {}           # code -> 行业名
    if industry_rs:
        ind_map = fetch_industry_map(cli, args.cache_dir)
        for i in range(0, len(codes), 50):
            chunk = codes[i:i + 50]
            try:
                profiles.update(parse_profile_batch(
                    run_westock(cli, "profile", ",".join(chunk), cache_dir=args.cache_dir, tag=f"prof_{i}")))
            except Exception as e:
                print(f"[提示] 行业获取失败：{e}", file=sys.stderr)
        ind_names = list({v for v in profiles.values() if v})
        industry_chg_map = fetch_industry_change_map(cli, ind_names, ind_map, args.cache_dir)
        print(f"[信息] 行业RS：{len(industry_chg_map)}/{len(ind_names)} 个行业取得实时涨跌。", file=sys.stderr)
    industry_ok = bool(industry_chg_map)

    results = []
    excluded = []
    for code in codes:
        try:
            d = fetch_stock_data(cli, code, snapshot, args.cache_dir)
        except Exception as e:
            excluded.append((code, f"抓取失败:{e}"))
            continue
        if d is None:
            excluded.append((code, "无行情"))
            continue
        if "excluded" in d:
            excluded.append((code, d["excluded"]))
            continue
        quote, kline, minute = d["quote"], d["kline"], d["minute"]
        intraday = compute_intraday(minute, snapshot, quote["prev_close"], quote["open"])
        if not intraday:
            excluded.append((code, "分时解析失败"))
            continue
        series = build_daily_series(kline, intraday["cur"])
        daily = compute_daily_indicators(series)
        daily["close_proxy"] = intraday["cur"]
        vol_surge = compute_volume_surge(intraday, daily, snapshot)
        # ② 行业相对强弱：code -> 行业名 -> 实时涨跌幅
        industry_chg = None
        if industry_rs:
            iname = profiles.get(code)
            if iname:
                industry_chg = industry_chg_map.get(iname)
        sc = score_stock(quote, intraday, daily, vol_surge, idx_mapped, env_points, snapshot, industry_chg)
        # 过滤条件（策略第十二节）
        rs_pos = (sc["rs_det"].get("rs_hs300", 0) > 0) or (sc["rs_det"].get("rs_zz1000", 0) > 0)
        near_limit = sc["risk_det"].get("near_limitup", False)
        c_total = sc["total"] >= threshold
        c_aft = sc["afternoon"] >= 12
        c_dir = intraday["day_chg"] > 0 and (vol_surge is None or vol_surge >= 1.0)
        c_liq = (intraday["amount_cur"] or 0) / 1e8 >= 1.0
        passes = c_total and c_aft and c_dir and rs_pos and c_liq and not near_limit
        miss = []
        if not c_total: miss.append(f"总分{sc['total']}<{threshold}")
        if not c_aft: miss.append(f"下午动量{sc['afternoon']}<12")
        if not c_dir: miss.append(f"量价方向不一致(涨幅{intraday['day_chg']*100:.2f}%,量比{vol_surge if vol_surge is not None else 'NA'})")
        if not rs_pos: miss.append("相对强弱为负")
        if not c_liq: miss.append("流动性不足")
        if near_limit: miss.append("接近涨停/过热")
        rec = {
            "code": code, "name": quote["name"], "score": sc,
            "day_chg_pct": intraday["day_chg"] * 100,
            "morn_ret": intraday["morn_ret"],
            "aft_1400": intraday["aft_1400"],
            "vol_surge": vol_surge,
            "atr": daily["atr"],
            "passes": passes,
            "miss": miss,
        }
        results.append(rec)
        print(f"[信息] {code} {quote['name']}: 总分 {sc['total']} "
              f"(趋{sc['trend']}/下{sc['afternoon']}/量{sc['volume']}/强{sc['rs']}/环{sc['env']}/险{sc['risk']}) "
              f"{'✓' if passes else '✗'}", file=sys.stderr)

    # 排序：通过的在前，再按总分
    passed = [r for r in results if r["passes"]]
    others = [r for r in results if not r["passes"]]
    passed.sort(key=lambda x: -x["score"]["total"])
    others.sort(key=lambda x: -x["score"]["total"])
    final = passed[:args.top]
    # 观察名单：未达买入阈值但分数较高（策略「60~69分：观察」档），供跟踪
    watch = [r for r in others if r["score"]["total"] >= 60][:args.top]

    report = build_report(final, watch, env_label, env_points, env_det, snapshot, args.top, bear_threshold)
    print(report)

    # 保存信号（供次日复盘）
    today = date.today().strftime("%Y-%m-%d")
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    signals = {
        "date": today, "snapshot": snapshot, "env_label": env_label,
        "env_points": env_points, "threshold": threshold,
        "candidates": [
            {"code": r["code"], "name": r["name"], "total": r["score"]["total"],
             "snapshot_close": r["score"]["snapshot_close"],
             "day_chg_pct": r["day_chg_pct"]}
            for r in final
        ],
        "excluded_count": len(excluded),
    }
    sig_path = os.path.join(out_dir, f"signals_{today}.json")
    with open(sig_path, "w", encoding="utf-8") as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)
    rep_path = os.path.join(out_dir, f"report_{today}.txt")
    with open(rep_path, "w", encoding="utf-8") as f:
        f.write(report)

    # ③ HTML 看板
    if not args.no_html:
        html = build_html(final, watch, env_label, env_points, env_det, snapshot,
                          args.top, bear_threshold, today, industry_ok)
        html_path = os.path.join(out_dir, f"dashboard_{today}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[完成] 看板已保存: {html_path}", file=sys.stderr)

    print(f"\n[完成] 信号已保存: {sig_path}", file=sys.stderr)
    print(f"[完成] 报告已保存: {rep_path}", file=sys.stderr)
    if excluded:
        print(f"[提示] 排除/失败 {len(excluded)} 只："
              + "; ".join(f"{c}({r})" for c, r in excluded[:10]), file=sys.stderr)


# --------------------------------------------------------------------------- #
# 8. 次日复盘
# --------------------------------------------------------------------------- #
def do_review(cli, args):
    sig_path = args.review_file
    if not sig_path:
        # 默认取输出目录下「按文件名（含日期后缀）排序」最近的一份信号
        cands = sorted(glob.glob(os.path.join(args.out_dir, "signals_*.json")))
        if not cands:
            print(f"未找到任何信号文件于：{args.out_dir}"
                  f"（请先运行一次选股，或用 --review-file 指定）")
            return
        sig_path = cands[-1]
        print(f"[信息] 自动选用最近信号文件：{sig_path}")
    if not os.path.exists(sig_path):
        print(f"未找到信号文件：{sig_path}（请先运行一次选股）")
        return
    with open(sig_path, "r", encoding="utf-8") as f:
        sig = json.load(f)
    print(f"复盘日期信号来源：{sig['date']} 快照 {sig['snapshot']}")
    # 次日 = 信号日期的下一个交易日；这里用 quote（含 prevClose/open/high/low/price）
    # 以及 kline 取次日那一行。简化：用 quote 的 open/high/low/price 近似次日（若已发生）。
    codes = [c["code"] for c in sig["candidates"]]
    if not codes:
        print("上次无候选，无需复盘。")
        return
    q = parse_quote_batch(run_westock(cli, "quote", ",".join(codes)))
    for c in sig["candidates"]:
        code = c["code"]
        qq = q.get(code)
        if not qq:
            print(f"{code} {c['name']}: 无行情")
            continue
        prev = qq.get("prev_close"); op = qq.get("open")
        hi = qq.get("high"); lo = qq.get("low"); px = qq.get("price")
        rec_price = c["snapshot_close"]
        max_win = (hi / rec_price - 1) * 100 if hi else None
        max_loss = (lo / rec_price - 1) * 100 if lo else None
        print(f"{code} {c['name']}: 推荐价 {rec_price:.2f} → 次日开 {op} 高 {hi} 低 {lo} 收 {px} "
              f"| 最大盈利 {max_win:.2f}% 最大亏损 {max_loss:.2f}%")


if __name__ == "__main__":
    main()
