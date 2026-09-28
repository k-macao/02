"""行业轮动「能否进推送」的离线回归：取数健壮性 → 判死原因 → 拼版与审计。

沙箱 / CI 都访问不到东方财富，整条链路用可复现的假接口驱动：
既验证「数据正常时栏目一定出现」，也验证「数据异常时原因可追溯、绝不静默」。
"""
import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "output"))
sys.modules.setdefault("requests", types.SimpleNamespace())
import sector_rotation as sr      # noqa: E402
import pipeline                   # noqa: E402

CST = timezone(timedelta(hours=8))


def _trading_days(asof, count):
    """生成以 asof 结尾、跳过周末的 count 个交易日（YYYY-MM-DD）。"""
    end = datetime.strptime(asof, "%Y-%m-%d").date()
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return list(reversed(days))


def _bars(asof, count=90, seed=0.0):
    """构造既有正收益窗口又有负收益窗口的日线（否则赔率无定义，行业不评分）。"""
    dates = _trading_days(asof, count)
    price = 100.0 * (1.0 + seed)
    rows = []
    for i, day in enumerate(dates):
        daily = 0.004 if (i // 5) % 2 == 0 else -0.003
        price *= (1.0 + daily)
        rows.append((day, round(price, 4)))
    return rows


def _kline_payload(bars):
    """按东财 kline 接口字段序拼装：日期,开,收,高,低,量。"""
    klines = []
    for day, close in bars:
        klines.append(f"{day},{close - 1:.4f},{close:.4f},{close + 1:.4f},{close - 2:.4f},100000")
    return {"data": {"code": "BK0001", "klines": klines}}


class FakeAPI:
    """可编排的东方财富假接口：记录每次请求，按 fqt / 页码返回设定好的响应。"""

    def __init__(self, pages=None, bars_by_code=None, empty_fqt=(), accept_headers=True):
        self.pages = pages or []                 # 行业列表逐页响应
        self.bars_by_code = bars_by_code or {}   # 代码 -> [(日期, 收盘)]
        self.empty_fqt = set(empty_fqt)          # 这些复权口径一律返回空日线
        self.accept_headers = accept_headers
        self.calls = []

    def __call__(self, url, params=None, timeout=15, **kwargs):
        params = params or {}
        if not self.accept_headers and "headers" in kwargs:
            raise TypeError("unexpected keyword argument 'headers'")   # 老式取数函数
        self.calls.append((url, dict(params)))
        if "clist" in url:
            page = int(params.get("pn", "1"))
            return self.pages[page - 1] if page <= len(self.pages) else None
        code = params.get("secid", "").split(".", 1)[-1]
        if params.get("fqt") in self.empty_fqt:
            return {"data": {"klines": []}}
        bars = self.bars_by_code.get(code)
        return _kline_payload(bars) if bars else {"data": None}


def _universe_page(codes, total=None):
    return {"data": {"total": total if total is not None else len(codes),
                     "diff": [{"f12": code, "f14": f"行业{code}"} for code in codes]}}


class UniversePaginationTests(unittest.TestCase):
    """完整列表：必须取全，取不全就整栏缺席（绝不用局部行业冒充全行业）。"""

    def test_pages_until_total_reached(self):
        page1 = _universe_page([f"BK{i:03d}" for i in range(100)], total=150)
        page2 = _universe_page([f"BK{i:03d}" for i in range(100, 150)], total=150)
        api = FakeAPI(pages=[page1, page2])
        universe = sr.fetch_universe(api)
        self.assertEqual(len(universe), 150)
        self.assertEqual([p["pn"] for _, p in api.calls], ["1", "2"])

    def test_single_page_short_circuits(self):
        api = FakeAPI(pages=[_universe_page(["BK001", "BK002"], total=2)])
        self.assertEqual(len(sr.fetch_universe(api)), 2)
        self.assertEqual(len(api.calls), 1)

    def test_incomplete_list_returns_empty(self):
        # 接口声称 150 个，第二页却是空的 → 判定不完整
        api = FakeAPI(pages=[_universe_page([f"BK{i:03d}" for i in range(100)], total=150)])
        self.assertEqual(sr.fetch_universe(api), [])
        with patch.object(sr, "fetch_universe", return_value=[]):
            with tempfile.TemporaryDirectory() as tmp:
                res = sr.run(api, state_path=os.path.join(tmp, "s.json"),
                             now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
        self.assertFalse(res["available"])
        self.assertIn("行业列表不完整", res["reason"])

    def test_first_page_empty_returns_empty(self):
        api = FakeAPI(pages=[{"data": None}])
        self.assertEqual(sr.fetch_universe(api), [])


class KlineFetchTests(unittest.TestCase):
    """日线口径自适应：板块指数在前复权 / 不复权下可用性不同，取能返回数据的那个。"""

    def _api(self, asof, empty_fqt=(), accept_headers=True):
        return FakeAPI(
            pages=[_universe_page(["BK001", "BK002", "BK003", "BK004", "BK005"], total=5)],
            bars_by_code={f"BK00{i}": _bars(asof, seed=i / 1000) for i in range(1, 6)},
            empty_fqt=empty_fqt, accept_headers=accept_headers)

    def test_forward_adjusted_default(self):
        asof = "2026-09-25"
        api = self._api(asof)
        with tempfile.TemporaryDirectory() as tmp:
            res = sr.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 25, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["diag"]["fqt"], "1")
        self.assertEqual(res["universe_count"], 5)
        self.assertEqual(res["scored_count"], 5)
        self.assertEqual(len(res["state"]["holdings"]), 5)

    def test_falls_back_to_unadjusted(self):
        asof = "2026-09-25"
        api = self._api(asof, empty_fqt=("1",))
        with tempfile.TemporaryDirectory() as tmp:
            res = sr.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 25, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))
        self.assertEqual(res["diag"]["fqt"], "0")

    def test_both_adjustments_empty_stops_early(self):
        """两种口径都取不到 → 只探测样本行业就停手，不对 80+ 个行业逐个重试。"""
        asof = "2026-09-25"
        api = self._api(asof, empty_fqt=("0", "1"))
        with tempfile.TemporaryDirectory() as tmp:
            res = sr.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 25, 20, 0, tzinfo=CST))
        self.assertFalse(res["available"])
        self.assertIn("行业日K接口未返回数据", res["reason"])
        self.assertEqual(len(api.calls), 1 + 4)      # 1 次列表 + 2 个样本 × 2 种口径

    def test_legacy_fetcher_without_headers_still_works(self):
        asof = "2026-09-25"
        api = self._api(asof, accept_headers=False)
        with tempfile.TemporaryDirectory() as tmp:
            res = sr.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 9, 25, 20, 0, tzinfo=CST))
        self.assertTrue(res["available"], res.get("reason"))

    def test_stale_anchor_rejects_section(self):
        """共同收盘日距今超过 14 天 → 整栏缺席（不用过期锚点冒充当日信号）。"""
        asof = "2026-09-25"
        api = self._api(asof)
        with tempfile.TemporaryDirectory() as tmp:
            res = sr.run(api, state_path=os.path.join(tmp, "s.json"),
                         now=datetime(2026, 10, 20, 20, 0, tzinfo=CST))
        self.assertFalse(res["available"])
        self.assertIn("过期", res["reason"])


class DiagPersistenceTests(unittest.TestCase):
    """诊断落盘：成功与失败都写，且不破坏存档里的其它字段（新闻标题等）。"""

    def test_failure_reason_persisted_without_clobbering_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "news_history.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "items": [{"title": "旧标题", "date": "2026-09-01"}]}, f)
            api = FakeAPI(pages=[{"data": None}])
            res = sr.run(api, state_path=path, now=datetime(2026, 9, 28, 20, 0, tzinfo=CST))
            self.assertFalse(res["available"])
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["items"], [{"title": "旧标题", "date": "2026-09-01"}])
            self.assertIn("行业列表不完整", saved["sector_rotation_diag"]["reason"])
            self.assertIn("ran_at", saved["sector_rotation_diag"])

    def test_success_persists_holdings_and_diag(self):
        asof = "2026-09-25"
        api = FakeAPI(
            pages=[_universe_page(["BK001", "BK002", "BK003", "BK004", "BK005"], total=5)],
            bars_by_code={f"BK00{i}": _bars(asof, seed=i / 1000) for i in range(1, 6)})
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "news_history.json")
            res = sr.run(api, state_path=path, now=datetime(2026, 9, 25, 20, 0, tzinfo=CST))
            self.assertTrue(res["available"], res.get("reason"))
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(len(saved["sector_rotation"]["holdings"]), 5)
            self.assertEqual(saved["sector_rotation"]["month"], "2026-09")
            self.assertEqual(saved["sector_rotation_diag"]["state"], "built")
            # 同月再跑：沿用原持仓，不换仓
            again = sr.run(api, state_path=path, now=datetime(2026, 9, 26, 20, 0, tzinfo=CST))
            self.assertEqual(again["state"]["holdings"], saved["sector_rotation"]["holdings"])
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["sector_rotation_diag"]["state"], "reused")


class PushRenderTests(unittest.TestCase):
    """推送拼版：数据够 → 栏目必现；数据不够 → 审计点名、正文不留空栏。"""

    @staticmethod
    def _source(asof, ok=True):
        if not ok:
            return pipeline._source_result(
                "东方财富 · 中国行业板块指数日线", "unavailable", result={
                    "available": False, "reason": "行业日K接口未返回数据",
                    "diag": {"universe": 86, "fqt": None}})
        bars = {f"BK00{i}": _bars(asof, seed=i / 1000) for i in range(1, 6)}
        scores = sr.build_scores([(c, f"行业{c}", b) for c, b in bars.items()], asof)
        result = {"available": True, "asof": asof, "scores": scores,
                  "scored_count": len(scores), "universe_count": 5,
                  "state": {"month": asof[:7], "rebalance_date": asof,
                            "holdings": sr.allocate(scores)},
                  "diag": {"fqt": "1", "state": "built"}}
        return pipeline._source_result("东方财富 · 中国行业板块指数日线", "success",
                                       is_today=True, content_date=asof, result=result)

    def test_section_rendered_when_available(self):
        html = pipeline.generate_report({"行业轮动": self._source("2026-09-25")},
                                        "2026年9月25日", "20260925")
        self.assertIn("每日量化策略（行业轮动）", html)
        self.assertIn("目标权重", html)
        self.assertIn("80%", html)
        self.assertIn("2026-09-25", html)

    def test_absent_section_named_in_audit_only(self):
        html = pipeline.generate_report({"行业轮动": self._source("2026-09-25", ok=False)},
                                        "2026年9月25日", "20260925")
        self.assertNotIn("SECTOR ROTATION", html)          # 正文不留空栏
        self.assertNotIn("目标权重", html)                  # 也不留半截表格
        self.assertEqual(html.count("每日量化策略（行业轮动）"), 1)
        self.assertIn("每日量化策略（行业轮动）", html.split("数据覆盖")[-1])

    def test_fetch_logs_reason_on_failure(self):
        api = FakeAPI(pages=[{"data": None}])
        buf = io.StringIO()
        with patch.object(pipeline, "safe_request", api), redirect_stdout(buf):
            src = pipeline.fetch_sector_rotation()
        self.assertEqual(src["status"], "unavailable")
        self.assertIn("行业轮动栏目缺席", buf.getvalue())
        self.assertIn("行业列表不完整", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
