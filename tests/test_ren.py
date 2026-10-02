"""「🦑 鲜鲜解读」（output/octopus_ren.py）回归测试（全部离线）。

防自欺口径与整仓一致：
  · 确定性——同一份输入永远得到同一份解读（可复现，绝不随机跳变）；
  · 不伪造——数据缺失 / available=False 时必须返回空串，该栏目自动缺席；
  · 同源——解读引用的数字与正文（⌁ AI 研判 / 总结）来自同一批实参；
  · 诚实——概率接近 50% 时解读必须出现「抛硬币」级措辞，不得夸大把握。
"""
import importlib.util
import sys
import types
import unittest
import unittest.mock
from pathlib import Path

sys.modules.setdefault("requests", types.SimpleNamespace())

REN_PATH = Path(__file__).parents[1] / "output" / "octopus_ren.py"
spec = importlib.util.spec_from_file_location("octopus_ren_under_test", REN_PATH)
ren = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ren)

ALL_KICKERS = (
    "STRATEGY READ", "QUANT FORECAST", "HK PROBABILITY", "LIQUIDITY FLOW",
    "WEEKLY FORECAST", "POLICY SHOCK", "FED TREND", "GEO TREND", "ECON CALENDAR",
    "MARKET REVIEW", "TREND TRACKING", "GLOBAL HEADLINES", "EASTMONEY WIRE",
    "HK GURU CHANNELS", "NEWS SENTIMENT", "HK 7D PROB", "SUMMARY", "FORECAST",
)


def rich_ctx():
    """一份信息量充足的 ctx（数字均为测试造的数据，断言围绕它们展开）。"""
    return {
        "date_str": "20260929",
        "notes": {},
        "market": {"status": "success", "quotes": {}},
        "pan": {
            "status": "success",
            "breadth": {"up": 3525, "down": 1944, "mood": "偏多震荡", "ratio": 1.81},
            "turnover": {"total": 14217.23, "chg_pct": -17.19},
            "sectors": {"leading": [{"name": "燃料电池", "chg_pct": 7.73}]},
        },
        "policy": {"available": True, "broad_score": -9, "broad_label": "偏冷",
                   "winners": [{"name": "银行"}], "losers": [{"name": "地产链"}]},
        "ai": {"available": True, "sentiment_label": "中性", "score": 7,
               "confidence": "高", "themes": ["AI/算力", "新能源/锂电"]},
        "quant": {
            "available": True,
            "headline": {"available": True, "label": "中性", "p_up": 0.52, "arrow": "■"},
            "target_label": "下一交易日 09-30（周三）",
            "validation": {1: {"hit_rate": 0.519, "base_rate": 0.508, "n": 185, "z": 0.51}},
            "stocks": [
                {"label": "汇丰控股", "probs": {5: {"p_up": 0.63}}},
                {"label": "小米集团-W", "probs": {5: {"p_up": 0.36}}},
                {"label": "腾讯控股", "probs": {5: {"p_up": 0.52}}},
            ],
            "breadth": {"available": True, "score": 24},
            "liquidity": {
                "available": True,
                "summary": "流动性偏紧（综合分 45/100）",
                "score": 45, "label": "流动性偏紧",
                "south": {"available": True, "latest": 640, "pct60": 0.02},
            },
        },
        "weekly": {"available": True,
                   "entry": {"p_up": 0.53, "label": "中性（略偏涨）", "target_sessions": 5}},
        "hk7": {},
        "fed": {"available": True, "verdict": "偏鹰（紧缩倾向）",
                "positive_label": "鸽派（宽松）", "negative_label": "鹰派（紧缩）",
                "positive_n": 0, "negative_n": 7, "total": 8},
        "geo": {"available": True, "verdict": "升温（对抗）",
                "positive_label": "缓和（降温）", "negative_label": "升温（对抗）",
                "positive_n": 1, "negative_n": 5, "total": 8},
        "senti": {"available": True, "total_matched": 12,
                  "market_summary": {"overall_dns": 0.10, "overall_label": "中性",
                                     "hottest": {"name": "纳指ETF", "key": "qqq"},
                                     "coldest": {"name": "亨通光电", "key": "htgd"},
                                     "most_covered": {"name": "英伟达", "total": 25}}},
        "cal": {"status": "success",
                "window": "2026-09-29 ~ 2026-10-29 · 未来 30 天",
                "items": [
                    {"date": "2026-10-28", "time": "02:00", "imp": 3, "kind": 1,
                     "name": "美联储议息会议"},
                    {"date": "2026-10-14", "time": "09:30", "imp": 3, "kind": 0,
                     "name": "CPI:同比/环比"},
                    {"date": "2026-10-14", "time": "09:30", "imp": 3, "kind": 0,
                     "name": "PPI:全部工业品:同比"},
                    {"date": "2026-10-02", "time": "20:30", "imp": 3, "kind": 0,
                     "name": "非农就业人数:季调"},
                ]},
        "yt": {"channels": [{"is_today": True, "videos": [{"title": "a"}]},
                            {"is_today": False, "videos": [{"title": "b"}]}]},
        "google": {"status": "success",
                   "headlines": [{"title": "新型电池产业迎重磅利好"}, {"title": "AI 模型突破"}]},
        "em": {"status": "success",
               "headlines": [{"title": "红塔证券首次回购股份"}, {"title": "长盈通签订订单"}]},
        "trend": {"platforms": ["Reddit", "StockTwits"], "samples": 33,
                  "bull": 8, "bear": 30,
                  "news_an": {"scanned": 94, "hk_n": 31, "total": 20, "themes": ["AI/科技"]}},
        "coverage": {"today": 15, "total": 18, "missing": ["每日量化策略（行业轮动）"]},
    }


class DeterminismTests(unittest.TestCase):
    def test_same_input_same_output(self):
        """可复现：同一 ctx 重复调用，结果逐字一致（绝不随机）。"""
        ctx = rich_ctx()
        for kicker in ALL_KICKERS:
            first = ren.section_ren(kicker, ctx)
            second = ren.section_ren(kicker, ctx)
            self.assertEqual(first, second, kicker)

    def test_day_seed_changes_wording_pool_only(self):
        """隔天措辞从池里换花样，但数字口径不变（52% 还是 52%，绝不变造数字）。"""
        ctx_a, ctx_b = rich_ctx(), dict(rich_ctx(), date_str="20260930")
        expect = {"FORECAST": "52%", "QUANT FORECAST": "52%", "WEEKLY FORECAST": "53%"}
        for kicker, token in expect.items():
            self.assertIn(token, ren.section_ren(kicker, ctx_a), kicker)
            self.assertIn(token, ren.section_ren(kicker, ctx_b), kicker)


class NoFabricationTests(unittest.TestCase):
    def test_empty_ctx_returns_empty_for_every_section(self):
        """数据缺失 → 空串（栏目末尾不出现硬编解读）。"""
        for kicker in ALL_KICKERS:
            self.assertEqual(ren.section_ren(kicker, {}), "", kicker)
            self.assertEqual(ren.section_ren(kicker, {"date_str": "20260101"}), "", kicker)

    def test_unavailable_results_return_empty(self):
        """available=False / status!=success 时整行缺席，绝不用旧数据充数。"""
        ctx = rich_ctx()
        for key in ("policy", "ai", "quant", "weekly", "fed", "geo", "senti"):
            broken = dict(ctx, **{key: {"available": False}})
            kicker = {"policy": "POLICY SHOCK", "ai": "STRATEGY READ",
                      "quant": "QUANT FORECAST", "weekly": "WEEKLY FORECAST",
                      "fed": "FED TREND", "geo": "GEO TREND",
                      "senti": "NEWS SENTIMENT"}[key]
            self.assertEqual(ren.section_ren(kicker, broken), "", kicker)
        broken = dict(ctx, cal={"status": "failed", "items": []})
        self.assertEqual(ren.section_ren("ECON CALENDAR", broken), "")
        broken = dict(ctx, pan={"status": "failed"}, market={"status": "failed"})
        self.assertEqual(ren.section_ren("MARKET REVIEW", broken), "")

    def test_unknown_kicker_returns_empty(self):
        self.assertEqual(ren.section_ren("NOT A KICKER", rich_ctx()), "")

    def test_numbers_come_from_input_only(self):
        """解读引用的概率 / 命中率 / 分数必须能在输入里找到（防凭空造数）。"""
        ctx = rich_ctx()
        cases = {
            "FORECAST": ["52%", "53%"],
            "QUANT FORECAST": ["52%", "185"],
            "HK PROBABILITY": ["63%", "36%", "24"],
            "LIQUIDITY FLOW": ["640", "45/100"],
            "WEEKLY FORECAST": ["53%"],
            "POLICY SHOCK": ["-9"],
            "FED TREND": ["命中 7 次", "8 条"],
            "GEO TREND": ["命中 5 次"],
            "TREND TRACKING": ["33", "94", "31", "20 家"],
            "SUMMARY": ["15", "18"],
        }
        for kicker, tokens in cases.items():
            text = ren.section_ren(kicker, ctx)
            self.assertTrue(text, kicker)
            for token in tokens:
                self.assertIn(token, text, f"{kicker} 缺少输入数字 {token}")

    def test_coin_probability_wording_is_honest(self):
        """概率 45%~55% 区间必须出现「抛硬币 / 五五开」级措辞，不许吹成稳了。"""
        ctx = rich_ctx()
        text = ren.section_ren("QUANT FORECAST", ctx)
        honest_words = ("抛硬币", "五五开", "神仙", "氛围")
        self.assertTrue(any(w in text for w in honest_words), text)


class ContentTests(unittest.TestCase):
    def test_rich_ctx_every_section_has_text(self):
        ctx = rich_ctx()
        # HK 7D PROB 只在配置大模型（hk7.available）时出现：未配置 → 空，绝不硬编。
        self.assertEqual(ren.section_ren("HK 7D PROB", ctx), "")
        for kicker in ALL_KICKERS:
            if kicker == "HK 7D PROB":
                continue
            self.assertTrue(ren.section_ren(kicker, ctx), kicker)

    def test_hk7_ren_only_when_available(self):
        ctx = rich_ctx()
        ctx["hk7"] = {"available": True, "engine": "llm",
                      "targets": [{"label": "恒生指数", "p_up": 0.57},
                                  {"label": "恒生科技", "p_up": 0.49}]}
        text = ren.section_ren("HK 7D PROB", ctx)
        self.assertIn("57%", text)
        self.assertIn("49%", text)
        self.assertIn("大模型研判", text)
        degraded = dict(ctx, hk7={"available": True, "engine": "quant_base",
                                  "targets": [{"label": "恒生指数", "p_up": 0.55}]})
        self.assertIn("量化基准", ren.section_ren("HK 7D PROB", degraded))

    def test_meme_flavor_present(self):
        ctx = rich_ctx()
        self.assertIn("开盲盒", ren.section_ren("ECON CALENDAR", ctx))
        self.assertIn("紧箍咒", ren.section_ren("FED TREND", ctx))
        self.assertIn("吃瓜", ren.section_ren("GEO TREND", ctx))
        self.assertIn("显眼包", ren.section_ren("GEO TREND", ctx))
        self.assertIn("热帖和头条", ren.section_ren("TREND TRACKING", ctx))
        self.assertIn("后视镜", ren.section_ren("NEWS SENTIMENT", ctx))
        self.assertIn("非投资建议", ren.section_ren("SUMMARY", ctx) + ren.DISCLAIMER)

    def test_digest_ren_empty_and_rich(self):
        self.assertEqual(ren.digest_ren({}), "")
        text = ren.digest_ren(rich_ctx())
        self.assertTrue(text)
        self.assertIn("一句话攻略", text)


class PipelineIntegrationTests(unittest.TestCase):
    """走完整的 generate_report（离线合成数据），验证两主题都会挂上「鲜鲜解读」行。"""

    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault("requests", types.SimpleNamespace())
        pipeline_path = Path(__file__).parents[1] / "output" / "pipeline.py"
        spec = importlib.util.spec_from_file_location(
            "pipeline_for_ren_test", pipeline_path)
        cls.pipeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.pipeline)

    @staticmethod
    def _data():
        p = PipelineIntegrationTests.pipeline
        return {
            "实时行情": p._source_result(
                "test quote", "success",
                quotes={
                    "上证指数": {"price": 3830.45, "change_pct": 0.18, "currency": "CNY",
                                "as_of": "2026-09-29"},
                    "恒生指数": {"price": 24523.57, "change_pct": -0.48, "currency": "HKD",
                                "as_of": "2026-09-29"},
                },
                is_today=True),
            "全球头条": p._source_result(
                "test news", "success",
                headlines=[{"title": "新型电池产业迎重磅利好，长寿命锂电池突破",
                            "source": "测试源", "published_cst": "2026-09-29 10:00"}],
                content_date="2026-09-29", is_today=True),
            "东财快讯": p._source_result(
                "test wire", "success",
                headlines=[{"title": "红塔证券首次回购股份103万股",
                            "time": "2026-09-29 18:10"}],
                content_date="2026-09-29", is_today=True),
            "港股名家频道": p._source_result(
                "test yt", "success", channels=[],
                content_date="2026-09-29", is_today=True),
        }

    def test_guizang_and_pixel_both_render_ren_rows(self):
        for theme in ("guizang", "pixel"):
            html = self.pipeline.generate_report(
                self._data(), "2026年9月29日 · 周二", "20260929", theme=theme)
            self.assertIn("鲜鲜解读", html, theme)
            self.assertIn("🦑", html, theme)
            self.assertIn(ren.DISCLAIMER, html, theme)

    def test_ren_disabled_by_flag(self):
        with unittest.mock.patch.object(self.pipeline, "REN_ENABLED", False):
            html = self.pipeline.generate_report(
                self._data(), "2026年9月29日 · 周二", "20260929")
        self.assertNotIn("鲜鲜解读", html)
        self.assertNotIn("🦑", html)

    def test_ren_numbers_match_body(self):
        """解读行里的数字必须来自正文同源数据（这里验证实时行情涨跌家数）。"""
        html = self.pipeline.generate_report(
            self._data(), "2026年9月29日 · 周二", "20260929")
        self.assertIn("0.18", html)          # 上证 +0.18% 与正文同源
        self.assertIn("1 涨 / 1 跌", html)  # 报价面计数进入解读


if __name__ == "__main__":
    unittest.main()
