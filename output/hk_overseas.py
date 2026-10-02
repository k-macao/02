#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🇭🇰 港股境外数据源读取（hk_overseas）

用途：为日报「【深水石斑鱼】港股行情」栏目供数。全部取自**境外（香港 / 国际）公开站点**，
无需 API Key，四个数据源彼此独立、各自降级，取不到就标注「暂缺」，绝不编造数字。

数据源与优先级（同一品种按路序取第一个有效值，每行都标明供数来源与行情日期）：

  ① Yahoo Finance Chart API（query1 → query2 两主机）———— 主源
     港股指数（恒生指数 ^HSI / 恒生科技 ^HSTECH / 恒生国企 ^HSCE）+ 港股个股篮子。
     JSON 免密钥，日报流水线已在用（实时行情栏目同一条数据线），这里复用同一口径。

  ② Stooq（stooq.com / stooq.pl 镜像）———— 备用源 + 交叉校验
     国际行情站点，提供港股日线 CSV（如 0700.hk）。主源缺某只时由它补位；
     OCTOPUS_HK_CROSSCHECK=1 时对主源价格做独立交叉校验，偏差 >1.5% 记入 crosscheck。

  ③ HKEX 香港交易所官网 ———— 市场层数据（成交额 / 统计）
     每日市场统计页。服务端多为静态 HTML，用关键词 + 单位的确定性解析；
     读不出数字（或读得到数字但没有单位）→ 返回 {}，栏目显示「暂缺」。

  ④ stealth 浏览器（tools/patchright-enhanced/probe.js）———— 可选，默认关闭
     用 patchright 的 stealth Chrome 渲染带 WAF 的香港财经站点
     （etnet 經濟通 / aastocks 阿斯達克 / investing.com / HKEX 统计页），
     再把页面文本交回本模块解析。开启方式：OCTOPUS_HK_BROWSER=1，
     且本机有 node + `tools/patchright-enhanced/npm install` + Chrome。
     浏览器只读公开页面，不登录、不绕过付费墙；解析不出数字时如实标注。

结构约定：返回的 dict 与 pipeline 的 `_source_result` 同构（source / status / is_today /
content_date / fetched_at / snapshot），另附：
  indices  —— 指数行 [{label, code, price, change_pct, volume, turnover_yi, as_of, source}]
  stocks   —— 个股行（同上结构 + sec_code）
  market   —— {turnover_yi, as_of, source, raw} 或 {}
  sources  —— 每一路的运行状态 [{name, tier, status, as_of, count, note}]
  crosscheck —— 交叉校验结果（可选）

单独调试：python3 output/hk_overseas.py [--browser] [--json]
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote as _urlquote

CST = timezone(timedelta(hours=8))          # 香港与北京同时区（UTC+8，无夏令时）

# ------------------------------------------------------------
# 配置（环境变量可覆盖；非法值一律回落默认，不抛异常）
# ------------------------------------------------------------
HK_OVERSEAS_SOURCE = "港股境外数据源"

YAHOO_HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
STOOQ_HOSTS = ("https://stooq.com", "https://stooq.pl")
# HKEX 每日市场统计（英文页；OCTOPUS_HKEX_URL 可换成中文页或其它统计页）
HKEX_STATS_URL = os.environ.get(
    "OCTOPUS_HKEX_URL",
    "https://www.hkex.com.hk/Market-Data/Statistics/Securities-Market-Statistics/"
    "Daily-Market-Report?sc_lang=en",
)

# 港股指数（Yahoo 代码 / 展示名 / Stooq 代码，Stooq 无对应代码时为 None → 该路自然跳过）
HK_INDEX_SPECS = (
    {"label": "恒生指数", "code": "^HSI", "stooq": "^hsi"},
    {"label": "恒生科技", "code": "^HSTECH", "stooq": None},
    {"label": "恒生中国企业指数", "code": "^HSCE", "stooq": None},
)

# 港股个股篮子（Yahoo 代码 / Stooq 代码 / 展示名；OCTOPUS_HK_BASKET 可覆盖）
_DEFAULT_BASKET = (
    ("0700.HK", "0700.hk", "腾讯控股"),
    ("9988.HK", "9988.hk", "阿里巴巴-W"),
    ("3690.HK", "3690.hk", "美团-W"),
    ("1810.HK", "1810.hk", "小米集团-W"),
    ("0941.HK", "0941.hk", "中国移动"),
    ("1299.HK", "1299.hk", "友邦保险"),
    ("0388.HK", "0388.hk", "香港交易所"),
    ("2318.HK", "2318.hk", "中国平安"),
)


def _env_flag(name, default=False):
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "y")


def _basket():
    """个股篮子：OCTOPUS_HK_BASKET="0700.HK:腾讯控股,9988.HK:阿里巴巴-W" 可覆盖。"""
    raw = str(os.environ.get("OCTOPUS_HK_BASKET", "")).strip()
    if not raw:
        return _DEFAULT_BASKET
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        code, _, label = part.partition(":")
        code = code.strip().upper()
        if not code:
            continue
        stooq = code.lower() if code.endswith(".HK") else code.lower()
        out.append((code, stooq, (label.strip() or code)))
    return tuple(out) or _DEFAULT_BASKET


# 浏览器取数目标（OCTOPUS_HK_BROWSER=1 时启用；只读公开页面）
BROWSER_TARGETS = (
    {"name": "etnet", "label": "經濟通", "kind": "quote",
     "url": "https://www.etnet.com.hk/www/tc/stocks/realtime/quote.php?code={sec}"},
    {"name": "aastocks", "label": "阿斯達克", "kind": "quote",
     "url": "https://www.aastocks.com/tc/stocks/quote/detail-quote.aspx?symbol={yahoo_sec}"},
    {"name": "hkex-stats", "label": "港交所统计", "kind": "market", "url": HKEX_STATS_URL},
)
BROWSER_SEC_CODES = {"0700.HK": "700", "9988.HK": "9988", "3690.HK": "3690", "1810.HK": "1810",
                     "0941.HK": "941", "1299.HK": "1299", "0388.HK": "388", "2318.HK": "2318"}

PROBE_REL_PATH = os.path.join("tools", "patchright-enhanced", "probe.js")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE_PATH = os.environ.get("OCTOPUS_HK_PROBE", os.path.join(_REPO_ROOT, PROBE_REL_PATH))


# ------------------------------------------------------------
# 小工具
# ------------------------------------------------------------
def _num(value):
    """宽松转 float：支持 '1,234.5' / 'N/D' / None；失败返回 None。"""
    try:
        text = str(value).replace(",", "").replace("%", "").strip()
        if not text or text.upper() in ("N/D", "N/A", "-", "--", "—"):
            return None
        out = float(text)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError, AttributeError):
        return None


def _pct(price, prev):
    if price is None or prev in (None, 0):
        return None
    return (price / prev - 1) * 100


def _date_iso(dt):
    return dt.astimezone(CST).strftime("%Y-%m-%d") if dt else None


def _today(now=None):
    return (now or datetime.now(CST)).astimezone(CST).strftime("%Y-%m-%d")


def _fmt_num(v, digits=2):
    return f"{v:,.{digits}f}" if v is not None else "—"


# ------------------------------------------------------------
# ① Yahoo Chart API
# ------------------------------------------------------------
def yahoo_chart_urls(symbol, hosts=YAHOO_HOSTS, rng="5d", interval="1d"):
    """同一品种的主源 → 备用镜像地址（query1 / query2，格式完全一致）。"""
    return [f"{host}/v8/finance/chart/{_urlquote(symbol, safe='')}"
            f"?range={rng}&interval={interval}" for host in hosts]


def parse_yahoo_chart(payload):
    """Yahoo Chart JSON → quote dict；数据不足返回 None（绝不返回半成品数字）。

    口径与 pipeline._yahoo_quote_from_chart 一致：优先用日线序列里最后一根有效收盘，
    日线还没更新到刚收盘那一根时回退 meta.regularMarketPrice（via 字段标明用了哪一路）。
    """
    try:
        results = ((payload or {}).get("chart") or {}).get("result") or []
        result = results[0] or {}
    except (AttributeError, IndexError, TypeError):
        return None
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])
    closes = (quotes[0] or {}).get("close") or []
    volumes = (quotes[0] or {}).get("volume") or []

    bars = []
    for i, ts in enumerate(stamps):
        close = _num(closes[i]) if i < len(closes) else None
        if close and close > 0 and ts:
            vol = _num(volumes[i]) if i < len(volumes) else None
            bars.append((int(ts), close, vol))

    price = bars[-1][1] if bars else _num(meta.get("regularMarketPrice"))
    if not price or price <= 0:
        return None
    prev = None
    via = "bar"
    if len(bars) >= 2:
        prev = bars[-2][1]
    else:
        prev = _num(meta.get("chartPreviousClose")) or _num(meta.get("previousClose"))
        if bars:
            via = "bar"
    if prev is None:
        prev = _num(meta.get("chartPreviousClose")) or _num(meta.get("previousClose"))
    if not bars:
        via = "meta"
        mkt_ts = _num(meta.get("regularMarketTime"))
        as_of = _date_iso(datetime.fromtimestamp(mkt_ts, CST)) if mkt_ts else None
    else:
        as_of = _date_iso(datetime.fromtimestamp(bars[-1][0], CST))
    volume = (bars[-1][2] if bars and bars[-1][2] else None) or _num(meta.get("regularMarketVolume"))
    return {"price": float(price), "change_pct": _pct(price, prev), "volume": volume,
            "currency": meta.get("currency") or "HKD", "as_of": as_of, "via": via}


# ------------------------------------------------------------
# ② Stooq（国际行情站点：备用源 + 交叉校验）
# ------------------------------------------------------------
def stooq_history_urls(symbol, hosts=STOOQ_HOSTS):
    return [f"{host}/q/d/l/?s={_urlquote(str(symbol), safe='')}&i=d" for host in hosts]


def parse_stooq_history_csv(text):
    """Stooq 日线 CSV（Date,Open,High,Low,Close,Volume）→ quote dict。

    取最后两根有效收盘算涨跌幅；不足两根 → change_pct=None（渲染成「—」，不编）。
    """
    if not text or not isinstance(text, str) or "No data" in text[:200]:
        return None
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        head = parts[0].lower()
        if head in ("date", "symbol", "data"):        # 表头 / 本地化表头
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
            continue
        close = _num(parts[4])
        if close is None or close <= 0:
            continue
        rows.append((parts[0], close, _num(parts[5]) if len(parts) > 5 else None))
    if not rows:
        return None
    rows.sort(key=lambda r: r[0])
    last = rows[-1]
    prev = rows[-2][1] if len(rows) >= 2 else None
    return {"price": float(last[1]), "change_pct": _pct(last[1], prev),
            "volume": last[2], "currency": "HKD", "as_of": last[0], "via": "stooq"}


# ------------------------------------------------------------
# ③ HKEX / 市场层文本解析（成交额）
# ------------------------------------------------------------
_TURNOVER_KEYWORDS = ("market turnover", "total turnover", "turnover", "成交金額",
                      "成交金额", "成交總額", "成交总额", "成交額", "成交额")
_UNIT_FACTORS = (
    ("億", 1e8), ("亿", 1e8), ("billion", 1e9), ("bn", 1e9),
    ("百萬", 1e6), ("百万", 1e6), ("million", 1e6), ("mn", 1e6),
    ("萬", 1e4), ("万", 1e4), ("thousand", 1e3),
)
_NUM_RE = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)")
_DATE_RE = re.compile(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})")


def parse_market_stats_text(text):
    """从页面文本里抓「市场成交额」→ {'turnover_yi': 亿港元, 'as_of': 日期或 None, 'raw': 原文片段}。

    诚实约束：数字与单位必须**成对出现**才采纳（HKEX 英文页用 million / billion，
    中文页用 億 / 百萬）；只有数字没有单位 → 返回 {}，不做单位猜测。
    """
    if not text or not isinstance(text, str):
        return {}
    low = text.lower()
    for kw in _TURNOVER_KEYWORDS:
        start = 0
        while True:
            idx = low.find(kw.lower(), start)
            if idx < 0:
                break
            start = idx + len(kw)
            # 数字只在关键词之后找（避免抓到关键词前的日期年份如 2026）；
            # 日期允许向前多看 80 字：官方页的「数据日期」常写在关键词前的表头行。
            window = text[idx:idx + 160]
            num_m = _NUM_RE.search(window)
            if not num_m:
                continue
            value = _num(num_m.group(1))
            if not value or value <= 0:
                continue
            tail = window[num_m.end():num_m.end() + 24].lower()
            factor = None
            for unit, f in _UNIT_FACTORS:
                if tail.lstrip().startswith(unit) or unit in tail[:6]:
                    factor = f
                    break
            if factor is None:
                continue                      # 没单位：宁缺勿猜
            date_m = _DATE_RE.search(text[max(0, idx - 80):idx + 160])
            as_of = None
            if date_m:
                raw_date = date_m.group(1)
                as_of = raw_date.replace("年", "-").replace("月", "-").replace("/", "-").rstrip("-")
                try:                          # 归一成 YYYY-MM-DD
                    parts = [int(x) for x in re.split(r"[-]", as_of) if x.isdigit()]
                    if len(parts) == 3:
                        as_of = f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
                    else:
                        as_of = None
                except (TypeError, ValueError):
                    as_of = None
            return {"turnover_yi": value * factor / 1e8, "as_of": as_of,
                    "raw": window.strip()[:120]}
    return {}


# ------------------------------------------------------------
# ④ 浏览器渲染文本解析（etnet / aastocks / investing / HKEX）
# ------------------------------------------------------------
_PRICE_RE = re.compile(
    r"(?:現價|现价|最新價|最新价|按盤價|按盘价|收市價|收市价|Last\s*Price|Price)\s*[:：]?\s*"
    r"(?:HK\$|HKD|\$)?\s*([0-9][0-9,]*\.[0-9]{1,3})", re.I)
_CHANGE_RE = re.compile(r"([+-]?[0-9]+(?:\.[0-9]+)?)\s*%")
_TURNOVER_TEXT_RE = re.compile(
    r"(?:成交金額|成交金额|成交額|成交额|Turnover)\s*[:：]?\s*(?:HK\$|HKD|\$)?\s*"
    r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(億|亿|百萬|百万|萬|万|B|M|K|billion|million)?", re.I)
_PREV_CLOSE_RE = re.compile(
    r"(?:前收市價|前收市价|上日收市|Previous\s*Close)\s*[:：]?\s*"
    r"(?:HK\$|HKD|\$)?\s*([0-9][0-9,]*\.[0-9]{1,3})", re.I)


def parse_browser_quote_text(text):
    """渲染后的个股页面文本 → {price, change_pct, prev_close, turnover_yi}（尽力而为，字段各自独立）。

    解析不到的字段一律不填；调用方按「暂缺」渲染，不拿相邻数字顶替。
    """
    if not text or not isinstance(text, str):
        return {}
    out = {}
    m = _PRICE_RE.search(text)
    if m:
        out["price"] = _num(m.group(1))
    m = _PREV_CLOSE_RE.search(text)
    if m:
        out["prev_close"] = _num(m.group(1))
    m = _CHANGE_RE.search(text)
    if m:
        out["change_pct"] = _num(m.group(1))
    m = _TURNOVER_TEXT_RE.search(text)
    if m:
        value = _num(m.group(1))
        unit = (m.group(2) or "").lower()
        factor = 1.0
        if unit in ("億", "亿"):
            factor = 1e8
        elif unit in ("百萬", "百万", "m", "million", "mn"):
            factor = 1e6
        elif unit in ("萬", "万", "k", "thousand"):
            factor = 1e3
        elif unit in ("b", "billion", "bn"):
            factor = 1e9
        if value is not None:
            out["turnover_yi"] = value * factor / 1e8
    if out.get("change_pct") is None and out.get("price") and out.get("prev_close"):
        out["change_pct"] = _pct(out["price"], out["prev_close"])
    return out


# ------------------------------------------------------------
# 请求封装：优先用 pipeline 的 safe_request，独立运行时自建
# ------------------------------------------------------------
def _default_request(url, headers=None, params=None, timeout=15, is_json=True):
    try:
        import requests
    except ImportError:
        return None
    try:
        resp = requests.get(url, headers=headers or {"User-Agent": "Mozilla/5.0"}, params=params,
                            timeout=timeout)
        resp.raise_for_status()
        return resp.json() if is_json else resp.text
    except Exception as exc:                       # noqa: BLE001 —— 单路失败只影响该路
        print(f"  ⚠️ [hk_overseas] 请求失败 [{url[:70]}]: {exc}")
        return None


def _get(request, url, is_json=True, timeout=15):
    getter = request or _default_request
    try:
        return getter(url, timeout=timeout, is_json=is_json)
    except TypeError:                              # 兼容只接受 (url) 的简易取数函数（测试替身）
        try:
            return getter(url)
        except Exception as exc:                   # noqa: BLE001
            print(f"  ⚠️ [hk_overseas] 取数失败 [{url[:70]}]: {exc}")
            return None
    except Exception as exc:                       # noqa: BLE001
        print(f"  ⚠️ [hk_overseas] 取数失败 [{url[:70]}]: {exc}")
        return None


def _first_ok(request, urls, is_json=True, timeout=10):
    """依次尝试主源 / 镜像；返回 (结果, 命中URL, 错误列表)。"""
    errors = []
    for url in urls:
        data = _get(request, url, is_json=is_json, timeout=timeout)
        if data:
            return data, url, errors
        errors.append(url)
    return None, None, errors


# ------------------------------------------------------------
# 浏览器取数（可选）
# ------------------------------------------------------------
def _browser_available(node=None):
    node = node or os.environ.get("OCTOPUS_HK_NODE", "node")
    if not shutil.which(node):
        return False, f"未找到 {node}"
    if not os.path.isfile(PROBE_PATH):
        return False, f"未找到 probe.js（{PROBE_PATH}）"
    patchright_dir = os.path.join(os.path.dirname(PROBE_PATH), "node_modules", "patchright")
    if not os.path.isdir(patchright_dir):
        return False, "probe 目录未安装 patchright（npm install）"
    return True, ""


def browser_probe(targets, *, node=None, timeout=240, max_text=200000):
    """调 probe.js 渲染页面；返回 {'ok', 'results', 'error'}（失败不抛异常）。"""
    ok, why = _browser_available(node)
    if not ok:
        return {"ok": False, "results": [], "error": why}
    payload = json.dumps({"targets": list(targets), "max_text": max_text}, ensure_ascii=False)
    try:
        proc = subprocess.run(
            [node or os.environ.get("OCTOPUS_HK_NODE", "node"), PROBE_PATH],
            input=payload.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "results": [], "error": f"probe.js 超时（>{timeout}s）"}
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "results": [], "error": f"probe.js 启动失败：{exc}"}
    raw = (proc.stdout or b"").decode("utf-8", "replace").strip()
    try:
        out = json.loads(raw.splitlines()[-1] if raw else "{}")
    except (ValueError, IndexError):
        return {"ok": False, "results": [],
                "error": f"probe.js 输出非 JSON（stderr: {(proc.stderr or b'')[:200]!r}）"}
    if not out.get("ok"):
        return {"ok": False, "results": [], "error": out.get("error") or "probe 失败"}
    return {"ok": True, "results": out.get("results") or [], "error": None}


def browser_targets_for(indices, stocks, *, include_market=True):
    """给 probe.js 生成目标列表：每只指数 / 个股查 etnet + aastocks，另加 HKEX 统计页。"""
    targets = []
    for row in list(indices) + list(stocks):
        sec = BROWSER_SEC_CODES.get(row["code"]) or row["code"].split(".")[0]
        yahoo_sec = f"{int(sec):05d}" if sec.isdigit() else sec
        for tpl in BROWSER_TARGETS:
            if tpl.get("kind") != "quote":
                continue
            targets.append({"name": f"{tpl['name']}:{row['code']}", "kind": "quote",
                            "code": row["code"], "label": row["label"],
                            "url": tpl["url"].format(sec=sec, yahoo_sec=yahoo_sec)})
    if include_market:
        market_tpl = next((t for t in BROWSER_TARGETS if t.get("kind") == "market"), None)
        if market_tpl:
            targets.append({"name": market_tpl["name"], "kind": "market", "url": market_tpl["url"]})
    return targets


# ------------------------------------------------------------
# 编排：四路取数 → 合并 → 归一化结果
# ------------------------------------------------------------
def _quote_row(spec, quote, source):
    row = {"label": spec["label"], "code": spec["code"], "price": quote.get("price"),
           "change_pct": quote.get("change_pct"), "volume": quote.get("volume"),
           "turnover_yi": quote.get("turnover_yi"), "currency": quote.get("currency") or "HKD",
           "as_of": quote.get("as_of"), "source": source, "via": quote.get("via") or source}
    return row


def fetch_hk_overseas(request=None, *, use_browser=None, now=None, crosscheck=None,
                      browser_targets=None):
    """读取港股境外数据源（指标 + 个股 + 市场层），返回 pipeline 同构的来源 dict。

    参数：
      request        —— 取数函数 (url, timeout=, is_json=) → dict/str/None，默认用 pipeline.safe_request
      use_browser    —— 是否启用 stealth 浏览器这一路；None → 读 OCTOPUS_HK_BROWSER
      crosscheck     —— 是否用 Stooq 交叉校验主源；None → 读 OCTOPUS_HK_CROSSCHECK
      browser_targets—— 自定义浏览器目标（测试用）
      now            —— 注入当前时间（测试用）
    """
    print("\n🇭🇰 正在抓取港股境外数据源（Yahoo / Stooq / HKEX / 可选浏览器）...")
    if use_browser is None:
        use_browser = _env_flag("OCTOPUS_HK_BROWSER", False)
    if crosscheck is None:
        crosscheck = _env_flag("OCTOPUS_HK_CROSSCHECK", False)
    today = _today(now)

    sources = []
    indices, stocks = [], []
    errors = []

    def _note(name, tier, status, count=0, as_of=None, note=""):
        sources.append({"name": name, "tier": tier, "status": status, "count": count,
                        "as_of": as_of, "note": note})

    # ---- ①② 指数 + 个股：Yahoo 主源 → Stooq 备用源 ----
    #      熔断：某一路连续失败 HK_CIRCUIT_FAILS 次即本轮跳过该路（离线 / 被墙时不至于
    #      让 11 只标的 × 2 个镜像逐个超时，把整条流水线拖到超时上限）；恢复后自动重试。
    HK_CIRCUIT_FAILS = 3
    yahoo_ok = yahoo_fail = 0
    stooq_ok = 0
    yahoo_streak = stooq_streak = 0
    yahoo_dead = stooq_dead = False
    cross_rows, cross_bad = [], []
    for group, spec_list, out in (("index", HK_INDEX_SPECS, indices),
                                  ("stock", _basket(), stocks)):
        for spec in spec_list:
            if group == "index":
                slot = {"label": spec["label"], "code": spec["code"]}
                stooq_sym = spec.get("stooq")
            else:
                code, stooq_sym, label = spec
                slot = {"label": label, "code": code}
            served = None
            quote = None
            if not yahoo_dead:
                data, hit_url, _errs = _first_ok(request, yahoo_chart_urls(slot["code"]),
                                                 timeout=10)
                if data:
                    quote = parse_yahoo_chart(data)
                    if quote:
                        served = "yahoo"
                        yahoo_ok += 1
                        yahoo_streak = 0
                if not quote:
                    yahoo_fail += 1
                    yahoo_streak += 1
                    if yahoo_streak >= HK_CIRCUIT_FAILS:
                        yahoo_dead = True
                        print(f"  ⚠️ [hk_overseas] Yahoo 连续 {yahoo_streak} 次失败，本轮跳过该路（熔断）")
            if quote is None:
                if stooq_sym and not stooq_dead:
                    sdata, _surl, _serrs = _first_ok(request, stooq_history_urls(stooq_sym),
                                                     is_json=False, timeout=10)
                    if sdata:
                        quote = parse_stooq_history_csv(sdata)
                        if quote:
                            served = "stooq"
                            stooq_ok += 1
                            stooq_streak = 0
                    if not quote:
                        stooq_streak += 1
                        if stooq_streak >= HK_CIRCUIT_FAILS:
                            stooq_dead = True
                            print(f"  ⚠️ [hk_overseas] Stooq 连续 {stooq_streak} 次失败，本轮跳过该路（熔断）")
            if quote is None:
                errors.append(f"{slot['label']}（{slot['code']}）主备均未取到")
                continue
            out.append(_quote_row(slot, quote, served))
            # 交叉校验（可选）：主源成功时再取一次 Stooq，价格偏差 >1.5% 才记
            if crosscheck and served == "yahoo" and stooq_sym:
                sdata, _u, _e = _first_ok(request, stooq_history_urls(stooq_sym),
                                          is_json=False, timeout=10)
                s_quote = parse_stooq_history_csv(sdata) if sdata else None
                if s_quote and s_quote.get("price"):
                    diff = abs(s_quote["price"] - quote["price"]) / quote["price"] * 100
                    cross_rows.append((slot["label"], quote["price"], s_quote["price"], diff))
                    if diff > 1.5:
                        cross_bad.append(f"{slot['label']} 差 {diff:.1f}%")

    _note("Yahoo Finance Chart（境外·主源）", 1,
          "success" if yahoo_ok else "failed", yahoo_ok,
          max((r.get("as_of") or "" for r in indices + stocks), default=None),
          f"{yahoo_ok} 项成功 / {yahoo_fail} 项失败" + ("（连续失败已熔断）" if yahoo_dead else ""))
    if stooq_ok or crosscheck or stooq_dead:
        _note("Stooq（境外·备用/校验）", 2,
              "success" if stooq_ok else ("empty" if crosscheck else "failed"), stooq_ok,
              None, f"补位 {stooq_ok} 项"
              + (f" · 交叉校验 {len(cross_rows)} 项" if cross_rows else "")
              + ("（连续失败已熔断）" if stooq_dead else ""))

    # ---- ③ 市场层：HKEX 官方页（HTTP 优先；失败且开了浏览器 → 渲染后再解析）----
    market = {}
    hkex_text = _get(request, HKEX_STATS_URL, is_json=False, timeout=20)
    hkex_stats = parse_market_stats_text(hkex_text) if hkex_text else {}
    hkex_via = None
    if hkex_stats:
        market = {**hkex_stats, "source": "hkex-http", "via": "http"}
        hkex_via = "http"

    # ---- ④ 浏览器一路（可选）：补个股成交额 / 市场成交 / 未取到的品种 ----
    browser_used = 0
    browser_note = ""
    if use_browser:
        targets = browser_targets or browser_targets_for(indices, stocks,
                                                         include_market=not bool(hkex_stats))
        probe = browser_probe(targets)
        if not probe.get("ok"):
            browser_note = probe.get("error") or "浏览器不可用"
            _note("stealth 浏览器（patchright）", 4, "failed", 0, None, browser_note)
        else:
            parsed_any = 0
            for rec in probe.get("results") or []:
                if not rec.get("ok"):
                    continue
                text = rec.get("text") or ""
                if rec.get("kind") == "market":
                    stats = parse_market_stats_text(text) or parse_market_stats_text(
                        re.sub(r"\s+", " ", text))
                    if stats and not market:
                        market = {**stats, "source": f"browser:{site}"}
                        hkex_via = f"browser:{site}"
                        parsed_any += 1
                    continue
                site = str(rec.get("name") or "").split(":")[0] or "browser"
                code = rec.get("code")
                parsed = parse_browser_quote_text(text)
                if not parsed or not code:
                    continue
                row = next((r for r in indices + stocks if r["code"] == code), None)
                if row is None:
                    continue
                # 浏览器只补「主源没给的字段」，绝不覆盖已有数字，避免两路口径打架。
                filled = False
                if row.get("turnover_yi") is None and parsed.get("turnover_yi") is not None:
                    row["turnover_yi"] = parsed["turnover_yi"]
                    filled = True
                if row.get("change_pct") is None and parsed.get("change_pct") is not None:
                    row["change_pct"] = parsed["change_pct"]
                    filled = True
                if filled:
                    row["browser_source"] = f"browser:{site}"
                    parsed_any += 1
            browser_used = parsed_any
            _note("stealth 浏览器（patchright）", 4, "success" if parsed_any else "empty",
                  parsed_any, None,
                  f"{len(probe.get('results') or [])} 页渲染，{parsed_any} 项补充成功"
                  if parsed_any else "页面已渲染但未解析出可用数字（标注暂缺，不猜测）")
    else:
        _note("stealth 浏览器（patchright）", 4, "skipped", 0, None,
              "未开启（OCTOPUS_HK_BROWSER=1 且安装 Node + patchright 后启用）")

    if market:
        _note("HKEX 官方统计（境外）", 3, "success", 1, market.get("as_of"),
              f"市场成交额 {market.get('turnover_yi'):.2f} 亿港元（{hkex_via}）")
    elif hkex_text:
        _note("HKEX 官方统计（境外）", 3, "empty", 0, None,
              "页面已取到，但未解析出「数字+单位」成对的成交额（标注暂缺，不猜测）")
    else:
        _note("HKEX 官方统计（境外）", 3, "failed", 0, None, "页面请求失败")

    # ---- 汇总 ----
    all_rows = indices + stocks
    dates = sorted({r.get("as_of") for r in all_rows if r.get("as_of")})
    content_date = dates[-1] if dates else (market.get("as_of") if market else None)
    status = "success" if all_rows else "unavailable"
    result = {
        "source": HK_OVERSEAS_SOURCE,
        "status": status,
        "is_today": bool(content_date and content_date == today),
        "content_date": content_date,
        "snapshot": True,                      # 行情快照：不作为「当天发布内容」单独放行推送
        "indices": indices,
        "stocks": stocks,
        "market": market,
        "sources": sources,
        "crosscheck": {"rows": cross_rows, "bad": cross_bad} if crosscheck else {},
        "error": "；".join(errors[:3]) if errors else None,
    }
    got = len(all_rows)
    print(f"  {'✅' if got else '⚠️'} 港股境外数据源：指数 {len(indices)} / 个股 {len(stocks)} 项"
          + (f" · 行情日 {content_date}" if content_date else " · 行情日暂缺")
          + (f" · 市场成交额 {market['turnover_yi']:.2f} 亿港元" if market else "")
          + (f" · 浏览器补充 {browser_used} 项" if use_browser else ""))
    if errors:
        print("  ⚠️ 未取到：" + "、".join(errors[:4]))
    return result


# ------------------------------------------------------------
# CLI（人工核查用）：python3 output/hk_overseas.py [--browser] [--json]
# ------------------------------------------------------------
def _cli(argv):
    want_json = "--json" in argv
    use_browser = "--browser" in argv
    res = fetch_hk_overseas(use_browser=use_browser)
    if want_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    print(f"\n来源：{res['source']} · 状态：{res['status']} · 行情日：{res['content_date']}")
    for row in res["indices"] + res["stocks"]:
        print(f"  {row['label']:<12} {_fmt_num(row['price']):>12} "
              f"{_fmt_num(row['change_pct'], 2):>8}%  [{row['source']}] {row['as_of'] or '—'}")
    if res.get("market"):
        print(f"  市场成交额：{res['market']['turnover_yi']:.2f} 亿港元（{res['market'].get('source')}）")
    for s in res["sources"]:
        print(f"  · {s['name']}：{s['status']} {s['note']}")
    return 0 if res["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
