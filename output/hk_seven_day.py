#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""◈ AI 七日港股走势分析概率 —— 未来 7 个交易日三大港股指数升跌概率。

取代原「每日量化策略（行业轮动）」栏目（该栏目从上线到 2026-09-28 的 58 份日报里
出现率 0/58：东方财富行业板块两步取数在真实环境没跑通，连续整栏缺席）。新栏目按
用户口径实现：**恒生指数 / 恒生科技 / 国企指数**，未来 **7 个交易日**（按交易日计数、
假期顺延）收盘价高于当前收盘价的概率。

两条腿（先算量化基准，再让大模型在给定数据内做合成判断）：

  ① 量化基准（always on）：复用 ``octopus_weekly`` 的因果引擎（扩张基准率 + 20 日特征
     最近邻、逐期扩张 z 标准化、``s+horizon ≤ t`` 的已结算锚点），本模块只把视界改成 7；
     并提供 5%~95% 硬边界与滚动样本外体检（Brier / 命中 / 恒定基准）。
  ② 大模型研判（可选，任何 OpenAI 兼容的 ``/chat/completions``）：把 ① 的数字与当日
     港股证据（指数特征、南向资金、未来两周日程、港股相关标题）作为**唯一可用依据**
     交给模型，要求回传严格 JSON。三道硬约束：
       · 概率夹在 5%~95%，且相对量化基准的偏离不超过 ``MAX_PROB_DEVIATION``（超出即收敛，
         并在栏目里如实标注「已按量化基准收敛」）；
       · **数字溯源**：模型文案里出现的每个数字都必须能在本次给定数据里找到，否则该条
         文案回退为量化口径（绝不把编造的数字写进日报）；
       · 禁用「一定 / 必然 / 保证」等绝对化措辞，命中即回退。

降级（``OCTOPUS_HK7_FALLBACK``，三档）：默认 ``auto`` —— **未配置 Key 时本栏目整体
缺席**（没有大模型研判就不挂「AI」栏目，上层也不把它计入数据覆盖审计）；已配置 Key
但网络失败 / 返回不是合法 JSON / 字段校验不过 → 回落量化基准（``engine="quant"``）并
在栏内标注原因。``=1`` 连没有 Key 也降级渲染（量化基准 + 标注）；``=0`` 任何大模型
不可用（含调用失败）都整栏缺席。数据取不到、样本不足 → ``available=False`` + 原因，
由上层整栏缺席。

留痕与结算：每次运行把三只指数的概率写进 ``output/hk7_forecast.json``（settled=False），
满 7 个交易日后按真实收盘回填方向命中；样本 <10 只报样本量，不下命中率结论。

对外入口：``run_seven_day(fetch_json, history_path=..., extra=..., post_json=..., now=...)``。
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
TRADING_DAYS = 252

# ---- 口径常量（写死可复现；改任何一条都会改变预测，必须同步测试）----
HORIZON = 7                  # 预测视界 = 未来 7 个交易日（按交易日计数，假期顺延）
WINDOW = 20                  # 特征窗口（交易日）
MIN_BARS = 60                # 最少日线根数（与 octopus_weekly 同口径）
PROB_FLOOR = 0.05            # 概率硬边界：统计模型永远保留被证伪的余地
PROB_CAP = 0.95
DIR_UP = 0.58                # 展示方向阈值（结算一律按 P ≥ 0.5 的底牌方向）
DIR_DOWN = 0.42
MAX_PROB_DEVIATION = 0.20    # 大模型概率相对量化基准的最大偏离（超出即收敛）
MIN_JOURNAL_FOR_HITRATE = 10  # 结算样本 <10 只报样本量，不下命中率结论
JOURNAL_FILENAME = "hk7_forecast.json"
JOURNAL_MAX_ENTRIES = 120
MAX_TEXT_NEWS = 10           # 交给大模型的港股相关标题上限

# 三只标的：Yahoo 代码按顺序尝试（国企指数在 Yahoo 是 ^HSCE；^HSCEI 作兜底）
TARGETS = (
    {"name": "恒生指数", "short": "恒指", "symbols": ("^HSI",)},
    {"name": "恒生科技", "short": "恒科", "symbols": ("^HSTECH",)},
    {"name": "国企指数", "short": "国企", "symbols": ("^HSCE", "^HSCEI")},
)

# 大模型配置：任何 OpenAI 兼容服务都能用（默认 DeepSeek，可在环境变量里改）
ENV_KEY_NAMES = ("OCTOPUS_LLM_API_KEY", "OCTOPUS_HK7_LLM_KEY",
                 "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
                 "MOONSHOT_API_KEY", "DASHSCOPE_API_KEY")
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 60
USER_AGENT = "octopus-ai-daily/1.0 (+hk-seven-day)"

# 「一定 / 必然」这类绝对化措辞：命中即该条文案回退量化口径
_FORBIDDEN_RE = re.compile(
    r"一定|必然|保证|确保|稳赚|必涨|必跌|无风险|百分百|100\s*%|零风险|包赚", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"https?://\S+")
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*%?")

# 允许出现在模型文案里的常量数字（口径本身：视界 / 窗口 / 概率边界 / 指标参数等）
_CONST_NUMBERS = {"1", "2", "3", "4", "5", "7", "10", "14", "20", "50", "52", "60", "95"}


# ============================================================
# 基础工具（纯函数，可离线单测）
# ============================================================
def _clamp(p):
    return max(PROB_FLOOR, min(PROB_CAP, float(p)))


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _direction_label(p_up):
    """P(7日涨) → (方向, 展示文案)；展示可以中性，结算只认 P ≥ 0.5 的底牌。"""
    p_up = _clamp(p_up)
    if p_up >= DIR_UP:
        return "up", f"▲ 偏多 · P(7日涨) {p_up * 100:.0f}%"
    if p_up <= DIR_DOWN:
        return "down", f"▼ 偏空 · P(7日涨) {p_up * 100:.0f}%"
    lean = "涨" if p_up >= 0.5 else "跌"
    return "neutral", f"■ 中性（略偏{lean}）· P(7日涨) {p_up * 100:.0f}%"


def _features(closes, t, window=WINDOW):
    """t 时刻（含）之前的窗口特征 —— 只读 closes[0..t]，无未来数据。"""
    c0 = closes[t]

    def _ret(k):
        prev = closes[t - k] if t - k >= 0 else None
        return (c0 / prev - 1.0) if prev else 0.0

    w = closes[t - window + 1:t + 1]
    rets = [w[i] / w[i - 1] - 1.0 for i in range(1, len(w)) if w[i - 1] > 0]
    peak = max(w) if w else c0
    n = len(rets)
    vol = 0.0
    if n >= 2:
        mu = sum(rets) / n
        vol = math.sqrt(sum((r - mu) ** 2 for r in rets) / n) * math.sqrt(TRADING_DAYS)
    return {
        "ret5": _ret(5),
        "ret10": _ret(10),
        "ret20": _ret(window),
        "vol20": vol,
        "dd20": (c0 / peak - 1.0) if peak > 0 else 0.0,
    }


def _ret_over(closes, k):
    """最近 k 个交易日的收益（样本不足返回 None）。"""
    if not closes or len(closes) <= k or k <= 0 or closes[-1 - k] <= 0:
        return None
    return closes[-1] / closes[-1 - k] - 1.0


def _var7(closes):
    """历史 7 交易日收益分布（重叠窗口，仅用于展示 5%/95% 区间，不参与概率）。

    样本 <60 时返回 None（不给出置信区间，绝不编造）。
    """
    rets = []
    for i in range(len(closes) - HORIZON):
        base = closes[i]
        if base > 0:
            rets.append(closes[i + HORIZON] / base - 1.0)
    if len(rets) < 60:
        return None
    rets.sort()

    def _q(p):
        pos = (len(rets) - 1) * p
        lo = int(math.floor(pos))
        hi = min(lo + 1, len(rets) - 1)
        return rets[lo] + (rets[hi] - rets[lo]) * (pos - lo)

    return {"q05": _q(0.05), "q50": _q(0.50), "q95": _q(0.95), "n": len(rets)}


def _rsi14(closes):
    """Wilder RSI14 —— 直接复用港股量化引擎的实现，保证两个港股指数的 RSI 口径一致。"""
    from octopus_quant import stats as _stats
    return _stats.rsi(closes, 14)


def _sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _vol_pct(closes):
    """当前 20 日年化波动在过去一年里的分位（只用 ≤ 最新一根的数据）。"""
    hist = []
    for t in range(WINDOW, len(closes)):
        hist.append(_features(closes, t)["vol20"])
    if len(hist) < 2:
        return None
    cur = hist[-1]
    past = hist[:-1]
    return sum(1 for v in past if v <= cur) / len(past)


# ============================================================
# 量化基准：复用 octopus_weekly 的因果引擎（视界改成 7）
# ============================================================
def quant_probability(closes):
    """返回 {ok, reason, p_up, backtest, self_check, features, n_resolved, ...}。"""
    import octopus_weekly as _weekly  # 惰性导入：同一份经过回归测试的因果引擎

    computed = _weekly.compute_signals(list(closes), horizon=HORIZON)
    if not computed.get("ok"):
        return {"ok": False, "reason": computed.get("reason") or "信号不可计算"}
    last = computed["signals"][-1]
    if not last:
        return {"ok": False, "reason": "最新一根 K 线尚无足够已结算样本"}
    ok, msg = _weekly.check_no_lookahead(list(closes), horizon=HORIZON)
    if not ok:
        return {"ok": False, "reason": f"未来函数自检未通过：{msg}"}
    return {
        "ok": True,
        "p_up": _clamp(last["p_up"]),
        "p_base": last.get("p_base"),
        "p_sim": last.get("p_sim"),
        "n_analog": last.get("n_analog"),
        "n_resolved": last.get("n_resolved"),
        "blended": last.get("blended"),
        "features": last.get("features"),
        "backtest": _weekly._backtest(list(closes), computed["signals"], horizon=HORIZON),
        "self_check": msg,
    }


# ============================================================
# 大模型：配置 / 调用 / 严格 JSON 解析 / 校验
# ============================================================
def llm_config(env=None):
    """读取大模型配置；无 Key 时 enabled=False。

    ``fallback`` 三档（``OCTOPUS_HK7_FALLBACK``）：
      · auto（默认）——未配置 Key → 上层整栏缺席；已配 Key 但大模型不可用 → 降级量化基准；
      · always（=1）——没有 Key 也降级渲染（量化基准 + 栏内标注）；
      · never（=0）——任何大模型不可用（含调用失败）都整栏缺席。
    """
    env = os.environ if env is None else env
    key = ""
    for name in ENV_KEY_NAMES:
        val = str(env.get(name) or "").strip()
        if val:
            key = val
            break
    base = str(env.get("OCTOPUS_LLM_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    model = str(env.get("OCTOPUS_LLM_MODEL") or DEFAULT_MODEL).strip()
    timeout = 60
    try:
        timeout = max(5, min(180, int(str(env.get("OCTOPUS_LLM_TIMEOUT") or DEFAULT_TIMEOUT))))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    mode = str(env.get("OCTOPUS_HK7_FALLBACK", "auto")).strip().lower()
    if mode in ("1", "true", "yes", "always"):
        fallback = "always"
    elif mode in ("0", "false", "no", "never"):
        fallback = "never"
    else:
        fallback = "auto"
    return {"enabled": bool(key), "key": key, "base": base, "model": model,
            "timeout": timeout, "fallback": fallback}


def http_post_json(url, payload, headers, timeout=DEFAULT_TIMEOUT):
    """标准库 POST → 解析 JSON；任何异常直接抛出，由调用方降级（不静默）。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def build_prompt(context):
    """(system, user)：把「唯一可用依据」和输出结构写清楚，禁止自由发挥。"""
    system = (
        "你是港股量化研究员，只做概率研判、不做投资建议。硬性要求："
        "① 只能使用用户消息里给出的数据，禁止编造任何数字、日期、点位或新闻；"
        "② 概率必须在 0.05~0.95 之间，绝不出现 0%/100% 的假确定性；"
        "③ 不使用「一定 / 必然 / 保证」等绝对化措辞；"
        "④ 只输出一个 JSON 对象，不要 markdown 代码块、不要多余文字。")
    user = (
        "任务：估计下列港股指数在未来 {h} 个交易日（按交易日计数，假期顺延）收盘价"
        "高于当前收盘价的概率。\n"
        "可用数据（唯一依据）：\n{ctx}\n\n"
        "请输出 JSON，结构（不要增删字段）：\n"
        '{{"targets":[{{"code":"^HSI","p_up":0.57,"summary":"不超过60字的结论",'
        '"drivers":["不超过30字的依据","…"],"risks":["不超过30字的风险"],'
        '"support":24500,"resistance":25600}}],"cross_note":"不超过60字的跨市场一句",'
        '"confidence":"低或中或高"}}\n'
        "要求：targets 必须恰好覆盖上面列出的每个 code；support/resistance 必须落在"
        "该指数的近期波动区间内；每个 drivers / risks 最多 3 条。".format(
            h=HORIZON, ctx=json.dumps(context, ensure_ascii=False, indent=1)))
    return system, user


def _extract_json(text):
    """从模型回复里取出 JSON 对象（容忍 ```json 代码块与前后废话）。"""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(s[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def call_llm(config, context, post_json=None):
    """调用大模型；返回 (payload, error)。任何一步失败都返回 (None, 原因)。"""
    if not config.get("enabled"):
        return None, "未配置大模型 API Key"
    post = post_json or http_post_json
    url = f"{config['base']}/chat/completions"
    system, user = build_prompt(context)
    payload = {
        "model": config.get("model") or DEFAULT_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {config.get('key') or ''}"}
    try:
        data = post(url, payload, headers, int(config.get("timeout") or DEFAULT_TIMEOUT))
    except Exception as exc:                      # 网络 / HTTP / 解析异常一律降级
        return None, f"{type(exc).__name__}: {exc}"
    if not isinstance(data, dict):
        return None, "大模型返回不是 JSON 对象"
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        return None, str(err.get("message") or "大模型响应缺少 choices[0].message.content")
    parsed = _extract_json(content)
    if parsed is None:
        return None, "大模型回复不是合法 JSON"
    return parsed, ""


# ------------------------------------------------------------
# 数字溯源：文案里的每个数字都必须能在给定数据里找到
# ------------------------------------------------------------
def _number_forms(value):
    """一个数值在文案里的常见写法（整数 / 一两位小数 / 千分位 / 百分号，正负号忽略）。"""
    forms = set()
    val = _num(value)
    if val is None:
        return forms
    for v in (val, abs(val)):                     # 符号不参与溯源：方向由概率字段负责
        for spec in ("{:.0f}", "{:.1f}", "{:.2f}", "{:,.0f}", "{:,.2f}"):
            try:
                forms.add(spec.format(v))
            except (ValueError, TypeError):
                continue
        if abs(v) <= 1000:
            for spec in ("{:.0f}%", "{:.1f}%", "{:.2f}%"):
                try:
                    forms.add(spec.format(v))
                except (ValueError, TypeError):
                    continue
    return forms


def _normalize_number(tok):
    return str(tok or "").strip().lstrip("+-").rstrip("%").replace(",", "")


def _collect_numbers(obj, strings, values):
    """递归收集数据里的全部数值（字符串只做原样收录，不解析）。"""
    if isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, strings, values)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _collect_numbers(v, strings, values)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        val = _num(obj)
        if val is None:
            return
        values.append(val)
        strings.update(_number_forms(val))
    elif isinstance(obj, str):
        for tok in _NUM_RE.findall(obj):
            strings.add(_normalize_number(tok))
    return strings, values


def _allowed_numbers(context, extra_values=()):
    """本次给定数据允许出现的数字集合（字符串写法 + 原值，供近似比对）。"""
    strings = {_normalize_number(t) for t in _CONST_NUMBERS}
    values = []
    _collect_numbers(context, strings, values)
    for v in extra_values:
        val = _num(v)
        if val is not None:
            values.append(val)
            strings.update({_normalize_number(f) for f in _number_forms(val)})
    return {"strings": strings, "values": values}


def _trace_numbers(text, allowed):
    """返回文案里查不到来源的数字集合（空集 = 全部可溯源）。"""
    missing = set()
    for tok in _NUM_RE.findall(str(text or "")):
        norm = _normalize_number(tok)
        if norm in allowed.get("strings", ()):
            continue
        try:
            val = float(norm)
        except ValueError:
            missing.add(tok)
            continue
        if any(abs(val - a) <= max(0.01, abs(a) * 0.005) for a in allowed.get("values") or ()):
            continue
        missing.add(tok)
    return missing


def _sanitize_text(text, limit, allowed):
    """清 HTML / 链接 / 绝对化措辞；数字查不到来源时返回 (None, missing)。"""
    s = _TAG_RE.sub(" ", str(text or ""))
    s = _URL_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "", set()
    if _FORBIDDEN_RE.search(s):
        return None, {"绝对化措辞"}
    missing = _trace_numbers(s, allowed)
    if missing:
        return None, missing
    if len(s) > limit:
        s = s[:limit].rstrip(" ，,。.;；") + "…"
    return s, set()


def _quant_texts(ctx):
    """量化口径的文案模板（大模型文案不可用时的兜底，数字全部来自本次数据）。"""
    q = ctx.get("quant") or {}
    drivers = [f"扩张基准率 + 20日特征最近邻（K=8，已结算锚点，无未来函数）"
               f" · 已结算 {int(q.get('n_resolved') or 0)} 个 {HORIZON} 日样本"]
    risks = ["统计口径不含事件冲击与政策突发；样本外表现见留痕，非投资建议"]
    summary = (f"量化基准 P(7日涨) {float(q.get('p_up') or 0.5) * 100:.1f}%"
               f"（已结算 {int(q.get('n_resolved') or 0)} 个 {HORIZON} 日样本）")
    return summary, drivers, risks


# ------------------------------------------------------------
# 合并大模型输出：概率收敛 + 文案溯源 + 兜底
# ------------------------------------------------------------
def merge_llm_estimate(payload, contexts, allowed):
    """把大模型 JSON 合并进量化上下文。

    返回 (by_symbol, notes)：by_symbol[code] = {texts..., "converged": bool, ...}；
    notes 汇总降级原因（供栏目与日志展示，绝不静默）。
    """
    notes = {"targets": 0, "p_fallback": 0, "text_fallback": 0, "converged": 0,
             "texts_offered": 0, "texts_traced": 0, "dropped": []}
    by_code = {}
    for item in (payload or {}).get("targets") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip().upper()
        if code:
            by_code[code] = item
    out = {}
    for ctx in contexts:
        code = ctx["symbol"].upper()
        item = by_code.get(code) or {}
        q = ctx.get("quant") or {}
        q_p = _clamp(q.get("p_up") if q.get("p_up") is not None else 0.5)
        p_up = _num(item.get("p_up"))
        converged = False
        if p_up is None:
            p_up = q_p
            notes["p_fallback"] += 1
        else:
            p_up = _clamp(p_up)
            if abs(p_up - q_p) > MAX_PROB_DEVIATION:      # 偏离过大 → 向量化基准收敛
                p_up = _clamp(q_p + math.copysign(MAX_PROB_DEVIATION, p_up - q_p))
                converged = True
                notes["converged"] += 1
        extra_values = [p_up * 100, ctx.get("close"),
                        item.get("support"), item.get("resistance")]
        allowed_for_target = _allowed_numbers(ctx, extra_values)
        allowed_for_target |= allowed

        def _pick(field, limit, max_items=3):
            raw = item.get(field)
            values = raw if isinstance(raw, list) else ([raw] if raw else [])
            good, dropped = [], 0
            for v in values[:max_items]:
                notes["texts_offered"] += 1
                text, missing = _sanitize_text(v, limit, allowed_for_target)
                if text is None or not text:
                    dropped += 1
                    if missing:
                        notes["dropped"].extend(sorted(missing)[:3])
                    continue
                notes["texts_traced"] += 1
                good.append(text)
            return good, dropped

        summary, drop_s = _pick("summary", 64)
        drivers, drop_d = _pick("drivers", 32)
        risks, drop_r = _pick("risks", 32)
        cross, _drop_c = _sanitize_text(payload.get("cross_note"), 80, allowed_for_target)
        d_sum, d_drv, d_rsk = _quant_texts(ctx)
        summary = summary[0] if summary else d_sum
        if not drivers:
            drivers = d_drv
        if not risks:
            risks = d_rsk
        notes["text_fallback"] += drop_s + drop_d + drop_r
        support = _num(item.get("support"))
        resistance = _num(item.get("resistance"))
        close = _num(ctx.get("close")) or 0.0
        if support is not None and not (close * 0.85 <= support <= close * 1.15):
            support = None
        if resistance is not None and not (close * 0.85 <= resistance <= close * 1.15):
            resistance = None
        out[code] = {
            "p_up": p_up, "quant_p_up": q_p, "converged": converged,
            "summary": summary, "drivers": drivers, "risks": risks,
            "support": support, "resistance": resistance,
            "cross_note": cross,
        }
        notes["targets"] += 1
    return out, notes


# ============================================================
# 留痕与结算：先存档（settled=False）→ 满 7 个交易日按真实收盘回填
# ============================================================
def _load_journal(path):
    empty = {"version": 1, "entries": []}
    if not path or not os.path.isfile(path):
        return empty
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return empty


def _save_journal(path, journal):
    if not path:
        return
    try:
        entries = journal.get("entries")
        if isinstance(entries, list) and len(entries) > JOURNAL_MAX_ENTRIES:
            journal["entries"] = entries[-JOURNAL_MAX_ENTRIES:]
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(journal, fh, ensure_ascii=False, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        pass  # 留痕写不进去不影响本次展示；下次运行再写


def _settle(entries, series, now=None):
    """结算所有已到龄的预测（目标日 = 锚定日 + 7 个**交易日**，没有那根 K 线就不结算）。"""
    now = now or datetime.now(CST)
    resolved_today = []
    today = now.strftime("%Y-%m-%d")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("settled"):
            continue
        pair = series.get(entry.get("symbol"))
        if not pair:
            continue
        dates, closes = pair
        index = {d: i for i, d in enumerate(dates)}
        b = index.get(entry.get("base_date"))
        if b is None:
            continue
        j = b + HORIZON
        if j >= len(closes) or closes[b] <= 0:
            continue
        actual = closes[j] / closes[b] - 1.0
        entry["settled"] = True
        entry["settle_date"] = dates[j]
        entry["actual_ret"] = actual
        entry["actual_dir"] = "up" if actual > 0 else ("down" if actual < 0 else "flat")
        entry["hit"] = bool((entry.get("p_up") or 0.5) >= 0.5) == (actual > 0)
        entry["brier"] = (float(entry.get("p_up") or 0.5) - (1.0 if actual > 0 else 0.0)) ** 2
        if dates[j] == today:
            resolved_today.append(entry)
    return resolved_today


def _issue(ctx, merged, dates, closes, now):
    """按最新一根 K 线签发预测（同一锚定日同一标的只签发一次）。"""
    i = len(dates) - 1
    direction, label = _direction_label(merged["p_up"])
    return {
        "base_date": dates[i],
        "base_close": closes[i],
        "symbol": ctx["symbol"],
        "symbol_label": ctx["name"],
        "target_sessions": HORIZON,
        "target_note": f"锚定日后第 {HORIZON} 个交易日收盘（按交易日计数，假期顺延）",
        "p_up": merged["p_up"],
        "quant_p_up": merged.get("quant_p_up"),
        "engine": ctx.get("engine") or "quant",
        "direction": direction,
        "label": label,
        "issued_cst": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "settled": False,
    }


def _journal_stats(entries):
    settled = [e for e in entries if isinstance(e, dict) and e.get("settled")]
    n = len(settled)
    hits = sum(1 for e in settled if e.get("hit"))
    recent = [{"date": e.get("settle_date"), "ret": e.get("actual_ret"),
               "hit": bool(e.get("hit")), "p_up": e.get("p_up")}
              for e in settled[-3:]]
    brier = None
    if n:
        vals = [e.get("brier") for e in settled if e.get("brier") is not None]
        if vals:
            brier = sum(vals) / len(vals)
    return {
        "n": n,
        "hits": hits,
        "hit_rate": (hits / n) if n >= MIN_JOURNAL_FOR_HITRATE else None,
        "brier": brier if n >= MIN_JOURNAL_FOR_HITRATE else None,
        "note": (None if n >= MIN_JOURNAL_FOR_HITRATE
                 else f"已结算 {n} 个样本（<{MIN_JOURNAL_FOR_HITRATE}，只报样本量）"),
        "recent": recent,
        "standing": sum(1 for e in entries if isinstance(e, dict) and not e.get("settled")),
    }


# ============================================================
# 对外入口
# ============================================================
def _fetch_bars_for(fetch_json, target, rng):
    """按候选代码顺序取日线；返回 (symbol, bars)，全失败返回 (None, [])。"""
    from octopus_quant.providers import fetch_bars  # 唯一复用的联网数据层

    for symbol in target["symbols"]:
        try:
            bars = fetch_bars(fetch_json, symbol, rng=rng)
        except Exception:
            bars = []
        if len(bars) >= MIN_BARS:
            return symbol, bars
    return None, []


def _build_context(target, symbol, bars, engine):
    closes = [float(b["close"]) for b in bars]
    highs = [float(b.get("high") or b["close"]) for b in bars]
    lows = [float(b.get("low") or b["close"]) for b in bars]
    q = quant_probability(closes)
    if not q.get("ok"):
        return None, q.get("reason") or "量化基准不可用"
    feats = q.get("features") or _features(closes, len(closes) - 1)
    vol20_ann = None
    if feats.get("vol20") is not None:
        vol20_ann = float(feats["vol20"]) * math.sqrt(TRADING_DAYS)   # 日波动 → 年化
    ma20, ma60 = _sma(closes, 20), _sma(closes, 60)
    var = _var7(closes)
    close = closes[-1]
    ctx = {
        "name": target["name"], "short": target["short"], "symbol": symbol,
        "asof": bars[-1]["date"], "close": close,
        "ret5": _ret_over(closes, 5), "ret20": _ret_over(closes, 20),
        "ret60": _ret_over(closes, 60),
        "ma20_dev": (close / ma20 - 1.0) if ma20 else None,
        "ma60_dev": (close / ma60 - 1.0) if ma60 else None,
        "rsi14": _rsi14(closes), "vol_pct": _vol_pct(closes),
        "vol20_ann": vol20_ann,
        "hi20": max(highs[-20:]), "lo20": min(lows[-20:]),
        "hi52": max(highs[-252:]), "lo52": min(lows[-252:]),
        "var7": var,
        "lo95": close * (1.0 + var["q05"]) if var else None,
        "hi95": close * (1.0 + var["q95"]) if var else None,
        "features": feats, "quant": q, "engine": engine,
        "bars_n": len(closes),
    }
    return ctx, ""


def _context_for_prompt(contexts, extra):
    """交给大模型的数据块（唯一可用依据）——只放本次真实抓到的数字。"""
    def _r2(v):
        x = _num(v)
        return None if x is None else round(x, 2)

    def _pct(v):
        x = _num(v)
        return None if x is None else round(x * 100, 1)

    ctx = {
        "as_of": contexts[0]["asof"] if contexts else None,
        "horizon_trading_days": HORIZON,
        "indices": [],
    }
    for c in contexts:
        ctx["indices"].append({
            "code": c["symbol"], "name": c["name"],
            "close": _r2(c["close"]),
            "ret5_pct": _pct(c.get("ret5")), "ret20_pct": _pct(c.get("ret20")),
            "ret60_pct": _pct(c.get("ret60")),
            "ma20_dev_pct": _pct(c.get("ma20_dev")), "ma60_dev_pct": _pct(c.get("ma60_dev")),
            "rsi14": _r2(c.get("rsi14")),
            "vol20_annual_pct": _pct(c.get("vol20_ann")),
            "vol_percentile_pct": _pct(c.get("vol_pct")),
            "drawdown20_pct": _pct((c.get("features") or {}).get("dd20")),
            "range20_low": _r2(c.get("lo20")), "range20_high": _r2(c.get("hi20")),
            "range52_low": _r2(c.get("lo52")), "range52_high": _r2(c.get("hi52")),
            "quant_base_prob_up": round(float((c.get("quant") or {}).get("p_up") or 0.5), 3),
            "quant_resolved_samples": int((c.get("quant") or {}).get("n_resolved") or 0),
            "hist_7d_q05_pct": _pct((c.get("var7") or {}).get("q05")),
            "hist_7d_q95_pct": _pct((c.get("var7") or {}).get("q95")),
            "hist_7d_samples": int((c.get("var7") or {}).get("n") or 0),
        })
    flows = extra.get("flows") or {}
    if any(v is not None for v in flows.values()):
        ctx["southbound"] = flows
    events = extra.get("events") or []
    if events:
        ctx["upcoming_events"] = events[:6]
    news = extra.get("news") or []
    if news:
        ctx["hk_headlines"] = news[:MAX_TEXT_NEWS]
    return ctx


def run_seven_day(fetch_json=None, *, history_path=None, extra=None, post_json=None,
                  now=None, targets=None, rng="2y", bars_by_symbol=None,
                  config=None):
    """计算 + 大模型研判 + 留痕结算；返回供管线消费的结果字典。

    可用时：{available: True, asof, horizon, engine, engine_label, llm_reason,
             targets: [...], journal, notes, method, grounded}
    不可用：{available: False, reason}
    """
    now = now or datetime.now(CST)
    extra = extra or {}
    config = config or llm_config()
    targets = targets or TARGETS

    # 1) 取日线（注入 bars_by_symbol 时离线；否则走 providers 的 Yahoo→东财链路）
    used, contexts = {}, []
    for target in targets:
        bars = []
        symbol = None
        if bars_by_symbol:
            for cand in target["symbols"]:
                if len(bars_by_symbol.get(cand) or []) >= MIN_BARS:
                    symbol, bars = cand, bars_by_symbol[cand]
                    break
        else:
            symbol, bars = _fetch_bars_for(fetch_json, target, rng)
        if not bars:
            continue
        engine = "llm" if config.get("enabled") else "quant"
        ctx, reason = _build_context(target, symbol, bars, engine)
        if ctx is None:
            continue
        used[symbol] = bars
        contexts.append(ctx)
    if not contexts:
        return {"available": False,
                "reason": f"三只指数都没有足够的日线样本（每只至少 {MIN_BARS} 根）"}
    if len(contexts) < len(targets):
        missing = [t["name"] for t in targets
                   if t["name"] not in {c["name"] for c in contexts}]
        reason = "部分标的日线不可用：" + "、".join(missing)
    else:
        reason = ""

    # 2) 大模型研判（可选）
    prompt_ctx = _context_for_prompt(contexts, extra)
    llm_payload, llm_error = (None, "未配置大模型 API Key")
    if config.get("enabled"):
        llm_payload, llm_error = call_llm(config, prompt_ctx, post_json=post_json)
    if not llm_payload and config.get("fallback") == "never":
        # 严格模式：没有大模型结论就不出这个栏目，也不把量化口径写进预测留痕
        return {"available": False, "llm_reason": llm_error,
                "reason": f"大模型不可用（{llm_error}）"}
    engine = "llm" if llm_payload else "quant"
    for ctx in contexts:
        ctx["engine"] = engine

    merged, notes = {}, {"targets": 0, "text_fallback": 0, "converged": 0}
    if llm_payload:
        merged, notes = merge_llm_estimate(
            llm_payload, contexts, _allowed_numbers(prompt_ctx))
    if not merged:
        merged = {}
        for ctx in contexts:
            d_sum, d_drv, d_rsk = _quant_texts(ctx)
            merged[ctx["symbol"]] = {
                "p_up": _clamp((ctx.get("quant") or {}).get("p_up") or 0.5),
                "quant_p_up": _clamp((ctx.get("quant") or {}).get("p_up") or 0.5),
                "converged": False, "summary": d_sum, "drivers": d_drv, "risks": d_rsk,
                "support": None, "resistance": None,
                "cross_note": "",
            }

    # 3) 留痕：先结算历史，再按最新锚定日签发（同一锚定日不重复签发）
    journal = _load_journal(history_path)
    entries = journal.setdefault("entries", [])
    series = {sym: ([b["date"] for b in bars], [float(b["close"]) for b in bars])
              for sym, bars in used.items()}
    resolved_today = _settle(entries, series, now=now)
    changed = bool(resolved_today)
    for ctx in contexts:
        sig = merged.get(ctx["symbol"])
        if not sig:
            continue
        base_date = ctx["asof"]
        if any(isinstance(e, dict) and e.get("symbol") == ctx["symbol"]
               and e.get("base_date") == base_date for e in entries):
            continue
        entries.append(_issue(ctx, sig, *series[ctx["symbol"]], now))
        changed = True
    if changed:
        journal["updated_cst"] = now.strftime("%Y-%m-%d %H:%M:%S%z")
        _save_journal(history_path, journal)
    stats = _journal_stats(entries)

    # 4) 组装展示结构
    out_targets = []
    for ctx in contexts:
        sig = merged.get(ctx["symbol"]) or {}
        p_up = _clamp(sig.get("p_up") if sig.get("p_up") is not None else
                      (ctx.get("quant") or {}).get("p_up") or 0.5)
        direction, label = _direction_label(p_up)
        q = ctx.get("quant") or {}
        q_p = _clamp(q.get("p_up") if q.get("p_up") is not None else 0.5)
        out_targets.append({
            "code": ctx["symbol"], "name": ctx["name"], "short": ctx["short"],
            "close": ctx["close"], "asof": ctx["asof"],
            "ret5": ctx.get("ret5"), "ret20": ctx.get("ret20"),
            "rsi14": ctx.get("rsi14"), "vol20": ctx.get("vol20_ann"),
            "vol_pct": ctx.get("vol_pct"), "dd20": (ctx.get("features") or {}).get("dd20"),
            "lo95": ctx.get("lo95"), "hi95": ctx.get("hi95"),
            "var_n": (ctx.get("var7") or {}).get("n"),
            "p_up": p_up, "direction": direction, "label": label,
            "quant_p_up": q_p, "deviation": p_up - q_p,
            "converged": bool(sig.get("converged")),
            "summary": sig.get("summary") or "", "drivers": sig.get("drivers") or [],
            "risks": sig.get("risks") or [],
            "support": sig.get("support"), "resistance": sig.get("resistance"),
            "backtest": q.get("backtest"), "self_check": q.get("self_check"),
        })
    crosses = [c for c in (merged.get(c2["symbol"], {}).get("cross_note")
                           for c2 in contexts) if c]
    engine_label = (f"大模型 · {config.get('model')}" if engine == "llm"
                    else "量化规则（无大模型 Key 或调用失败已降级）")
    offered = int(notes.get("texts_offered") or 0)
    traced = int(notes.get("texts_traced") or 0)
    grounded = (f"{traced}/{offered}" if (engine == "llm" and offered)
                else ("—" if engine == "quant" else "0/0"))
    is_today = any(t["asof"] == now.strftime("%Y-%m-%d") for t in out_targets)
    return {
        "available": True,
        "asof": contexts[0]["asof"],
        "horizon": HORIZON,
        "engine": engine,
        "engine_label": engine_label,
        "llm_model": config.get("model") if engine == "llm" else None,
        "llm_reason": "" if engine == "llm" else str(llm_error or "未配置大模型 API Key"),
        "targets": out_targets,
        "journal": stats,
        "notes": notes,
        "grounded": grounded,
        "cross_note": crosses[0] if crosses else "",
        "missing": reason,
        "is_today": bool(is_today),
        "method": (f"量化基准（扩张基准率 + 20日特征最近邻，s+{HORIZON}≤t 已结算锚点）"
                   + (" + 大模型合成（概率收敛 + 数字溯源）" if engine == "llm" else "")),
    }
