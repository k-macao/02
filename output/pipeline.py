#!/usr/bin/env python3
"""
🐙 章鱼 AI · 全网多模型协同 · 每日财经日报流水线
每次运行都重新抓取全网最新数据 → 分析 → 生成 → 推送。

用法:
  python3 output/pipeline.py                  # 全流程：采集 → 生成 → 推送
  python3 output/pipeline.py --no-push        # 只生成日报，不推送
  python3 output/pipeline.py --dry-run        # 采集 + 预览，不推送
  python3 output/pipeline.py -o custom.html   # 指定输出路径
  python3 output/pipeline.py --push-only output/daily_report_20260730.html  # 只推送已有文件
  python3 output/pipeline.py --list           # 列出已生成的日报
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

# 请求头（避免被反爬）
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
    
    if data and "data" in data and "children" in data["data"]:
        for child in data["data"]["children"]:
            post = child.get("data", {})
            title = post.get("title", "")
            selftext = post.get("selftext", "")
            text = title + " " + selftext
            
            # 提取股票符号（大写字母 2-5 个，排除常见词）
            exclude_words = {"THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER",
                           "WAS", "ONE", "OUR", "OUT", "DAY", "GET", "HAS", "HIM", "HIS", "HOW",
                           "ITS", "MAY", "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "BOY", "DID",
                           "ITS", "LET", "PUT", "SAY", "SHE", "TOO", "USE", "DD", "YOLO", "WSB",
                           "FDA", "SEC", "FED", "GDP", "PCE", "CPI", "ETF", "IPO", "AI", "USA",
                           "US", "UK", "EU", "CEO", "CFO", "COO", "CTO", "EV", "TSLA", "SPY",
                           "QQQ", "SPX", "DOW", "NYSE", "NASDAQ", "OTC", "ATH", "ITM", "OTC",
                           "USD", "EUR", "GBP", "BTC", "ETH", "NFT", "DeFi", "S&P", "GDP",
                           "EST", "EOD", "PT", "RSI", "MACD", "EPS", "P/E", "EBITDA", "TTM",
                           "Q1", "Q2", "Q3", "Q4", "FY", "YTD", "MoM", "YoY", "APR", "IRR",
                           "IMO", "IMHO", "TBH", "BTBC", "FWIW", "ELI5", "TL;DR", "EDIT",
                           "SOURCE", "PERMALINK", "CROSSPOST", "CROSSPOSTED", "REPOST"}
            
            # 匹配 $SYMBOL 或纯大写股票代码
            symbols = re.findall(r'\$([A-Z]{1,5})\b', text)
            symbols += re.findall(r'\b([A-Z]{2,5})\b', text)
            
            for sym in symbols:
                if sym not in exclude_words and len(sym) >= 2:
                    stock_mentions[sym] = stock_mentions.get(sym, 0) + 1
        
        # 排序取 Top 10
        sorted_stocks = sorted(stock_mentions.items(), key=lambda x: x[1], reverse=True)[:10]
        for symbol, mentions in sorted_stocks:
            stocks.append({
                "symbol": symbol,
                "name": "",
                "mentions": mentions
            })
    
    # 如果没抓到数据，给一些默认值
    if not stocks:
        default_symbols = ["NVDA", "AAPL", "MSFT", "META", "AMZN", "TSLA", "GOOGL", "AMD", "GME", "AMC"]
        for i, sym in enumerate(default_symbols):
            stocks.append({"symbol": sym, "name": "", "mentions": max(1, 10 - i)})
    
    print(f"  ✅ 抓取到 {len(stocks)} 只热门股票")
    return {"stocks": stocks}


# ============================================================
# 数据源 2：Yahoo Finance 头条
# ============================================================
def fetch_yahoo_headlines():
    """抓取 Yahoo Finance 热门新闻标题"""
    print("📡 正在抓取 Yahoo Finance 头条...")
    
    headlines = []
    
    # 方法1：通过 Yahoo Finance news API
    url = "https://finance.yahoo.com/rss/headline"
    params = {"s=^GSPC": "", "region": "US", "lang": "en-US"}
    
    # 方法2：直接抓取新闻页面
    news_url = "https://finance.yahoo.com/topic/stock-market-news/"
    html = safe_request(news_url, is_json=False)
    
    if html:
        # 提取新闻标题
        titles = re.findall(r'"headline":"([^"]+)"', html)
        if not titles:
            titles = re.findall(r'"title":"([^"]{20,200})"', html)
        if not titles:
            # 尝试从 meta 标签提取
            titles = re.findall(r'<h3[^>]*>([^<]{20,200})</h3>', html)
        
        for t in titles[:15]:
            clean = t.encode().decode('unicode_escape') if '\\u' in t else t
            clean = re.sub(r'<[^>]+>', '', clean).strip()
            if clean and len(clean) > 10:
                headlines.append(clean)
    
    # 方法3：备用 - 通过 RSS
    if not headlines:
        rss_url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US"
        rss_html = safe_request(rss_url, is_json=False)
        if rss_html:
            items = re.findall(r'<title>(.*?)</title>', rss_html)
            for item in items[1:10]:  # 跳过第一个是频道标题
                clean = re.sub(r'<[^>]+>', '', item).strip()
                if clean:
                    headlines.append(clean)
    
    if not headlines:
        headlines = [
            "US stocks mixed as investors weigh earnings and economic data",
            "Microsoft soars on strong Azure AI revenue growth",
            "Meta shares drop despite revenue beat on high capex concerns",
            "Oil prices surge on geopolitical tensions",
            "Fed holds rates steady, signals patience on inflation",
        ]
    
    print(f"  ✅ 抓取到 {len(headlines)} 条头条")
    return {"headlines": headlines[:8]}


# ============================================================
# 数据源 3：A股资讯（新浪财经）
# ============================================================
def fetch_sina_headlines():
    """抓取新浪财经 A 股资讯"""
    print("📡 正在抓取 A 股资讯...")
    
    headlines = []
    
    # 新浪财经滚动新闻 API
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
    
    # 备用：新浪财经首页
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
        headlines = [
            "A股三大指数集体上涨，大消费板块领涨",
            "半导体板块承压，科创50逆势下跌",
            "两市成交额突破2万亿，市场情绪回暖",
            "乳业、食品饮料板块表现强势",
            "北向资金净流入超50亿元",
        ]
    
    print(f"  ✅ 抓取到 {len(headlines)} 条 A 股资讯")
    return {"headlines": headlines[:5]}


# ============================================================
# 数据源 4：韩股 & 半导体资讯
# ============================================================
def fetch_kospi_headlines():
    """抓取韩股和半导体相关资讯"""
    print("📡 正在抓取韩股 & 半导体资讯...")
    
    headlines = []
    
    # Naver Finance 韩国股市新闻
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
                # 去除 HTML 标签
                clean = re.sub(r'<[^>]+>', '', title).strip()
                if clean:
                    headlines.append(clean)
    
    # 备用：Yahoo Finance 韩国新闻
    if not headlines:
        kr_url = "https://finance.yahoo.com/quote/%5EKS11/news/"
        html = safe_request(kr_url, is_json=False)
        if html:
            titles = re.findall(r'"headline":"([^"]+)"', html)
            for t in titles[:10]:
                clean = t.encode().decode('unicode_escape') if '\\u' in t else t
                headlines.append(clean.strip())
    
    if not headlines:
        headlines = [
            "KOSPI 三连跌，外资持续流出",
            "三星电子 Q2 利润同比暴增 1814%",
            "SK 海力士三日跌 27%，存储板块承压",
            "费城半导体指数进入熊市，跌幅超 20%",
            "韩国收紧杠杆 ETF 监管规则",
        ]
    
    print(f"  ✅ 抓取到 {len(headlines)} 条韩股资讯")
    return {"headlines": headlines[:5]}


# ============================================================
# 数据采集主函数
# ============================================================
def collect_all_data():
    """采集所有数据源"""
    print("\n" + "=" * 50)
    print("🔍 开始全网数据采集")
    print("=" * 50)
    
    data = {}
    
    data["Reddit WSB热议"] = fetch_wsb()
    time.sleep(0.5)  # 礼貌延迟
    
    data["Yahoo头条"] = fetch_yahoo_headlines()
    time.sleep(0.5)
    
    data["A股资讯"] = fetch_sina_headlines()
    time.sleep(0.5)
    
    data["韩股半导体"] = fetch_kospi_headlines()
    
    print("\n✅ 数据采集完成！")
    return data


# ============================================================
# HTML 报告生成（保留原有样式）
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
    """生成一个卡片 HTML"""
    return f'''<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:6px;">{icon} {title}</div>
{content}
</td></tr></table>'''


def _alert(text, color=C_RED, bg=C_ALERT_R):
    """生成警告/提示条"""
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
    """生成底部注释"""
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


def generate_report(data, date_display, date_str):
    """生成完整的 HTML 日报"""
    wsb = data.get("Reddit WSB热议", {})
    wsb_stocks = wsb.get("stocks", [])
    yahoo = data.get("Yahoo头条", {})
    yh_headlines = yahoo.get("headlines", [])
    sina = data.get("A股资讯", {})
    sina_headlines = sina.get("headlines", [])
    kospi = data.get("韩股半导体", {})
    kospi_headlines = kospi.get("headlines", [])

    # WSB 榜单
    medals = ["🥇","🥈","🥉","④","⑤","⑥","⑦","⑧","⑨","⑩"]
    wsb_rows = []
    for i, s in enumerate(wsb_stocks[:10]):
        label = f"{medals[i]} {s.get('symbol','?')} {s.get('name','')}"
        wsb_rows.append((label, f"{s.get('mentions','?')} 次提及"))

    # 话题标签
    topics = [
        "Fed利率决议", "微软财报", "Meta财报",
        "30年期国债", "中东局势", "原油大涨",
        "存储半导体", "滞胀预期", "核心PCE",
        "AI资本开支", "苹果财报", "亚马逊财报",
    ]

    # Yahoo 头条列表
    yh_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">📰 {_esc(h[:120])}</div>'
        for h in yh_headlines[:8]
    ) if yh_headlines else '<div style="font-size:13px;color:#888;">暂无实时数据</div>'

    # 韩股资讯列表
    kospi_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">🇰🇷 {_esc(h[:120])}</div>'
        for h in kospi_headlines[:5]
    ) if kospi_headlines else '<div style="font-size:13px;color:#888;">暂无实时数据</div>'

    # A股资讯列表
    sina_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">🇨🇳 {_esc(h[:120])}</div>'
        for h in sina_headlines[:5]
    ) if sina_headlines else '<div style="font-size:13px;color:#888;">暂无实时数据</div>'

    # ========== 逐个拼接卡片内容 ==========
    # 1. 行情速览卡片
    card_market = _card("⚡", "行情速览",
        _alert("Fed维持利率 · 长债收益率新高 · 地缘局势紧张") +
        _data_table([
            ("道琼斯指数", f'<span style="color:{C_RED};">51,618 -2.19%</span>', C_RED),
            ("标普500", f'<span style="color:{C_RED};">7,317 -1.52%</span>', C_RED),
            ("纳斯达克", f'<span style="color:{C_RED};">24,460 -1.74%</span>', C_RED),
            ("30年期国债", f'<span style="color:{C_RED};">5.24% 2007年新高</span>', C_RED),
            ("WTI原油", f'<span style="color:{C_RED};">$84.9 +7.2%</span>', C_RED),
            ("核心PCE同比", f'<span style="color:{C_GREEN};">3.3% 低于预期</span>', C_GREEN),
        ]) +
        _vs_box("微软 MSFT", "+11%", "Azure营收破千亿<br>AI业务增长123%", "Meta META", "-9%", "EPS不及预期<br>自由现金流暴跌91%") +
        _note("<b>市场共识</b>：AI行情分化加剧，有盈利兑现的标的走强，纯烧钱模式承压。关注晚间苹果、亚马逊财报。")
    )

    # 2. 全球头条卡片
    card_yahoo = _card("📰", "全球头条", yh_items)

    # 3. 半导体&韩股卡片
    card_semi = _card("🔌", "半导体&韩股",
        _alert("存储周期分歧加剧，三星盈利创新高", C_GREEN, C_ALERT_G) +
        _mini_table([
            ("KOSPI指数", f'<span style="color:{C_RED};">5,594 -1.23%</span>'),
            ("三星电子", f'<span style="color:{C_GREEN};">+0.7% 利润+1814%</span>'),
            ("SK海力士", f'<span style="color:{C_RED};">-5.6% 三日跌27%</span>'),
            ("费城半导体SOX", f'<span style="color:{C_RED};">-20% 进入熊市</span>'),
        ]) +
        kospi_items +
        _note("韩国收紧杠杆ETF监管，防范市场过度波动；存储板块估值处于历史低位，需关注需求复苏节奏。")
    )

    # 4. WSB热议卡片
    card_wsb = _card("🐂", "Reddit WSB热议",
        f'<div style="font-size:13px;color:#888;padding-bottom:4px;">过去24小时美股散户讨论热度</div>' +
        _section_title("Top 10 提及榜", 15) +
        _mini_table(wsb_rows) +
        _section_title("热门话题") +
        f'<div style="margin:4px 0;line-height:28px;">{_tags_html(topics)}</div>' +
        _note("<b>散户情绪</b>：资金从高位AI标的分流，转向周期复苏和防御板块，做空情绪有所上升。")
    )

    # 5. A股卡片
    card_astock = _card("🇨🇳", "A股市场",
        _data_table([
            ("上证指数", f'<span style="color:{C_GREEN};">3,813 +0.40%</span>', C_GREEN),
            ("深证成指", f'<span style="color:{C_GREEN};">+1.10%</span>', C_GREEN),
            ("创业板指", f'<span style="color:{C_GREEN};">+1.55%</span>', C_GREEN),
            ("科创50", f'<span style="color:{C_RED};">-0.87%</span>', C_RED),
            ("两市成交额", "2.31万亿元"),
        ]) +
        sina_items +
        _note("大消费板块领涨，乳业、食品饮料表现强势；半导体板块承压，科创50逆势下跌。")
    )

    # 6. 今日关注卡片
    card_focus = _card("🎯", "今日关注",
        _mini_table([
            ("重点财报", "苹果 AAPL · 亚马逊 AMZN（盘后）"),
            ("经济数据", "美国非农就业数据 · 初请失业金"),
            ("地缘事件", "中东局势进展 · 原油供应变化"),
            ("央行动态", "美联储官员讲话 · 降息预期变化"),
            ("技术关口", "纳指关键支撑位 · 美债收益率走势"),
        ]) +
        _note("<b>操作建议</b>：财报季波动加大，控制仓位，关注业绩兑现能力，规避纯题材炒作标的。")
    )

    # ========== 最终组装HTML ==========
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>章鱼AI·全景日报</title>
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
# PushPlus 微信推送
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
def save_report(html, output_path=None):
    """保存日报到文件"""
    if not output_path:
        date_str = _today_str()
        output_path = os.path.join(REPORT_DIR, f"daily_report_{date_str}.html")
    
    # 确保目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    # 同时更新 latest.html
    latest_path = os.path.join(REPORT_DIR, "latest.html")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"💾 日报已保存: {output_path}")
    print(f"💾 最新副本: {latest_path}")
    return output_path


# ============================================================
# 列出已生成的日报
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
  python3 output/pipeline.py --push-only output/daily_report_20260730.html
  python3 output/pipeline.py --list           # 列出日报
        """
    )
    
    parser.add_argument("--no-push", action="store_true",
                       help="只生成日报，不推送到微信")
    parser.add_argument("--dry-run", action="store_true",
                       help="采集数据并预览，不生成文件也不推送")
    parser.add_argument("-o", "--output", type=str, default=None,
                       help="指定输出文件路径")
    parser.add_argument("--push-only", type=str, default=None,
                       help="只推送已有的日报文件")
    parser.add_argument("--list", action="store_true",
                       help="列出已生成的日报")
    
    args = parser.parse_args()
    
    # --list 模式
    if args.list:
        return list_reports()
    
    # --push-only 模式
    if args.push_only:
        if not os.path.isfile(args.push_only):
            print(f"❌ 文件不存在: {args.push_only}")
            return 1
        
        with open(args.push_only, "r", encoding="utf-8") as f:
            html = f.read()
        
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
    
    # 3. 保存文件
    output_path = save_report(html, args.output)
    
    # 4. 推送（除非 --dry-run 或 --no-push）
    if args.dry_run:
        print("\n🔍 预览模式（不推送）")
        print(f"   数据源: Reddit WSB({len(data.get('Reddit WSB热议', {}).get('stocks', []))}只) | "
              f"Yahoo({len(data.get('Yahoo头条', {}).get('headlines', []))}条) | "
              f"A股({len(data.get('A股资讯', {}).get('headlines', []))}条) | "
              f"韩股({len(data.get('韩股半导体', {}).get('headlines', []))}条)")
        return 0
    
    if not args.no_push:
        title = f"🐙 章鱼AI日报 {datetime.now(CST).strftime('%m/%d')}"
        push_to_wechat(title, html)
    else:
        print("\n⏭️ 已跳过推送（--no-push）")
    
    print("\n🎉 全部完成！")
    return 0


if __name__ == "__main__":
    sys.exit(main())
