#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📅 每周量化走势预测 —— 未来一周（5 个交易日）港股升跌方向与概率（无未来函数）。

方法学来源（GitHub 公开量化工程实践调研，2026-09-28）：

  · akfamily/akquant（AKQuant · docs/zh/advanced/ml.md）
      防未来函数教义：特征 X 只能用 t 及之前；标签 y 描述 t 之后；预处理统计量
      （均值/方差）不得来自全样本，必须滚动 / 扩张因果计算。
  · arielb57/peekahead（黑箱前视偏差检测器）
      核心不变量「截断不变性」：输出 ≤ t 的行只依赖输入 ≤ t 的行——删掉 / 扰动 t
      之后的数据，过去时刻的输出必须逐位不变。本模块把该检测做成运行时自检
      （check_no_lookahead），自检不过整栏降级，绝不产出预测。
  · paidaxing1234/quant-backtest-guard（回测照妖镜）
      未来函数 / 标签泄漏为致命项：不用 close[i+1] 预测 close[i]、不做全样本
      z-score 归一化、信号不得在未收盘前生效。
  · haeganm/walkforward（purged / embargo walk-forward splits）
      相似样本（类比锚点）的标签必须在预测时点之前全部结算：锚点 s 需满足 s+H ≤ t。
  · k-macao/03 PR #54「AI 预测 · 未来函数」栏目（同组织姊妹仓）
      四条硬约束：①输入闭合（只读当次快照）②目标日在严格之后（不成立即整栏降级）
      ③先存档后结算（先落盘 settled=False，后续按真实行情回填）④零写死叙事；
      结算样本 <10 只报样本量，不下命中率结论。
  · 本仓库 output/octopus_quant/probability.py：推进式（walk-forward）回测与概率夹逼。

预测器（三条腿，纯确定性规则，无随机数、不调外部模型、纯标准库）：
  1. 历史基准 P0 —— 过去已结算周度涨跌的拉普拉斯平滑频率（只数 s+H ≤ t 的标签）；
  2. 相似样本 P_sim —— 当前 20 日特征（逐期扩张 z 标准化，绝不全样本归一）在已结算
     锚点里取 K=8 最近邻，其周度方向的拉普拉斯平滑频率；
  3. 合成 P = (P0 + P_sim) / 2，夹在 5%~95%；已结算锚点 <4 个时退化为 P0 并如实标注。

留痕与结算：预测先写入 output/weekly_forecast.json（settled=False），满 5 个交易日
后按真实收盘回填实际涨跌与命中——当次运行结构上不可能结算当次预测。

对外入口：run_weekly(fetch_json, history_path=...)；任一步失败都返回
available=False + 原因，由上层决定整栏缺席（绝不编造数据）。
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

# ---- 口径常量（写死可复现；改任何一条都会改变预测，必须同步测试）----
WINDOW = 20            # 特征窗口（交易日）
HORIZON = 5            # 预测视界 = 未来一周（5 个交易日）
ANALOG_K = 8           # 相似样本（最近邻）个数
MIN_ANALOGS = 4         # 相似样本退化阈值：不足则只用历史基准
MIN_RESOLVED = 30      # 历史基准最少已结算周数（不足则不产出信号）
MIN_BARS = 60          # 最少日线根数（≈ WINDOW + HORIZON + MIN_RESOLVED + 余量）
PROB_FLOOR = 0.05      # 概率硬边界：统计模型永远保留被证伪的余地
PROB_CAP = 0.95
DIR_UP = 0.58          # 展示方向阈值（结算一律按 P ≥ 0.5 的底牌方向）
DIR_DOWN = 0.42
JOURNAL_FILENAME = "weekly_forecast.json"
JOURNAL_MAX_ENTRIES = 40
FEATURE_KEYS = ("ret5", "ret10", "ret20", "vol20", "dd20")

# 可展示的指数别名（不写死任何具体日期 / 点位叙事）
_SYMBOL_LABELS = {
    "^HSI": "恒生指数",
    "^HSTECH": "恒生科技",
    "^HSCEI": "国企指数",
}


# ============================================================
# 基础工具（纯函数，可离线单测）
# ============================================================
def _clamp(p):
    return max(PROB_FLOOR, min(PROB_CAP, float(p)))


def _pstdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    mu = sum(xs) / n
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / n)


def _features(closes, t):
    """t 时刻（含）之前的窗口特征 —— 只读 closes[0..t]，无未来数据。"""
    c0 = closes[t]

    def _ret(k):
        prev = closes[t - k]
        return (c0 / prev - 1.0) if prev > 0 else 0.0

    w = closes[t - WINDOW + 1:t + 1]
    rets = [w[i] / w[i - 1] - 1.0 for i in range(1, len(w)) if w[i - 1] > 0]
    peak = max(w)
    return {
        "ret5": _ret(5),
        "ret10": _ret(10),
        "ret20": _ret(WINDOW),
        "vol20": _pstdev(rets),
        "dd20": (c0 / peak - 1.0) if peak > 0 else 0.0,
    }


def _dist2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _weekly_label(p_up):
    """P(周涨) → (结算方向, 展示文案)。展示可以中性，结算只认 P ≥ 0.5 的底牌。"""
    p_up = _clamp(p_up)
    if p_up >= DIR_UP:
        return "up", f"▲ 看涨 · P(周涨) {p_up * 100:.0f}%"
    if p_up <= DIR_DOWN:
        return "down", f"▼ 看跌 · P(周涨) {p_up * 100:.0f}%"
    lean = "涨" if p_up >= 0.5 else "跌"
    return "neutral", f"■ 中性（略偏{lean}）· P(周涨) {p_up * 100:.0f}%"


# ============================================================
# 信号计算：单向前向扫描，每个 t 的输出只吃 ≤t 的输入（截断不变）
# ============================================================
def compute_signals(closes, horizon=HORIZON):
    """逐期滚动计算每周方向信号（horizon = 预测视界，默认 5 个交易日）。

    返回 {"ok", "reason", "signals", "vol_hist"}：
      signals[t] = None（样本不足）或
      {"p_up", "p_base", "p_sim", "n_analog", "n_resolved", "blended", "features"}

    因果性（每条都被 tests/test_weekly.py 的截断不变性测试锁死）：
      · 特征只用 closes[0..t]；扩张 z 标准化的均值/方差逐期更新（非全样本统计量）；
      · 基准率只数已结算标签：s + horizon ≤ t；
      · 相似锚点同样要求 s + horizon ≤ t（purged/embargo 依据）；
      · 距离只在两侧各自的「当期扩张标准化」坐标里比较，未来行不参与。
    """
    closes = [float(c) for c in (closes or [])]
    n = len(closes)
    if n < MIN_BARS:
        return {"ok": False,
                "reason": f"日线样本不足（{n} < {MIN_BARS} 根）",
                "signals": [], "vol_hist": []}

    # 逐特征 Welford 扩张统计（count, mean, M2）；含当期 t（当期值在 t 时刻可观测）
    wstats = {k: [0, 0.0, 0.0] for k in FEATURE_KEYS}
    z_at = {}              # t → 当期扩张 z 坐标（锚点用自己当期的坐标，绝不借用未来统计量）
    candidates = []        # [(z_s, y_s, s)]：已结算类比锚点，s + HORIZON ≤ 当前 t
    resolved_ys = []       # 全部已结算周度方向标签（历史基准样本）
    vol_hist = []          # 逐期 vol20（因果序列，供扩张分位展示）
    signals = [None] * n

    for t in range(WINDOW, n):
        f = _features(closes, t)
        for k in FEATURE_KEYS:
            m = wstats[k]
            x = f[k]
            m[0] += 1
            delta = x - m[1]
            m[1] += delta / m[0]
            m[2] += delta * (x - m[1])
        z = []
        for k in FEATURE_KEYS:
            m = wstats[k]
            sd = math.sqrt(m[2] / m[0]) if m[0] > 1 else 0.0
            z.append(0.0 if sd < 1e-12 else (f[k] - m[1]) / sd)
        z_t = tuple(z)
        z_at[t] = z_t
        vol_hist.append(f["vol20"])

        # t 推进后，锚点 s = t - horizon 的标签此刻已经结算（严格在先）
        s = t - horizon
        if s >= WINDOW:
            y = 1.0 if closes[s + horizon] > closes[s] else 0.0
            candidates.append((z_at[s], y, s))
            resolved_ys.append(y)

        if len(resolved_ys) < MIN_RESOLVED:
            continue

        # 1) 历史基准：拉普拉斯平滑的已结算周度上涨频率
        n_res = len(resolved_ys)
        p0 = (sum(resolved_ys) + 1.0) / (n_res + 2.0)

        # 2) 相似样本：已结算锚点里取最近的 K 个（距离用两侧各自当期的扩张 z 坐标）
        ranked = sorted(candidates, key=lambda c: _dist2(c[0], z_t))[:ANALOG_K]
        p_sim = None
        blended = False
        n_analog = len(ranked)
        if n_analog >= MIN_ANALOGS:
            up = sum(c[1] for c in ranked)
            p_sim = (up + 1.0) / (n_analog + 2.0)
            p = _clamp((p0 + p_sim) / 2.0)
            blended = True
        else:
            p = _clamp(p0)

        signals[t] = {
            "p_up": p,
            "p_base": _clamp(p0),
            "p_sim": None if p_sim is None else _clamp(p_sim),
            "n_analog": n_analog,
            "n_resolved": n_res,
            "blended": blended,
            "features": f,
        }

    first = next((i for i, s in enumerate(signals) if s), None)
    if first is None:
        return {"ok": False,
                "reason": "已结算周度样本不足（<%d 周）" % MIN_RESOLVED,
                "signals": signals, "vol_hist": vol_hist}
    return {"ok": True, "reason": "", "signals": signals, "vol_hist": vol_hist,
            "first_signal": first}


# ------------------------------------------------------------
# 未来函数自检：peekahead 式截断不变性（运行时执行，不过则整栏降级）
# ------------------------------------------------------------
def check_no_lookahead(closes, cuts=None, horizon=HORIZON):
    """对任意截断点 k，signals[k] 必须逐位不依赖 k 之后的输入。

    返回 (ok, message)。ok=False 时上层必须整栏降级——这是「目标日严格在后」的
    运行时等价物（k-macao/03 PR #54 约束②：assert 不成立不出预测）。
    """
    closes = [float(c) for c in (closes or [])]
    n = len(closes)
    if cuts is None:
        full = compute_signals(closes, horizon=horizon)
        if not full.get("ok"):
            return False, full.get("reason") or "信号不可计算"
        f0 = full.get("first_signal", MIN_BARS - 1)
        k0 = max(f0, MIN_BARS - 1)
        k_mid = k0 + max(0, (n - 1 - k0)) // 2
        cuts = sorted({k0, k_mid, n - 1})
    cuts = list(cuts)
    full = compute_signals(closes, horizon=horizon)
    if not full.get("ok"):
        return False, full.get("reason") or "信号不可计算"
    for k in cuts:
        if k < MIN_BARS - 1 or k >= n:
            return False, f"切点 {k} 越界（需 {MIN_BARS - 1} ≤ k < {n}）"
        trunc = compute_signals(closes[:k + 1], horizon=horizon)
        a = full["signals"][k]
        b = trunc["signals"][k] if trunc.get("ok") else None
        if a is None and b is None:
            continue
        if a is None or b is None:
            return False, f"切点 {k} 信号存在性不一致（截断改变了输出）"
        for key in ("p_up", "p_base", "p_sim", "n_analog", "n_resolved"):
            if a.get(key) != b.get(key):
                return False, f"切点 {k} 的 {key} 被未来数据改变了"
    return True, f"{len(cuts)} 个切点逐位一致"


# ============================================================
# 滚动样本外回测（walk-forward 体检：每步只用 ≤t 的输入打分）
# ============================================================
def _backtest(closes, signals, horizon=HORIZON):
    n = len(closes)
    probs, outs = [], []
    for t, sig in enumerate(signals):
        if not sig or t + horizon >= n:
            continue
        y = 1.0 if closes[t + horizon] > closes[t] else 0.0
        probs.append(sig["p_up"])
        outs.append(y)
    n_bt = len(probs)
    up_rate = (sum(outs) / n_bt) if n_bt else None
    base_hit = max(up_rate, 1.0 - up_rate) if n_bt else None
    result = {"n": n_bt, "hit_rate": None, "base_rate": base_hit,
              "brier": None, "up_rate": up_rate}
    if n_bt < 10:
        # 与 k-macao/03 结算口径一致：样本不足只报样本量，不下命中率结论。
        result["note"] = f"样本不足 10 期（{n_bt} 期），只报样本量"
        return result
    hits = sum(1 for p, y in zip(probs, outs) if (p >= 0.5) == (y >= 0.5))
    brier = sum((p - y) ** 2 for p, y in zip(probs, outs)) / n_bt
    result.update({"hit_rate": hits / n_bt, "brier": brier})
    return result


# ============================================================
# 预测留痕：先存档（settled=False）→ 满 5 个交易日按真实收盘结算
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
        pass  # 留痕写不进去不影响本次预测展示；下次运行再写


def _settle(entries, dates, closes, now=None):
    """结算所有已到龄的预测；返回今日是否有结算事件。

    目标日严格在后（约束②）：结算点 = base + HORIZON 个**交易日**，
    数据里没有这根 K 线就绝不结算——假期顺延由交易日计数自然处理。
    """
    now = now or datetime.now(CST)
    index = {d: i for i, d in enumerate(dates)}
    settled_today = False
    today = now.strftime("%Y-%m-%d")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("settled"):
            continue
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
        # 底牌方向 = 发布时存档的 P ≥ 0.5；展示可以写中性，结算认底牌。
        entry["hit"] = bool((entry.get("p_up") or 0.5) >= 0.5) == (actual > 0)
        if dates[j] == today:
            settled_today = True
    return settled_today


def _issue(sig, dates, closes, now, symbol):
    """按最新一根 K 线签发新预测（结构上只可能发生在结算完成之后）。"""
    i = len(dates) - 1
    f = dict(sig["features"])
    direction, label = _weekly_label(sig["p_up"])
    return {
        "base_date": dates[i],
        "base_close": closes[i],
        "symbol": symbol,
        "symbol_label": _SYMBOL_LABELS.get(symbol, symbol),
        "target_sessions": HORIZON,
        "target_note": "锚定日后第 5 个交易日收盘（按交易日计数，假期顺延）",
        "p_up": sig["p_up"],
        "direction": direction,
        "label": label,
        "p_base": sig["p_base"],
        "p_sim": sig["p_sim"],
        "n_analog": sig["n_analog"],
        "n_resolved": sig["n_resolved"],
        "blended": sig["blended"],
        "factors": {k: f.get(k) for k in FEATURE_KEYS},
        "issued_cst": now.strftime("%Y-%m-%d %H:%M:%S%z"),
        "settled": False,
    }


# ============================================================
# 对外入口
# ============================================================
def run_weekly(fetch_json=None, *, history_path=None, symbol=None, rng="2y", now=None):
    """计算 + 留痕 + 结算；返回供管线消费的结果字典。

    可用时：{"available": True, "entry", "backtest", "journal", "as_of",
             "symbol", "symbol_label", "self_check", "is_today", "vol_pct"}
    不可用：{"available": False, "reason": "..."} —— 由上层整栏缺席。
    """
    from octopus_quant.providers import fetch_bars  # 惰性导入：唯一复用的联网数据层

    symbol = symbol or os.environ.get("OCTOPUS_WEEKLY_SYMBOL", "^HSI")
    now = now or datetime.now(CST)
    today = now.strftime("%Y-%m-%d")

    bars = fetch_bars(fetch_json, symbol, rng=rng) if fetch_json else []
    if len(bars) < MIN_BARS:
        return {"available": False,
                "reason": f"日线样本不足（{len(bars)} < {MIN_BARS} 根）"}

    dates = [b["date"] for b in bars]
    closes = [float(b["close"]) for b in bars]

    # 1) 信号（单向扫描，逐 t 因果）
    computed = compute_signals(closes)
    if not computed.get("ok"):
        return {"available": False, "reason": computed.get("reason") or "信号不可计算"}
    signals = computed["signals"]
    last = signals[-1]
    if not last:
        return {"available": False, "reason": "最新一根 K 线尚无足够已结算周度样本"}

    # 2) 未来函数自检（截断不变性）：不过则整栏降级，绝不出预测
    ok, check_msg = check_no_lookahead(closes)
    if not ok:
        return {"available": False, "reason": f"未来函数自检未通过：{check_msg}"}

    # 3) 滚动样本外体检
    backtest = _backtest(closes, signals)

    # 4) 留痕：先结算历史，再（无未决预测时）签发新预测
    journal = _load_journal(history_path)
    entries = journal.setdefault("entries", [])
    settled_today = _settle(entries, dates, closes, now=now)
    standing = next((e for e in reversed(entries)
                     if isinstance(e, dict) and not e.get("settled")), None)
    changed = settled_today
    if standing is None:
        standing = _issue(last, dates, closes, now, symbol)
        entries.append(standing)
        changed = True
    if changed:
        journal["updated_cst"] = now.strftime("%Y-%m-%d %H:%M:%S%z")
        _save_journal(history_path, journal)

    # 5) 留痕统计（样本 <10 只报样本量）
    settled = [e for e in entries
               if isinstance(e, dict) and e.get("settled")]
    n_settled = len(settled)
    hits = sum(1 for e in settled if e.get("hit"))
    recent = [{"date": e.get("settle_date"),
               "ret": e.get("actual_ret"),
               "hit": bool(e.get("hit"))}
              for e in settled[-3:]]
    journal_stats = {
        "n": n_settled,
        "hit_rate": (hits / n_settled) if n_settled >= 10 else None,
        "hits": hits,
        "recent": recent,
    }

    # 6) 展示用扩张分位（vol20 相对自身过去分位，只用 ≤ 最新一根的数据）
    vol_hist = computed.get("vol_hist") or []
    vol_pct = None
    if len(vol_hist) >= 2:
        past = vol_hist[:-1]
        vol_pct = sum(1 for v in past if v <= vol_hist[-1]) / len(past)

    # is_today：今天有签发或结算事件（预测本身的锚定日可能是最近收盘日）
    is_today = (standing.get("base_date") == today) or any(
        e.get("settle_date") == today for e in settled)

    return {
        "available": True,
        "entry": standing,
        "backtest": backtest,
        "journal": journal_stats,
        "as_of": dates[-1],
        "symbol": symbol,
        "symbol_label": _SYMBOL_LABELS.get(symbol, symbol),
        "self_check": check_msg,
        "vol_pct": vol_pct,
        "is_today": bool(is_today),
        "method": "扩张基准率 + 20日特征最近邻（s+5≤t 已结算锚点）混合",
    }
