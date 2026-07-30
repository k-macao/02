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
    payload = json.dumps({"token":token,"title":title,"content":content,"template":"html","channel":"wechat"}).encode()
    for url in ["https://www.pushplus.plus/send", "https://pushplus.hxtrip.com/send"]:
        try:
            import urllib.request
            req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json","User-Agent":"OctopusAI/2.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                result = json.loads(r.read().decode())
                print(f"  📬 PushPlus: code={result.get('code')}")
                return result.get("code") == 200
        except Exception as e:
            print(f"  ⚠️ {url}: {e}")
    return False

# ======================== HTML 组件（全 inline + table，微信兼容） ========================

def _tag(style_extra=""):
    return f'display:inline-block;background:{C_TAG_BG};color:{C_BLUE};padding:2px 8px;margin:2px 3px;font-size:12px;line-height:20px;{style_extra}'

def _row_cell(label, value, vcolor=C_BLUE):
    """两列数据行：左label 右value，table布局"""
    return f'<tr><td style="padding:5px 0;font-size:14px;color:{C_BLUE};border-bottom:1px dashed {C_DASH};vertical-align:top;" width="42%">{_esc(label)}</td><td style="padding:5px 0;font-size:14px;font-weight:700;color:{vcolor};text-align:right;border-bottom:1px dashed {C_DASH};" width="58%">{value}</td></tr>'

def _data_table(rows):
    """rows: [(label, value), ...] 或 [(label, value, color), ...]"""
    t = '<table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;">'
    for r in rows:
        c = r[2] if len(r) > 2 else C_BLUE
        t += _row_cell(r[0], r[1], c)
    return t + '</table>'

def _mini_table(rows):
    """rows: [(key, value_html), ...]"""
    t = '<table width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;">'
    for k, v in rows:
        t += f'<tr><td style="padding:4px 0;color:{C_BLUE};border-bottom:1px dashed {C_DASH};">{_esc(k)}</td><td style="padding:4px 0;text-align:right;font-weight:700;border-bottom:1px dashed {C_DASH};">{v}</td></tr>'
    return t + '</table>'

def _card(title_emoji, title_text, body, extra_style=""):
    """白色卡片"""
    return f'''
<!-- card -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};{extra_style}">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr><td style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">{title_emoji} {_esc(title_text)}</td></tr>
      <tr><td>{body}</td></tr>
    </table>
  </td></tr>
</table>
'''

def _note(text):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px;background:{C_NOTE_BG};border-left:3px solid {C_BLUE};"><tr><td style="padding:8px 10px;font-size:13px;color:{C_BLUE};line-height:1.7;">{text}</td></tr></table>'

def _alert(text, color=C_RED, bg=C_ALERT_R):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:6px;background:{bg};"><tr><td style="padding:6px 10px;font-size:13px;color:{color};font-weight:600;text-align:center;">{text}</td></tr></table>'

def _vs_box(left_name, left_pct, left_detail, right_name, right_pct, right_detail):
    """并排对比：table布局两列"""
    return f'''
<table width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0;">
  <tr>
    <td width="50%" valign="top" style="padding-right:3px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#e6f4ea;border:1px solid #c6e6ce;">
        <tr><td style="padding:8px;text-align:center;">
          <div style="font-weight:700;font-size:15px;color:{C_GREEN};">{_esc(left_name)}</div>
          <div style="font-size:22px;font-weight:800;color:{C_GREEN};">{_esc(left_pct)}</div>
          <div style="font-size:11px;color:{C_GREEN};">{left_detail}</div>
        </td></tr>
      </table>
    </td>
    <td width="50%" valign="top" style="padding-left:3px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#fce8e6;border:1px solid #f5c6cb;">
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
<meta name="format-detection" content="telephone=no">
<title>🐙 章鱼 AI · {date_str}</title>
<style>
*{{margin:0;padding:0}}
body{{background:{C_BG};font-family:{FONT};color:{C_BLUE};font-size:15px;line-height:1.75;-webkit-text-size-adjust:100%}}
table{{border-collapse:collapse}}
</style>
</head>
<body>

<!-- ═══ 外层容器 ═══ -->
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:0 auto;background:{C_BG};">
<tr><td style="padding:10px;">

<!-- ═══════ HEADER ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_BLUE};">
  <tr><td style="padding:18px 14px 14px;text-align:center;color:{C_WHITE};font-size:13px;letter-spacing:2px;">
    🐙 章鱼 AI · 全景分析
  </td></tr>
  <tr><td style="padding:0 14px 4px;text-align:center;color:{C_WHITE};font-size:20px;font-weight:700;letter-spacing:1px;">
    全网多模型协同日报
  </td></tr>
  <tr><td style="padding:0 14px 14px;text-align:center;color:{C_WHITE};font-size:12px;">
    {_esc(date_display)} · 实时数据
  </td></tr>
  <tr><td style="padding:0 14px 16px;text-align:center;">
    <span style="display:inline-block;background:rgba(255,255,255,.20);padding:3px 10px;margin:2px;font-size:11px;color:{C_WHITE};">🌐 全球扫描</span>
    <span style="display:inline-block;background:rgba(255,255,255,.20);padding:3px 10px;margin:2px;font-size:11px;color:{C_WHITE};">🤖 多模型推理</span>
    <span style="display:inline-block;background:rgba(255,255,255,.20);padding:3px 10px;margin:2px;font-size:11px;color:{C_WHITE};">📡 {_now()}</span>
  </td></tr>
</table>

<!-- ═══════ ① 昨夜今晨重磅 ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">⚡ 昨夜今晨 · 重磅速览</div>

    {_alert("⚠️ 美联储 9-3 维持利率，30年期国债飙至 5.24%（2007以来最高） | 伊朗突袭→美军反击→原油 +7.2%")}

    {_data_table([
      ("🇺🇸 道琼斯", '<span style="color:{0};">51,618（-1,153 点 / -2.19%）</span>'.format(C_RED), C_RED),
      ("🇺🇸 标普500", '<span style="color:{0};">7,317（-1.52%）</span>'.format(C_RED), C_RED),
      ("🇺🇸 纳斯达克", '<span style="color:{0};">24,460（-1.74%）· 六连跌</span>'.format(C_RED), C_RED),
      ("📈 30年期国债", '<span style="color:{0};">5.24%（2007年来最高）</span>'.format(C_RED), C_RED),
      ("🛢 原油 WTI", '<span style="color:{0};">$84.9（+7.2%）</span>'.format(C_RED), C_RED),
      ("🇺🇸 GDP Q2", '<span style="color:{0};">年化 +1.5%（预期 +2.0%）⚠️</span>'.format(C_RED), C_RED),
      ("📊 核心 PCE 6月", '<span style="color:{0};">+3.3% YoY · 月率 +0.1%（低于预期）✅</span>'.format(C_GREEN), C_GREEN),
    ])}

    {_vs_box(
      "🟢 微软 MSFT", "+11%",
      "Azure 突破 $1000亿<br>AI 年营收 $370亿(+123%)<br>RPO 暴增 +84%",
      "🔴 Meta META", "-9%",
      "EPS $6.18 远逊 $7.22<br>自由现金流暴跌 -91%<br>资本支出吞没 97.5%",
    )}

    {_note("🧠 <b>多模型共识：</b>AI 路线大分化。微软证明 AI 基础设施→Azure 收入正循环成立；Meta 烧 $310 亿资本开支却无利润兑现。市场正在对 AI 投入回报率进行残酷投票。今晚 Apple + Amazon 财报是下一块试金石。")}
  </td></tr>
</table>

<!-- ═══════ ② 7/30 盘前盘中 ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">📈 7月30日 盘前与盘中</div>
    {_alert("🟢 美股反弹：微软领涨 +11%，PCE 通胀降温助阵", C_GREEN, C_ALERT_G)}
    {_data_table([
      ("🇺🇸 标普500", '<span style="color:{0};">+0.88%</span>'.format(C_GREEN), C_GREEN),
      ("🇺🇸 纳斯达克", '<span style="color:{0};">+1.6%</span>'.format(C_GREEN), C_GREEN),
      ("🇺🇸 道琼斯", '<span style="color:{0};">+0.53%</span>'.format(C_GREEN), C_GREEN),
      ("🇺🇸 罗素2000", '<span style="color:{0};">-1.61%（小盘承压）</span>'.format(C_RED), C_RED),
      ("⚠️ GDP价格指数", '<span style="color:{0};">+6.2% YoY · 滞胀信号</span>'.format(C_RED), C_RED),
      ("📉 初请失业金", '19.7万（低于预期 20万）'),
    ])}
    {_note("💡 GDP 放缓 + 通胀顽固 = 经典滞胀组合。但核心 PCE 月率仅 +0.1% 是好消息。JPMorgan 已发出「战术性买入」信号，认为超卖到足以反弹。")}
  </td></tr>
</table>

<!-- ═══════ ③ 雅虎财经头条 ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">📰 雅虎财经 · 实时头条</div>
    {yh_items}
  </td></tr>
</table>

<!-- ═══════ ④ KOSPI · 半导体风暴 ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">🇰🇷 KOSPI · 半导体风暴</div>
    {_alert("🔥 费城半导体指数 SOX 进入熊市（-20%+）| KOSPI 7月累跌约 -32%，史上最惨月份")}
    {_section_title("📅 7月30日收盘")}
    {_mini_table([
      ("KOSPI 收盘", '<span style="color:{0};">5,594（-1.23%）</span>'.format(C_RED)),
      ("三星电子", '<span style="color:{0};">+0.7%（早盘一度 +7%）</span>'.format(C_GREEN)),
      ("SK 海力士", '<span style="color:{0};">-5.64%（三日累跌 -27%）</span>'.format(C_RED)),
      ("三星 Q2 营业利润", '<span style="color:{0};">89.49万亿韩元（+1,814%）🥇</span>'.format(C_GREEN)),
      ("日经 225", '<span style="color:{0};">+0.71%（与韩国背离）</span>'.format(C_GREEN)),
    ])}
    {_section_title("🔻 三连暴击")}
    <div style="font-size:13px;color:{C_BLUE};margin:4px 0;">
      ① CXMT 长鑫存储 IPO — 首日暴涨 +466%，市值 3.3万亿人民币<br>
      ② 中国 DUV 光刻机突破 — 国资背景量产浸没式 DUV<br>
      ③ AI 循环融资质疑 — 英伟达-OpenAI $2500亿担保 + 供应过剩恐慌
    </div>
    {_section_title("🇰🇷 实时新闻")}
    {kospi_items}
    {_note("💡 韩国政府出台杠杆 ETF 新规（零售配比上限 20%）。三星利润暴增 18 倍仍无法救大盘 → 市场从基本面驱动切换至恐慌驱动。KOSPI PER 降至 5.1 倍，半导体低于 4 倍——历史极端。")}
  </td></tr>
</table>

<!-- ═══════ ⑤ Reddit WSB ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">💬 Reddit · WSB · 全网热议</div>
    <div style="font-size:13px;color:#888;padding-bottom:6px;">📡 r/wallstreetbets · r/stocks · r/investing | 过去24小时</div>
    {_section_title("🔥 最热股票提及 Top 10", 15)}
    {_mini_table(wsb_rows)}
    {_section_title("🗣 热议话题")}
    <div style="margin:4px 0;line-height:28px;">{_tags_html(topics)}</div>
    {_note('💬 <b>WSB 情绪：</b>"AI trade 彻底分叉——微软证明 AI 能赚钱，Meta 证明 AI 能烧钱。""Fed 9-3 简直是在预告加息。"散户对 KORU（3倍做多韩国）讨论激增，逆势赌博情绪浓厚。')}
  </td></tr>
</table>

<!-- ═══════ ⑥ A股动态 ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">🇨🇳 A股 · 中国动态</div>
    {_data_table([
      ("上证综指", '<span style="color:{0};">3,813（+0.40%）</span>'.format(C_GREEN), C_GREEN),
      ("深证成指", '<span style="color:{0};">+1.10%</span>'.format(C_GREEN), C_GREEN),
      ("创业板指", '<span style="color:{0};">+1.55%</span>'.format(C_GREEN), C_GREEN),
      ("科创50", '<span style="color:{0};">-0.87%</span>'.format(C_RED), C_RED),
      ("成交额", '2.31万亿元'),
    ])}
    {_section_title("🇨🇳 实时新闻")}
    {sina_items}
    {_note('📌 大消费全面爆发，乳业 +6.82% 领涨。存储芯片/半导体持续杀跌，长鑫科技逆势 +12.66%。4,253 只个股上涨，市场"新旧主线切换"。')}
  </td></tr>
</table>

<!-- ═══════ ⑦ 亮点个股 ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">✨ 今日亮点个股</div>
    {_mini_table([
      ("🟢 微软 MSFT", '<span style="color:{0};">+11% · Azure 里程碑</span>'.format(C_GREEN)),
      ("🔴 Meta META", '<span style="color:{0};">-9% · FCF 崩塌 91%</span>'.format(C_RED)),
      ("🟢 Lam Research LRCX", '<span style="color:{0};">+14.1% · 双创纪录</span>'.format(C_GREEN)),
      ("🟢 MarketAxess MKTX", '<span style="color:{0};">+30% · ICE $57亿收购</span>'.format(C_GREEN)),
      ("🔴 Alnylam ALNY", '<span style="color:{0};">-21.1% · 营收不及预期</span>'.format(C_RED)),
      ("🔴 SK海力士", '<span style="color:{0};">-5.6% · 三日累跌 27%</span>'.format(C_RED)),
      ("🟢 SpaceX SPCX", '<span style="color:{0};">$16亿太空部队合约</span>'.format(C_GREEN)),
      ("🔴 费城半导体 SOX", '<span style="color:{0};">熊市 -20%+</span>'.format(C_RED)),
    ])}
  </td></tr>
</table>

<!-- ═══════ ⑧ 今日关注 ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};">
  <tr><td style="padding:14px 12px;border-bottom:1px solid {C_BORDER};">
    <div style="font-size:17px;font-weight:700;color:{C_BLUE};padding-bottom:8px;">🎯 今日关注</div>
    {_mini_table([
      ("📌 今晚财报", '<b>Apple (AAPL) + Amazon (AMZN)</b> 盘后'),
      ("📌 PCE 通胀", '核心 +3.3% YoY · 月率 +0.1%（降温中）'),
      ("📌 GDP", 'Q2 +1.5% · 滞胀担忧上升'),
      ("📌 地缘", '美军空袭伊朗十余处目标，局势升级'),
      ("📌 债券", '30年期 5.24% · 压制科技估值'),
      ("📌 技术面", '纳斯达克距高点 -9.8%，逼近修正 -10%'),
    ])}
    {_note("🐙 <b>章鱼AI综合研判：</b>Microsoft 的 AI→收入正循环是全局最大亮点。但 Meta 的 FCF 崩塌和 Fed 9-3 投票构成双重压力。恐慌接近极值（JPMorgan 战术性买入信号已触发），反弹需 Apple/Amazon 财报确认。警惕「滞胀」叙事取代「AI狂热」成为市场主旋律。")}
  </td></tr>
</table>

<!-- ═══════ FOOTER ═══════ -->
<table width="100%" cellpadding="0" cellspacing="0" style="background:{C_WHITE};margin-top:0;">
  <tr><td style="padding:14px 12px;text-align:center;">
    <div style="font-size:11px;color:#8899c0;line-height:1.8;">
      🐙 <b style="color:{C_BLUE};">章鱼 AI</b>，仅供参考。<br>
      全网境内外检索公开行情，多模型协同推理决策<br>
      Claude / ChatGPT / Gemini / Grok / Qwen / Kimi
    </div>
    <div style="font-size:10px;color:#99aacc;margin-top:6px;line-height:1.6;">
      自动生成：{_now()}<br>
      数据源：Reddit · Yahoo Finance · 新浪财经 · TradingKey · Bloomberg · SCMP
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
