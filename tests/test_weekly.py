"""📅 每周量化走势预测离线回归测试（不发任何网络请求）。

核心是两条「防自欺」未来函数测试：
  · 截断不变性（arielb57/peekahead 不变量）：对任意切点 k，signals[k] 只依赖 ≤k 的
    输入——把 k 之后的未来数据删掉 / 扰动，过去时刻的输出必须逐位不变；
  · 结算严格在后（k-macao/03 PR #54 约束②③）：类比锚点标签必须已结算（s+5 ≤ t），
    预测先存档 settled=False，满 5 个交易日才按真实收盘回填，当次运行不可能结算当次。

另覆盖：概率夹逼 5%~95%、基准率独立双记账、回测样本不足只报样本量、
留痕档案 issue→settle→reissue 流转、两主题渲染与栏目顺序、审计与结论接入。
"""
import importlib.util
import json
import math
import random
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# pipeline 在导入时只需要 requests 存在；本测试不发出 HTTP 请求。
sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

import octopus_weekly as w  # noqa: E402
from octopus_quant import providers  # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_weekly_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

CST = timezone(timedelta(hours=8))


def synthetic_closes(n=300, seed=42):
    """确定性随机游走收盘价（无网络、可复现）。"""
    rng = random.Random(seed)
    closes, x = [], 24000.0
    for _ in range(n):
        x *= 1 + rng.gauss(0.0002, 0.011)
        closes.append(x)
    return closes


def weekday_dates(n, start=datetime(2026, 1, 5)):
    dates, d = [], start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return dates


def fake_chart_fetch(closes):
    """伪造 Yahoo chart JSON（fetch_bars 的输入契约），只读给定 closes 序列。"""
    dates = weekday_dates(len(closes))

    def fetch_json(url, params=None, timeout=None):
        stamps = [int(datetime.strptime(dt, "%Y-%m-%d")
                      .replace(hour=8, tzinfo=CST).timestamp()) for dt in dates]
        return {"chart": {"result": [{
            "timestamp": stamps,
            "indicators": {"quote": [{
                "close": list(closes), "open": list(closes),
                "high": list(closes), "low": list(closes),
                "volume": [1] * len(closes),
            }]},
        }]}}

    return fetch_json


class WeeklySignalsLookaheadTests(unittest.TestCase):
    """未来函数（look-ahead）防线：截断不变性 / 扰动不变性 / embargo 双记账。"""

    @classmethod
    def setUpClass(cls):
        cls.closes = synthetic_closes(300, seed=42)
        cls.computed = w.compute_signals(cls.closes)

    def test_constants_lock_the_lookahead_contract(self):
        # 口径常量一旦改动就会改变预测，必须与文档/README 一致
        self.assertEqual(w.HORIZON, 5)       # 未来一周 = 5 个交易日
        self.assertEqual(w.WINDOW, 20)
        self.assertEqual(w.ANALOG_K, 8)
        self.assertEqual(w.MIN_ANALOGS, 4)
        self.assertEqual((w.PROB_FLOOR, w.PROB_CAP), (0.05, 0.95))

    def test_compute_signals_ok_on_sufficient_bars(self):
        self.assertTrue(self.computed["ok"])
        first = self.computed.get("first_signal")
        self.assertIsNotNone(first)
        # 首个信号必须已积累 ≥ MIN_RESOLVED 个已结算周样本（s+5 ≤ t）
        self.assertGreaterEqual(self.computed["signals"][first]["n_resolved"],
                                w.MIN_RESOLVED)

    def test_truncation_invariance(self):
        """peekahead 核心不变量：删掉未来数据，历史输出逐位不变。"""
        full = self.computed
        n = len(self.closes)
        f0 = full["first_signal"]
        k0 = max(f0, w.MIN_BARS - 1)
        cuts = sorted({k0, k0 + (n - 1 - k0) // 2, n - 1})
        for k in cuts:
            trunc = w.compute_signals(self.closes[:k + 1])
            self.assertTrue(trunc["ok"])
            a, b = full["signals"][k], trunc["signals"][k]
            self.assertIsNotNone(a, f"切点 {k} 应有信号")
            self.assertIsNotNone(b, f"切点 {k} 截断后应仍有信号")
            self.assertEqual(a, b, f"切点 {k} 的输出被未来数据改变了")

    def test_future_perturbation_invariance(self):
        """扰动 t 之后的一切（暴涨/腰斩），signals[:t+1] 必须与原序列一致。"""
        k = 200
        mod = self.closes[:k + 1] + [c * (3.14 if i % 2 else 0.13)
                                     for i, c in enumerate(self.closes[k + 1:])]
        a = w.compute_signals(self.closes)
        b = w.compute_signals(mod)
        self.assertEqual(a["signals"][:k + 1], b["signals"][:k + 1])

    def test_base_rate_embargo_double_entry(self):
        """基准率只数 s+5 ≤ t 的已结算标签（独立复算，双记账对账）。"""
        H, W = w.HORIZON, w.WINDOW
        signals = self.computed["signals"]
        for t in (60, 150, 250, len(self.closes) - 1):
            sig = signals[t]
            self.assertIsNotNone(sig, f"t={t} 应有信号")
            ys = [1.0 if self.closes[s + H] > self.closes[s] else 0.0
                  for s in range(W, t - H + 1)]
            p0 = (sum(ys) + 1.0) / (len(ys) + 2.0)
            self.assertEqual(sig["n_resolved"], len(ys), f"t={t} 已结算样本数不一致")
            self.assertAlmostEqual(sig["p_base"], p0, places=12, msg=f"t={t} 基准率不一致")
            # 相似锚点上限：锚点 s 必须满足 s ≤ t - H（标签已结算）
            self.assertLessEqual(sig["n_analog"], w.ANALOG_K)

    def test_probability_bounds_everywhere(self):
        for i, sig in enumerate(self.computed["signals"]):
            if not sig:
                continue
            self.assertGreaterEqual(sig["p_up"], w.PROB_FLOOR, f"t={i}")
            self.assertLessEqual(sig["p_up"], w.PROB_CAP, f"t={i}")
            if sig["p_sim"] is not None:
                self.assertGreaterEqual(sig["p_sim"], w.PROB_FLOOR)
                self.assertLessEqual(sig["p_sim"], w.PROB_CAP)

    def test_deterministic_on_same_input(self):
        a = w.compute_signals(synthetic_closes(200, seed=7))
        b = w.compute_signals(synthetic_closes(200, seed=7))
        self.assertEqual(a["signals"], b["signals"])

    def test_insufficient_bars_degrades_without_signals(self):
        short = w.compute_signals(self.closes[:w.MIN_BARS - 1])
        self.assertFalse(short["ok"])
        self.assertIn("样本不足", short["reason"])

    def test_check_no_lookahead_passes_and_rejects_bad_cut(self):
        ok, msg = w.check_no_lookahead(self.closes)
        self.assertTrue(ok, msg)
        self.assertIn("逐位一致", msg)
        bad_ok, bad_msg = w.check_no_lookahead(self.closes, cuts=[3])
        self.assertFalse(bad_ok)
        self.assertIn("越界", bad_msg)

    def test_backtest_sample_honesty(self):
        bt = w._backtest(self.closes, self.computed["signals"])
        self.assertGreater(bt["n"], 0)
        if bt["hit_rate"] is None:
            # 样本 <10 只报样本量，绝不下命中率结论
            self.assertIn("只报样本量", bt["note"])
            self.assertLess(bt["n"], 10)
        else:
            self.assertGreaterEqual(bt["hit_rate"], 0.0)
            self.assertLessEqual(bt["hit_rate"], 1.0)
            self.assertGreaterEqual(bt["brier"], 0.0)
            self.assertLessEqual(bt["brier"], 1.0)
            self.assertTrue(0 < bt["base_rate"] <= 1)


class WeeklyJournalSettleTests(unittest.TestCase):
    """先存档后结算：issue → 满 5 个交易日 settle → 再 issue 的档案流转。"""

    def _run(self, closes, history_path, now):
        return w.run_weekly(fake_chart_fetch(closes), history_path=history_path, now=now)

    def test_issue_settle_reissue_flow(self):
        base = synthetic_closes(300, seed=11)[:75]
        with tempfile.TemporaryDirectory() as td:
            hp = str(Path(td) / "weekly_forecast.json")
            now1 = datetime(2026, 4, 10, 9, 0, tzinfo=CST)
            r1 = self._run(base, hp, now1)
            self.assertTrue(r1["available"])
            with open(hp, encoding="utf-8") as fh:
                journal = json.load(fh)
            self.assertEqual(len(journal["entries"]), 1)
            e0 = journal["entries"][0]
            self.assertFalse(e0["settled"])              # ③ 先存档 settled=False
            self.assertEqual(e0["base_date"], weekday_dates(75)[-1])
            self.assertGreaterEqual(e0["p_up"], w.PROB_FLOOR)
            self.assertLessEqual(e0["p_up"], w.PROB_CAP)

            # 不足 5 个交易日：即使重跑也绝不结算（目标日在严格之后）
            r_mid = self._run(base, hp, now1)
            self.assertTrue(r_mid["available"])
            with open(hp, encoding="utf-8") as fh:
                journal = json.load(fh)
            self.assertEqual(len(journal["entries"]), 1)
            self.assertFalse(journal["entries"][0]["settled"])

            # 长出 5 根 K 线 → 按真实收盘结算，同一次运行里再签发新预测
            grown = synthetic_closes(300, seed=11)[:80]
            now2 = datetime(2026, 4, 17, 9, 0, tzinfo=CST)
            r2 = self._run(grown, hp, now2)
            self.assertTrue(r2["available"])
            with open(hp, encoding="utf-8") as fh:
                journal = json.load(fh)
            self.assertEqual(len(journal["entries"]), 2)
            e0, e1 = journal["entries"]
            self.assertTrue(e0["settled"])
            self.assertEqual(e0["settle_date"], weekday_dates(80)[-1])
            # 结算内容 = 真实收盘价差与底牌方向的命中判定（独立复算对账）
            actual = grown[-1] / grown[74] - 1.0
            self.assertAlmostEqual(e0["actual_ret"], actual, places=12)
            self.assertEqual(e0["hit"], bool((e0["p_up"] >= 0.5) == (actual > 0)))
            # 当次运行不可能结算当次预测：新签发的第二条必为未结算
            self.assertFalse(e1["settled"])
            self.assertEqual(e1["base_date"], weekday_dates(80)[-1])
            # 留痕统计：样本 <10 不下命中率结论
            self.assertEqual(r2["journal"]["n"], 1)
            self.assertIsNone(r2["journal"]["hit_rate"])
            self.assertGreaterEqual(r2["journal"]["hits"], 0)

    def test_unavailable_when_fetch_fails_or_bars_short(self):
        with tempfile.TemporaryDirectory() as td:
            hp = str(Path(td) / "wf.json")
            res = w.run_weekly(lambda *a, **k: None, history_path=hp)
            self.assertFalse(res["available"])
            self.assertIn("样本不足", res["reason"])
            res2 = w.run_weekly(None, history_path=hp)
            self.assertFalse(res2["available"])
            # 无数据时绝不写档案（不造假）
            self.assertFalse(Path(hp).exists())

    def test_run_weekly_self_check_reported(self):
        closes = synthetic_closes(300, seed=3)
        with tempfile.TemporaryDirectory() as td:
            hp = str(Path(td) / "wf.json")
            res = w.run_weekly(fake_chart_fetch(closes), history_path=hp,
                               now=datetime(2026, 5, 8, 9, 0, tzinfo=CST))
            self.assertTrue(res["available"])
            self.assertIn("逐位一致", res["self_check"])
            self.assertIn("entry", res)
            self.assertIn("backtest", res)


class WeeklyPipelineIntegrationTests(unittest.TestCase):
    """管线接入：fetch 降级 / 栏目渲染 / 顺序 / 审计 / 今日结论。"""

    def _result(self):
        closes = synthetic_closes(300, seed=5)[:75]
        with tempfile.TemporaryDirectory() as td:
            hp = str(Path(td) / "wf.json")
            return w.run_weekly(fake_chart_fetch(closes), history_path=hp,
                                now=datetime(2026, 4, 10, 9, 0, tzinfo=CST))

    def _source(self, res=None):
        res = res if res is not None else self._result()
        return {"source": "每周量化走势预测", "status": "success",
                "fetched_at": "2026-04-10 09:00:00",
                "is_today": True, "content_date": res.get("as_of"),
                "result": res}

    def test_fetch_weekly_forecast_switch_and_degradation(self):
        # 关闭开关 → unavailable，不调用引擎
        with patch.object(pipeline, "WEEKLY_ENABLED", False):
            res = pipeline.fetch_weekly_forecast()
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("关闭", res["error"])
        # 引擎异常 → 单源降级，不影响其它栏目
        with patch.object(pipeline, "_weekly") as fake:
            fake.run_weekly.side_effect = ValueError("boom")
            res = pipeline.fetch_weekly_forecast()
        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(res["error"], "boom")
        # 样本不足 → unavailable + 原因
        with patch.object(pipeline, "_weekly") as fake:
            fake.run_weekly.return_value = {"available": False, "reason": "日线样本不足"}
            res = pipeline.fetch_weekly_forecast()
        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(res["error"], "日线样本不足")

    def test_section_order_lock(self):
        order = pipeline.REPORT_SECTION_ORDER
        self.assertIn("WEEKLY FORECAST", order)
        self.assertLess(order.index("LIQUIDITY FLOW"), order.index("WEEKLY FORECAST"))
        # 2026-09-30 起「行情速览」+「全球大盘全景复盘」合并为 MARKET REVIEW 一栏
        self.assertLess(order.index("WEEKLY FORECAST"), order.index("MARKET REVIEW"))
        self.assertLess(order.index("WEEKLY FORECAST"), order.index("SUMMARY"))

    def test_render_section_in_both_themes(self):
        source = self._source()
        data = {"每周走势预测": source}
        date_display = "2026年4月10日 · 周五"
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(data, date_display, "20260410", theme=theme)
            self.assertIn(pipeline.SECTION_TITLE_WEEKLY_FORECAST, html, theme)
            self.assertIn("无未来函数口径", html, theme)
            self.assertIn("截断不变性自检通过", html, theme)
            self.assertIn("先存档后结算", html, theme)
            # 审计口径：元数据总源数含每周预测（9 个基础源 + 每周走势预测 = 10）
            self.assertIn('octopus-total-sources" content="9"', html, theme)
            # 栏目副标题 = 来源名（_short_source）：数据源名不随栏目标题改名（2026-09-29）
            self.assertIn("每周量化走势预测", html, theme)
            self.assertGreaterEqual(
                html.count(pipeline.SECTION_TITLE_WEEKLY_FORECAST), 1, theme)
            # 今日结论携带周度预测（页首优先级）
            self.assertIn("周度预测", html, theme)
            if theme == "pixel":
                self.assertIn("WEEKLY FORECAST", html)

    def test_render_absent_when_unavailable(self):
        data = {"每周走势预测": {"source": "每周量化走势预测", "status": "unavailable",
                                "is_today": False, "content_date": None,
                                "error": "日线样本不足"}}
        html = pipeline.generate_report(data, "2026年4月10日 · 周五", "20260410")
        self.assertNotIn("每周量化走势预测</h2>", html)
        self.assertNotIn(f"{pipeline.SECTION_TITLE_WEEKLY_FORECAST}</h2>", html)
        self.assertNotIn("周度预测", html)

    def test_weekly_section_before_market_snapshot_in_html(self):
        data = {"每周走势预测": self._source(),
                "实时行情": {"source": "行情", "status": "success", "is_today": True,
                             "content_date": "2026-04-10",
                             "quotes": {"恒生指数": {"price": 24600, "change_pct": 0.38}}}}
        html = pipeline.generate_report(data, "2026年4月10日 · 周五", "20260410")
        # 页首「AI 全篇速览」会先提到各栏目标题，因此用栏目 kicker（只在正文栏目头出现）定位顺序
        # 归藏简洁排版（2026-09-29 起）栏目头写作「07 · WEEKLY FORECAST」，编号在前
        i_wk = html.find("· WEEKLY FORECAST<")
        i_mk = html.find("· MARKET REVIEW<")
        self.assertGreater(i_wk, -1)
        self.assertGreater(i_mk, -1)
        self.assertLess(i_wk, i_mk)

    def test_collect_report_parts_counts_weekly_source(self):
        parts = pipeline._collect_report_parts({"每周走势预测": self._source()},
                                               pipeline.GUIZANG_KIT, date_str="20260410")
        # 8 个基础数据源 + 每周走势预测 = 9（财经日历 / Reddit / 新闻源头本次缺席）
        self.assertEqual(parts["total"], 9)
        self.assertEqual(parts["today_n"], 1)
        kickers = [s[0] for s in parts["sections"]]
        self.assertIn("WEEKLY FORECAST", kickers)
        # 审计状态表渲染出每周预测的审计标签（与港股量化引擎并列）
        footer = pipeline._status_footer([
            ("港股量化引擎", {"status": "success", "is_today": True,
                              "fetched_at": "2026-04-10 09:00:00"}),
            ("每周量化走势预测（恒指·5交易日）", self._source()),
        ])
        self.assertIn("每周量化走势预测（恒指·5交易日）", footer)
        self.assertIn("港股量化引擎", footer)


if __name__ == "__main__":
    unittest.main()
