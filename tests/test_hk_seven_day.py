"""◈ AI 七日港股走势分析概率离线回归测试（不发任何网络请求）。

覆盖：
  · 量化基准（复用 octopus_weekly 因果引擎、视界 7）：概率夹 5%~95%、截断不变性
    （未来数据不得影响过去输出）、样本不足 → available=False 且带原因；
  · 大模型链路（注入假 post_json）：严格 JSON 解析、概率偏离量化基准 >20pp 收敛、
    数字溯源（编造的数字 / 绝对化措辞 → 该条文案回退量化口径，绝不写进日报）；
  · 留痕：先存档（settled=False）、满 7 个交易日才结算、当次运行不可能结算当次；
  · 管线接入：fetch_hk_seven_day 的 source 结果与审计名、栏目渲染（两主题）、
    无 Key 降级、OCTOPUS_HK7=0 关闭、原「行业轮动」栏目与模块已彻底下线。
"""
import importlib.util
import json
import random
import re
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# pipeline 在导入时只需要 requests 存在；本测试不发出 HTTP 请求。
sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = Path(__file__).parents[1]
OUTPUT_DIR = REPO_ROOT / "output"
if str(OUTPUT_DIR) not in sys.path:
    sys.path.insert(0, str(OUTPUT_DIR))

import hk_seven_day as hk7  # noqa: E402
import octopus_weekly as weekly  # noqa: E402

MODULE_PATH = OUTPUT_DIR / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_hk7_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

CST = timezone(timedelta(hours=8))


def synthetic_closes(n=320, seed=42):
    rng = random.Random(seed)
    closes, x = [], 24500.0
    for _ in range(n):
        x *= 1 + rng.gauss(0.0002, 0.011)
        closes.append(x)
    return closes


def weekday_dates(n, start=date(2025, 1, 6)):
    dates, d = [], start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


def synthetic_bars(n=320, seed=42, start=date(2025, 1, 6)):
    closes = synthetic_closes(n, seed=seed)
    dates = weekday_dates(n, start=start)
    return [{"date": dates[i], "open": c, "high": c * 1.012, "low": c * 0.988,
             "close": c, "volume": 1.2e8} for i, c in enumerate(closes)]


def bars_by_symbol(n=320, seed=42):
    return {"^HSI": synthetic_bars(n, seed=seed),
            "^HSTECH": synthetic_bars(n, seed=seed + 1),
            "^HSCE": synthetic_bars(n, seed=seed + 2)}


def quant_config(**over):
    cfg = {"enabled": False, "key": "", "base": "https://example.invalid/v1",
           "model": "test-model", "timeout": 10, "fallback": True}
    cfg.update(over)
    return cfg


def yahoo_chart_payload(symbol, bars):
    def ts(day_str):
        d = datetime.strptime(day_str, "%Y-%m-%d").replace(hour=16, tzinfo=CST)
        return int(d.timestamp())
    return {"chart": {"result": [{
        "meta": {"symbol": symbol},
        "timestamp": [ts(b["date"]) for b in bars],
        "indicators": {"quote": [{
            "open": [b["open"] for b in bars], "high": [b["high"] for b in bars],
            "low": [b["low"] for b in bars], "close": [b["close"] for b in bars],
            "volume": [b["volume"] for b in bars]}]}}]}}


# ======================================================================
# ① 量化基准 + 因果性
# ======================================================================
class QuantEngineTests(unittest.TestCase):
    def test_horizon_is_seven_trading_days(self):
        self.assertEqual(hk7.HORIZON, 7)

    def test_quant_probability_is_bounded_and_labelled(self):
        closes = synthetic_closes()
        out = hk7.quant_probability(closes)
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["p_up"], hk7.PROB_FLOOR)
        self.assertLessEqual(out["p_up"], hk7.PROB_CAP)
        direction, label = hk7._direction_label(out["p_up"])
        self.assertIn(direction, ("up", "down", "neutral"))
        self.assertIn("P(7日涨)", label)

    def test_short_sample_is_unavailable_with_reason(self):
        res = hk7.run_seven_day(None, bars_by_symbol={"^HSI": synthetic_bars(40)},
                                history_path=None, config=quant_config())
        self.assertFalse(res["available"])
        self.assertIn("日线样本", res["reason"])

    def test_truncation_invariance_of_seven_day_engine(self):
        """截断不变性：删掉 k 之后的数据，signals[k] 必须逐位不变（无未来函数）。"""
        closes = synthetic_closes(280, seed=9)
        full = weekly.compute_signals(closes, horizon=hk7.HORIZON)
        self.assertTrue(full["ok"])
        for k in (80, 150, 230):
            trunc = weekly.compute_signals(closes[:k + 1], horizon=hk7.HORIZON)
            self.assertTrue(trunc["ok"], f"cut={k}")
            a, b = full["signals"][k], trunc["signals"][k]
            for key in ("p_up", "p_base", "p_sim", "n_analog", "n_resolved"):
                self.assertEqual(a.get(key), b.get(key), f"{key} @ {k}")

    def test_run_reports_three_targets_and_journal_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / hk7.JOURNAL_FILENAME
            res = hk7.run_seven_day(None, bars_by_symbol=bars_by_symbol(),
                                    history_path=str(journal), config=quant_config())
            self.assertTrue(res["available"])
            self.assertEqual(res["engine"], "quant")
            self.assertEqual(len(res["targets"]), 3)
            self.assertEqual(res["journal"]["n"], 0)
            self.assertEqual(res["journal"]["standing"], 3)
            saved = json.loads(journal.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["entries"]), 3)
            self.assertTrue(all(e["settled"] is False for e in saved["entries"]))
            # 同一锚定日重复运行：不重复签发
            again = hk7.run_seven_day(None, bars_by_symbol=bars_by_symbol(),
                                      history_path=str(journal), config=quant_config())
            self.assertEqual(again["journal"]["standing"], 3)


# ======================================================================
# ② 留痕：先存档后结算（7 个交易日）
# ======================================================================
class JournalSettleTests(unittest.TestCase):
    def test_settle_only_after_seven_sessions(self):
        bars = synthetic_bars(120, seed=3)
        base_index = 114                       # 之后只有 5 根 K 线 → 还不够 7 个交易日
        series = {"^HSI": ([b["date"] for b in bars], [b["close"] for b in bars])}
        entries = [{"symbol": "^HSI", "base_date": bars[base_index]["date"], "p_up": 0.6,
                    "settled": False}]
        hk7._settle(entries, series, now=datetime(2030, 1, 1, tzinfo=CST))
        self.assertFalse(entries[0]["settled"])
        # 补齐第 7 根 K 线 → 结算并回填命中 / Brier（当次运行不可能结算当次预测）
        more = synthetic_bars(122, seed=3)
        series2 = {"^HSI": ([b["date"] for b in more], [b["close"] for b in more])}
        hk7._settle(entries, series2, now=datetime(2030, 1, 1, tzinfo=CST))
        self.assertTrue(entries[0]["settled"])
        self.assertEqual(entries[0]["settle_date"], more[base_index + hk7.HORIZON]["date"])
        self.assertIn("hit", entries[0])
        self.assertIsNotNone(entries[0]["brier"])

    def test_journal_stats_hold_back_hit_rate_below_ten(self):
        entries = [{"settled": True, "hit": True, "brier": 0.1, "p_up": 0.6,
                    "settle_date": "2026-01-01", "actual_ret": 0.01}] * 4
        stats = hk7._journal_stats(entries)
        self.assertIsNone(stats["hit_rate"])
        self.assertEqual(stats["n"], 4)
        self.assertIn("只报样本量", stats["note"])


# ======================================================================
# ③ 大模型链路：解析 / 收敛 / 数字溯源
# ======================================================================
class LLMTests(unittest.TestCase):
    def test_llm_config_env_precedence_and_fallback(self):
        cfg = hk7.llm_config({"DEEPSEEK_API_KEY": " k ", "OCTOPUS_LLM_MODEL": "m1",
                              "OCTOPUS_LLM_TIMEOUT": "3"})
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["key"], "k")
        self.assertEqual(cfg["model"], "m1")
        self.assertEqual(cfg["timeout"], 5)          # 夹到下限 5 秒
        cfg2 = hk7.llm_config({"OCTOPUS_LLM_API_KEY": "x", "OCTOPUS_HK7_FALLBACK": "0"})
        self.assertFalse(cfg2["fallback"])
        self.assertFalse(hk7.llm_config({})["enabled"])

    def test_extract_json_tolerates_fences_and_noise(self):
        self.assertEqual(hk7._extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(hk7._extract_json('前言 {"a": {"b": 2}} 后记'), {"a": {"b": 2}})
        self.assertIsNone(hk7._extract_json("no json here"))
        self.assertIsNone(hk7._extract_json(""))

    def _llm_run(self, payload, tmp, allowed_extra=None):
        def fake_post(url, body, headers, timeout):
            self.assertIn("chat/completions", url)
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}
        return hk7.run_seven_day(
            None, bars_by_symbol=bars_by_symbol(), history_path=str(Path(tmp) / "j.json"),
            post_json=fake_post, config=quant_config(enabled=True, key="test-key"))

    def test_probability_is_converged_to_quant_base(self):
        bars = bars_by_symbol()
        base = hk7.run_seven_day(None, bars_by_symbol=bars, history_path=None,
                                 config=quant_config())
        p_hsi = next(t["quant_p_up"] for t in base["targets"] if t["code"] == "^HSI")
        payload = {"targets": [{"code": "^HSI", "p_up": 0.97, "summary": "偏强"}],
                   "cross_note": ""}
        with tempfile.TemporaryDirectory() as tmp:
            res = self._llm_run(payload, tmp)
        self.assertEqual(res["engine"], "llm")
        hsi = next(t for t in res["targets"] if t["code"] == "^HSI")
        self.assertTrue(hsi["converged"])
        self.assertAlmostEqual(hsi["p_up"], min(hk7.PROB_CAP, p_hsi + hk7.MAX_PROB_DEVIATION),
                               places=6)
        self.assertLessEqual(hsi["p_up"], hk7.PROB_CAP)

    def test_fabricated_numbers_and_absolute_words_fall_back_to_quant(self):
        payload = {"targets": [
            {"code": "^HSI", "p_up": 0.6, "summary": "目标位 12345.67 点",
             "drivers": ["必涨无风险"], "risks": ["政策不确定性"]}],
            "cross_note": "南向资金回暖"}
        with tempfile.TemporaryDirectory() as tmp:
            res = self._llm_run(payload, tmp)
        hsi = next(t for t in res["targets"] if t["code"] == "^HSI")
        # 编造数字 → summary 回退量化口径；绝对化措辞 → drivers 回退量化口径
        self.assertIn("量化基准", hsi["summary"])
        self.assertNotIn("12345.67", hsi["summary"])
        self.assertTrue(any("扩张基准率" in d for d in hsi["drivers"]))
        self.assertIn("12345.67", res["notes"]["dropped"])
        self.assertIn("绝对化措辞", res["notes"]["dropped"])
        # 可溯源的文案保留（南向资金一句不含数字，直接通过）
        self.assertEqual(res["cross_note"], "南向资金回暖")

    def test_traceable_numbers_are_kept(self):
        bars = bars_by_symbol()
        close = bars["^HSI"][-1]["close"]
        payload = {"targets": [
            {"code": "^HSI", "p_up": 0.6,
             "summary": "现价 %.2f 附近震荡" % close,
             "drivers": ["现价 %.2f 上方运行" % close], "risks": ["波动放大"]}],
            "cross_note": ""}
        with tempfile.TemporaryDirectory() as tmp:
            res = self._llm_run(payload, tmp)
        hsi = next(t for t in res["targets"] if t["code"] == "^HSI")
        self.assertIn(f"{close:.2f}", hsi["summary"])
        self.assertIn(f"{close:.2f}", hsi["drivers"][0])
        # summary / drivers / risks 三条都没有编造数字 → 全部保留
        self.assertEqual(res["grounded"], "3/3")

    def test_broken_llm_reply_degrades_to_quant(self):
        def bad_post(url, body, headers, timeout):
            return {"choices": [{"message": {"content": "抱歉，我无法给出概率。"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            res = hk7.run_seven_day(
                None, bars_by_symbol=bars_by_symbol(), history_path=str(Path(tmp) / "j.json"),
                post_json=bad_post, config=quant_config(enabled=True, key="k"))
        self.assertTrue(res["available"])
        self.assertEqual(res["engine"], "quant")
        self.assertIn("合法 JSON", res["llm_reason"])

    def test_llm_exception_degrades_and_never_raises(self):
        def boom(url, body, headers, timeout):
            raise RuntimeError("network down")
        with tempfile.TemporaryDirectory() as tmp:
            res = hk7.run_seven_day(
                None, bars_by_symbol=bars_by_symbol(), history_path=str(Path(tmp) / "j.json"),
                post_json=boom, config=quant_config(enabled=True, key="k"))
        self.assertTrue(res["available"])
        self.assertEqual(res["engine"], "quant")
        self.assertIn("RuntimeError", res["llm_reason"])

    def test_prompt_only_carries_given_data(self):
        bars = bars_by_symbol()
        with tempfile.TemporaryDirectory() as tmp:
            res = hk7.run_seven_day(
                None, bars_by_symbol=bars, history_path=str(Path(tmp) / "j.json"),
                extra={"flows": {"south_amount_yi": 612.34},
                       "events": [{"date": "2026-10-02", "name": "非农就业人数:季调"}],
                       "news": [{"title": "港股成交回暖", "source": "香港经济日报"}]},
                config=quant_config())
        self.assertEqual(len(res["targets"]), 3)
        # 证据缺失时不编造：extra 为空时也不报错
        res2 = hk7.run_seven_day(None, bars_by_symbol=bars, history_path=None,
                                 extra={}, config=quant_config())
        self.assertTrue(res2["available"])


# ======================================================================
# ④ 管线接入：source 结果 / 审计 / 渲染 / 开关
# ======================================================================
class PipelineWiringTests(unittest.TestCase):
    def _fake_request(self, bars):
        def fake(url, headers=None, params=None, timeout=15, is_json=True):
            m = re.search(r"chart/([^?/]+)", url)
            if not m:
                return None
            return yahoo_chart_payload(m.group(1), bars)
        return fake

    def test_fetch_returns_success_source_and_audit_name(self):
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        self.assertEqual(src["status"], "success")
        self.assertEqual(src["source"], pipeline.HK7_SOURCE_NAME)
        self.assertEqual(src["result"]["engine"], "quant")
        self.assertEqual(src["content_date"], bars[-1]["date"])

    def test_disabled_switch_marks_unavailable(self):
        with patch.object(pipeline, "HK7_ENABLED", False):
            src = pipeline.fetch_hk_seven_day({})
        self.assertEqual(src["status"], "unavailable")
        self.assertIn("关闭", src["error"])

    def test_no_key_without_fallback_is_unavailable(self):
        with patch.object(pipeline, "HK7_ENABLED", True), \
                patch.object(pipeline._hk7, "llm_config",
                             return_value={"enabled": False, "fallback": False,
                                           "key": "", "base": "", "model": "m",
                                           "timeout": 10}):
            src = pipeline.fetch_hk_seven_day({})
        self.assertEqual(src["status"], "unavailable")

    def test_block_renders_both_themes_and_hides_when_unavailable(self):
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        res = src["result"]
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            html = pipeline._hk_seven_day_block(res, kit)
            self.assertIn("恒生指数", html)
            self.assertIn("P(7日涨)", html)
            self.assertIn("预测留痕", html)
        self.assertEqual(pipeline._hk_seven_day_block({"available": False}, pipeline.GUIZANG_KIT), "")
        self.assertEqual(pipeline._hk_seven_day_block({"available": True, "targets": []},
                                                      pipeline.GUIZANG_KIT), "")

    def test_report_contains_section_and_coverage_line(self):
        bars = synthetic_bars()
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(pipeline, "REPORT_DIR", tmp), \
                patch.object(pipeline, "safe_request", self._fake_request(bars)):
            src = pipeline.fetch_hk_seven_day({})
        html = pipeline.generate_report_guizang(
            {pipeline.HK7_SOURCE_NAME: src, "_backup_info": {"events": []}},
            "2026年9月29日", "20260929")
        self.assertIn("AI 七日港股走势分析概率", html)
        self.assertIn("HK 7D PROB", html)
        self.assertIn("恒生科技", html)
        # 栏目顺序：策略研判之后、趋势跟踪之前
        self.assertLess(html.index("HK 7D PROB"),
                        html.index("TREND TRACKING") if "TREND TRACKING" in html else len(html))

    def test_sector_rotation_column_is_fully_removed(self):
        self.assertFalse(hasattr(pipeline, "fetch_sector_rotation"))
        self.assertFalse(hasattr(pipeline, "_sector_rotation_block"))
        self.assertNotIn("SECTOR ROTATION", pipeline.REPORT_SECTION_ORDER)
        self.assertNotIn("SECTOR ROTATION", pipeline._SECTION_ICON_META)
        for name in ("sector_rotation.py", "probe_sector_rotation.py"):
            self.assertFalse((OUTPUT_DIR / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
