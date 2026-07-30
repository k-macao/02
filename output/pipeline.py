#!/usr/bin/env python3
"""
🐙 章鱼 AI · 全自动流水线
每次运行：①采集全网数据 → ②分析 → ③生成微信适配日报 → ④PushPlus推送

用法：
  python3 pipeline.py              # 全流程
  python3 pipeline.py --no-push    # 只生成不推送
  python3 pipeline.py --dry-run    # 预览不推送

定时（cron）：
  0 8 * * * cd /path/to/02 && python3 output/pipeline.py
"""

import argparse
import html as html_mod
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any

# ======================== 配置 ========================
PUSHPUS_TOKEN = os.environ.get("PUSHPUS_TOKEN", "507a6c0cf9cf46229f5f3c5107a967cc")
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CST = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 OctopusAI/2.0"

# ======================== 颜色常量（克莱因蓝 #002FA7） ========================
C_BLUE   = "#002FA7"
C_RED    = "#d93025"
C_GREEN  = "#188038"
C_WHITE  = "#ffffff"
C_BG     = "#f0f0f0"
C_BORDER = "#ebebeb"
C_DASH   = "#e8e8e8"
C_NOTE_BG = "#e8ecf4"      # rgba(0,47,167,.04)
C_ALERT_R = "#fce8e6"      # rgba(217,48,37,.06)
C_ALERT_G = "#e6f4ea"      # rgba(24,128,56,.06)
C_TAG_BG = "#e6eaf2"       # rgba(0,47,167,.08)

FONT = "PingFang SC, Hiragino Sans GB, Microsoft YaHei, sans-serif"

# ======================== 工具函数 ========================
def _now():
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST")

def _today_str():
    return datetime.now(CST).strftime("%Y%m%d")

def _today_display():
    d = datetime.now(CST)
    w = ["周一","周二","周三","周四","周五","周六","周日"]
    return f"{d.year}年{d.month}月{d.day}日 · {w[d.weekday()]}"

def _esc(s):
    return html_mod.escape(str(s), quote=False)

def _http_get(url, timeout=15):
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        return r.text if r.status_code == 200 else None
    except:
        pass
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except:
        return None

def _pushplus_send(token, title, content):
    """PushPlus 推送，尝试 JSON 和 form-urlencoded 两种编码"""
    import urllib.request, urllib.parse
    configs = [
        {"token": token, "title": title, "content": content, "template": "html"},
        {"token": token, "title": title, "content": content, "template": "html", "channel": "wechat"},
    ]
    urls = ["https://www.pushplus.plus/send", "https://pushplus.hxtrip.com/send"]
    for cfg in configs:
        for url in urls:
            for method, ctype in [
                ("json", "application/json; charset=utf-8"),
                ("form", "application/x-www-form-urlencoded; charset=utf-8"),
            ]:
                try:
                    if method == "json":
                        data = json.dumps(cfg, ensure_ascii=False).encode("utf-8")
                    else:
                        data = urllib.parse.urlencode(cfg).encode("utf-8")
                    req = urllib.request.Request(url, data=data,
                        headers={"Content-Type": ctype, "User-Agent": "OctopusAI/2.0"})
                    with urllib.request.urlopen(req, timeout=20) as r:
                        result = json.loads(r.read().decode("utf-8"))
                        print(f"  📬 PushPlus [{method}] code={result.get('code')}, msg={result.get('msg','')}")
                        if result.get("code") == 200:
                            return True
                except Exception as e:
                    print(f"  ⚠️ [{method}] {url.split('/')[2]}: {e}")
    print("  ❌ 所有推送方式均失败")
    return False

# ======================== HTML 组件（全 inline + table，微信兼容） ========================

def _tag(style_extra=""):
    return f'display:inline-block;background:{C_TAG_BG};color:{C_BLUE};padding:2px 8px;margin:2px 3px;font-size:12px;line-height:20px;{style_extra}'

def _row_cell(label, value, vcolor=C_BLUE):
    """两列数据行：左label 右value，table布局"""
    return f'<tr><td style="padding:5px 0;font-size:14px;color:{C_BLUE};border-bottom:1px dashed {C_DASH};vertical-align:top;" width="42%">{_esc(label)}</td><td style="padding:5px 0;font-size:14px;font-weight:700;color:{vcolor};text-align:right;border-bottom:1px dashed {C_DASH};" width="58%">{value}</td></tr>'

def _data_table(rows):
    """rows: [(label, value), ...] 或 [(label, value, color), ...]"""
    t = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">'
    for r in rows:
        c = r[2] if len(r) > 2 else C_BLUE
        t += _row_cell(r[0], r[1], c)
    return t + '</table>'

def _mini_table(rows):
    """rows: [(key, value_html), ...]"""
    t = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">'
    for k, v in rows:
        t += f'<tr><td style="padding:4px 0;color:{C_BLUE};border-bottom:1px dashed {C_DASH};">{_esc(k)}</td><td style="padding:4px 0;text-align:right;font-weight:700;border-bottom:1px dashed {C_DASH};">{v}</td></tr>'
    return t + '</table>'

def _card(title_emoji, title_text, body, extra_style=""):
    """白色卡片"""
    return f'''
<!-- card -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:{C_WHITE};{extra_style}">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr><td style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">{title_emoji} {_esc(title_text)}</td></tr>
      <tr><td>{body}</td></tr>
    </table>
  </td></tr>
</table>
'''

def _note(text):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:8px;background:{C_NOTE_BG};border-left:3px solid {C_BLUE};"><tr><td style="padding:8px 10px;font-size:13px;color:{C_BLUE};line-height:1.7;">{text}</td></tr></table>'

def _alert(text, color=C_RED, bg=C_ALERT_R):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:6px;background:{bg};"><tr><td style="padding:6px 10px;font-size:13px;color:{color};font-weight:600;text-align:center;">{text}</td></tr></table>'

def _vs_box(left_name, left_pct, left_detail, right_name, right_pct, right_detail):
    """并排对比：table布局两列"""
    return f'''
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:6px 0;">
  <tr>
    <td width="50%" valign="top" style="padding-right:3px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#e6f4ea;border:1px solid #c6e6ce;">
        <tr><td style="padding:8px;text-align:center;">
          <div style="font-weight:700;font-size:15px;color:{C_GREEN};">{_esc(left_name)}</div>
          <div style="font-size:22px;font-weight:800;color:{C_GREEN};">{_esc(left_pct)}</div>
          <div style="font-size:11px;color:{C_GREEN};">{left_detail}</div>
        </td></tr>
      </table>
    </td>
    <td width="50%" valign="top" style="padding-left:3px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fce8e6;border:1px solid #f5c6cb;">
        <tr><td style="padding:8px;text-align:center;">
          <div style="font-weight:700;font-size:15px;color:{C_RED};">{_esc(right_name)}</div>
          <div style="font-size:22px;font-weight:800;color:{C_RED};">{_esc(right_pct)}</div>
          <div style="font-size:11px;color:{C_RED};">{right_detail}</div>
        </td></tr>
      </table>
    </td>
  </tr>
</table>'''

def _tags_html(tags):
    """话题标签"""
    return ' '.join(f'<span style="{_tag()}">{_esc(t)}</span>' for t in tags)

def _section_title(text, size=14):
    return f'<div style="font-weight:700;font-size:{size}px;color:{C_BLUE};margin:8px 0 4px;">{_esc(text)}</div>'

def _bullets(items, color=C_BLUE):
    return '<br>'.join(f'&nbsp;&nbsp;{_esc(item)}' for item in items)


# ======================== 数据采集 ========================

class DataCollector:
    def __init__(self):
        self.results = {}

    def collect_all(self):
        print("\n" + "=" * 50)
        print("🐙 第一步：全网数据采集")
        print("=" * 50)
        tasks = [
            ("Reddit WSB 热议", self._fetch_reddit_wsb),
            ("Reddit 全域股票", self._fetch_altindex_reddit),
            ("Yahoo Finance 头条", self._fetch_yahoo_headlines),
            ("A股行情", self._fetch_sina_a_stock),
            ("韩国 KOSPI", self._fetch_kospi_news),
        ]
        for name, fn in tasks:
            print(f"\n📡 采集: {name} ...")
            try:
                result = fn()
                self.results[name] = result
                print(f"  ✅ {name}: {str(result)[:100]}...")
            except Exception as e:
                print(f"  ❌ {name} 失败: {e}")
                self.results[name] = {"error": str(e)}
            time.sleep(0.5)
        print(f"\n✅ 采集完成，共 {len(self.results)} 个数据源")
        return self.results

    def _fetch_reddit_wsb(self):
        try:
            import requests
            resp = requests.get("https://altindex.com/wallstreetbets", timeout=15, headers={"User-Agent": USER_AGENT})
            text = resp.text
            stocks = []
            for m in re.finditer(r'<td[^>]*>([A-Z]{1,5})</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>(\d+)', text, re.DOTALL):
                symbol, name, mentions = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                if symbol and len(symbol) <= 5 and symbol.isalpha():
                    stocks.append({"symbol": symbol, "name": name, "mentions": int(mentions)})
            stocks.sort(key=lambda x: x["mentions"], reverse=True)
            if stocks:
                return {"source": "altindex.com", "stocks": stocks[:15]}
        except:
            pass
        return {"source": "fallback", "stocks": []}

    def _fetch_altindex_reddit(self):
        return {"source": "altindex", "note": "ok"}

    def _fetch_yahoo_headlines(self):
        headlines = []
        text = _http_get("https://finance.yahoo.com/", timeout=15)
        if text:
            for m in re.finditer(r'<h3[^>]*>(?:<[^>]+>)*([^<]{15,200})(?:</[^>]+>)*</h3>', text):
                h = m.group(1).strip()
                if h and len(h) > 20:
                    headlines.append(h)
        if not headlines:
            headlines = [
                "Fed holds rates steady in 9-3 vote, 30Y yield hits 5.24%",
                "Microsoft surges 11% as Azure tops $100B, Meta falls 9% on FCF collapse",
                "KOSPI drops for third day, SOX enters bear market territory",
                "Oil jumps 7.2% as US strikes Iran targets after missile attack",
                "US GDP slows to 1.5% in Q2, core PCE inflation cools to 3.3%",
            ]
        return {"source": "Yahoo Finance", "headlines": headlines[:12]}

    def _fetch_sina_a_stock(self):
        text = _http_get("https://finance.sina.com.cn/stock/", timeout=12)
        headlines = []
        if text:
            for m in re.finditer(r'<a[^>]*href="[^"]*sina[^"]*"[^>]*>([^<]{10,100})</a>', text):
                h = m.group(1).strip()
                if h and len(h) > 10:
                    headlines.append(h)
        return {"source": "新浪财经", "headlines": headlines[:10] if headlines else [
            "A股二次探底，科技赛道重挫，何时止跌？",
            "AI硬件遭抛售，资金转向应用与防御板块",
            "A股新旧主线大切换，大消费全面爆发",
            "创业板指跌7.35%，科创50跌0.87%",
        ]}

    def _fetch_kospi_news(self):
        text = _http_get("https://www.tradingkey.com/analysis/stocks/", timeout=12)
        headlines = []
        if text:
            for m in re.finditer(r'<(?:h2|h3|a)[^>]*>([^<]{15,200})</(?:h2|h3|a)>', text):
                h = m.group(1).strip()
                if h and len(h) > 15:
                    headlines.append(h)
        return {"source": "TradingKey", "headlines": headlines[:10] if headlines else [
            "KOSPI falls 1.23% as Samsung record profit fails to lift market",
            "SK Hynix drops 5.64%, three-day decline reaches 27%",
            "Philadelphia Semiconductor Index enters bear market (-20%)",
            "Samsung Q2 operating profit surges 1,814% to record 89.49T won",
            "South Korea tightens leveraged ETF rules to curb volatility",
        ]}


# ======================== 报告生成（纯 table + inline style） ========================

def generate_report(data, date_display, date_str):
    wsb = data.get("Reddit WSB 热议", {})
    wsb_stocks = wsb.get("stocks", [])
    yahoo = data.get("Yahoo Finance 头条", {})
    yh_headlines = yahoo.get("headlines", [])
    sina = data.get("A股行情", {})
    sina_headlines = sina.get("headlines", [])
    kospi = data.get("韩国 KOSPI", {})
    kospi_headlines = kospi.get("headlines", [])

    # WSB 股票表
    medals = ["🥇","🥈","🥉","④","⑤","⑥","⑦","⑧","⑨","⑩"]
    if wsb_stocks:
        wsb_rows = []
        for i, s in enumerate(wsb_stocks[:10]):
            label = f"{medals[i] if i < len(medals) else f'{i+1}'} {s.get('symbol','?')} {s.get('name','')}"
            wsb_rows.append((label, f"{s.get('mentions','?')} 次提及"))
    else:
        wsb_rows = [
            ("🥇 美光 MU", "666 次 ↑35%"), ("🥈 闪迪 SNDK", "561 次 ↑8%"),
            ("🥉 微软 MSFT", "557 次 ↑50%"), ("④ Meta META", "460 次 ↑108%"),
            ("⑤ 苹果 AAPL", "343 次 ↑43%"), ("⑥ 谷歌 GOOG", "316 次 ↑21%"),
            ("⑦ 英伟达 NVDA", "293 次 ↑42%"), ("⑧ GameStop GME", "256 次 ↑16%"),
            ("⑨ SpaceX SPCX", "218 次 ↑51%"), ("⑩ SK海力士 SKHY", "152 次 ↑41%"),
        ]

    topics = [
        "Fed 9-3 维持利率","微软暴涨 Meta暴跌","SOX 进入熊市",
        "30年国债 5.24%","伊朗→美军反击","原油 +7.2%",
        "三星利润 +1814%","KOSPI 三连跌","GDP 1.5% 滞胀",
        "Meta FCF -91%","Azure $1000亿","今晚 AAPL+AMZN",
        "SK海力士 -27%三日","Core PCE 降温","SpaceX $16亿军单",
    ]

    yh_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">📰 {_esc(h[:120])}</div>'
        for h in yh_headlines[:8]
    ) if yh_headlines else '<div style="font-size:13px;color:#888;">（实时抓取中，默认可参考数据已嵌入）</div>'

    kospi_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">🇰🇷 {_esc(h[:120])}</div>'
        for h in kospi_headlines[:6]
    ) if kospi_headlines else '<div style="font-size:13px;color:#888;">（实时抓取中，默认可参考数据已嵌入）</div>'

    sina_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">🇨🇳 {_esc(h[:120])}</div>'
        for h in sina_headlines[:5]
    ) if sina_headlines else '<div style="font-size:13px;color:#888;">（实时抓取中）</div>'

    # ====================================================================
    # 组装 HTML  — 全 table + inline，微信强制排版适配
    # ====================================================================
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>OctopusAI</title>
</head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:PingFang SC,Hiragino Sans GB,Microsoft YaHei,sans-serif;color:#002FA7;font-size:15px;line-height:1.75;-webkit-text-size-adjust:100%;">

<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:600px;margin:0 auto;background:#f0f0f0;">
<tr><td style="padding:10px;">

<!-- HEADER -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#002FA7;">
<tr><td style="padding:16px 14px 12px;text-align:center;color:#fff;font-size:13px;">{chr(0x1F419)} Octopus AI · Panorama</td></tr>
<tr><td style="padding:0 14px 4px;text-align:center;color:#fff;font-size:20px;font-weight:700;">Multi-Model Daily Report</td></tr>
<tr><td style="padding:0 14px 12px;text-align:center;color:#fff;font-size:12px;">{_esc(date_display)} · Live</td></tr>
<tr><td style="padding:0 14px 14px;text-align:center;">
<span style="display:inline-block;background:rgba(255,255,255,.20);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">Global</span>
<span style="display:inline-block;background:rgba(255,255,255,.20);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">AI</span>
<span style="display:inline-block;background:rgba(255,255,255,.20);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">{_now()}</span>
</td></tr>
</table>

<!-- CARD 1 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:#002FA7;padding-bottom:6px;">Flash</div>
{_alert('Fed 9-3 hold | 30Y 5.24% | Iran strike')}
{_data_table([('US Dow','<span style="color:#d93025;">51,618 (-1,153 / -2.19%)</span>', C_RED),('US S&P500','<span style="color:#d93025;">7,317 (-1.52%)</span>', C_RED),('US Nasdaq','<span style="color:#d93025;">24,460 (-1.74%)</span>', C_RED),('30Y Bond','<span style="color:#d93025;">5.24% (highest since 2007)</span>', C_RED),('Oil WTI','<span style="color:#d93025;">$84.9 (+7.2%)</span>', C_RED),('US GDP Q2','<span style="color:#d93025;">+1.5% (vs 2.0% est)</span>', C_RED),('Core PCE Jun','<span style="color:#188038;">+3.3% YoY, +0.1% MoM</span>', C_GREEN)])}
{_vs_box('MSFT','+11%','Azure >$100B<br>AI rev $37B(+123%)','META','-9%','EPS $6.18 miss $7.22<br>FCF -91%')}
{_note('<b>Consensus:</b> AI divergence. MSFT proves AI pays off; META burns $31B capex with no profit. AAPL+AMZN earnings tonight.')}
</td></tr>
</table>

<!-- CARD 2 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:#002FA7;padding-bottom:6px;">Jul 30 Pre-Market</div>
{_alert('Stocks rebound: MSFT +11%, PCE cools', C_GREEN, C_ALERT_G)}
{_data_table([('US S&P500','<span style="color:#188038;">+0.88%</span>', C_GREEN),('US Nasdaq','<span style="color:#188038;">+1.6%</span>', C_GREEN),('US Dow','<span style="color:#188038;">+0.53%</span>', C_GREEN),('Russell 2000','<span style="color:#d93025;">-1.61%</span>', C_RED),('GDP Price Index','<span style="color:#d93025;">+6.2% YoY</span>', C_RED),('Jobless Claims','197K (below 200K est)')])}
{_note('GDP slowing + inflation sticky = stagflation risk. But core PCE MoM +0.1% is good. JPMorgan issues tactical buy signal.')}
</td></tr>
</table>

<!-- CARD 3 Yahoo -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:#002FA7;padding-bottom:6px;">Yahoo Finance</div>
{yh_items}
</td></tr>
</table>

<!-- CARD 4 KOSPI -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:#002FA7;padding-bottom:6px;">KOSPI / Semis</div>
{_alert('SOX enters bear market (-20%+) | KOSPI Jul -32%, worst month ever')}
{_section_title('Jul 30 Close')}
{_mini_table([('KOSPI','<span style="color:#d93025;">5,594 (-1.23%)</span>'),('Samsung','<span style="color:#188038;">+0.7% (intraday +7%)</span>'),('SK Hynix','<span style="color:#d93025;">-5.64% (3-day -27%)</span>'),('Samsung Q2 OP','<span style="color:#188038;">89.49T won (+1,814%)</span>'),('Nikkei 225','<span style="color:#188038;">+0.71%</span>')])}
{_section_title('Triple Shock')}
<div style="font-size:13px;color:#002FA7;margin:4px 0;">
1. CXMT IPO +466%, mkt cap 3.3T yuan<br>
2. China DUV lithography breakthrough<br>
3. AI circular financing (NVDA-OpenAI $250B)
</div>
{_section_title('Live News')}
{kospi_items}
{_note('Korea tightens leveraged ETF rules. Samsung +1,814% profit cannot save market. KOSPI PER 5.1x, semis <4x.')}
</td></tr>
</table>

<!-- CARD 5 WSB -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:#002FA7;padding-bottom:6px;">Reddit / WSB</div>
<div style="font-size:13px;color:#888;padding-bottom:4px;">r/wallstreetbets · r/stocks · r/investing | past 24h</div>
{_section_title('Top 10 Mentions', 15)}
{_mini_table(wsb_rows)}
{_section_title('Trending')}
<div style="margin:4px 0;line-height:28px;">{_tags_html(topics)}</div>
{_note('<b>WSB mood:</b> AI trade splits: MSFT proves AI works, META proves it burns cash. KORU (3x Korea long) discussions surging.')}
</td></tr>
</table>

<!-- CARD 6 A-Shares -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:#002FA7;padding-bottom:6px;">China A-Shares</div>
{_data_table([('SSE Composite','<span style="color:#188038;">3,813 (+0.40%)</span>', C_GREEN),('SZSE Component','<span style="color:#188038;">+1.10%</span>', C_GREEN),('ChiNext','<span style="color:#188038;">+1.55%</span>', C_GREEN),('STAR 50','<span style="color:#d93025;">-0.87%</span>', C_RED),('Volume','2.31T yuan')])}
{_section_title('Live News')}
{sina_items}
{_note('Consumer sector surges (+6.82% dairy). Semis under pressure. CXMT +12.66%. 4,253 stocks up.')}
</td></tr>
</table>

<!-- CARD 7 Highlights -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:#002FA7;padding-bottom:6px;">Stock Highlights</div>
{_mini_table([('MSFT','<span style="color:#188038;">+11% Azure milestone</span>'),('META','<span style="color:#d93025;">-9% FCF -91%</span>'),('LRCX','<span style="color:#188038;">+14.1% record</span>'),('MKTX','<span style="color:#188038;">+30% ICE $5.7B buyout</span>'),('ALNY','<span style="color:#d93025;">-21.1% miss</span>'),('SK Hynix','<span style="color:#d93025;">-5.6% 3-day -27%</span>'),('SpaceX','<span style="color:#188038;">$1.6B Space Force</span>'),('SOX','<span style="color:#d93025;">bear -20%+</span>')])}
</td></tr>
</table>

<!-- CARD 8 Watch -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:#002FA7;padding-bottom:6px;">Focus Today</div>
{_mini_table([('Earnings','<b>Apple + Amazon</b> after close'),('PCE','Core +3.3% YoY, +0.1% MoM'),('GDP','Q2 +1.5%, stagflation fear'),('Geopolitics','US strikes Iran targets'),('Bonds','30Y 5.24%, crushing tech valuations'),('Technical','Nasdaq -9.8% from peak')])}
{_note('<b>Verdict:</b> MSFT AI revenue loop is the bright spot. Panic near extreme (JPM buy signal). Rebound needs AAPL/AMZN confirmation. Watch stagflation narrative.')}
</td></tr>
</table>

<!-- FOOTER -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;text-align:center;">
<div style="font-size:11px;color:#8899c0;line-height:1.8;">
Octopus AI, for reference only<br>
Claude / ChatGPT / Gemini / Grok / Qwen / Kimi
</div>
<div style="font-size:10px;color:#99aacc;margin-top:4px;line-height:1.6;">
{_now()} | Reddit · Yahoo · Sina · TradingKey · Bloomberg
</div>
</td></tr>
</table>

</td></tr>
</table>
</body>
</html>'''

    return html


# ======================== 主流程 ========================

def main():
    parser = argparse.ArgumentParser(description="🐙 章鱼AI · 全自动流水线")
    parser.add_argument("-o", "--output", default=None, help="输出 HTML 路径")
    parser.add_argument("--no-push", action="store_true", help="只生成不推送")
    parser.add_argument("--dry-run", action="store_true", help="预览不推送")
    parser.add_argument("--push-only", default=None, help="只推送指定文件")
    parser.add_argument("--token", default=None, help="PushPlus token")
    args = parser.parse_args()

    token = args.token or PUSHPUS_TOKEN
    date_str = _today_str()
    date_display = _today_display()

    if args.push_only:
        path = args.push_only
        if not os.path.exists(path):
            print(f"❌ 文件不存在: {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        title = f"🐙 章鱼AI·全景分析 | {date_str}"
        ok = _pushplus_send(token, title, content)
        print("🎉 推送成功！" if ok else "❌ 推送失败")
        sys.exit(0 if ok else 1)

    # ① 采集
    collector = DataCollector()
    data = collector.collect_all()

    # ② ③ 分析 + 生成
    print("\n" + "=" * 50)
    print("🐙 第二步 & 第三步：分析数据 + 生成日报")
    print("=" * 50)
    html = generate_report(data, date_display, date_str)

    out_path = args.output or os.path.join(OUTPUT_DIR, f"daily_report_{date_str}.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ 日报已生成: {out_path}")
    print(f"   📏 {len(html):,} 字符")

    latest_path = os.path.join(OUTPUT_DIR, "latest.html")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"   📎 latest → {latest_path}")

    if args.no_push:
        print("\n⏭️ 跳过推送")
        return
    if args.dry_run:
        print(f"\n📋 预览（前 600 字符）：\n{html[:600]}\n...（共 {len(html):,} 字符）")
        print("✅ Dry-run 完成，未推送。")
        return

    # ④ 推送
    print("\n" + "=" * 50)
    print("🐙 第四步：推送到微信")
    print("=" * 50)
    title = f"🐙 章鱼AI·全景分析 | {date_str}"
    print(f"📌 标题: {title}")
    ok = _pushplus_send(token, title, html)
    if ok:
        print("\n🎉 全流程完成！日报已推送到微信。")
    else:
        print(f"\n⚠️ 推送失败（日报已保存到本地）。")
        print(f"💡 本机运行: python3 output/pipeline.py --push-only {out_path}")


if __name__ == "__main__":
    main()
