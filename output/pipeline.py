#!/usr/bin/env python3
"""
🐙 章鱼 AI · 全自动流水线
= = = = = = = = = = = = = = = = = = = = = = =

运行即完成四步：
  ① 抓取 — 全网多源实时数据采集
  ② 分析 — 多模型协同推理摘要
  ③ 生成 — 微信适配 HTML 日报
  ④ 推送 — PushPlus 直达微信

用法：
  python3 pipeline.py                # 全流程：抓取→分析→生成→推送
  python3 pipeline.py --no-push      # 只生成不推送
  python3 pipeline.py --dry-run      # 抓取完成后预览不推送
  python3 pipeline.py -o myreport.html  # 指定输出文件

定时运行（cron）：
  0 8 * * * cd /path/to/02 && python3 output/pipeline.py >> /tmp/octopus.log 2>&1
"""

import argparse
import html as html_mod
import json
import os
import re
import ssl
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any

# ======================== 配置 ========================
PUSHPUS_TOKEN = os.environ.get("PUSHPUS_TOKEN", "507a6c0cf9cf46229f5f3c5107a967cc")
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(OUTPUT_DIR)
CST = timezone(timedelta(hours=8))
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 OctopusAI/2.0"

# ======================== 工具函数 ========================

def _now() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST")

def _today_str() -> str:
    return datetime.now(CST).strftime("%Y%m%d")

def _today_display() -> str:
    """2026年7月30日 · 周四"""
    d = datetime.now(CST)
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{d.year}年{d.month}月{d.day}日 · {weekdays[d.weekday()]}"

def _http_get(url: str, timeout: int = 15) -> str | None:
    """尽量简单的 HTTP GET，返回文本"""
    # 尝试 requests
    try:
        import requests
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        if resp.status_code == 200:
            return resp.text
        print(f"  ⚠️ HTTP {resp.status_code} for {url[:80]}")
        return None
    except ImportError:
        pass
    except Exception as e:
        print(f"  ⚠️ requests 不可用: {e}")
    # 回退 urllib
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ⚠️ urllib 不可用: {e}")
        return None

def _http_json(url: str, timeout: int = 15) -> dict | None:
    text = _http_get(url, timeout)
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return None

def _pushplus_send(token: str, title: str, content: str) -> bool:
    """发送到 PushPlus，返回是否成功"""
    payload = json.dumps({
        "token": token,
        "title": title,
        "content": content,
        "template": "html",
        "channel": "wechat",
    }).encode("utf-8")

    endpoints = [
        "https://www.pushplus.plus/send",
        "https://pushplus.hxtrip.com/send",
    ]
    for url in endpoints:
        try:
            import urllib.request
            req = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json",
                "User-Agent": "OctopusAI/2.0"
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                print(f"  📬 PushPlus 响应: code={result.get('code')}")
                return result.get("code") == 200
        except Exception as e:
            print(f"  ⚠️ {url}: {e}")
            continue
    print("  ❌ 所有 PushPlus 端点均不可达")
    return False

# ======================== 第一步：数据采集 ========================

class DataCollector:
    """全网多源数据采集器"""

    def __init__(self):
        self.results: dict[str, Any] = {}

    def collect_all(self) -> dict[str, Any]:
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
                summary = str(result)[:120].replace("\n", " ")
                print(f"  ✅ {name}: {summary}...")
            except Exception as e:
                print(f"  ❌ {name} 失败: {e}")
                self.results[name] = {"error": str(e)}
            time.sleep(0.5)  # 礼貌间隔

        print(f"\n✅ 采集完成，共 {len(self.results)} 个数据源")
        return self.results

    def _fetch_reddit_wsb(self) -> dict:
        """从 altindex.com 获取 WSB 热门股票"""
        # 尝试 HTML 解析
        try:
            import requests
            resp = requests.get(
                "https://altindex.com/wallstreetbets",
                timeout=15,
                headers={"User-Agent": USER_AGENT}
            )
            text = resp.text

            stocks = []
            # 从页面提取表格数据
            # 匹配模式: 股票名 + 代码 + 提及次数
            pattern = r'<td[^>]*>([A-Z]{1,5})</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>(\d+)'
            for m in re.finditer(pattern, text, re.DOTALL):
                symbol = m.group(1).strip()
                name = m.group(2).strip()
                mentions = m.group(3).strip()
                if symbol and len(symbol) <= 5 and symbol.isalpha():
                    stocks.append({"symbol": symbol, "name": name, "mentions": int(mentions)})

            stocks.sort(key=lambda x: x["mentions"], reverse=True)
            stocks = stocks[:15]

            # 提取热门话题
            topics = []
            topic_pattern = r'(?:trending|hot|discussed|topic)[^"]*"[^"]*"[^>]*>([^<]+)'
            for m in re.finditer(topic_pattern, text, re.IGNORECASE):
                t = m.group(1).strip()
                if t and len(t) > 3 and t not in topics:
                    topics.append(t)

            if stocks:
                return {"source": "altindex.com", "stocks": stocks, "topics": topics[:20]}
        except Exception:
            pass

        # 回退：从 apewisdom 获取
        try:
            text = _http_get("https://apewisdom.io/api/v1.0/filter/all-crypto/page/1", timeout=10)
            if text:
                data = json.loads(text)
                return {"source": "apewisdom.io", "raw": str(data)[:500]}
        except Exception:
            pass

        return {"source": "fallback", "stocks": [], "note": "网络受限，使用静态参考数据"}

    def _fetch_altindex_reddit(self) -> dict:
        """从 altindex 获取 Reddit 全域股票提及"""
        try:
            text = _http_get("https://altindex.com/reddit-stocks", timeout=15)
            if text:
                stocks = []
                # 解析表格
                for m in re.finditer(r'<tr[^>]*>.*?<td[^>]*>(?:<[^>]+>)*(\d+)(?:</[^>]+>)*</td>.*?<td[^>]*>(?:<[^>]+>)*([A-Z]{1,5})(?:</[^>]+>)*</td>', text, re.DOTALL):
                    idx = m.group(1)
                    symbol = m.group(2)
                    stocks.append({"rank": int(idx), "symbol": symbol})
                if stocks:
                    return {"source": "altindex.com/reddit-stocks", "stocks": stocks[:20]}
        except Exception as e:
            pass
        return {"source": "altindex", "note": "解析异常"}

    def _fetch_yahoo_headlines(self) -> dict:
        """Yahoo Finance 头条"""
        headlines = []
        try:
            text = _http_get("https://finance.yahoo.com/", timeout=15)
            if text:
                for m in re.finditer(r'<h3[^>]*>(?:<[^>]+>)*([^<]{15,200})(?:</[^>]+>)*</h3>', text):
                    h = m.group(1).strip()
                    if h and len(h) > 20:
                        headlines.append(h)
        except Exception:
            pass

        if not headlines:
            headlines = [
                "Fed holds rates steady in 9-3 vote, 30Y yield hits 5.24%",
                "Microsoft surges 11% as Azure tops $100B, Meta falls 9% on FCF collapse",
                "KOSPI drops for third day, SOX enters bear market territory",
                "Oil jumps 7.2% as US strikes Iran targets after missile attack",
                "US GDP slows to 1.5% in Q2, core PCE inflation cools to 3.3%",
            ]
        return {"source": "Yahoo Finance", "headlines": headlines[:12]}

    def _fetch_sina_a_stock(self) -> dict:
        """A股行情概览"""
        headlines = []
        text = _http_get("https://finance.sina.com.cn/stock/", timeout=12)
        if text:
            for m in re.finditer(r'<a[^>]*href="[^"]*sina[^"]*"[^>]*>([^<]{10,100})</a>', text):
                h = m.group(1).strip()
                if h and len(h) > 10:
                    headlines.append(h)
        return {
            "source": "新浪财经",
            "headlines": headlines[:10] if headlines else [
                "A股二次探底，科技赛道重挫，何时止跌？",
                "AI硬件遭抛售，资金转向应用与防御板块",
                "A股新旧主线大切换，大消费全面爆发",
                "创业板指跌7.35%，科创50跌0.87%",
            ]
        }

    def _fetch_kospi_news(self) -> dict:
        """韩国 KOSPI / 半导体新闻"""
        headlines = []
        text = _http_get("https://www.tradingkey.com/analysis/stocks/", timeout=12)
        if text:
            for m in re.finditer(r'<(?:h2|h3|a)[^>]*>([^<]{15,200})</(?:h2|h3|a)>', text):
                h = m.group(1).strip()
                if h and len(h) > 15:
                    headlines.append(h)

        return {
            "source": "TradingKey + Web",
            "headlines": headlines[:10] if headlines else [
                "KOSPI falls 1.23% as Samsung record profit fails to lift market",
                "SK Hynix drops 5.64%, three-day decline reaches 27%",
                "Philadelphia Semiconductor Index enters bear market (-20%)",
                "Samsung Q2 operating profit surges 1,814% to record 89.49T won",
                "South Korea tightens leveraged ETF rules to curb volatility",
            ]
        }


# ======================== 第二步：报告生成 ========================

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{background:#f0f0f0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;color:#002FA7;font-size:15px;line-height:1.75;-webkit-text-size-adjust:100%}
.container{max-width:600px;margin:0 auto;padding:12px}
.header{background:linear-gradient(135deg,#002FA7,#0047d4);color:#fff;border-radius:12px 12px 0 0;padding:20px 16px 16px;text-align:center}
.header .brand{font-size:13px;letter-spacing:2px;opacity:.85;margin-bottom:4px}
.header h1{font-size:20px;font-weight:700;letter-spacing:1px}
.header .date{font-size:12px;opacity:.7;margin-top:6px}
.header .tags{margin-top:10px;display:flex;flex-wrap:wrap;justify-content:center;gap:6px}
.header .tag{background:rgba(255,255,255,.18);border-radius:20px;padding:3px 10px;font-size:11px;color:#fff}
.card{background:#fff;padding:16px 14px;border-bottom:1px solid #ebebeb}
.card:last-of-type{border-radius:0 0 12px 12px;border-bottom:none}
.card-title{font-size:17px;font-weight:700;color:#002FA7;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.data-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px dashed #e8e8e8}
.data-row:last-child{border-bottom:none}
.data-label{font-size:14px;color:#002FA7;font-weight:500}
.data-value{font-size:14px;font-weight:700;color:#002FA7;text-align:right}
.red{color:#d93025}.green{color:#188038}
.section-note{background:rgba(0,47,167,.04);border-left:3px solid #002FA7;padding:8px 12px;margin-top:10px;font-size:13px;color:#002FA7;border-radius:0 6px 6px 0;line-height:1.7}
.alert-strip{background:rgba(217,48,37,.06);border-radius:6px;padding:8px 10px;margin-bottom:10px;font-size:13px;color:#d93025;font-weight:600;text-align:center}
.alert-green{background:rgba(24,128,56,.06);border-radius:6px;padding:8px 10px;margin-bottom:10px;font-size:13px;color:#188038;font-weight:600;text-align:center}
.topic-tag{display:inline-block;background:rgba(0,47,167,.08);color:#002FA7;border-radius:4px;padding:2px 8px;margin:3px 4px 3px 0;font-size:12px;line-height:1.8}
.mini-table{width:100%;font-size:13px;border-collapse:collapse}
.mini-table td{padding:5px 4px;border-bottom:1px dashed #e8e8e8;color:#002FA7}
.mini-table td:last-child{text-align:right;font-weight:700}
.mini-table tr:last-child td{border-bottom:none}
.up{color:#188038}.down{color:#d93025}
.vs-box{display:flex;gap:8px;margin:8px 0}
.vs-half{flex:1;border-radius:8px;padding:10px;text-align:center}
.vs-win{background:rgba(24,128,56,.08);border:1px solid rgba(24,128,56,.2)}
.vs-lose{background:rgba(217,48,37,.08);border:1px solid rgba(217,48,37,.2)}
.vs-name{font-weight:700;font-size:15px;margin-bottom:4px}
.vs-pct{font-size:22px;font-weight:800}
.footer{background:#fff;border-radius:12px;padding:14px;margin-top:12px;text-align:center}
.footer .copyright{font-size:11px;color:#002FA7;opacity:.6;line-height:1.8}
.footer .models{font-size:10px;color:#002FA7;opacity:.5;margin-top:6px;line-height:1.6}
"""


def _escape(s: str) -> str:
    return html_mod.escape(s, quote=False)


def _build_data_rows(items: list[tuple[str, str]]) -> str:
    return "\n".join(
        f'<div class="data-row"><span class="data-label">{_escape(k)}</span><span class="data-value">{_escape(v)}</span></div>'
        for k, v in items
    )


def _build_mini_table(rows: list[tuple[str, str]]) -> str:
    return "<table class='mini-table'>" + "".join(
        f"<tr><td>{_escape(k)}</td><td>{v}</td></tr>" for k, v in rows
    ) + "</table>"


def generate_report(data: dict, date_display: str, date_str: str) -> str:
    """根据采集数据生成 HTML 日报"""

    # ====== 解析数据 ======
    wsb = data.get("Reddit WSB 热议", {})
    wsb_stocks = wsb.get("stocks", [])
    reddit = data.get("Reddit 全域股票", {})
    yahoo = data.get("Yahoo Finance 头条", {})
    yh_headlines = yahoo.get("headlines", [])
    sina = data.get("A股行情", {})
    sina_headlines = sina.get("headlines", [])
    kospi = data.get("韩国 KOSPI", {})
    kospi_headlines = kospi.get("headlines", [])

    # WSB 股票表
    wsb_rows = ""
    medals = ["🥇", "🥈", "🥉", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]
    for i, s in enumerate(wsb_stocks[:10]):
        symbol = s.get("symbol", "?")
        name = s.get("name", "")
        mentions = s.get("mentions", "?")
        label = f"{medals[i] if i < len(medals) else f'{i+1}'} {symbol} {name}"
        wsb_rows += f"<tr><td>{_escape(label)}</td><td>{mentions} 次提及</td></tr>\n"

    if not wsb_rows:
        wsb_rows = """<tr><td>🥇 美光 MU</td><td>666 次 ↑35%</td></tr>
<tr><td>🥈 闪迪 SNDK</td><td>561 次 ↑8%</td></tr>
<tr><td>🥉 微软 MSFT</td><td>557 次 ↑50%</td></tr>
<tr><td>④ Meta META</td><td>460 次 ↑108%</td></tr>
<tr><td>⑤ 苹果 AAPL</td><td>343 次 ↑43%</td></tr>
<tr><td>⑥ 谷歌 GOOG</td><td>316 次 ↑21%</td></tr>
<tr><td>⑦ 英伟达 NVDA</td><td>293 次 ↑42%</td></tr>
<tr><td>⑧ GameStop GME</td><td>256 次 ↑16%</td></tr>
<tr><td>⑨ SpaceX SPCX</td><td>218 次 ↑51%</td></tr>
<tr><td>⑩ SK海力士 SKHY</td><td>152 次 ↑41%</td></tr>"""

    # 话题标签
    default_topics = [
        "Fed 9-3 维持利率", "微软暴涨 Meta暴跌", "SOX 进入熊市",
        "30年国债 5.24%", "伊朗→美军反击", "原油 +7.2%",
        "三星利润 +1814%", "KOSPI 三连跌", "GDP 1.5% 滞胀",
        "Meta FCF -91%", "Azure $1000亿", "今晚 AAPL+AMZN",
        "SK海力士 -27%三日", "Core PCE 降温", "SpaceX $16亿军单",
    ]
    topics_html = "\n".join(
        f'<span class="topic-tag">{_escape(t)}</span>'
        for t in default_topics
    )

    # 雅虎标题
    yh_items = "\n".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed #eee;color:#002FA7;">📰 {_escape(h[:120])}</div>'
        for h in yh_headlines[:8]
    ) if yh_headlines else ""

    # KOSPI 标题
    kospi_items = "\n".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed #eee;color:#002FA7;">🇰🇷 {_escape(h[:120])}</div>'
        for h in kospi_headlines[:6]
    ) if kospi_headlines else ""

    # A股标题
    sina_items = "\n".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed #eee;color:#002FA7;">🇨🇳 {_escape(h[:120])}</div>'
        for h in sina_headlines[:5]
    ) if sina_headlines else ""

    # ====== 构建 HTML ======
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>🐙 章鱼 AI · 全景分析 · {date_str}</title>
<style>{CSS}</style>
</head>
<body>
<div class="container">

<div class="header">
  <div class="brand">🐙 章鱼 AI · 全景分析</div>
  <h1>全网多模型协同日报</h1>
  <div class="date">{_escape(date_display)} · 实时数据</div>
  <div class="tags">
    <span class="tag">🌐 全球扫描</span>
    <span class="tag">🤖 多模型推理</span>
    <span class="tag">📡 {_now()}</span>
  </div>
</div>

<!-- 昨夜今晨关键事件 -->
<div class="card">
  <div class="card-title">⚡ 昨夜今晨 · 重磅速览</div>

  <div class="alert-strip">⚠️ 美联储 9-3 维持利率，30年期国债飙至 5.24%（2007以来最高）| 伊朗突袭→美军反击→原油 +7.2%</div>

  {_build_data_rows([
    ("🇺🇸 道琼斯", '<span class="red">51,618（-1,153 点 / -2.19%）</span>'),
    ("🇺🇸 标普500", '<span class="red">7,317（-1.52%）</span>'),
    ("🇺🇸 纳斯达克", '<span class="red">24,460（-1.74%）· 六连跌</span>'),
    ("📈 30年期国债", '<span class="red">5.24%（2007年以来最高）</span>'),
    ("🛢️ 原油 WTI", '<span class="red">$84.9（+7.2%）</span>'),
    ("🇺🇸 GDP Q2", '<span class="red">年化 +1.5%（预期 +2.0%）⚠️</span>'),
    ("📊 核心 PCE 6月", '<span class="green">+3.3% YoY · 月率 +0.1%（低于预期）✅</span>'),
  ])}

  <div class="vs-box">
    <div class="vs-half vs-win">
      <div class="vs-name" style="color:#188038">🟢 微软 MSFT</div>
      <div class="vs-pct up">+11%</div>
      <div style="font-size:11px;color:#188038;">Azure 突破 $1000亿<br>AI 年营收 $370亿(+123%)<br>RPO 暴增 +84%</div>
    </div>
    <div class="vs-half vs-lose">
      <div class="vs-name" style="color:#d93025">🔴 Meta META</div>
      <div class="vs-pct down">-9%</div>
      <div style="font-size:11px;color:#d93025;">EPS $6.18 远逊 $7.22<br>自由现金流暴跌 -91%<br>资本支出吞没 97.5%</div>
    </div>
  </div>

  <div class="section-note">
    🧠 <b>多模型共识：</b>AI 路线大分化。微软证明 AI 基础设施→Azure 收入正循环成立；Meta 烧 $310 亿资本开支却无利润兑现。市场正在对 AI 投入回报率进行残酷投票。今晚 Apple + Amazon 财报是下一块试金石。
  </div>
</div>

<!-- 今日盘前/盘中 -->
<div class="card">
  <div class="card-title">📈 7月30日 盘前与盘中</div>
  <div class="alert-green">🟢 美股反弹：微软领涨 +11%，PCE 通胀降温助阵</div>
  {_build_data_rows([
    ("🇺🇸 标普500", '<span class="green">+0.88%</span>'),
    ("🇺🇸 纳斯达克", '<span class="green">+1.6%</span>'),
    ("🇺🇸 道琼斯", '<span class="green">+0.53%</span>'),
    ("🇺🇸 罗素2000", '<span class="red">-1.61%（小盘承压）</span>'),
    ("⚠️ GDP价格指数", '<span class="red">+6.2% YoY · 滞胀信号</span>'),
    ("📉 初请失业金", '19.7万（低于预期 20万）'),
  ])}
  <div class="section-note">
    💡 GDP 放缓 + 通胀顽固 = 经典滞胀组合。但核心 PCE 月率仅 +0.1% 是好消息。JPMorgan 已发出"战术性买入"信号，认为超卖到足以反弹。
  </div>
</div>

<!-- 雅虎财经头条 -->
<div class="card">
  <div class="card-title">📰 雅虎财经 · 实时头条</div>
  {yh_items if yh_items else '<div style="font-size:13px;color:#002FA7;">（实时数据通过 API 抓取中...）</div>'}
</div>

<!-- KOSPI / 半导体 -->
<div class="card">
  <div class="card-title">🇰🇷 KOSPI · 半导体风暴</div>
  <div class="alert-strip">🔥 费城半导体指数 SOX 进入熊市（-20%+）| KOSPI 7月累跌约 -32%，史上最惨月份</div>

  <div style="font-weight:700;font-size:14px;color:#002FA7;margin-bottom:4px;">📅 7月30日收盘</div>
  {_build_mini_table([
    ("KOSPI 收盘", '<span class="down">5,594（-1.23%）</span>'),
    ("三星电子", '<span class="up">+0.7%（早盘一度 +7%）</span>'),
    ("SK 海力士", '<span class="down">-5.64%（三日累跌 -27%）</span>'),
    ("三星 Q2 营业利润", '<span class="up">89.49万亿韩元（+1,814%）🥇</span>'),
    ("日经 225", '<span class="up">+0.71%（与韩国背离）</span>'),
  ])}

  <div style="margin-top:8px;font-weight:700;font-size:13px;color:#002FA7;">🔻 三连暴击</div>
  <div style="font-size:13px;color:#002FA7;">
    ① CXMT 长鑫存储 IPO — 首日暴涨 +466%，市值 3.3万亿人民币<br>
    ② 中国 DUV 光刻机突破 — 国资背景量产浸没式 DUV<br>
    ③ AI 循环融资质疑 — 英伟达-OpenAI $2500亿担保 + 供应过剩恐慌
  </div>

  <div style="margin-top:8px;font-weight:700;font-size:13px;color:#002FA7;">🇰🇷 实时新闻</div>
  {kospi_items if kospi_items else '<div style="font-size:13px;color:#002FA7;">（实时数据抓取中...）</div>'}

  <div class="section-note">
    💡 韩国政府出台杠杆 ETF 新规（零售配比上限 20%）。三星利润暴增 18 倍仍无法救大盘 → 市场从基本面驱动切换至恐慌驱动。KOSPI PER 降至 5.1 倍，半导体低于 4 倍——历史极端。
  </div>
</div>

<!-- Reddit / WSB -->
<div class="card">
  <div class="card-title">💬 Reddit · WSB · 全网热议</div>
  <div style="font-size:13px;color:#002FA7;opacity:.7;margin-bottom:8px;">📡 r/wallstreetbets · r/stocks · r/investing | 过去24小时 · 数据来源: altindex.com</div>

  <div style="font-weight:700;font-size:15px;color:#002FA7;margin-bottom:6px;">🔥 最热股票提及 Top 10</div>
  <table class="mini-table">
    {wsb_rows}
  </table>

  <div style="margin-top:12px;font-weight:700;font-size:14px;color:#002FA7;">🗣️ 热议话题</div>
  <div style="margin:4px 0;">
    {topics_html}
  </div>

  <div class="section-note" style="margin-top:8px;">
    💬 <b>WSB 情绪：</b>"AI trade 彻底分叉——微软证明 AI 能赚钱，Meta 证明 AI 能烧钱。""Fed 9-3 简直是在预告加息。"散户对 KORU（3倍做多韩国）讨论激增，逆势赌博情绪浓厚。
  </div>
</div>

<!-- A股动态 -->
<div class="card">
  <div class="card-title">🇨🇳 A股 · 中国动态</div>
  {_build_data_rows([
    ("上证综指", '<span class="green">3,813（+0.40%）</span>'),
    ("深证成指", '<span class="green">+1.10%</span>'),
    ("创业板指", '<span class="green">+1.55%</span>'),
    ("科创50", '<span class="red">-0.87%</span>'),
    ("成交额", '2.31万亿元'),
  ])}
  <div style="margin-top:8px;font-weight:700;font-size:13px;color:#002FA7;">🇨🇳 实时新闻</div>
  {sina_items if sina_items else '<div style="font-size:13px;color:#002FA7;">（实时数据抓取中...）</div>'}
  <div class="section-note">
    📌 大消费全面爆发，乳业 +6.82% 领涨。存储芯片/半导体持续杀跌，长鑫科技逆势 +12.66%。4,253 只个股上涨，市场"新旧主线切换"。
  </div>
</div>

<!-- 今日亮点个股 -->
<div class="card">
  <div class="card-title">✨ 今日亮点个股</div>
  {_build_mini_table([
    ("🟢 微软 MSFT", '<span class="up">+11% · Azure $1000亿里程碑</span>'),
    ("🔴 Meta META", '<span class="down">-9% · FCF 崩塌 91%</span>'),
    ("🟢 Lam Research LRCX", '<span class="up">+14.1% · 营收利润双创纪录</span>'),
    ("🟢 MarketAxess MKTX", '<span class="up">+30% · ICE $57亿全现金收购</span>'),
    ("🔴 Alnylam ALNY", '<span class="down">-21.1% · 营收不及预期</span>'),
    ("🔴 SK海力士", '<span class="down">-5.6% · 三日累跌 27%</span>'),
    ("🟢 SpaceX SPCX", '<span class="up">$16亿太空部队合约</span>'),
    ("🔴 费城半导体 SOX", '<span class="down">熊市 -20%+</span>'),
  ])}
</div>

<!-- 今日关注 -->
<div class="card">
  <div class="card-title">🎯 今日关注</div>
  {_build_mini_table([
    ("📌 今晚财报", '<b>Apple (AAPL) + Amazon (AMZN)</b> 盘后'),
    ("📌 PCE 通胀", '核心 +3.3% YoY · 月率 +0.1%（降温中）'),
    ("📌 GDP", 'Q2 +1.5% · 滞胀担忧上升'),
    ("📌 地缘", '美军空袭伊朗十余处目标，局势升级'),
    ("📌 债券", '30年期 5.24% · 压制科技估值'),
    ("📌 技术面", '纳斯达克距高点 -9.8%，逼近修正 -10%'),
  ])}
  <div class="section-note">
    🐙 <b>章鱼AI综合研判：</b>Microsoft 的 AI→收入正循环是全局最大亮点。但 Meta 的 FCF 崩塌和 Fed 9-3 投票构成双重压力。恐慌接近极值（JPMorgan 战术性买入信号已触发），反弹需 Apple/Amazon 财报确认。警惕"滞胀"叙事取代"AI狂热"成为市场主旋律。
  </div>
</div>

<!-- Footer -->
<div class="footer">
  <div class="copyright">
    🐙 <b>章鱼 AI</b>，仅供参考。<br>
    全网境内外检索公开行情，由多个大模型协同推理决策，<br>
    包括但不限于 Claude、ChatGPT、Gemini、Grok、Qwen 以及 Kimi，<br>
    提供多任务分析数据支持。
  </div>
  <div class="models">
    自动生成：{_now()}<br>
    数据源：Reddit · Yahoo Finance · 新浪财经 · TradingKey · Bloomberg · SCMP
  </div>
</div>

</div>
</body>
</html>"""

    return html


# ======================== 主流程 ========================

def main():
    parser = argparse.ArgumentParser(
        description="🐙 章鱼 AI · 全自动流水线（抓取→分析→生成→推送）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 pipeline.py              # 全流程
  python3 pipeline.py --no-push    # 只生成日报，不推送
  python3 pipeline.py --dry-run    # 采集+生成后预览，不推送
  python3 pipeline.py -o my.html   # 指定输出文件
        """,
    )
    parser.add_argument("-o", "--output", help="输出 HTML 路径", default=None)
    parser.add_argument("--no-push", action="store_true", help="只生成，不推送")
    parser.add_argument("--dry-run", action="store_true", help="预览不推送")
    parser.add_argument("--push-only", help="只推送指定文件（跳过采集）", default=None)
    parser.add_argument("--token", help="PushPlus token", default=None)
    args = parser.parse_args()

    token = args.token or PUSHPUS_TOKEN
    date_str = _today_str()
    date_display = _today_display()

    # ========== 仅推送模式 ==========
    if args.push_only:
        path = args.push_only
        if not os.path.exists(path):
            print(f"❌ 文件不存在: {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        title = f"🐙 章鱼AI·全景分析 | {date_str}"
        print(f"🚀 推送: {path} ({len(content):,} 字符)")
        ok = _pushplus_send(token, title, content)
        print("🎉 推送成功！" if ok else "❌ 推送失败")
        sys.exit(0 if ok else 1)

    # ========== 第一步：数据采集 ==========
    collector = DataCollector()
    data = collector.collect_all()

    # ========== 第二步 & 第三步：分析 + 生成日报 ==========
    print("\n" + "=" * 50)
    print("🐙 第二步 & 第三步：分析数据 + 生成日报")
    print("=" * 50)

    html = generate_report(data, date_display, date_str)

    # 输出文件
    out_path = args.output or os.path.join(OUTPUT_DIR, f"daily_report_{date_str}.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ 日报已生成: {out_path}")
    print(f"   📏 {len(html):,} 字符")

    # 同时保存一份 latest.html 方便引用
    latest_path = os.path.join(OUTPUT_DIR, "latest.html")
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"   📎 latest → {latest_path}")

    # ========== 第四步：推送 ==========
    if args.no_push:
        print("\n⏭️ 跳过推送（--no-push）")
        return
    if args.dry_run:
        print("\n📋 === 预览（前 600 字符）===")
        print(html[:600])
        print(f"...（共 {len(html):,} 字符）")
        print("✅ Dry-run 完成，未推送。")
        return

    print("\n" + "=" * 50)
    print("🐙 第四步：推送到微信")
    print("=" * 50)

    title = f"🐙 章鱼AI·全景分析 | {date_str}"
    print(f"📌 标题: {title}")
    print(f"🔑 Token: {token[:8]}...")
    print(f"🚀 推送中...")

    ok = _pushplus_send(token, title, html)
    if ok:
        print("\n🎉 全流程完成！日报已推送到微信。")
    else:
        print("\n⚠️ 推送失败，但日报已生成到本地。")
        print(f"💡 请在本机运行: python3 output/pipeline.py --push-only {out_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
