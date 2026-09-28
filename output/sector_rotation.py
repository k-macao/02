"""中国行业指数周度评分 / 月度纯多头轮动（东方财富行业板块指数）。

每次展示截至最近完整收盘日的全行业评分；持仓仅在新月份首次成功运行时
更新（首次启用为建仓，并非回填月初）。纯规则研究口径，不含交易成本或收益承诺。
"""
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
STATE_FILE = os.path.join(os.path.dirname(__file__), "news_history.json")
MIN_WEEKS = 12


def _finite(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def fetch_universe(fetch_json):
    """抓取完整行业板块列表，不只取涨幅榜前五。"""
    data = fetch_json(LIST_URL, params={"pn": "1", "pz": "500", "po": "1", "np": "1",
                                        "fltt": "2", "invt": "2", "fid": "f12", "fs": "m:90+t:2",
                                        "fields": "f12,f14"}, timeout=15)
    root = (data or {}).get("data") or {}
    diff = root.get("diff") or []
    if isinstance(diff, dict):
        diff = list(diff.values())
    if not isinstance(diff, list) or not diff or int(root.get("total") or len(diff)) > len(diff):
        return []  # 分页/不完整列表绝不冒充全行业
    return sorted({str(it["f12"]): str(it["f14"]).strip() for it in diff
                   if isinstance(it, dict) and it.get("f12") and it.get("f14")}.items())


def fetch_closes(fetch_json, code):
    data = fetch_json(KLINE_URL, params={"secid": "90." + code, "klt": "101", "fqt": "1",
                                          "lmt": "180", "end": "20500101",
                                          "fields1": "f1,f2,f3,f4,f5,f6",
                                          "fields2": "f51,f52,f53,f54,f55,f56"}, timeout=15)
    raw = ((data or {}).get("data") or {}).get("klines") or []
    rows = {}
    for line in raw:
        parts = str(line).split(",")
        if len(parts) < 3:
            continue
        try:
            d = datetime.strptime(parts[0], "%Y-%m-%d").date().isoformat()
        except ValueError:
            continue
        close = _finite(parts[2])
        if close is not None and close > 0:
            rows[d] = close
    return sorted(rows.items())


def score_sector(code, name, bars, asof):
    """截至 asof 的 5 日收益；前 12 个不重叠已结算 5 日窗口算胜率与赔率。"""
    valid = [(d, _finite(c)) for d, c in bars if d <= asof]
    valid = [(d, c) for d, c in valid if c is not None and c > 0]
    if len(valid) < 5 * (MIN_WEEKS + 1) + 1 or valid[-1][0] != asof:
        return None
    closes = [c for _, c in valid]
    end = len(closes) - 1
    week_return = closes[end] / closes[end - 5] - 1
    # 训练窗口截止于当前 5 日之前；当前一周不参与历史胜率估计。
    returns = [closes[end - 5 - 5 * j] / closes[end - 10 - 5 * j] - 1
               for j in range(MIN_WEEKS)]
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    # 无赢或无亏时赔率没有定义：不以零或无穷伪装为正常赔率。
    if not wins or not losses:
        return None
    win_rate = len(wins) / MIN_WEEKS
    odds = (sum(wins) / len(wins)) / (-sum(losses) / len(losses))
    odds_score = odds / (1 + odds)  # 单调有界 0~1，避免极端赔率主导
    composite = 100 * (0.8 * win_rate + 0.2 * odds_score)
    return {"code": code, "name": name, "asof": asof, "week_return": week_return,
            "win_rate": win_rate, "odds": odds, "score": composite, "weeks": MIN_WEEKS}


def build_scores(series, asof):
    scores = [score_sector(code, name, bars, asof) for code, name, bars in series]
    return sorted((s for s in scores if s), key=lambda s: (-s["score"], s["code"]))


def allocate(scores):
    """前五权重与综合得分成正比；不得做空或虚构不满五只的组合。"""
    if len(scores) < 5:
        return []
    top = scores[:5]
    total = sum(s["score"] for s in top)
    if total <= 0:
        return []
    return [{"code": s["code"], "name": s["name"], "score": s["score"],
             "weight": s["score"] / total} for s in top]


def monthly_holdings(scores, asof, path=STATE_FILE):
    """同一月保留原持仓；先原子写入新月快照再返回。失败则不冒充调仓成功。"""
    month = asof[:7]
    try:
        with open(path, encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    previous.setdefault("version", 1)
    previous.setdefault("items", [])
    saved = previous.get("sector_rotation") or {}
    if len(saved.get("holdings") or []) == 5 and saved.get("month", "") >= month:
        return saved
    holdings = allocate(scores)
    if not holdings:
        return None
    state = {"month": month, "rebalance_date": asof, "holdings": holdings}
    previous["sector_rotation"] = state
    temp = path + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(previous, f, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return state


def run(fetch_json, *, state_path=STATE_FILE, now=None):
    """只有足够且同步的完整收盘数据才产出栏目；单行业失败只剔除该行业。"""
    now = now or datetime.now(CST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CST)
    today = now.astimezone(CST).date()
    universe = fetch_universe(fetch_json)
    if len(universe) < 5:
        return {"available": False, "reason": "行业列表不完整"}
    series = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(fetch_closes, fetch_json, code): (code, name) for code, name in universe}
        local_now = now.astimezone(CST)
        cutoff = today if (local_now.hour, local_now.minute) >= (15, 30) else today - timedelta(days=1)
        for job in as_completed(jobs):
            code, name = jobs[job]
            try:
                bars = job.result()
                # 当天盘中不含当日未收盘 K 线（北京时间 15:30 后视为完整）。
                bars = [(d, c) for d, c in bars if d <= cutoff.isoformat()]
                if bars:
                    series.append((code, name, bars))
            except Exception:
                continue
    if len(series) < 5:
        return {"available": False, "reason": "可用行业日线不足五个"}
    # 取各行业最后收盘日的众数，避免不同日期价格混用；允许个别行业缺失。
    dates = [bars[-1][0] for _, _, bars in series]
    asof = sorted(set(dates), key=lambda d: (-dates.count(d), d))[0]
    if (today - datetime.strptime(asof, "%Y-%m-%d").date()).days > 14:
        return {"available": False, "reason": "行业日线已过期"}
    scores = build_scores(series, asof)
    if len(scores) < 5:
        return {"available": False, "reason": "有效历史周样本不足五个行业"}
    try:
        state = monthly_holdings(scores, asof, state_path)
    except OSError as exc:
        return {"available": False, "reason": f"月度持仓无法存档：{exc}"}
    return {"available": True, "asof": asof, "scores": scores, "state": state,
            "universe_count": len(universe), "scored_count": len(scores)}
