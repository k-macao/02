"""🇭🇰 港股境外数据源（output/hk_overseas.py）与「【深水石斑鱼】港股行情」栏目测试（全部离线）。

守的整仓「防自欺」口径：
  · 确定性——同一份输入永远得到同一结果，解析器不依赖当前时间；
  · 不伪造——取不到的行/字段一律缺席或「—」，绝不拿相邻数字顶替、绝不猜单位；
  · 可溯源——每个数字都带行情日与供数来源（YH / ST / HKEX / +BR）；
  · 边界——浏览器第 4 路默认关闭；开启时也只补主源没给的字段，不覆盖既有数字。

所有 HTTP 请求都用测试替身注入，不访问任何网站。
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# CI 装有 requests；本地最小环境没有时仅提供导入占位（所有请求均 mock）。
sys.modules.setdefault("requests", types.SimpleNamespace())

OUT = Path(__file__).parents[1] / "output"

spec = importlib.util.spec_from_file_location("hk_overseas_under_test", OUT / "hk_overseas.py")
hkx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hkx)

spec_p = importlib.util.spec_from_file_location("pipeline_hk_overseas_test", OUT / "pipeline.py")
pipeline = importlib.util.module_from_spec(spec_p)
spec_p.loader.exec_module(pipeline)


# ------------------------------------------------------------
# 测试替身
# ------------------------------------------------------------
def chart_payload(price, prev, ts=1759132800, volume=1234, currency="HKD"):
    """Yahoo Chart JSON（两根日线：prev → price）。"""
    return {"chart": {"result": [{
        "meta": {"currency": currency, "regularMarketPrice": price, "regularMarketTime": ts,
                 "regularMarketVolume": volume, "chartPreviousClose": prev},
        "timestamp": [ts - 86400, ts],
        "indicators": {"quote": [{"close": [prev, price], "volume": [10, volume]}]},
    }]}}


STOOQ_CSV = ("Date,Open,High,Low,Close,Volume\n"
             "2026-09-29,640,646,648,640.0,100\n"
             "2026-09-30,641,646,647,645.0,120\n")

HKEX_HTML = "Daily Market Report 2026-09-30 ... Market Turnover HK$ 123,456 million ..."


def make_request(*, yahoo=None, stooq=None, hkex=None, log=None):
    """构造取数替身：按 URL 前缀返回不同内容，None 表示该路失败。"""
    def _req(url, timeout=15, is_json=True, **kw):
        if log is not None:
            log.append(url)
        if "finance.yahoo" in url:
            return yahoo
        if "stooq" in url:
            return stooq
        if "hkex" in url:
            return hkex
        return None
    return _req


def quote_row(**kw):
    base = {"label": "腾讯控股", "code": "0700.HK", "price": 645.5, "change_pct": -0.69,
            "volume": 12345678, "turnover_yi": 12.3, "currency": "HKD",
            "as_of": "2026-10-02", "source": "yahoo", "via": "bar"}
    base.update(kw)
    return base


# ------------------------------------------------------------
# ① 解析器
# ------------------------------------------------------------
class YahooChartTests(unittest.TestCase):
    def test_bar_path_reads_last_two_closes(self):
        q = hkx.parse_yahoo_chart(chart_payload(645.5, 650.0))
        self.assertAlmostEqual(q["price"], 645.5)
        self.assertAlmostEqual(q["change_pct"], (645.5 / 650.0 - 1) * 100, places=4)
        self.assertEqual(q["volume"], 1234)
        self.assertEqual(q["currency"], "HKD")
        self.assertEqual(q["via"], "bar")
        self.assertTrue(q["as_of"].startswith("20"))

    def test_meta_fallback_when_no_bars(self):
        payload = {"chart": {"result": [{"meta": {
            "currency": "HKD", "regularMarketPrice": 100.0, "chartPreviousClose": 98.0,
            "regularMarketTime": 1759132800, "regularMarketVolume": 7}, "timestamp": [],
            "indicators": {"quote": [{}]}}]}}
        q = hkx.parse_yahoo_chart(payload)
        self.assertAlmostEqual(q["price"], 100.0)
        self.assertAlmostEqual(q["change_pct"], (100 / 98 - 1) * 100, places=4)
        self.assertEqual(q["via"], "meta")

    def test_invalid_payload_returns_none(self):
        for bad in ({}, {"chart": {"result": []}}, {"chart": {"result": [{}]}}, None):
            self.assertIsNone(hkx.parse_yahoo_chart(bad), f"{bad!r} 不应产出数字")


class StooqCsvTests(unittest.TestCase):
    def test_two_rows_give_change(self):
        q = hkx.parse_stooq_history_csv(STOOQ_CSV)
        self.assertAlmostEqual(q["price"], 645.0)
        self.assertAlmostEqual(q["change_pct"], (645 / 640 - 1) * 100, places=4)
        self.assertEqual(q["as_of"], "2026-09-30")
        self.assertEqual(q["via"], "stooq")

    def test_single_row_has_no_change(self):
        q = hkx.parse_stooq_history_csv("Date,Open,High,Low,Close,Volume\n"
                                        "2026-09-30,1,1,1,645.0,120\n")
        self.assertAlmostEqual(q["price"], 645.0)
        self.assertIsNone(q["change_pct"])

    def test_no_data_and_garbage(self):
        for bad in ("No data", "", None, "Date,Open\n", "not,a,csv\n"):
            self.assertIsNone(hkx.parse_stooq_history_csv(bad))


class MarketStatsTests(unittest.TestCase):
    def test_english_million(self):
        out = hkx.parse_market_stats_text(HKEX_HTML)
        self.assertAlmostEqual(out["turnover_yi"], 1234.56)
        self.assertEqual(out["as_of"], "2026-09-30")

    def test_chinese_yi(self):
        out = hkx.parse_market_stats_text("成交金額 1,234.5 億港元")
        self.assertAlmostEqual(out["turnover_yi"], 1234.5)

    def test_number_without_unit_is_rejected(self):
        """只有数字没有单位 → 不猜，返回 {}（宁缺勿错）。"""
        self.assertEqual(hkx.parse_market_stats_text("Market Turnover: 1,234,567"), {})
        self.assertEqual(hkx.parse_market_stats_text("今天天气不错"), {})
        self.assertEqual(hkx.parse_market_stats_text(None), {})


class BrowserTextTests(unittest.TestCase):
    def test_price_pct_turnover(self):
        out = hkx.parse_browser_quote_text("騰訊控股 現價 645.50 升 1.25% 成交金額 12.3億")
        self.assertAlmostEqual(out["price"], 645.5)
        self.assertAlmostEqual(out["change_pct"], 1.25)
        self.assertAlmostEqual(out["turnover_yi"], 12.3)

    def test_pct_derived_from_prev_close_when_missing(self):
        out = hkx.parse_browser_quote_text("現價 645.50 前收市價 650.00")
        self.assertAlmostEqual(out["change_pct"], (645.5 / 650.0 - 1) * 100, places=4)

    def test_unknown_page_yields_empty(self):
        self.assertEqual(hkx.parse_browser_quote_text("Cloudflare 验证中"), {})
        self.assertEqual(hkx.parse_browser_quote_text(""), {})


# ------------------------------------------------------------
# ② 编排：多路合并 / 降级 / 交叉校验
# ------------------------------------------------------------
class FetchOrchestrationTests(unittest.TestCase):
    def test_yahoo_primary_and_hkex_market(self):
        res = hkx.fetch_hk_overseas(make_request(yahoo=chart_payload(645.5, 650.0),
                                                 hkex=HKEX_HTML),
                                    use_browser=False)
        self.assertEqual(res["status"], "success")
        self.assertAlmostEqual(res["market"]["turnover_yi"], 1234.56)
        self.assertTrue(res["indices"] and res["stocks"])
        self.assertTrue(all(r["source"] == "yahoo" for r in res["indices"]))
        self.assertEqual({s["status"] for s in res["sources"] if s["tier"] == 1}, {"success"})
        self.assertEqual(res["source"], hkx.HK_OVERSEAS_SOURCE)

    def test_stooq_fills_when_yahoo_fails(self):
        res = hkx.fetch_hk_overseas(make_request(yahoo=None, stooq=STOOQ_CSV, hkex=None),
                                    use_browser=False)
        self.assertEqual(res["status"], "success")
        self.assertTrue(all(r["source"] == "stooq" for r in res["stocks"]))
        st = next(s for s in res["sources"] if s["tier"] == 2)
        self.assertEqual(st["status"], "success")
        self.assertEqual(st["count"], len(res["indices"]) + len(res["stocks"]))

    def test_all_sources_down_is_unavailable_and_fabricates_nothing(self):
        res = hkx.fetch_hk_overseas(make_request(), use_browser=False)
        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(res["indices"], [])
        self.assertEqual(res["stocks"], [])
        self.assertEqual(res["market"], {})
        self.assertIsNone(res["content_date"])
        self.assertTrue(res["error"])

    def test_is_today_uses_content_date_and_injected_now(self):
        from datetime import datetime, timezone, timedelta
        ts = int(datetime(2026, 10, 2, 16, 0, tzinfo=timezone(timedelta(hours=8))).timestamp())
        res = hkx.fetch_hk_overseas(make_request(yahoo=chart_payload(645.5, 650.0, ts=ts)),
                                    use_browser=False,
                                    now=datetime(2026, 10, 2, 18, 0, tzinfo=timezone(timedelta(hours=8))))
        self.assertEqual(res["content_date"], "2026-10-02")
        self.assertTrue(res["is_today"])
        res2 = hkx.fetch_hk_overseas(make_request(yahoo=chart_payload(645.5, 650.0, ts=ts)),
                                     use_browser=False,
                                     now=datetime(2026, 10, 5, 9, 0, tzinfo=timezone(timedelta(hours=8))))
        self.assertFalse(res2["is_today"])

    def test_crosscheck_flags_deviation(self):
        # Yahoo 645.5 vs Stooq 640.0 → 偏差 ~0.85%？不：差 5.5/645.5 ≈ 0.85% 不触发；
        # 这里用 700.0 制造 >1.5% 的偏差，确认被记录。
        yahoo_payload = chart_payload(645.5, 650.0)
        stooq = ("Date,Open,High,Low,Close,Volume\n"
                 "2026-09-29,690,700,701,690.0,1\n"
                 "2026-09-30,695,700,702,700.0,1\n")
        res = hkx.fetch_hk_overseas(make_request(yahoo=yahoo_payload, stooq=stooq),
                                    use_browser=False, crosscheck=True)
        cross = res["crosscheck"]
        self.assertTrue(cross["rows"])
        self.assertTrue(cross["bad"], ">1.5% 的价格偏差必须被记为交叉校验不一致")
        # 交叉校验不覆盖主源数字
        self.assertTrue(all(r["source"] == "yahoo" for r in res["stocks"]))

    def test_browser_tier_fills_missing_fields_only(self):
        def fake_probe(targets, **kw):
            return {"ok": True, "error": None, "results": [
                {"name": "etnet:0700.HK", "kind": "quote", "code": "0700.HK", "ok": True,
                 "url": "https://example/", "status": 200, "title": "t",
                 "text": "現價 700.00 成交金額 12.3億", "error": None},
                {"name": "hkex-stats", "kind": "market", "ok": True,
                 "url": "https://example/", "status": 200, "title": "t",
                 "text": "Market Turnover HK$ 123,456 million 2026-10-02", "error": None},
            ]}
        # 浏览器页面故意报一个不同的价格（700.00）：主源已有的价格 / 涨跌绝不被覆盖，
        # 只允许补主源没有的字段（这里是成交额）。
        yahoo = chart_payload(645.5, 650.0)
        base = hkx.fetch_hk_overseas(make_request(yahoo=yahoo), use_browser=False)
        self.assertIsNone(base["stocks"][0]["turnover_yi"])
        with patch.object(hkx, "browser_probe", fake_probe):
            res = hkx.fetch_hk_overseas(make_request(yahoo=yahoo), use_browser=True)
        self.assertAlmostEqual(res["stocks"][0]["price"], 645.5, msg="浏览器不得覆盖主源价格")
        self.assertAlmostEqual(res["stocks"][0]["change_pct"], base["stocks"][0]["change_pct"],
                               msg="浏览器不得覆盖主源涨跌")
        self.assertAlmostEqual(res["stocks"][0]["turnover_yi"], 12.3,
                               msg="主源缺成交额时允许由浏览器补齐")
        self.assertEqual(res["stocks"][0]["browser_source"], "browser:etnet")
        self.assertEqual(res["market"]["turnover_yi"], 1234.56,
                         "HTTP 拿不到市场成交时由浏览器补上")
        self.assertEqual(next(s for s in res["sources"] if s["tier"] == 4)["status"], "success")

    def test_circuit_breaker_caps_failed_requests(self):
        """离线 / 被墙时不能把 11 只标的 × 2 镜像逐个超时拖垮流水线：连续失败即熔断。"""
        log = []
        res = hkx.fetch_hk_overseas(make_request(log=log), use_browser=False)
        self.assertLess(len(log), 20, f"熔断失效：发起了 {len(log)} 次请求")
        notes = " ".join(s["note"] for s in res["sources"])
        self.assertIn("熔断", notes)

    def test_browser_unavailable_is_recorded_not_raised(self):
        with patch.object(hkx, "browser_probe",
                          return_value={"ok": False, "results": [], "error": "未找到 node"}):
            res = hkx.fetch_hk_overseas(make_request(yahoo=chart_payload(645.5, 650.0)),
                                        use_browser=True)
        tier4 = next(s for s in res["sources"] if s["tier"] == 4)
        self.assertEqual(tier4["status"], "failed")
        self.assertIn("node", tier4["note"])
        self.assertEqual(res["status"], "success")   # 浏览器失败不影响前三路


# ------------------------------------------------------------
# ③ 栏目渲染与流水线接线
# ------------------------------------------------------------
def sample_source_result():
    return {
        "source": hkx.HK_OVERSEAS_SOURCE, "status": "success", "is_today": True,
        "content_date": "2026-10-02", "snapshot": True, "fetched_at": "2026-10-02 09:30",
        "indices": [
            quote_row(label="恒生指数", code="^HSI", price=26800.5, change_pct=1.13,
                      volume=None, turnover_yi=None),
            quote_row(label="恒生科技", code="^HSTECH", price=6100.2, change_pct=-2.4,
                      volume=None, turnover_yi=None),
        ],
        "stocks": [
            quote_row(),
            quote_row(label="阿里巴巴-W", code="9988.HK", price=101.5, change_pct=None,
                      volume=None, turnover_yi=None, browser_source="browser:etnet"),
        ],
        "market": {"turnover_yi": 1234.56, "as_of": "2026-10-02", "source": "hkex-http"},
        "sources": [
            {"name": "Yahoo Finance Chart（境外·主源）", "tier": 1, "status": "success",
             "count": 12, "as_of": "2026-10-02", "note": "12 项成功 / 0 项失败"},
            {"name": "HKEX 官方统计（境外）", "tier": 3, "status": "success", "count": 1,
             "as_of": "2026-10-02", "note": "市场成交额 1234.56 亿港元（http）"},
            {"name": "stealth 浏览器（patchright）", "tier": 4, "status": "skipped",
             "count": 0, "as_of": None, "note": "未开启"},
        ],
        "crosscheck": {"rows": [("恒生指数", 26800.5, 26801.0, 0.0)], "bad": []},
    }


class SectionRenderTests(unittest.TestCase):
    def test_both_themes_render_rows_and_sources(self):
        res = sample_source_result()
        with pipeline.notes_mode():                  # 来源标签属于说明文字：--notes 下必须齐全
            for kit, name in ((pipeline.GUIZANG_KIT, "guizang"), (pipeline.PIXEL_KIT, "pixel")):
                html = kit.hk_quotes_block(res)
                self.assertIn("恒生指数", html, name)
                self.assertIn("645.50", html, name)
                self.assertIn("阿里巴巴-W", html, name)
                self.assertIn("1,234.56", html, name)
                self.assertIn("Yahoo Finance", html, name)
                self.assertIn("YH", html, name)          # 每行标供数来源
                self.assertIn("+BR", html, name)         # 浏览器补齐的字段有标记

    def test_plain_mode_keeps_numbers_but_drops_source_tags(self):
        """入门版（默认）：行情数字一个不少，逐行来源标签 / 数据源脚注不出。"""
        res = sample_source_result()
        for kit, name in ((pipeline.GUIZANG_KIT, "guizang"), (pipeline.PIXEL_KIT, "pixel")):
            html = kit.hk_quotes_block(res)
            self.assertIn("恒生指数", html, name)
            self.assertIn("645.50", html, name)
            self.assertIn("1,234.56", html, name)
            self.assertIn("10-02", html, name)              # 行情日期保留
            self.assertNotIn("Yahoo Finance", html, name)
            self.assertNotIn("+BR", html, name)
            self.assertNotIn("来源</td>", html, name)

    def test_missing_field_renders_dash_not_fabrication(self):
        res = sample_source_result()
        html = pipeline.GUIZANG_KIT.hk_quotes_block(res)
        self.assertIn("—", html)                     # 缺涨跌/成交额 → —，不拿相邻值顶替

    def test_empty_result_renders_nothing(self):
        empty = {"status": "unavailable", "indices": [], "stocks": [], "market": {},
                 "sources": [], "content_date": None}
        self.assertEqual(pipeline.GUIZANG_KIT.hk_quotes_block(empty), "")
        self.assertEqual(pipeline.PIXEL_KIT.hk_quotes_block(empty), "")

    def test_market_missing_discloses_gap(self):
        res = sample_source_result()
        res["market"] = {}
        html = pipeline.GUIZANG_KIT.hk_quotes_block(res)
        self.assertIn("暂缺", html)

    def test_section_wired_into_report_both_themes(self):
        data = {pipeline.HK_OVERSEAS_SOURCE_NAME: sample_source_result()}
        titles = [s[1] for s in pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT)["sections"]]
        self.assertIn(pipeline.SECTION_TITLE_HK_QUOTES, titles)
        order = list(pipeline.REPORT_SECTION_ORDER)
        self.assertEqual(order[order.index("HK QUOTES") - 1], "MARKET REVIEW",
                         "港股行情栏目应紧跟在【及时秋刀鱼】AI 行情复盘之后")
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(data, "2026年10月2日 · 周五", "20261002", theme=theme)
            self.assertIn(pipeline.SECTION_TITLE_HK_QUOTES, html, theme)
            self.assertIn("645.50", html, theme)

    def test_section_absent_when_source_unavailable(self):
        data = {pipeline.HK_OVERSEAS_SOURCE_NAME: {"source": hkx.HK_OVERSEAS_SOURCE,
                                                   "status": "unavailable", "indices": [],
                                                   "stocks": [], "market": {}, "sources": [],
                                                   "content_date": None, "error": "全路失败"}}
        titles = [s[1] for s in pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT)["sections"]]
        self.assertNotIn(pipeline.SECTION_TITLE_HK_QUOTES, titles)

    def test_ai_note_uses_only_section_evidence(self):
        notes = pipeline.build_section_ai_notes({pipeline.HK_OVERSEAS_SOURCE_NAME: sample_source_result()})
        note = notes.get("HK QUOTES")
        self.assertIsNotNone(note, "港股行情栏目应有一行 AI 研判")
        self.assertEqual(note["bull_pct"] + note["bear_pct"], 100)
        self.assertIn("恒生指数", note["text"])
        self.assertLessEqual(note["bull_pct"], 95)
        self.assertGreaterEqual(note["bull_pct"], 5)

    def test_icon_and_freshness_registered(self):
        self.assertIn("HK QUOTES", pipeline._SECTION_ICON_META)
        sys.path.insert(0, str(OUT))
        try:
            import freshness_checker
            self.assertIn(pipeline.HK_OVERSEAS_SOURCE_NAME, freshness_checker.FRESHNESS_THRESHOLDS)
        finally:
            sys.path.pop(0)

    def test_environment_switches(self):
        import os
        with patch.dict(os.environ, {"OCTOPUS_HK_OVERSEAS": "0"}):
            self.assertFalse(pipeline._env_flag("OCTOPUS_HK_OVERSEAS", True))
        with patch.dict(os.environ, {"OCTOPUS_HK_BROWSER": "1"}):
            self.assertTrue(pipeline._env_flag("OCTOPUS_HK_BROWSER", False))
        self.assertTrue(hkx._env_flag("OCTOPUS_HK_OVERSEAS", True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
