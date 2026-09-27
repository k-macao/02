#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📡 数据层 —— 量化引擎的第 1 层（唯一的联网层）。

所有函数都通过注入的 ``fetch_json(url, params=..., timeout=...)`` 取数，
因此单元测试可以在完全离线的情况下用假数据替换整个网络层。

取数原则（与日报其它数据源一致）：
  · 抓不到就返回空 / None，绝不返回历史兜底数字，绝不「用旧数据冒充实时」；
  · 每个函数只负责「把原始接口解析成标准结构」，不做任何统计判断。
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))  # 北京时间 / 澳门时间

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
EASTMONEY_CLIST = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_ULIST = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EASTMONEY_DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# ------------------------------------------------------------------
# 标的池（可用环境变量覆盖，逗号分隔的 Yahoo 代码即可）
# ------------------------------------------------------------------
# 指数：恒指（大盘）/ 恒生科技（成长）/ 国企指数（中资）
HK_INDEX_SPECS = [
    ("恒生指数", "^HSI"),
    ("恒生科技", "^HSTECH"),
    ("国企指数", "^HSCEI"),
]

# 个股：港股市值 / 成交活跃度居前的中资与本地蓝筹（Yahoo 代码 = 5 位数字.HK）
HK_STOCK_UNIVERSE = [
    ("腾讯控股", "0700.HK"),
    ("阿里巴巴-W", "9988.HK"),
    ("美团-W", "3690.HK"),
    ("小米集团-W", "1810.HK"),
    ("友邦保险", "1299.HK"),
    ("汇丰控股", "0005.HK"),
    ("建设银行", "0939.HK"),
    ("中国移动", "0941.HK"),
    ("香港交易所", "0388.HK"),
    ("中芯国际", "0981.HK"),
    ("比亚迪股份", "1211.HK"),
    ("快手-W", "1024.HK"),
    ("京东集团-SW", "9618.HK"),
    ("中国海洋石油", "0883.HK"),
    ("中国平安", "2318.HK"),
    ("安踏体育", "2020.HK"),
    ("网易-S", "9999.HK"),
    ("药明生物", "2269.HK"),
]

# 港股在东方财富的 secid 前缀（1=A股 0=深/京 100=HK指数 105~107=美股 116=港股个股）
EM_HK_PREFIX = "116."


def _env_list(name, default):
    """从环境变量读取标的池（``代码:名称,代码:名称``）。"""
    raw = os.environ.get(name, "")
    items = []
    for chunk in str(raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            code, label = chunk.split(":", 1)
            items.append((label.strip() or code.strip(), code.strip()))
        else:
            items.append((chunk, chunk))
    return items or default


def hk_index_specs():
    return _env_list("OCTOPUS_HK_INDEX_SPECS", HK_INDEX_SPECS)


def hk_stock_universe():
    return _env_list("OCTOPUS_HK_UNIVERSE", HK_STOCK_UNIVERSE)


# ------------------------------------------------------------------
# Yahoo Finance Chart —— 日线序列
# ------------------------------------------------------------------
def fetch_bars(fetch_json, symbol, *, rng="1y", interval="1d", timeout=15):
    """取一只标的的日线序列。

    返回按日期升序的 ``[{date, open, high, low, close, volume}, ...]``；
    任何一步失败都返回 ``[]``（由上层决定降级，绝不编造数据）。
    """
    if not fetch_json:
        return []
    url = YAHOO_CHART.format(symbol=symbol)
    data = fetch_json(url, params={"range": rng, "interval": interval},
                      timeout=timeout)
    try:
        result = (data or {})["chart"]["result"][0]
        stamps = result.get("timestamp") or []
        quote = result["indicators"]["quote"][0]
        closes = quote.get("close") or []
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        volumes = quote.get("volume") or []
    except (KeyError, TypeError, IndexError, AttributeError):
        return []

    bars = []
    for i, ts in enumerate(stamps):
        try:
            close = closes[i]
            if close is None:
                continue
            bars.append({
                "date": datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d"),
                "open": opens[i] if i < len(opens) else None,
                "high": highs[i] if i < len(highs) else None,
                "low": lows[i] if i < len(lows) else None,
                "close": float(close),
                "volume": (volumes[i] if i < len(volumes) else None),
            })
        except (IndexError, TypeError, ValueError):
            continue
    bars.sort(key=lambda b: b["date"])
    return bars


def fetch_series_batch(fetch_json, specs, *, rng="1y", workers=6, timeout=15,
                       executor=None):
    """并发抓一批标的；返回 ``{代码: [bars]}``（失败的键不出现，不造假）。"""
    from concurrent.futures import ThreadPoolExecutor

    if not fetch_json or not specs:
        return {}
    out = {}

    def _one(item):
        label, symbol = item
        return symbol, fetch_bars(fetch_json, symbol, rng=rng, timeout=timeout)

    if executor is not None:
        for symbol, bars in executor.map(_one, specs):
            if bars:
                out[symbol] = bars
        return out
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for symbol, bars in pool.map(_one, specs):
            if bars:
                out[symbol] = bars
    return out


# ------------------------------------------------------------------
# 东方财富 —— 南向 / 北向资金（沪深港通成交总额历史）
# ------------------------------------------------------------------
MUTUAL_TYPE_NORTH = "005"   # 北向合计（沪股通 + 深股通）
MUTUAL_TYPE_SOUTH = "006"   # 南向合计（港股通沪 + 港股通深）


def fetch_mutual_series(fetch_json, page_size=500, timeout=15):
    """沪深港通每日成交总额（单位：亿元）。

    返回 ``{"north": [(date, 亿元)], "south": [(date, 亿元)]}``（按日期升序）。
    说明：港交所自 2024-08-19 起停披南北向净买入，只披露成交总额，
    因此这里用「成交总额」刻画资金活跃度，不估算、更不编造净流入。
    """
    empty = {"north": [], "south": []}
    if not fetch_json:
        return empty
    params = {
        "reportName": "RPT_MUTUAL_DEAL_HISTORY",
        "columns": "ALL",
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": "TRADE_DATE,MUTUAL_TYPE",
        "sortTypes": "-1,1",
        "source": "WEB",
        "client": "WEB",
    }
    data = fetch_json(EASTMONEY_DATACENTER, params=params, timeout=timeout)
    try:
        rows = ((data or {}).get("result") or {}).get("data") or []
    except (AttributeError, TypeError):
        return empty

    def _collect(mtype):
        pairs = []
        for it in rows:
            if str(it.get("MUTUAL_TYPE") or "") != mtype:
                continue
            day = str(it.get("TRADE_DATE") or "")[:10]
            try:
                amt = float(it.get("DEAL_AMT"))
            except (TypeError, ValueError):
                continue
            if day and amt > 0:
                pairs.append((day, amt / 100.0))  # 百万元 → 亿元
        pairs.sort(key=lambda p: p[0])
        return pairs

    return {"north": _collect(MUTUAL_TYPE_NORTH),
            "south": _collect(MUTUAL_TYPE_SOUTH)}


# ------------------------------------------------------------------
# 东方财富 —— 港股大盘成交 / 龙头成交额集中度
# ------------------------------------------------------------------
def fetch_hk_index_quotes(fetch_json, timeout=12):
    """恒指 / 恒科 / 国企指数的最新价与成交额（东财口径）。

    返回 ``{代码: {name, price, chg_pct, amount}}``；失败返回 {}。
    """
    if not fetch_json:
        return {}
    secids = ",".join(f"100.{code}" for code in ("HSI", "HSTECH", "HSCEI"))
    data = fetch_json(EASTMONEY_ULIST, params={
        "fltt": "2", "invt": "2", "secids": secids,
        "fields": "f2,f3,f4,f6,f12,f14",
    }, timeout=timeout)
    out = {}
    try:
        rows = ((data or {}).get("data") or {}).get("diff") or []
    except (AttributeError, TypeError):
        return out
    for it in rows:
        code = str(it.get("f12") or "").strip()
        try:
            price = float(it.get("f2"))
        except (TypeError, ValueError):
            continue
        amount = None
        try:
            amount = float(it.get("f6"))
        except (TypeError, ValueError):
            amount = None
        out[code] = {
            "name": str(it.get("f14") or "").strip() or code,
            "price": price,
            "chg_pct": _num(it.get("f3")),
            "amount": amount,  # 单位：元
        }
    return out


def fetch_hk_top_turnover(fetch_json, top_n=50, timeout=12):
    """港股主板成交额前 N 只（东财 push2 免费接口）。

    返回 ``[{code, name, price, chg_pct, amount}]``（amount 单位：元，降序）。
    用于计算「资金集中度 CR5 / CR20」——资金扎堆在哪里，是流动性分析的核心。
    """
    if not fetch_json:
        return []
    data = fetch_json(EASTMONEY_CLIST, params={
        "pn": "1", "pz": str(top_n), "po": "1", "np": "1", "fltt": "2",
        "invt": "2", "fid": "f6",
        "fs": "m:128+t:1,m:128+t:2,m:128+t:3,m:128+t:4",
        "fields": "f2,f3,f6,f12,f14",
    }, timeout=timeout)
    try:
        diff = ((data or {}).get("data") or {}).get("diff") or []
    except (AttributeError, TypeError):
        return []
    rows = []
    for it in diff[:top_n]:
        name = str(it.get("f14") or "").strip()
        amount = _num(it.get("f6"))
        if not name or amount is None:
            continue
        rows.append({
            "code": str(it.get("f12") or "").strip(),
            "name": name,
            "price": _num(it.get("f2")),
            "chg_pct": _num(it.get("f3")),
            "amount": amount,
        })
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return rows


def fetch_hk_fundflow(fetch_json, universe=None, timeout=12):
    """个股主力资金净流入（东财港股资金流字段 f62/主力净占比 f184）。

    返回 ``{5位代码: {"main_net": 元, "main_pct": %, "name": 名称}}``。
    港股该字段不保证可用，取不到返回 {}（上层按「无个股资金流」降级）。
    """
    if not fetch_json:
        return {}
    universe = universe or hk_stock_universe()
    secids = []
    for _label, symbol in universe:
        code = symbol.split(".")[0]
        if code.isdigit():
            secids.append(f"{EM_HK_PREFIX}{code}")
    if not secids:
        return {}
    out = {}
    for i in range(0, len(secids), 8):  # 小批量，避免单请求过长
        data = fetch_json(EASTMONEY_ULIST, params={
            "fltt": "2", "invt": "2", "secids": ",".join(secids[i:i + 8]),
            "fields": "f12,f14,f2,f3,f62,f184",
        }, timeout=timeout)
        try:
            rows = ((data or {}).get("data") or {}).get("diff") or []
        except (AttributeError, TypeError):
            continue
        for it in rows:
            code = str(it.get("f12") or "").strip()
            net = _num(it.get("f62"))
            if not code or net is None:
                continue
            out[code] = {
                "name": str(it.get("f14") or "").strip() or code,
                "main_net": net,
                "main_pct": _num(it.get("f184")),
            }
    return out


def _num(val):
    """东财字段可能是 ``"-"`` / None / 字符串数字。"""
    try:
        if val is None or val == "-" or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None
