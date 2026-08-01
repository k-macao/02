#!/usr/bin/env python3
"""
🐙 章鱼 AI · 全网多模型协同 · 每日财经日报流水线
每次运行都重新抓取全网最新数据 → 分析 → 生成 → 推送

用法:
  python3 output/pipeline.py                  # 全流程
  python3 output/pipeline.py --no-push        # 只生成，不推送
  python3 output/pipeline.py --dry-run        # 采集+预览，不推送
  python3 output/pipeline.py -o custom.html   # 指定输出路径
  python3 output/pipeline.py --push-only              # 推送实际最后更新的一份日报
  python3 output/pipeline.py --push-only path/to/report.html
  python3 output/pipeline.py --list           # 列出日报
"""
import os
import sys
import json
import time
import argparse
import re
import glob
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
CST = timezone(timedelta(hours=8))  # 北京时间
MACAU = timezone(timedelta(hours=8))  # 澳门时间（同东八区）

# PushPlus 配置
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_URL = "https://www.pushplus.plus/send"

# 请求头
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
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
def _source_result(source, status, **payload):
    """统一记录来源、抓取时间和失败状态；绝不把历史文案伪装成实时数据。"""
    return {"source": source, "status": status, "fetched_at": _now(), **payload}


def _source_note(item):
    """供 HTML 使用的数据来源状态。"""
    if item.get("status") == "success":
        return f"✅ {item.get('source', '数据源')} · 抓取于 {item.get('fetched_at', '—')}"
    detail = _esc(item.get("error", "暂时不可用"))
    return f"⚠️ {item.get('source', '数据源')} 暂缺（{detail}）· 抓取于 {item.get('fetched_at', '—')}"


def fetch_market_snapshot():
    """从 Yahoo Chart API 获取实际最新收盘/最新报价，不提供历史数字兜底。"""
    print("📡 正在抓取全球/A股实时行情...")
    specs = [
        ("道琼斯指数", "%5EDJI"), ("标普500", "%5EGSPC"), ("纳斯达克", "%5EIXIC"),
        ("WTI 原油", "CL=F"), ("微软 MSFT", "MSFT"), ("Meta META", "META"),
        ("上证指数", "000001.SS"), ("深证成指", "399001.SZ"),
        ("创业板指", "399006.SZ"), ("科创50", "000688.SS"),
    ]
    quotes, failures = {}, []
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
        except (KeyError, TypeError, IndexError, ValueError, ZeroDivisionError) as exc:
            failures.append(f"{label}: {exc}")
    status = "success" if quotes else "unavailable"
    if quotes:
        print(f"  ✅ 成功抓取 {len(quotes)}/{len(specs)} 个实时行情")
    else:
        print("  ⚠️ 实时行情暂不可用；日报将明确显示数据暂缺")
    return _source_result("Yahoo Finance Chart", status, quotes=quotes,
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
    is_fallback = False
    
    if data and "data" in data and "children" in data["data"]:
        for child in data["data"]["children"]:
            post = child.get("data", {})
            title = post.get("title", "")
            selftext = post.get("selftext", "")
            text = title + " " + selftext
            
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
    print(f"  ✅ 成功抓取到 {len(stocks)} 只热门股票")
    return _source_result("Reddit WSB", "success", stocks=stocks)


# ============================================================
# 数据源 2：Yahoo Finance 头条
# ============================================================
def fetch_yahoo_headlines():
    """抓取 Yahoo Finance 热门新闻标题"""
    print("📡 正在抓取 Yahoo Finance 头条...")
    
    headlines = []
    is_fallback = False
    
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
    print(f"  ✅ 成功抓取到 {len(headlines)} 条头条")
    return _source_result("Yahoo Finance News", "success", headlines=headlines[:8])


# ============================================================
# 数据源 3：A股资讯（新浪财经）
# ============================================================
def fetch_sina_headlines():
    """抓取新浪财经 A 股资讯"""
    print("📡 正在抓取 A 股资讯...")
    
    headlines = []
    is_fallback = False
    
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
    print(f"  ✅ 成功抓取到 {len(headlines)} 条 A 股资讯")
    return _source_result("新浪财经", "success", headlines=headlines[:5])


# ============================================================
# 数据源 4：韩股 & 半导体资讯
# ============================================================
def fetch_kospi_headlines():
    """抓取韩股和半导体相关资讯"""
    print("📡 正在抓取韩股 & 半导体资讯...")
    
    headlines = []
    is_fallback = False
    
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
    print(f"  ✅ 成功抓取到 {len(headlines)} 条韩股资讯")
    return _source_result("Naver / Yahoo Korea", "success", headlines=headlines[:5])


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
C_DASH = "#e8e8e8"
C_ALERT_R = "#fce8e6"
C_ALERT_G = "#e6f4ea"
FONT = "PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif"


def _card(icon, title, content):
    """生成卡片 HTML"""
    return f'''<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:6px;">{icon} {title}</div>
{content}
</td></tr></table>'''


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


# ============================================================
# 报告生成（核心修复部分）
# ============================================================
def generate_report(data, date_display, date_str):
    """生成完整的 HTML 日报"""
    # 1. 提取所有数据源
    wsb = data.get("Reddit WSB热议", {})
    wsb_stocks = wsb.get("stocks", [])
    yahoo = data.get("Yahoo头条", {})
    yh_headlines = yahoo.get("headlines", [])
    sina = data.get("A股资讯", {})
    sina_headlines = sina.get("headlines", [])
    kospi = data.get("韩股半导体", {})
    kospi_headlines = kospi.get("headlines", [])

    # 2. 构建 WSB 榜单
    medals = ["🥇","🥈","🥉","④","⑤","⑥","⑦","⑧","⑨","⑩"]
    wsb_rows = []
    for i, s in enumerate(wsb_stocks[:10]):
        label = f"{medals[i]} {s.get('symbol','?')} {s.get('name','')}"
        wsb_rows.append((label, f"{s.get('mentions','?')} 次提及"))

    # 3. 构建各列表项 HTML
    yh_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">📰 {_esc(h[:120])}</div>'
        for h in yh_headlines[:8]
    ) if yh_headlines else '<div style="font-size:13px;color:#888;">暂无实时数据</div>'

    kospi_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">🇰🇷 {_esc(h[:120])}</div>'
        for h in kospi_headlines[:5]
    ) if kospi_headlines else '<div style="font-size:13px;color:#888;">暂无实时数据</div>'

    sina_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">🇨🇳 {_esc(h[:120])}</div>'
        for h in sina_headlines[:5]
    ) if sina_headlines else '<div style="font-size:13px;color:#888;">暂无实时数据</div>'

    # 4. 按本次采集结果构建页面。没有任何常量行情或“历史兜底”内容。
    market = data.get("实时行情", {})
    source_items = [market, yahoo, sina, kospi, wsb]
    source_status = "<br>".join(
        f'<div style="font-size:11px;padding:2px 0;color:{C_GREEN if x.get("status") == "success" else C_RED};">{_source_note(x)}</div>'
        for x in source_items
    )
    market_rows = []
    for label, precision in [("道琼斯指数", 0), ("标普500", 0), ("纳斯达克", 0),
                             ("WTI 原油", 2), ("微软 MSFT", 2), ("Meta META", 2)]:
        value, color = _quote_value(market, label, precision)
        market_rows.append((label, value, color))
    astock_rows = []
    for label, precision in [("上证指数", 2), ("深证成指", 2), ("创业板指", 2), ("科创50", 2)]:
        value, color = _quote_value(market, label, precision)
        astock_rows.append((label, value, color))

    card_market = _card("⚡", "行情速览（实时）",
        _alert(_source_note(market), C_GREEN if market.get("status") == "success" else C_RED,
               C_ALERT_G if market.get("status") == "success" else C_ALERT_R) +
        _data_table(market_rows) +
        _note("涨跌幅基于行情源返回的最近两个有效日线收盘价计算；非交易时段显示最近收盘，不以旧日报数值替代。")
    )

    card_yahoo = _card("📰", "全球头条",
        f'<div style="font-size:11px;color:#666;padding-bottom:4px;">{_source_note(yahoo)}</div>' + yh_items)

    card_semi = _card("🔌", "半导体&韩股",
        f'<div style="font-size:11px;color:#666;padding-bottom:4px;">{_source_note(kospi)}</div>' +
        kospi_items
    )

    card_wsb = _card("🐂", "Reddit WSB热议",
        f'<div style="font-size:11px;color:#666;padding-bottom:4px;">{_source_note(wsb)}</div>' +
        ( _section_title("Top 10 提及榜", 15) + _mini_table(wsb_rows)
          if wsb_rows else '<div style="font-size:13px;color:#888;">暂无实时数据；为避免误导，未展示旧榜单。</div>' )
    )

    card_astock = _card("🇨🇳", "A股市场（实时行情 + 资讯）",
        _data_table(astock_rows) +
        f'<div style="font-size:11px;color:#666;padding:6px 0 3px;">{_source_note(sina)}</div>' +
        sina_items
    )

    successful = sum(1 for item in source_items if item.get("status") == "success")
    card_focus = _card("🎯", "本次数据可用性",
        _alert(f"本次运行 {successful}/{len(source_items)} 个数据源可用；所有暂缺项均已明确标注，不会复用旧日报内容。",
               C_GREEN if successful else C_RED, C_ALERT_G if successful else C_ALERT_R) + source_status +
        _note("生成、抓取和推送是独立步骤：请以本页各来源的抓取时间和状态判断数据新鲜度。")
    )

    # 6. 拼接完整 HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>章鱼AI·财经日报</title>
</head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:{FONT};color:#002FA7;font-size:15px;line-height:1.75;-webkit-text-size-adjust:100%;">

<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:600px;margin:0 auto;background:#f0f0f0;">
<tr><td style="padding:10px;">

<!-- 头部 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#002FA7;">
<tr><td style="padding:16px 14px 4px;text-align:center;color:#fff;font-size:13px;">🐙 Octopus AI · 全景分析</td></tr>
<tr><td style="padding:0 14px 4px;text-align:center;color:#fff;font-size:20px;font-weight:700;">每日财经日报</td></tr>
<tr><td style="padding:0 14px 12px;text-align:center;color:#fff;font-size:12px;">{_esc(date_display)} · 自动生成</td></tr>
<tr><td style="padding:0 14px 14px;text-align:center;">
<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">全球市场</span>
<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">AI科技</span>
<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">{_esc(_now())}</span>
</td></tr>
</table>

{card_market}
{card_yahoo}
{card_semi}
{card_wsb}
{card_astock}
{card_focus}

<!-- 页脚 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;text-align:center;">
<div style="font-size:11px;color:#8899c0;line-height:1.8;">
🐙 章鱼AI · 仅供参考，不构成投资建议<br>
数据来源：Reddit · Yahoo · 新浪财经 · TradingKey
</div>
<div style="font-size:10px;color:#99aacc;margin-top:4px;line-height:1.6;">
生成时间：{_now()}
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
def push_to_wechat(title, content_html, token=None):
    """通过 PushPlus 推送消息到微信"""
    token = token or PUSHPLUS_TOKEN
    
    if not token:
        print("⚠️ 未设置 PUSHPLUS_TOKEN，跳过推送")
        print("   请设置环境变量: export PUSHPLUS_TOKEN=你的token")
        return False
    
    print(f"📤 正在推送到微信 (PushPlus)...")
    
    try:
        resp = requests.post(
            PUSHPLUS_URL,
            json={
                "token": token,
                "title": title,
                "content": content_html,
                "template": "html",
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        
        if result.get("code") == 200:
            print("  ✅ 推送成功！")
            return True
        else:
            print(f"  ❌ 推送失败: {result.get('msg', '未知错误')}")
            return False
    except Exception as e:
        print(f"  ❌ 推送异常: {e}")
        return False


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


def _timestamped_report_path():
    """目标文件被锁定/不可覆盖时使用的全新日期时间文件名。"""
    stamp = datetime.now(CST).strftime("%Y%m%d_%H%M%S")
    candidate = os.path.join(REPORT_DIR, f"daily_report_{stamp}.html")
    sequence = 1
    while os.path.exists(candidate):
        candidate = os.path.join(REPORT_DIR, f"daily_report_{stamp}_{sequence}.html")
        sequence += 1
    return candidate


def newest_report_path():
    """返回实际最后更新的一份日报，不依赖可能被锁住的 latest.html。"""
    reports = glob.glob(os.path.join(REPORT_DIR, "daily_report_*.html"))
    return max(reports, key=os.path.getmtime) if reports else None


def save_report(html, output_path=None, data=None):
    """保存本次报告；目标不能覆盖时创建带日期时间的新 HTML，绝不退回旧文件。"""
    requested_path = output_path or os.path.join(REPORT_DIR, f"daily_report_{_today_str()}.html")
    try:
        _atomic_write(requested_path, html)
        output_path = requested_path
        print(f"💾 日报已原子保存: {output_path}")
    except OSError as exc:
        # 文件被其它进程锁定、只读或无法替换时，保留旧文件并输出一份可追溯的新报告。
        output_path = _timestamped_report_path()
        try:
            _atomic_write(output_path, html)
        except OSError as fallback_exc:
            raise RuntimeError(f"无法保存日报（原路径: {exc}；新日期文件: {fallback_exc}）") from fallback_exc
        print(f"⚠️ 无法覆盖 {requested_path}: {exc}")
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
# 主函数
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="🐙 章鱼AI · 每日财经日报流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 output/pipeline.py                  # 全流程
  python3 output/pipeline.py --no-push        # 只生成，不推送
  python3 output/pipeline.py --dry-run        # 采集+预览，不推送
  python3 output/pipeline.py -o custom.html   # 指定输出路径
  python3 output/pipeline.py --push-only              # 推送实际最后更新的一份日报
  python3 output/pipeline.py --push-only path/to/report.html
  python3 output/pipeline.py --list           # 列出日报
        """
    )
    
    parser.add_argument("--no-push", action="store_true",
                       help="只生成日报，不推送到微信")
    parser.add_argument("--dry-run", action="store_true",
                       help="采集数据并预览，不生成文件也不推送")
    parser.add_argument("-o", "--output", type=str, default=None,
                       help="指定输出文件路径")
    parser.add_argument("--push-only", nargs="?", const="__LATEST__", default=None,
                       help="推送实际最后更新的日报；也可指定带新鲜度标记的文件")
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
    
    # --push-only 模式
    if args.push_only:
        push_path = newest_report_path() if args.push_only == "__LATEST__" else args.push_only
        if not push_path or not os.path.isfile(push_path):
            print(f"❌ 文件不存在: {push_path or '没有可推送的日报'}")
            return 1
        print(f"📎 本次推送最新 HTML: {push_path}")
        with open(push_path, "r", encoding="utf-8") as f:
            html = f.read()
        if "本次数据可用性" not in html and not args.force_push_old:
            print("❌ 拒绝推送旧版日报：文件没有数据来源/抓取时间标记。")
            print("   请重新生成，或在确认风险后添加 --force-push-old。")
            return 1

        title = f"🐙 章鱼AI日报 {datetime.now(CST).strftime('%m/%d')}"
        push_to_wechat(title, html)
        return 0
    
    # 正常流程
    print("🐙 " + "=" * 48)
    print("   章鱼 AI · 全网多模型协同 · 每日财经日报")
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
        print(f"   数据源: WSB({len(data.get('Reddit WSB热议', {}).get('stocks', []))}只) | "
              f"Yahoo({len(data.get('Yahoo头条', {}).get('headlines', []))}条) | "
              f"A股({len(data.get('A股资讯', {}).get('headlines', []))}条) | "
              f"韩股({len(data.get('韩股半导体', {}).get('headlines', []))}条)")
        return 0
    
    # 4. 保存文件
    output_path = save_report(html, args.output, data)
    # 必须从刚保存的路径读取，避免 latest.html 被锁定时推送到旧副本。
    with open(output_path, "r", encoding="utf-8") as f:
        push_html = f.read()
    
    # 5. 推送：所有来源都失败时，不把“数据暂缺”误当日报推送给用户。
    available_sources = sum(1 for item in data.values()
                            if isinstance(item, dict) and item.get("status") == "success")
    if not args.no_push and (available_sources > 0 or args.allow_incomplete_push):
        title = f"🐙 章鱼AI日报 {datetime.now(CST).strftime('%m/%d')}"
        print(f"📎 正在推送本次生成的 HTML: {output_path}")
        push_to_wechat(title, push_html)
    elif not args.no_push:
        print("\n⏭️ 所有数据源均不可用：已生成带状态标记的报告，但默认不推送。")
        print("   如需推送状态报告，请添加 --allow-incomplete-push。")
    else:
        print("\n⏭️ 已跳过推送（--no-push）")
    
    print("\n🎉 全部完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
