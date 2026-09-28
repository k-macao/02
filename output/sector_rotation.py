"""中国行业指数周度评分 / 月度纯多头轮动（东方财富行业板块指数）。

每次展示截至最近完整收盘日的全行业评分；持仓仅在新月份首次成功运行时
更新（首次启用为建仓，并非回填月初）。纯规则研究口径，不含交易成本或收益承诺。

取数与判死口径（任一环节不达标 → 整栏缺席，并记录原因，绝不补造行情）：
  1. 完整行业列表：按页抓取（每页 100），列表不完整 = 未取到全行业；
  2. 行业日 K：板块指数在「前复权 / 不复权」两种口径下可用性不同，先用一个
     样本行业探测能返回数据的口径，再按该口径取全部行业；样本行业两种口径
     都取不到 → 判定接口不可用，不再对余下行业逐个重试（避免拖垮每日任务）；
  3. 锚点日：各行业最后收盘日的众数，且必须落在最近完整收盘日（北京时间
     15:30 前视为前一日收盘），超过 14 个自然日视为过期；
  4. 评分：需 ≥66 根日线（当前 5 日 + 12 个不重叠 5 日窗口），零赢或零亏的
     行业不评分；有效行业 <5 个 → 整栏缺席；
  5. 月度持仓：写入存档失败同样整栏缺席（不冒充调仓成功）。

每次运行（成功或失败）都把诊断写入存档的 `sector_rotation_diag` 字段，日报
据此在日志里点名失败原因；该存档（news_history.json）由自动/手动工作流随日报
提交，便于隔日核查「栏目为什么缺席」。
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
# 行业列表逐页抓取：单页 100，最多 6 页（行业板块约 86 个，留足余量）。
LIST_PAGE_SIZE = 100
LIST_MAX_PAGES = 6
# 日 K 复权口径候选：先试前复权，再试不复权（板块指数两种口径可用性不同）。
FQT_CANDIDATES = ("1", "0")
# 东财行情接口按来源页校验，带上 Referer 更接近站点真实请求。
EM_HEADERS = {"Referer": "https://quote.eastmoney.com/"}


def _finite(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def _get_json(fetch_json, url, params, timeout=15, headers=None):
    """调用注入的取数函数；老版取数函数不接受 headers 时自动降级。"""
    if headers is None:
        return fetch_json(url, params=params, timeout=timeout)
    try:
        return fetch_json(url, params=params, timeout=timeout, headers=headers)
    except TypeError:
        return fetch_json(url, params=params, timeout=timeout)


def fetch_universe(fetch_json):
    """逐页抓取完整行业板块列表，不只取涨幅榜前五。

    任一一页取不到数据、或已知总数大于抓到的条数 → 返回空列表：
    不完整的列表绝不能冒充全行业（持仓会因此偏向抓到的那几个行业）。
    """
    collected = {}
    total = None
    for page in range(1, LIST_MAX_PAGES + 1):
        data = _get_json(fetch_json, LIST_URL,
                         {"pn": str(page), "pz": str(LIST_PAGE_SIZE), "po": "1", "np": "1",
                          "fltt": "2", "invt": "2", "fid": "f12", "fs": "m:90+t:2",
                          "fields": "f12,f14"}, timeout=15, headers=EM_HEADERS)
        root = (data or {}).get("data") or {}
        diff = root.get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        if not isinstance(diff, list) or not diff:
            return []          # 首页空=接口不可用/参数被拒；中间页空=列表不完整
        for it in diff:
            if isinstance(it, dict) and it.get("f12") and it.get("f14"):
                collected[str(it["f12"])] = str(it["f14"]).strip()
        raw_total = root.get("total")
        if raw_total not in (None, "", "-"):
            try:
                total = int(raw_total)
            except (TypeError, ValueError):
                total = None
        if total is not None and len(collected) >= total:
            break
    if total is not None and len(collected) < total:
        return []              # 抓到的条数少于接口声明的总数 → 判定列表不完整
    return sorted(collected.items())


def fetch_closes(fetch_json, code, fqt="1"):
    """单个板块指数的前复权日线（date, close）列表；取不到返回空列表。"""
    data = _get_json(fetch_json, KLINE_URL,
                     {"secid": "90." + code, "klt": "101", "fqt": fqt,
                      "lmt": "180", "end": "20500101",
                      "fields1": "f1,f2,f3,f4,f5,f6",
                      "fields2": "f51,f52,f53,f54,f55,f56"},
                     timeout=15, headers=EM_HEADERS)
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


def negotiate_fqt(fetch_json, samples):
    """用 1~2 个样本行业确定能返回日线的复权口径，返回 (fqt, 样本日线)。

    样本行业在两种口径下都取不到数据 → 返回 (None, [])：判定接口不可用，
    不再对余下 80+ 个行业逐个重试（否则网络异常时会把每日任务拖到超时）。
    """
    for code, _name in samples:
        for fqt in FQT_CANDIDATES:
            bars = fetch_closes(fetch_json, code, fqt=fqt)
            if bars:
                return fqt, bars
    return None, []


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


def _load_state(path):
    try:
        with open(path, encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, ValueError):
        previous = {}
    if not isinstance(previous, dict):
        previous = {}
    previous.setdefault("version", 1)
    previous.setdefault("items", [])
    return previous


def _persist(path, mutate):
    """读-改-写存档（原子替换），保持 items 等其它字段不被覆盖。"""
    previous = _load_state(path)
    mutate(previous)
    temp = path + ".tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(previous, f, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def save_diag(path, diag):
    """把本次运行的诊断写进存档，便于隔日核查栏目缺席原因（失败也写）。"""
    try:
        def _set(state):
            state["sector_rotation_diag"] = diag
        _persist(path, _set)
    except OSError:
        pass                   # 诊断写不进去不影响本次日报


def monthly_holdings(scores, asof, path=None):
    """同一月保留原持仓；先原子写入新月快照再返回。失败则不冒充调仓成功。"""
    path = path or STATE_FILE
    month = asof[:7]
    previous = _load_state(path)
    saved = previous.get("sector_rotation") or {}
    if len(saved.get("holdings") or []) == 5 and saved.get("month", "") >= month:
        return saved
    holdings = allocate(scores)
    if not holdings:
        return None
    state = {"month": month, "rebalance_date": asof, "holdings": holdings}
    previous["sector_rotation"] = state

    def _set(target):
        target["sector_rotation"] = state
    _persist(path, _set)
    return state


def run(fetch_json, *, state_path=None, now=None):
    """只有足够且同步的完整收盘数据才产出栏目；单行业失败只剔除该行业。

    返回值：成功 {"available": True, ...}；失败 {"available": False,
    "reason": "...", "diag": {...}}。诊断同时落盘到存档的
    ``sector_rotation_diag``，供日报日志与隔日核查使用。

    state_path 缺省用 STATE_FILE（运行时可整体替换，便于离线测试隔离）。
    """
    state_path = state_path or STATE_FILE
    now = now or datetime.now(CST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=CST)
    local_now = now.astimezone(CST)
    today = local_now.date()
    diag = {"ran_at": local_now.strftime("%Y-%m-%d %H:%M:%S"),
            "cutoff": (today if (local_now.hour, local_now.minute) >= (15, 30)
                       else today - timedelta(days=1)).isoformat()}

    def _fail(reason):
        diag["reason"] = reason
        save_diag(state_path, diag)
        return {"available": False, "reason": reason, "diag": diag}

    universe = fetch_universe(fetch_json)
    diag["universe"] = len(universe)
    if len(universe) < 5:
        return _fail(f"行业列表不完整（抓到 {len(universe)} 个，接口未返回完整行业板块列表）")

    fqt, sample_bars = negotiate_fqt(fetch_json, universe[:2])
    diag["fqt"] = fqt
    if not fqt:
        return _fail("行业日K接口未返回数据（前复权/不复权两种口径均无有效日线）")

    series = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {pool.submit(fetch_closes, fetch_json, code, fqt): (code, name)
                for code, name in universe}
        for job in as_completed(jobs):
            code, name = jobs[job]
            try:
                bars = job.result()
                # 当天盘中不含当日未收盘 K 线（北京时间 15:30 后视为完整）。
                bars = [(d, c) for d, c in bars if d <= diag["cutoff"]]
                if bars:
                    series.append((code, name, bars))
            except Exception:
                continue
    diag["kline_series"] = len(series)
    if len(series) < 5:
        return _fail(f"可用行业日线不足五个（{len(series)}/{len(universe)} 个行业取到日线）")
    # 取各行业最后收盘日的众数，避免不同日期价格混用；允许个别行业缺失。
    dates = [bars[-1][0] for _, _, bars in series]
    asof = sorted(set(dates), key=lambda d: (-dates.count(d), d))[0]
    diag["asof"] = asof
    diag["asof_hits"] = dates.count(asof)
    if (today - datetime.strptime(asof, "%Y-%m-%d").date()).days > 14:
        return _fail(f"行业日线已过期（最新共同收盘日 {asof}，距今超过 14 个自然日）")
    scores = build_scores(series, asof)
    diag["scored"] = len(scores)
    if len(scores) < 5:
        return _fail(f"有效历史周样本不足五个行业（{len(scores)}/{len(series)} 个行业满足评分条件）")
    try:
        before = _load_state(state_path).get("sector_rotation") or {}
        state = monthly_holdings(scores, asof, state_path)
    except OSError as exc:
        return _fail(f"月度持仓无法存档：{exc}")
    diag["state"] = "reused" if before and before == state else "built"
    diag["holdings"] = len((state or {}).get("holdings") or [])
    if not state or len(state.get("holdings") or []) != 5:
        return _fail("月度持仓未能生成五只组合（评分或权重计算未通过）")
    save_diag(state_path, diag)
    return {"available": True, "asof": asof, "scores": scores, "state": state,
            "universe_count": len(universe), "scored_count": len(scores),
            "diag": diag}
