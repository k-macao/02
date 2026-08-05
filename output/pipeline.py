#!/usr/bin/env python3
"""
🐙 章鱼 AI · 全网多模型协同 · 每日财经日报流水线
每次运行都重新抓取全网最新数据 → 分析 → 生成 → 当天检验 → 推送

核心规则（2026-08-02 新版，当天修订）：
  1. 没有数据的区块不出现在页面里，也不推送空内容。
  1.1 手动 / 自动推送前先清理 output/ 目录下的全部历史 HTML 报告（含
      daily_report_*.html 与 latest.html），再抓取数据并生成新报告；
      避免历史残留文件（含旧版本特征）被误推或被 latest.html 引用。
      --push-only / --list / --dry-run 不清理（前者基于旧文件，后两者不写文件）。
  2. 每次生成后先做「当天内容检验」：每个数据源标注 ✅当天 / 🕓非当天 / ⚠️无数据，
     只有当「至少一个数据源含当天内容」时才自动推送日报；否则不推日报，
     但会推一条「纯文本告警」说明原因与各来源状态，避免彻底沉默。
  3. 页面内容包含「港股名家频道」区块：香港股评人/财经平台的 YouTube 与通用 RSS
     抓取（无需 API Key），每频道列出最新 3 条；需登录平台明确标注「暂缺」及原因，
     不伪造内容。
  4. 「全球头条」改用 Google News 数据源（替换原 Yahoo Finance News）：直接抓
     Google News 中文版，标题本身即中文，无需翻译。
  5. 新增「东方财富快讯」区块：东方财富免费公开接口的最新 5 条财经新闻。
  6. 新增「热门榜单」区块：最近交易日收盘后 A股/港股/美股 成交量前十
     （东方财富 push2 免费接口）。
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
  7.1 页面风格（2026-08-02 起）：瑞士国际主义排版（Swiss International Style）×
     高级电子杂志——严格网格 + 全程左对齐、黑白 + 克莱因蓝单一强调色（红绿仅作
     涨跌/状态语义色）、粗黑栏线 + 发丝线分级、杂志式刊头（刊名行 / 大标题 /
     导语 / 期号元信息栅格）+ 编号栏目 + 数据审计栏 + 版权页。
     硬约束：全部内联样式 + 表格布局（微信/PushPlus 会剥离 <style> 与 class）。
  8. PushPlus 内容上限（账号已升级会员，默认按 10 万字；可用环境变量
     PUSHPLUS_MAX_CONTENT_CHARS 覆盖）。日报 HTML 超过上限时，发送前会按完整标签边界
     截断并闭合所有标签、末尾附「完整版」链接，保证微信端排版正常；磁盘上的日报文件
     始终保留完整版。
  9. 「AI 盘研判」栏目：基于当日多源信号（实时行情、热门榜单、全球/东财/A股/韩股头条、
     Reddit WSB、港股名家频道观点）做确定性规则合成，输出跨市场综合研判（情绪定调 +
     信号分 + 置信度、板块热度、技术速读、风险提示、明日关注清单）。无需大模型 API、
     可复现、不伪造内容，明确标注「非投资建议」；数据源不足时该区块自动缺席。

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
def _format_amount(val):
    """格式化成交额：显示亿/万，保留两位小数"""
    try:
        v = float(val)
        if v >= 1e8:
            return f"{v/1e8:.2f}亿"
        if v >= 1e4:
            return f"{v/1e4:.2f}万"
        return f"{v:.2f}"
    except (TypeError, ValueError):
        return str(val or "—")


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
    """供 HTML 使用的数据来源状态（纯文字溯源行；状态以色块徽标另行表达）。"""
    if item.get("status") == "success":
        return f"{item.get('source', '数据源')} · 抓取于 {item.get('fetched_at', '—')}"
    detail = _esc(item.get("error", "暂时不可用"))
    return f"{item.get('source', '数据源')} 数据暂缺（{detail}）· 抓取于 {item.get('fetched_at', '—')}"


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
# 数据源 2：全球头条（Google News 中文版）
# ============================================================
GOOGLE_NEWS_RSS = {
    "zh": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
}


def _rfc2822_cst(pub_raw):
    """解析 RFC 2822 时间（如 Google News pubDate）为北京时间 datetime；失败返回 None。"""
    if not pub_raw:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pub_raw).astimezone(CST)
    except Exception:
        return None


def fetch_google_news():
    """抓取 Google News 商业/财经头条（替换原 Yahoo Finance News 数据源）。

    直接抓 Google News 中文版，标题本身即中文，无需翻译；
    每条返回 {title, source, url, published_cst, is_today}。
    """
    print("📡 正在抓取 Google News 全球头条...")
    url = GOOGLE_NEWS_RSS["zh"]
    xml_text = safe_request(url, is_json=False, timeout=15)

    items = []
    if xml_text:
        try:
            root = ET.fromstring(xml_text)
            for item in root.findall("channel/item")[:12]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub = (item.findtext("pubDate") or "").strip()
                if not title:
                    continue
                # Google News 标题形如「原标题 - 来源名」，拆出来源
                src = ""
                m = re.search(r"\s+-\s+([^-]+)$", title)
                if m:
                    src = m.group(1).strip()
                    title = title[: m.start()].strip()
                pub_dt = _rfc2822_cst(pub)
                items.append({
                    "title": title,
                    "source": src,
                    "url": link,
                    "published": pub,
                    "published_cst": pub_dt.strftime("%Y-%m-%d %H:%M") if pub_dt else "—",
                    "is_today": _date_is_today(pub_dt),
                })
        except Exception as exc:
            print(f"  ⚠️ Google News RSS 解析失败: {exc}")

    if not items:
        print("  ⚠️ Google News 暂不可用，不显示历史兜底头条")
        return _source_result("Google News", "unavailable", headlines=[], error="未取得有效新闻")

    content_date = max((it["published_cst"][:10] for it in items if it["published_cst"] != "—"), default=None)
    is_today = any(it["is_today"] for it in items)
    print(f"  ✅ 成功抓取 {len(items)} 条全球头条（中文源，最新 {content_date}）")
    return _source_result("Google News", "success",
                          is_today=is_today, content_date=content_date,
                          headlines=items[:8])


# ============================================================
# 数据源 6：东方财富快讯（免费 API，5 条最新新闻）
# ============================================================
EASTMONEY_NEWS_URLS = [
    "https://np-weblist.eastmoney.com/comm/web/getNewsByColumns",
    "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns",
]


def fetch_eastmoney_news():
    """抓取东方财富最新财经新闻（免费接口，无 API Key，取 5 条）。"""
    print("📡 正在抓取东方财富快讯...")
    params = {
        "client": "web", "biz": "web_news_col", "column": "350",
        "order": "1", "needInteractData": "0",
        "page_index": "1", "page_size": "10",
    }
    news, content_dates = [], []
    for url in EASTMONEY_NEWS_URLS:
        data = safe_request(url, params=params, timeout=12)
        if not data:
            continue
        try:
            lst = ((data.get("data") or {}).get("list")) or []
        except AttributeError:
            lst = []
        for it in lst[:10]:
            title = re.sub(r"<[^>]+>", "", (it.get("title") or it.get("name") or "")).strip()
            if not title:
                continue
            raw_time = str(it.get("showTime") or it.get("createTime") or it.get("publishTime") or "")
            news.append({
                "title": title[:120],
                "url": it.get("url") or it.get("articleUrl") or "",
                "time": raw_time[:16],
                "summary": re.sub(r"<[^>]+>", "", (it.get("summary") or it.get("digest") or ""))[:80],
                "is_today": raw_time[:10] == _today_display(),
            })
            if raw_time[:10]:
                content_dates.append(raw_time[:10])
        if news:
            break

    if not news:
        print("  ⚠️ 东方财富快讯暂不可用，不显示历史兜底资讯")
        return _source_result("东方财富", "unavailable", headlines=[], error="未取得有效资讯")
    content_date = max(content_dates) if content_dates else None
    is_today = any(n["is_today"] for n in news)
    print(f"  ✅ 成功抓取 {len(news)} 条东财快讯（最新 {content_date or '—'}）")
    return _source_result("东方财富", "success",
                          is_today=is_today, content_date=content_date,
                          headlines=news[:5])


# ============================================================
# 数据源 7：热门榜单（最近交易日收盘后 A股/港股/美股 成交量前十）
# ============================================================
HOT_STOCK_MARKETS = {
    "A股": {"fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "desc": "沪深京 A 股"},
    "港股": {"fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2", "desc": "港股主板"},
    "美股": {"fs": "m:105,m:106,m:107", "desc": "美股（纽交所/纳斯达克/美交所）"},
}


def fetch_hot_stocks():
    """抓取最近一个交易日收盘后的 A股/港股/美股成交量前十（东方财富 push2 免费接口）。

    返回 _source_result：markets={市场名: {"desc", "stocks":[{code,name,price,amount}]}}
    """
    print("📡 正在抓取 A股/港股/美股成交量前十...")
    markets = {}
    any_stock = False
    for label, cfg in HOT_STOCK_MARKETS.items():
        params = {
            "pn": "1", "pz": "10", "po": "1", "np": "1", "fltt": "2", "invt": "2",
            "fid": "f6", "fs": cfg["fs"], "fields": "f2,f3,f4,f6,f12,f14",
        }
        data = safe_request("https://push2.eastmoney.com/api/qt/clist/get",
                            params=params, timeout=12)
        stocks = []
        try:
            diff = ((data or {}).get("data") or {}).get("diff") or []
            for it in diff[:10]:
                name = str(it.get("f14") or "").strip()
                if not name:
                    continue
                stocks.append({
                    "code": str(it.get("f12") or ""),
                    "name": name,
                    "price": it.get("f2"),
                    "change_pct": it.get("f3"),
                    "amount": it.get("f6"),
                })
        except Exception:
            stocks = []
        markets[label] = {"desc": cfg["desc"], "stocks": stocks}
        if stocks:
            any_stock = True
        print(f"  {'✅' if stocks else '⚠️'} {label}成交量前十: {len(stocks)} 只")

    if not any_stock:
        print("  ⚠️ 热门榜单暂不可用，不显示历史兜底榜单")
        return _source_result("东方财富热门榜", "unavailable", markets=markets,
                              error="push2 接口未返回有效数据")

    # 榜单即最近交易日收盘数据；标注数据日期为最近交易日（无法从接口取得时用当天）
    content_date = _today_display()
    print("  ✅ 热门榜单抓取完成（数据为最近交易日收盘后）")
    return _source_result("东方财富热门榜", "success",
                          is_today=True, content_date=content_date,
                          markets=markets)


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

    data["全球头条"] = fetch_google_news()
    time.sleep(0.5)

    data["A股资讯"] = fetch_sina_headlines()
    time.sleep(0.5)

    data["韩股半导体"] = fetch_kospi_headlines()
    time.sleep(0.5)

    data["东财快讯"] = fetch_eastmoney_news()
    time.sleep(0.5)

    data["热门榜单"] = fetch_hot_stocks()

    print("\n✅ 数据采集完成！")
    return data


# ============================================================
# HTML 组件（设计系统：瑞士国际主义排版 × 高级电子杂志）
# ------------------------------------------------------------
# 版式语言：
#   · 严格网格 + 全程左对齐（flush-left），非对称留白；
#   · 黑 / 白 / 克莱因蓝 #002FA7（品牌色）为唯一编辑强调色；
#     红 / 绿 / 琥珀仅作「涨跌与数据状态」语义色，不参与装饰；
#   · 粗黑栏线（3px）分隔「栏目」，细发丝线（1px hairline）分隔条目；
#   · 杂志式刊头（masthead）：刊名行 → 大标题 → 导语（standfirst）→ 期号元信息栅格；
#   · 栏目带编号 kicker（01 · MARKET SNAPSHOT），如杂志编辑部栏目；
# ------------------------------------------------------------
# 渲染硬约束：全部使用「内联样式 + 表格布局」——微信 / PushPlus 会剥离
# <style> 标签与 class 选择器，外部样式表与类名排版会在微信端整体失效。
# ============================================================
C_INK = "#191919"      # 墨色正文（近黑）
C_PAPER = "#FFFFFF"    # 纸面
C_BG = "#F4F4F2"       # 页面底色（纸灰）
C_ACCENT = "#002FA7"   # 克莱因蓝：唯一编辑强调色（品牌色）
C_MUTED = "#6E6E73"    # 次级灰（来源说明 / caption）
C_FAINT = "#9B9BA0"    # 三级灰（刊头小字）
C_HAIR = "#E5E5E1"     # 发丝分隔线
C_ZEBRA = "#FAFAF7"    # 极浅底（注释盒 / 暂缺盒）
# 数据语义色（沿用旧值：红跌绿涨；另保留琥珀色表示「非当天」）
# ——仅用于数值与状态标识，不作版式装饰
C_RED = "#d93025"
C_GREEN = "#188038"
C_AMBER = "#8a5300"
C_BLUE = C_ACCENT      # 兼容别名
FONT = ("Helvetica Neue, Helvetica, -apple-system, Arial, "
        "PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif")


def _sq(color=C_ACCENT, size=8):
    """瑞士方块点：最小的强调单元（纯字符，跨端渲染稳定）。"""
    return f'<span style="color:{color};font-size:{size}px;line-height:1;">■</span>'


def _badge(text, kind="ok"):
    """状态徽标：直角描边（非填充药丸）。ok=绿(当天) / warn=黄(非当天) / bad=红(无数据)"""
    colors = {"ok": C_GREEN, "warn": C_AMBER, "bad": C_RED, "ai": C_ACCENT}
    color = colors.get(kind, C_GREEN)
    return (f'<span style="display:inline-block;border:1px solid {color};color:{color};'
            f'background:#fff;padding:0 5px;margin-left:6px;font-size:10px;font-weight:700;'
            f'letter-spacing:1px;line-height:16px;vertical-align:2px;">■&nbsp;{_esc(text)}</span>')


def _alert(text, color=C_AMBER, bg=None):
    """状态提示条：白底 + 左侧色条 + 色文（直角，无圆角填充）。"""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-bottom:8px;border:1px solid {C_HAIR};border-left:3px solid {color};">'
            f'<tr><td style="padding:7px 10px;font-size:11px;color:{color};font-weight:700;'
            f'line-height:1.75;letter-spacing:.5px;">{text}</td></tr></table>')


def _ledger_table(rows, pad):
    """分类账式数据表：左标签右数值，发丝线行分隔（share by _data_table / _mini_table）。"""
    html = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
    for label, value, *color in rows:
        val_color = color[0] if color else C_INK
        html += (f'<tr><td style="padding:{pad} 0;border-bottom:1px solid {C_HAIR};'
                 f'font-size:13px;color:{C_INK};vertical-align:top;line-height:1.5;" '
                 f'width="46%">{label}</td>'
                 f'<td style="padding:{pad} 0;border-bottom:1px solid {C_HAIR};'
                 f'font-size:13px;font-weight:700;color:{val_color};text-align:right;'
                 f'line-height:1.5;font-variant-numeric:tabular-nums;" width="54%">{value}</td></tr>')
    return html + '</table>'


def _data_table(rows):
    """主数据表（行情速览等大行距）。"""
    return _ledger_table(rows, "8px")


def _mini_table(rows):
    """迷你数据表（榜单等紧凑行距）。可选第三元组为数值颜色，默认墨色。"""
    return _ledger_table(rows, "6px")


def _note(text):
    """注释盒：杂志编辑脚注样式（浅底 + 墨色左条 + 小号灰字）。"""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-top:8px;background:{C_ZEBRA};border-left:3px solid {C_INK};">'
            f'<tr><td style="padding:7px 10px;font-size:10px;color:{C_MUTED};'
            f'line-height:1.8;letter-spacing:.3px;">注&nbsp;—&nbsp;{text}</td></tr></table>')


def _subsection(text):
    """栏内小节标题：发丝线 + 小方块 + 加粗小题。"""
    return (f'<div style="border-top:1px solid {C_HAIR};margin-top:10px;padding:8px 0 2px;'
            f'font-size:13px;font-weight:800;color:{C_INK};letter-spacing:.5px;">'
            f'{_sq(C_INK, 7)}<span style="padding-left:5px;">{text}</span></div>')


def _source_badge(item):
    """根据数据源的 status / is_today 生成新鲜度徽标。"""
    if item.get("status") != "success":
        return _badge("无数据", "bad")
    if item.get("is_today"):
        return _badge("当天", "ok")
    return _badge(f"非当天（{item.get('content_date') or '—'}）", "warn")


def _item_row(icon, text, sub=""):
    """条目行：索引/符号窄列 + 标题与来源信息，发丝线收尾。"""
    sub_html = (f'<div style="font-size:10px;color:{C_MUTED};letter-spacing:.3px;'
                f'padding-top:2px;line-height:1.5;">{sub}</div>' if sub else "")
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f'<tr><td width="26" valign="top" style="padding:7px 0;border-bottom:1px solid {C_HAIR};'
            f'font-size:10px;font-weight:800;color:{C_ACCENT};line-height:1.6;">{icon}</td>'
            f'<td style="padding:7px 0;border-bottom:1px solid {C_HAIR};font-size:13px;'
            f'color:{C_INK};line-height:1.7;">{text}{sub_html}</td></tr></table>')


def _headline_row(it, index=None):
    """Google News 头条行：杂志索引号 + 中文标题 + 来源/时间小字。"""
    marker = f"{index:02d}" if isinstance(index, int) else "—"
    display = it.get("title") if isinstance(it, dict) else it
    sub = ""
    if isinstance(it, dict):
        parts = []
        if it.get("source"):
            parts.append(it["source"])
        if it.get("published_cst") and it["published_cst"] != "—":
            parts.append(it["published_cst"])
        sub = " · ".join(parts)
    return _item_row(marker, _esc(display[:120]), _esc(sub[:140]))


def _em_news_row(it, index=None):
    """东方财富快讯行：编号 + 标题 + 时间/摘要小字（兼容字符串与 dict 两种结构）。"""
    marker = f"{index:02d}" if isinstance(index, int) else "—"
    if isinstance(it, dict):
        title = it.get("title") or ""
        sub = " · ".join(x for x in (it.get("time", ""), it.get("summary", "")) if x)
        return _item_row(marker, _esc(title[:120]), _esc(sub[:110]))
    return _item_row(marker, _esc(it[:120]))


def _rank_span(i):
    """榜单序号：00 起始的等宽小编号，杂志索引式。"""
    return (f'<span style="color:{C_ACCENT};font-weight:800;'
            f'font-variant-numeric:tabular-nums;">{i + 1:02d}</span>')


def _channel_block(ch):
    """生成单个频道的内容块：有内容时列出最新 CHANNEL_TOP_N 条；无内容（需登录/未配置）标注暂缺原因。

    有内容：墨色左边条 + 频道名（链接）+ 新鲜度徽标 + ▶️ 条目清单；
    暂缺：虚线边框盒 + 「暂缺」徽标 + 原因，不伪造内容。
    """
    name = _esc(ch.get("name", "?"))
    desc = _esc(ch.get("desc", ""))
    url = ch.get("url", "")
    videos = ch.get("videos") or []
    if not videos:
        note = _esc(ch.get("note") or "平台需登录，暂不支持自动抓取")
        return f'''<div style="margin:8px 0;border:1px dashed {C_FAINT};border-left:3px solid {C_FAINT};background:{C_ZEBRA};padding:10px 12px;">
<div style="font-size:13px;font-weight:800;color:{C_INK};">{name} {_badge("暂缺", "bad")}</div>
<div style="font-size:10px;color:{C_MUTED};padding:3px 0 1px;">{desc}</div>
<div style="font-size:11px;color:{C_MUTED};line-height:1.7;">{note}</div>
</div>'''
    badge = _badge("当天", "ok") if ch.get("is_today") else _badge("非当天", "warn")
    rows = []
    top_n = videos[:CHANNEL_TOP_N]
    for vi, v in enumerate(top_n):
        title = _esc(v.get("title", "")[:110])
        pub = _esc(v.get("published_cst", ""))
        today_tag = (f' <span style="display:inline-block;border:1px solid {C_ACCENT};color:{C_ACCENT};'
                     f'padding:0 4px;font-size:9px;font-weight:700;letter-spacing:1px;'
                     f'background:#fff;">NEW · 当天</span>' if v.get("is_today") else "")
        link = f'<a href="{v.get("url","#")}" style="color:{C_ACCENT};text-decoration:none;">{title}</a>'
        # 最后一行免发丝线，避免与频道盒下边框叠线
        hair = "" if vi == len(top_n) - 1 else f"border-bottom:1px solid {C_HAIR};"
        rows.append(
            f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f'<tr><td width="24" valign="top" style="padding:5px 0;{hair}'
            f'font-size:11px;line-height:1.6;">▶️</td>'
            f'<td style="padding:5px 0;{hair}font-size:13px;'
            f'color:{C_INK};line-height:1.65;">{link}'
            f'<div style="font-size:10px;color:{C_MUTED};padding-top:2px;">发布于 {pub}{today_tag}</div>'
            f'</td></tr></table>')
    return f'''<div style="margin:8px 0;border:1px solid {C_HAIR};border-left:3px solid {C_ACCENT};padding:10px 12px;">
<div style="font-size:13px;font-weight:800;color:{C_INK};">
<a href="{_esc(url)}" style="color:{C_INK};text-decoration:none;">{name}</a> {badge}
</div>
<div style="font-size:10px;color:{C_MUTED};padding:2px 0 4px;letter-spacing:.3px;">{desc}</div>
{"".join(rows)}
</div>'''


def _status_footer(sources):
    """数据审计清单（含无数据源，便于审计）：状态方块 + 名称 + 徽标 + 抓取时间。"""
    lines = []
    for name, s in sources:
        if s.get("status") == "success":
            lines.append((_sq(C_GREEN, 8),
                          f'<b style="color:{C_INK};">{_esc(name)}</b> {_source_badge(s)}'
                          f' · 抓取于 {_esc(s.get("fetched_at", "—"))}'))
        else:
            detail = _esc(s.get("error", "暂时不可用"))
            lines.append((_sq(C_RED, 8),
                          f'<b style="color:{C_INK};">{_esc(name)}</b> 数据暂缺（{detail}）'
                          f' · 抓取于 {_esc(s.get("fetched_at", "—"))}'))
    rows = "".join(
        f'<tr><td width="22" valign="top" style="padding:5px 0;border-bottom:1px solid {C_HAIR};">{marker}</td>'
        f'<td style="padding:5px 0;border-bottom:1px solid {C_HAIR};font-size:11px;'
        f'color:{C_MUTED};line-height:1.7;">{line}</td></tr>'
        for marker, line in lines)
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows}</table>'


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


def _masthead_cell(label, value, value_color=C_INK, first=False):
    """刊头元信息栅格单元：小号大写标签 + 加粗值；除首列外带左发丝线。"""
    border = "" if first else f"border-left:1px solid {C_HAIR};"
    padding = "0" if first else "12px"
    return (f'<td width="33%" valign="top" style="padding:8px 0;{border}">'
            f'<div style="padding-left:{padding};">'
            f'<div style="font-size:9px;font-weight:700;color:{C_FAINT};letter-spacing:2px;">{label}</div>'
            f'<div style="font-size:12px;font-weight:800;color:{value_color};padding-top:3px;'
            f'font-variant-numeric:tabular-nums;">{value}</div></div></td>')


def _section(num, kicker_en, title, content, badge_html="", caption=""):
    """栏目块：3px 粗黑栏线 + 编号 kicker + 中文题 + 来源说明 + 内容。

    num        —— 杂志栏目编号（"01"…），按实际渲染顺序生成；
    kicker_en  —— 英文 kicker（大写字距拉开，置灰）；
    badge_html —— 右侧新鲜度徽标（可选）；
    caption    —— 栏目来源/抓取时间说明行（可选）。
    """
    badge_cell = (f'<td align="right" valign="bottom">{badge_html}</td>' if badge_html else "")
    caption_html = (f'<div style="font-size:10px;color:{C_MUTED};letter-spacing:.3px;'
                    f'padding:4px 0 8px;line-height:1.6;">{caption}</div>'
                    if caption else '<div style="padding-bottom:6px;"></div>')
    return f'''
<div style="border-top:3px solid {C_INK};margin-top:26px;padding-top:9px;">
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
<tr>
<td valign="bottom">{_sq(C_ACCENT, 8)}<span style="font-size:11px;font-weight:800;color:{C_ACCENT};padding-left:6px;letter-spacing:.5px;">{num}</span><span style="font-size:10px;font-weight:700;color:{C_MUTED};letter-spacing:2px;padding-left:8px;">{kicker_en}</span></td>
{badge_cell}
</tr>
</table>
<div style="font-size:16px;font-weight:800;color:{C_INK};letter-spacing:1px;padding-top:4px;">{title}</div>
{caption_html}
{content}
</div>'''


# ============================================================
# 报告生成（Swiss × 杂志排版：刊头 + 编号栏目 + 审计栏 + 版权页）
# ——只渲染有内容的区块；每个区块带来源、抓取时间与「当天/非当天/无数据」徽标
# ============================================================
# ============================================================
# AI 盘研判（规则 / 启发式合成，无需大模型 API）
# ------------------------------------------------------------
# 基于当日已抓取的多源信号（实时行情、热门榜单、全球/东财/A股/韩股头条、
# Reddit WSB、港股名家频道观点）做确定性合成，输出一个跨市场综合研判：
#   情绪定调（多/空/中性 + 信号分 + 置信度）、板块热度、技术速读、
#   风险提示、明日关注清单。全部由规则计算，可复现、不调外部大模型、
#   不伪造内容；明确标注「非投资建议」。
# 如需接大模型，可在 build_ai_analysis 内增加 LLM 分支（保留本规则作兜底）。
# ============================================================
AI_ANALYSIS_ENABLED = True

# 板块关键词：从行情/榜单/头条文本中识别板块提及热度
AI_SECTOR_KEYWORDS = {
    "半导体/芯片": ["半导体", "芯片", "集成电路", "晶圆", "中芯", "寒武纪", "北方华创",
                   "韦尔", "兆易", "设备", "光刻"],
    "AI/算力": ["AI", "人工智能", "算力", "大模型", "英伟达", "NVIDIA", "GPU",
                "光模块", "CPO", "服务器", "数据中心"],
    "新能源/锂电": ["新能源", "锂电", "电池", "光伏", "储能", "宁德", "比亚迪",
                    "逆变器", "氢能"],
    "医药/生物": ["医药", "生物", "创新药", "疫苗", "CRO", "制药", "医疗", "器械"],
    "地产/基建": ["地产", "房地产", "物业", "基建", "建材", "水泥", "建筑", "新城"],
    "金融/银行": ["银行", "券商", "保险", "证券", "信托", "金控", "信贷"],
    "消费": ["消费", "白酒", "食品", "饮料", "零售", "家电", "免税", "餐饮"],
    "黄金/有色": ["黄金", "有色", "铜", "铝", "稀土", "金属", "矿业", "锂矿"],
    "军工": ["军工", "国防", "航空", "船舶", "卫星", "航天"],
    "汽车": ["汽车", "整车", "零部件", "特斯拉", "理想", "蔚来", "小鹏", "小米汽车"],
}

# 舆情多/空关键词（子串匹配，叠加计数）
_AI_BULL_WORDS = ["涨", "升", "新高", "利好", "反弹", "回暖", "走强", "突破",
                  "创新高", "提振", "超预期", "上扬", "收涨", "飘红", "乐观",
                  "复苏", "宽松", "加码", "扩容"]
_AI_BEAR_WORDS = ["跌", "崩", "暴跌", "下挫", "走弱", "回落", "风险", "危机",
                  "警告", "抛售", "利空", "制裁", "衰退", "违约", "加息",
                  "缩表", "监管", "承压", "亏损", "爆雷", "破位", "跳水", "低迷"]
# 风险/宏观风险关键词（用于风险舆情与承压板块识别）
_AI_RISK_KEYWORDS = ["风险", "危机", "警告", "崩", "暴跌", "制裁", "衰退", "违约",
                     "加息", "缩表", "监管", "爆雷", "破位", "跳水", "利空",
                     "承压", "亏损", "诉讼", "调查", "处罚", "关税", "地缘",
                     "降级", "做空", "冻结", "停牌"]
# 风险否定词：标题同时含这些词时，往往「利空出尽/风险偏好走强」，不计入风险项
_AI_RISK_NEGATION = ["利好", "走强", "回暖", "收涨", "飘红", "超预期", "出尽",
                     "消退", "缓解", "复苏", "反弹", "宽松", "加码"]


def _ai_is_risk_title(title):
    """标题含风险关键词但同时又含利好/走强等否定词时，视为非风险项。"""
    if not any(k in title for k in _AI_RISK_KEYWORDS):
        return False
    return not any(n in title for n in _AI_RISK_NEGATION)


def _ai_label(points):
    """把信号分映射为情绪标签（中文 + 英文 kicker）。"""
    if points >= 25:
        return "偏多", "BULLISH-LEANING"
    if points > 8:
        return "温和偏多", "MILDLY BULLISH"
    if points >= -8:
        return "中性", "NEUTRAL"
    if points > -25:
        return "温和偏空", "MILDLY BEARISH"
    return "偏空", "BEARISH"


def _ai_band(pct):
    """把单指数涨跌幅映射到动能档位（中文 + 语义色）。"""
    if pct >= 2:
        return "强势", C_GREEN
    if pct >= 0.5:
        return "偏强", C_GREEN
    if pct > -0.5:
        return "震荡", C_AMBER
    if pct > -2:
        return "偏弱", C_RED
    return "弱势", C_RED


def build_ai_analysis(data):
    """规则合成跨市场综合研判（A股 + 港股 + 美股）。

    返回 dict；available=False 时调用方不渲染该区块（避免空分析）。
    纯确定性计算：不调用任何大模型 API，可复现，不伪造内容。
    """
    market = data.get("实时行情", {}) or {}
    quotes = market.get("quotes", {}) or {}
    hot = data.get("热门榜单", {}) or {}
    hot_markets = hot.get("markets", {}) or {}
    google = data.get("全球头条", {}) or {}
    em = data.get("东财快讯", {}) or {}
    sina = data.get("A股资讯", {}) or {}
    kospi = data.get("韩股半导体", {}) or {}
    wsb = data.get("Reddit WSB热议", {}) or {}
    yt = data.get("港股名家频道", {}) or {}

    google_headlines = google.get("headlines", []) or []
    em_headlines = em.get("headlines", []) or []
    sina_headlines = sina.get("headlines", []) or []
    kospi_headlines = kospi.get("headlines", []) or []
    wsb_stocks = wsb.get("stocks", []) or []
    yt_channels = yt.get("channels", []) or []

    # —— 1. 文本与结构化信号汇总 ——
    texts = []
    for it in google_headlines:
        if isinstance(it, dict):
            texts.append(it.get("title", ""))
    for it in em_headlines:
        if isinstance(it, dict):
            texts.append(it.get("title", ""))
            texts.append(it.get("summary", ""))
    texts += [h for h in sina_headlines if isinstance(h, str)]
    texts += [h for h in kospi_headlines if isinstance(h, str)]
    for ch in yt_channels:
        for v in ch.get("videos", []) or []:
            texts.append(v.get("title", ""))
    all_text = " ".join(t for t in texts if t)

    # 结构化头条（标题 + 来源），用于风险项展示
    headlines_struct = []
    for it in google_headlines:
        if isinstance(it, dict):
            headlines_struct.append((it.get("title", ""), it.get("source", "")))
    for it in em_headlines:
        if isinstance(it, dict):
            headlines_struct.append((it.get("title", ""), ""))
    for h in sina_headlines:
        if isinstance(h, str):
            headlines_struct.append((h, "新浪财经"))
    for h in kospi_headlines:
        if isinstance(h, str):
            headlines_struct.append((h, "韩股/半导体"))
    for ch in yt_channels:
        for v in ch.get("videos", []) or []:
            headlines_struct.append((v.get("title", ""), ch.get("name", "")))

    # 热门榜单个股名（用于板块/关注）
    stock_names = []
    for m, md in hot_markets.items():
        for s in (md or {}).get("stocks", []) or []:
            stock_names.append(s.get("name", ""))

    # —— 2. 情绪打分 ——
    changes = []
    for q in quotes.values():
        try:
            changes.append(float(q["change_pct"]))
        except (TypeError, ValueError, KeyError):
            pass

    present = [m for m, md in hot_markets.items() if (md or {}).get("stocks")]

    bull = sum(all_text.count(w) for w in _AI_BULL_WORDS)
    bear = sum(all_text.count(w) for w in _AI_BEAR_WORDS)
    net = bull - bear

    points = 0.0
    signals = 0
    if changes:
        avg = sum(changes) / len(changes)
        points += max(-40, min(40, avg * 6))
        signals += 1
    if present:
        points += {3: 6, 2: 3, 1: 1}.get(len(present), 0)
        signals += 1
    if all_text:
        points += max(-20, min(20, net * 2))
        signals += 1
    if wsb_stocks:
        points += 3
        signals += 1
    points = max(-100, min(100, round(points)))

    has_data = bool(changes) or bool(present) or bool(all_text) or bool(wsb_stocks)
    if not has_data or not AI_ANALYSIS_ENABLED:
        return {"available": False}

    sentiment_label, sentiment_en = _ai_label(points)
    sentiment_color = C_GREEN if points > 8 else (C_RED if points < -8 else C_AMBER)
    confidence = {3: "高", 2: "中", 1: "低"}.get(signals, "低")

    reason_parts = []
    if changes:
        reason_parts.append(f"主要指数平均{sum(changes) / len(changes):+.2f}%")
    if present:
        reason_parts.append(f"{len(present)} 个市场榜单活跃")
    if all_text:
        tone = "多" if net > 0 else ("空" if net < 0 else "平")
        reason_parts.append(f"舆情净{tone}（利好 {int(bull)} / 利空 {int(bear)}）")
    if wsb_stocks:
        reason_parts.append("Reddit 散户热议")
    reason = "；".join(reason_parts) + "。" if reason_parts else "信号不足。"

    # —— 3. 板块热度 ——
    sector_counts = {}
    for sec, kws in AI_SECTOR_KEYWORDS.items():
        c = sum(all_text.count(k) for k in kws)
        if c:
            sector_counts[sec] = c
    sectors_strong = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:4]

    # 承压板块：出现在真正风险舆情中的板块
    risk_titles = [t for t, _ in headlines_struct if _ai_is_risk_title(t)]
    risk_joined = " ".join(risk_titles)
    sectors_weak = [sec for sec, kws in AI_SECTOR_KEYWORDS.items()
                   if any(k in risk_joined for k in kws)][:3]

    # —— 4. 技术速读 ——
    tech_rows = []
    for label, q in quotes.items():
        try:
            pct = float(q["change_pct"])
        except (TypeError, ValueError, KeyError):
            continue
        band, bcolor = _ai_band(pct)
        tech_rows.append((label, f"{pct:+.2f}%", band, bcolor))
    ups = sum(1 for p in changes if p > 0)
    downs = sum(1 for p in changes if p < 0)
    if ups > downs:
        tech_read = "多数指数上行，动能偏强，留意上方整数关口与前高。"
    elif downs > ups:
        tech_read = "多数指数承压，短线偏弱，关注近期支撑与量能变化。"
    else:
        tech_read = "指数分化/震荡，方向待明朗，宜控制仓位、等待确认。"

    # —— 5. 风险提示 ——
    risks = [(t, src) for t, src in headlines_struct if t and _ai_is_risk_title(t)][:5]

    # —— 6. 关注清单 ——
    watch = []
    for m, md in hot_markets.items():
        for s in (md or {}).get("stocks", []) or []:
            nm = s.get("name", "")
            if nm:
                watch.append((nm, m))
    for s in wsb_stocks[:5]:
        sym = s.get("symbol", "")
        if sym:
            watch.append((sym, "WSB"))
    seen, uniq = set(), []
    for nm, tag in watch:
        if nm and nm not in seen:
            seen.add(nm)
            uniq.append((nm, tag))
    watch = uniq[:8]
    themes = "、".join(sec for sec, _ in sectors_strong[:3])

    return {
        "available": True,
        "score": int(points),
        "confidence": confidence,
        "sentiment_label": sentiment_label,
        "sentiment_en": sentiment_en,
        "sentiment_color": sentiment_color,
        "reason": reason,
        "sectors_strong": sectors_strong,
        "sectors_weak": sectors_weak,
        "tech_rows": tech_rows,
        "tech_read": tech_read,
        "risks": risks,
        "watch": watch,
        "themes": themes,
    }


def _ai_analysis_block(res):
    """渲染「AI 盘研判」栏目内容（Swiss × 杂志风格，复用既有组件）。"""
    color = res["sentiment_color"]
    hero = (
        f'<div style="border:1px solid {C_HAIR};border-left:3px solid {color};'
        f'background:{C_ZEBRA};padding:12px 14px;">'
        f'<div style="font-size:10px;font-weight:700;color:{C_MUTED};letter-spacing:2px;">'
        f'AI 盘研判 · 综合定调</div>'
        f'<div style="font-size:22px;font-weight:800;color:{color};letter-spacing:1px;'
        f'padding:4px 0 2px;">{_esc(res["sentiment_label"])}</div>'
        f'<div style="font-size:11px;color:{C_MUTED};letter-spacing:1px;">'
        f'{_esc(res["sentiment_en"])} · 信号分 {res["score"]:+d} · 置信度 {_esc(res["confidence"])}</div>'
        f'<div style="font-size:12px;color:#3A3A3E;line-height:1.85;padding-top:6px;">'
        f'{_esc(res["reason"])}</div></div>'
    )

    # 板块热度
    if res["sectors_strong"]:
        sec_rows = [(f"{_sq(C_ACCENT, 7)} {sec}", f"{cnt} 提及", C_INK)
                    for sec, cnt in res["sectors_strong"]]
        sectors_html = _subsection("板块热度（信号提及）") + _mini_table(sec_rows)
    else:
        sectors_html = (_subsection("板块热度（信号提及）")
                        + f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;">'
                          f'暂无明显板块信号</div>')
    if res["sectors_weak"]:
        sectors_html += (f'<div style="font-size:11px;color:{C_RED};padding-top:4px;'
                         f'line-height:1.7;">承压板块：'
                         f'{" · ".join(_esc(s) for s in res["sectors_weak"])}</div>')

    # 技术速读
    if res["tech_rows"]:
        tech_rows = [(label, f"{pct} · {band}", c)
                     for label, pct, band, c in res["tech_rows"]]
        tech_html = _subsection("技术速读（指数动能）") + _data_table(tech_rows)
    else:
        tech_html = (_subsection("技术速读（指数动能）")
                     + f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;">无行情数据</div>')
    tech_html += (f'<div style="font-size:11px;color:{C_MUTED};padding-top:4px;'
                  f'line-height:1.8;">{_esc(res["tech_read"])}</div>')

    # 风险提示
    if res["risks"]:
        risk_html = _subsection("风险提示（来自舆情）") + "".join(
            _item_row("⚠", _esc(t), _esc(src)) for t, src in res["risks"])
    else:
        risk_html = (_subsection("风险提示（来自舆情）")
                     + f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;">'
                       f'未检出显著风险舆情</div>')

    # 关注清单
    if res["watch"]:
        watch_html = _subsection("明日关注清单") + "".join(
            _item_row(f"{i + 1:02d}",
                      f'<b>{_esc(n)}</b> <span style="color:{C_MUTED};font-size:11px;">{_esc(tag)}</span>')
            for i, (n, tag) in enumerate(res["watch"]))
    else:
        watch_html = (_subsection("明日关注清单")
                      + f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;">'
                        f'暂无可提炼的关注标的</div>')
    if res["themes"]:
        watch_html += (f'<div style="font-size:11px;color:{C_ACCENT};padding-top:4px;'
                       f'font-weight:700;line-height:1.7;">主题关注：{_esc(res["themes"])}</div>')

    note_html = _note("AI 盘研判由多源公开信号经确定性规则合成，非投资建议，亦不构成任何买卖依据；"
                      "具体决策请结合自身风险偏好与独立判断。")

    return hero + sectors_html + tech_html + risk_html + watch_html + note_html


def generate_report(data, date_display, date_str):
    """生成完整的 HTML 日报

    - 每个区块都带来源、抓取时间与「当天/非当天/无数据」徽标；
    - 没有抓到内容的区块不出现在页面主体，仅在数据审计栏留痕；
    - 当天内容检验仍作为推送门禁，但不在页面顶部单独显示横幅。
    """
    # 1. 提取所有数据源（缺失的键按空处理，兼容旧测试数据）
    market = data.get("实时行情", {})
    yt = data.get("港股名家频道", {})
    yt_live = yt.get("channels", [])        # 已抓取到内容的频道
    wsb = data.get("Reddit WSB热议", {})
    wsb_stocks = wsb.get("stocks", [])
    google = data.get("全球头条", {})
    gh_headlines = google.get("headlines", [])
    sina = data.get("A股资讯", {})
    sina_headlines = sina.get("headlines", [])
    kospi = data.get("韩股半导体", {})
    kospi_headlines = kospi.get("headlines", [])
    em = data.get("东财快讯", {})
    em_headlines = em.get("headlines", [])
    hot = data.get("热门榜单", {})
    hot_markets = hot.get("markets", {})

    # 2. 数据源清单（顺序即页面展示顺序）
    source_items = [
        ("实时行情", market),
        ("港股名家频道", yt),
        ("全球头条", google),
        ("A股资讯", sina),
        ("韩股半导体", kospi),
        ("Reddit WSB热议", wsb),
        ("东财快讯", em),
        ("热门榜单", hot),
    ]

    # 3. 当天内容检验统计
    total = len(source_items)
    today_n = sum(1 for _, s in source_items if s.get("is_today"))
    content_n = sum(1 for _, s in source_items if s.get("status") == "success")

    # 4. 逐栏目构建内容（只登记有内容的栏目；编号在拼版时统一生成）
    sections = []  # (kicker_en, title, content, badge_html, caption)

    # 4.1 行情速览
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
        sections.append((
            "MARKET SNAPSHOT", "行情速览（实时）",
            _subsection("全球与美股") + _data_table(market_rows)
            + _subsection("A股四指数") + _data_table(astock_rows)
            + _note("涨跌幅基于行情源返回的最近两个有效日线收盘价计算；非交易时段显示最近收盘，不以旧日报数值替代。"),
            _source_badge(market),
            f"{_source_note(market)} · 数据日期 {data_date}",
        ))

    # 4.2 港股名家频道：只显示实际抓取到内容的频道；暂缺/未配置项不渲染到日报
    if yt_live:
        blocks = "".join(_channel_block(ch) for ch in yt_live)
        note = f"本次 {len(yt_live)}/{len(HK_CHANNELS)} 个频道可自动抓取"
        sections.append((
            "HK GURU CHANNELS", "港股名家频道",
            blocks + _note(f"数据来自各频道公开 RSS；{note}。带 NEW · 当天 标记的内容发布于今天（北京时间）；"
                           f"每个频道列出最新 {CHANNEL_TOP_N} 条。"),
            _source_badge(yt),
            f"{_source_note(yt)} · 内容最新日期 {_esc(yt.get('content_date') or '—')}",
        ))

    # 4.3 全球头条（Google News 中文）
    if gh_headlines:
        gh_items = "".join(_headline_row(it, i)
                           for i, it in enumerate(gh_headlines[:8], 1))
        sections.append(("GLOBAL HEADLINES", "全球头条", gh_items,
                         _source_badge(google), _source_note(google)))

    # 4.4 东方财富快讯
    if em_headlines:
        em_items = "".join(_em_news_row(it, i)
                           for i, it in enumerate(em_headlines[:5], 1))
        sections.append(("EASTMONEY WIRE", "东方财富快讯", em_items,
                         _source_badge(em),
                         f"{_source_note(em)} · 免费公开数据源"))

    # 4.5 半导体 & 韩股
    if kospi_headlines:
        kospi_items = "".join(_item_row(f"{i:02d}", _esc(h[:120]))
                              for i, h in enumerate(kospi_headlines[:5], 1))
        sections.append(("SEMIS & KOSPI", "半导体 & 韩股", kospi_items,
                         _source_badge(kospi), _source_note(kospi)))

    # 4.6 A股市场（四指数行情已并入「行情速览」，这里只展示新浪资讯）
    if sina_headlines:
        sina_items = "".join(_item_row(f"{i:02d}", _esc(h[:120]))
                             for i, h in enumerate(sina_headlines[:5], 1))
        sections.append(("A-SHARE DESK", "A股市场（实时行情 + 资讯）", sina_items,
                         _source_badge(sina), _source_note(sina)))

    # 4.7 Reddit WSB 热议
    if wsb_stocks:
        wsb_rows = []
        for i, s in enumerate(wsb_stocks[:10]):
            label = (f'{_rank_span(i)}&nbsp; <b>{_esc(s.get("symbol", "?"))}</b>'
                     f' <span style="color:{C_MUTED};font-size:11px;">{_esc(s.get("name", ""))}</span>')
            wsb_rows.append((label, f'{s.get("mentions", "?")} 次提及', C_INK))
        sections.append((
            "WSB HEAT", "Reddit WSB热议",
            _subsection("TOP 10 · 提及榜") + _mini_table(wsb_rows),
            _source_badge(wsb),
            f"{_source_note(wsb)} · 最新帖日期 {_esc(wsb.get('content_date') or '—')}",
        ))

    # 4.8 热门榜单（最近交易日收盘后 A股/港股/美股 成交量前十）
    # 一对一模式：每个市场独立成一个栏目（三个排行榜）
    if hot.get("status") == "success":
        for mlabel, m_en in [("A股", "A-SHARES"), ("港股", "HK-STOCKS"), ("美股", "US-STOCKS")]:
            mdata = hot_markets.get(mlabel) or {}
            stocks = mdata.get("stocks", [])
            if not stocks:
                continue

            rows = []
            for i, s in enumerate(stocks[:10]):
                amount_display = _format_amount(s.get("amount"))
                label = (f'{_rank_span(i)}&nbsp; {_esc(s.get("name", "?"))} '
                         f'<span style="font-size:10px;color:{C_FAINT};">{_esc(str(s.get("code", "")))}</span>')
                rows.append((label, amount_display, C_INK))

            content = _mini_table(rows) + _note(f"榜单为最近交易日收盘后的{mlabel}成交量排名。")
            sections.append((
                f"{m_en} RANK", f"{mlabel}成交量前十",
                content,
                _source_badge(hot),
                f"{_source_note(hot)} · {mlabel}成交量前十"
            ))

    # 4.9 AI 盘研判（规则合成综合研判，作为导读首位栏目）
    if AI_ANALYSIS_ENABLED:
        ai_result = build_ai_analysis(data)
        if ai_result.get("available"):
            ai_block = _ai_analysis_block(ai_result)
            sections.insert(0, (
                "AI READ", "AI 盘研判",
                ai_block, _badge("AI 合成", "ai"),
                "章鱼AI · 多源信号规则合成（非投资建议）",
            ))

    # 5. 数据审计栏（当天检验仍用于推送门禁，但不在页面顶部单独显示横幅）
    if today_n > 0:
        push_hint = f"有 {today_n}/{total} 个数据源为当天内容 → 本次会自动推送（除非 --no-push）。"
        hint_color = C_GREEN
    else:
        push_hint = ("无当天内容 → 本次默认不会推送；确认内容后可用 --force-push 手动强制推送。"
                     if content_n > 0 else
                     "无任何抓取内容 → 本次不会推送。")
        hint_color = C_AMBER if content_n > 0 else C_RED

    audit_content = (
        _alert(f"本次运行 {content_n}/{total} 个数据源抓到内容，其中 {today_n} 个为当天内容；"
               f"所有暂缺项均已明确标注，不会复用旧日报内容。",
               C_GREEN if today_n > 0 else hint_color)
        + _status_footer(source_items)
        + _note(f"{push_hint}生成、抓取和推送是独立步骤：请以各来源的抓取时间、数据日期和当天标记判断数据新鲜度。")
    )
    sections.append(("DATA AUDIT", "本次数据可用性 · 当天检验", audit_content, "", ""))

    # 6. 拼版：栏目编号按渲染顺序生成（只在场的栏目占用编号）
    content_html = "".join(
        _section(f"{i:02d}", kicker, title, content, badge, caption)
        for i, (kicker, title, content, badge, caption) in enumerate(sections, 1))

    # 7. 拼接完整 HTML（头部嵌入元信息，供 --push-only 二次当天检验）
    generated_at = _now()
    src_color = C_GREEN if today_n > 0 else (C_AMBER if content_n > 0 else C_RED)
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<title>章鱼AI · 每日财经日报</title>
</head>
<body style="margin:0;padding:0;background:{C_BG};font-family:{FONT};color:{C_INK};font-size:14px;line-height:1.8;-webkit-text-size-adjust:100%;">

<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:640px;margin:0 auto;background:{C_BG};">
<tr><td style="padding:14px 10px;">

<!-- 纸面（Swiss sheet） -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:{C_PAPER};border:1px solid {C_HAIR};border-top:4px solid {C_INK};">
<tr><td style="padding:22px 20px 20px;">

<!-- 刊头 masthead -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
<tr>
<td valign="bottom">{_sq(C_ACCENT, 12)}<span style="font-size:12px;font-weight:800;color:{C_INK};letter-spacing:3px;padding-left:7px;">OCTOPUS AI</span><span style="font-size:10px;color:{C_FAINT};letter-spacing:2px;padding-left:8px;">章鱼 · 全景分析</span></td>
<td align="right" valign="bottom"><span style="font-size:9px;font-weight:700;color:{C_FAINT};letter-spacing:3px;">FINANCE DAILY</span></td>
</tr>
</table>

<div style="font-size:30px;font-weight:800;color:{C_INK};letter-spacing:2px;line-height:1.3;padding-top:16px;">每日财经日报</div>
<div style="font-size:10px;font-weight:700;color:{C_FAINT};letter-spacing:3px;padding-top:6px;">DAILY FINANCE · MULTI-SOURCE SCAN · UTC+8</div>
<div style="border-bottom:5px solid {C_ACCENT};width:46px;margin-top:12px;font-size:0;line-height:0;">&nbsp;</div>

<!-- 导语 standfirst -->
<div style="margin-top:16px;padding-left:10px;border-left:3px solid {C_ACCENT};font-size:12px;color:#3A3A3E;line-height:1.9;">
全网多源实时抓取，只呈现「确有内容」的栏目；每个栏目标注来源、抓取时间与新鲜度徽标。无数据栏目自动缺席，不以历史内容充数。</div>

<!-- 期号元信息栅格 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-top:2px solid {C_INK};border-bottom:1px solid {C_INK};margin-top:18px;">
<tr>
{_masthead_cell("DATE · 日期", _esc(date_display), first=True)}
{_masthead_cell("GENERATED · 生成", _esc(generated_at))}
{_masthead_cell("TODAY SOURCES · 当天源", f"{today_n} / {total}", src_color)}
</tr>
</table>

{content_html}

<!-- 版权页 colophon -->
<div style="border-top:3px solid {C_INK};margin-top:28px;padding-top:10px;">
<div>{_sq(C_ACCENT, 9)}<span style="font-size:10px;font-weight:800;color:{C_INK};letter-spacing:2px;padding-left:6px;">OCTOPUS AI · COLOPHON</span></div>
<div style="font-size:11px;color:{C_MUTED};line-height:1.9;padding-top:8px;">
仅供投资参考，不构成投资建议。行情与榜单来自公开数据，未抓取到内容的栏目自动缺席，不以历史内容充数。</div>
<div style="font-size:10px;color:{C_FAINT};letter-spacing:.5px;line-height:1.8;padding-top:4px;">
DATA — 港股名家频道 (YouTube / RSS) · Google News · 东方财富 · Reddit · 新浪财经 · NAVER · AI 盘研判（规则合成）<br>
生成时间 {_esc(generated_at)} · 报告日期 {date_str} · 章鱼AI 自动出品</div>
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
            link = (f'<div style="padding-top:6px;"><a href="{url}" '
                    f'style="color:{C_ACCENT};font-weight:700;text-decoration:none;">'
                    f"→ 查看完整日报（{report_name}）</a></div>")
    fname = f"（完整版文件：{report_name}）" if report_name else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;margin-top:8px;background:{C_ZEBRA};'
            f'border:1px solid {C_HAIR};border-left:3px solid {C_AMBER};"><tr><td '
            f'style="padding:8px 10px;font-size:11px;color:{C_AMBER};line-height:1.75;">'
            f"微信推送有内容长度上限，本消息已自动截断；仓库中的完整日报不受影响{fname}。"
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
            raise RuntimeError(f"无法保存日报（原路径: {exc}；新日期文件: {fallback_exc}）") from fallback_exc
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
# 清理旧的 HTML 报告
# ============================================================
def clean_old_html_reports(keep_latest=False):
    """清理 output/ 目录下的所有旧 HTML 报告（daily_report_*.html + latest.html）。

    在手动/自动推送前调用，确保本次生成的日报是"最新且唯一"的内容，
    避免历史残留文件（特别是含旧版本特征的报告）被误推或被 latest.html 引用。

    参数:
        keep_latest: True 时保留 latest.html（仅清 daily_report_*.html）；
                     默认 False：两个都清。
    返回:
        (删除的 daily_report 数, 是否删了 latest.html)
    """
    deleted = 0
    latest_deleted = False

    # 1) 清理 daily_report_*.html
    pattern = os.path.join(REPORT_DIR, "daily_report_*.html")
    for filepath in glob.glob(pattern):
        try:
            os.remove(filepath)
            deleted += 1
        except OSError as exc:
            print(f"⚠️ 清理失败: {filepath} ({exc})")

    # 2) 清理 latest.html（除非显式保留）
    latest_path = os.path.join(REPORT_DIR, "latest.html")
    if not keep_latest and os.path.isfile(latest_path):
        try:
            os.remove(latest_path)
            latest_deleted = True
        except OSError as exc:
            print(f"⚠️ 清理失败: {latest_path} ({exc})")

    if deleted or latest_deleted:
        parts = []
        if deleted:
            parts.append(f"{deleted} 份 daily_report_*.html")
        if latest_deleted:
            parts.append("latest.html")
        print(f"🧹 已清理历史 HTML 报告: {', '.join(parts)}")
    return deleted, latest_deleted


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

    # 0. 清理历史 HTML 报告（手动/自动推送前必做）：
    #    避免历史残留文件（含旧版本特征的报告）被推送或被 latest.html 引用。
    #    --dry-run 不写文件，所以跳过清理。
    if not args.dry_run:
        clean_old_html_reports()

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
              f"全球头条({len(data.get('全球头条', {}).get('headlines', []))}条) | "
              f"A股({len(data.get('A股资讯', {}).get('headlines', []))}条) | "
              f"韩股({len(data.get('韩股半导体', {}).get('headlines', []))}条) | "
              f"东财快讯({len(data.get('东财快讯', {}).get('headlines', []))}条) | "
              f"热门榜({sum(len(m.get('stocks', [])) for m in data.get('热门榜单', {}).get('markets', {}).values())}只)")
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
