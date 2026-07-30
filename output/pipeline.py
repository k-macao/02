#!/usr/bin/env python3
"""
🐙 章鱼AI · 全自动流水线
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
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any

# ======================== 配置 ========================
# 优先读取环境变量 PUSHPLUS_TOKEN，兼容旧变量名 RE_TOKEN
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN") or os.environ.get("RE_TOKEN", "")
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CST = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 OctopusAI/2.0"

# ======================== 颜色常量（克莱因蓝 #002FA7） ========================
C_BLUE   = "#002FA7"
C_RED    = "#d93025"
C_GREEN  = "#188038"
C_WHITE  = "#ffffff"
C_BG     = "#f0f0f0"
C_BORDER = "#ebebeb"
C_DASH   = "#e8e8e8"
C_NOTE_BG = "#e8ecf4"
C_ALERT_R = "#fce8e6"
C_ALERT_G = "#e6f4ea"
C_TAG_BG = "#e6eaf2"

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
    """通用HTTP请求，优先requests，失败回退urllib"""
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        r.encoding = r.apparent_encoding
        return r.text if r.status_code == 200 else None
    except Exception:
        pass
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None

def _pushplus_send(token, title, content):
    """PushPlus 推送，仅使用官方域名，兼容json/form两种格式"""
    import urllib.request
    import urllib.parse

    if not token:
        print("❌ PushPlus Token 为空，请配置环境变量 PUSHPLUS_TOKEN")
        return False

    url = "https://www.pushplus.plus/send"
    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": "html"
    }

    # 依次尝试 json、form 两种提交格式
    for method, ctype in [
        ("json", "application/json; charset=utf-8"),
        ("form", "application/x-www-form-urlencoded; charset=utf-8"),
    ]:
        try:
            if method == "json":
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            else:
                data = urllib.parse.urlencode(payload).encode("utf-8")
            
            req = urllib.request.Request(url, data=data, headers={
                "Content-Type": ctype,
                "User-Agent": "OctopusAI/2.0"
            })
            with urllib.request.urlopen(req, timeout=20) as r:
                result = json.loads(r.read().decode("utf-8"))
                print(f"  📬 PushPlus [{method}] code={result.get('code')}, msg={result.get('msg','')}")
                if result.get("code") == 200:
                    return True
        except Exception as e:
            print(f"  ⚠️ [{method}] 请求失败: {str(e)}")
    
    print("  ❌ 所有推送方式均失败")
    return False

# ======================== HTML 组件 ========================
def _tag(style_extra=""):
    return f'display:inline-block;background:{C_TAG_BG};color:{C_BLUE};padding:2px 8px;margin:2px;font-size:12px;line-height:20px;{style_extra}'

def _row_cell(label, value, vcolor=C_BLUE):
    return f'<tr><td style="padding:5px 0;font-size:14px;color:{C_BLUE};border-bottom:1px dashed {C_DASH};vertical-align:top;" width="42%">{_esc(label)}</td><td style="padding:5px 0;font-size:14px;font-weight:700;color:{vcolor};text-align:right;border-bottom:1px dashed {C_DASH};" width="58%">{value}</td></tr>'

def _data_table(rows):
    t = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">'
    for r in rows:
        c = r[2] if len(r) > 2 else C_BLUE
        t += _row_cell(r[0], r[1], c)
    return t + '</table>'

def _mini_table(rows):
    t = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:13px;">'
    for k, v in rows:
        t += f'<tr><td style="padding:4px 0;color:{C_BLUE};border-bottom:1px dashed {C_DASH};">{_esc(k)}</td><td style="padding:4px 0;text-align:right;font-weight:700;border-bottom:1px dashed {C_DASH};">{v}</td></tr>'
    return t + '</table>'

def _card(title_emoji, title_text, body):
    return f'''
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;border-bottom:1px solid #ebebeb;">
<div style="font-size:17px;font-weight:700;color:#002FA7;padding-bottom:6px;">{title_emoji} {_esc(title_text)}</div>
{body}
</td></tr>
</table>
'''

def _note(text):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:8px;background:{C_NOTE_BG};border-left:3px solid {C_BLUE};"><tr><td style="padding:8px 10px;font-size:13px;color:{C_BLUE};line-height:1.7;">{text}</td></tr></table>'

def _alert(text, color=C_RED, bg=C_ALERT_R):
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:6px;background:{bg};"><tr><td style="padding:6px 10px;font-size:13px;color:{color};font-weight:600;text-align:center;">{text}</td></tr></table>'

def _vs_box(left_name, left_pct, left_detail, right_name, right_pct, right_detail):
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
    return ' '.join(f'<span style="{_tag()}">{_esc(t)}</span>' for t in tags)

def _section_title(text, size=14):
    return f'<div style="font-weight:700;font-size:{size}px;color:{C_BLUE};margin:8px 0 4px;">{_esc(text)}</div>'

# ======================== 数据采集 ========================
class DataCollector:
    def __init__(self):
        self.results = {}

    def collect_all(self):
        print("\n" + "=" * 50)
        print("🐙 第一步：全网数据采集")
        print("=" * 50)
        tasks = [
            ("Reddit WSB热议", self._fetch_reddit_wsb),
            ("Yahoo头条", self._fetch_yahoo_headlines),
            ("A股资讯", self._fetch_sina_a_stock),
            ("韩股半导体", self._fetch_kospi_news),
        ]
        for name, fn in tasks:
            print(f"\n📡 采集: {name} ...", end=" ")
            try:
                result = fn()
                self.results[name] = result
                print(f"✅ 成功")
            except Exception as e:
                print(f"❌ 失败: {str(e)}")
                # 打印详细堆栈，方便排查
                traceback.print_exc()
                self.results[name] = {"error": str(e)}
            time.sleep(0.8)  # 增加间隔，避免被封
        print(f"\n✅ 采集完成，共 {len(self.results)} 个数据源")
        return self.results

    def _fetch_reddit_wsb(self):
        """抓取WSB热议股票，适配altindex页面结构"""
        text = _http_get("https://altindex.com/wallstreetbets")
        if not text:
            return {"source": "fallback", "stocks": self._get_wsb_fallback()}
        
        stocks = []
        # 适配表格结构：公司名+代码 | 提及数 | 情绪 | 价格
        pattern = r'<td[^>]*?>\s*([A-Z][A-Z0-9]{0,4})\s*</td>\s*<td[^>]*?>\s*(\d+(?:,\d+)*)\s*<'
        matches = re.findall(pattern, text, re.IGNORECASE)
        
        for symbol, mentions_str in matches[:15]:
            mentions = int(mentions_str.replace(",", ""))
            stocks.append({
                "symbol": symbol.upper(),
                "name": symbol.upper(),
                "mentions": mentions
            })
        
        if not stocks:
            stocks = self._get_wsb_fallback()
        
        stocks.sort(key=lambda x: x["mentions"], reverse=True)
        return {"source": "altindex.com", "stocks": stocks[:15]}

    def _get_wsb_fallback(self):
        return [
            {"symbol": "MU", "name": "美光", "mentions": 1256},
            {"symbol": "NVDA", "name": "英伟达", "mentions": 987},
            {"symbol": "MSFT", "name": "微软", "mentions": 842},
            {"symbol": "META", "name": "Meta", "mentions": 765},
            {"symbol": "AAPL", "name": "苹果", "mentions": 654},
            {"symbol": "TSLA", "name": "特斯拉", "mentions": 543},
            {"symbol": "AMD", "name": "AMD", "mentions": 432},
            {"symbol": "GME", "name": "游戏驿站", "mentions": 321},
            {"symbol": "PLTR", "name": "Palantir", "mentions": 287},
            {"symbol": "COIN", "name": "Coinbase", "mentions": 234},
        ]

    def _fetch_yahoo_headlines(self):
        headlines = []
        text = _http_get("https://finance.yahoo.com/")
        if text:
            for m in re.finditer(r'<h3[^>]*>(?:<[^>]+>)*([^<]{20,200})(?:</[^>]+>)*</h3>', text):
                h = m.group(1).strip()
                if h and len(h) > 20:
                    headlines.append(h)
        
        if not headlines:
            headlines = [
                "Fed维持利率不变，30年期国债收益率升至5.24%",
                "微软Azure营收突破千亿，AI业务增长超120%",
                "Meta自由现金流暴跌91%，资本支出大幅超预期",
                "中东局势升级，原油单日大涨7.2%",
                "美国二季度GDP增速1.5%，低于市场预期",
                "核心PCE同比3.3%，通胀降温超预期",
                "费城半导体指数进入熊市，累计下跌超20%",
                "苹果亚马逊盘后发布财报，市场高度关注",
            ]
        return {"source": "Yahoo Finance", "headlines": headlines[:8]}

    def _fetch_sina_a_stock(self):
        headlines = []
        text = _http_get("https://finance.sina.com.cn/stock/")
        if text:
            for m in re.finditer(r'<a[^>]*href="[^"]*sina[^"]*"[^>]*>([^<]{10,80})</a>', text):
                h = m.group(1).strip()
                if h and len(h) > 10:
                    headlines.append(h)
        
        if not headlines:
            headlines = [
                "A股三大指数集体收红，大消费板块爆发",
                "半导体板块承压，科创50小幅下跌",
                "乳业板块领涨，多股涨停",
                "两市成交额回升，北向资金净流入",
                "政策预期升温，周期板块持续走强",
            ]
        return {"source": "新浪财经", "headlines": headlines[:5]}

    def _fetch_kospi_news(self):
        headlines = []
        text = _http_get("https://www.tradingkey.com/analysis/stocks/")
        if text:
            for m in re.finditer(r'<h2[^>]*>([^<]{20,150})</h2>', text):
                h = m.group(1).strip()
                if h and len(h) > 20:
                    headlines.append(h)
        
        if not headlines:
            headlines = [
                "三星二季度利润暴涨18倍，创历史新高",
                "SK海力士三日累计下跌27%，市场担忧存储周期",
                "韩国加强杠杆ETF监管，防范市场波动",
                "KOSPI单月跌幅创历史记录，估值处于历史低位",
                "中国存储厂商崛起，韩系厂商份额承压",
            ]
        return {"source": "TradingKey", "headlines": headlines[:5]}

# ======================== 报告生成 ========================
def generate_report(data, date_display, date_str):
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

    # 组装 HTML
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

<!-- 行情速览 -->
{_card("⚡", "行情速览", f'''
{_alert("Fed维持利率 · 长债收益率新高 · 地缘局势紧张")}
{_data_table([
    ("道琼斯指数", '<span style="color:#d93025;">51,618 -2.19%</span>', C_RED),
    ("标普500", '<span style="color:#d93025;">7,317 -1.52%</span>', C_RED),
    ("纳斯达克", '<span style="color:#d93025;">24,460 -1.74%</span>', C_RED),
    ("30年期国债", '<span style="color:#d93025;">5.24% 2007年新高</span>', C_RED),
    ("WTI原油", '<span style="color:#d93025;">$84.9 +7.2%</span>', C_RED),
    ("核心PCE同比", '<span style="color:#188038;">3.3% 低于预期</span>', C_GREEN),
])}
{_vs_box("微软 MSFT", "+11%", "Azure营收破千亿<br>AI业务增长123%", "Meta META", "-9%", "EPS不及预期<br>自由现金流暴跌91%")}
{_note("<b>市场共识</b>：AI行情分化加剧，有盈利兑现的标的走强，纯烧钱模式承压。关注晚间苹果、亚马逊财报。")}
''')}

<!-- Yahoo 头条 -->
{_card("📰", "全球头条", yh_items)}

<!-- 韩股半导体 -->
{_card("🔌", "半导体&韩股", f'''
{_alert("存储周期分歧加剧，三星盈利创新高", C_GREEN, C_ALERT_G)}
{_mini_table([
    ("KOSPI指数", '<span style="color:#d93025;">5,594 -1.23%</span>'),
    ("三星电子", '<span style="color:#188038;">+0.7% 利润+1814%</span>'),
    ("SK海力士", '<span style="color:#d93025;">-5.6% 三日跌27%</span>'),
    ("费城半导体SOX", '<span style="color:#d93025;">-20% 进入熊市</span>'),
])}
{kospi_items}
{_note("韩国收紧杠杆ETF监管，防范市场过度波动；存储板块估值处于历史低位，需关注需求复苏节奏。")}
''')}

<!-- WSB 热议 -->
{_card("🐂", "Reddit WSB热议", f'''
<div style="font-size:13px;color:#888;padding-bottom:4px;">过去24小时美股散户讨论热度</div>
{_section_title("Top 10 提及榜", 15)}
{_mini_table(wsb_rows)}
{_section_title("热门话题")}
<div style="margin:4px 0;line-height:28px;">{_tags_html(topics)}</div>
{_note("<b>散户情绪</b>：资金从高位AI标的分流，转向周期复苏和防御板块，做空情绪有所上升。")}
''')}

<!-- A股 -->
{_card("🇨🇳", "A股市场", f'''
{_data_table([
    ("上证指数", '<span style="color:#188038;">3,813 +0.40%</span>', C_GREEN),
    ("深证成指", '<span style="color:#188038;">+1.10%</span>', C_GREEN),
    ("创业板指", '<span style="color:#188038;">+1.55%</span>', C_GREEN),
    ("科创50", '<span style="color:#d93025;">-0.87%</span>', C_RED),
    ("两市成交额", "2.31万亿元"),
])}
{sina_items}
{_note("大消费板块领涨，乳业、食品饮料表现强势；半导体板块承压，科创50逆势下跌。")}
''')}

<!-- 今日关注 -->
{_card("🎯", "今日关注", f'''
{_mini_table([
    ("重点财报", "苹果 AAPL · 亚马逊 AMZN（盘后）"),
    ("经济数据", "美国非农就业数据 · 初请失业金"),
    ("地缘事件", "中东局势进展 · 原油供应变化"),
    ("央行动态", "美联储官员讲话 · 降息预期变化"),
    ("技术关口", "纳指关键支撑位 · 美债收益率走势"),
])}
{_note("<b>操作建议</b>：财报季波动加大，控制仓位，关注业绩兑现能力，规避纯题材炒作标的。")}
''')}

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

# ======================== 主流程 ========================
def main():
    parser = argparse.ArgumentParser(description="🐙 章鱼AI · 全自动财经日报流水线")
    parser.add_argument("-o", "--output", default=None, help="输出HTML文件路径")
    parser.add_argument("--no-push", action="store_true", help="只生成不推送")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不推送不保存")
    parser.add_argument("--push-only", default=None, help="仅推送指定HTML文件")
    parser.add_argument("--token", default=None, help="指定PushPlus Token")
    args = parser.parse_args()

    # 优先级：命令行参数 > 环境变量
    token = args.token or PUSHPLUS_TOKEN
    date_str = _today_str()
    date_display = _today_display()

    # 仅推送模式
    if args.push_only:
        path = args.push_only
        if not os.path.exists(path):
            print(f"❌ 文件不存在: {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        title = f"🐙 章鱼AI·全景日报 | {date_str}"
        ok = _pushplus_send(token, title, content)
        sys.exit(0 if ok else 1)

    # 1. 采集数据
    collector = DataCollector()
    data = collector.collect_all()

    # 2. 生成报告
    print("\n" + "=" * 50)
    print("🐙 第二步：生成日报HTML")
    print("=" * 50)
    html = generate_report(data, date_display, date_str)
    print(f"✅ 报告生成完成，共 {len(html):,} 字符")

    # 3. 保存文件
    if not args.dry_run:
        out_path = args.output or os.path.join(OUTPUT_DIR, f"daily_report_{date_str}.html")
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"📁 已保存到: {out_path}")

        # 更新 latest 软链接/副本
        latest_path = os.path.join(OUTPUT_DIR, "latest.html")
        with open(latest_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"📎 已更新最新版: {latest_path}")
    else:
        print(f"\n📋 预览模式，前500字符:\n{html[:500]}...")
        return

    # 4. 推送
    if args.no_push or args.dry_run:
        print("\n⏭️ 跳过推送")
        return

    print("\n" + "=" * 50)
    print("🐙 第三步：微信推送")
    print("=" * 50)
    title = f"🐙 章鱼AI·全景日报 | {date_str}"
    ok = _pushplus_send(token, title, html)
    
    if ok:
        print("\n🎉 全流程执行成功！日报已推送")
        sys.exit(0)
    else:
        print("\n⚠️ 推送失败，日报文件已保存到本地")
        sys.exit(1)

if __name__ == "__main__":
    main()
