"""行业轮动因果性、月度持仓与日报拼版离线回归。"""
import os
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "output"))
import sector_rotation as sr
import types
sys.modules.setdefault("requests", types.SimpleNamespace())
import pipeline


class SectorRotationTests(unittest.TestCase):
    def setUp(self):
        self.bars = [(f"2026-06-{d:02d}", 100 + d) for d in range(1, 31)]
        # 生成足量连续交易日样本
        start = datetime(2026, 1, 1)
        self.bars = [((start + timedelta(days=i)).strftime("%Y-%m-%d"),
                      100 * (1.01 if i % 9 < 5 else 0.98) ** i)
                     for i in range(150)]
        self.asof = self.bars[-1][0]

    def test_score_causal_and_formula(self):
        s = sr.score_sector("BK1", "甲", self.bars, self.asof)
        self.assertIsNotNone(s)
        self.assertEqual(s, sr.score_sector("BK1", "甲", self.bars + [("2027-01-01", 100000)], self.asof))
        self.assertAlmostEqual(s["score"], 100 * (.8 * s["win_rate"] + .2 * s["odds"] / (1 + s["odds"])))
        self.assertIsNone(sr.score_sector("BK1", "甲", self.bars[:15], self.bars[14][0]))

    def test_top_five_weighted_and_monthly_lock(self):
        scores = [{"code": str(i), "name": f"行业{i}", "score": 80 - i} for i in range(7)]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "holdings.json")
            first = sr.monthly_holdings(scores, "2026-09-03", path)
            self.assertEqual(len(first["holdings"]), 5)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["sector_rotation"], first)
            self.assertAlmostEqual(sum(h["weight"] for h in first["holdings"]), 1)
            self.assertTrue(all(h["weight"] > 0 for h in first["holdings"]))
            reversed_scores = list(reversed(scores))
            self.assertEqual(sr.monthly_holdings(reversed_scores, "2026-09-29", path), first)
            self.assertNotEqual(sr.monthly_holdings(reversed_scores, "2026-10-01", path)["holdings"], first["holdings"])

    def test_incomplete_universe_and_missing_data_hide_section(self):
        # 用临时存档：run() 会把诊断写进存档，不能污染仓库里的 output/news_history.json
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sr, "fetch_universe", return_value=[]):
                res = sr.run(lambda *a, **kw: None,
                             state_path=os.path.join(tmp, "news_history.json"))
            self.assertFalse(res["available"])
        html = pipeline.generate_report({"行业轮动": pipeline._source_result(
            "fake", "unavailable", result={"available": False})}, "2026年9月28日", "20260928")
        self.assertNotIn("SECTOR ROTATION", html)

    def test_report_section(self):
        scores = sr.build_scores([(str(i), f"行业{i}", self.bars) for i in range(6)], self.asof)
        state = {"month": "2026-05", "rebalance_date": self.asof, "holdings": sr.allocate(scores)}
        result = {"available": True, "asof": self.asof, "scores": scores,
                  "state": state, "scored_count": 6, "universe_count": 6}
        src = pipeline._source_result("东方财富", "success", result=result)
        html = pipeline.generate_report({"行业轮动": src}, "2026年5月30日", "20260530")
        self.assertIn("每日量化策略（行业轮动）", html)
        self.assertIn("目标权重", html)
        self.assertIn("80%", html)


if __name__ == "__main__":
    unittest.main()
