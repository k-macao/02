#!/usr/bin/env python3
"""
🐙 章鱼 AI · 全网多模型协同 · 每日财经日报流水线
每次运行都重新抓取全网最新数据 → 分析 → 生成 → 当天检验 → 推送

核心规则（2026-08-01 新版，当天修订）：
  1. 没有数据的区块不出现在页面里，也不推送空内容。
  2. 每次生成后先做「当天内容检验」：每个数据源标注 ✅当天 / 🕓非当天 / ⚠️无数据，
     只有当「至少一个数据源含当天内容」时才自动推送日报；否则不推日报，
     但会推一条「纯文本告警」说明原因与各来源状态，避免彻底沉默。
  3. 页面内容包含「港股名家频道」区块：香港股评人/财经平台的 YouTube 与通用 RSS
     抓取（无需 API Key），每频道列出最新 3 条；需登录平台明确标注「暂缺」及原因，
     不伪造内容。
  4. 支持手动推送：--manual / manual_push.sh / GitHub Actions 手动按钮（可勾选 force_push），
     内容非当天时可用 --force-push 强制推送（谨慎）。
  5. 任何「应当推送却失败」的情况（PushPlus 报错、未配置 PUSHPLUS_TOKEN、网络异常，
     含「检验未通过」告警发送失败）都以退出码 1 结束：GitHub Actions 会显红并触发
     失败通知，杜绝“推送失败却显示成功”的假象。
  6. PushPlus 推送对「发送频繁 / 稍后再试 / 服务器繁忙 / 网络异常 / HTTP 429·5xx」
     等可恢复错误按 10s→30s→60s 退避自动重试（最多 4 次）；对「当日配额已达上限、
     token 失效、内容违规」等重试无意义的错误不重试、立即失败。日报多次推送仍失败时
     会再发一条纯文本「推送失败」告警（含 PushPlus 返回的 code/msg 与处理建议），
     让微信侧也能感知原因，而不是只看到 Actions 变红。
  7. 推送标题带当日时分（如 08/01 18:30）：同一天多次手动推送不会因标题完全重复
     触发反垃圾/去重拦截，也便于区分每一次推送。
  8. PushPlus 内容上限（账号已升级会员，默认按 10 万字；可用环境变量
     PUSHPLUS_MAX_CONTENT_CHARS 覆盖）。日报 HTML 超过上限时，发送前会按完整标签边界
     截断并闭合所有标签、末尾附「完整版」链接，保证微信端排版正常；磁盘上的日报文件
     始终保留完整版。

退出码约定：
  0 = 正常完成（含 --no-push / --dry-run 等有意的跳过，或检验未通过但告警已送达）；
  1 = 应当推送却失败，或用法错误。

用法:
  python3 output/pipeline.py                  # 全流程（当天检验通过才推送）
  python3 output/pipeline.py --no-push        # 只生成，不推送
  python3 output/pipeline.py --dry-run        # 采集+预览，不推送
  python3 output/pipeline.py -o custom.html   # 指定输出路径
  python3 output/pipeline.py --manual         # 手动推送模式
  python3 output/pipeline.py --manual --force-push   # 手动强制推送（内容非当天）
  python3 output/pipeline.py --push-only              # 推送实际最后更新的一份日报（当天检验）
  python3 output/pipeline.py --push-only path/to/report.html
  python3 output/pipeline.py --list           # 列出日报

退出码：0 = 正常完成；1 = 应当推送却失败 / 用法错误（GitHub Actions 据此标红）。
"""
import os
import sys
import json
import time
import argparse
import random
import re
import glob
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    print("❌ 缺少依赖 requests，请运行: pip install requests")
    sys.exit(1)

# ============================================================
# 全局配置
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = SCRIPT_DIR

# 时区
CST = timezone(timedelta(hours=8))  # 北京时间 / 澳门时间（东八区）

# PushPlus 配置
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_URL = "https://www.pushplus.plus/send"
# PushPlus 内容长度上限：实名用户 2 万字、会员用户 10 万字（账号已升级会员，默认按 10 万）。
# 超过上限的内容会被平台截断，截断点常落在标签中间，导致微信端整页排版崩坏
# （表现为整页只剩浅灰背景、正文缺失）。因此发送前先按完整标签边界截断并闭合标签，
# 末尾附「完整版」链接；磁盘上的日报文件始终保留完整版。
# 如账号额度变化，可用环境变量 PUSHPLUS_MAX_CONTENT_CHARS 覆盖（如 20000 / 100000）。
PUSHPLUS_MAX_CONTENT_CHARS = int(os.environ.get("PUSHPLUS_MAX_CONTENT_CHARS", "100000"))

# 请求头
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ------------------------------------------------------------
# 港股名家频道（内容渠道配置，2026-08-02 起按用户指定列表）
# 每个频道可配置：
#   kind = "youtube"  → YouTube 频道，通过公开 RSS 抓取（无需 API Key），
#                       填 channel_id（最稳）或 handle（运行时自动解析，失败标记暂缺）
#   kind = "rss"      → 通用 RSS / Atom 源（如 Medium、Substack）
#   kind = "manual"   → 需登录 / 平台限制，暂无法自动抓取（页面标注「暂缺」及原因，不伪造内容）
# 每频道在日报中列出最新 CHANNEL_TOP_N 条内容。
# 需要增删频道或接入新平台时直接改这个列表即可。
# ------------------------------------------------------------
CHANNEL_TOP_N = 3

HK_CHANNELS = [
    # ── 港股股评人 YouTube 频道（可自动抓取）─────────────────
    {"name": "郭思治（郭Sir）",
     "desc": "香港著名股評人，專注大盤技術走勢。",
     "kind": "youtube", "handle": "@KwokSirFinance"},

    # ── 需登录 / 暂未提供可抓取源（明确标注暂缺）────────────
    {"name": "曾廣標（股票分析）",
     "desc": "資深股評人，專注細價股與價值挖掘。",
     "kind": "manual",
     "note": "暂无官方可抓取频道；旧视频散见于「港股直播室 @hongkongstock」（2023 年后未更新）"},
    {"name": "陸羽仁（金融肉搏戰）",
     "desc": "老牌專欄，分析港股大局與政經關係。",
     "kind": "manual",
     "note": "信報專欄，非 YouTube；暂不支持自动抓取"},
    {"name": "青姐（胡孟青）",
     "desc": "風格辛辣，直擊港股市場痛點與散戶心態。",
     "kind": "manual",
     "note": "暂无官方频道；节目「胡孟青拆局」发布于 AASTOCKS 频道（@AASTOCKS_AATV）"},
    {"name": "智通財經App（微信公众号）",
     "desc": "每日推送港股早報與板塊機會。",
     "kind": "manual",
     "note": "微信公众号需登录，暂不支持自动抓取"},
    {"name": "港股那點事（格隆匯）（微信公众号）",
     "desc": "深度剖析港股上市公司實力。",
     "kind": "manual",
     "note": "微信公众号需登录，暂不支持自动抓取"},
    {"name": "球友大白（雪球 KOL）",
     "desc": "長線跟蹤港股高股息、藍籌股。",
     "kind": "manual",
     "note": "雪球需登录 / 反爬限制，暂不支持自动抓取"},
    {"name": "香港投資筆記（Medium）",
     "desc": "獨立分析師發表深度個股研究。",
     "kind": "rss", "feed_url": "",
     "note": "请提供 Medium 地址后接入 RSS"},
    {"name": "港股策略通訊（Substack）",
     "desc": "付費/免費的深度行業趨勢報告。",
     "kind": "rss", "feed_url": "",
     "note": "请提供 Substack 地址后接入 RSS"},
    {"name": "港股交易員（微博大V）",
     "desc": "實時更新盤中異動與傳聞。",
     "kind": "manual",
     "note": "微博需登录 / 反爬限制，暂不支持自动抓取"},

    # ── 第二批（2026-08-02 追加，用户指定）──────────────────
    {"name": "施凌部署",
     "desc": "結合宏觀經濟與技術分析的知名財經頻道；施凌部署為「我要做富翁」旗下品牌，於該官方頻道發布。",
     "kind": "youtube", "handle": "@Money-Tab"},
    {"name": "BofA Global Research（美銀研究）",
     "desc": "解讀大行對港股策略的官方影音；BofA Global Research 內容於 Bank of America 官方頻道發布（Must Read Research 系列）。",
     "kind": "youtube", "handle": "@BankofAmerica"},
    {"name": "秒投（ShareNews / StockViva）",
     "desc": "邀請多位香港股評人進行直播分析。",
     "kind": "youtube", "handle": "@StockViva"},
    {"name": "C基金 - 李浩德",
     "desc": "基金經理視角，分析港股大盤與科技股。",
     "kind": "youtube", "handle": "@CFund_Channel"},
    {"name": "Finance730",
     "desc": "探討香港財經、地產及股市走勢的專業網媒。",
     "kind": "youtube", "handle": "@Finance730hk"},
    {"name": "紅猴（Red Monkey）",
     "desc": "深度分析港股價值投資與公司基本面。",
     "kind": "manual",
     "note": "未找到独立官方频道；其视频散见于「成家網上投資課程」等第三方频道（多为 2022 年前旧内容）"},
    {"name": "米高（Michael）的財經頻道",
     "desc": "專注港股短線操作與期指分析。",
     "kind": "manual",
     "note": "未能在 YouTube 检索到明确的「米高 Michael 財經頻道」，请提供频道链接或 handle 后接入"},
    {"name": "小斯財經",
     "desc": "用深入淺出的方式講解港股與新股申購。",
     "kind": "manual",
     "note": "未能在 YouTube 检索到明确的「小斯財經」频道，请提供频道链接或 handle 后接入"},
    {"name": "智富同學會",
     "desc": "分享技術指標與港股實戰策略。",
     "kind": "manual",
     "note": "未检索到「智富同學會」独立频道；疑似相关频道「智富財經 Invest Smarter @investsmarter536」，如需接入请确认"},
    {"name": "港股研究社（Bilibili）",
     "desc": "面向內地投資者的港股解讀視頻（B站 UP 主，UID 613310838）。",
     "kind": "rss", "feed_url": "https://rsshub.app/bilibili/user/video/613310838",
     "note": "通过 RSSHub 抓取 Bilibili 投稿；如公共实例被限流，可更换其他 RSSHub 实例"},
]

YT_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}

# ============================================================
# 工具函数
# ============================================================
def _now():
    """返回当前北京时间字符串"""
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _today_str():
    """返回今天日期字符串 YYYYMMDD"""
    return datetime.now(CST).strftime("%Y%m%d")


def _today_display():
    """返回今天的日期字符串 YYYY-MM-DD"""
    return datetime.now(CST).strftime("%Y-%m-%d")


def _date_display():
    """返回中文日期显示"""
    now = datetime.now(CST)
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{now.year}年{now.month}月{now.day}日 · {weekdays[now.weekday()]}"


def _esc(s):
    """HTML 转义"""
    if not s:
        return ""
    return (s.replace("&", "&amp;")
              .replace("<", "&lt;")
              .replace(">", "&gt;")
              .replace('"', "&quot;")
              .replace("'", "&#x27;"))


def _cst_from_iso(iso_str):
    """把 ISO8601 时间转为北京时间 datetime；失败返回 None。"""
    if not iso_str:
        return None
    try:
        iso = iso_str.replace("Z", "+00:00")
        return datetime.fromisoformat(iso).astimezone(CST)
    except Exception:
        return None


def _date_is_today(dt):
    """判断某个 datetime 是否属于今天（北京时间）。"""
    return bool(dt and dt.strftime("%Y%m%d") == _today_str())


def safe_request(url, headers=None, params=None, timeout=15, is_json=True):
    """安全请求，失败返回 None"""
    try:
        h = {**DEFAULT_HEADERS, **(headers or {})}
        resp = requests.get(url, headers=h, params=params, timeout=timeout)
        resp.raise_for_status()
        if is_json:
            return resp.json()
        return resp.text
    except Exception as e:
        print(f"  ⚠️ 请求失败 [{url[:60]}...]: {e}")
        return None


# ============================================================
# 数据新鲜度与实时行情
# ============================================================
def _source_result(source, status, is_today=False, content_date=None, **payload):
    """统一记录来源、抓取时间、当天标记和失败状态；绝不把历史文案伪装成实时数据。

    is_today      —— 该来源的内容是否属于「当天」（按北京时间判断）
    content_date  —— 该来源最新内容的日期（如最后收盘日 / 最新视频发布日），用于展示
    """
    return {
        "source": source, "status": status, "fetched_at": _now(),
        "is_today": bool(is_today), "content_date": content_date,
        **payload,
    }


def _source_note(item):
    """供 HTML 使用的数据来源状态。"""
    if item.get("status") == "success":
        return f"✅ {item.get('source', '数据源')} · 抓取于 {item.get('fetched_at', '—')}"
    detail = _esc(item.get("error", "暂时不可用"))
    return f"⚠️ {item.get('source', '数据源')} 数据暂缺（{detail}）· 抓取于 {item.get('fetched_at', '—')}"


def fetch_market_snapshot():
    """从 Yahoo Chart API 获取实际最新收盘/最新报价，不提供历史数字兜底。"""
    print("📡 正在抓取全球/A股实时行情...")
    specs = [
        ("道琼斯指数", "%5EDJI"), ("标普500", "%5EGSPC"), ("纳斯达克", "%5EIXIC"),
        ("WTI 原油", "CL=F"), ("微软 MSFT", "MSFT"), ("Meta META", "META"),
        ("上证指数", "000001.SS"), ("深证成指", "399001.SZ"),
        ("创业板指", "399006.SZ"), ("科创50", "000688.SS"),
    ]
    quotes, failures, last_dates = {}, [], []
    for label, symbol in specs:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
        data = safe_request(url)
        try:
            result = data["chart"]["result"][0]
            closes = [x for x in result["indicators"]["quote"][0]["close"] if x is not None]
            if len(closes) < 2:
                raise ValueError("报价记录不足")
            price, previous = closes[-1], closes[-2]
            quotes[label] = {"price": price, "change_pct": (price / previous - 1) * 100,
                             "currency": result.get("meta", {}).get("currency", "")}
            # 最后收盘日期（用于当天检验；非交易时段为最近交易日）
            ts_list = result.get("timestamp") or []
            if ts_list:
                last = datetime.fromtimestamp(ts_list[-1], CST).strftime("%Y-%m-%d")
                last_dates.append(last)
        except (KeyError, TypeError, IndexError, ValueError, ZeroDivisionError) as exc:
            failures.append(f"{label}: {exc}")
    status = "success" if quotes else "unavailable"
    content_date = max(last_dates) if last_dates else None
    is_today = content_date == _today_display()
    if quotes:
        print(f"  ✅ 成功抓取 {len(quotes)}/{len(specs)} 个实时行情（数据日期 {content_date}）")
    else:
        print("  ⚠️ 实时行情暂不可用；日报将明确显示数据暂缺")
    return _source_result("Yahoo Finance Chart", status,
                          is_today=is_today, content_date=content_date,
                          quotes=quotes,
                          error="；".join(failures[:2]) or None,
                          partial=len(quotes) != len(specs))


def _quote_value(market, label, precision=2):
    quote = market.get("quotes", {}).get(label)
    if not quote:
        return '<span style="color:#888;">数据暂缺</span>', "#888"
    price = quote["price"]
    pct = quote["change_pct"]
    color = C_GREEN if pct >= 0 else C_RED
    # 股指/原油精度不同不影响新鲜度；保留可审计的真实数值和涨跌幅。
    return (f'<span style="color:{color};">{price:,.{precision}f} {pct:+.2f}%</span>', color)


# ============================================================
# 数据源 1：Reddit WSB 热议
# ============================================================
def fetch_wsb():
    """抓取 r/wallstreetbets 热门帖子，提取股票提及"""
    print("📡 正在抓取 Reddit WSB...")

    url = "https://www.reddit.com/r/wallstreetbets/hot.json"
    params = {"limit": 100}
    headers = {**DEFAULT_HEADERS, "Accept": "application/json"}

    data = safe_request(url, headers=headers, params=params)

    stocks = []
    stock_mentions = {}
    post_utcs = []

    if data and "data" in data and "children" in data["data"]:
        for child in data["data"]["children"]:
            post = child.get("data", {})
            title = post.get("title", "")
            selftext = post.get("selftext", "")
            text = title + " " + selftext
            created = post.get("created_utc")
            if created:
                post_utcs.append(created)

            # 排除常见非股票代码
            exclude_words = {"THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER",
                           "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS", "HOW",
                           "ITS", "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "BOY", "DID",
                           "LET", "PUT", "SAY", "SHE", "TOO", "USE", "DD", "YOLO", "WSB",
                           "FDA", "SEC", "FED", "GDP", "PCE", "CPI", "ETF", "IPO", "AI", "USA",
                           "US", "UK", "EU", "CEO", "CFO", "COO", "CTO", "EV", "TSLA", "SPY",
                           "QQQ", "SPX", "DOW", "NYSE", "NASDAQ", "OTC", "ATH", "ITM",
                           "USD", "EUR", "GBP", "BTC", "ETH", "NFT", "DeFi", "S&P",
                           "EST", "EOD", "PT", "RSI", "MACD", "EPS", "P/E", "EBITDA", "TTM",
                           "Q1", "Q2", "Q3", "Q4", "FY", "YTD", "MoM", "YoY", "APR", "IRR",
                           "IMO", "IMHO", "TBH", "BTBC", "FWIW", "ELI5", "TL;DR", "EDIT",
                           "SOURCE", "PERMALINK", "CROSSPOST", "REPOST"}

            # 匹配 $SYMBOL 或纯大写代码
            symbols = re.findall(r'\$([A-Z]{1,5})\b', text)
            symbols += re.findall(r'\b([A-Z]{2,5})\b', text)

            for sym in symbols:
                if sym not in exclude_words and len(sym) >= 2:
                    stock_mentions[sym] = stock_mentions.get(sym, 0) + 1

        # 排序取 Top 10
        sorted_stocks = sorted(stock_mentions.items(), key=lambda x: x[1], reverse=True)[:10]
        for symbol, mentions in sorted_stocks:
            stocks.append({"symbol": symbol, "name": "", "mentions": mentions})

    if not stocks:
        print("  ⚠️ Reddit 暂不可用，不显示历史兜底榜单")
        return _source_result("Reddit WSB", "unavailable", stocks=[], error="未取得有效帖子")

    newest_dt = datetime.fromtimestamp(max(post_utcs), CST) if post_utcs else None
    content_date = newest_dt.strftime("%Y-%m-%d") if newest_dt else None
    print(f"  ✅ 成功抓取到 {len(stocks)} 只热门股票（最新帖 {content_date}）")
    return _source_result("Reddit WSB", "success",
                          is_today=_date_is_today(newest_dt), content_date=content_date,
                          stocks=stocks)


# ============================================================
# 数据源 2：Yahoo Finance 头条
# ============================================================
def fetch_yahoo_headlines():
    """抓取 Yahoo Finance 热门新闻标题"""
    print("📡 正在抓取 Yahoo Finance 头条...")

    headlines = []

    # 尝试抓取新闻页面
    news_url = "https://finance.yahoo.com/topic/stock-market-news/"
    html = safe_request(news_url, is_json=False)

    if html:
        # 提取标题
        titles = re.findall(r'"headline":"([^"]+)"', html)
        if not titles:
            titles = re.findall(r'<h3[^>]*>([^<]{20,200})</h3>', html)

        for t in titles[:15]:
            clean = t.encode().decode('unicode_escape') if '\\u' in t else t
            clean = re.sub(r'<[^>]+>', '', clean).strip()
            if clean and len(clean) > 10:
                headlines.append(clean)

    # 兜底 RSS
    if not headlines:
        rss_url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US"
        rss_html = safe_request(rss_url, is_json=False)
        if rss_html:
            items = re.findall(r'<title>(.*?)</title>', rss_html)
            for item in items[1:10]:
                clean = re.sub(r'<[^>]+>', '', item).strip()
                if clean:
                    headlines.append(clean)

    if not headlines:
        print("  ⚠️ Yahoo 暂不可用，不显示历史兜底头条")
        return _source_result("Yahoo Finance News", "unavailable", headlines=[], error="未取得有效新闻")
    print(f"  ✅ 成功抓取到 {len(headlines)} 条头条（本次抓取 = 当天内容）")
    return _source_result("Yahoo Finance News", "success",
                          is_today=True, content_date=_today_display(),
                          headlines=headlines[:8])


# ============================================================
# 数据源 3：A股资讯（新浪财经）
# ============================================================
def fetch_sina_headlines():
    """抓取新浪财经 A 股资讯"""
    print("📡 正在抓取 A 股资讯...")

    headlines = []

    # 新浪滚动新闻 API
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    params = {
        "pageid": "153",
        "lid": "2509",
        "num": "20",
        "page": "1",
    }

    data = safe_request(url, params=params)

    if data and "result" in data and "data" in data["result"]:
        for item in data["result"]["data"][:10]:
            title = item.get("title", "") or item.get("intro", "")
            if title:
                headlines.append(title.strip())

    # 首页兜底
    if not headlines:
        sina_url = "https://finance.sina.com.cn/"
        html = safe_request(sina_url, is_json=False)
        if html:
            titles = re.findall(r'target="_blank"[^>]*>([^<]{10,100})</a>', html)
            for t in titles[:10]:
                clean = t.strip()
                if clean and not clean.startswith("http"):
                    headlines.append(clean)

    if not headlines:
        print("  ⚠️ 新浪财经暂不可用，不显示历史兜底资讯")
        return _source_result("新浪财经", "unavailable", headlines=[], error="未取得有效资讯")
    print(f"  ✅ 成功抓取到 {len(headlines)} 条 A 股资讯（本次抓取 = 当天内容）")
    return _source_result("新浪财经", "success",
                          is_today=True, content_date=_today_display(),
                          headlines=headlines[:5])


# ============================================================
# 数据源 4：韩股 & 半导体资讯
# ============================================================
def fetch_kospi_headlines():
    """抓取韩股和半导体相关资讯"""
    print("📡 正在抓取韩股 & 半导体资讯...")

    headlines = []

    # Naver 财经 API
    url = "https://api.stock.naver.com/news/world/stock/KOSPI"
    params = {
        "pageSize": "20",
        "page": "1",
    }

    data = safe_request(url, params=params)

    if data and isinstance(data, list):
        for item in data[:10]:
            title = item.get("title", "") or item.get("content", "")
            if title:
                clean = re.sub(r'<[^>]+>', '', title).strip()
                if clean:
                    headlines.append(clean)

    # Yahoo 韩股新闻兜底
    if not headlines:
        kr_url = "https://finance.yahoo.com/quote/%5EKS11/news/"
        html = safe_request(kr_url, is_json=False)
        if html:
            titles = re.findall(r'"headline":"([^"]+)"', html)
            for t in titles[:10]:
                clean = t.encode().decode('unicode_escape') if '\\u' in t else t
                headlines.append(clean.strip())

    if not headlines:
        print("  ⚠️ Naver/Yahoo 韩股资讯暂不可用，不显示历史兜底资讯")
        return _source_result("Naver / Yahoo Korea", "unavailable", headlines=[], error="未取得有效资讯")
    print(f"  ✅ 成功抓取到 {len(headlines)} 条韩股资讯（本次抓取 = 当天内容）")
    return _source_result("Naver / Yahoo Korea", "success",
                          is_today=True, content_date=_today_display(),
                          headlines=headlines[:5])


# ============================================================
# 数据源 5：港股名家频道（YouTube / 通用 RSS / 需登录平台）
# ============================================================
def resolve_channel_id(channel):
    """解析频道的 channel_id：优先使用配置的 channel_id，否则通过 handle 页面解析。"""
    cid = channel.get("channel_id")
    if cid:
        return cid
    handle = (channel.get("handle") or "").lstrip("@")
    if not handle:
        return None
    html = safe_request(f"https://www.youtube.com/@{handle}", is_json=False, timeout=12)
    if not html:
        return None
    m = re.search(r'"channelId":"(UC[0-9A-Za-z_-]{22})"', html)
    if m:
        return m.group(1)
    m = re.search(r'"externalId":"(UC[0-9A-Za-z_-]{22})"', html)
    return m.group(1) if m else None


def _channel_item(title, url, pub_raw):
    """把一条频道内容的标题/链接/发布时间整理成统一结构（北京时间 + 是否当天）。"""
    pub_cst = _cst_from_iso(pub_raw)
    if pub_cst is None:  # 兼容 RSS 2.0 的 RFC 2822 格式（如 Fri, 01 Aug 2026 12:00:00 +0800）
        try:
            from email.utils import parsedate_to_datetime
            pub_cst = parsedate_to_datetime(pub_raw).astimezone(CST)
        except Exception:
            pub_cst = None
    return {
        "title": title,
        "url": url,
        "published": pub_raw,
        "published_cst": pub_cst.strftime("%Y-%m-%d %H:%M") if pub_cst else "—",
        "is_today": _date_is_today(pub_cst),
    }


def _parse_rss_items(xml_text, limit=8):
    """解析通用 RSS 2.0 / Atom 源，返回 [{title,url,published_cst,is_today}, ...]。"""
    items = []
    try:
        root = ET.fromstring(xml_text or "")
    except Exception:
        return []
    # RSS 2.0
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub = (item.findtext("pubDate")
                       or item.findtext("dc:date", namespaces={"dc": "http://purl.org/dc/elements/1.1/"})
                       or "")
                if title:
                    items.append(_channel_item(title, link, pub))
                if len(items) >= limit:
                    break
    # Atom
    elif root.tag.endswith("feed"):
        for entry in root.findall("a:entry", YT_NS):
            title = (entry.findtext("a:title", "", YT_NS) or "").strip()
            link = ""
            for ln in entry.findall("a:link", YT_NS):
                if (ln.get("rel") or "alternate") == "alternate":
                    link = ln.get("href") or ""
                    break
            pub = (entry.findtext("a:published", "", YT_NS)
                   or entry.findtext("a:updated", "", YT_NS) or "")
            if title:
                items.append(_channel_item(title, link, pub))
            if len(items) >= limit:
                break
    return items


def fetch_hk_channels():
    """抓取「港股名家频道」的最新内容。

    - kind="youtube"：YouTube 频道 RSS（无需 API Key），返回最新视频；
    - kind="rss"    ：通用 RSS / Atom 源（Medium、Substack 等）；
    - kind="manual" ：需登录 / 未配置来源，放入 unsupported（页面标注「暂缺」及原因，
                      绝不伪造内容）。

    返回 _source_result：channels=已抓取频道、unsupported=需登录/未配置频道。
    """
    print("📡 正在抓取港股名家频道...")
    channels, unsupported, failures = [], [], []
    for ch in HK_CHANNELS:
        name = ch.get("name", "?")
        kind = ch.get("kind", "youtube")

        if kind == "manual":
            unsupported.append({"name": name, "desc": ch.get("desc", ""),
                                "note": ch.get("note", "平台需登录，暂不支持自动抓取")})
            continue

        if kind == "rss":
            feed_url = (ch.get("feed_url") or "").strip()
            if not feed_url:
                unsupported.append({"name": name, "desc": ch.get("desc", ""),
                                    "note": ch.get("note", "未配置 feed 地址")})
                continue
            xml_text = safe_request(feed_url, is_json=False, timeout=12)
            items = _parse_rss_items(xml_text, limit=8)
            if items:
                channels.append({
                    "name": name, "desc": ch.get("desc", ""), "source": "RSS",
                    "url": feed_url, "videos": items,
                    "is_today": any(v["is_today"] for v in items),
                    "newest_date": next((v["published_cst"] for v in items if v["is_today"]),
                                        items[0]["published_cst"]),
                })
            else:
                msg = "自动抓取失败（源可能需登录/被限流，或地址无效），暂缺"
                unsupported.append({"name": name, "desc": ch.get("desc", ""), "note": msg})
                failures.append(f"{name}: {msg}")
            continue

        # kind == "youtube"
        cid = resolve_channel_id(ch)
        if not cid:
            msg = "无法解析频道 ID（handle 可能不存在或页面结构变化），暂缺"
            unsupported.append({"name": name, "desc": ch.get("desc", ""), "note": msg})
            failures.append(f"{name}: {msg}")
            continue
        xml_text = safe_request(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
            is_json=False, timeout=12,
        )
        videos = []
        try:
            root = ET.fromstring(xml_text or "")
            for entry in root.findall("a:entry", YT_NS)[:8]:
                title = (entry.findtext("a:title", "", YT_NS) or "").strip()
                published = entry.findtext("a:published", "", YT_NS) or ""
                vid = entry.findtext("yt:videoId", "", YT_NS) or ""
                if not title:
                    continue
                pub_cst = _cst_from_iso(published)
                videos.append({
                    "title": title,
                    "video_id": vid,
                    "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
                    "published": published,
                    "published_cst": pub_cst.strftime("%Y-%m-%d %H:%M") if pub_cst else "—",
                    "is_today": _date_is_today(pub_cst),
                })
        except Exception as exc:
            failures.append(f"{name}: {exc}")

        if videos:
            handle = (ch.get("handle") or "").lstrip("@")
            channel_url = f"https://www.youtube.com/@{handle}" if handle else \
                          f"https://www.youtube.com/channel/{cid}"
            channels.append({
                "name": name, "desc": ch.get("desc", ""), "source": "YouTube",
                "url": channel_url, "videos": videos,
                "is_today": any(v["is_today"] for v in videos),
                "newest_date": next((v["published_cst"] for v in videos if v["is_today"]),
                                    videos[0]["published_cst"]),
            })
        else:
            msg = "自动抓取失败（RSS 暂无内容或网络异常），暂缺"
            unsupported.append({"name": name, "desc": ch.get("desc", ""), "note": msg})
            failures.append(f"{name}: {msg}")

    # 全部已抓取频道中最新内容的日期（用于当天检验）
    all_dates = [v["published_cst"][:10] for ch in channels for v in ch["videos"]]
    newest_date = max(all_dates) if all_dates else None
    is_today = any(ch["is_today"] for ch in channels)

    if channels:
        print(f"  ✅ 成功抓取 {len(channels)}/{len(HK_CHANNELS)} 个频道"
              + (f"（含当天内容）" if is_today else f"（最新内容日期 {newest_date}）"))
        if unsupported:
            print(f"  🕐 {len(unsupported)} 个频道需登录/未配置，标注暂缺："
                  + "、".join(u["name"] for u in unsupported))
        return _source_result("港股名家频道", "success",
                              is_today=is_today, content_date=newest_date,
                              channels=channels, unsupported=unsupported,
                              error="；".join(failures[:3]) or None,
                              partial=len(channels) + len(unsupported) != len(HK_CHANNELS))

    if unsupported:
        print("  ⚠️ 暂无可自动抓取的频道；需登录/未配置：" + "、".join(u["name"] for u in unsupported))
        return _source_result("港股名家频道", "unavailable", channels=[], unsupported=unsupported,
                              error="；".join(failures[:3]) or "全部频道需登录或未配置自动抓取源")

    print("  ⚠️ 港股名家频道暂不可用，不显示历史内容兜底")
    return _source_result("港股名家频道", "unavailable", channels=[], unsupported=[],
                          error="；".join(failures[:3]) or "未取得有效内容")


# ============================================================
# 数据采集主函数
# ============================================================
def collect_all_data():
    """采集所有数据源"""
    print("\n" + "=" * 50)
    print("🔍 开始全网数据采集")
    print("=" * 50)

    data = {}
    data["实时行情"] = fetch_market_snapshot()
    time.sleep(0.5)
    data["港股名家频道"] = fetch_hk_channels()
    time.sleep(0.5)
    data["Reddit WSB热议"] = fetch_wsb()
    time.sleep(0.5)

    data["Yahoo头条"] = fetch_yahoo_headlines()
    time.sleep(0.5)

    data["A股资讯"] = fetch_sina_headlines()
    time.sleep(0.5)

    data["韩股半导体"] = fetch_kospi_headlines()

    print("\n✅ 数据采集完成！")
    return data


# ============================================================
# HTML 组件
# ============================================================
# 颜色常量
C_RED = "#d93025"
C_GREEN = "#188038"
C_BLUE = "#002FA7"
C_AMBER = "#8a5300"
C_DASH = "#e8e8e8"
C_ALERT_R = "#fce8e6"
C_ALERT_G = "#e6f4ea"
C_ALERT_A = "#fdf3d9"
FONT = "PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif"


def _card(icon, title, content, badge_html=""):
    """生成卡片 HTML（可附带新鲜度徽标）"""
    return f'''<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:6px;">{icon} {title} {badge_html}</div>
{content}
</td></tr></table>'''


def _badge(text, kind="ok"):
    """生成小徽标：ok=绿(当天) / warn=黄(非当天) / bad=红(无数据)"""
    styles = {
        "ok": (C_GREEN, C_ALERT_G, "✅"),
        "warn": (C_AMBER, C_ALERT_A, "🕓"),
        "bad": (C_RED, C_ALERT_R, "⚠️"),
    }
    color, bg, icon = styles.get(kind, styles["ok"])
    return (f'<span style="display:inline-block;background:{bg};color:{color};'
            f'padding:1px 8px;margin-left:4px;font-size:11px;font-weight:700;'
            f'border-radius:8px;vertical-align:2px;">{icon} {_esc(text)}</span>')


def _alert(text, color=C_RED, bg=C_ALERT_R):
    """生成提示条"""
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:6px;background:{bg};"><tr><td style="padding:6px 10px;font-size:13px;color:{color};font-weight:600;text-align:center;">{text}</td></tr></table>'


def _data_table(rows):
    """生成数据表格"""
    html = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">'
    for label, value, *color in rows:
        val_color = color[0] if color else C_RED
        html += f'<tr><td style="padding:5px 0;font-size:14px;color:{C_BLUE};border-bottom:1px dashed {C_DASH};vertical-align:top;" width="42%">{label}</td>'
        html += f'<td style="padding:5px 0;font-size:14px;font-weight:700;color:{val_color};text-align:right;border-bottom:1px dashed {C_DASH};" width="58%">{value}</td></tr>'
    html += '</table>'
    return html


def _mini_table(rows):
    """生成迷你表格"""
    html = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">'
    for label, value in rows:
        html += f'<tr><td style="padding:4px 0;color:{C_BLUE};border-bottom:1px dashed {C_DASH};">{label}</td>'
        html += f'<td style="padding:4px 0;text-align:right;font-weight:700;border-bottom:1px dashed {C_DASH};">{value}</td></tr>'
    html += '</table>'
    return html


def _vs_box(left_sym, left_pct, left_desc, right_sym, right_pct, right_desc):
    """生成对比卡片"""
    left_color = C_GREEN if "+" in left_pct else C_RED
    right_color = C_GREEN if "+" in right_pct else C_RED
    return f'''<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:6px 0;">
  <tr>
    <td width="50%" valign="top" style="padding-right:3px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#e6f4ea;border:1px solid #c6e6ce;">
        <tr><td style="padding:8px;text-align:center;">
          <div style="font-weight:700;font-size:15px;color:{left_color};">{left_sym}</div>
          <div style="font-size:22px;font-weight:800;color:{left_color};">{left_pct}</div>
          <div style="font-size:11px;color:{left_color};">{left_desc}</div>
        </td></tr>
      </table>
    </td>
    <td width="50%" valign="top" style="padding-left:3px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fce8e6;border:1px solid #f5c6cb;">
        <tr><td style="padding:8px;text-align:center;">
          <div style="font-weight:700;font-size:15px;color:{right_color};">{right_sym}</div>
          <div style="font-size:22px;font-weight:800;color:{right_color};">{right_pct}</div>
          <div style="font-size:11px;color:{right_color};">{right_desc}</div>
        </td></tr>
      </table>
    </td>
  </tr>
</table>'''


def _note(text):
    """生成注释条"""
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:8px;background:#e8ecf4;border-left:3px solid {C_BLUE};"><tr><td style="padding:8px 10px;font-size:13px;color:{C_BLUE};line-height:1.7;">{text}</td></tr></table>'


def _section_title(text, size=15):
    """生成小节标题"""
    return f'<div style="font-weight:700;font-size:{size}px;color:{C_BLUE};margin:8px 0 4px;">{text}</div>'


def _tags_html(tags):
    """生成标签 HTML"""
    return " ".join(
        f'<span style="display:inline-block;background:#e6eaf2;color:{C_BLUE};padding:2px 8px;margin:2px 3px;font-size:12px;line-height:20px;">{t}</span>'
        for t in tags
    )


def _source_badge(item):
    """根据数据源的 status / is_today 生成新鲜度徽标。"""
    if item.get("status") != "success":
        return _badge("无数据", "bad")
    if item.get("is_today"):
        return _badge("当天", "ok")
    return _badge(f"非当天（{item.get('content_date') or '—'}）", "warn")


def _item_row(icon, text, sub=""):
    """生成列表项"""
    sub_html = f'<div style="font-size:11px;color:#8899c0;">{sub}</div>' if sub else ""
    return (f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};'
            f'color:{C_BLUE};line-height:1.6;">{icon} {text}{sub_html}</div>')


def _channel_block(ch):
    """生成单个频道的内容块：有内容时列出最新 CHANNEL_TOP_N 条；无内容（需登录/未配置）标注暂缺原因。"""
    name = _esc(ch.get("name", "?"))
    desc = _esc(ch.get("desc", ""))
    url = ch.get("url", "")
    videos = ch.get("videos") or []
    if not videos:
        note = _esc(ch.get("note") or "平台需登录，暂不支持自动抓取")
        return f'''<div style="margin:8px 0 4px;padding:8px;background:#fdf6ec;border:1px solid #f0ddb8;">
<div style="font-size:14px;font-weight:700;color:{C_BLUE};">📺 {name} {_badge("暂缺", "bad")}</div>
<div style="font-size:11px;color:#8899c0;padding:2px 0;">{desc}</div>
<div style="font-size:12px;color:#8a5300;line-height:1.6;">{note}</div>
</div>'''
    badge = _badge("当天", "ok") if ch.get("is_today") else _badge("非当天", "warn")
    rows = []
    for v in videos[:CHANNEL_TOP_N]:
        title = _esc(v.get("title", "")[:110])
        pub = _esc(v.get("published_cst", ""))
        today_tag = (' <span style="display:inline-block;background:#e6f4ea;color:#0b6e34;'
                     'padding:0 6px;font-size:10px;font-weight:700;border-radius:6px;">🆕 当天</span>'
                     if v.get("is_today") else "")
        link = f'<a href="{v.get("url","#")}" style="color:{C_BLUE};text-decoration:none;">{title}</a>'
        rows.append(f'<div style="font-size:13px;padding:4px 0;border-bottom:1px dashed {C_DASH};'
                    f'color:{C_BLUE};line-height:1.6;">▶️ {link}<br>'
                    f'<span style="font-size:11px;color:#8899c0;">发布于 {pub}</span>{today_tag}</div>')
    return f'''<div style="margin:8px 0 4px;padding:8px;background:#f5f7fb;border:1px solid #dfe5f2;">
<div style="font-size:14px;font-weight:700;color:{C_BLUE};">
<a href="{_esc(url)}" style="color:{C_BLUE};text-decoration:none;">📺 {name}</a> {badge}
</div>
<div style="font-size:11px;color:#8899c0;padding:2px 0;">{desc}</div>
{"".join(rows)}
</div>'''


def _freshness_banner(sources):
    """生成「当天内容检验」横幅。sources: [(名称, item), ...]"""
    total = len(sources)
    today_n = sum(1 for _, s in sources if s.get("is_today"))
    no_data = sum(1 for _, s in sources if s.get("status") != "success")
    ok = today_n > 0

    chips = "".join(
        f'<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;'
        f'margin:2px 3px;font-size:11px;color:#fff;">{_esc(name)} {_source_badge(s)}</span>'
        for name, s in sources
    )

    if ok:
        headline = f"✅ {today_n}/{total} 个数据源含当天内容，本次满足推送条件"
        color, bg = C_GREEN, C_ALERT_G
    else:
        headline = (f"⏸️ 本次没有任何数据源含当天内容（{today_n}/{total}），默认不推送"
                    if no_data < total else
                    f"❌ 本次全部数据源均未抓到内容（0/{total}），不会推送")
        color, bg = C_AMBER, C_ALERT_A if no_data < total else (C_RED, C_ALERT_R)

    return f'''<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:6px;background:{bg};">
<tr><td style="padding:8px 10px;">
<div style="font-size:14px;font-weight:700;color:{color};">📅 当天内容检验</div>
<div style="font-size:13px;color:{color};font-weight:600;padding:2px 0;">{headline}</div>
<div style="padding:4px 0;">{chips}</div>
</td></tr></table>'''


def _status_footer(sources):
    """生成页脚数据源状态清单（含无数据源，便于审计）"""
    lines = []
    for name, s in sources:
        if s.get("status") == "success":
            lines.append(f'✅ {_esc(name)} · {_source_badge(s)} · 抓取于 {_esc(s.get("fetched_at","—"))}')
        else:
            detail = _esc(s.get("error", "暂时不可用"))
            lines.append(f'⚠️ {_esc(name)} 数据暂缺（{detail}）· 抓取于 {_esc(s.get("fetched_at","—"))}')
    return "<br>".join(f'<div style="font-size:11px;padding:2px 0;color:#8899c0;line-height:1.7;">{line}</div>'
                       for line in lines)


def _report_meta(html):
    """从 HTML 提取日报元信息（生成日期、当天来源数等），供 --push-only 当天检验用。"""
    def g(name):
        m = re.search(rf'name="octopus-{name}" content="([^"]+)"', html)
        return m.group(1) if m else None
    try:
        today_sources = int(g("today-sources") or 0)
    except (TypeError, ValueError):
        today_sources = 0
    try:
        total_sources = int(g("total-sources") or 0)
    except (TypeError, ValueError):
        total_sources = 0
    return {
        "date": g("report-date"),
        "generated_at": g("generated-at"),
        "today_sources": today_sources,
        "total_sources": total_sources,
    }


# ============================================================
# 报告生成（新版排版：只渲染有内容的区块 + 当天检验横幅）
# ============================================================
def generate_report(data, date_display, date_str):
    """生成完整的 HTML 日报（新排版）

    - 每个区块都带来源、抓取时间与「当天/非当天/无数据」徽标；
    - 没有抓到内容的区块不出现在页面主体，仅在页脚状态清单中留痕；
    - 页面顶部是当天内容检验横幅，直接展示本次是否满足推送条件。
    """
    # 1. 提取所有数据源（缺失的键按空处理，兼容旧测试数据）
    market = data.get("实时行情", {})
    yt = data.get("港股名家频道", {})
    yt_live = yt.get("channels", [])        # 已抓取到内容的频道
    yt_missing = yt.get("unsupported", [])  # 需登录/未配置的频道（带暂缺原因）
    wsb = data.get("Reddit WSB热议", {})
    wsb_stocks = wsb.get("stocks", [])
    yahoo = data.get("Yahoo头条", {})
    yh_headlines = yahoo.get("headlines", [])
    sina = data.get("A股资讯", {})
    sina_headlines = sina.get("headlines", [])
    kospi = data.get("韩股半导体", {})
    kospi_headlines = kospi.get("headlines", [])

    # 2. 数据源清单（顺序即页面展示顺序）
    source_items = [
        ("实时行情", market),
        ("港股名家频道", yt),
        ("Yahoo头条", yahoo),
        ("A股资讯", sina),
        ("韩股半导体", kospi),
        ("Reddit WSB热议", wsb),
    ]

    # 3. 当天内容检验统计
    total = len(source_items)
    today_n = sum(1 for _, s in source_items if s.get("is_today"))
    content_n = sum(1 for _, s in source_items if s.get("status") == "success")

    # 4. 行情速览（有数据才渲染）
    card_market = ""
    if market.get("status") == "success":
        market_rows = []
        for label, precision in [("道琼斯指数", 0), ("标普500", 0), ("纳斯达克", 0),
                                 ("WTI 原油", 2), ("微软 MSFT", 2), ("Meta META", 2)]:
            value, color = _quote_value(market, label, precision)
            market_rows.append((label, value, color))
        astock_rows = []
        for label, precision in [("上证指数", 2), ("深证成指", 2), ("创业板指", 2), ("科创50", 2)]:
            value, color = _quote_value(market, label, precision)
            astock_rows.append((label, value, color))
        data_date = market.get("content_date") or "—"
        card_market = _card(
            "⚡", "行情速览（实时）", _source_badge(market),
            f'<div style="font-size:11px;color:#666;padding-bottom:4px;">{_source_note(market)} · 数据日期 {data_date}</div>'
            + _data_table(market_rows + astock_rows)
            + _note("涨跌幅基于行情源返回的最近两个有效日线收盘价计算；非交易时段显示最近收盘，不以旧日报数值替代。")
        )

    # 5. 港股名家频道：只显示实际抓取到内容的频道；暂缺/未配置项不渲染到日报。
    card_yt = ""
    if yt_live:
        blocks = "".join(_channel_block(ch) for ch in yt_live)
        note = f'本次 {len(yt_live)}/{len(HK_CHANNELS)} 个频道可自动抓取'
        card_yt = _card(
            "📺", "港股名家频道",
            f'<div style="font-size:11px;color:#666;padding-bottom:4px;">{_source_note(yt)} · 内容最新日期 {_esc(yt.get("content_date") or "—")}</div>'
            + blocks
            + _note(f"数据来自各频道公开 RSS；{note}。带 🆕 当天 标记的内容发布于今天（北京时间）；"
                    f"每个频道列出最新 {CHANNEL_TOP_N} 条。"),
            _source_badge(yt),
        )

    # 6. 其它资讯区块（有数据才渲染）
    yh_items = "".join(_item_row("📰", _esc(h[:120])) for h in yh_headlines[:8])
    card_yahoo = _card("📰", "全球头条", _source_badge(yahoo),
                       f'<div style="font-size:11px;color:#666;padding-bottom:4px;">{_source_note(yahoo)}</div>' + yh_items) \
        if yh_headlines else ""

    kospi_items = "".join(_item_row("🇰🇷", _esc(h[:120])) for h in kospi_headlines[:5])
    card_semi = _card("🔌", "半导体&韩股", _source_badge(kospi),
                      f'<div style="font-size:11px;color:#666;padding-bottom:4px;">{_source_note(kospi)}</div>' + kospi_items) \
        if kospi_headlines else ""

    sina_items = "".join(_item_row("🇨🇳", _esc(h[:120])) for h in sina_headlines[:5])
    # 注：A股四指数行情已并入上方「行情速览」卡片，这里只展示新浪资讯
    card_astock = _card("🇨🇳", "A股市场（实时行情 + 资讯）", _source_badge(sina),
                        f'<div style="font-size:11px;color:#666;padding:6px 0 3px;">{_source_note(sina)}</div>' + sina_items) \
        if sina_headlines else ""

    medals = ["🥇", "🥈", "🥉", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]
    wsb_rows = []
    for i, s in enumerate(wsb_stocks[:10]):
        label = f"{medals[i]} {s.get('symbol', '?')} {s.get('name', '')}"
        wsb_rows.append((label, f"{s.get('mentions', '?')} 次提及"))
    card_wsb = _card("🐂", "Reddit WSB热议", _source_badge(wsb),
                     f'<div style="font-size:11px;color:#666;padding-bottom:4px;">{_source_note(wsb)} · 最新帖日期 {_esc(wsb.get("content_date") or "—")}</div>'
                     + (_section_title("Top 10 提及榜", 15) + _mini_table(wsb_rows))) \
        if wsb_rows else ""

    # 7. 有内容的区块拼接（没有数据的区块不会出现在主体）
    content_cards = "".join(c for c in [card_market, card_yt, card_yahoo, card_semi, card_astock, card_wsb] if c)

    # 8. 数据可用性面板（当天检验仍用于推送门禁，但不在页面顶部单独显示横幅）

    # 推送策略说明（与 main() 中的实际门禁保持一致）
    if today_n > 0:
        push_hint = f"✅ 有 {today_n}/{total} 个数据源为当天内容 → 本次会自动推送（除非 --no-push）。"
        hint_color = C_GREEN
    else:
        push_hint = ("⏸️ 无当天内容 → 本次默认不会推送；确认内容后可用 --force-push 手动强制推送。"
                     if content_n > 0 else
                     "❌ 无任何抓取内容 → 本次不会推送。")
        hint_color = C_AMBER if content_n > 0 else C_RED

    card_focus = _card("🎯", "本次数据可用性 · 当天检验",
                       _alert(f"本次运行 {content_n}/{total} 个数据源抓到内容，其中 {today_n} 个为当天内容；"
                              f"所有暂缺项均已明确标注，不会复用旧日报内容。",
                              C_GREEN if today_n > 0 else hint_color,
                              C_ALERT_G if today_n > 0 else C_ALERT_A) +
                       _status_footer(source_items) +
                       _note(f"{push_hint} 生成、抓取和推送是独立步骤：请以各来源的抓取时间、数据日期和当天标记判断数据新鲜度。")
                       )

    # 9. 拼接完整 HTML（头部嵌入元信息，供 --push-only 二次当天检验）
    generated_at = _now()
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<title>章鱼AI·财经日报</title>
</head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:{FONT};color:#002FA7;font-size:15px;line-height:1.75;-webkit-text-size-adjust:100%;">

<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:600px;margin:0 auto;background:#f0f0f0;">
<tr><td style="padding:10px;">

<!-- 头部 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#002FA7;">
<tr><td style="padding:16px 14px 4px;text-align:center;color:#fff;font-size:13px;">🐙 Octopus AI · 全景分析</td></tr>
<tr><td style="padding:0 14px 4px;text-align:center;color:#fff;font-size:20px;font-weight:700;">每日财经日报</td></tr>
<tr><td style="padding:0 14px 12px;text-align:center;color:#fff;font-size:12px;">{_esc(date_display)} · 自动生成 · 生成时间 {_esc(generated_at)}</td></tr>
<tr><td style="padding:0 14px 14px;text-align:center;">
<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">全球市场</span>
<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">AI科技</span>
<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">港股名家频道</span>
</td></tr>
</table>

{content_cards}
{card_focus}

<!-- 页脚 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;text-align:center;">
<div style="font-size:11px;color:#8899c0;line-height:1.8;">
🐙 章鱼AI · 仅供参考，不构成投资建议<br>
数据来源：港股名家频道(YouTube/RSS) · Reddit · Yahoo · 新浪财经 · Naver · TradingKey
</div>
<div style="font-size:10px;color:#99aacc;margin-top:4px;line-height:1.6;">
生成时间：{_esc(generated_at)} · 报告日期：{date_str}
</div>
</td></tr>
</table>

</td></tr>
</table>
</body>
</html>'''

    return html


# ============================================================
# PushPlus 推送
# ============================================================
# 可恢复错误的退避重试节奏：首次 + 3 次重试（共最多 4 次尝试）
PUSH_RETRY_BACKOFF = (10, 30, 60)

# 配额/凭证/内容类错误关键字：重试无意义，立即失败，避免浪费仅剩的额度。
_PUSH_FATAL_KEYWORDS = (
    "已达上限", "已用完", "超出今日", "超过今日", "今日已达", "发送次数",
    "token错误", "token 错误", "token 无效", "token无效", "用户不存在",
    "敏感", "违规",
)

# 频率/服务器类错误关键字：稍等重试通常可以恢复。
_PUSH_RETRYABLE_KEYWORDS = (
    "频繁", "太快", "频率", "稍后再试", "稍后重试", "请重试", "繁忙",
    "too many", "frequent", "rate limit", "busy", "retry", "timeout", "超时",
)


def _push_failure_kind(http_status=None, code=None, msg=""):
    """把一次推送失败分类：

    transient —— 频率/服务器/网络类，按 PUSH_RETRY_BACKOFF 重试；
    fatal     —— 配额/凭证/内容类，重试无意义，立即失败；
    unknown   —— 无法归类的业务错误，不重试，立即失败并把 code/msg 打进日志。
    """
    if isinstance(http_status, int) and (http_status == 429 or http_status >= 500):
        return "transient"
    if isinstance(http_status, int) and 400 <= http_status < 500:
        return "fatal"
    low = (msg or "").lower()
    # 先看致命关键字，避免「已达上限，请稍后再试」被误判成可重试
    if any(k in low for k in _PUSH_FATAL_KEYWORDS):
        return "fatal"
    if any(k in low for k in _PUSH_RETRYABLE_KEYWORDS):
        return "transient"
    return "unknown"


# ------------------------------------------------------------
# PushPlus 内容上限截断
# ------------------------------------------------------------
# 自闭合 / void 标签（不会消耗闭合标签）
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}
# 匹配完整标签（含属性中带引号的 > ），用于按标签边界安全截断
_TAG_RE = re.compile(r"<(?P<close>/)?(?P<tag>[a-zA-Z][a-zA-Z0-9]*)"
                     r"(?P<attrs>(?:\"[^\"]*\"|'[^']*'|[^>\"'])*)>")


def _build_truncate_notice(report_name=None):
    """生成截断提示条：说明推送被截断、磁盘完整版不受影响，并附完整版链接（如有）。"""
    link = ""
    if report_name:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if repo:
            url = (f"https://raw.githubusercontent.com/{repo}/main/output/"
                   f"{report_name}")
            link = (f'<div style="padding:6px 0 2px;"><a href="{url}" '
                    f'style="color:#002FA7;font-weight:700;text-decoration:none;">'
                    f"📄 查看完整日报（{report_name}）</a></div>")
    fname = f"（完整版文件：{report_name}）" if report_name else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;margin-top:8px;background:#fdf3d9;'
            f'border-left:3px solid #8a5300;"><tr><td '
            f'style="padding:8px 10px;font-size:12px;color:#8a5300;line-height:1.7;">'
            f"⚠️ 微信推送有内容长度上限，本消息已自动截断；仓库中的完整日报不受影响{fname}。"
            f"{link}</td></tr></table>")


def _truncate_html_for_push(html, limit=PUSHPLUS_MAX_CONTENT_CHARS, report_name=None):
    """把 HTML 截断到 PushPlus 内容上限以内：只切在完整标签边界，并逆序补全所有未闭合标签。

    返回 (截断后的 html, 是否发生了截断)。磁盘上的日报文件不会被改动——完整版始终保留，
    微信推送只发截断后的版本，末尾附完整版链接/文件名，避免平台截断导致整页排版崩坏。
    """
    if len(html) <= limit:
        return html, False

    notice = _build_truncate_notice(report_name)

    stack = []          # 未闭合标签栈
    candidates = []     # (完整标签结束位置, 该位置时的标签栈快照)
    for m in _TAG_RE.finditer(html):
        end = m.end()
        if end > limit:
            break
        tag, closing = m.group("tag").lower(), bool(m.group("close"))
        if tag not in _VOID_TAGS:
            if closing:
                if stack and stack[-1] == tag:
                    stack.pop()
                # 不匹配时保持栈不变：由下面的逆序补闭合保证结果合法
            else:
                stack.append(tag)
        candidates.append((end, stack.copy()))

    # 从最后一个候选点向前找：正文 + 截断提示 + 逆序闭合标签 的总长不超过上限。
    # 越靠前的候选点未闭合标签越少，闭合标签越短，因此总能找到可用点。
    for end, stack_at_cut in reversed(candidates):
        closers = "".join(f"</{t}>" for t in reversed(stack_at_cut))
        if len(html[:end]) + len(notice) + len(closers) <= limit:
            return html[:end] + notice + closers, True

    # 极端情况：任何截断点都放不下 → 只发截断提示，保证微信端仍能看到说明与完整版入口
    return notice, True


def push_to_wechat(title, content_html, token=None, template="html", report_name=None):
    """通过 PushPlus 推送消息到微信；返回 True/False，调用方必须据此决定退出码。

    - 「发送频繁 / 稍后再试 / 服务器繁忙 / 网络异常 / HTTP 429·5xx」等可恢复错误
      按 PUSH_RETRY_BACKOFF 自动重试（最多 1+3=4 次）；
    - token 失效、当日配额已达上限、内容违规等错误重试无意义，立即返回 False；
    - 每次失败都在日志里保留 PushPlus 返回的 code/msg，便于在 Actions 日志定位。
    """
    token = token or PUSHPLUS_TOKEN

    if not token:
        print("⚠️ 未设置 PUSHPLUS_TOKEN，跳过推送")
        print("   请设置环境变量: export PUSHPLUS_TOKEN=你的token")
        print("   （在 GitHub Actions 中请确认仓库 Settings → Secrets → PUSHPLUS_TOKEN 已配置）")
        return False

    print(f"📤 正在推送到微信 (PushPlus, template={template})...")
    if template == "html":
        content_html, was_truncated = _truncate_html_for_push(
            content_html, PUSHPLUS_MAX_CONTENT_CHARS, report_name)
        if was_truncated:
            print(f"  ⚠️ 日报 HTML 超过 PushPlus 上限 {PUSHPLUS_MAX_CONTENT_CHARS} 字符，"
                  f"已按完整标签边界截断后推送（磁盘上的完整版不受影响）")
    payload = {
        "token": token,
        "title": title,
        "content": content_html,
        "template": template,
    }
    attempts = (0, *PUSH_RETRY_BACKOFF)
    last_error = "未知错误"

    for attempt, wait in enumerate(attempts, 1):
        if wait:
            print(f"  ⏳ 等待 {wait}s 后进行第 {attempt}/{len(attempts)} 次尝试...")
            time.sleep(wait)
        http_status = None
        try:
            resp = requests.post(PUSHPLUS_URL, json=payload, timeout=30)
            http_status = getattr(resp, "status_code", None)
            result = resp.json()
        except Exception as exc:
            last_error = f"网络/请求异常: {exc}"
            if http_status is not None:
                kind = _push_failure_kind(http_status, None, str(exc))
            elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
                # requests 的网络异常（含 SSL/超时/连接重置）都是 OSError 子类，可重试
                kind = "transient"
            else:
                # 编程错误等非网络异常：重试无意义，立即失败并暴露原因
                kind = "unknown"
        else:
            code = result.get("code") if isinstance(result, dict) else None
            msg = str(result.get("msg", "未知错误")) if isinstance(result, dict) else "返回数据格式错误"
            if code == 200:
                print("  ✅ 推送成功！" if attempt == 1 else f"  ✅ 推送成功！（第 {attempt} 次尝试）")
                return True
            last_error = f"PushPlus code={code} msg={msg}"
            kind = _push_failure_kind(http_status, code, msg)

        remaining = len(attempts) - attempt
        if kind == "transient" and remaining > 0:
            print(f"  ⚠️ 第 {attempt}/{len(attempts)} 次推送失败（可重试错误）: {last_error}")
            continue
        if kind == "fatal":
            print(f"  ❌ 推送失败（配额/凭证/内容类错误，重试无意义）: {last_error}")
        else:
            print(f"  ❌ 推送失败: {last_error}")
        return False

    print(f"  ❌ 推送最终失败（已重试 {len(attempts) - 1} 次）: {last_error}")
    return False


def build_no_push_alert_text(reason, data, report_path=None):
    """生成「当天检验未通过」纯文本告警正文（列出每个来源的当天/非当天/无数据状态）。"""
    items = [(k, v) for k, v in (data or {}).items() if isinstance(v, dict)]
    total = len(items)
    content_n = sum(1 for _, v in items if v.get("status") == "success")
    lines = [
        f"📅 当天内容检验未通过（{_now()} 北京时间）",
        f"原因：{reason}",
        f"数据：{content_n}/{total} 个来源抓到内容，且无来源判定为当天，"
        f"已按防旧内容规则不推送日报。",
        "",
        "各来源状态：",
    ]
    for name, s in items:
        if s.get("status") != "success":
            mark = "⚠️ 无数据"
        elif s.get("is_today"):
            mark = "✅ 当天"
        else:
            mark = "🕓 非当天"
        lines.append(f"· {name}：{mark}（数据日期 {s.get('content_date') or '—'}）")
    lines += [
        "",
        "处理建议：",
        "· 周末/休市/源站维护属预期情况，无需处理；",
        "· 确需强制推送：Actions 手动运行并勾选 force_push，"
        "或本地 ./output/manual_push.sh --force。",
        f"报告文件：{os.path.basename(report_path) if report_path else '—'}",
    ]
    return "\n".join(lines)


def push_no_push_alert(reason, data, report_path=None, token=None):
    """推送「当天检验未通过」纯文本告警。

    返回 True/False；返回 False 时调用方应以退出码 1 结束，
    确保 token 缺失 / 接口异常在 Actions 上显红而不是静默。
    """
    print("📣 正在推送「检验未通过」纯文本告警（避免彻底沉默）...")
    title = f"🐙 日报未推送提醒 {datetime.now(CST).strftime('%m/%d %H:%M')}"
    return push_to_wechat(title, build_no_push_alert_text(reason, data, report_path),
                          token=token, template="txt")


def build_push_failure_alert_text(reason, data=None, report_path=None):
    """生成「日报推送失败」兜底告警正文：日报已生成但被 PushPlus 拒绝时，
    让微信侧也能直接看到失败原因和处理建议，而不是只看到 Actions 变红。"""
    lines = [
        f"⚠️ 日报已生成，但推送到微信失败（{_now()} 北京时间）",
        f"原因：{reason}",
        "",
    ]
    if data:
        items = [v for v in data.values() if isinstance(v, dict)]
        today_n = sum(1 for v in items if v.get("is_today"))
        lines.append(f"数据状态：{today_n}/{len(items)} 个来源为当天内容，日报内容本身无问题。")
        lines.append("")
    lines += [
        "处理建议：",
        "· 若日志提示「发送频繁 / 稍后再试 / 服务器繁忙」：属 PushPlus 频率限制，"
        "稍等片刻后在 Actions 重跑一次即可；",
        "· 若提示「发送次数已达上限 / 已用完」：今日 PushPlus 额度已耗尽，次日零点恢复，"
        "或在 PushPlus 升级套餐后更新 Secrets；",
        "· 若提示 token 无效 / 已失效：到 pushplus.plus 重新获取，"
        "并更新仓库 Settings → Secrets → PUSHPLUS_TOKEN；",
        "· 手动重新推送：Actions → 🐙 章鱼AI · 手动抓取推送 → Run workflow，"
        "或本地 ./output/manual_push.sh --force。",
        f"报告文件：{os.path.basename(report_path) if report_path else '—'}",
    ]
    return "\n".join(lines)


def push_failure_alert(reason, data=None, report_path=None, token=None):
    """日报推送失败后的兜底告警（template=txt）。

    返回 True/False；本告警只负责「让微信侧感知失败」，不改变调用方的退出码——
    日报未送达，调用方仍应以退出码 1 结束（Actions 显红）。"""
    print("📣 正在发送「推送失败」兜底告警（让微信侧也能看到失败原因）...")
    title = f"🐙 日报推送失败提醒 {datetime.now(CST).strftime('%m/%d %H:%M')}"
    return push_to_wechat(title, build_push_failure_alert_text(reason, data, report_path),
                          token=token, template="txt")


# ============================================================
# 文件保存
# ============================================================
def _atomic_write(path, content):
    """原子替换文件，避免定时任务被中断后留下旧文件或半个 HTML。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _unique_report_path(requested_path):
    """返回不重复的 HTML 路径。

    自动和手动运行都可能在同一天执行多次；日报不能因同名而覆盖上一份。
    冲突时统一追加澳门日期（YYYYMMDD）和三位随机数，例如：
    ``daily_report_20260802_417.html``。循环检查可避免随机数碰撞。
    """
    if not os.path.exists(requested_path):
        return requested_path

    directory = os.path.dirname(os.path.abspath(requested_path))
    extension = os.path.splitext(requested_path)[1] or ".html"
    stem = os.path.splitext(os.path.basename(requested_path))[0]
    date = _today_str()
    for _ in range(1000):
        suffix = f"{random.SystemRandom().randint(0, 999):03d}"
        candidate = os.path.join(directory, f"{stem}_{date}_{suffix}{extension}")
        if not os.path.exists(candidate):
            return candidate

    raise RuntimeError(f"无法为 {requested_path} 找到不重复的日期随机文件名")


def _timestamped_report_path():
    """目标文件被锁定/不可覆盖时使用的全新日期随机文件名。"""
    directory = os.path.abspath(REPORT_DIR)
    date = _today_str()
    for _ in range(1000):
        suffix = f"{random.SystemRandom().randint(0, 999):03d}"
        candidate = os.path.join(directory, f"daily_report_{date}_{suffix}.html")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("无法为锁定的日报找到不重复的日期随机文件名")


def newest_report_path():
    """返回实际最后更新的一份日报，不依赖可能被锁住的 latest.html。"""
    reports = glob.glob(os.path.join(REPORT_DIR, "daily_report_*.html"))
    return max(reports, key=os.path.getmtime) if reports else None


def save_report(html, output_path=None, data=None):
    """保存本次报告；同名或无法覆盖时创建日期+三位随机数的新 HTML。"""
    requested_path = output_path or os.path.join(REPORT_DIR, f"daily_report_{_today_str()}.html")
    # 先检查文件名是否已存在，避免自动/手动重复运行覆盖既有日报。
    target_path = _unique_report_path(requested_path)
    if target_path != requested_path:
        print(f"⚠️ 输出文件已存在: {requested_path}")
        print(f"   本次改用不重复文件: {target_path}")

    try:
        _atomic_write(target_path, html)
        output_path = target_path
        print(f"💾 日报已原子保存: {output_path}")
    except OSError as exc:
        # 文件在检查后被其它进程锁定或抢先创建时，再生成一个日期随机文件。
        output_path = _timestamped_report_path()
        try:
            _atomic_write(output_path, html)
        except OSError as fallback_exc:
            raise RuntimeError(f"无法保存日报（原路径: {exc}；新日期文件: {fallback_exc}") from fallback_exc
        print(f"⚠️ 无法写入 {target_path}: {exc}")
        print(f"💾 已改存为新的日期文件: {output_path}")

    latest_path = os.path.join(REPORT_DIR, "latest.html")
    try:
        _atomic_write(latest_path, html)
        print(f"💾 最新副本已同步: {latest_path}")
    except OSError as exc:
        # 推送时始终从 output_path 重读，latest 锁定不会导致推送昨天的内容。
        print(f"⚠️ 无法更新 {latest_path}: {exc}")
        print(f"   本次推送将直接使用最新生成文件: {output_path}")

    available = sum(1 for item in (data or {}).values()
                    if isinstance(item, dict) and item.get("status") == "success")
    total = sum(1 for item in (data or {}).values() if isinstance(item, dict))
    print(f"📊 数据源状态: {available}/{total} 可用（不可用项已在报告中标注）")
    return output_path


# ============================================================
# 列出日报
# ============================================================
def list_reports():
    """列出所有已生成的日报文件"""
    pattern = os.path.join(REPORT_DIR, "daily_report_*.html")
    files = sorted(glob.glob(pattern), reverse=True)

    if not files:
        print("暂无日报文件。")
        return 0

    print(f"\n共找到 {len(files)} 份日报：\n")
    for idx, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        mtime = datetime.fromtimestamp(os.path.getmtime(filepath), CST)
        print(f"  {idx:2d}. {filename}  ({size:,} 字节)  [{mtime.strftime('%Y-%m-%d %H:%M')}]")
    return 0


# ============================================================
# 推送前的当天内容检验
# ============================================================
def check_push_eligibility(data):
    """根据采集结果判断是否允许推送。

    返回 (can_push, reason)。
    规则：
      - 没有任何来源抓到内容 → 不推送；
      - 有内容但没有任何来源属于「当天」→ 不推送（防旧内容）；
      - 否则可推送。
    """
    items = [v for v in data.values() if isinstance(v, dict)]
    content_n = sum(1 for v in items if v.get("status") == "success")
    today_n = sum(1 for v in items if v.get("is_today"))
    total = len(items)

    if content_n == 0:
        return False, f"全部数据源均未抓到内容（0/{total}）"
    if today_n == 0:
        return False, f"抓到 {content_n}/{total} 个来源，但没有一个属于当天内容（当天检验未通过）"
    return True, f"当天检验通过：{today_n}/{total} 个数据源含当天内容"


# ============================================================
# 主函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="🐙 章鱼AI · 每日财经日报流水线（当天检验后推送）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 output/pipeline.py                        # 全流程（当天检验通过才推送）
  python3 output/pipeline.py --no-push              # 只生成，不推送
  python3 output/pipeline.py --dry-run              # 采集+预览，不推送
  python3 output/pipeline.py -o custom.html         # 指定输出路径
  python3 output/pipeline.py --manual               # 手动推送模式（重新抓取并推送）
  python3 output/pipeline.py --manual --force-push  # 手动强制推送（内容非当天也推，谨慎）
  python3 output/pipeline.py --push-only            # 推送实际最后更新的一份日报（再次当天检验）
  python3 output/pipeline.py --push-only path/to/report.html
  python3 output/pipeline.py --list                 # 列出日报
        """
    )

    parser.add_argument("--no-push", action="store_true",
                       help="只生成日报，不推送到微信")
    parser.add_argument("--dry-run", action="store_true",
                       help="采集数据并预览，不生成文件也不推送")
    parser.add_argument("-o", "--output", type=str, default=None,
                       help="指定输出文件路径")
    parser.add_argument("--manual", action="store_true",
                       help="手动推送模式：重新抓取→生成→当天检验→推送")
    parser.add_argument("--force-push", action="store_true",
                       help="当天检验未通过时仍强制推送（谨慎）")
    parser.add_argument("--push-only", nargs="?", const="__LATEST__", default=None,
                       help="推送实际最后更新的日报；也可指定带新鲜度标记的文件（再次执行当天检验）")
    parser.add_argument("--force-push-old", action="store_true",
                       help="允许 --push-only 推送未带新鲜度标记的旧版日报（不推荐）")
    parser.add_argument("--allow-incomplete-push", action="store_true",
                       help="当本次所有数据源均不可用时仍推送状态报告（默认不推送）")
    parser.add_argument("--list", action="store_true",
                       help="列出已生成的日报")

    args = parser.parse_args()

    # --list 模式
    if args.list:
        return list_reports()

    # --push-only 模式：推送已有文件，同样执行「当天检验」
    if args.push_only:
        push_path = newest_report_path() if args.push_only == "__LATEST__" else args.push_only
        if not push_path or not os.path.isfile(push_path):
            print(f"❌ 文件不存在: {push_path or '没有可推送的日报'}")
            return 1
        print(f"📎 本次推送 HTML: {push_path}")
        with open(push_path, "r", encoding="utf-8") as f:
            html = f.read()

        meta = _report_meta(html)
        today = _today_str()
        forced = args.force_push or args.force_push_old
        if not meta.get("date") and not forced:
            # 旧版文件：没有「当天检验」元信息，无法确认是否当天 → 默认拒绝
            print("❌ 拒绝推送旧版日报：文件没有当天检验元信息（octopus-report-date）。")
            print("   请先运行 pipeline.py 重新生成，或在确认风险后添加 --force-push / --force-push-old。")
            return 1
        if meta["date"] != today and not forced:
            print(f"❌ 拒绝推送：报告日期 {meta['date']} ≠ 今天 {today}（当天检验未通过）")
            print("   请重新生成，或使用 --force-push 强制推送。")
            return 1
        if meta["today_sources"] < 1 and not forced:
            print(f"❌ 拒绝推送：该日报 {meta['today_sources']}/{meta['total_sources']} 个数据源为当天内容（当天检验未通过）")
            print("   请重新生成，或使用 --force-push 强制推送。")
            return 1

        title = f"🐙 章鱼AI日报 {datetime.now(CST).strftime('%m/%d %H:%M')}"
        if push_to_wechat(title, html, report_name=os.path.basename(push_path)):
            print("\n🎉 全部完成！")
            return 0
        push_failure_alert("通过 --push-only 推送日报被 PushPlus 拒绝（详见上方 code/msg）",
                           report_path=push_path)
        print("\n❌ 推送未成功（退出码 1；在 GitHub Actions 中将标红提醒）。")
        return 1

    # 正常流程
    mode = "🖐 手动推送模式" if args.manual else "每日自动模式"
    print("🐙 " + "=" * 48)
    print(f"   章鱼 AI · 全网多模型协同 · 每日财经日报（{mode}）")
    print("🐙 " + "=" * 48)
    print(f"   运行时间: {_now()}")

    # 1. 采集数据
    data = collect_all_data()

    # 2. 生成报告
    print("\n📝 正在生成日报...")
    date_display = _date_display()
    date_str = _today_str()
    html = generate_report(data, date_display, date_str)
    print("  ✅ 日报生成完成")

    # 3. dry-run 模式
    if args.dry_run:
        print("\n🔍 预览模式（不推送、不保存）")
        print(f"   数据源: 港股名家频道({len(data.get('港股名家频道', {}).get('channels', []))}频道可抓取) | "
              f"WSB({len(data.get('Reddit WSB热议', {}).get('stocks', []))}只) | "
              f"Yahoo({len(data.get('Yahoo头条', {}).get('headlines', []))}条) | "
              f"A股({len(data.get('A股资讯', {}).get('headlines', []))}条) | "
              f"韩股({len(data.get('韩股半导体', {}).get('headlines', []))}条)")
        return 0

    # 4. 保存文件
    output_path = save_report(html, args.output, data)
    # 必须从刚保存的路径读取，避免 latest.html 被锁定时推送到旧副本。
    with open(output_path, "r", encoding="utf-8") as f:
        push_html = f.read()

    # 5. 推送决策：先做「当天内容检验」，再决定是否推送。
    #    约定：任何「应当推送却失败」的情况都返回退出码 1（GitHub Actions 将标红），
    #    不再出现“推送失败但 workflow 显示成功”的静默问题。
    can_push, reason = check_push_eligibility(data)

    def _finish(ok, ok_msg="🎉 全部完成！",
                fail_msg="❌ 流程完成，但推送未成功（见上方原因；Actions 将标红提醒）"):
        print(f"\n{ok_msg if ok else fail_msg}")
        return 0 if ok else 1

    if args.no_push:
        print(f"\n⏭️ 已跳过推送（--no-push）。当天检验: {reason}")
        print(f"   日报已保存: {output_path}")
        return _finish(True)

    if can_push:
        print(f"\n📤 当天检验通过：{reason}")
        title = f"🐙 章鱼AI日报 {datetime.now(CST).strftime('%m/%d %H:%M')}"
        print(f"📎 正在推送本次生成的 HTML: {output_path}")
        if push_to_wechat(title, push_html, report_name=os.path.basename(output_path)):
            return _finish(True)
        # 日报推送失败：再发一条纯文本失败告警，微信侧能直接看到原因；退出码仍为 1。
        push_failure_alert("日报 HTML 多次推送均被 PushPlus 拒绝（详见上方 code/msg）",
                           data=data, report_path=output_path)
        return _finish(False)

    if args.force_push:
        print(f"\n⚠️ 当天检验未通过，但检测到 --force-push，强制推送！")
        print(f"   原因: {reason}")
        title = f"🐙 章鱼AI日报(强制) {datetime.now(CST).strftime('%m/%d %H:%M')}"
        if push_to_wechat(title, push_html, report_name=os.path.basename(output_path)):
            return _finish(True)
        push_failure_alert("强制推送的日报被 PushPlus 拒绝（详见上方 code/msg）",
                           data=data, report_path=output_path)
        return _finish(False)

    if args.allow_incomplete_push:
        print(f"\n⚠️ 全部数据源不可用，但检测到 --allow-incomplete-push，推送状态报告。")
        print(f"   原因: {reason}")
        title = f"🐙 章鱼AI日报(状态) {datetime.now(CST).strftime('%m/%d %H:%M')}"
        if push_to_wechat(title, push_html, report_name=os.path.basename(output_path)):
            return _finish(True)
        push_failure_alert("状态报告推送被 PushPlus 拒绝（详见上方 code/msg）",
                           data=data, report_path=output_path)
        return _finish(False)

    # 当天检验未通过且不强制：不推日报，但推一条纯文本告警，避免彻底沉默。
    print(f"\n⏸️ 当天检验未通过，本次不推送日报。")
    print(f"   原因: {reason}")
    print("   日报已保存（带状态标记），可在确认后使用:")
    print("     python3 output/pipeline.py --manual --force-push   # 强制手动推送")
    print("     python3 output/pipeline.py --push-only output/latest.html")
    if push_no_push_alert(reason, data, output_path):
        return _finish(True, ok_msg="🎉 全部完成（日报未推，已发出检验未通过告警）！")
    print("   ⚠️ 告警也发送失败。若是 token 未配置/失效，本次将以失败结束以便在 Actions 中发现。")
    return _finish(False)


if __name__ == "__main__":
    sys.exit(main())
