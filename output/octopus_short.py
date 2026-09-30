#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 短线速查卡 —— 日报最前面那张「30 秒读完就能动手」的卡（2026-09-30 新增）。

用户要求：内容再精炼，适合短线操作，入门观看。本模块只回答短线客开场三问——
**今天什么风、明天怎么做、哪些日子别碰**——外加一张固定的【新手三句话】小抄。

设计原则（与整仓「防自欺」文化一致，写进 tests/test_short_card.py 兜底）：
  1. **纯规则合成、可复现**：不调大模型、不掷骰子；同一份输入永远得到同一张卡。
  2. **零新增计算**：卡上每个数字都直接取自本次渲染正文用的同一批实参
     （weekly 逐日表 T+1 行 / entry 整段结论 / quant headline+liquidity /
     ai_result quant_sectors / pan 板块热力 / cal items / senti market_summary），
     不另算一套、不把数字四舍五入成新口径、不给方向「加戏」。
     南向的「温和缩量 / 显著放量」标签直接调用量化包同一个 `liquidity.flow_label`，
     阈值只有一处定义。
  3. **数据不足自动缺席**：哪一路没数据，对应那一行就不出现；全都没数据 → 整卡缺席，
     绝不用旧数据或写死文案充数。
  4. **字数硬预算**：正文可见文字 ≤ CARD_CHAR_BUDGET（默认 600 字，含【新手三句话】）。
     超预算时按 DROP_ORDER 从「最不影响动手」的行开始**整行**撤下，绝不截断半句话，
     撤了哪几行如实记在 card["dropped"] 里（测试与日志都能查）。
     地板：定调 + 明日剧本 + 数据底 + 新手小抄永不撤（撤完可撤行仍超预算时如实超长，
     也不砍「明天怎么做」）。
  5. **不给投资建议**：仓位 / 止损 / 止盈都是引擎既有输出，卡上原样搬运；
     末尾固定「规则合成 · 非投资建议」。
  6. 环境变量 OCTOPUS_LITE=0（或命令行 --full）整体关闭，日报回到全量长版。

ctx 约定（键全部可选，缺了就降级）：
  date_str   报告日 YYYYMMDD
  today      报告日 date 对象（「今明必看」的日基准；缺了该行直接缺席，绝不猜今明）
  weekly     每周走势预测 result（daily.rows / entry）
  quant      港股量化 result（headline / liquidity / target_label）
  ai         策略研判结果（quant_sectors / sentiment_label / score）
  pan        A股大盘全景 source_result（sectors 领涨领跌，作 ai 的兜底）
  cal        财经日历 source_result（items）
  senti      新闻情绪结果（market_summary）
  coverage   {"today": n, "total": m}
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

try:                                    # 南向标签复用量化包同一套阈值（不另写一份）
    from octopus_quant import liquidity as _liquidity
except Exception:                       # pragma: no cover - 包缺失时只丢标签，不丢数字
    _liquidity = None

# OCTOPUS_LITE=0 / false / no → 关闭速查卡（同时关闭全篇瘦身，回到全量长版）。
ENABLED = str(os.environ.get("OCTOPUS_LITE", "1")).strip().lower() not in ("0", "false", "no")

# 速查卡正文可见文字的字数预算（不含 HTML 标签）。超出按 DROP_ORDER 整行撤下。
CARD_CHAR_BUDGET = max(200, int(os.environ.get("OCTOPUS_CARD_CHARS", "600") or 600))

# 卡片副标（口径披露，诚实标注：规则合成 + 非投资建议）。
CAPTION = "30 秒读完 · 数字与下文各栏同源 · 非投资建议"
DISCLAIMER = "规则合成 · 非投资建议"

# 【新手三句话】：固定小抄，**不随数据变化**（用户要的「入门观看」兜底）。
# 三行分别回答：怎么看方向 / 止损放哪 / 什么时候别动手。
BEGINNER_TIPS = (
    ("① 看方向", "概率 ≥60% 才算有方向，50% 上下就是抛硬币——没有方向的时候，不亏就是赚。"),
    ("② 放止损", "按卡上「止损」价位挂单；没有价位就用单笔最多亏 3% 当红线，先想输多少再想赚多少。"),
    ("③ 别动手", "数据缺、当天有 ★★★ 大数据、概率五五开——三种情况都先观望，市场天天开门。"),
)
TIPS_TITLE = "🐣 新手三句话（固定小抄，不随数据变）"

# 超预算时的撤行顺序：**先撤锦上添花，最后才动「明天怎么做」**；
# setup（明日剧本）与 coverage（数据底）永不撤。
DROP_ORDER = ("news", "money", "sector", "mustsee", "week")

# 行顺序（小的排前面）：明日剧本 → 七日风 → 今明必看 → 板块强弱 → 水位 → 风声 → 数据底。
LINE_ORDER = {"setup": 0, "week": 1, "mustsee": 2, "sector": 3,
              "money": 4, "news": 5, "coverage": 6}

# 短线客真正要盯的重要度门槛：★★ 以上（★ 级多为周报 / 讲话，噪音大）。
MUSTSEE_MIN_IMP = 2
MUSTSEE_MAX = 4
MUSTSEE_MAX_CHARS = 88      # 这一行的字数上限：装不下就少列几条并如实写「等 N 项」
MUSTSEE_NAME_CHARS = 16     # 单条时点名称截断字数（完整名称仍在「时间节点」栏目里）
MUSTSEE_DAYS = 2            # 只看今天 + 明天
SECTOR_MAX = 3
SECTOR_NAME_CHARS = 8       # 板块名截断字数（完整榜单仍在「策略研判」栏目里）


# ------------------------------------------------------------------
# 数字格式化：None → 缺席（绝不补 0），口径与正文渲染层一致
# ------------------------------------------------------------------
def _p0(value):
    """0.52 → '52%'；非法值返回 None。"""
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return None


def _n0(value):
    """24589.4 → '24,589'；非法值返回 None。"""
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return None


def _signed(value, digits=2):
    """1.234 → '+1.23'；非法值返回 None。"""
    try:
        return f"{float(value):+.{digits}f}"
    except (TypeError, ValueError):
        return None


def _yi(value):
    """亿元（与资金流动性栏同一口径：整数亿）。"""
    try:
        return f"{float(value):,.0f} 亿"
    except (TypeError, ValueError):
        return None


def _day_md(date_str):
    """'2026-10-01' → '10-01'；已短或空值原样返回。"""
    text = str(date_str or "")
    return text[5:10] if len(text) >= 10 else text


def _dns_arrow(dns):
    """新闻情绪 DNS → ▲/▼/■（阈值与正文「市场情绪全景」一致：±0.2）。"""
    try:
        value = float(dns)
    except (TypeError, ValueError):
        return "■"
    return "▲" if value > 0.2 else ("▼" if value < -0.2 else "■")


def _strip_tags(text):
    return re.sub(r"<[^>]+>", "", str(text or ""))


def _pack(labels, budget, sep="、"):
    """按字数预算装条数：装不下的不硬塞，末尾如实写「等 N 项」（绝不静默丢内容）。"""
    labels = [str(x) for x in labels if str(x).strip()]
    if not labels:
        return ""
    kept = []
    used = 0
    for text in labels:
        extra = len(text) + (len(sep) if kept else 0)
        if kept and used + extra > budget:
            break
        kept.append(text)
        used += extra
    out = sep.join(kept)
    if len(labels) > len(kept):
        out += f" 等 {len(labels)} 项"
    return out


# ------------------------------------------------------------------
# 各行取材（每行一个函数：数据不在就返回 None，绝不留占位符）
# ------------------------------------------------------------------
def _line_setup(ctx):
    """① 明日剧本：T+1 的概率 / 预期区间 / 建议仓位 / 止损 / 止盈（逐日表第一行原样搬运）。"""
    weekly = ctx.get("weekly") or {}
    rows = ((weekly.get("daily") or {}).get("rows")) or []
    row = next((r for r in rows if isinstance(r, dict) and int(r.get("k") or 0) == 1), None)
    if not row:
        return None
    adv = row.get("advice") or {}
    head = (f'{_day_md(row.get("date"))} {str(row.get("weekday") or "")}'.strip()
            or "下一交易日")
    bits = []
    label = str(row.get("label") or "").strip()
    prob = row.get("p_day") if row.get("p_day") is not None else row.get("p_cum")
    p_txt = _p0(prob)
    if label and p_txt:
        bits.append(f"{label} {p_txt}")
    elif label or p_txt:
        bits.append(label or p_txt)
    lo, hi = _n0(row.get("band_lo")), _n0(row.get("band_hi"))
    if lo and hi:
        bits.append(f"区间 {lo}–{hi}")
    if adv.get("position") is not None:
        bits.append(f"仓位 ≤{int(adv['position'])}%")
    stop = _n0(adv.get("stop_price"))
    if stop:
        bits.append(f"止损 {stop}")
    take = _n0(adv.get("take_profit"))
    if take:
        bits.append(f"止盈 {take}")
    if len(bits) < 2:            # 只剩一个数字就不成「剧本」，整行缺席
        return None
    icon = {"up": "▲", "down": "▼"}.get(row.get("direction"), "■")
    return ("setup", (f"{icon} 明日剧本", f"<b>{head}</b> · " + " · ".join(bits)))


def _line_week(ctx):
    """② 七日风：整段累计概率（+ 量化 5 日概率；两者视界不同，如实并列不混算）。"""
    bits = []
    entry = (ctx.get("weekly") or {}).get("entry") or {}
    if entry.get("label"):
        p_up = _p0(entry.get("p_up"))
        horizon = entry.get("target_sessions")
        bits.append(str(entry["label"])
                    + (f' · P({horizon}日涨) {p_up}' if p_up and horizon else ""))
    quant = ctx.get("quant") or {}
    head_q = quant.get("headline") or {}
    if head_q.get("available") and head_q.get("p_up") is not None:
        bits.append(f'量化 5 日 {head_q.get("arrow", "■")} {_p0(head_q["p_up"])}'
                    f'（{str(quant.get("target_label") or "下一交易日")}）')
    if not bits:
        return None
    return ("week", ("■ 七日风", " · ".join(bits)))


def _line_mustsee(ctx):
    """③ 今明必看：今天 + 明天的 ★★ 以上时点（最多 4 条），没有就如实说没有。

    「今明」以 ctx["today"]（报告日的 date 对象，由 pipeline 传入）为基准逐日算 T+n，
    而不是取窗口里最早的两天——否则报告日之后的远期读数会被误当成「明天」。
    """
    cal = ctx.get("cal") or {}
    items = [it for it in (cal.get("items") or []) if isinstance(it, dict)]
    dated = [(str(it.get("date") or ""), _day_md(it.get("date")), it) for it in items]
    dated = [x for x in dated if x[0]]
    if not dated:
        return None
    base = ctx.get("today")
    near = set()
    if base is not None:
        for iso, _md, _it in dated:
            try:
                day = datetime.strptime(iso, "%Y-%m-%d").date()
            except ValueError:
                continue
            if 0 <= (day - base).days < MUSTSEE_DAYS:
                near.add(iso)
    else:                                   # 没有报告日基准 → 不猜「今明」，整行缺席
        return None
    picked = [x for x in dated if x[0] in near
              and int(x[2].get("imp") or 0) >= MUSTSEE_MIN_IMP]
    if not picked:               # 今明没有重要时点 → 如实说「无」，不硬凑远处的日子
        return ("mustsee", ("⏰ 今明必看", "无 ★★ 以上数据 / 事件（可正常操作）"))
    picked.sort(key=lambda x: (x[0], str(x[2].get("time") or "99:99")))
    labels = []
    for iso, md, it in picked[:MUSTSEE_MAX]:
        name = str(it.get("name") or "")[:MUSTSEE_NAME_CHARS]
        city = str(it.get("city") or "")
        when = str(it.get("time") or "")[:5]
        when = "" if when in ("", "99:99") else when
        labels.append(f'{md}{" " + city if city else ""} {name}{" " + when if when else ""}')
    return ("mustsee", ("⏰ 今明必看",
                        _pack([x.strip() for x in labels], MUSTSEE_MAX_CHARS)))


def _line_sector(ctx):
    """④ 板块强弱：各取前 3（优先策略研判量化强度榜，缺席时用 A股全景板块热力）。"""
    sectors = [s for s in ((ctx.get("ai") or {}).get("quant_sectors") or [])
               if isinstance(s, dict)]

    def tag(name, chg):
        name = str(name or "")[:SECTOR_NAME_CHARS]
        chg = _signed(chg)
        return name + (f" {chg}%" if chg else "")

    # 强弱按趋势分（composite）的正负号分堆：样本不足 3+3 时有几只列几只，
    # 绝不让「领跌板块」混进强的一堆（隐喻必须说真话）。
    strong, weak = [], []
    for sec in [s for s in sectors if (s.get("composite") or 0) > 0][:SECTOR_MAX]:
        strong.append(tag(sec.get("name"), sec.get("chg")))
    for sec in [s for s in sectors if (s.get("composite") or 0) < 0][-SECTOR_MAX:]:
        weak.append(tag(sec.get("name"), sec.get("chg")))
    if not strong:               # 策略研判缺席 → 用 A股全景的板块热力兜底（同源同口径）
        pan_sectors = (ctx.get("pan") or {}).get("sectors") or {}
        for key, bucket in (("leading", strong), ("lagging", weak)):
            for it in (pan_sectors.get(key) or [])[:SECTOR_MAX]:
                if isinstance(it, dict):
                    bucket.append(tag(it.get("name"), it.get("chg_pct")))
    strong = [s.strip() for s in strong if s.strip()][:SECTOR_MAX]
    weak = [w.strip() for w in weak if w.strip()][:SECTOR_MAX]
    if not strong and not weak:
        return None
    bits = []
    if strong:
        bits.append("强 " + "、".join(strong))
    if weak:
        bits.append("弱 " + "、".join(weak))
    return ("sector", ("⚡ 板块强弱", " · ".join(bits)))


def _line_money(ctx):
    """⑤ 水位：流动性综合分 + 南向成交与量能标签（水少就别追高）。"""
    liq = (ctx.get("quant") or {}).get("liquidity") or {}
    if not liq.get("available"):
        return None
    bits = []
    if liq.get("score") is not None:
        bits.append(f'{float(liq["score"]):.0f}/100 {str(liq.get("label") or "")}'.strip())
    south = liq.get("south") or {}
    if south.get("available"):
        amount = _yi(south.get("latest"))
        flow = ""
        if _liquidity is not None:
            try:
                # 只取标签的第一段（放量 / 缩量 / 中性）：分位那句在「资金流动性分析」
                # 栏目里原样保留，卡上不重复占字数。
                flow = str(_liquidity.flow_label(south) or "").split(" · ")[0]
            except Exception:
                flow = ""
        if amount:
            bits.append("南向 " + amount + (f"（{flow}）" if flow and flow != "None" else ""))
    if not bits:
        return None
    return ("money", ("💧 水位", " · ".join(bits)))


def _line_news(ctx):
    """⑥ 风声：新闻情绪整体 DNS + 最暖 / 最冷点名（情绪是后视镜，只作氛围参考）。"""
    ms = (ctx.get("senti") or {}).get("market_summary") or {}
    if not ms.get("available") or ms.get("overall_dns") is None:
        return None
    bits = [f'{_dns_arrow(ms["overall_dns"])} {str(ms.get("overall_label") or "中性")}'
            f' DNS {_signed(ms["overall_dns"])}']
    hot, cold = ms.get("hottest") or {}, ms.get("coldest") or {}
    if hot.get("name"):
        bits.append(f'最暖 {hot["name"]}')
    if cold.get("name") and cold.get("key") != hot.get("key"):
        bits.append(f'最冷 {cold["name"]}')
    return ("news", ("📣 风声", " · ".join(bits)))


def _line_coverage(ctx):
    """⑦ 数据底：当天源 n/m（数据不新鲜时，短线客最该先知道这件事）。"""
    cov = ctx.get("coverage") or {}
    today, total = cov.get("today"), cov.get("total")
    if not total:
        return None
    return ("coverage", ("🔎 数据底", f"当天源 {today}/{total} · 数字与下文各栏同源"))


_LINE_BUILDERS = (_line_setup, _line_week, _line_mustsee, _line_sector,
                  _line_money, _line_news, _line_coverage)


# ------------------------------------------------------------------
# 组卡：取材 → 预算内整行裁剪 → 输出纯文本（渲染交给 pipeline 的 kit）
# ------------------------------------------------------------------
def _lead_text(ctx):
    """一句定调：策略研判倾向（信号分）→ 量化 headline → 诚实兜底「信息不足」。"""
    ai = ctx.get("ai") or {}
    if ai.get("available"):
        score = ai.get("score") or 0
        arrow = "▲" if score > 8 else ("▼" if score < -8 else "■")
        try:
            score_txt = f"{int(score):+d}"
        except (TypeError, ValueError):
            score_txt = ""
        return (f'{arrow} 今日定调 {str(ai.get("sentiment_label") or "中性")}'
                + (f"（信号 {score_txt}）" if score_txt else ""))
    quant = ctx.get("quant") or {}
    head = quant.get("headline") or {}
    if head.get("available") and head.get("label"):
        p_up = _p0(head.get("p_up"))
        return (f'{head.get("arrow", "■")} 今日定调 {head["label"]}'
                + (f" {p_up}" if p_up else "")
                + f'（{str(quant.get("target_label") or "下一交易日")}）')
    return "■ 今日定调：现有数据不足以判断方向，先看下面的时点与水位"


def build_card(ctx):
    """按 ctx 组装速查卡；一行数据都拿不到时返回 None（整卡缺席，不占版面）。

    返回 {"lead": str, "pairs": [(label, value)], "tips": [(label, text)],
          "dropped": [key], "text": str}
      lead    —— 一句定调（大字）；
      pairs   —— 数据行（已按预算整行撤下部分行，顺序按 LINE_ORDER）；
      tips    —— 固定【新手三句话】；
      dropped —— 因字数预算被撤下的行 key（如实留痕，绝不静默丢内容）；
      text    —— 全部可见文字（去标签）拼接，字数预算与测试断言共用同一口径。
    """
    ctx = ctx if isinstance(ctx, dict) else {}
    lines = []
    for build in _LINE_BUILDERS:
        try:
            line = build(ctx)
        except Exception:                       # 单行出错只丢该行，不影响日报
            line = None
        if line:
            lines.append(line)

    droppable = [ln for ln in lines if ln[0] != "coverage"]
    if not droppable:
        return None                             # 一行数据都没有 → 整卡缺席

    lead = _lead_text(ctx)
    tips = list(BEGINNER_TIPS)

    def plain(pairs):
        blob = [lead, DISCLAIMER]
        blob += [f"{a}{b}" for a, b in pairs]
        blob += [f"{a}{b}" for a, b in tips]
        return _strip_tags("".join(blob))

    kept = list(droppable)
    dropped = []
    while kept and len(plain([(a, b) for _k, (a, b) in kept])) > CARD_CHAR_BUDGET:
        rank = {key: i for i, key in enumerate(DROP_ORDER)}
        victim = min(kept, key=lambda ln: rank.get(ln[0], len(rank)))
        kept.remove(victim)
        dropped.append(victim[0])

    kept.sort(key=lambda ln: LINE_ORDER.get(ln[0], 99))
    pairs = [(label, value) for _key, (label, value) in kept]
    pairs += [(label, value) for key, (label, value) in lines if key == "coverage"]
    return {"lead": lead, "pairs": pairs, "tips": tips,
            "dropped": dropped, "text": plain(pairs)}


def card_char_count(card):
    """卡片可见文字字数（不含 HTML 标签）；测试用它守字数预算。"""
    if not card:
        return 0
    return len(str(card.get("text") or ""))
