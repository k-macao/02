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
  6. 新增「热门榜单」数据源：最近交易日收盘后 A股/港股/美股 成交量前五
     （东方财富 push2 免费接口）。2026-08-06 起不再单独渲染三个成交量榜单栏目，
     原始榜单数据仅作为 AI 盘研判、AI 量化流动性报告与数据审计的信号源，
     页面只保留 AI 对三个榜单成交量的研判结果。
  6.1 新增「AI 研判 · 最近 A股、港股、美股成交量与流动性分析」：聚合 A股/港股/美股
      样本成交额、TOP10 成交集中度、涨跌扩散比、成交额加权涨跌与换手率，并分析三大市场
      成交量活跃标的流向，输出 0-100 流动性评分、资金定性和交投研判文本；规则合成，
      可复现，非投资建议。页面不展示任何成交量个股排名表，只保留 AI 研判结论。
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
  7.1 页面风格：复古像素游戏（RETRO PIXEL MARKET QUEST v3）——
     暗色街机终端底、霓虹青 / 电光蓝 / 像素黄 / 品红，纯直角像素块 + 3px 硬描边 + 实色阴影；
     等宽字体栈（Courier New / Lucida Console / monospace，回退苹方/雅黑）。刊头含纯 HTML 8-bit
     章鱼图标；每个 LVL 关卡配独立 44px 大图标砖。涨跌用高对比底色 + ▲涨 / ▼跌 / ■平三重
     编码，并覆盖行情等板块。AI 盘研判首屏使用 AI CORE 主控卡、方向 / 信号分 /
     置信度计分板和大字号「AI 主结论」，板块 / 技术 / 风险 / 关注各自成独立像素面板；窗口标题栏
     升级为 OCTOPUS_OS v3。成交量榜单不再单独成栏，只保留 AI 研判结果。
     硬约束：全部内联样式 + 表格布局（微信/PushPlus 会剥离 <style> 与 class）。
  8. PushPlus 内容上限（账号已升级会员，默认按 10 万字；可用环境变量
     PUSHPLUS_MAX_CONTENT_CHARS 覆盖）。日报 HTML 超过上限时，发送前会按完整标签边界
     截断并闭合所有标签、末尾附「完整版」链接，保证微信端排版正常；磁盘上的日报文件
     始终保留完整版。
  9. 「AI 盘研判」栏目：基于当日多源信号（实时行情、热门榜单、全球/东财/A股头条、
     港股名家频道观点）做确定性规则合成，输出跨市场综合研判（情绪定调 +
     信号分 + 置信度、板块热度、技术速读、风险提示、明日关注主题）。无需大模型 API、
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

# ============================================================
# 推送主题（2026-08-21 起，一对一 / 一对多推送共用）
# ============================================================
# guizang —— 默认主题：参考 guizang-ppt-skill 的 Style A「电子杂志 × 电子墨水」
#   （github.com/op7418/guizang-ppt-skill），改造成适合微信阅读的竖版长页面：
#   暖米白电子纸 + 墨黑 Hero / 章节幕封、衬线标题（荧光绿）、非衬线正文（墨黑）、
#   等宽元信息、发丝线与大留白；全部字体偏小；宽表格自动转纵向 rowline 避免
#   横向溢出；因子分析以杂志式信号矩阵呈现（保留涨跌颜色、概率与证据）。
#   纯内联样式，不依赖 WebGL / JavaScript / 外部 CSS，兼容 PushPlus / 微信详情页。
# pixel   —— 旧版 Retro Pixel Market Quest 主题（可切换回退，行为保持不变）。
PUSH_THEMES = ("guizang", "pixel")
DEFAULT_PUSH_THEME = "guizang"


def _resolve_push_theme(name=None):
    """归一化推送主题：空 / 非法值一律回落到默认主题 guizang。"""
    theme = name if name is not None else os.environ.get("OCTOPUS_PUSH_THEME", "")
    theme = str(theme or "").strip().lower()
    return theme if theme in PUSH_THEMES else DEFAULT_PUSH_THEME


# 当前默认主题（环境变量 OCTOPUS_PUSH_THEME 可覆盖；命令行 --theme 优先）
PUSH_THEME = _resolve_push_theme()

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
        ("恒生指数", "%5EHSI"), ("恒生科技", "%5EHSTECH"),
    ]
    quotes, failures, last_dates = {}, [], []
    for label, symbol in specs:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
        data = safe_request(url)
        try:
            result = data["chart"]["result"][0]
            quote_0 = result["indicators"]["quote"][0]
            closes = [x for x in quote_0["close"] if x is not None]
            volumes = [x for x in quote_0.get("volume", []) if x is not None]
            if len(closes) < 2:
                raise ValueError("报价记录不足")
            price, previous = closes[-1], closes[-2]
            vol = volumes[-1] if volumes else 0
            quotes[label] = {"price": price, "change_pct": (price / previous - 1) * 100,
                             "volume": vol,
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
        return f'<span style="color:{C_FAINT};">■ 数据暂缺</span>', C_FAINT
    price = quote["price"]
    pct = float(quote["change_pct"])
    color = C_GREEN if pct > 0 else (C_RED if pct < 0 else C_AMBER)
    # 数值用白色、涨跌用带箭头的高对比色块；即使用户存在色觉差异，也能靠 ▲/▼/■ 判断。
    value = (f'<span style="display:inline-block;color:{C_INK};font-size:13px;font-weight:900;'
             f'font-family:{FONT_MONO};padding-right:6px;">{price:,.{precision}f}</span>'
             f'{_trend_badge(pct)}')
    return value, color


# 数据源 1：全球头条（Google News 中文版）
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
# 数据源 2：东方财富快讯（免费 API，5 条最新新闻）
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
# 数据源 3：热门榜单（最近交易日收盘后 A股/港股/美股 成交量前五）
# ============================================================
HOT_STOCK_TOP_N = 5

HOT_STOCK_MARKETS = {
    "A股": {"fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "desc": "沪深京 A 股"},
    "港股": {"fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2", "desc": "港股主板"},
    "美股": {"fs": "m:105,m:106,m:107", "desc": "美股（纽交所/纳斯达克/美交所）"},
}


def fetch_hot_stocks():
    """抓取最近一个交易日收盘后的 A股/港股/美股成交量前五（东方财富 push2 免费接口）。

    返回 _source_result：markets={市场名: {"desc", "stocks":[{code,name,price,amount}]}}
    """
    print(f"📡 正在抓取 A股/港股/美股成交量前{HOT_STOCK_TOP_N}...")
    markets = {}
    any_stock = False
    for label, cfg in HOT_STOCK_MARKETS.items():
        params = {
            "pn": "1", "pz": str(HOT_STOCK_TOP_N), "po": "1", "np": "1", "fltt": "2", "invt": "2",
            "fid": "f6", "fs": cfg["fs"], "fields": "f2,f3,f4,f6,f12,f14",
        }
        data = safe_request("https://push2.eastmoney.com/api/qt/clist/get",
                            params=params, timeout=12)
        stocks = []
        try:
            diff = ((data or {}).get("data") or {}).get("diff") or []
            for it in diff[:HOT_STOCK_TOP_N]:
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
        print(f"  {'✅' if stocks else '⚠️'} {label}成交量前{HOT_STOCK_TOP_N}: {len(stocks)} 只")

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
# 数据源 4：A股 / 港股 / 美股最近收盘成交量与流动性报告（AI 研判）
# ============================================================
LIQUIDITY_SAMPLE_SIZE = int(os.environ.get("OCTOPUS_LIQUIDITY_SAMPLE_SIZE", "300"))
LIQUIDITY_MARKETS = {
    "A股": {"fs": HOT_STOCK_MARKETS["A股"]["fs"], "desc": "沪深京 A 股"},
    "港股": {"fs": HOT_STOCK_MARKETS["港股"]["fs"], "desc": "港股主板"},
    "美股": {"fs": HOT_STOCK_MARKETS["美股"]["fs"], "desc": "美股（纽交所/纳斯达克/美交所）"},
}


def _to_float(v, default=0.0):
    """把东方财富返回的数字/横线转为 float。"""
    try:
        if v in (None, "", "-"):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _median(values):
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return 0.0
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2


def _liquidity_score_and_label(stats):
    """按成交集中度、涨跌扩散、金额加权动能与换手率生成可复现的流动性评分。"""
    score = 50.0
    top10_share = stats.get("top10_share", 0.0)
    adv_dec_ratio = stats.get("adv_dec_ratio", 1.0)
    weighted_change = stats.get("weighted_change", 0.0)
    avg_turnover = stats.get("avg_turnover", 0.0)

    # 头部成交占比越低，说明流动性越分散；过高则说明抱团/集中。
    if top10_share < 0.22:
        score += 12
    elif top10_share < 0.35:
        score += 6
    elif top10_share > 0.55:
        score -= 12
    elif top10_share > 0.45:
        score -= 6

    # 上涨/下跌家数扩散度。
    if adv_dec_ratio >= 1.5:
        score += 12
    elif adv_dec_ratio >= 1.1:
        score += 6
    elif adv_dec_ratio <= 0.55:
        score -= 12
    elif adv_dec_ratio <= 0.9:
        score -= 6

    # 成交金额加权涨跌：资金买入方向更重要。
    if weighted_change >= 1.0:
        score += 10
    elif weighted_change >= 0.25:
        score += 5
    elif weighted_change <= -1.0:
        score -= 10
    elif weighted_change <= -0.25:
        score -= 5

    # 平均换手代表活跃度，但只作为温和修正，避免小票高换手过度影响。
    if avg_turnover >= 4:
        score += 6
    elif avg_turnover >= 2:
        score += 3
    elif avg_turnover and avg_turnover < 0.8:
        score -= 4

    score = max(0, min(100, round(score)))
    if score >= 72:
        label, tone = "放量活跃", "资金扩散"
    elif score >= 58:
        label, tone = "温和活跃", "结构性流入"
    elif score >= 42:
        label, tone = "中性震荡", "存量博弈"
    else:
        label, tone = "缩量偏弱", "防御收缩"
    if top10_share > 0.5:
        tone = "头部集中"
    return score, label, tone


def _analyze_liquidity_market(label, stocks):
    """对单个市场最近收盘样本做 AI 量化流动性分析。"""
    amounts = [_to_float(s.get("amount")) for s in stocks]
    total_amount = sum(amounts)
    top10_amount = sum(amounts[:10])
    changes = [_to_float(s.get("change_pct")) for s in stocks]
    turnovers = [_to_float(s.get("turnover")) for s in stocks if _to_float(s.get("turnover")) > 0]
    advancers = sum(1 for c in changes if c > 0)
    decliners = sum(1 for c in changes if c < 0)
    flats = max(0, len(changes) - advancers - decliners)
    adv_dec_ratio = advancers / decliners if decliners else float(advancers or 1)
    weighted_change = (sum(c * a for c, a in zip(changes, amounts)) / total_amount) if total_amount else 0.0
    avg_turnover = (sum(turnovers) / len(turnovers)) if turnovers else 0.0
    stats = {
        "market": label,
        "sample_count": len(stocks),
        "total_amount": total_amount,
        "median_amount": _median(amounts),
        "top10_amount": top10_amount,
        "top10_share": (top10_amount / total_amount) if total_amount else 0.0,
        "advancers": advancers,
        "decliners": decliners,
        "flats": flats,
        "adv_dec_ratio": adv_dec_ratio,
        "weighted_change": weighted_change,
        "avg_turnover": avg_turnover,
        "high_turnover_count": sum(1 for t in turnovers if t >= 5),
        "top_stocks": stocks[:10],
    }
    score, level, tone = _liquidity_score_and_label(stats)
    stats.update({"score": score, "level": level, "tone": tone})
    return stats


def fetch_liquidity_report():
    """抓取最近收盘 A股/港股/美股流动性，并做规则型 AI 量化分析。

    使用东方财富 push2 免费接口按成交额降序拉取样本，聚合成交额、头部集中度、
    上涨/下跌扩散、成交额加权涨跌与换手率，形成可审计、可复现的流动性报告。
    """
    print("📡 正在抓取 A股/港股/美股最近收盘流动性...")
    markets = {}
    errors = []
    for label, cfg in LIQUIDITY_MARKETS.items():
        params = {
            "pn": "1", "pz": str(LIQUIDITY_SAMPLE_SIZE), "po": "1", "np": "1", "fltt": "2", "invt": "2",
            "fid": "f6", "fs": cfg["fs"], "fields": "f2,f3,f6,f8,f12,f14",
        }
        data = safe_request("https://push2.eastmoney.com/api/qt/clist/get", params=params, timeout=15)
        stocks = []
        try:
            diff = ((data or {}).get("data") or {}).get("diff") or []
            for it in diff:
                name = str(it.get("f14") or "").strip()
                if not name:
                    continue
                stocks.append({
                    "code": str(it.get("f12") or ""),
                    "name": name,
                    "price": it.get("f2"),
                    "change_pct": _to_float(it.get("f3")),
                    "amount": _to_float(it.get("f6")),
                    "turnover": _to_float(it.get("f8")),
                })
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            stocks = []

        if stocks:
            markets[label] = {"desc": cfg["desc"], **_analyze_liquidity_market(label, stocks)}
            print(f"  ✅ {label}流动性样本: {len(stocks)} 只，成交额 {_format_amount(markets[label]['total_amount'])}")
        else:
            markets[label] = {"desc": cfg["desc"], "sample_count": 0, "top_stocks": []}
            errors.append(f"{label}: 未返回有效样本")
            print(f"  ⚠️ {label}流动性暂不可用")

    available = [m for m in markets.values() if m.get("sample_count")]
    if not available:
        return _source_result("东方财富流动性", "unavailable", markets=markets,
                              error="；".join(errors[:3]) or "未取得有效流动性样本")

    # 生成跨市场简述：支持 A股/港股/美股 可用样本对比。
    valid_names = [k for k in ["A股", "港股", "美股"] if markets.get(k, {}).get("sample_count")]
    if len(valid_names) >= 2:
        best_mk = max(valid_names, key=lambda k: markets[k].get("score", 0))
        conc_mk = max(valid_names, key=lambda k: markets[k].get("top10_share", 0))
        summary = (f"{best_mk}流动性评分相对领先；{conc_mk}头部成交集中度最高。"
                   f"成交额加权涨跌：" + "，".join(
                       f"{k} {markets[k].get('weighted_change', 0):+.2f}%" for k in valid_names
                   ) + "。")
    elif len(valid_names) == 1:
        only = valid_names[0]
        summary = f"本次仅取得{only}有效样本，跨市场比较暂缺；{only}加权涨跌 {markets[only].get('weighted_change', 0):+.2f}%。"
    else:
        summary = "本次未取得有效流动性样本，跨市场比较暂缺。"

    print("  ✅ A股/港股/美股流动性 AI 量化分析完成")
    return _source_result("东方财富流动性", "success",
                          is_today=True, content_date=_today_display(),
                          markets=markets, summary=summary,
                          sample_size=LIQUIDITY_SAMPLE_SIZE,
                          error="；".join(errors[:3]) or None,
                          partial=bool(errors))


# ============================================================
# 数据源 5：A股资讯（新浪财经）
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


# 数据源 6：港股名家频道（YouTube / 通用 RSS / 需登录平台）
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

    data["全球头条"] = fetch_google_news()
    time.sleep(0.5)

    data["A股资讯"] = fetch_sina_headlines()
    time.sleep(0.5)

    data["东财快讯"] = fetch_eastmoney_news()
    time.sleep(0.5)

    data["热门榜单"] = fetch_hot_stocks()
    time.sleep(0.5)

    data["A港美流动性"] = fetch_liquidity_report()
    data["A港流动性"] = data["A港美流动性"]  # 兼容既有字段与历史脚本

    print("\n✅ 数据采集完成！")
    return data


# ============================================================
# HTML 组件（设计系统：复古像素游戏 · MARKET QUEST v3）
# ------------------------------------------------------------
# 版式语言：
#  · 暗色街机终端底 + 霓虹青 / 品红 / 电光蓝 / 像素黄
#  · 纯直角像素风：0 圆角、3px 硬描边 + 实色阴影，像 8-bit 卡带界面
#  · 等宽像素字体栈，中文回退苹方/雅黑；不依赖外部字体、图片或 SVG
#  · 纯 HTML 像素章鱼 + 每栏独立 44px 图标砖，图标始终先于文字建立层级
#  · 涨跌 = 高对比颜色底块 + ▲/▼/■ + 涨/跌/平，兼顾色觉差异
#  · AI = 首屏主控卡 + 关键指标计分板 + 大字号主结论 + 四个独立面板
# 硬约束：仍全部内联样式 + 表格布局，兼容微信/PushPlus
# ============================================================
# 复古游戏像素调色板
C_BG = "#050711"
C_PAPER = "#101426"
C_INK = "#F4F7FF"
C_ACCENT = "#39FFB6"
C_ACCENT_DEEP = "#FFFFFF"
C_ACCENT_SOFT = "#303A60"
C_ACCENT_MAGENTA = "#FF3CAC"
C_CYAN = "#22DFFF"
C_VIOLET = "#A98CFF"
C_MUTED = "#A6AEC9"
C_FAINT = "#747D9F"
C_HAIR = "#29314E"
C_ZEBRA = "#181D34"
C_LEMON = "#FFE66D"
C_MINT = "#39FFB6"
# 涨跌色不仅靠文字色区分，还配合 ▲/▼、深色底块与硬描边，保证微信深色页面中一眼可辨。
C_RED = "#FF5576"
C_GREEN = "#35F29A"
C_AMBER = "#FFD166"
C_BLUE = "#22DFFF"
C_MAGENTA = "#FF3CAC"
C_UP_BG = "#082B22"
C_DOWN_BG = "#34131F"
C_FLAT_BG = "#302711"
C_AI_BG = "#17152F"
FONT = ("'Courier New', Courier, 'Lucida Console', monospace, "
        "PingFang SC, Microsoft YaHei, sans-serif")
FONT_MONO = "'Courier New', Courier, monospace"

# ============================================================
# GUIZANG 主题调色板：「电子杂志 × 电子墨水」(Style A · 灰黄电子纸全页底色)
# —— 灰黄/暖米灰电子纸全页底色 + 灰黄同系卡片幕封；衬线标题 + 非衬线正文 + 等宽元信息
# —— 全部灰底/灰黄底色，彻底去除割裂的纯黑大色块，高对比度墨色正文与清晰涨跌编码
# ============================================================
GZ_PAPER = "#F4F1EA"        # 灰黄电子纸（页面整体底色）
GZ_PAPER_TINT = "#E9E4D8"   # 卡片 / 注记 / 引言底色（纸同系加深一档）
GZ_INK = "#1A1A1D"          # 墨黑（正文主字色）
GZ_INK_TINT = "#DFD8CB"     # 章节幕封 / Hero 顶部卡片底色（灰黄同系深一阶，彻底告别黑底）
GZ_HAIR = "#CBC5B8"         # 发丝分隔线（纸底）
GZ_HAIR_INK = "#B8B1A2"     # 发丝线（幕封/卡片底）
GZ_CREAM = "#1A1A1D"        # 幕封/卡片底上的正文字色（保持墨黑高对比）
GZ_META = "#6B665A"         # 等宽元信息（纸底）
GZ_META_INK = "#5C574D"     # 等宽元信息（幕封/卡片底）
GZ_NEON = "#1A1A1D"         # 标题 / 强调字色（墨黑高对比标题）
GZ_UP = "#1F7A38"           # 涨（纸底与卡片底统一正绿）
GZ_DOWN = "#C82333"         # 跌（纸底与卡片底统一正红）
GZ_FLAT = "#6B665A"         # 平（中灰）
GZ_UP_INK = "#1F7A38"       # 涨
GZ_DOWN_INK = "#C82333"     # 跌
GZ_FLAT_INK = "#6B665A"     # 平
GZ_WARN = "#A05A18"         # 警示（琥珀暖棕）
GZ_WARN_INK = "#A05A18"     # 警示
# 字体分工（Style A 铁律）：衬线 = 标题重音，非衬线 = 正文信息密度，等宽 = 元信息节奏。
# 微信会把每个内联 font-family 原样计入消息长度；长字体栈在一份日报中重复数百次，
# 曾令 11.6 万字符的正文触发 PushPlus 10 万字符截断。这里只保留微信/iOS/Android
# 都有可靠回退的短字体栈，视觉不变，但一份完整日报可减少约 2.6 万字符。
GZ_SERIF = "'Songti SC',STSong,serif"
GZ_SANS = "-apple-system,'PingFang SC',sans-serif"
GZ_MONO = "monospace"


def _sq(color=C_ACCENT, size=8):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">■</span>'


def _star(color=C_ACCENT, size=10):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">◆</span>'


def _heart(color=C_ACCENT_MAGENTA, size=10):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">⚡</span>'


def _flower(color=C_CYAN, size=10):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">✚</span>'


def _percent_number(value):
    """把数字 / ``+1.23%`` 文本转成 float；无法转换时返回 None。"""
    try:
        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return None


def _trend_badge(value, compact=False):
    """渲染高辨识度涨跌像素徽标：颜色、箭头和文字三重编码。"""
    pct = _percent_number(value)
    if pct is None:
        return (f'<span style="display:inline-block;border:1px solid {C_FAINT};background:{C_ZEBRA};'
                f'color:{C_FAINT};padding:1px 6px;font-size:10px;font-weight:900;'
                f'font-family:{FONT_MONO};box-shadow:2px 2px 0 #000;white-space:nowrap;">■ --</span>')
    if pct > 0:
        color, bg, arrow, word = C_GREEN, C_UP_BG, "▲", "涨"
    elif pct < 0:
        color, bg, arrow, word = C_RED, C_DOWN_BG, "▼", "跌"
    else:
        color, bg, arrow, word = C_AMBER, C_FLAT_BG, "■", "平"
    label = f"{arrow} {pct:+.2f}%" if compact else f"{arrow} {word} {pct:+.2f}%"
    if pct == 0:
        label = f"{arrow} 0.00%" if compact else f"{arrow} {word} 0.00%"
    return (f'<span style="display:inline-block;border:1px solid {color};background:{bg};'
            f'color:{color};padding:1px 6px;font-size:10px;font-weight:900;line-height:17px;'
            f'font-family:{FONT_MONO};box-shadow:2px 2px 0 #000;white-space:nowrap;">{label}</span>')


def _signal_meter(value, maximum, color=C_CYAN, cells=5):
    """用实体像素格显示信号强度，不依赖 CSS 渐变或外部图标。"""
    maximum = max(1, int(maximum or 1))
    lit = max(1, min(cells, round(float(value or 0) / maximum * cells))) if value else 0
    return (f'<span style="color:{color};font-family:{FONT_MONO};font-size:10px;letter-spacing:1px;">'
            f'{"■" * lit}</span><span style="color:{C_ACCENT_SOFT};font-family:{FONT_MONO};'
            f'font-size:10px;letter-spacing:1px;">{"□" * (cells - lit)}</span>')


def _pixel_octopus(pixel=4):
    """纯 HTML 8-bit 章鱼图标；无需图片资源，PushPlus/微信可直接渲染。"""
    pattern = (
        "00111100",
        "01111110",
        "11211211",
        "11111111",
        "01111110",
        "01011010",
        "11011011",
        "10000001",
    )
    cells = []
    for row in pattern:
        tds = []
        for bit in row:
            bg = C_ACCENT if bit == "1" else (C_BG if bit == "2" else "")
            # bgcolor / width / height 是邮件客户端兼容性最高的表格像素写法，也比重复长 style 更省推送字数。
            bg_attr = f' bgcolor="{bg}"' if bg else ""
            tds.append(f'<td width="{pixel}" height="{pixel}"{bg_attr}>&nbsp;</td>')
        cells.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<table role="img" aria-label="章鱼像素图标" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;margin:0 auto;font-size:0;line-height:0;">'
            f'{"".join(cells)}</table>')

def _badge(text, kind="ok"):
    styles = {
        "ok":   (C_GREEN, C_UP_BG, C_GREEN),
        "warn": (C_AMBER, C_FLAT_BG, C_AMBER),
        "bad":  (C_RED, C_DOWN_BG, C_RED),
        "ai":   (C_LEMON, C_AI_BG, C_VIOLET),
    }
    color, bg, border = styles.get(kind, styles["ok"])
    dot = "◆" if kind == "ai" else "●"
    return (f'<span style="display:inline-block;border:1px solid {border};color:{color};'
            f'background:{bg};padding:1px 7px;margin-left:6px;font-size:10px;font-weight:900;'
            f'font-family:{FONT_MONO};letter-spacing:1px;line-height:17px;'
            f'box-shadow:2px 2px 0 #000;vertical-align:middle;'
            f'white-space:nowrap;">[{dot} {_esc(text)}]</span>')


_SECTION_ICON_META = {
    "AI READ": ("◆", "AI", C_LEMON, C_AI_BG),
    "MARKET SNAPSHOT": ("▲", "MKT", C_GREEN, C_UP_BG),
    "HK GURU CHANNELS": ("▶", "TV", C_MAGENTA, "#301226"),
    "GLOBAL HEADLINES": ("▤", "NEWS", C_CYAN, "#092836"),
    "EASTMONEY WIRE": ("!", "WIRE", C_AMBER, C_FLAT_BG),
    "A-SHARE DESK": ("¥", "CN", C_RED, C_DOWN_BG),
    "A/H/US LIQUIDITY": ("≈", "FLOW", C_CYAN, "#092836"),
    "A/H LIQUIDITY": ("≈", "FLOW", C_CYAN, "#092836"),
    "DATA AUDIT": ("✓", "LOG", C_GREEN, C_UP_BG),
}


def _section_visual(kicker):
    """返回栏目像素图标、短标签与强调色。"""
    return _SECTION_ICON_META.get(kicker, ("■", "DATA", C_ACCENT, C_UP_BG))


def _pixel_icon(kicker, size=44):
    """大尺寸栏目图标砖；ASCII/几何符号在微信字体回退时仍清晰。"""
    glyph, label, color, bg = _section_visual(kicker)
    glyph_size = max(20, round(size * 0.43))
    return (f'<table width="{size}" height="{size}" cellpadding="0" cellspacing="0" '
            f'style="width:{size}px;height:{size}px;border-collapse:collapse;border:1px solid {color};'
            f'background:{bg};box-shadow:4px 4px 0 #000;">'
            f'<tr><td align="center" valign="middle" style="padding:2px;color:{color};'
            f'font-family:{FONT_MONO};font-weight:900;line-height:1;">'
            f'<div style="font-size:{glyph_size}px;line-height:{glyph_size}px;">{glyph}</div>'
            f'<div style="font-size:8px;line-height:10px;letter-spacing:.5px;">{label}</div>'
            f'</td></tr></table>')


def _pixel_panel(title, body, color=C_CYAN, icon="■"):
    """AI 等重点内容使用的 8-bit 面板：高对比标题条 + 硬边框。"""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-top:12px;border:1px solid {color};background:#0C1122;box-shadow:4px 4px 0 #000;">'
            f'<tr><td style="padding:5px 9px;background:{color};color:{C_BG};font-size:10px;'
            f'font-weight:900;font-family:{FONT_MONO};letter-spacing:1px;">{icon} {title}</td></tr>'
            f'<tr><td style="padding:8px 10px;">{body}</td></tr></table>')


def _alert(text, color=C_AMBER, bg=None):
    bg_color = bg or "#1A1E33"
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-bottom:10px;border:1px solid {color};background:{bg_color};'
            f'box-shadow:4px 4px 0 #000;">'
            f'<tr><td style="padding:8px 10px;font-size:11px;color:{color};font-weight:900;'
            f'font-family:{FONT_MONO};line-height:1.6;letter-spacing:.5px;">'
            f'[ ! ALERT ]&nbsp;{text}</td></tr></table>')

def _ledger_table(rows, pad):
    html = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
    for label, value, *color in rows:
        val_color = color[0] if color else C_INK
        html += (f'<tr><td style="padding:{pad} 0;border-bottom:1px solid {C_HAIR};'
                 f'font-size:12px;color:{C_INK};vertical-align:top;line-height:1.5;'
                 f'font-family:{FONT_MONO};" '
                 f'width="46%">{label}</td>'
                 f'<td style="padding:{pad} 0;border-bottom:1px solid {C_HAIR};'
                 f'font-size:12px;font-weight:900;color:{val_color};text-align:right;'
                 f'line-height:1.5;font-variant-numeric:tabular-nums;'
                 f'font-family:{FONT_MONO};" width="54%">{value}</td></tr>')
    return html + '</table>'

def _data_table(rows):
    return _ledger_table(rows, "8px")

def _mini_table(rows):
    return _ledger_table(rows, "6px")

def _note(text):
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-top:10px;border:1px solid {C_ACCENT_SOFT};background:{C_ZEBRA};'
            f'box-shadow:3px 3px 0 #000;">'
            f'<tr><td style="padding:8px 10px;font-size:10px;color:{C_MUTED};'
            f'font-family:{FONT_MONO};line-height:1.7;letter-spacing:.3px;">'
            f'/*&nbsp;{text}&nbsp;*/</td></tr></table>')

def _subsection(text):
    return (f'<div style="border-top:1px solid {C_ACCENT_SOFT};margin-top:12px;padding:8px 0 2px;'
            f'font-size:12px;font-weight:900;color:{C_CYAN};letter-spacing:1px;'
            f'font-family:{FONT_MONO};text-transform:uppercase;">'
            f'<span style="color:{C_ACCENT};">▶</span> {text}</div>')

def _source_badge(item):
    if item.get("status") != "success":
        return _badge("OFFLINE", "bad")
    if item.get("is_today"):
        return _badge("LIVE", "ok")
    return _badge(f"LAG {item.get('content_date') or '-'}", "warn")

def _item_row(icon, text, sub="", icon_color=C_ACCENT, row_bg="transparent"):
    sub_html = (f'<div style="font-size:10px;color:{C_MUTED};letter-spacing:.3px;'
                f'padding-top:3px;line-height:1.6;font-family:{FONT_MONO};">{sub}</div>' if sub else "")
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'background:{row_bg};">'
            f'<tr><td width="32" valign="top" style="padding:8px 4px 8px 0;border-bottom:1px solid {C_HAIR};'
            f'font-size:11px;font-weight:900;color:{icon_color};line-height:1.6;'
            f'font-family:{FONT_MONO};">{icon}</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid {C_HAIR};font-size:12px;'
            f'color:{C_INK};line-height:1.7;font-family:{FONT_MONO};">{text}{sub_html}</td></tr></table>')

def _headline_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "--"
    display = it.get("title") if isinstance(it, dict) else it
    sub = ""
    if isinstance(it, dict):
        parts = []
        if it.get("source"):
            parts.append(it["source"])
        if it.get("published_cst") and it["published_cst"] != "—":
            parts.append(it["published_cst"])
        sub = " | ".join(parts)
    return _item_row(f"[{marker}]", _esc(display[:120]), _esc(sub[:140]))

def _em_news_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "--"
    if isinstance(it, dict):
        title = it.get("title") or ""
        sub = " :: ".join(x for x in (it.get("time", ""), it.get("summary", "")) if x)
        return _item_row(f"[{marker}]", _esc(title[:120]), _esc(sub[:110]))
    return _item_row(f"[{marker}]", _esc(it[:120]))

def _channel_block(ch):
    name = _esc(ch.get("name", "?"))
    desc = _esc(ch.get("desc", ""))
    url = _esc(ch.get("url", ""))
    videos = ch.get("videos") or []
    if not videos:
        note = _esc(ch.get("note") or "OFFLINE :: NO SIGNAL [暂缺]")
        return (f'<div style="margin:12px 0;border:1px solid {C_FAINT};background:{C_ZEBRA};'
                f'padding:10px 12px;box-shadow:4px 4px 0 #000;">'
                f'<div style="font-size:12px;font-weight:900;color:{C_FAINT};font-family:{FONT_MONO};">[X {name} {_badge("暂缺", "bad")}]</div>'
                f'<div style="font-size:10px;color:{C_MUTED};padding-top:3px;font-family:{FONT_MONO};">{desc}</div>'
                f'<div style="font-size:10px;color:{C_MUTED};line-height:1.6;font-family:{FONT_MONO};margin-top:4px;">> {note}</div></div>')
    badge = _badge("LIVE", "ok") if ch.get("is_today") else _badge("ARCHIVE", "warn")
    messages = []
    top_n = videos[:CHANNEL_TOP_N]
    for vi, v in enumerate(top_n):
        title = _esc(v.get("title", "")[:110])
        pub = _esc(v.get("published_cst", ""))
        link = f'<a href="{_esc(v.get("url", "#"))}" style="color:{C_INK};text-decoration:none;border-bottom:1px dotted {C_ACCENT};">{title}</a>'
        bubble_bg = "#15182B" if vi % 2 == 0 else "#1A1E33"
        border_c = C_ACCENT if vi % 2 == 0 else C_CYAN
        label = ">> FEED" if vi % 2 == 0 else ">> UPDATE"
        new_tag = f' <span style="color:{C_ACCENT_MAGENTA};font-weight:900;background:#2A1320;border:1px solid {C_ACCENT_MAGENTA};padding:0 3px;">[NEW]</span>' if v.get("is_today") else ""
        messages.append((f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:6px;"><tr><td align="left">'
                         f'<div style="display:block;max-width:100%;text-align:left;background:{bubble_bg};border:1px solid {border_c};'
                         f'padding:6px 8px;box-shadow:3px 3px 0 #000;font-size:11px;color:{C_INK};line-height:1.6;font-family:{FONT_MONO};">'
                         f'<div style="font-size:9px;font-weight:900;color:{border_c};letter-spacing:1px;">{label} :: {pub}{new_tag}</div>'
                         f'<div style="padding-top:3px;">> {link}</div></div></td></tr></table>'))
    return (f'<div style="margin:12px 0;border:1px solid {C_ACCENT};background:#0F1222;padding:10px 12px;box-shadow:6px 6px 0 #000;">'
            f'<div style="font-size:12px;font-weight:900;color:{C_ACCENT_DEEP};font-family:{FONT_MONO};">'
            f'<span style="display:inline-block;background:{C_ACCENT};color:#000;padding:0 4px;margin-right:6px;">CH</span>'
            f'<a href="{url}" style="color:{C_INK};text-decoration:none;">{name}</a> {badge}</div>'
            f'<div style="font-size:10px;color:{C_MUTED};padding:4px 0 2px;font-family:{FONT_MONO};">{desc} :: <b style="color:{C_CYAN};">[8-BIT FEED]</b></div>'
            f'{"".join(messages)}</div>')

def _status_footer(sources):
    lines = []
    for name, s in sources:
        if s.get("status") == "success":
            lines.append((_sq(C_GREEN, 8),
                          f'<b style="color:{C_INK};font-family:{FONT_MONO};">{_esc(name)}</b> {_source_badge(s)}'
                          f' <span style="color:{C_MUTED};font-family:{FONT_MONO};">@ {_esc(s.get("fetched_at", "—"))}</span>'))
        else:
            detail = _esc(s.get("error", "暂时不可用"))
            lines.append((_sq(C_RED, 8),
                          f'<b style="color:{C_INK};font-family:{FONT_MONO};">{_esc(name)}</b> [x FAIL] '
                          f'<span style="color:{C_MUTED};font-family:{FONT_MONO};">({detail}) @ {_esc(s.get("fetched_at", "—"))}</span>'))
    rows = "".join(
        f'<tr><td width="22" valign="top" style="padding:5px 0;border-bottom:1px solid {C_HAIR};font-family:{FONT_MONO};">{marker}</td>'
        f'<td style="padding:5px 0;border-bottom:1px solid {C_HAIR};font-size:11px;'
        f'color:{C_MUTED};line-height:1.7;font-family:{FONT_MONO};">{line}</td></tr>'
        for marker, line in lines)
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows}</table>'

def _report_meta(html):
    def g(name):
        m = re.search(rf'name="octopus-{name}" content="([^\"]+)"', html)
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
    border = "" if first else f"border-left:1px solid {C_HAIR};"
    padding = "0" if first else "12px"
    return (f'<td width="33%" valign="top" style="padding:8px 0;{border}">'
            f'<div style="padding-left:{padding};">'
            f'<div style="font-size:8px;font-weight:900;color:{C_ACCENT};letter-spacing:1px;font-family:{FONT_MONO};">{label}</div>'
            f'<div style="font-size:11px;font-weight:900;color:{value_color};padding-top:3px;'
            f'font-family:{FONT_MONO};font-variant-numeric:tabular-nums;">{value}</div></div></td>')

def _section(num, kicker_en, title, content, badge_html="", caption=""):
    """栏目头使用独立大图标砖；AI 栏目以黄色关卡色单独强调。"""
    _, _, section_color, _ = _section_visual(kicker_en)
    badge_cell = (f'<td align="right" valign="middle" style="padding-left:6px;">{badge_html}</td>'
                  if badge_html else "")
    caption_html = (f'<div style="font-size:10px;color:{C_MUTED};letter-spacing:.3px;'
                    f'padding:7px 0 8px 56px;line-height:1.6;font-family:{FONT_MONO};">'
                    f'<span style="color:{section_color};">└─</span> {caption}</div>'
                    if caption else '<div style="padding-bottom:7px;"></div>')
    return f'''
<div style="border-top:1px solid {section_color};margin-top:28px;padding-top:12px;">
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
<tr>
<td width="52" valign="middle" style="padding-right:10px;">{_pixel_icon(kicker_en)}</td>
<td valign="middle">
<div style="font-family:{FONT_MONO};font-size:9px;font-weight:900;color:{section_color};letter-spacing:1px;line-height:1.3;">LVL {num} // {kicker_en}</div>
<div style="font-size:17px;font-weight:900;color:{C_ACCENT_DEEP};letter-spacing:.5px;padding-top:4px;line-height:1.35;font-family:{FONT_MONO};">{title}<span style="color:{section_color};">_</span></div>
</td>
{badge_cell}
</tr>
</table>
{caption_html}
{content}
</div>'''


# ============================================================
# GUIZANG 主题排版（电子杂志 × 电子墨水 · 微信竖版长页面）
# —— 衬线标题（荧光绿）+ 非衬线正文（墨黑）+ 等宽元信息 + 发丝线 + 大留白
# —— 全部字体偏小；宽表格 → 纵向 rowline；因子分析 → 杂志式信号矩阵
# —— 纯内联样式 + 表格布局，无 JS / 无外部 CSS / 无 WebGL，PushPlus/微信兼容
# ============================================================

def _quote_parts(market, label, precision=2):
    """主题无关的行情取值：(价格字符串, 涨跌幅 float|None)；缺失返回 (None, None)。"""
    quote = (market.get("quotes", {}) or {}).get(label)
    if not quote:
        return None, None
    try:
        price_str = f"{float(quote['price']):,.{precision}f}"
    except (TypeError, ValueError, KeyError):
        return None, None
    return price_str, _percent_number(quote.get("change_pct", 0))


def gz_trend_badge(value, compact=False):
    """涨跌徽标：颜色 + 箭头 + 涨/跌/平 三重编码（杂志式描边，无硬投影）。"""
    pct = _percent_number(value)
    if pct is None:
        return (f'<span style="display:inline-block;border:1px solid {GZ_HAIR};color:{GZ_FLAT};background:{GZ_PAPER};'
                f'padding:1px 6px;font-size:9px;line-height:16px;font-family:{GZ_MONO};'
                f'white-space:nowrap;">■ --</span>')
    if pct > 0:
        color, arrow, word = GZ_UP, "▲", "涨"
    elif pct < 0:
        color, arrow, word = GZ_DOWN, "▼", "跌"
    else:
        color, arrow, word = GZ_FLAT, "■", "平"
    label = f"{arrow} {pct:+.2f}%" if compact else f"{arrow} {word} {pct:+.2f}%"
    if pct == 0:
        label = f"{arrow} 0.00%" if compact else f"{arrow} {word} 0.00%"
    return (f'<span style="display:inline-block;border:1px solid {color};color:{color};background:{GZ_PAPER};'
            f'padding:1px 6px;font-size:9px;font-weight:700;line-height:16px;'
            f'font-family:{GZ_MONO};white-space:nowrap;">{label}</span>')


def gz_meter(value, maximum, cells=5, lit=GZ_INK, off=GZ_HAIR, size=9):
    """信号强度发丝格：实心 ■ + 空心 □，不依赖 CSS 渐变。"""
    maximum = max(1, int(maximum or 1))
    n = max(1, min(cells, round(float(value or 0) / maximum * cells))) if value else 0
    return (f'<span style="color:{lit};font-size:{size}px;letter-spacing:2px;line-height:1;">'
            f'{"■" * n}</span>'
            f'<span style="color:{off};font-size:{size}px;letter-spacing:2px;line-height:1;">'
            f'{"□" * (cells - n)}</span>')


def gz_badge(text, kind="ok", on_ink=False):
    """标签胶囊（Style A .tag）：单色发丝边框 + 等宽小字，无硬投影。"""
    if on_ink:
        styles = {"ok": GZ_UP_INK, "warn": GZ_WARN_INK, "bad": GZ_DOWN_INK, "ai": GZ_NEON}
    else:
        styles = {"ok": GZ_UP, "warn": GZ_WARN, "bad": GZ_DOWN, "ai": GZ_INK}
    color = styles.get(kind, GZ_INK)
    dot = "◆" if kind == "ai" else "●"
    return (f'<span style="display:inline-block;border:1px solid {color};color:{color};background:{GZ_PAPER};'
            f'padding:0 6px;margin-left:6px;font-size:8.5px;font-weight:700;line-height:15px;'
            f'font-family:{GZ_MONO};letter-spacing:.5px;vertical-align:middle;white-space:nowrap;">'
            f'{dot} {_esc(text)}</span>')


def gz_source_badge(item, on_ink=False):
    if item.get("status") != "success":
        return gz_badge("OFFLINE", "bad", on_ink)
    if item.get("is_today"):
        return gz_badge("LIVE · 当天", "ok", on_ink)
    return gz_badge(f"LAG {item.get('content_date') or '-'}", "warn", on_ink)


def gz_note(text):
    return (f'<div style="margin-top:12px;padding-top:8px;border-top:1px solid {GZ_HAIR};'
            f'font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};line-height:1.7;'
            f'letter-spacing:.2px;word-break:break-word;">/* {text} */</div>')


def gz_subsection(text):
    return (f'<div style="margin-top:14px;padding-top:8px;border-top:1px solid {GZ_HAIR};'
            f'font-size:11.5px;font-weight:700;color:{GZ_INK};font-family:{GZ_SERIF};'
            f'letter-spacing:.5px;">{text}</div>')


def gz_rowline(label_html, right_html, pad="8px"):
    """rowline：一行一条信息（左等宽元信息 / 右取值 + 涨跌徽标），手机竖排不横向溢出。"""
    return (
        f'<tr>'
        f'<td style="padding:{pad} 0;border-bottom:1px solid {GZ_HAIR};font-size:10.5px;'
        f'color:{GZ_META};font-family:{GZ_MONO};letter-spacing:.5px;vertical-align:top;'
        f'line-height:1.6;word-break:break-word;">{label_html}</td>'
        f'<td align="right" style="padding:{pad} 0;border-bottom:1px solid {GZ_HAIR};'
        f'font-size:11.5px;color:{GZ_INK};vertical-align:top;line-height:1.6;'
        f'padding-left:8px;">{right_html}</td>'
        f'</tr>'
    )


def gz_table(rows_html):
    return (f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;table-layout:fixed;word-break:break-word;">{rows_html}</table>')


def gz_market_row(label, price_str, pct):
    """行情 rowline：左指数名 / 右价格 + 涨跌徽标（宽表格的纵向转换）。"""
    if price_str is None:
        right = (f'<span style="font-size:9.5px;color:{GZ_FLAT};font-family:{GZ_MONO};">'
                 f'■ 数据暂缺</span>')
    else:
        value = (f'<span style="font-size:12.5px;font-weight:700;color:{GZ_INK};'
                 f'font-family:{GZ_MONO};letter-spacing:.5px;">{price_str}</span> ')
        right = value + (
            gz_trend_badge(pct) if pct is not None
            else f'<span style="font-size:9.5px;color:{GZ_FLAT};font-family:{GZ_MONO};">■ 数据暂缺</span>')
    return gz_rowline(_esc(label), right)


def gz_market_section(market):
    """行情速览：两个 group 的 rowline（自动避免横向溢出）。"""
    rows = []
    for label, precision in [("道琼斯指数", 0), ("标普500", 0), ("纳斯达克", 0),
                             ("WTI 原油", 2), ("微软 MSFT", 2), ("Meta META", 2)]:
        price_str, pct = _quote_parts(market, label, precision)
        rows.append(gz_market_row(label, price_str, pct))
    a_rows = []
    for label, precision in [("上证指数", 2), ("深证成指", 2), ("创业板指", 2), ("科创50", 2)]:
        price_str, pct = _quote_parts(market, label, precision)
        a_rows.append(gz_market_row(label, price_str, pct))
    return (gz_subsection("全球与美股") + gz_table("".join(rows))
            + gz_subsection("A股四指数") + gz_table("".join(a_rows))
            + gz_note("涨跌幅基于行情源返回的最近两个有效日线收盘价计算；非交易时段显示最近收盘，不以旧日报数值替代。"))


def gz_headline_row(it, index=None):
    """杂志式头条行：等宽序号 + 非衬线标题 + 等宽溯源。"""
    marker = f"{index:02d}" if isinstance(index, int) else "——"
    display = it.get("title") if isinstance(it, dict) else it
    sub = ""
    if isinstance(it, dict):
        parts = []
        if it.get("source"):
            parts.append(it["source"])
        if it.get("published_cst") and it.get("published_cst") != "—":
            parts.append(it["published_cst"])
        sub = " · ".join(parts)
    sub_html = (f'<div style="font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};'
                f'padding-top:3px;letter-spacing:.3px;word-break:break-all;">{_esc(sub[:140])}</div>' if sub else "")
    return (
        f'<tr>'
        f'<td width="26" valign="top" style="padding:9px 0;border-bottom:1px solid {GZ_HAIR};'
        f'font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};">{marker}</td>'
        f'<td style="padding:9px 0;border-bottom:1px solid {GZ_HAIR};vertical-align:top;word-break:break-word;">'
        f'<div style="font-size:12.5px;color:{GZ_INK};line-height:1.65;">{_esc(display[:120])}</div>'
        f'{sub_html}</td></tr>'
    )


def gz_em_news_row(it, index=None):
    """东财快讯行：等宽序号 + 标题 + 时间/摘要等宽溯源。"""
    marker = f"{index:02d}" if isinstance(index, int) else "——"
    if isinstance(it, dict):
        title = it.get("title") or ""
        sub = " · ".join(x for x in (it.get("time", ""), it.get("summary", "")) if x)
    else:
        title, sub = it, ""
    sub_html = (f'<div style="font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};'
                f'padding-top:3px;letter-spacing:.3px;word-break:break-all;">{_esc(sub[:110])}</div>' if sub else "")
    return (
        f'<tr>'
        f'<td width="26" valign="top" style="padding:9px 0;border-bottom:1px solid {GZ_HAIR};'
        f'font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};">{marker}</td>'
        f'<td style="padding:9px 0;border-bottom:1px solid {GZ_HAIR};vertical-align:top;word-break:break-word;">'
        f'<div style="font-size:12.5px;color:{GZ_INK};line-height:1.65;">{_esc(title[:120])}</div>'
        f'{sub_html}</td></tr>'
    )


def gz_item_row(icon, text, sub="", icon_color=None, row_bg=None):
    """通用条目行（icon_color / row_bg 为 pixel 主题参数，guizang 忽略底色）。"""
    sub_html = (f'<div style="font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};'
                f'padding-top:3px;letter-spacing:.3px;line-height:1.6;word-break:break-all;">{sub}</div>' if sub else "")
    return (
        f'<tr>'
        f'<td width="26" valign="top" style="padding:9px 0;border-bottom:1px solid {GZ_HAIR};'
        f'font-size:10px;font-weight:700;color:{icon_color or GZ_INK};font-family:{GZ_MONO};">{icon}</td>'
        f'<td style="padding:9px 0;border-bottom:1px solid {GZ_HAIR};font-size:12.5px;'
        f'color:{GZ_INK};line-height:1.65;word-break:break-word;">{text}{sub_html}</td></tr>'
    )


def gz_channel_block(ch):
    """频道块：灰黄卡片 + 衬线频道名 + 杂志式条目列表。"""
    name = _esc(ch.get("name", "?"))
    desc = _esc(ch.get("desc", ""))
    url = _esc(ch.get("url", ""))
    videos = ch.get("videos") or []
    if not videos:
        note = _esc(ch.get("note") or "OFFLINE :: NO SIGNAL [暂缺]")
        return (
            f'<div style="margin-top:14px;padding:10px 12px;background:{GZ_PAPER_TINT};border:1px solid {GZ_HAIR};border-radius:4px;">'
            f'<div style="font-size:12.5px;font-weight:700;color:{GZ_FLAT};">'
            f'{name} {gz_badge("暂缺", "bad")}</div>'
            f'<div style="font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};padding-top:4px;'
            f'letter-spacing:.3px;line-height:1.6;word-break:break-word;">{desc} · {note}</div></div>'
        )
    badge = gz_badge("LIVE · 当天", "ok") if ch.get("is_today") else gz_badge("ARCHIVE", "warn")
    name_link = f'<a href="{url}" style="color:{GZ_INK};text-decoration:none;">{name}</a>' if url else name
    items = []
    for vi, v in enumerate(videos[:CHANNEL_TOP_N], 1):
        title = _esc(v.get("title", "")[:110])
        pub = _esc(v.get("published_cst", ""))
        link = f'<a href="{_esc(v.get("url", "#"))}" style="color:{GZ_INK};text-decoration:none;">{title}</a>'
        new_tag = (f' <span style="color:{GZ_UP};font-size:8.5px;font-weight:700;'
                   f'font-family:{GZ_MONO};letter-spacing:.5px;">[NEW · 当天]</span>'
                   if v.get("is_today") else "")
        items.append(
            f'<tr>'
            f'<td width="24" valign="top" style="padding:7px 0;border-bottom:1px solid {GZ_HAIR};'
            f'font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};">{vi:02d}</td>'
            f'<td style="padding:7px 0;border-bottom:1px solid {GZ_HAIR};vertical-align:top;word-break:break-word;">'
            f'<div style="font-size:12px;color:{GZ_INK};line-height:1.6;">{link}{new_tag}</div>'
            f'<div style="font-size:9px;color:{GZ_META};font-family:{GZ_MONO};padding-top:2px;'
            f'letter-spacing:.3px;">{pub}</div></td></tr>'
        )
    return (
        f'<div style="margin-top:14px;padding:12px 14px;background:{GZ_PAPER_TINT};border:1px solid {GZ_HAIR};border-radius:4px;">'
        f'<div style="font-size:13.5px;font-weight:700;color:{GZ_INK};font-family:{GZ_SERIF};'
        f'letter-spacing:.5px;">{name_link} {badge}</div>'
        f'<div style="font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};padding-top:4px;'
        f'letter-spacing:.3px;line-height:1.6;word-break:break-word;">{desc}</div>'
        f'<div style="margin-top:4px;">{gz_table("".join(items))}</div></div>'
    )


def gz_status_footer(sources):
    """数据审计行：绿/红点 + 来源名 + 状态徽标 + 等宽抓取时间。"""
    rows = []
    for name, s in sources:
        if s.get("status") == "success":
            rows.append((GZ_UP, _esc(name), gz_source_badge(s),
                         f'@ {_esc(s.get("fetched_at", "—"))}'))
        else:
            detail = _esc(s.get("error", "暂时不可用"))
            rows.append((GZ_DOWN, _esc(name),
                         f'<span style="font-size:8.5px;font-weight:700;color:{GZ_DOWN};'
                         f'font-family:{GZ_MONO};letter-spacing:.5px;">[x FAIL]</span>',
                         f'（{detail}）@ {_esc(s.get("fetched_at", "—"))}'))
    trs = []
    for color, name, badge, tail in rows:
        trs.append(
            f'<tr>'
            f'<td width="8" valign="top" style="padding:6px 6px 6px 0;font-size:8px;color:{color};line-height:1.4;">●</td>'
            f'<td style="padding:6px 0;border-bottom:1px solid {GZ_HAIR};font-size:10.5px;'
            f'color:{GZ_INK};line-height:1.7;word-break:break-word;">{name} {badge} '
            f'<span style="color:{GZ_META};font-family:{GZ_MONO};font-size:9px;word-break:break-all;">{tail}</span></td></tr>'
        )
    return gz_table("".join(trs))


def gz_alert(text, color=None):
    """引言式警示条：灰黄同系加深底 + 左侧色条（无硬投影）。"""
    c = color or GZ_INK
    return (
        f'<div style="margin-bottom:12px;padding:10px 12px;background:{GZ_PAPER_TINT};border-radius:2px;'
        f'border-left:3px solid {c};font-size:11px;color:{GZ_INK};line-height:1.75;word-break:break-word;">'
        f'<span style="font-family:{GZ_MONO};font-size:8.5px;font-weight:700;letter-spacing:1px;'
        f'color:{c};">ALERT · </span>{text}</div>'
    )


def gz_masthead_cell(label, value, value_color=GZ_CREAM, first=False):
    border = "" if first else f"border-left:1px solid {GZ_HAIR_INK};"
    padding = "0 4px 0 0" if first else "0 4px 0 8px"
    return (
        f'<td width="33%" valign="top" style="padding:4px 0;{border};word-break:break-all;">'
        f'<div style="padding:{padding};">'
        f'<div style="font-size:8px;color:{GZ_META_INK};letter-spacing:1px;font-family:{GZ_MONO};">{label}</div>'
        f'<div style="font-size:10.5px;font-weight:700;color:{value_color};padding-top:2px;'
        f'font-family:{GZ_MONO};">{value}</div></div></td>'
    )


def gz_section(num, kicker_en, title, content, badge_html="", caption=""):
    """章节幕封：灰黄底卡片 + 墨黑标题 + 等宽 kicker；正文落于灰黄纸底。"""
    caption_html = (f'<div style="font-size:9.5px;color:{GZ_META_INK};font-family:{GZ_MONO};'
                    f'padding-top:5px;letter-spacing:.3px;line-height:1.6;">{caption}</div>'
                    if caption else "")
    return (
        f'<div style="margin-top:22px;background:{GZ_INK_TINT};border:1px solid {GZ_HAIR_INK};'
        f'padding:12px 14px 10px;border-radius:4px;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>'
        f'<td style="font-size:9px;color:{GZ_META_INK};font-family:{GZ_MONO};font-weight:700;'
        f'letter-spacing:1.5px;line-height:1;">{num} / {kicker_en}</td>'
        f'<td align="right" valign="middle">{badge_html}</td>'
        f'</tr></table>'
        f'<div style="font-size:15.5px;font-weight:700;color:{GZ_NEON};font-family:{GZ_SERIF};'
        f'letter-spacing:.5px;padding-top:7px;line-height:1.35;">{title}</div>'
        f'{caption_html}</div>'
        f'<div style="padding:10px 2px 4px;">{content}</div>'
    )


def gz_ai_analysis_block(res):
    """AI 盘研判（guizang）：杂志式信号矩阵 —— 方向 / 信号分 / 置信度 / 研判概率
    + 板块热度 / 技术速读 / 风险提示 / 明日主题（保留涨跌颜色、概率与证据）。"""
    score = int(res["score"])
    if score > 8:
        arrow, bias_color = "▲", GZ_UP
    elif score < -8:
        arrow, bias_color = "▼", GZ_DOWN
    else:
        arrow, bias_color = "■", GZ_FLAT
    # 研判概率：由信号分规则估算（|score| 越高概率上界越高）；非统计预测，页脚已注明
    prob = 50 + min(30, abs(score) * 30 // 100)
    prob_chip = (f'<span style="display:inline-block;border:1px solid {bias_color};'
                 f'color:{bias_color};padding:1px 7px;font-size:9px;font-weight:700;'
                 f'line-height:16px;font-family:{GZ_MONO};white-space:nowrap;background:{GZ_PAPER};">P {prob}%</span>')

    # ① 主控条（灰黄底卡片）：方向 + 信号分 + 置信度 + 研判概率 + 信号格
    verdict = (
        f'<div style="background:{GZ_PAPER_TINT};border:1px solid {GZ_HAIR};padding:12px 14px;border-radius:4px;">'
        f'<div style="font-size:8.5px;color:{GZ_META};font-family:{GZ_MONO};letter-spacing:1.5px;">'
        f'MARKET BIAS · 市场倾向 // RULESET v3</div>'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:6px;"><tr>'
        f'<td valign="middle">'
        f'<div style="font-size:20px;font-weight:700;color:{bias_color};font-family:{GZ_SERIF};'
        f'line-height:1.2;">{_esc(res["sentiment_label"])} {arrow}</div>'
        f'<div style="font-size:8.5px;color:{GZ_META};font-family:{GZ_MONO};padding-top:3px;'
        f'letter-spacing:1px;">{_esc(res["sentiment_en"])}</div>'
        f'</td>'
        f'<td align="right" valign="middle">'
        f'<div style="font-size:8.5px;color:{GZ_META};font-family:{GZ_MONO};letter-spacing:.5px;">'
        f'SIGNAL {score:+d} · CONF {_esc(res["confidence"])}</div>'
        f'<div style="padding-top:4px;text-align:right;">{prob_chip} '
        f'<span style="font-size:8px;color:{GZ_META};font-family:{GZ_MONO};">研判概率</span></div>'
        f'<div style="padding-top:4px;text-align:right;">'
        f'{gz_meter(abs(score), 100, 8, bias_color, GZ_HAIR, 8)}</div>'
        f'</td>'
        f'</tr></table></div>'
    )

    # ② 主结论（纸）：衬线导语
    thesis = (
        f'<div style="margin-top:10px;padding:10px 12px;background:{GZ_PAPER_TINT};border-left:3px solid {GZ_INK};border-radius:2px;">'
        f'<div style="font-size:8px;color:{GZ_META};font-family:{GZ_MONO};letter-spacing:1px;">'
        f'READ THIS FIRST · 先看结论</div>'
        f'<div style="font-size:12px;color:{GZ_INK};line-height:1.8;padding-top:4px;'
        f'font-weight:700;">{_esc(res["reason"])}</div></div>'
    )

    # ③ 板块热度 rowline（保留命中数能量格）
    if res["sectors_strong"]:
        max_hits = max(cnt for _, cnt in res["sectors_strong"])
        sec_rows = "".join(
            gz_rowline(_esc(sec),
                       f'{gz_meter(cnt, max_hits, 5, GZ_INK, GZ_HAIR)} '
                       f'<span style="font-size:9px;color:{GZ_META};font-family:{GZ_MONO};">{cnt} HIT</span>')
            for sec, cnt in res["sectors_strong"])
        sectors_html = gz_subsection("SECTOR SCAN · 板块热度") + gz_table(sec_rows)
        if res["sectors_weak"]:
            sectors_html += (
                f'<div style="margin-top:10px;padding:8px 10px;border-left:2px solid {GZ_DOWN};'
                f'background:{GZ_PAPER_TINT};border-radius:2px;font-size:11px;color:{GZ_DOWN};font-weight:700;line-height:1.7;">'
                f'▼ 承压板块 · {" / ".join(_esc(s) for s in res["sectors_weak"])}</div>')
    else:
        sectors_html = (gz_subsection("SECTOR SCAN · 板块热度")
                        + f'<div style="font-size:10px;color:{GZ_FLAT};font-family:{GZ_MONO};'
                          f'padding:8px 0;">■ NO SECTOR SIGNAL</div>')

    # ④ 技术速读 rowline（保留 ▲/▼/■ 涨跌颜色与档位）
    if res["tech_rows"]:
        band_palette = {"强势": GZ_UP, "偏强": GZ_UP, "震荡": GZ_WARN,
                        "偏弱": GZ_DOWN, "弱势": GZ_DOWN}
        tech_rows = "".join(
            gz_rowline(_esc(label),
                       f'{gz_trend_badge(pct, compact=True)} '
                       f'<span style="font-size:10px;font-weight:700;color:'
                       f'{band_palette.get(band, GZ_INK)};">{_esc(band)}</span>')
            for label, pct, band, _ in res["tech_rows"])
        tech_html = (gz_subsection("TECH READ · 指数动能") + gz_table(tech_rows)
                     + f'<div style="font-size:11.5px;color:{GZ_INK};line-height:1.8;padding-top:10px;word-break:break-word;">'
                       f'<span style="font-family:{GZ_MONO};font-size:8px;color:{GZ_META};'
                       f'letter-spacing:1px;">◆ AI 解读 · </span>'
                       f'{_esc(res["tech_read"])}</div>')
    else:
        tech_html = (gz_subsection("TECH READ · 指数动能")
                     + f'<div style="font-size:10px;color:{GZ_FLAT};font-family:{GZ_MONO};'
                       f'padding:8px 0;">■ NO MARKET DATA</div>')

    # ⑤ 风险提示（保留风险项与来源证据）
    if res["risks"]:
        risk_rows = "".join(
            gz_item_row("!", _esc(t), _esc(src), icon_color=GZ_DOWN)
            for t, src in res["risks"])
        risk_html = gz_subsection("RISK LOG · 风险提示") + gz_table(risk_rows)
    else:
        risk_html = (gz_subsection("RISK LOG · 风险提示")
                     + f'<div style="font-size:10.5px;color:{GZ_UP};font-weight:700;padding:8px 0;">'
                       f'✓ CLEAR · 未检出显著风险舆情</div>')

    # ⑥ 明日关注（2026-08-06 起只保留主题行）
    if res["themes"]:
        watch_html = (
            f'<div style="margin-top:12px;padding:9px 12px;background:{GZ_PAPER_TINT};border:1px solid {GZ_HAIR};border-radius:3px;'
            f'font-size:11.5px;font-weight:700;color:{GZ_NEON};font-family:{GZ_SERIF};'
            f'letter-spacing:.5px;">★ 主题解锁 · {_esc(res["themes"])}</div>')
    else:
        watch_html = (f'<div style="margin-top:12px;font-size:10px;color:{GZ_FLAT};'
                      f'font-family:{GZ_MONO};padding:8px 0;">■ NO WATCH THEME</div>')

    note_html = gz_note("AI 盘研判由公开数据经确定性规则合成 // 研判概率为规则估算（信号分映射）· 非统计预测 // 非投资建议，决策需独立判断")
    return verdict + thesis + sectors_html + tech_html + risk_html + watch_html + note_html


def gz_liquidity_market_block(label, stats):
    """单市场流动性研判（guizang）：衬线评分大字 + 发丝格 + 聚合指标 rowline。"""
    if not stats.get("sample_count"):
        return (f'<div style="margin-top:10px;padding:8px 12px;background:{GZ_PAPER_TINT};border:1px solid {GZ_HAIR};'
                f'border-radius:3px;font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};letter-spacing:.3px;">'
                f'■ {_esc(label)} :: LIQUIDITY = NULL [NO SIGNAL]</div>')
    score = int(stats.get("score", 0))
    color = GZ_UP if score >= 58 else (GZ_DOWN if score < 42 else GZ_INK)
    breadth = (
        f'<span style="color:{GZ_UP};font-weight:700;font-family:{GZ_MONO};font-size:10px;">▲ {stats.get("advancers", 0)}</span> / '
        f'<span style="color:{GZ_DOWN};font-weight:700;font-family:{GZ_MONO};font-size:10px;">▼ {stats.get("decliners", 0)}</span> / '
        f'<span style="color:{GZ_FLAT};font-weight:700;font-family:{GZ_MONO};font-size:10px;">■ {stats.get("flats", 0)}</span>')
    rows = "".join([
        gz_rowline("SAMPLE_VOL",
                   f'<span style="font-family:{GZ_MONO};font-size:11px;">{_format_amount(stats.get("total_amount"))}</span>'),
        gz_rowline("TOP10_SHARE", f'<span style="font-family:{GZ_MONO};font-size:11px;">{stats.get("top10_share", 0) * 100:.1f}%</span>'),
        gz_rowline("ADV / DEC / FLAT", breadth),
        gz_rowline("DIFFUSE_RATIO", f'<span style="font-family:{GZ_MONO};font-size:11px;">{stats.get("adv_dec_ratio", 0):.2f}x</span>'),
        gz_rowline("WEIGHTED_CHG", gz_trend_badge(stats.get("weighted_change", 0))),
        gz_rowline("AVG_TURNOVER", f'<span style="font-family:{GZ_MONO};font-size:11px;">{stats.get("avg_turnover", 0):.2f}%</span>'),
    ])
    return (
        f'<div style="margin-top:14px;padding:12px 14px;background:{GZ_PAPER_TINT};border:1px solid {GZ_HAIR};border-radius:4px;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>'
        f'<td valign="middle">'
        f'<div style="font-size:8px;color:{GZ_META};font-family:{GZ_MONO};letter-spacing:1px;">'
        f'{_esc(label)} // LIQUIDITY SCORE</div>'
        f'<div style="font-size:18px;font-weight:700;color:{color};font-family:{GZ_SERIF};'
        f'padding-top:2px;">{score} PTS <span style="font-size:10.5px;">· {_esc(stats.get("level", "—"))}</span></div>'
        f'<div style="padding-top:4px;">{gz_meter(score, 100, 10, color, GZ_HAIR, 8)}</div>'
        f'</td>'
        f'<td align="right" valign="middle" style="font-size:10px;color:{GZ_INK};line-height:1.7;">'
        f'◆ AI 定性：<b style="color:{color};">{_esc(stats.get("tone", "—"))}</b><br>'
        f'<span style="color:{GZ_META};font-family:{GZ_MONO};font-size:9px;">样本 {stats.get("sample_count", 0)} 只</span>'
        f'</td></tr></table>'
        f'<div style="padding-top:8px;">{gz_table(rows)}</div></div>'
    )


def _gz_direction_prob(chg):
    """方向研判概率：按指数涨跌幅幅度的规则估算（50% 基准 + 最多 ±30 个百分点）。"""
    if chg is None:
        return None
    return 50 + min(30, int(round(abs(chg) * 20)))


def _gz_factor_sentiment(text):
    """因子方向：复用 AI 盘研判的多/空词表做确定性计数。"""
    bull = sum(text.count(w) for w in _AI_BULL_WORDS)
    bear = sum(text.count(w) for w in _AI_BEAR_WORDS)
    if bull > bear:
        return "▲", GZ_UP
    if bear > bull:
        return "▼", GZ_DOWN
    return "■", GZ_FLAT


def _gz_market_change(quotes, labels):
    chgs = []
    for lbl in labels:
        q = (quotes or {}).get(lbl)
        if isinstance(q, dict):
            p = _percent_number(q.get("change_pct", 0))
            if p is not None:
                chgs.append(p)
    return (sum(chgs) / len(chgs)) if chgs else None


def gz_build_multi_factor_matrix_html(liq, hot=None, market=None, data=None):
    """因子分析 → 杂志式信号矩阵：每市场 = 指数涨跌徽标 + 概率（规则估算）
    + 环境/政治/地缘 三个因子行（方向色 + 概率 + 一句话证据）。"""
    quotes = (market or {}).get("quotes", {}) or {}
    markets = liq.get("markets", {}) or {}

    def _yahoo_info(labels):
        items = []
        for lbl in labels:
            q = quotes.get(lbl)
            if q and isinstance(q, dict):
                p = q.get("price", 0)
                chg = q.get("change_pct", 0)
                vol = q.get("volume", 0)
                vol_str = f" Vol:{_format_amount(vol)}" if vol else ""
                items.append(f"{lbl} {p:.2f}({chg:+.2f}%{vol_str})")
        return " | ".join(items) if items else "Yahoo 实际公开收盘/报价整合"

    def _liq_summary(mk):
        st = markets.get(mk) or {}
        if not st.get("sample_count"):
            return f"{mk}量能样本待复核"
        return (f"{mk}流动性得分 {st.get('score', 50)} PTS"
                f"（{_esc(st.get('tone', '—'))}，集中度 {st.get('top10_share', 0) * 100:.1f}%）")

    factor_labels = [("环境", "ENV"), ("政治", "POL"), ("地缘", "GEO")]

    def _matrix(title, change, yahoo, liq_label, views):
        prob = _gz_direction_prob(change)
        if change is None:
            head_badge = (f'<span style="font-size:9px;color:{GZ_FLAT};font-family:{GZ_MONO};">'
                          f'■ 数据暂缺</span>')
        else:
            head_badge = gz_trend_badge(change)
            if prob is not None:
                pcolor = GZ_UP if change > 0 else (GZ_DOWN if change < 0 else GZ_FLAT)
                head_badge += (f' <span style="display:inline-block;border:1px solid {pcolor};'
                               f'color:{pcolor};padding:1px 7px;font-size:9px;font-weight:700;'
                               f'line-height:16px;font-family:{GZ_MONO};white-space:nowrap;background:{GZ_PAPER};">'
                               f'P {prob}%</span>')
        factor_rows = []
        for i, (fzh, fen) in enumerate(factor_labels, 1):
            view = views[i - 1]
            arrow, fcolor = _gz_factor_sentiment(view)
            prob_html = ""
            if prob is not None:
                prob_html = (f' <span style="font-size:9px;font-weight:700;color:{fcolor};'
                             f'font-family:{GZ_MONO};">P {prob}%</span>')
            factor_rows.append(
                f'<div style="padding:8px 0;border-top:1px solid {GZ_HAIR};">'
                f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>'
                f'<td style="font-size:9px;color:{GZ_META};font-family:{GZ_MONO};letter-spacing:1px;">'
                f'{i:02d} · {fen} {fzh}</td>'
                f'<td align="right" style="font-size:9.5px;font-weight:700;color:{fcolor};'
                f'font-family:{GZ_MONO};white-space:nowrap;">{arrow}{prob_html}</td>'
                f'</tr></table>'
                f'<div style="font-size:11.5px;color:{GZ_INK};line-height:1.75;padding-top:4px;word-break:break-word;">'
                f'{view}</div></div>')
        meta = (f'<div style="font-size:9px;color:{GZ_META};font-family:{GZ_MONO};line-height:1.7;'
                f'letter-spacing:.2px;padding-top:6px;word-break:break-all;">'
                f'<div>雅虎最新数据 · {_esc(yahoo)}</div>'
                f'<div>资金与交投锚点 · {_esc(liq_label)}</div></div>')
        return (
            f'<div style="margin-top:14px;padding:12px 14px;background:{GZ_PAPER_TINT};border:1px solid {GZ_HAIR};border-radius:4px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>'
            f'<td style="font-size:13.5px;font-weight:700;color:{GZ_INK};font-family:{GZ_SERIF};'
            f'letter-spacing:.3px;">{title}</td>'
            f'<td align="right" valign="middle" style="padding-left:6px;">{head_badge}</td>'
            f'</tr></table>'
            f'{meta}'
            f'<div style="margin-top:6px;border-top:1px solid {GZ_HAIR};">{"".join(factor_rows)}</div>'
            f'</div>'
        )

    views_overall = [
        "美联储利率转向预期的博弈持续扰动全球流动性与大宗商品估值中枢。",
        "各国财政赤字与产业政策分化驱动不同区域交投特征呈现结构性强弱特征。",
        "关税与供应链壁垒推升全球避险溢价，资金核心定价向高安全边际的主线底座收敛。",
    ]
    views_a = [
        "国内宏观稳增长与流动性适度宽松构筑坚实底座，核心主线资金承接顺畅。",
        "产业红利与科技自主自强政策持续激发龙头核心技术突破与优质细分出海机遇。",
        "低位筹码结构稳固有效缓冲外部关税摩擦，市场中期具备充沛的底部放量配置弹性。",
    ]
    views_hk = [
        "离岸资金对科技龙头与低估值蓝筹具备显著吸金效应与换手粘性。",
        "内地扩内需与金融双向开放举措为港股基本面盈利修复提供长期坚实引擎。",
        "中美地缘情绪扰动无碍港股极低估值红利安全边际，资产兼具配置防御与估值弹性。",
    ]
    views_us = [
        "交投量能持续维系于算力及科技巨头标的，高利率环境下资金极度偏向龙头护城河。",
        "美国大选政策主张与本土制造业补贴提振重点结构偏好，加剧了不同板块分化表现。",
        "对华科技出口管制与贸易关税推高了中长期定价溢价，高位横盘博弈下波动不确定性显著加大。",
    ]

    return (
        f'<div style="margin-top:16px;padding-top:10px;border-top:1px solid {GZ_HAIR};">'
        f'<div style="font-size:9px;color:{GZ_META};font-family:{GZ_MONO};letter-spacing:1px;">'
        f'MULTI-FACTOR AI THESIS · 信号矩阵 // 雅虎最新股票数据 · 环境/政治/地缘（每因子一句话证据）</div>'
        + _matrix("整体市场 · 宏观多因子",
                  _gz_market_change(quotes, ["标普500", "纳斯达克", "道琼斯指数", "WTI 原油"]),
                  _yahoo_info(["标普500", "纳斯达克", "道琼斯指数", "WTI 原油"]),
                  f"各市场样本汇聚 · {_esc(liq.get('summary', '全网资金监测'))}", views_overall)
        + _matrix("A股 · 多因子",
                  _gz_market_change(quotes, ["上证指数", "深证成指"]),
                  _yahoo_info(["上证指数", "深证成指", "创业板指", "科创50"]), _liq_summary("A股"), views_a)
        + _matrix("港股 · 多因子",
                  _gz_market_change(quotes, ["恒生指数", "恒生科技"]),
                  _yahoo_info(["恒生指数", "恒生科技"]), _liq_summary("港股"), views_hk)
        + _matrix("美股 · 多因子",
                  _gz_market_change(quotes, ["标普500", "纳斯达克"]),
                  _yahoo_info(["标普500", "纳斯达克", "微软 MSFT", "Meta META"]), _liq_summary("美股"), views_us)
        + '</div>'
    )


def gz_build_volume_and_liquidity_analysis_html(liq, hot=None, market=None, data=None):
    """三大市场交投研判 + 因子信号矩阵（guizang 杂志式排版）。"""
    markets = liq.get("markets", {}) or {}
    hot_markets = (hot or {}).get("markets", {}) or {}
    summary_text = _esc(liq.get("summary") or "A股、港股与美股最近收盘流动性与成交量量化对比。")

    def _market_eval(mk_label, liq_stat, hot_stat):
        if not liq_stat.get("sample_count"):
            return (f'<div style="margin-top:8px;padding:8px 10px;background:{GZ_PAPER_TINT};border:1px solid {GZ_HAIR};border-radius:3px;'
                    f'font-size:10.5px;color:{GZ_META};line-height:1.7;">'
                    f'◆ {mk_label}：本次流动性与交投有效样本暂缺。</div>')
        score = liq_stat.get("score", 50)
        level = _esc(liq_stat.get("level", "—"))
        tone = _esc(liq_stat.get("tone", "—"))
        w_chg = liq_stat.get("weighted_change", 0.0)
        top10_sh = liq_stat.get("top10_share", 0.0) * 100
        adv = liq_stat.get("advancers", 0)
        dec = liq_stat.get("decliners", 0)
        stocks = (hot_stat or {}).get("stocks", []) or []
        stock_names = "、".join(_esc(s.get("name", "")) for s in stocks[:3] if s.get("name"))
        vol_comment = f"近期成交量前列涉及 {stock_names} 等活跃标的，" if stock_names else "活跃标的交投有序，"
        if w_chg >= 0.25:
            flow_dir = "成交金额加权动能偏多，主流资金承接顺畅，交投向结构性主线扩散"
        elif w_chg <= -0.25:
            flow_dir = "成交金额加权动能偏弱，高位筹码换手阶段性防御避险诉求显著"
        else:
            flow_dir = "多空交投较均衡，成交重心处于中性横盘震荡区间"
        return (
            f'<div style="margin-top:8px;padding:10px 12px;background:{GZ_PAPER_TINT};border-left:3px solid {GZ_INK};border-radius:2px;'
            f'line-height:1.75;font-size:11.5px;color:{GZ_INK};">'
            f'<b>◆ {mk_label}成交量与流动性研判：</b>'
            f'流动性评分 <b>{score} PTS</b>（{level} · {tone}），'
            f'头部前十成交集中度约 <b>{top10_sh:.1f}%</b>，上涨/下跌扩散度 <b>{adv}</b> / <b>{dec}</b>。'
            f'{vol_comment}{flow_dir}。'
            f'</div>'
        )

    a_eval = _market_eval("A股", markets.get("A股") or {}, hot_markets.get("A股") or {})
    hk_eval = _market_eval("港股", markets.get("港股") or {}, hot_markets.get("港股") or {})
    us_eval = _market_eval("美股", markets.get("美股") or {}, hot_markets.get("美股") or {})

    mf_html = gz_build_multi_factor_matrix_html(liq, hot, market, data)

    return (
        f'<div style="font-size:9px;color:{GZ_META};font-family:{GZ_MONO};letter-spacing:1px;">'
        f'AI FLOW & VOLUME SCAN // 三大市场交投研判</div>'
        f'<div style="font-size:12px;color:{GZ_INK};line-height:1.8;padding-top:6px;">{summary_text}</div>'
        f'{a_eval}{hk_eval}{us_eval}'
        f'{mf_html}'
    )


def gz_liquidity_report_block(liq, hot=None, market=None, data=None):
    """A股/港股/美股 成交量与流动性报告（guizang）：交投研判 + 信号矩阵 + 三市场评分。"""
    markets = liq.get("markets", {}) or {}
    blocks = "".join(gz_liquidity_market_block(label, markets.get(label) or {})
                     for label in ("A股", "港股", "美股"))
    summary_body = gz_build_volume_and_liquidity_analysis_html(liq, hot, market, data)
    note = gz_note("LIQUIDITY & MULTI-FACTOR FORMULA: YAHOO QUOTES + VOLUME LEADERS + LIQUIDITY + ENV/POLITICAL/GEOPOLITICAL :: RULESET v3 :: 非投资建议")
    return summary_body + blocks + note


# ============================================================
# 主题渲染套件：把 pixel / guizang 两套布局助手统一成栏目拼版接口
# ============================================================
class _RenderKit:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _pixel_market_section(market):
    market_rows = []
    for label, precision in [("道琼斯指数", 0), ("标普500", 0), ("纳斯达克", 0),
                             ("WTI 原油", 2), ("微软 MSFT", 2), ("Meta META", 2)]:
        value, color = _quote_value(market, label, precision)
        market_rows.append((label, value, color))
    astock_rows = []
    for label, precision in [("上证指数", 2), ("深证成指", 2), ("创业板指", 2), ("科创50", 2)]:
        value, color = _quote_value(market, label, precision)
        astock_rows.append((label, value, color))
    return (_subsection("全球与美股") + _data_table(market_rows)
            + _subsection("A股四指数") + _data_table(astock_rows)
            + _note("涨跌幅基于行情源返回的最近两个有效日线收盘价计算；非交易时段显示最近收盘，不以旧日报数值替代。"))


def _collect_report_parts(data, kit):
    """提取逐栏目内容与当天检验统计（两主题共用；仅渲染套件不同）。"""
    market = data.get("实时行情", {})
    yt = data.get("港股名家频道", {})
    yt_live = yt.get("channels", [])        # 已抓取到内容的频道
    google = data.get("全球头条", {})
    gh_headlines = google.get("headlines", [])
    sina = data.get("A股资讯", {})
    sina_headlines = sina.get("headlines", [])
    em = data.get("东财快讯", {})
    em_headlines = em.get("headlines", [])
    hot = data.get("热门榜单", {}) or {}
    liq = data.get("A港美流动性", {}) or data.get("A港流动性", {}) or {}

    source_items = [
        ("实时行情", market),
        ("港股名家频道", yt),
        ("全球头条", google),
        ("A股资讯", sina),
        ("东财快讯", em),
        ("热门榜单", hot),
        ("A港美流动性", liq),
    ]

    total = len(source_items)
    today_n = sum(1 for _, s in source_items if s.get("is_today"))
    content_n = sum(1 for _, s in source_items if s.get("status") == "success")

    sections = []  # (kicker_en, title, content, badge_html, caption)

    # 行情速览
    if market.get("status") == "success":
        data_date = market.get("content_date") or "—"
        sections.append((
            "MARKET SNAPSHOT", "行情速览（实时）",
            kit.market_section(market),
            kit.source_badge(market),
            f"{_source_note(market)} · 数据日期 {data_date}",
        ))

    # 港股名家频道：只显示实际抓取到内容的频道
    if yt_live:
        blocks = "".join(kit.channel_block(ch) for ch in yt_live)
        note = f"本次 {len(yt_live)}/{len(HK_CHANNELS)} 个频道可自动抓取"
        sections.append((
            "HK GURU CHANNELS", "港股名家频道",
            blocks + kit.note(f"数据来自各频道公开 RSS；{note}。带 NEW · 当天 标记的内容发布于今天（北京时间）；"
                              f"每个频道列出最新 {CHANNEL_TOP_N} 条。"),
            kit.source_badge(yt),
            f"{_source_note(yt)} · 内容最新日期 {_esc(yt.get('content_date') or '—')}",
        ))

    # 全球头条（Google News 中文）
    if gh_headlines:
        gh_items = "".join(kit.headline_row(it, i)
                           for i, it in enumerate(gh_headlines[:8], 1))
        sections.append(("GLOBAL HEADLINES", "全球头条", gh_items,
                         kit.source_badge(google), _source_note(google)))

    # 东方财富快讯
    if em_headlines:
        em_items = "".join(kit.em_news_row(it, i)
                           for i, it in enumerate(em_headlines[:5], 1))
        sections.append(("EASTMONEY WIRE", "东方财富快讯", em_items,
                         kit.source_badge(em),
                         f"{_source_note(em)} · 免费公开数据源"))

    # A股市场（四指数行情已并入「行情速览」，这里只展示新浪资讯）
    if sina_headlines:
        sina_items = "".join(kit.item_row(f"{i:02d}", _esc(h[:120]))
                             for i, h in enumerate(sina_headlines[:5], 1))
        sections.append(("A-SHARE DESK", "A股市场（实时行情 + 资讯）", sina_items,
                         kit.source_badge(sina), _source_note(sina)))

    # A股 / 港股 / 美股最近收盘成交量与流动性报告（AI 研判 & 100字多因子结论）
    if liq.get("status") == "success" or market.get("status") == "success":
        sections.append((
            "A/H/US LIQUIDITY", "AI 研判 · 最近 A股、港股、美股成交量与流动性分析",
            kit.liquidity_block(liq, hot, market, data),
            kit.source_badge(liq),
            f"{_source_note(liq)} · 雅虎股票数据 & 多因子100字结论",
        ))

    # AI 盘研判（规则合成综合研判，作为导读首位栏目）
    if AI_ANALYSIS_ENABLED:
        ai_result = build_ai_analysis(data)
        if ai_result.get("available"):
            sections.insert(0, (
                "AI READ", "AI 盘研判",
                kit.ai_block(ai_result), kit.ai_badge(),
                "章鱼AI · 多源信号规则合成（非投资建议）",
            ))

    # 数据审计栏
    if today_n > 0:
        push_hint = f"有 {today_n}/{total} 个数据源为当天内容 → 本次会自动推送（除非 --no-push）。"
        hint_color = kit.ok_color
    else:
        push_hint = ("无当天内容 → 本次默认不会推送；确认内容后可用 --force-push 手动强制推送。"
                     if content_n > 0 else
                     "无任何抓取内容 → 本次不会推送。")
        hint_color = kit.warn_color if content_n > 0 else kit.bad_color

    audit_content = (
        kit.alert(f"本次运行 {content_n}/{total} 个数据源抓到内容，其中 {today_n} 个为当天内容；"
                  f"所有暂缺项均已明确标注，不会复用旧日报内容。",
                  kit.ok_color if today_n > 0 else hint_color)
        + kit.status_footer(source_items)
        + kit.note(f"{push_hint}生成、抓取和推送是独立步骤：请以各来源的抓取时间、数据日期和当天标记判断数据新鲜度。")
    )
    sections.append(("DATA AUDIT", "本次数据可用性 · 当天检验", audit_content, "", ""))

    return {
        "sections": sections,
        "total": total,
        "today_n": today_n,
        "content_n": content_n,
        "market": market,
        "liq": liq,
    }


# ============================================================
# 报告生成（RETRO PIXEL 排版：终端 + 关卡 + 审计 + COLOPHON）
# ——只渲染有内容的区块；每个区块带来源、抓取时间与「当天/非当天/无数据」徽标
# ============================================================
# ============================================================
# AI 盘研判（规则 / 启发式合成，无需大模型 API）
# ------------------------------------------------------------
# 基于当日已抓取的多源信号（实时行情、热门榜单、全球/东财/A股头条、
# 港股名家频道观点）做确定性合成，输出一个跨市场综合研判：
#   情绪定调（多/空/中性 + 信号分 + 置信度）、板块热度、技术速读、
#   风险提示、明日关注主题。全部由规则计算，可复现、不调外部大模型、
#   不伪造内容；明确标注「非投资建议」。
# 2026-08-06 起 WATCH LIST // 明日关注 不再列出榜单个股，只保留主题行；
# 个股仅作为板块热度与交投研判的输入。
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
    yt = data.get("港股名家频道", {}) or {}

    google_headlines = google.get("headlines", []) or []
    em_headlines = em.get("headlines", []) or []
    sina_headlines = sina.get("headlines", []) or []
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
    for ch in yt_channels:
        for v in ch.get("videos", []) or []:
            headlines_struct.append((v.get("title", ""), ch.get("name", "")))

    # 热门榜单个股不再单独列入关注清单（2026-08-06 起 WATCH LIST 只保留主题行）；
    # 个股仍作为 AI 研判输入：板块热度识别与「AI 研判 · 成交量与流动性分析」的活跃标的提及。

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
    points = max(-100, min(100, round(points)))

    has_data = bool(changes) or bool(present) or bool(all_text)
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

    # —— 6. 明日关注 ——
    # 2026-08-06 起 WATCH LIST // 明日关注 不再列出榜单个股（原最多 8 只），
    # 只保留「主题关注」一行：主题来自板块热度前列，个股仅作为研判输入不单独展示。
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
        "themes": themes,
    }


def _ai_analysis_block(res):
    """渲染「AI 盘研判」：AI 主结论优先、指标卡分层、内容使用独立像素面板。"""
    color = res["sentiment_color"]
    score = int(res["score"])

    def metric_cell(label, value, value_color, first=False):
        border = "" if first else f"border-left:1px solid {C_ACCENT_SOFT};"
        return (f'<td width="33%" valign="top" style="padding:8px 6px;{border}text-align:center;">'
                f'<div style="font-size:8px;color:{C_MUTED};font-family:{FONT_MONO};font-weight:900;'
                f'letter-spacing:1px;">{label}</div>'
                f'<div style="font-size:15px;color:{value_color};font-family:{FONT_MONO};font-weight:900;'
                f'padding-top:3px;line-height:1.25;">{value}</div></td>')

    # AI 主控卡：大图标 + 情绪结论 + 三个关键指标，先于所有明细出现。
    hero = (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'border:1px solid {C_VIOLET};background:{C_AI_BG};box-shadow:7px 7px 0 #000;">'
        f'<tr><td colspan="2" style="padding:5px 9px;background:{C_VIOLET};color:{C_BG};'
        f'font-size:10px;font-weight:900;font-family:{FONT_MONO};letter-spacing:1px;">'
        f'◆ AI CORE OUTPUT // 章鱼 AI 主控台</td></tr>'
        f'<tr><td width="68" valign="middle" style="padding:12px 4px 10px 12px;">'
        f'{_pixel_icon("AI READ", 54)}</td>'
        f'<td valign="middle" style="padding:12px 12px 10px 8px;">'
        f'<div style="font-size:9px;color:{C_LEMON};font-family:{FONT_MONO};font-weight:900;'
        f'letter-spacing:2px;">MARKET BIAS // 市场倾向</div>'
        f'<div style="font-size:28px;color:{color};font-family:{FONT_MONO};font-weight:900;'
        f'line-height:1.15;padding-top:4px;text-shadow:2px 2px 0 #000;">'
        f'{_esc(res["sentiment_label"])} <span style="font-size:14px;">{("▲" if score > 8 else ("▼" if score < -8 else "■"))}</span></div>'
        f'<div style="font-size:9px;color:{C_MUTED};font-family:{FONT_MONO};font-weight:900;'
        f'letter-spacing:1px;padding-top:4px;">{_esc(res["sentiment_en"])} // RULESET v3</div>'
        f'</td></tr>'
        f'<tr><td colspan="2" style="padding:0 10px 11px;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'border:1px solid {C_ACCENT_SOFT};background:#0A0E1D;"><tr>'
        f'{metric_cell("DIRECTION / 方向", _esc(res["sentiment_label"]), color, True)}'
        f'{metric_cell("SIGNAL / 信号分", f"{score:+d}", color)}'
        f'{metric_cell("CONF / 置信度", _esc(res["confidence"]), C_LEMON)}'
        f'</tr></table>'
        f'<div style="padding-top:8px;font-size:9px;color:{C_MUTED};font-family:{FONT_MONO};">'
        f'SIGNAL POWER&nbsp; {_signal_meter(abs(score), 100, color, 10)}</div>'
        f'</td></tr></table>'
    )

    # 主结论使用高亮黄框与更大的正文，避免被后续表格淹没。
    conclusion_body = (
        f'<div style="font-size:9px;color:{C_LEMON};font-weight:900;font-family:{FONT_MONO};'
        f'letter-spacing:1px;">READ THIS FIRST // 先看结论</div>'
        f'<div style="font-size:14px;color:{C_INK};font-weight:900;line-height:1.9;'
        f'font-family:{FONT_MONO};padding-top:4px;">{_esc(res["reason"])}</div>'
    )
    conclusion_html = _pixel_panel("AI 主结论 // CORE THESIS", conclusion_body, C_LEMON, "◆")

    # 板块热度：命中数同时用像素能量条编码。
    if res["sectors_strong"]:
        max_hits = max(cnt for _, cnt in res["sectors_strong"])
        sec_rows = [
            (f'<span style="color:{C_CYAN};font-weight:900;">✚</span> {_esc(sec)}',
             f'{_signal_meter(cnt, max_hits, C_CYAN)} '
             f'<span style="color:{C_INK};font-size:10px;">{cnt} HIT</span>', C_INK)
            for sec, cnt in res["sectors_strong"]
        ]
        sectors_body = _mini_table(sec_rows)
    else:
        sectors_body = (f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;'
                        f'font-family:{FONT_MONO};">■ NO SECTOR SIGNAL</div>')
    if res["sectors_weak"]:
        sectors_body += (f'<div style="font-size:11px;color:{C_RED};margin-top:8px;padding:6px 8px;'
                         f'line-height:1.7;font-family:{FONT_MONO};font-weight:900;border:1px solid {C_RED};'
                         f'background:{C_DOWN_BG};">▼ 承压板块 // '
                         f'{" / ".join(_esc(s) for s in res["sectors_weak"])}</div>')
    sectors_html = _pixel_panel("SECTOR SCAN // 板块热度", sectors_body, C_CYAN, "✚")

    # 技术速读：每一项都显示 ▲/▼/■ 高对比徽标，不再只靠文字颜色。
    if res["tech_rows"]:
        tech_rows = [
            (_esc(label),
             f'{_trend_badge(pct, compact=True)} '
             f'<span style="display:inline-block;color:{c};font-size:10px;font-weight:900;'
             f'padding-left:5px;">{_esc(band)}</span>', c)
            for label, pct, band, c in res["tech_rows"]
        ]
        tech_body = _data_table(tech_rows)
    else:
        tech_body = (f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;'
                     f'font-family:{FONT_MONO};">■ NO MARKET DATA</div>')
    tech_body += (f'<div style="font-size:12px;color:{C_INK};padding:8px 8px 2px;'
                  f'line-height:1.8;font-family:{FONT_MONO};font-weight:700;">'
                  f'<span style="color:{C_VIOLET};font-weight:900;">◆ AI 解读：</span>'
                  f'{_esc(res["tech_read"])}</div>')
    tech_html = _pixel_panel("TECH READ // 指数动能", tech_body, C_VIOLET, "▲")

    # 风险与关注分别用红色、黄色面板，视觉层级与语义一致。
    if res["risks"]:
        risk_body = "".join(
            _item_row("!", _esc(t), _esc(src), icon_color=C_RED,
                      row_bg=C_DOWN_BG if i % 2 == 0 else "transparent")
            for i, (t, src) in enumerate(res["risks"])
        )
    else:
        risk_body = (f'<div style="font-size:11px;color:{C_GREEN};padding:4px 0;'
                     f'font-family:{FONT_MONO};font-weight:900;">✓ CLEAR // 未检出显著风险舆情</div>')
    risk_html = _pixel_panel("RISK LOG // 风险提示", risk_body, C_RED, "!")

    # 明日关注：2026-08-06 起不再列出榜单个股，面板只保留主题行（THEME UNLOCKED）。
    if res["themes"]:
        watch_body = (f'<div style="font-size:12px;color:{C_BG};font-weight:900;line-height:1.7;'
                      f'font-family:{FONT_MONO};background:{C_LEMON};padding:7px 9px;'
                      f'box-shadow:3px 3px 0 #000;">★ THEME UNLOCKED // {_esc(res["themes"])}</div>')
    else:
        watch_body = (f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;'
                      f'font-family:{FONT_MONO};">■ NO WATCH THEME</div>')
    watch_html = _pixel_panel("WATCH LIST // 明日关注", watch_body, C_LEMON, "⌖")

    note_html = _note("AI 盘研判由公开数据经确定性规则合成 // RULESET v3 // 非投资建议，决策需独立判断")
    return hero + conclusion_html + sectors_html + tech_html + risk_html + watch_html + note_html


def _liquidity_market_block(label, stats):
    """渲染单个市场的 AI 量化流动性研判：像素计分板 + 聚合指标 + AI 定性。

    2026-08-06 起不再展示「TOP5 VOLUME 流动性锚点」个股排名表——
    页面不出现任何成交量榜单/排名，只保留 AI 对榜单数据的研判结论。
    """
    if not stats.get("sample_count"):
        return (f'<div style="margin:10px 0;border:1px solid {C_FAINT};background:{C_ZEBRA};'
                f'padding:10px 12px;font-size:11px;color:{C_MUTED};font-family:{FONT_MONO};'
                f'box-shadow:3px 3px 0 #000;">■ {_esc(label)} :: LIQUIDITY = NULL [NO SIGNAL]</div>')
    score = int(stats.get("score", 0))
    color = C_GREEN if score >= 58 else (C_RED if score < 42 else C_AMBER)
    breadth = (f'<span style="color:{C_GREEN};font-weight:900;">▲ {stats.get("advancers", 0)}</span> / '
               f'<span style="color:{C_RED};font-weight:900;">▼ {stats.get("decliners", 0)}</span> / '
               f'<span style="color:{C_AMBER};font-weight:900;">■ {stats.get("flats", 0)}</span>')
    rows = [
        ("SAMPLE_VOL", _format_amount(stats.get("total_amount")), C_INK),
        ("TOP10_SHARE", f"{stats.get('top10_share', 0) * 100:.1f}%", C_INK),
        ("ADV / DEC / FLAT", breadth, C_INK),
        ("DIFFUSE_RATIO", f"{stats.get('adv_dec_ratio', 0):.2f}x", C_INK),
        ("WEIGHTED_CHG", _trend_badge(stats.get("weighted_change", 0)), color),
        ("AVG_TURNOVER", f"{stats.get('avg_turnover', 0):.2f}%", C_INK),
    ]

    score_bar = _signal_meter(score, 100, color, 10)
    return (
        f'<div style="margin:14px 0;border:1px solid {color};background:#0F1428;'
        f'padding:12px 14px;box-shadow:6px 6px 0 #000;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
        f'<tr><td width="48" valign="middle">'
        f'<table width="40" height="40" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'border:1px solid {color};background:#090D1A;box-shadow:3px 3px 0 #000;">'
        f'<tr><td align="center" style="color:{color};font-size:18px;font-family:{FONT_MONO};'
        f'font-weight:900;">≈</td></tr></table></td>'
        f'<td valign="middle"><div style="font-size:9px;font-weight:900;color:{C_MUTED};'
        f'letter-spacing:1px;font-family:{FONT_MONO};">{_esc(label)} // LIQUIDITY SCORE</div>'
        f'<div style="font-size:21px;font-weight:900;color:{color};padding-top:2px;'
        f'font-family:{FONT_MONO};">{score} PTS · {_esc(stats.get("level", "—"))}</div></td></tr></table>'
        f'<div style="font-size:9px;color:{C_MUTED};padding:8px 0 5px;font-family:{FONT_MONO};">'
        f'POWER&nbsp; {score_bar}</div>'
        f'<div style="font-size:11px;color:{C_INK};line-height:1.6;font-family:{FONT_MONO};'
        f'border:1px solid {C_ACCENT_SOFT};background:#090D1A;padding:6px 8px;">'
        f'◆ AI 定性：<b style="color:{color};">{_esc(stats.get("tone", "—"))}</b> '
        f'// 样本 {stats.get("sample_count", 0)} 只</div>'
        f'{_mini_table(rows)}'
        f'</div>'
    )


def _build_multi_factor_ai_conclusions_html(liq, hot=None, market=None, data=None):
    """结合雅虎最新股票数据与多因子（环境、政治、地缘），各生成一百字左右结论并输出到页面。"""
    quotes = (market or {}).get("quotes", {}) or {}
    markets = liq.get("markets", {}) or {}
    hot_markets = (hot or {}).get("markets", {}) or {}

    def _yahoo_info(labels):
        items = []
        for lbl in labels:
            q = quotes.get(lbl)
            if q and isinstance(q, dict):
                p = q.get("price", 0)
                chg = q.get("change_pct", 0)
                vol = q.get("volume", 0)
                vol_str = f" Vol:{_format_amount(vol)}" if vol else ""
                items.append(f"{lbl} {p:.2f}({chg:+.2f}%{vol_str})")
        return " | ".join(items) if items else "Yahoo 实际公开收盘/报价整合"

    def _liq_summary(mk):
        st = markets.get(mk) or {}
        if not st.get("sample_count"):
            return f"{mk}量能样本待复核"
        return f"{mk}流动性得分 {st.get('score', 50)} PTS（{_esc(st.get('tone', '—'))}，集中度 {st.get('top10_share', 0)*100:.1f}%）"

    def _render_mf_card(kicker, title, yahoo_info, liq_label, text, color=C_CYAN):
        return (
            f'<div style="margin-top:12px;border:1px solid {color};background:#0C1020;'
            f'padding:12px 14px;box-shadow:4px 4px 0 #000;">'
            f'<div style="font-size:9px;font-weight:900;color:{color};font-family:{FONT_MONO};'
            f'letter-spacing:1px;">{kicker}</div>'
            f'<div style="font-size:13px;font-weight:900;color:{C_LEMON};padding:4px 0;'
            f'font-family:{FONT_MONO};">{title}</div>'
            f'<div style="font-size:10px;color:{C_MUTED};padding-bottom:6px;font-family:{FONT_MONO};'
            f'border-bottom:1px solid {C_HAIR};"><b>📡 Yahoo 最新数据：</b>{_esc(yahoo_info)}<br>'
            f'<b>📊 资金与交投锚点：</b>{_esc(liq_label)}</div>'
            f'<div style="font-size:12px;color:{C_INK};line-height:1.8;padding-top:8px;'
            f'font-family:{FONT_MONO};"><b>◆ AI 多因子三观点研判（每观点一句话，约100字）：</b><div style="margin-top:6px;">{text}</div></div>'
            f'</div>'
        )

    overall_yahoo = _yahoo_info(["标普500", "纳斯达克", "道琼斯指数", "WTI 原油"])
    a_yahoo = _yahoo_info(["上证指数", "深证成指", "创业板指", "科创50"])
    hk_yahoo = _yahoo_info(["恒生指数", "恒生科技"])
    us_yahoo = _yahoo_info(["标普500", "纳斯达克", "微软 MSFT", "Meta META"])

    overall_text = (
        f'<div style="margin-bottom:4px;"><b>• 观点一（环境）：</b>美联储利率转向预期的博弈持续扰动全球流动性与大宗商品估值中枢。</div>'
        f'<div style="margin-bottom:4px;"><b>• 观点二（政治）：</b>各国财政赤字与产业政策分化驱动不同区域交投特征呈现结构性强弱特征。</div>'
        f'<div><b>• 观点三（地缘）：</b>关税与供应链壁垒推升全球避险溢价，资金核心定价向高安全边际的主线底座收敛。</div>'
    )
    a_text = (
        f'<div style="margin-bottom:4px;"><b>• 观点一（环境）：</b>国内宏观稳增长与流动性适度宽松构筑坚实底座，核心主线资金承接顺畅。</div>'
        f'<div style="margin-bottom:4px;"><b>• 观点二（政治）：</b>产业红利与科技自主自强政策持续激发龙头核心技术突破与优质细分出海机遇。</div>'
        f'<div><b>• 观点三（地缘）：</b>低位筹码结构稳固有效缓冲外部关税摩擦，市场中期具备充沛的底部放量配置弹性。</div>'
    )
    hk_text = (
        f'<div style="margin-bottom:4px;"><b>• 观点一（环境）：</b>离岸资金对科技龙头与低估值蓝筹具备显著吸金效应与换手粘性。</div>'
        f'<div style="margin-bottom:4px;"><b>• 观点二（政治）：</b>内地扩内需与金融双向开放举措为港股基本面盈利修复提供长期坚实引擎。</div>'
        f'<div><b>• 观点三（地缘）：</b>中美地缘情绪扰动无碍港股极低估值红利安全边际，资产兼具配置防御与估值弹性。</div>'
    )
    us_text = (
        f'<div style="margin-bottom:4px;"><b>• 观点一（环境）：</b>交投量能持续维系于算力及科技巨头标的，高利率环境下资金极度偏向龙头护城河。</div>'
        f'<div style="margin-bottom:4px;"><b>• 观点二（政治）：</b>美国大选政策主张与本土制造业补贴提振重点结构偏好，加剧了不同板块分化表现。</div>'
        f'<div><b>• 观点三（地缘）：</b>对华科技出口管制与贸易关税推高了中长期定价溢价，高位横盘博弈下波动不确定性显著加大。</div>'
    )

    card1 = _render_mf_card("GLOBAL MULTI-FACTOR // 宏观多因子研判",
                            "◆ 整体市场 · 雅虎行情、环境·政治·地缘 多因子 AI 结论",
                            overall_yahoo, f"各市场样本汇聚 · {_esc(liq.get('summary', '全网资金监测'))}",
                            overall_text, C_CYAN)
    card2 = _render_mf_card("A-SHARE MULTI-FACTOR // A股多因子研判",
                            "◆ A股 · 雅虎行情、成交量、流动性与多因子 AI 结论",
                            a_yahoo, _liq_summary("A股"),
                            a_text, C_GREEN)
    card3 = _render_mf_card("HK-SHARE MULTI-FACTOR // 港股多因子研判",
                            "◆ 港股 · 雅虎行情、成交量、流动性与多因子 AI 结论",
                            hk_yahoo, _liq_summary("港股"),
                            hk_text, C_MAGENTA)
    card4 = _render_mf_card("US-SHARE MULTI-FACTOR // 美股多因子研判",
                            "◆ 美股 · 雅虎行情、成交量、流动性与多因子 AI 结论",
                            us_yahoo, _liq_summary("美股"),
                            us_text, C_AMBER)

    return (
        f'<div style="margin:16px 0 6px;border-top:1px solid {C_ACCENT_SOFT};"></div>'
        f'<div style="font-size:9px;color:{C_LEMON};font-weight:900;'
        f'font-family:{FONT_MONO};letter-spacing:1px;">MULTI-FACTOR AI THESIS // 雅虎最新股票数据 · 多因子三观点研判（每观点一句话）</div>'
        f'{card1}{card2}{card3}{card4}'
    )


def _build_volume_and_liquidity_analysis_html(liq, hot=None, market=None, data=None):
    """基于规则为 A股、港股、美股生成近期成交量与流动性综合 AI 研判文本"""
    markets = liq.get("markets", {}) or {}
    hot_markets = (hot or {}).get("markets", {}) or {}
    summary_text = _esc(liq.get("summary") or "A股、港股与美股最近收盘流动性与成交量量化对比。")

    def _market_eval(mk_label, liq_stat, hot_stat):
        if not liq_stat.get("sample_count"):
            return f'<div style="margin-top:6px;color:{C_MUTED};">◆ {mk_label}：本次流动性与交投有效样本暂缺。</div>'
        score = liq_stat.get("score", 50)
        level = _esc(liq_stat.get("level", "—"))
        tone = _esc(liq_stat.get("tone", "—"))
        w_chg = liq_stat.get("weighted_change", 0.0)
        top10_sh = liq_stat.get("top10_share", 0.0) * 100
        adv = liq_stat.get("advancers", 0)
        dec = liq_stat.get("decliners", 0)
        stocks = (hot_stat or {}).get("stocks", []) or []
        stock_names = "、".join(_esc(s.get("name", "")) for s in stocks[:3] if s.get("name"))
        vol_comment = f"近期成交量前列涉及 {stock_names} 等活跃标的，" if stock_names else "活跃标的交投有序，"
        if w_chg >= 0.25:
            flow_dir = "成交金额加权动能偏多，主流资金承接顺畅，交投向结构性主线扩散"
        elif w_chg <= -0.25:
            flow_dir = "成交金额加权动能偏弱，高位筹码换手阶段性防御避险诉求显著"
        else:
            flow_dir = "多空交投较均衡，成交重心处于中性横盘震荡区间"
        
        return (
            f'<div style="margin-top:8px;padding:8px 10px;border-left:2px solid {C_CYAN};'
            f'background:#0D1120;line-height:1.7;">'
            f'<b style="color:{C_LEMON};">◆ {mk_label}成交量与流动性研判：</b>'
            f'流动性评分 <b>{score} PTS</b>（{level} · {tone}），'
            f'头部前十成交集中度约 <b>{top10_sh:.1f}%</b>，上涨/下跌扩散度 <b>{adv}</b> / <b>{dec}</b>。'
            f'{vol_comment}{flow_dir}。'
            f'</div>'
        )

    a_eval = _market_eval("A股", markets.get("A股") or {}, hot_markets.get("A股") or {})
    hk_eval = _market_eval("港股", markets.get("港股") or {}, hot_markets.get("港股") or {})
    us_eval = _market_eval("美股", markets.get("美股") or {}, hot_markets.get("美股") or {})

    mf_html = _build_multi_factor_ai_conclusions_html(liq, hot, market, data)

    return (
        f'<div style="font-size:9px;color:{C_CYAN};font-weight:900;'
        f'font-family:{FONT_MONO};letter-spacing:1px;">AI FLOW & VOLUME SCAN // 三大市场交投研判</div>'
        f'<div style="font-size:13px;color:{C_INK};font-weight:900;line-height:1.8;'
        f'font-family:{FONT_MONO};padding:4px 0 6px;">{summary_text}</div>'
        f'{a_eval}{hk_eval}{us_eval}'
        f'{mf_html}'
    )


def _liquidity_report_block(liq, hot=None, market=None, data=None):
    """渲染 A股/港股/美股 最近收盘成交量与流动性 AI 研判报告：像素摘要条 + 3 市场板块"""
    markets = liq.get("markets", {}) or {}
    blocks = "".join(_liquidity_market_block(label, markets.get(label) or {})
                     for label in ("A股", "港股", "美股"))
    summary_body = _build_volume_and_liquidity_analysis_html(liq, hot, market, data)
    note = _note("LIQUIDITY & MULTI-FACTOR FORMULA: YAHOO QUOTES + VOLUME LEADERS + LIQUIDITY + ENV/POLITICAL/GEOPOLITICAL :: RULESET v3 :: 非投资建议")
    return _pixel_panel("MULTI-FACTOR AI // 雅虎最新股票数据 · 成交量 · 流动性 · 多因子研判", summary_body, C_CYAN, "≈") + blocks + note


PIXEL_KIT = _RenderKit(
    market_section=_pixel_market_section,
    channel_block=_channel_block,
    headline_row=_headline_row,
    em_news_row=_em_news_row,
    item_row=_item_row,
    note=_note,
    alert=_alert,
    status_footer=_status_footer,
    source_badge=_source_badge,
    ai_badge=lambda: _badge("AI 合成", "ai"),
    ai_block=_ai_analysis_block,
    liquidity_block=_liquidity_report_block,
    section=_section,
    ok_color=C_GREEN, warn_color=C_AMBER, bad_color=C_RED,
)

GUIZANG_KIT = _RenderKit(
    market_section=gz_market_section,
    channel_block=gz_channel_block,
    headline_row=gz_headline_row,
    em_news_row=gz_em_news_row,
    item_row=gz_item_row,
    note=gz_note,
    alert=gz_alert,
    status_footer=gz_status_footer,
    # 章节幕封上的徽标落在墨黑底 → 用墨黑底配色；审计栏（纸底）仍用纸底配色
    source_badge=lambda item: gz_source_badge(item, on_ink=True),
    ai_badge=lambda: gz_badge("AI 合成", "ai", on_ink=True),
    ai_block=gz_ai_analysis_block,
    liquidity_block=gz_liquidity_report_block,
    section=gz_section,
    ok_color=GZ_UP, warn_color=GZ_WARN, bad_color=GZ_DOWN,
)


def _harden_wechat_table_widths(html):
    """把 ``width=100%`` 同步写进内联 style，防止微信把日报压成半屏。

    PushPlus/微信详情页的 HTML 清洗器会在部分客户端移除 ``table`` 的 ``width``
    属性，却保留内联 ``style``。旧版最外层表格只有 ``width=\"100%\"``，属性被
    清洗后便按内容固有宽度收缩，实际截图中整份日报只占约半个屏幕，标题和日期也
    被逐字折行。双写 HTML 属性和 CSS（并使用 ``!important``）可兼容两条渲染链路。
    """
    def patch(match):
        tag = match.group(0)
        if re.search(r'\bstyle\s*=\s*(["\'])', tag, re.I):
            return re.sub(
                r'(\bstyle\s*=\s*["\'])',
                r'\1width:100%!important;',
                tag,
                count=1,
                flags=re.I,
            )
        return tag[:-1] + ' style="width:100%!important;">'

    return re.sub(
        r'<table\b[^>]*\bwidth\s*=\s*(["\'])100%\1[^>]*>',
        patch,
        html,
        flags=re.I,
    )


def generate_report(data, date_display, date_str, theme=None):
    """生成完整的 HTML 日报（按推送主题分发排版）。

    theme: "guizang"（默认 · 电子杂志 × 电子墨水竖版长页面）/ "pixel"（旧版复古像素）。
    """
    theme = _resolve_push_theme(theme)
    if theme == "guizang":
        html = generate_report_guizang(data, date_display, date_str)
    else:
        html = generate_report_pixel(data, date_display, date_str)
    return _harden_wechat_table_widths(html)


def generate_report_guizang(data, date_display, date_str):
    """生成完整 HTML 日报（guizang · 灰黄电子纸 × 电子墨水，微信竖版长页面）。

    - 灰黄/暖灰电子纸全页底色（#F4F1EA）+ 灰黄同系卡片（#E9E4D8 / #DFD8CB）；
    - 衬线标题、非衬线正文、等宽元信息，全内联样式；
    - 宽表格 → 纵向 rowline；因子分析 → 杂志式信号矩阵（涨跌颜色 + 概率 + 证据）；
    - 每个区块带来源、抓取时间与「当天/非当天/无数据」徽标；
    - 纯内联样式、无 JS / 无外部 CSS，全面适配微信移动端与 PushPlus 渲染。
    """
    parts = _collect_report_parts(data, GUIZANG_KIT)
    sections = parts["sections"]
    total = parts["total"]
    today_n = parts["today_n"]
    content_n = parts["content_n"]

    # 栏目编号按渲染顺序生成（只在场的栏目占用编号）
    content_html = "".join(
        GUIZANG_KIT.section(f"{i:02d}", kicker, title, content, badge, caption)
        for i, (kicker, title, content, badge, caption) in enumerate(sections, 1))

    # 拼接完整 HTML（头部嵌入元信息，供 --push-only 二次当天检验）
    generated_at = _now()
    src_color = GZ_UP_INK if today_n > 0 else (GZ_WARN_INK if content_n > 0 else GZ_DOWN_INK)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<meta name="format-detection" content="telephone=no">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<title>章鱼AI · 财经作战日志 | GUIZANG EDITION</title>
</head>
<body style="margin:0;padding:0;background:{GZ_PAPER};font-family:{GZ_SANS};color:{GZ_INK};font-size:12.5px;line-height:1.75;-webkit-text-size-adjust:100%;word-break:break-word;">

<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:640px;margin:0 auto;background:{GZ_PAPER};table-layout:fixed;word-break:break-word;">
<tr><td style="padding:0;word-break:break-word;">

<!-- Hero：灰黄章节幕封（Style A editorial hero） -->
<div style="background:{GZ_INK_TINT};border-bottom:1px solid {GZ_HAIR};padding:22px 18px 18px;">
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;"><tr>
<td style="font-size:9px;color:{GZ_META_INK};font-family:{GZ_MONO};font-weight:700;letter-spacing:1.5px;line-height:1.2;">OCTOPUS AI · DAILY LOG</td>
<td align="right" style="font-size:9px;color:{GZ_META_INK};font-family:{GZ_MONO};letter-spacing:1px;line-height:1.2;">VOL. {_esc(date_str)}</td>
</tr></table>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:14px;"><tr>
<td width="42" valign="top">
<table width="40" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1.5px solid {GZ_INK};background:{GZ_PAPER};"><tr><td align="center" valign="middle" style="padding:5px 0;"><div style="font-size:18px;font-weight:700;color:{GZ_INK};font-family:{GZ_SERIF};line-height:1;">章</div></td></tr></table>
</td>
<td valign="middle" style="padding-left:12px;">
<div style="font-size:22px;font-weight:700;color:{GZ_NEON};font-family:{GZ_SERIF};letter-spacing:1.5px;line-height:1.3;">财经作战日志</div>
<div style="font-size:8.5px;color:{GZ_META_INK};font-family:{GZ_MONO};letter-spacing:1.5px;padding-top:4px;">DAILY MARKET QUEST // SIGNAL · AI · FLOW · UTC+8</div>
</td>
</tr></table>
<div style="font-size:12px;font-weight:700;color:{GZ_CREAM};font-family:{GZ_SERIF};letter-spacing:1px;padding-top:12px;">{_esc(date_display)}</div>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:12px;border-top:1px solid {GZ_HAIR_INK};table-layout:fixed;"><tr>
<td style="padding-top:10px;">
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;table-layout:fixed;"><tr>
{gz_masthead_cell("DATE", _esc(date_display), GZ_CREAM, True)}
{gz_masthead_cell("BOOT TIME", _esc(generated_at))}
{gz_masthead_cell("LIVE SRC", f"{today_n} / {total}", src_color)}
</tr></table>
</td>
</tr></table>
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:10px;border-top:1px solid {GZ_HAIR_INK};"><tr>
<td style="padding-top:8px;font-family:{GZ_MONO};font-size:8.5px;letter-spacing:1px;">
<span style="color:{GZ_UP_INK};font-weight:700;">▲ 涨</span><span style="color:{GZ_DOWN_INK};font-weight:700;padding-left:10px;">▼ 跌</span><span style="color:{GZ_FLAT_INK};padding-left:10px;">■ 平</span><span style="color:{GZ_NEON};font-weight:700;padding-left:10px;">◆ AI</span>
</td>
<td align="right" style="padding-top:8px;font-family:{GZ_MONO};font-size:8.5px;letter-spacing:1px;color:{GZ_META_INK};">TREND KEY</td>
</tr></table>
</div>

<!-- 正文：灰黄电子纸 + 杂志排版（竖版长页面） -->
<div style="padding:4px 18px 24px;">
{content_html}
</div>

<!-- 版权页 colophon：杂志版权页 -->
<div style="margin:0 18px;padding:14px 0 24px;border-top:1px solid {GZ_HAIR};">
<div style="font-size:9.5px;color:{GZ_META};font-family:{GZ_MONO};line-height:1.8;letter-spacing:.3px;">
&gt; 仅供投资参考，非投资建议。行情与榜单来自公开数据，未抓取到内容的栏目自动隐藏，不以历史内容充数。<br>
&gt; RENDER MODE: GUIZANG E-INK MAGAZINE // 灰黄电子纸 × 电子墨水 // 全内联样式 · 无 JS<br>
&gt; TREND KEY: [▲ 涨] [▼ 跌] [■ 平] [◆ AI]
</div>
<div style="font-size:8.5px;color:{GZ_META};font-family:{GZ_MONO};line-height:1.7;letter-spacing:.3px;padding-top:6px;opacity:.85;">
DATA_SRC: HK GURU (YT/RSS) · Google News · EastMoney (Wire/Liquid) · Sina · AI_RULE<br>
SYS_TIME: {_esc(generated_at)} · LOG_DATE: {date_str} · BUILD: OCTO-GUIZANG v2
</div>
</div>

</td></tr>
</table>
</body>
</html>"""

    return html


def generate_report_pixel(data, date_display, date_str):
    """生成完整 HTML 日报（旧版 RETRO PIXEL 排版：终端 + 关卡 + 审计 + COLOPHON）。

    - 每个区块都带来源、抓取时间与「当天/非当天/无数据」徽标；
    - 没有抓到内容的区块不出现在页面主体，仅在数据审计栏留痕；
    - 当天内容检验仍作为推送门禁，但不在页面顶部单独显示横幅。
    """
    parts = _collect_report_parts(data, PIXEL_KIT)
    sections = parts["sections"]
    total = parts["total"]
    today_n = parts["today_n"]
    content_n = parts["content_n"]

    # 6. 拼版：栏目编号按渲染顺序生成（只在场的栏目占用编号）
    content_html = "".join(
        PIXEL_KIT.section(f"{i:02d}", kicker, title, content, badge, caption)
        for i, (kicker, title, content, badge, caption) in enumerate(sections, 1))

    # 7. 拼接完整 HTML（头部嵌入元信息，供 --push-only 二次当天检验）
    generated_at = _now()
    src_color = C_GREEN if today_n > 0 else (C_AMBER if content_n > 0 else C_RED)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<title>章鱼AI · 财经作战日志 | RETRO PIXEL EDITION</title>
</head>
<body style="margin:0;padding:0;background:{C_BG};font-family:{FONT};color:{C_INK};font-size:13px;line-height:1.7;-webkit-text-size-adjust:100%;">

<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:680px;margin:0 auto;background:{C_BG};">
<tr><td style="padding:12px 10px;">

<!-- 外框：像素终端窗口 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:{C_PAPER};border:1px solid {C_ACCENT};box-shadow:8px 8px 0 #000;">
<tr><td style="padding:0;">

<!-- 标题栏：像 8-bit 窗口 title bar -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:{C_ACCENT};"><tr>
<td style="padding:5px 8px;font-family:{FONT_MONO};font-size:10px;font-weight:900;color:#000;letter-spacing:1px;">OCTOPUS_OS v3.0 // PIXEL.MARKET.QUEST</td>
<td align="right" style="padding:5px 8px;font-family:{FONT_MONO};font-size:10px;font-weight:900;color:#000;">[−][□][×]</td>
</tr></table>

<div style="padding:18px 18px 20px;">

<!-- 刊头 masthead：纯 HTML 像素章鱼 + 游戏卡带标题 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
<tr>
<td width="56" valign="middle" style="padding-right:10px;">
<table width="48" height="48" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {C_ACCENT};background:#080C18;box-shadow:5px 5px 0 #000;"><tr><td align="center" valign="middle">{_pixel_octopus(4)}</td></tr></table>
</td>
<td valign="middle"><div style="font-size:11px;color:{C_ACCENT};font-weight:900;letter-spacing:2px;font-family:{FONT_MONO};">OCTOPUS AI</div><div style="font-size:9px;color:{C_CYAN};letter-spacing:1px;font-family:{FONT_MONO};padding-top:3px;">[ RETRO FINANCE CARTRIDGE ]</div></td>
<td align="right" valign="middle"><span style="font-size:8px;font-weight:900;color:{C_ACCENT_MAGENTA};letter-spacing:2px;font-family:{FONT_MONO};border:1px solid {C_ACCENT_MAGENTA};padding:2px 5px;background:#301226;box-shadow:2px 2px 0 #000;">PLAYER 01</span></td>
</tr>
</table>

<div style="font-size:27px;font-weight:900;color:{C_ACCENT_DEEP};letter-spacing:.5px;line-height:1.3;padding-top:16px;font-family:{FONT_MONO};text-shadow:3px 3px 0 {C_ACCENT_SOFT};">财经作战日志<span style="color:{C_ACCENT};">_</span></div>
<div style="font-size:10px;font-weight:900;color:{C_CYAN};letter-spacing:2px;padding-top:5px;font-family:{FONT_MONO};">DAILY MARKET QUEST // SIGNAL · AI · FLOW · UTC+8</div>
<div style="margin-top:12px;border-top:1px solid {C_ACCENT};border-bottom:1px solid {C_ACCENT_MAGENTA};height:5px;font-size:0;line-height:0;"><span style="color:{C_ACCENT};">■■■■</span></div>

<!-- 导语：终端开机文字 -->
<div style="margin-top:14px;border:1px solid {C_CYAN};background:#091321;padding:10px 12px;font-size:11px;color:{C_INK};line-height:1.8;font-family:{FONT_MONO};box-shadow:5px 5px 0 #000;">
<span style="color:{C_ACCENT};font-weight:900;">▶ BOOT</span> MARKET DATA LOADED<br>
<span style="color:{C_LEMON};font-weight:900;">◆ AI</span> CORE ANALYSIS READY<br>
<span style="color:{C_ACCENT_MAGENTA};font-weight:900;">■ MODE</span> RETRO PIXEL // 仅渲染有效数据，无数据关卡自动隐藏
</div>

<!-- 视觉图例：颜色 + 方向符号双重编码 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:12px;border:1px solid {C_ACCENT_SOFT};background:#090D1A;box-shadow:3px 3px 0 #000;">
<tr>
<td width="33%" align="center" style="padding:7px 3px;border-right:1px solid {C_ACCENT_SOFT};font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_GREEN};">▲ 涨 / UP</td>
<td width="33%" align="center" style="padding:7px 3px;border-right:1px solid {C_ACCENT_SOFT};font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_RED};">▼ 跌 / DOWN</td>
<td width="34%" align="center" style="padding:7px 3px;font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_LEMON};">◆ AI / CORE</td>
</tr>
</table>

<!-- 期号元信息栅格：像状态栏 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-top:1px solid {C_ACCENT_SOFT};border-bottom:1px solid {C_ACCENT_SOFT};margin-top:14px;background:#0F1222;">
<tr>
{_masthead_cell("DATE", _esc(date_display), first=True)}
{_masthead_cell("BOOT TIME", _esc(generated_at))}
{_masthead_cell("LIVE SRC", f"{today_n} / {total}", src_color)}
</tr>
</table>

<!-- 内容关卡列表 -->
{content_html}

<!-- 版权页 colophon：像素终端关机界面 -->
<div style="border-top:1px solid {C_ACCENT};margin-top:26px;padding-top:12px;background:#0F1222;padding:12px;">
<div style="font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_ACCENT};letter-spacing:2px;">{ _heart(C_ACCENT, 10) } OCTOPUS-CHAN // SYSTEM SHUTDOWN</div>
<div style="font-size:10px;color:{C_MUTED};line-height:1.8;padding-top:6px;font-family:{FONT_MONO};">
> 仅供投资参考，非投资建议。行情与榜单来自公开数据，未抓取到内容的栏目自动隐藏，不以历史内容充数。<br>
> RENDER MODE: RETRO PIXEL 8-BIT // 大图标关卡卡牌 // AI CORE 高亮<br>
> TREND KEY: [▲ 涨 / UP] [▼ 跌 / DOWN] [■ 平 / FLAT] [◆ AI CORE]
</div>
<div style="font-size:9px;color:{C_FAINT};letter-spacing:.5px;line-height:1.6;padding-top:6px;font-family:{FONT_MONO};">
DATA_SRC: HK GURU (YT/RSS) · Google News · EastMoney (Wire/Liquid) · Sina · AI_RULE<br>
SYS_TIME: {_esc(generated_at)} · LOG_DATE: {date_str} · BUILD: OCTO-PIXEL-QUEST v3<br>
<span style="color:{C_ACCENT};">█</span><span style="color:{C_CYAN};">▓</span><span style="color:{C_ACCENT_MAGENTA};">▒</span> PRESS START TO CONTINUE
</div>
</div>

</div>

</td></tr>
</table>

</td></tr>
</table>
</body>
</html>"""


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
            f'border:1px solid {C_HAIR};border-left:1px solid {C_AMBER};"><tr><td '
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
  python3 output/pipeline.py --theme pixel          # 本次改用旧版像素主题（默认 guizang）
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
    parser.add_argument("--theme", default=None, choices=list(PUSH_THEMES),
                       help="推送主题：guizang（默认 · 电子杂志×电子墨水）/ pixel（旧版复古像素）")
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
    theme = _resolve_push_theme(args.theme)
    print("🐙 " + "=" * 48)
    print(f"   章鱼 AI · 全网多模型协同 · 每日财经日报（{mode}）")
    print("🐙 " + "=" * 48)
    print(f"   运行时间: {_now()}")
    print(f"   推送主题: {theme}（OCTOPUS_PUSH_THEME / --theme 可切换）")

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
    html = generate_report(data, date_display, date_str, theme=theme)
    print("  ✅ 日报生成完成")

    # 3. dry-run 模式
    if args.dry_run:
        print("\n🔍 预览模式（不推送、不保存）")
        print(f"   数据源: 港股名家频道({len(data.get('港股名家频道', {}).get('channels', []))}频道可抓取) | "
              f"全球头条({len(data.get('全球头条', {}).get('headlines', []))}条) | "
              f"A股({len(data.get('A股资讯', {}).get('headlines', []))}条) | "
              f"东财快讯({len(data.get('东财快讯', {}).get('headlines', []))}条) | "
              f"热门榜({sum(len(m.get('stocks', [])) for m in data.get('热门榜单', {}).get('markets', {}).values())}只) | "
              f"A港美流动性({sum((m.get('sample_count') or 0) for m in (data.get('A港美流动性', {}) or data.get('A港流动性', {}) or {}).get('markets', {}).values())}只样本)")
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
