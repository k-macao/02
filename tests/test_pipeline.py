"""无需网络的日报新鲜度回归测试。"""
import datetime as dt
import importlib.util
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# pipeline 在导入时只需要 requests 存在；本测试不发出 HTTP 请求。
sys.modules.setdefault("requests", types.SimpleNamespace())
MODULE_PATH = Path(__file__).parents[1] / "output" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


class ReportFreshnessTests(unittest.TestCase):
    def test_render_uses_current_quote_and_never_the_removed_static_quote(self):
        data = {
            "实时行情": pipeline._source_result(
                "test quote", "success", quotes={
                    "标普500": {"price": 6123.45, "change_pct": 1.25, "currency": "USD"}
                }
            ),
            "全球头条": pipeline._source_result("test news", "unavailable", headlines=[], error="offline"),
            "A股资讯": pipeline._source_result("test sina", "unavailable", headlines=[], error="offline"),
        }
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801")
        self.assertIn("6,123", html)
        # 精简排版：缺失品种不出「数据暂缺」行，来源状态压成盘点总结里的一行
        self.assertNotIn("数据暂缺", html)
        self.assertIn("盘点总结", html)
        self.assertRegex(html, r"暂缺：[^<]*全球头条[^<]*A股资讯")
        self.assertNotIn("51,618 -2.19%", html)
        self.assertNotIn("3,813 +0.40%", html)

    def test_duplicate_output_gets_date_and_three_digit_random_name(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "daily_report.html"
            target.write_text("old", encoding="utf-8")
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                actual = pipeline.save_report("new", str(target), {})
            finally:
                pipeline.REPORT_DIR = old_report_dir
            self.assertEqual(target.read_text(encoding="utf-8"), "old")
            self.assertRegex(Path(actual).name, r"daily_report_\d{8}_\d{3}\.html")
            self.assertEqual(Path(actual).read_text(encoding="utf-8"), "new")
            self.assertEqual((Path(directory) / "latest.html").read_text(encoding="utf-8"), "new")

    def test_locked_daily_file_creates_new_timestamped_report(self):
        with tempfile.TemporaryDirectory() as directory:
            requested = str(Path(directory) / "daily_report_20260801.html")
            original_write = pipeline._atomic_write

            def locked_first_write(path, content):
                if path == requested:
                    raise PermissionError("file is locked")
                return original_write(path, content)

            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                with patch.object(pipeline, "_atomic_write", side_effect=locked_first_write):
                    actual = pipeline.save_report("newest", requested, {})
            finally:
                pipeline.REPORT_DIR = old_report_dir

            self.assertNotEqual(actual, requested)
            self.assertRegex(Path(actual).name, r"daily_report_\d{8}_\d{3}\.html")
            self.assertEqual(Path(actual).read_text(encoding="utf-8"), "newest")
            self.assertEqual((Path(directory) / "latest.html").read_text(encoding="utf-8"), "newest")

    # ------------------------------------------------------------------
    # 新版：港股名家频道 + 空区块不渲染 + 当天检验 + 每频道前 3 条
    # ------------------------------------------------------------------
    def _sample_data(self, yt_today=True, market_today=True):
        data = {
            "实时行情": pipeline._source_result(
                "test quote", "success", is_today=market_today, content_date="2026-08-01",
                quotes={
                    "标普500": {"price": 6123.45, "change_pct": 1.25, "currency": "USD"},
                    "上证指数": {"price": 3813.5, "change_pct": 0.4, "currency": "CNY"},
                },
            ),
            "港股名家频道": pipeline._source_result(
                "test channels", "success", is_today=yt_today, content_date="2026-08-01",
                channels=[{
                    "name": "郭思治（郭Sir）",
                    "desc": "香港著名股評人，專注大盤技術走勢。",
                    "url": "https://www.youtube.com/@KwokSirFinance",
                    "is_today": yt_today,
                    "newest_date": "2026-08-01 10:00",
                    "videos": [{
                        "title": "今日市场解读",
                        "video_id": "abc123",
                        "url": "https://www.youtube.com/watch?v=abc123",
                        "published": "2026-08-01T02:00:00+00:00",
                        "published_cst": "2026-08-01 10:00",
                        "is_today": yt_today,
                    }],
                }],
                unsupported=[{
                    "name": "智通財經App（微信公众号）",
                    "desc": "每日推送港股早報與板塊機會。",
                    "note": "微信公众号需登录，暂不支持自动抓取",
                }],
            ),
            "全球头条": pipeline._source_result("test news", "unavailable", headlines=[], error="offline"),
            "A股资讯": pipeline._source_result("test sina", "unavailable", headlines=[], error="offline"),
        }
        return data

    def test_new_layout_renders_channels_section_and_badges(self):
        html = pipeline.generate_report(self._sample_data(), "2026年8月1日 · 周六", "20260801")
        self.assertIn("港股名家频道", html)
        self.assertIn("郭思治（郭Sir）", html)
        self.assertIn("今日市场解读", html)
        self.assertIn("当天", html)          # 当天徽标
        self.assertNotIn("📅 当天内容检验", html)   # 页面不显示检验横幅
        # 需登录/未配置的频道不在日报中渲染
        self.assertNotIn("智通財經App（微信公众号）", html)
        self.assertNotIn("微信公众号需登录", html)

    def test_new_layout_omits_empty_sections_and_keeps_meta(self):
        data = self._sample_data()
        data["港股名家频道"] = pipeline._source_result("test channels", "unavailable",
                                                      channels=[], unsupported=[], error="offline")
        data["全球头条"] = pipeline._source_result("test news", "success", is_today=True,
                                                    content_date="2026-08-01",
                                                    headlines=["一则今天的全球头条"])
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801")
        # 没有数据也没有需登录频道的卡片不渲染主体
        self.assertNotIn("郭思治（郭Sir）", html)
        self.assertNotIn("每个频道列出最新", html)
        # 盘点总结仍一行留痕缺失来源
        self.assertIn("数据覆盖", html)
        self.assertIn("暂缺：", html)
        self.assertIn("港股名家频道", html)
        # 元信息可供 --push-only 二次当天检验
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["date"], "20260801")
        self.assertGreaterEqual(meta["today_sources"], 1)
        self.assertEqual(meta["total_sources"], 9)  # 9 个基础数据源（2026-09-28 新增「港股量化引擎」）；Reddit 趋势跟踪线索另计，本样本未含

    def test_push_eligibility_requires_today_content(self):
        # 有内容但全部非当天 → 不推送
        data = self._sample_data(yt_today=False, market_today=False)
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertFalse(can_push)
        self.assertIn("当天", reason)
        # 有当天内容 → 推送
        can_push, reason = pipeline.check_push_eligibility(self._sample_data(yt_today=True))
        self.assertTrue(can_push)
        # 全部无内容 → 不推送
        empty = {k: pipeline._source_result(k, "unavailable", error="offline")
                 for k in ["实时行情", "港股名家频道", "全球头条", "A股资讯"]}
        can_push, reason = pipeline.check_push_eligibility(empty)
        self.assertFalse(can_push)
        self.assertIn("0/", reason)

    def test_channel_block_shows_only_top3(self):
        ch = {
            "name": "郭思治（郭Sir）", "url": "https://www.youtube.com/@KwokSirFinance",
            "is_today": True, "desc": "測試",
            "videos": [{"title": f"视频{i}", "url": f"https://x/{i}",
                        "published_cst": "2026-08-01 10:00", "is_today": True} for i in range(5)],
        }
        html = pipeline._channel_block(ch)
        # Retro Pixel 风格：每频道只列前 3 条，图标改为 cyber [>> FEED] / >> / ▶ / ■ 等
        # 兼容旧 ▶️ 计数与新风格：以实际渲染的视频标题数量为准
        rendered = sum(1 for i in range(5) if f"视频{i}" in html)
        self.assertEqual(rendered, pipeline.CHANNEL_TOP_N)
        self.assertIn("视频0", html)
        self.assertIn("视频2", html)
        self.assertNotIn("视频3", html)  # 第 4/5 条不展示

    def test_unsupported_channel_block_marks_zhanque(self):
        ch = {"name": "港股交易員（微博大V）", "desc": "測試",
              "note": "微博需登录 / 反爬限制，暂不支持自动抓取"}
        html = pipeline._channel_block(ch)
        self.assertIn("暂缺", html)
        self.assertIn("微博需登录", html)
        # Retro Pixel 风格：无内容时不伪造视频行，Badge 显示 [● 暂缺]
        self.assertNotIn("视频", html)

    def test_fetch_hk_channels_marks_manual_as_unsupported(self):
        # 全部为 manual 频道时：不发起任何请求，返回 unavailable + unsupported 列表
        manual = [{"name": "测试公众号", "desc": "", "kind": "manual",
                   "note": "需登录"}]
        with patch.object(pipeline, "HK_CHANNELS", manual), \
             patch.object(pipeline, "safe_request", return_value=None) as req:
            result = pipeline.fetch_hk_channels()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["channels"], [])
        self.assertEqual(len(result["unsupported"]), 1)
        self.assertEqual(result["unsupported"][0]["name"], "测试公众号")
        req.assert_not_called()  # manual 频道不产生网络请求

    def test_fetch_hk_channels_youtube_and_rss_kinds(self):
        # kind="rss"：safe_request 返回一个 RSS 2.0 文档 → 成功解析
        from datetime import datetime, timedelta
        now_cst = datetime.now(pipeline.CST)
        today_rfc = (now_cst - timedelta(hours=4)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>今日深度报告</title><link>https://example.com/a</link><pubDate>{today_rfc}</pubDate></item>
  <item><title>第二篇</title><link>https://example.com/b</link><pubDate>{today_rfc}</pubDate></item>
</channel></rss>"""
        conf = [
            {"name": "郭思治（郭Sir）", "desc": "", "kind": "youtube", "handle": "@KwokSirFinance"},
            {"name": "港股策略通訊（Substack）", "desc": "", "kind": "rss",
             "feed_url": "https://example.com/feed"},
            {"name": "青姐（胡孟青）", "desc": "", "kind": "manual", "note": "需登录"},
        ]
        with patch.object(pipeline, "HK_CHANNELS", conf), \
             patch.object(pipeline, "resolve_channel_id", return_value=None), \
             patch.object(pipeline, "safe_request", return_value=rss_xml):
            result = pipeline.fetch_hk_channels()
        # rss 成功 1 个；youtube 解析失败进入暂缺；manual 进入暂缺
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["channels"]), 1)
        self.assertEqual(result["channels"][0]["name"], "港股策略通訊（Substack）")
        self.assertEqual(len(result["channels"][0]["videos"]), 2)
        self.assertEqual(len(result["unsupported"]), 2)
        unsupported_names = {u["name"] for u in result["unsupported"]}
        self.assertEqual(unsupported_names, {"青姐（胡孟青）", "郭思治（郭Sir）"})
        self.assertTrue(any("暂缺" in u["note"] for u in result["unsupported"]))

    def test_failed_rss_feed_marks_unsupported_not_silent(self):
        # RSS 源抓取失败 → 进入 unsupported（页面标注暂缺），不会从页面消失
        conf = [{"name": "港股研究社（Bilibili）", "desc": "", "kind": "rss",
                 "feed_url": "https://rsshub.example/bilibili/user/video/1"}]
        with patch.object(pipeline, "HK_CHANNELS", conf), \
             patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_hk_channels()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["channels"], [])
        self.assertEqual(len(result["unsupported"]), 1)
        self.assertIn("暂缺", result["unsupported"][0]["note"])

    def test_rss2_pubdate_parsing(self):
        items = pipeline._parse_rss_items("""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>报告A</title><link>https://a/1</link><pubDate>Fri, 01 Aug 2026 12:00:00 +0800</pubDate></item>
  <item><title>报告B</title><link>https://a/2</link></item>
</channel></rss>""")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "报告A")
        self.assertEqual(items[0]["published_cst"], "2026-08-01 12:00")
        self.assertEqual(items[1]["published_cst"], "—")  # 无时间字段不崩溃

    def test_youtube_rss_parser_marks_today(self):
        # 用 RSS 文本验证解析逻辑（不联网）；日期动态生成，保证任何一天都能跑
        from datetime import datetime, timedelta
        now_cst = datetime.now(pipeline.CST)
        # 用当天/前一天的正午 UTC 时间构造，保证转换回北京时间后一定落在对应日期
        today_utc = f"{now_cst:%Y-%m-%d}T04:00:00+00:00"          # 北京时间当天 12:00
        yesterday_utc = f"{(now_cst - timedelta(days=1)):%Y-%m-%d}T12:00:00+00:00"  # 北京时间前一天 20:00
        rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>今日视频</title>
    <published>{today_utc}</published>
    <yt:videoId>abc123</yt:videoId>
  </entry>
  <entry>
    <title>昨日视频</title>
    <published>{yesterday_utc}</published>
    <yt:videoId>xyz789</yt:videoId>
  </entry>
</feed>"""
        root = pipeline.ET.fromstring(rss)
        videos = []
        for entry in root.findall("a:entry", pipeline.YT_NS):
            title = (entry.findtext("a:title", "", pipeline.YT_NS) or "").strip()
            published = entry.findtext("a:published", "", pipeline.YT_NS) or ""
            pub_cst = pipeline._cst_from_iso(published)
            videos.append({
                "title": title,
                "published_cst": pub_cst.strftime("%Y-%m-%d %H:%M") if pub_cst else "—",
                "is_today": pipeline._date_is_today(pub_cst),
            })
        self.assertTrue(videos[0]["is_today"])   # 当天 10:00 视频
        self.assertFalse(videos[1]["is_today"])  # 昨天视频


class _FakeResp:
    """模拟 PushPlus HTTP 响应。"""

    def __init__(self, code, msg="fake-msg", status_code=200):
        self._code = code
        self._msg = msg
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return {"code": self._code, "msg": self._msg}


class GoogleNewsSourceTests(unittest.TestCase):
    """2026-08-02 新增：全球头条改用 Google News 中文版。"""

    ZH_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item><title>美联储释放降息信号 - 华尔街见闻</title><link>https://news.google.com/a</link><pubDate>Sat, 02 Aug 2026 04:00:00 GMT</pubDate></item>
  <item><title>科技股财报推动股市上涨 - 彭博</title><link>https://news.google.com/b</link><pubDate>Sat, 02 Aug 2026 03:00:00 GMT</pubDate></item>
</channel></rss>"""

    def test_fetch_google_news_uses_chinese_feed(self):
        with patch.object(pipeline, "safe_request", return_value=self.ZH_RSS) as req:
            result = pipeline.fetch_google_news()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "Google News")
        self.assertEqual(result["headlines"][0]["title"], "美联储释放降息信号")
        self.assertEqual(result["headlines"][0]["source"], "华尔街见闻")
        self.assertEqual(result["headlines"][1]["title"], "科技股财报推动股市上涨")
        # 直接抓中文源
        self.assertIn("hl=zh-CN", req.call_args[0][0])

    def test_fetch_google_news_unavailable_marks_error(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_google_news()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["headlines"], [])


class EastmoneySourceTests(unittest.TestCase):
    """2026-08-02 新增：东方财富快讯（5 条最新新闻）与热门榜单（A股/港股/美股成交量前五）。"""

    def test_fetch_eastmoney_news_parses_five_items(self):
        payload = {"data": {"list": [
            {"title": f"<b>东财新闻{i}</b>", "url": f"https://finance.eastmoney.com/a/{i}.html",
             "showTime": "2026-08-02 10:00:00", "summary": f"摘要{i}"}
            for i in range(6)
        ]}}
        with patch.object(pipeline, "safe_request", return_value=payload):
            result = pipeline.fetch_eastmoney_news()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "东方财富")
        self.assertEqual(len(result["headlines"]), 5)          # 只取 5 条
        self.assertNotIn("<b>", result["headlines"][0]["title"])  # 剥掉 HTML 标签
        self.assertEqual(result["headlines"][0]["summary"], "摘要0")

    def test_fetch_eastmoney_news_unavailable(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_eastmoney_news()
        self.assertEqual(result["status"], "unavailable")

    def test_fetch_hot_stocks_parses_three_markets(self):
        requested_page_sizes = []

        def fake_request(url, params=None, **kw):
            requested_page_sizes.append(params["pz"])
            return {"data": {"diff": [
                {"f12": f"60000{i}", "f14": f"股票{i}", "f2": "10.5", "f3": "9.87"}
                for i in range(10)
            ]}}

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_hot_stocks()
        self.assertEqual(result["status"], "success")
        self.assertEqual(requested_page_sizes, [str(pipeline.HOT_STOCK_TOP_N)] * 3)
        self.assertEqual(set(result["markets"].keys()), {"A股", "港股", "美股"})
        self.assertEqual(len(result["markets"]["A股"]["stocks"]), pipeline.HOT_STOCK_TOP_N)
        self.assertEqual(result["markets"]["港股"]["stocks"][0]["code"], "600000")
        self.assertEqual(result["markets"]["美股"]["stocks"][4]["change_pct"], "9.87")

    def test_fetch_hot_stocks_unavailable(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_hot_stocks()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["markets"]["A股"]["stocks"], [])




class NewLayoutRenderingTests(unittest.TestCase):
    """2026-08-02 新增：东财快讯 / 热门榜单渲染（不含 AI 总览表）。"""

    def _rich_data(self):
        data = ReportFreshnessTests()._sample_data()
        data["全球头条"] = pipeline._source_result(
            "Google News", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": "美联储释放降息信号", "source": "华尔街见闻",
                        "url": "", "published_cst": "2026-08-02 10:00", "is_today": True}])
        data["东财快讯"] = pipeline._source_result(
            "东方财富", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": "A股三大指数集体收涨", "url": "", "time": "2026-08-02 15:30",
                        "summary": "沪指涨1.2%", "is_today": True}])
        data["热门榜单"] = pipeline._source_result(
            "东方财富热门榜", "success", is_today=True, content_date="2026-08-02",
            markets={m: {"desc": f"{m}测试", "stocks": [
                {"code": f"00000{i}", "name": f"{m}股票{i}", "price": "10.5", "change_pct": "9.87"}
                for i in range(10)]} for m in ["A股", "港股", "美股"]})
        return data

    def test_report_renders_new_sections(self):
        html = pipeline.generate_report(self._rich_data(), "2026年8月2日 · 周日", "20260802")
        self.assertIn("东方财富快讯", html)
        self.assertIn("A股三大指数集体收涨", html)
        self.assertIn("当天 5/9 源", html)  # 热门榜单只计入盘点总结的数据覆盖
        # 2026-08-06 起不再单独渲染三个成交量榜单栏目，只保留 AI 研判结果
        self.assertNotIn("A股成交量前五", html)
        self.assertNotIn("港股成交量前五", html)
        self.assertNotIn("美股成交量前五", html)
        self.assertIn("美联储释放降息信号", html)
        # 不再渲染 AI 总览相关元素
        self.assertNotIn("AI 总览", html)
        self.assertNotIn("栏目 AI 研判表", html)
        self.assertNotIn("Gemini", html)
        self.assertNotIn("GEMINI", html)
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 9)  # 9 个基础数据源（2026-09-28 新增「港股量化引擎」）；Reddit 趋势跟踪线索另计，本样本未含


class RetroPixelVisualTests(unittest.TestCase):
    """Retro Pixel v3：大图标、明确涨跌与 AI 主结论必须稳定渲染。"""

    def test_trend_badge_uses_color_arrow_and_text_triple_encoding(self):
        up = pipeline._trend_badge(1.25)
        down = pipeline._trend_badge("-2.50%")
        flat = pipeline._trend_badge(0)
        self.assertIn("▲ 涨 +1.25%", up)
        self.assertIn(pipeline.C_GREEN, up)
        self.assertIn("▼ 跌 -2.50%", down)
        self.assertIn(pipeline.C_RED, down)
        self.assertIn("■ 平 0.00%", flat)
        self.assertIn(pipeline.C_AMBER, flat)

    def test_report_prioritizes_pixel_icons_and_ai_core_content(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["实时行情"]["quotes"]["深证成指"] = {
            "price": 12345.67, "change_pct": -2.5, "currency": "CNY"
        }
        # 像素视觉回归固定走 pixel 主题（默认主题自 2026-08-21 起为 guizang）
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802", theme="pixel")

        self.assertIn("OCTOPUS_OS v3.0", html)
        self.assertIn("aria-label=\"章鱼像素图标\"", html)
        self.assertIn("LVL 01 // CONCLUSION", html)  # 结论先行
        self.assertIn("LVL 02 // MARKET SNAPSHOT", html)
        self.assertIn("// POLICY SHOCK", html)
        self.assertIn("// QUANT STRATEGY", html)
        self.assertIn("LVL 08 // WRAP-UP", html)  # 盘点收尾
        self.assertIn("QUANT CORE", html)
        self.assertIn("量化主结论 // QUANT THESIS", html)
        self.assertIn("READ THIS FIRST // 先看结论", html)
        self.assertIn("▲ 涨 +1.25%", html)  # 标普行情
        self.assertIn("▼ 跌 -2.50%", html)  # 深证行情（行情速览：明细数字唯一出处）
        # 2026-09-09 页内去重：TECH READ 不再逐条复述 compact 徽标，只保留聚合
        self.assertIn("指数动能聚合", html)
        self.assertNotIn("明细数值见「行情速览」", html)  # 说明性脚注已移除
        # 逐指数 compact 徽标已从动能区移除；只在页首「今日结论」摘要出现一次
        self.assertEqual(html.count("▼ -2.50%"), 1)
        self.assertLess(html.find("▼ -2.50%"), html.find("LVL 02 // MARKET SNAPSHOT"))
        self.assertIn("▲ 涨 / UP", html)    # 页首方向图例
        self.assertIn("▼ 跌 / DOWN", html)
        self.assertNotIn("<style", html)     # 微信 / PushPlus 仍保持全内联样式

    def test_watch_list_keeps_theme_only_and_omits_stock_rows(self):
        """2026-08-06 起 WATCH LIST // 明日关注 不再列出榜单个股，只保留主题行。"""
        data = NewLayoutRenderingTests()._rich_data()
        # 让舆情命中板块关键词，保证有「明日主题」可展示
        data["全球头条"]["headlines"].append({
            "title": "英伟达AI芯片需求超预期", "source": "测试源",
            "url": "", "published_cst": "2026-08-02 11:00", "is_today": True,
        })
        res = pipeline.build_ai_analysis(data)
        self.assertTrue(res["available"])
        self.assertNotIn("watch", res)          # 不再产出个股清单
        self.assertIn("AI/算力", res["themes"])  # 主题行保留
        html = pipeline._ai_analysis_block(res)
        self.assertIn("QUANT ALLOC // 量化配置", html)
        self.assertIn("★ THEME UNLOCKED // AI/算力", html)
        # 个股不再以「关注清单」形式渲染（榜单股名为 A股股票0 等）
        self.assertNotIn("<b>A股股票", html)


class GuizangThemeTests(unittest.TestCase):
    """默认 guizang 使用简洁白底研报；单列、内联样式与新鲜度元数据继续兼容微信。"""

    def test_default_theme_is_guizang_and_resolves_invalid_to_default(self):
        self.assertEqual(pipeline.DEFAULT_PUSH_THEME, "guizang")
        self.assertEqual(pipeline._resolve_push_theme(None), "guizang")
        self.assertEqual(pipeline._resolve_push_theme(""), "guizang")
        self.assertEqual(pipeline._resolve_push_theme("nonsense"), "guizang")
        self.assertEqual(pipeline._resolve_push_theme("PIXEL"), "pixel")
        self.assertEqual(pipeline._resolve_push_theme("  guizang "), "guizang")

    def test_font_scale_knob_shrinks_every_guizang_size_and_falls_back_safely(self):
        # 系数 1.0 使用新版设计基准：刊头/栏目变小，关键数字维持醒目
        bases = (40, 30, 36, 10, 9)
        self.assertEqual([pipeline._gz_fs(b, scale=1.0) for b in bases], list(bases))
        default = [pipeline._gz_fs(b) for b in bases]
        self.assertEqual(default, [pipeline.GZ_FS_DISPLAY, pipeline.GZ_FS_SECTION,
                                   pipeline.GZ_FS_PRICE, pipeline.GZ_FS_BODY, pipeline.GZ_FS_META])
        self.assertEqual(default, [34, 26, 31, 9, 8])
        self.assertTrue(all(s < b for s, b in zip(default, bases)))
        self.assertTrue(default[0] > default[2] > default[1] > default[3] > default[4])
        # 非法 / 越界输入回落到默认值，且不会把正文压到不可读
        for bad in ("", "  ", "abc", None, "nan", "inf"):
            self.assertEqual(pipeline._resolve_font_scale(bad), pipeline.DEFAULT_FONT_SCALE)
            self.assertGreaterEqual(pipeline._gz_fs(9, scale=bad), pipeline.GZ_FS_FLOOR)
        self.assertEqual(pipeline._resolve_font_scale("0.01"), 0.5)   # 下限夹紧
        self.assertEqual(pipeline._resolve_font_scale("99"), 1.5)     # 上限夹紧
        # 环境变量一处调整即可整体缩放
        with patch.dict(os.environ, {"OCTOPUS_FONT_SCALE": "0.7"}):
            self.assertEqual(pipeline._resolve_font_scale(), 0.7)
            self.assertEqual(pipeline._gz_fs(56), 39)
        # 信号格字号同样走缩放系数
        self.assertEqual(pipeline.gz_meter(3, 5), pipeline.gz_meter(3, 5, size=pipeline.GZ_FS_METER))
        self.assertIn(f"font-size:{pipeline.GZ_FS_METER}px", pipeline.gz_meter(3, 5))

    def test_guizang_page_style_tokens_and_vertical_layout(self):
        data = NewLayoutRenderingTests()._rich_data()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")  # 默认 = guizang
        self.assertIn(f"<title>{pipeline.REPORT_TITLE}</title>", html)
        self.assertIn(pipeline.GZ_PAPER, html)
        self.assertIn(pipeline.GZ_PAPER_TINT, html)   # 白底正文仍保留
        self.assertIn(pipeline.GZ_INK, html)
        for old_color in ("#30342F", "#D5D7D3", "#B7FF3C"):
            self.assertNotIn(old_color, html)
        self.assertIn("max-width:760px;margin:0 auto", html)
        self.assertIn("padding:0 4%", html)               # 流式外边距随视口宽度适配
        self.assertIn('content="width=device-width,initial-scale=1,viewport-fit=cover"', html)
        self.assertIn("padding:24px 0 12px", html)       # 栏目纵向留白收紧
        self.assertIn("line-height:1.85", html)
        self.assertNotIn("user-scalable=no", html)
        self.assertNotIn("●", html)
        self.assertNotIn("○", html)
        self.assertNotIn("SYS_TIME:", html)
        self.assertEqual(html.count("<h1 "), 1)
        self.assertGreater(html.count("<h2 "), 1)
        # 字体：全篇统一圆体（墨水屏适配），短字体栈避免
        # 数十次重复后撑破 PushPlus 10 万字符上限。
        self.assertIn("Yuanti SC", html)
        self.assertIn("PingFang SC", html)
        # 标题 / 正文 / 元信息不再各用各的栈，全篇只有这一条圆体栈
        self.assertEqual(pipeline.GZ_SERIF, pipeline.GZ_SANS)
        self.assertEqual(pipeline.GZ_SANS, pipeline.GZ_MONO)
        families = set(re.findall(r"font-family:[^;\"]*", html))
        self.assertEqual(families, {f"font-family:{pipeline.GZ_FONT}"})
        for gone in ("font-family:monospace", "IBM Plex Mono",
                     "Hiragino Mincho ProN", "Songti SC", "STSong", "SimSun"):
            self.assertNotIn(gone, html)
        # 发丝线与留白
        self.assertIn(pipeline.GZ_HAIR, html)
        # 中文标题，不再重复英文栏目编号。
        self.assertNotIn("01 · QUANT STRATEGY", html)
        self.assertIn("每日量化策略（板块趋势跟踪）</h2>", html)
        self.assertIn("▲ 涨", html)
        # 涨跌三重编码保留（颜色 + 箭头 + 文字）
        self.assertIn("▲ 涨 +1.25%", html)
        self.assertNotIn("OCTOPUS_OS", html)          # 不再是像素主题
        # 微信稳排：刊头单列、无 inline-block 胶囊、无 nowrap 挤爆、无极小英文 kicker
        self.assertNotIn("white-space:nowrap", html)
        self.assertNotIn("display:inline-block", html)
        self.assertNotIn('width="33%"', html)
        # 最小字号不得低于元信息（等价于旧版「无 8px kicker」，随缩放系数自适应）
        sizes = [int(s) for s in re.findall(r"font-size:(\d+)px", html)]
        self.assertTrue(sizes)
        self.assertGreaterEqual(min(sizes), pipeline.GZ_FS_META)
        self.assertIn("bgcolor=", html.lower())
        self.assertIn(f"font-size:{pipeline.GZ_FS_BODY}px", html)      # 普通正文极小
        self.assertIn(f"font-size:{pipeline.GZ_FS_DISPLAY}px", html)    # 缩小后的刊头标题
        self.assertIn(f"font-size:{pipeline.GZ_FS_SECTION}px", html)    # 缩小后的栏目标题

    def test_minimal_news_card_leads_with_title_and_keeps_source(self):
        html = pipeline.gz_headline_row({
            "title": "港股市场观察", "source": "测试来源", "published_cst": "2026-09-08 10:00"
        }, 1)
        self.assertLess(html.index("港股市场观察"), html.index("测试来源"))
        self.assertIn("2026-09-08 10:00", html)
        self.assertNotIn(">01", html)
        self.assertIn("padding:20px 0", html)

    def test_minimal_section_retains_freshness_with_black_title_bar(self):
        html = pipeline.gz_section("01", "MARKET SNAPSHOT", "行情速览", "原始内容",
                                   pipeline.gz_badge("非当天 2026-09-07", "warn"), "数据来源")
        for text in ("行情速览", "原始内容", "非当天 2026-09-07", "数据来源"):
            self.assertIn(text, html)
        self.assertNotIn("MARKET SNAPSHOT", html)
        self.assertNotIn("#30342F", html)
        self.assertLess(html.index("icons/svg/chart.svg"), html.index('bgcolor="#000000"'))
        self.assertRegex(html, r'<td bgcolor="#000000"[^>]*><h2\b')
        self.assertIn('bgcolor="#FFFFFF"', html)  # 图标和内容仍在白底上

    def test_compact_headings_use_white_text_on_black_background(self):
        html = pipeline.generate_report(NewLayoutRenderingTests()._rich_data(),
                                        "2026年8月2日 · 周日", "20260802")
        for level, size in (("h1", pipeline.GZ_FS_DISPLAY), ("h2", pipeline.GZ_FS_SECTION)):
            headings = re.findall(rf'<{level}\b[^>]*>', html)
            self.assertTrue(headings)
            for heading in headings:
                self.assertIn(f'font-size:{size}px', heading)
                self.assertIn(f'background:{pipeline.GZ_INK}', heading)
                self.assertIn(f'color:{pipeline.GZ_PAPER}', heading)
                self.assertIn('font-weight:700', heading)
            # 邮件客户端 CSS 失效时，td 的 bgcolor 仍保留标题底色
            self.assertRegex(html, rf'<td bgcolor="{pipeline.GZ_INK}"[^>]*><{level}\b')
        self.assertEqual(html.count("<h1 "), 1)

    def test_guizang_inline_only_with_remote_koboyo_icons(self):
        data = NewLayoutRenderingTests()._rich_data()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")
        low = html.lower()
        self.assertNotIn("<style", low)
        self.assertNotIn("<script", low)
        images = re.findall(r'<img\b[^>]*>', html)
        # 图片 = 每栏图标 + 刊头图标与横排装饰；全部统一压到最小 16px。
        self.assertEqual(len(images), html.count("<h2 ") + 1 + len(pipeline.KOBOYO_MASTHEAD_ICONS))
        for image in images:
            self.assertRegex(image, r'src="https://koboyo\.com/icons/svg/[a-z-]+\.svg"')
            self.assertIn('alt=""', image)
            self.assertIn('aria-hidden="true"', image)
            self.assertIn('width="16"', image)
            self.assertIn('height="16"', image)
        self.assertNotIn("<svg", low)                 # 只用链接，不内嵌或保存图标
        self.assertNotIn("data:image", low)
        self.assertNotIn("link rel", low)             # 无外部 CSS
        self.assertNotIn("onload", low)
        self.assertNotIn("onclick", low)
        self.assertNotIn("webgl", low)

    def test_eink_reading_contract_black_on_white_bold_and_thick_rules(self):
        """墨水屏（电子墨水 / e-reader）适配契约：无灰底、无发丝线、无细笔画。"""
        html = pipeline.generate_report(NewLayoutRenderingTests()._rich_data(),
                                       "2026年8月2日 · 周日", "20260802")

        # 1) 纯黑白：墨水屏只有黑/白，7% 灰底会抖成脏点
        self.assertEqual(pipeline.GZ_PAPER_TINT, pipeline.GZ_PAPER)
        for color in re.findall(r"(?:bgcolor=|background:|color:)(#[0-9A-Fa-f]{6})", html):
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            self.assertEqual((r, g, b), (r, r, r), color)   # 灰阶可用；标题用纯黑白对比
        self.assertNotIn("#F7F7F7", html)                  # 旧版浅灰底已移除
        self.assertNotIn("rgba(", html)                    # 墨水屏不支持半透明

        # 2) 对比度：正文纯黑，次要文字够深（#6B6B6B 在 16 级灰阶上偏淡）
        self.assertEqual(pipeline.GZ_INK, "#000000")
        self.assertEqual(int(pipeline.GZ_META[1:3], 16), 0x3A)
        self.assertLess(int(pipeline.GZ_META[1:3], 16), 0x60)

        # 3) 分隔线：1px 发丝线在墨水屏上会断裂，改为 2px 中灰
        self.assertEqual(pipeline.GZ_HAIR_W, 2)
        self.assertLessEqual(int(pipeline.GZ_HAIR[1:3], 16), 0xA0)
        self.assertNotIn("1px solid", html)                # 页面内不该再有 1px 线

        # 4) 字重：正文不再是 400 细笔画
        self.assertNotIn("font-weight:400", html)
        self.assertIn(f"font-weight:{pipeline.GZ_W_BODY}", html)
        self.assertIn(f"font-weight:{pipeline.GZ_W_BOLD}", html)
        self.assertEqual(pipeline.GZ_W_BODY, 500)

        # 5) 圆体：全篇一条栈，标题/正文/元信息不再分家
        self.assertIn("Yuanti SC", pipeline.GZ_FONT)
        for old_font in ("Hiragino Mincho ProN", "Songti SC", "STSong", "SimSun", "monospace"):
            self.assertNotIn(old_font, html)

    def test_rounded_grayscale_design_uses_bold_headings(self):
        html = pipeline.generate_report(NewLayoutRenderingTests()._rich_data(), "测试日期", "20260908")
        for color in re.findall(r"#[0-9A-Fa-f]{6}", html):
            self.assertEqual(color[1:3], color[3:5], color)
            self.assertEqual(color[3:5], color[5:7], color)
        for heading in re.findall(r'<h[12]\b[^>]*>', html):
            self.assertIn("Yuanti SC", heading)        # 圆体（墨水屏）
            self.assertIn(pipeline.GZ_FONT, heading)
            self.assertIn("letter-spacing:", heading)
            self.assertIn("font-weight:700", heading)   # 标题统一粗圆体
        for h1 in re.findall(r'<h1\b[^>]*>', html):
            self.assertIn(f"font-size:{pipeline.GZ_FS_DISPLAY}px", h1)   # 刊头更紧凑
        for h2 in re.findall(r'<h2\b[^>]*>', html):
            self.assertIn(f"font-size:{pipeline.GZ_FS_SECTION}px", h2)   # 栏目更紧凑
        # 刊头多图标显示：全部栏目手绘图标在刊头再排一行
        for slug in pipeline.KOBOYO_MASTHEAD_ICONS:
            self.assertIn(f'icons/svg/{slug}.svg', html)
        # 不依赖颜色，涨跌仍然可以分辨。
        self.assertIn("▲ 涨 +1.25%", html)
        self.assertIn("▼ 跌 -1.25%", pipeline.gz_trend_badge(-1.25))
        self.assertIn("■ 平 0.00%", pipeline.gz_trend_badge(0))
        self.assertIn("非当天", pipeline.gz_source_badge({"status": "success"}))

    def test_koboyo_icon_mapping_and_safe_fallback(self):
        for kicker, slug in pipeline.KOBOYO_SECTION_ICONS.items():
            html = pipeline.gz_section("01", kicker, "栏目标题", "正文")
            self.assertIn(f'src="https://koboyo.com/icons/svg/{slug}.svg"', html)
            # 外链不显示时文字标题与内容仍然存在。
            without_images = re.sub(r'<img\b[^>]*>', '', html)
            self.assertIn("栏目标题</h2>", without_images)
            self.assertIn("正文", without_images)
        icon = pipeline.gz_icon('../invalid" onerror="alert(1)', 200)
        self.assertIn('/document.svg"', icon)
        self.assertIn(f'width="{pipeline.GZ_ICON_MAX}"', icon)
        self.assertNotIn('onerror', icon)
        self.assertIn('loading="eager"', pipeline.gz_icon("octopus", 48, masthead=True))
        self.assertIn('loading="lazy"', pipeline.gz_icon("brain"))

    def test_guizang_market_table_becomes_vertical_rowline(self):
        data = ReportFreshnessTests()._sample_data()
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801")
        # 行情速览：三列满宽表（名称 / 最新价 / 涨跌），缺数品种直接不出行
        self.assertIn("6,123", html)                  # 标普500 价格
        self.assertNotIn("数据暂缺", html)
        self.assertNotIn("道琼斯指数", html)
        self.assertIn("名称", html)
        self.assertIn("最新价", html)
        self.assertIn("涨跌", html)
        self.assertIn("全球与美股", html)
        self.assertIn("A股四指数", html)
        self.assertNotIn("港股双指数", html)        # 整组缺失 → 小节缺席
        self.assertIn("table-layout:fixed", html)

    def test_wechat_width_is_in_inline_css_not_only_html_attribute(self):
        data = ReportFreshnessTests()._sample_data()
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801")
        tables = re.findall(r'<table\b[^>]*\bwidth="100%"[^>]*>', html, re.I)
        self.assertGreater(len(tables), 5)
        for tag in tables:
            self.assertIn("width:100%!important", tag)
        # 最外层尤其必须固定为满宽，否则微信清洗 width 属性后会收缩成半屏。
        self.assertRegex(
            html,
            r'<table width="100%"[^>]*style="width:100%!important;',
        )

    def test_guizang_news_lists_wrap_rows_in_table_not_bare_tr(self):
        """全球头条 / 东财快讯 / A股资讯 的 <tr> 必须包在 <table> 里。

        旧版把 gz_headline_row / gz_em_news_row / gz_item_row 产出的裸 <tr>
        直接塞进章节 <div>，微信 / PushPlus 会丢掉行或把序号与标题挤成一团。
        """
        data = NewLayoutRenderingTests()._rich_data()
        data["A股资讯"] = pipeline._source_result(
            "新浪财经", "success", is_today=True, content_date="2026-08-02",
            headlines=["国务院部署进一步释放消费潜力"])
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")
        self.assertNotRegex(html, r"<div[^>]*>\s*<tr\b")
        self.assertIn("美联储释放降息信号", html)
        self.assertIn("A股三大指数集体收涨", html)
        self.assertIn("国务院部署进一步释放消费潜力", html)
        # 刊头三列禁止 break-all，避免日期被微信逐字拆开
        self.assertNotIn("word-break:break-all", html)
        # pixel 主题每行本就是独立 table，同样不能裸 tr
        html_px = pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="pixel")
        self.assertNotRegex(html_px, r"<div[^>]*>\s*<tr\b")

    def test_guizang_never_uses_pixel_palette_colors(self):
        # 回归：AI 盘研判「技术速读」档位词（强势/偏强/震荡/偏弱/弱势）曾误用
        # _ai_band() 携带的像素墨黑底高对比色（#FF5576/#35F29A/#FFD166），
        # 印到暖米白电子纸上会刺眼；guizang 页面必须只出现 GZ_* 色板。
        data = NewLayoutRenderingTests()._rich_data()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")
        self.assertIn("指数动能", html)   # 确认技术速读在场（标普 +1.25% → 偏强，上证 +0.40% → 震荡）
        for leaked in (pipeline.C_RED, pipeline.C_GREEN, pipeline.C_AMBER):
            self.assertNotIn(leaked, html, f"像素主题配色 {leaked} 泄漏进 guizang 页面")
        # 档位词改用 guizang 纸底涨跌/警示色
        self.assertIn(f'color:{pipeline.GZ_UP};">偏强<', html)
        self.assertIn(f'color:{pipeline.GZ_WARN};">震荡<', html)
        # pixel 主题保持原高对比配色不受影响
        html_px = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802", theme="pixel")
        self.assertIn(pipeline.C_GREEN, html_px)
        self.assertIn(pipeline.C_AMBER, html_px)

    def test_theme_parameter_switches_to_pixel(self):
        data = NewLayoutRenderingTests()._rich_data()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802", theme="pixel")
        self.assertIn("OCTOPUS_OS v3.0", html)
        self.assertIn("RETRO PIXEL EDITION", html)
        self.assertNotIn("GUIZANG EDITION", html)
        # guizang 默认页不含像素标识
        html_gz = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")
        self.assertNotIn("OCTOPUS_OS v3.0", html_gz)

    def test_guizang_meta_supports_push_only_freshness_check(self):
        data = ReportFreshnessTests()._sample_data()
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801")
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["date"], "20260801")
        self.assertGreaterEqual(meta["today_sources"], 1)
        self.assertEqual(meta["total_sources"], 9)  # 9 个数据源（含 A股大盘全景与港股量化引擎）


class PushResultTests(unittest.TestCase):
    """推送结果必须明确返回 True/False，且支持 txt/html 模板参数。"""

    def test_push_to_wechat_passes_template_and_returns_true_on_code_200(self):
        calls = {}

        def fake_post(url, json=None, timeout=None):
            calls["url"] = url
            calls["json"] = json
            return _FakeResp(200)

        with patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)):
            ok = pipeline.push_to_wechat("标题", "正文", token="abc", template="txt")
        self.assertTrue(ok)
        self.assertEqual(calls["json"]["template"], "txt")
        self.assertEqual(calls["json"]["token"], "abc")
        self.assertEqual(calls["json"]["title"], "标题")
        self.assertEqual(pipeline.PUSHPLUS_TOPIC, "")  # 默认一对一
        self.assertNotIn("topic", calls["json"])     # 纯文本告警不携带 topic

        with patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)):
            self.assertTrue(pipeline.push_to_wechat("日报", "<p>内容</p>", token="abc"))
        self.assertEqual(calls["json"]["template"], "html")
        self.assertNotIn("topic", calls["json"])     # 日报也不携带 topic

    def test_push_to_wechat_group_topic_can_be_overridden_or_disabled(self):
        """仅显式设置 PUSHPLUS_TOPIC 才发送群组，topic='' 可覆盖为一对一。"""
        calls = []

        def fake_post(url, json=None, timeout=None):
            calls.append(json or {})
            return _FakeResp(200)

        with patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)), \
             patch.object(pipeline, "PUSHPLUS_TOPIC", "custom-group"):
            self.assertTrue(pipeline.push_to_wechat("标题", "正文", token="abc"))
        self.assertEqual(calls[-1]["topic"], "custom-group")

        with patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)), \
             patch.object(pipeline, "PUSHPLUS_TOPIC", ""):
            self.assertTrue(pipeline.push_to_wechat("标题", "正文", token="abc"))
        self.assertNotIn("topic", calls[-1])                 # 一对一不携带 topic

        with patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)), \
             patch.object(pipeline, "PUSHPLUS_TOPIC", "custom-group"):
            self.assertTrue(pipeline.push_to_wechat("标题", "正文", token="abc", topic=""))
        self.assertNotIn("topic", calls[-1])                 # 显式空值优先于环境群组配置

    def test_push_to_wechat_returns_false_on_error_code(self):
        with patch.object(pipeline, "requests",
                          types.SimpleNamespace(post=lambda *a, **kw: _FakeResp(500))):
            self.assertFalse(pipeline.push_to_wechat("t", "body", token="abc"))

    def test_push_to_wechat_non_network_exception_fails_fast(self):
        # 编程错误类异常（非网络异常）不应触发重试：立即失败，不白白等待退避
        calls = []

        def broken_post(*a, **kw):
            calls.append(a)
            raise TypeError("mock signature mismatch")

        sleeps = []
        with patch.object(pipeline, "requests", types.SimpleNamespace(post=broken_post)), \
             patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: sleeps.append(s))):
            self.assertFalse(pipeline.push_to_wechat("t", "body", token="abc"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])

    def test_push_to_wechat_returns_false_when_token_missing(self):
        with patch.object(pipeline, "PUSHPLUS_TOKEN", ""):
            self.assertFalse(pipeline.push_to_wechat("t", "body", token=None))


class PushTruncationTests(unittest.TestCase):
    """PushPlus 内容上限 2 万字：超长 HTML 必须按完整标签边界截断、闭合所有标签，
    并在末尾附截断提示，保证微信端排版正常（2026-08-02 修复整页浅灰/缺内容）。"""

    def _balanced(self, html):
        """简单校验：所有非 void 标签均成对闭合。"""
        stack = []
        for m in pipeline._TAG_RE.finditer(html):
            tag, closing = m.group("tag").lower(), bool(m.group("close"))
            if tag in pipeline._VOID_TAGS:
                continue
            if closing:
                if not stack or stack[-1] != tag:
                    return False
                stack.pop()
            else:
                stack.append(tag)
        return not stack

    def test_oversized_html_truncated_at_tag_boundary_and_balanced(self):
        # 模拟日报结构：外层 table 包裹大量内容块，总长超过 2 万字上限
        block = '<div style="font-size:13px;">段落内容' + "字" * 80 + "</div>"
        html = ("<!DOCTYPE html><html><body>"
                "<table><tr><td>"
                + block * 240
                + "</td></tr></table></body></html>")
        self.assertGreater(len(html), 20000)

        out, truncated = pipeline._truncate_html_for_push(html, limit=20000)
        self.assertTrue(truncated)
        self.assertLessEqual(len(out), 20000)
        self.assertTrue(self._balanced(out))
        self.assertIn("已自动截断", out)
        # 截断不会丢开头内容
        self.assertTrue(out.startswith("<!DOCTYPE html><html><body>"))

    def test_html_within_limit_passes_through(self):
        html = "<html><body><table><tr><td>短内容</td></tr></table></body></html>"
        out, truncated = pipeline._truncate_html_for_push(html, limit=20000)
        self.assertFalse(truncated)
        self.assertEqual(out, html)

    def test_notice_includes_full_report_link_when_report_name_and_repo_known(self):
        html = "<html><body><table><tr><td>" + "字" * 21000 + "</td></tr></table></body></html>"
        with patch.dict(pipeline.os.environ, {"GITHUB_REPOSITORY": "k-macao/02"}):
            out, truncated = pipeline._truncate_html_for_push(
                html, limit=20000, report_name="daily_report_20260802.html")
        self.assertTrue(truncated)
        self.assertIn("daily_report_20260802.html", out)
        self.assertIn("https://raw.githubusercontent.com/k-macao/02/main/output/daily_report_20260802.html", out)
        self.assertLessEqual(len(out), 20000)

    def test_push_to_wechat_sends_truncated_content_within_limit(self):
        calls = {}

        def fake_post(url, json=None, timeout=None):
            calls["json"] = json
            return _FakeResp(200)

        big = "<html><body><table><tr><td>" + "<div>段落</div>" * 3000 + "</td></tr></table></body></html>"
        self.assertGreater(len(big), 20000)
        with patch.object(pipeline, "PUSHPLUS_MAX_CONTENT_CHARS", 20000), \
             patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)):
            ok = pipeline.push_to_wechat("标题", big, token="abc", template="html")
        self.assertTrue(ok)
        sent = calls["json"]["content"]
        self.assertLessEqual(len(sent), 20000)
        self.assertIn("已自动截断", sent)
        self.assertTrue(self._balanced(sent))

    def test_member_limit_default_allows_full_report(self):
        # 账号已升级会员：默认上限 10 万字，当前日报（约 3.3 万字）完整推送、不截断
        self.assertEqual(pipeline.PUSHPLUS_MAX_CONTENT_CHARS, 100000)
        report_path = Path(__file__).parents[1] / "output" / "daily_report_20260802.html"
        if not report_path.exists():
            self.skipTest(f"日报样例文件不存在: {report_path}")
        html = open(report_path, encoding="utf-8").read()
        self.assertGreater(len(html), 20000)
        out, truncated = pipeline._truncate_html_for_push(html)
        self.assertFalse(truncated)
        self.assertEqual(out, html)


class PushMultipartTests(unittest.TestCase):
    """日报超过单条上限（默认 10 万字）时分条完整推送（2026-09-28）。

    旧行为在 10 万字处截断：25 万字的日报只有前四成送达微信，近六成内容每天被丢掉。
    新行为按栏目边界把日报拆成 N 条「各自完整可渲染」的消息，全部送达：
      · 每条都在上限内、标签自闭合、沿用同一份页面外壳（微信端排版与单条推送一致）；
      · 所有栏目按原顺序逐字送达，可见文字零丢失；
      · 每条标题与正文横幅都标明「第 i/N 条」，读者知道还有后续；
      · 任意一条失败即停止并返回 False（调用方发失败告警、Actions 显红），不假装成功。
    """

    # 测试用的单条上限按主题分别取：都必须明显大于该主题的「外壳开销」
    # （刊头 + 页脚 + 闭合标签，guizang ≈5.0k / pixel ≈11.1k），才能真实触发按栏目分条。
    LIMIT = {"guizang": 12000, "pixel": 20000}
    # 比单个栏目还小的上限：逼出「栏目内按标签边界细分」这条兜底路径
    TIGHT = {"guizang": 8000, "pixel": 14000}
    REPORT_NAME = "daily_report_20260928.html"

    # ---------- 工具 ----------
    @staticmethod
    def _data():
        """离线构造的样本数据：够渲染出多个栏目，不发任何网络请求。"""
        return {
            "Reddit": pipeline._public_site_result("Reddit", [
                {"title": f"散户热帖 {i}",
                 "url": "https://www.reddit.com/r/stocks/comments/s0/t0/",
                 "detail": "100 赞 · 20 评论", "published_cst": "2026-09-28 09:00",
                 "community": "r/stocks", "is_today": True} for i in range(5)],
                latest="2026-09-28"),
            "实时行情": pipeline._source_result(
                "quote", "success", is_today=True, content_date="2026-09-28",
                quotes={"标普500": {"price": 6123.45, "change_pct": 1.25}}),
        }

    def _report(self, theme="guizang"):
        """用真实渲染器产出一份带分条标记的日报（两个主题都要能被拆分）。"""
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False), \
             patch.object(pipeline, "HK_QUANT_ENABLED", False):
            return pipeline.generate_report(self._data(), "2026年9月28日 · 周一",
                                            "20260928", theme=theme)

    @staticmethod
    def _visible(html):
        """去掉注释、标签与空白后的可见文字（用于「一个字都不丢」的比对）。"""
        html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
        return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html))

    @staticmethod
    def _balanced(html):
        """所有非 void 标签都成对闭合（半截标签会让微信端整页排版崩坏）。"""
        stack = []
        for m in pipeline._TAG_RE.finditer(html):
            tag, closing = m.group("tag").lower(), bool(m.group("close"))
            if tag in pipeline._VOID_TAGS:
                continue
            if closing:
                if not stack or stack[-1] != tag:
                    return False
                stack.pop()
            else:
                stack.append(tag)
        return not stack

    @staticmethod
    def _body(html):
        """原日报的正文区（第一个分条标记 → 页脚标记之间）。"""
        return html[html.index(pipeline.PART_BREAK_MARK) + len(pipeline.PART_BREAK_MARK):
                    html.index(pipeline.DOC_FOOT_MARK)]

    @staticmethod
    def _sections(html):
        return [s for s in PushMultipartTests._body(html).split(pipeline.PART_BREAK_MARK)
                if s.strip()]

    def _chunks(self, html, parts, limit):
        """从每条消息里剥出「正文块」（去掉外壳、条序横幅与页脚），用于逐字比对。"""
        tail = html[html.index(pipeline.DOC_FOOT_MARK) + len(pipeline.DOC_FOOT_MARK):]
        theme = pipeline._report_theme(html)
        chunks = []
        for index, part in enumerate(parts, 1):
            banner = pipeline._build_part_banner(
                index, len(parts), theme, limit,
                tail_cut=(index == len(parts) and "已自动截断" in part))
            start = part.index(banner) + len(banner)
            chunks.append(part[start:len(part) - len(tail)])
        return chunks

    # ---------- 渲染侧：标记必须存在，否则推送只能退回截断 ----------
    def test_generated_reports_carry_split_marks_in_both_themes(self):
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                html = self._report(theme)
                self.assertGreaterEqual(html.count(pipeline.PART_BREAK_MARK), 3)
                self.assertEqual(html.count(pipeline.DOC_FOOT_MARK), 1)
                self.assertIn(f'name="octopus-theme" content="{theme}"', html)
                # 标记顺序：刊头 → 各栏目 → 页脚 → 闭合标签
                self.assertLess(html.index(pipeline.PART_BREAK_MARK),
                                html.index(pipeline.DOC_FOOT_MARK))
                self.assertTrue(self._balanced(html))
                self.assertGreaterEqual(len(self._sections(html)), 3)

    def test_marks_are_invisible_comments_and_survive_table_hardening(self):
        html = self._report()
        for mark in (pipeline.PART_BREAK_MARK, pipeline.DOC_FOOT_MARK):
            self.assertTrue(mark.startswith("<!--") and mark.endswith("-->"))
        self.assertEqual(pipeline._harden_wechat_table_widths(html).count(pipeline.PART_BREAK_MARK),
                         html.count(pipeline.PART_BREAK_MARK))

    # ---------- 拆分侧：每条都合法、都不超限、内容不丢 ----------
    def test_parts_are_within_limit_and_each_a_complete_balanced_document(self):
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                html, limit = self._report(theme), self.LIMIT[theme]
                self.assertGreater(len(html), limit)          # 确实需要分条
                parts = pipeline._split_html_for_push(html, limit, self.REPORT_NAME)
                self.assertIsNotNone(parts)
                self.assertGreater(len(parts), 1)
                self.assertLessEqual(len(parts), pipeline.PUSHPLUS_MAX_PARTS)
                for index, part in enumerate(parts, 1):
                    with self.subTest(part=index):
                        self.assertLessEqual(len(part), limit)
                        self.assertTrue(self._balanced(part))
                        self.assertTrue(part.startswith("<!DOCTYPE html>"))
                        self.assertTrue(part.rstrip().endswith("</html>"))
                        # 每条都是独立完整的一页：页脚免责声明也在
                        # （guizang 作「仅供参考」，pixel 作「仅供投资参考」）
                        self.assertIn("非投资建议", part)
                        self.assertIn('<meta name="octopus-report-date" content="20260928">', part)

    def test_every_section_is_delivered_verbatim_and_in_order(self):
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                html, limit = self._report(theme), self.LIMIT[theme]
                parts = pipeline._split_html_for_push(html, limit, self.REPORT_NAME)
                sections = self._sections(html)
                stream = "".join(self._chunks(html, parts, limit))
                cursor = 0
                for index, section in enumerate(sections, 1):
                    with self.subTest(section=index):
                        at = stream.find(section, cursor)
                        self.assertGreaterEqual(at, 0, f"第 {index} 栏没送达（内容被丢了）")
                        cursor = at + len(section)             # 顺序也必须与原日报一致
                # 逐字相同：拼接后的正文 == 原日报正文（只少了分条标记本身）
                self.assertEqual(stream,
                                 self._body(html).replace(pipeline.PART_BREAK_MARK, ""))

    def test_visible_text_is_not_lost_even_when_a_section_must_be_cut(self):
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                html, limit = self._report(theme), self.TIGHT[theme]
                parts = pipeline._split_html_for_push(html, limit, self.REPORT_NAME,
                                                      max_parts=400)
                self.assertIsNotNone(parts)
                self.assertTrue(all(len(p) <= limit for p in parts))
                self.assertTrue(all(self._balanced(p) for p in parts))
                self.assertEqual(self._visible("".join(self._chunks(html, parts, limit))),
                                 self._visible(self._body(html)))

    def test_part_banner_and_title_show_sequence(self):
        html, limit = self._report(), self.LIMIT["guizang"]
        parts = pipeline._split_html_for_push(html, limit, self.REPORT_NAME)
        total = len(parts)
        self.assertGreater(total, 1)
        for index, part in enumerate(parts, 1):
            with self.subTest(part=index):
                self.assertIn(f"第 {index}/{total} 条", part)
                self.assertIn(f"（第 {index}/{total} 条）</title>", part)
                if index < total:
                    self.assertIn(f"接下条 {index + 1}/{total}", part)
                else:
                    self.assertNotIn("接下条", part)

    # ---------- 兜底：条数超上限 / 旧版文件 / 外壳过大 ----------
    def test_part_count_cap_stays_honest_about_undelivered_tail(self):
        html, limit = self._report(), self.TIGHT["guizang"]
        parts = pipeline._split_html_for_push(html, limit, self.REPORT_NAME, max_parts=3)
        self.assertIsNotNone(parts)
        self.assertEqual(len(parts), 3)                        # 不超过条数上限
        self.assertTrue(all(len(p) <= limit for p in parts))
        self.assertTrue(all(self._balanced(p) for p in parts))
        self.assertIn("已自动截断", parts[-1])                  # 收尾条如实说明被截断
        self.assertIn("完整日报", parts[-1])                    # 并给出完整版入口
        self.assertIn("已达单次推送条数上限", parts[-1])
        self.assertNotIn("已自动截断", parts[0])                # 前面的条不许谎称截断

    def test_html_without_marks_falls_back_to_truncation(self):
        legacy = ("<html><body><table><tr><td>" + "<div>旧版段落</div>" * 900
                  + "</td></tr></table></body></html>")
        self.assertNotIn(pipeline.PART_BREAK_MARK, legacy)
        self.assertIsNone(pipeline._split_html_for_push(legacy, 6000, "old.html"))
        out, truncated = pipeline._truncate_html_for_push(legacy, 6000, "old.html")
        self.assertTrue(truncated)
        self.assertLessEqual(len(out), 6000)

    def test_shell_bigger_than_limit_returns_none(self):
        html = self._report()
        # 上限连刊头都装不下 → 拆了也没意义，交给截断兜底
        self.assertIsNone(pipeline._split_html_for_push(html, 400, self.REPORT_NAME))

    def test_short_html_is_returned_as_is(self):
        html = self._report()
        self.assertEqual(pipeline._split_html_for_push(html, len(html) + 1), [html])

    # ---------- 推送侧：多条依次发送、失败即停 ----------
    def _push(self, html, responses, limit=None, multipart=True):
        sent, sleeps = [], []
        it = iter(responses)

        def fake_post(url, json=None, timeout=None):
            sent.append(json)
            resp = next(it)
            if isinstance(resp, Exception):
                raise resp
            return resp

        fake_time = types.SimpleNamespace(sleep=lambda s: sleeps.append(s))
        with patch.object(pipeline, "PUSHPLUS_MAX_CONTENT_CHARS", limit or self.LIMIT["guizang"]), \
             patch.object(pipeline, "PUSHPLUS_MULTIPART", multipart), \
             patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)), \
             patch.object(pipeline, "time", fake_time):
            ok = pipeline.push_to_wechat("🐙 章鱼AI日报 09/28 09:00", html,
                                         token="abc", template="html",
                                         report_name=self.REPORT_NAME)
        return ok, sent, sleeps

    def test_push_sends_every_part_with_numbered_titles(self):
        html, limit = self._report(), self.LIMIT["guizang"]
        expected = len(pipeline._split_html_for_push(html, limit, self.REPORT_NAME))
        ok, sent, sleeps = self._push(html, [_FakeResp(200)] * expected, limit=limit)
        self.assertTrue(ok)
        self.assertEqual(len(sent), expected)                  # 每条都真的发出去了
        for index, payload in enumerate(sent, 1):
            with self.subTest(part=index):
                self.assertEqual(payload["title"],
                                 f"🐙 章鱼AI日报 09/28 09:00 ({index}/{expected})")
                self.assertLessEqual(len(payload["content"]), limit)
                self.assertEqual(payload["template"], "html")
                self.assertNotIn("topic", payload)             # 默认仍是一对一
        # 条与条之间按 PUSHPLUS_PART_DELAY 间隔，降低触发频率限制的概率
        self.assertEqual(sleeps.count(pipeline.PUSHPLUS_PART_DELAY), expected - 1)

    def test_push_covers_the_whole_report_not_just_the_first_part(self):
        html, limit = self._report(), self.LIMIT["guizang"]
        expected = len(pipeline._split_html_for_push(html, limit, self.REPORT_NAME))
        ok, sent, _ = self._push(html, [_FakeResp(200)] * expected, limit=limit)
        self.assertTrue(ok)
        delivered = "".join(payload["content"] for payload in sent)
        for section in self._sections(html):
            self.assertIn(section, delivered)                  # 每一栏都在推送流里
        self.assertEqual(self._visible(delivered).count("散户热帖"),
                         self._visible(html).count("散户热帖"))

    def test_push_stops_at_first_failed_part_and_returns_false(self):
        html, limit = self._report(), self.LIMIT["guizang"]
        total = len(pipeline._split_html_for_push(html, limit, self.REPORT_NAME))
        self.assertGreaterEqual(total, 3)
        responses = ([_FakeResp(200), _FakeResp(500, "今日发送次数已达上限")]
                     + [_FakeResp(200)] * total)
        ok, sent, _ = self._push(html, responses, limit=limit)
        self.assertFalse(ok)                                   # 未全部送达 → 失败（Actions 显红）
        self.assertEqual(len(sent), 2)                         # 第 2 条失败后不再发第 3 条

    def test_part_retry_uses_backoff_then_continues(self):
        html, limit = self._report(), self.LIMIT["guizang"]
        total = len(pipeline._split_html_for_push(html, limit, self.REPORT_NAME))
        responses = ([_FakeResp(500, "发送太频繁，请稍后再试"), _FakeResp(200)]
                     + [_FakeResp(200)] * (total - 1))
        ok, sent, sleeps = self._push(html, responses, limit=limit)
        self.assertTrue(ok)
        self.assertEqual(len(sent), total + 1)                 # 第 1 条重试一次后成功
        self.assertIn(pipeline.PUSH_RETRY_BACKOFF[0], sleeps)  # 走的是既有退避节奏

    def test_short_report_still_pushes_as_single_message(self):
        html = self._report()
        ok, sent, sleeps = self._push(html, [_FakeResp(200)], limit=len(html) + 1000)
        self.assertTrue(ok)
        self.assertEqual(len(sent), 1)                         # 不超限就不拆，行为不变
        self.assertEqual(sent[0]["title"], "🐙 章鱼AI日报 09/28 09:00")
        self.assertEqual(sent[0]["content"], html)             # 原样发送，不加横幅
        self.assertEqual(sleeps, [])

    def test_multipart_switch_off_restores_legacy_truncation(self):
        html, limit = self._report(), self.LIMIT["guizang"]
        ok, sent, _ = self._push(html, [_FakeResp(200)], limit=limit, multipart=False)
        self.assertTrue(ok)
        self.assertEqual(len(sent), 1)                         # 只发一条
        self.assertLessEqual(len(sent[0]["content"]), limit)
        self.assertIn("已自动截断", sent[0]["content"])         # 旧行为：截断 + 完整版链接

    def test_txt_alerts_are_never_split(self):
        sent = []

        def fake_post(url, json=None, timeout=None):
            sent.append(json)
            return _FakeResp(200)

        text = "告警正文" * 5000                                # 纯文本告警即使超长也不拆
        with patch.object(pipeline, "PUSHPLUS_MAX_CONTENT_CHARS", 6000), \
             patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)):
            ok = pipeline.push_to_wechat("🐙 告警", text, token="abc", template="txt")
        self.assertTrue(ok)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["content"], text)

    def test_group_topic_is_carried_into_every_part(self):
        html, limit = self._report(), self.LIMIT["guizang"]
        expected = len(pipeline._split_html_for_push(html, limit, self.REPORT_NAME))
        sent = []

        def fake_post(url, json=None, timeout=None):
            sent.append(json)
            return _FakeResp(200)

        with patch.object(pipeline, "PUSHPLUS_MAX_CONTENT_CHARS", limit), \
             patch.object(pipeline, "PUSHPLUS_TOPIC", "oai.1"), \
             patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)), \
             patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
            ok = pipeline.push_to_wechat("🐙 章鱼AI日报 09/28 09:00", html, token="abc",
                                         report_name=self.REPORT_NAME)
        self.assertTrue(ok)
        self.assertEqual(len(sent), expected)
        self.assertTrue(all(p["topic"] == "oai.1" for p in sent))   # 一对多同样分条送达


class PushRetryTests(unittest.TestCase):
    """可恢复错误按退避重试；配额/凭证/未知业务错误不重试（2026-08-01 Actions 显红修复）。"""

    def _run_push(self, responses):
        """依次返回 responses（元素可为 _FakeResp 或 Exception），返回 (结果, 请求数, 等待序列)。"""
        calls, sleeps = [], []
        it = iter(responses)

        def fake_post(url, json=None, timeout=None):
            calls.append(json)
            resp = next(it)
            if isinstance(resp, Exception):
                raise resp
            return resp

        fake_time = types.SimpleNamespace(sleep=lambda s: sleeps.append(s))
        with patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)), \
             patch.object(pipeline, "time", fake_time):
            result = pipeline.push_to_wechat("标题", "正文", token="abc", template="html")
        return result, len(calls), sleeps

    def test_rate_limit_is_retried_then_succeeds(self):
        ok, n_calls, sleeps = self._run_push([
            _FakeResp(500, "发送太频繁，请稍后再试"),
            _FakeResp(200),
        ])
        self.assertTrue(ok)
        self.assertEqual(n_calls, 2)              # 重试一次后成功
        self.assertEqual(sleeps, [10])            # 按 PUSH_RETRY_BACKOFF 的第一个节奏等待

    def test_network_exception_is_retried(self):
        ok, n_calls, sleeps = self._run_push([
            ConnectionError("connection reset"),
            _FakeResp(200),
        ])
        self.assertTrue(ok)
        self.assertEqual(n_calls, 2)
        self.assertEqual(sleeps, [10])

    def test_quota_exhausted_is_not_retried(self):
        ok, n_calls, sleeps = self._run_push([
            _FakeResp(500, "今日发送次数已达上限"),
        ])
        self.assertFalse(ok)
        self.assertEqual(n_calls, 1)              # 配额类错误重试无意义，立即失败
        self.assertEqual(sleeps, [])

    def test_unknown_business_error_fails_fast_without_retry(self):
        ok, n_calls, sleeps = self._run_push([
            _FakeResp(500, "fake-msg"),
        ])
        self.assertFalse(ok)
        self.assertEqual(n_calls, 1)              # 未知业务错误不重试，保持快速失败
        self.assertEqual(sleeps, [])

    def test_transient_error_gives_up_after_all_retries(self):
        ok, n_calls, sleeps = self._run_push([
            _FakeResp(500, "服务器繁忙，请稍后再试"),
            _FakeResp(500, "发送太频繁，请稍后再试"),
            _FakeResp(500, "请求频率过高"),
            _FakeResp(500, "服务器繁忙，请稍后再试"),
        ])
        self.assertFalse(ok)
        self.assertEqual(n_calls, 1 + len(pipeline.PUSH_RETRY_BACKOFF))  # 首次+全部重试
        self.assertEqual(sleeps, list(pipeline.PUSH_RETRY_BACKOFF))

    def test_failure_kind_classification(self):
        k = pipeline._push_failure_kind
        self.assertEqual(k(None, 500, "发送太频繁，请稍后再试"), "transient")
        self.assertEqual(k(None, 500, "今日发送次数已达上限"), "fatal")
        self.assertEqual(k(None, 500, "token错误"), "fatal")
        self.assertEqual(k(None, 500, "内容包含敏感词"), "fatal")
        self.assertEqual(k(None, 500, "fake-msg"), "unknown")
        self.assertEqual(k(503, 500, "fake-msg"), "transient")   # HTTP 5xx 始终可重试
        self.assertEqual(k(429, None, ""), "transient")
        self.assertEqual(k(401, None, ""), "fatal")


class PushFailureAlertTests(unittest.TestCase):
    """日报推送失败后的兜底告警：微信侧能直接看到原因与处理建议。"""

    def test_failure_alert_text_has_reason_advice_and_file(self):
        data = {
            "全球头条": pipeline._source_result("n", "success", is_today=True,
                                                 content_date="2026-08-01", headlines=["今日头条"]),
            "A股资讯": pipeline._source_result("s", "unavailable", headlines=[], error="offline"),
        }
        text = pipeline.build_push_failure_alert_text(
            "日报 HTML 多次推送均被 PushPlus 拒绝（详见上方 code/msg）",
            data, "/tmp/daily_report_20260801.html")
        self.assertIn("推送到微信失败", text)
        self.assertIn("PushPlus 拒绝", text)
        self.assertIn("1/2 个来源为当天内容", text)     # 说明日报内容本身无问题
        self.assertIn("发送频繁", text)                  # 给出频率限制处理建议
        self.assertIn("额度", text)                      # 给出配额处理建议
        self.assertIn("PUSHPLUS_TOKEN", text)            # 给出 token 失效处理建议
        self.assertIn("daily_report_20260801.html", text)

    def test_failure_alert_uses_txt_template_and_time_title(self):
        calls = {}

        def fake_post(url, json=None, timeout=None):
            calls.update(json or {})
            return _FakeResp(200)

        with patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)):
            ok = pipeline.push_failure_alert("测试原因", report_path="/tmp/x.html", token="abc")
        self.assertTrue(ok)
        self.assertEqual(calls["template"], "txt")
        self.assertNotIn("topic", calls)
        self.assertRegex(calls["title"], r"日报推送失败提醒 \d{2}/\d{2} \d{2}:\d{2}")
        self.assertIn("测试原因", calls["content"])


class NoPushAlertTests(unittest.TestCase):
    """当天检验未通过时的纯文本告警内容。"""

    def test_alert_text_lists_each_source_and_manual_actions(self):
        data = {
            "实时行情": pipeline._source_result("q", "success", is_today=False,
                                                content_date="2026-07-31", quotes={}),
            "全球头条": pipeline._source_result("n", "unavailable", headlines=[], error="offline"),
        }
        text = pipeline.build_no_push_alert_text("抓到 1/2 个来源，但没有一个属于当天内容",
                                                 data, "/tmp/daily_report_20260801.html")
        self.assertIn("当天内容检验未通过", text)
        self.assertIn("抓到 1/2 个来源", text)
        self.assertIn("实时行情：🕓 非当天（数据日期 2026-07-31）", text)
        self.assertIn("全球头条：⚠️ 无数据", text)
        self.assertIn("force_push", text)                      # 给出人工处理入口
        self.assertIn("daily_report_20260801.html", text)      # 报告文件可追溯

    def test_no_push_alert_is_one_to_one_by_default(self):
        calls = {}

        def fake_post(url, json=None, timeout=None):
            calls.update(json or {})
            return _FakeResp(200)

        with patch.object(pipeline, "requests", types.SimpleNamespace(post=fake_post)):
            self.assertTrue(pipeline.push_no_push_alert("无当天数据", {}, token="abc"))
        self.assertEqual(calls["template"], "txt")
        self.assertNotIn("topic", calls)


class MainExitCodeTests(unittest.TestCase):
    """main() 退出码：应推未推成 → 1；有意跳过 / 推送成功 / 告警送达 → 0。"""

    def _today_data(self):
        return {
            "全球头条": pipeline._source_result("n", "success", is_today=True,
                                                 content_date="2026-08-01", headlines=["今日头条"]),
            "A股资讯": pipeline._source_result("s", "unavailable", headlines=[], error="offline"),
        }

    def _stale_data(self):
        return {
            "实时行情": pipeline._source_result("q", "success", is_today=False,
                                                content_date="2026-07-31", quotes={}),
        }

    def _run_main(self, argv, data, push_result):
        with tempfile.TemporaryDirectory() as directory:
            def fake_save(html, output_path=None, data=None):
                path = Path(directory) / "daily_report_test.html"
                path.write_text(html, encoding="utf-8")
                return str(path)

            with patch.object(sys, "argv", argv), \
                 patch.object(pipeline, "collect_all_data", return_value=data), \
                 patch.object(pipeline, "generate_report", return_value="<html>ok</html>"), \
                 patch.object(pipeline, "save_report", side_effect=fake_save), \
                 patch.object(pipeline, "clean_old_html_reports", return_value=(0, False)), \
                 patch.object(pipeline, "push_to_wechat", return_value=push_result):
                return pipeline.main()

    def test_push_success_returns_zero(self):
        self.assertEqual(self._run_main(["pipeline.py"], self._today_data(), True), 0)

    def test_push_failure_returns_one(self):
        self.assertEqual(self._run_main(["pipeline.py"], self._today_data(), False), 1)

    def test_no_push_flag_returns_zero_even_if_push_would_fail(self):
        self.assertEqual(
            self._run_main(["pipeline.py", "--no-push"], self._today_data(), False), 0)

    def test_check_failed_but_alert_delivered_returns_zero(self):
        # 检验未通过 → 不发日报；告警（同样走 push_to_wechat 的 mock）送达 → 0
        self.assertEqual(self._run_main(["pipeline.py"], self._stale_data(), True), 0)

    def test_check_failed_and_alert_failed_returns_one(self):
        # 检验未通过且告警也发不出去（例如 token 未配置）→ 1，Actions 标红
        self.assertEqual(self._run_main(["pipeline.py"], self._stale_data(), False), 1)

    def test_force_push_failure_returns_one(self):
        self.assertEqual(
            self._run_main(["pipeline.py", "--force-push"], self._stale_data(), False), 1)


class CleanOldReportsTests(unittest.TestCase):
    """2026-08-02 新增：手动/自动推送前必须清理历史 HTML 报告。

    避免历史残留文件（含旧版本特征）被 latest.html 引用或被 --push-only 误推。
    清理函数 clean_old_html_reports 是 main() 正常流程的第一步（--dry-run 跳过）。
    """

    def _seed_reports(self, directory):
        """在测试目录里放几份旧报告 + latest.html，返回它们的路径。"""
        files = [
            "daily_report_20260801.html",
            "daily_report_20260802_20260802_069.html",
            "daily_report_20260802_20260802_098.html",
            "daily_report_20260802_20260802_243.html",
            "latest.html",
        ]
        created = []
        for name in files:
            p = Path(directory) / name
            p.write_text(f"OLD-CONTENT-{name}", encoding="utf-8")
            created.append(p)
        return created

    def test_clean_old_html_reports_removes_daily_reports_and_latest(self):
        """默认行为：删除全部 daily_report_*.html 和 latest.html。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                deleted, latest_deleted = pipeline.clean_old_html_reports()
            finally:
                pipeline.REPORT_DIR = old_report_dir
            self.assertEqual(deleted, 4)
            self.assertTrue(latest_deleted)
            # 目录里现在应只剩 pipeline 自身的非 HTML 文件
            remaining = list(Path(directory).glob("*.html"))
            self.assertEqual(remaining, [], f"应无 HTML 残留，实际: {remaining}")

    def test_clean_old_html_reports_keep_latest_keeps_latest(self):
        """keep_latest=True 时保留 latest.html，仅清 daily_report_*.html。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                deleted, latest_deleted = pipeline.clean_old_html_reports(keep_latest=True)
            finally:
                pipeline.REPORT_DIR = old_report_dir
            self.assertEqual(deleted, 4)
            self.assertFalse(latest_deleted)
            # latest.html 仍存在
            self.assertTrue((Path(directory) / "latest.html").is_file())
            self.assertTrue((Path(directory) / "latest.html").read_text(
                encoding="utf-8").startswith("OLD-CONTENT-latest.html"))

    def test_clean_old_html_reports_on_empty_directory(self):
        """空目录：不报错，返回 (0, False)。"""
        with tempfile.TemporaryDirectory() as directory:
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                deleted, latest_deleted = pipeline.clean_old_html_reports()
            finally:
                pipeline.REPORT_DIR = old_report_dir
            self.assertEqual(deleted, 0)
            self.assertFalse(latest_deleted)

    def test_clean_old_html_reports_ignores_non_html_files(self):
        """清理只匹配 .html，不动其他扩展名文件。"""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "daily_report_20260801.html").write_text("old", encoding="utf-8")
            (Path(directory) / "notes.txt").write_text("keep me", encoding="utf-8")
            (Path(directory) / "data.json").write_text("{}", encoding="utf-8")
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                pipeline.clean_old_html_reports()
            finally:
                pipeline.REPORT_DIR = old_report_dir
            # HTML 被清，txt/json 保留
            self.assertFalse((Path(directory) / "daily_report_20260801.html").exists())
            self.assertTrue((Path(directory) / "notes.txt").exists())
            self.assertTrue((Path(directory) / "data.json").exists())

    def test_main_normal_flow_calls_clean_before_collect(self):
        """main() 正常流程：必须在 collect_all_data 之前调用 clean_old_html_reports。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            call_order = []

            original_collect = pipeline.collect_all_data
            original_clean = pipeline.clean_old_html_reports

            def tracking_clean(*a, **kw):
                call_order.append("clean")
                return original_clean(*a, **kw)

            def tracking_collect():
                call_order.append("collect")
                return original_collect()

            def fake_save(html, output_path=None, data=None):
                p = Path(directory) / "daily_report_test.html"
                p.write_text(html, encoding="utf-8")
                return str(p)

            try:
                pipeline.REPORT_DIR = directory
                with patch.object(sys, "argv", ["pipeline.py"]), \
                     patch.object(pipeline, "collect_all_data",
                                  side_effect=tracking_collect), \
                     patch.object(pipeline, "clean_old_html_reports",
                                  side_effect=tracking_clean), \
                     patch.object(pipeline, "generate_report",
                                  return_value="<html>ok</html>"), \
                     patch.object(pipeline, "save_report", side_effect=fake_save), \
                     patch.object(pipeline, "push_to_wechat", return_value=True):
                    pipeline.main()
            finally:
                pipeline.REPORT_DIR = old_report_dir

            self.assertEqual(call_order, ["clean", "collect"],
                             "清理必须在采集之前执行，避免最新报告被旧文件污染")

    def test_main_dry_run_skips_clean(self):
        """--dry-run 模式：不清理（不写文件，清理无意义且会产生空目录警告）。"""
        with tempfile.TemporaryDirectory() as directory:
            self._seed_reports(directory)
            old_report_dir = pipeline.REPORT_DIR
            original_clean = pipeline.clean_old_html_reports
            clean_called = []

            def tracking_clean(*a, **kw):
                clean_called.append(True)
                return original_clean(*a, **kw)

            try:
                pipeline.REPORT_DIR = directory
                with patch.object(sys, "argv", ["pipeline.py", "--dry-run"]), \
                     patch.object(pipeline, "collect_all_data", return_value={}), \
                     patch.object(pipeline, "clean_old_html_reports",
                                  side_effect=tracking_clean):
                    pipeline.main()
            finally:
                pipeline.REPORT_DIR = old_report_dir

            self.assertEqual(clean_called, [],
                             "--dry-run 不应调用 clean_old_html_reports")
            # 旧文件应原封不动
            self.assertTrue((Path(directory) / "daily_report_20260801.html").exists())
            self.assertTrue((Path(directory) / "latest.html").exists())


class MarketPanoramaTests(unittest.TestCase):
    """2026-09-08 新增：A股大盘全景复盘（指数表现 / 涨跌家数 / 成交额 / 北向资金 / 板块热力）。

    全部用 fake safe_request 按 URL 分发，不发真实网络请求。
    """

    QUOTE_TS = int(pipeline.datetime(2026, 9, 8, 15, 0, tzinfo=pipeline.CST).timestamp())

    @staticmethod
    def _indices_diff():
        # f12 代码与 PANORAMA_INDEX_SPECS 一一对应；三大载体指数附带市场宽度统计
        return [
            {"f12": "000001", "f14": "上证指数", "f2": 3123.45, "f3": 1.25, "f4": 38.50,
             "f6": 5.1e11, "f17": 3090.0, "f15": 3130.0, "f16": 3081.0, "f18": 3084.95,
             "f104": 1800, "f105": 500, "f106": 60, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "399001", "f14": "深证成指", "f2": 10456.78, "f3": -0.62, "f4": -65.30,
             "f6": 6.2e11, "f17": 10500.0, "f15": 10580.0, "f16": 10400.0, "f18": 10522.08,
             "f104": 2100, "f105": 700, "f106": 80, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "399006", "f14": "创业板指", "f2": 2101.23, "f3": 2.10, "f4": 43.19,
             "f6": 3.0e11, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "000688", "f14": "科创50", "f2": 901.10, "f3": 0.0, "f4": 0.0,
             "f6": 8.0e10, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "899050", "f14": "北证50", "f2": 801.50, "f3": 0.85, "f4": 6.76,
             "f6": 8.0e9, "f104": 150, "f105": 100, "f106": 10,
             "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "000300", "f14": "沪深300", "f2": 3980.20, "f3": 0.90, "f4": 35.54,
             "f6": 2.9e11, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "000016", "f14": "上证50", "f2": 2601.30, "f3": 0.55, "f4": 14.22,
             "f6": 1.1e11, "f124": MarketPanoramaTests.QUOTE_TS},
            {"f12": "000905", "f14": "中证500", "f2": 5902.40, "f3": 1.10, "f4": 64.20,
             "f6": 2.2e11, "f124": MarketPanoramaTests.QUOTE_TS},
        ]

    @staticmethod
    def _sector_rows(po):
        sign = 1 if po == "1" else -1
        return [
            {"f12": f"BK10{i}", "f14": f"板块{i}", "f3": sign * (3.5 - i * 0.3),
             "f62": 1.5e9 - i * 1e8, "f104": 30 - i, "f105": 5 + i,
             "f128": f"领涨股{i}", "f136": 9.9 - i}
            for i in range(pipeline.PANORAMA_SECTOR_TOP_N)
        ]

    def _install_fake_requests(self, with_kline=True, with_hsgt=True, with_sectors=True):
        def fake(url, params=None, **kw):
            if "ulist.np" in url:
                return {"data": {"diff": self._indices_diff()}}
            if "stock/kline" in url:
                if not with_kline:
                    return None
                base = {"1.000001": 4.8e11, "0.399001": 6.0e11, "0.899050": 7.0e9}[
                    (params or {}).get("secid")]
                return {"data": {"klines": [f"2026-09-07,{base}", f"2026-09-08,{base * 1.05:.0f}"]}}
            if "datacenter-web.eastmoney.com" in url:
                if not with_hsgt:
                    return None
                return {"result": {"data": [
                    {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 135025.0},
                    {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 8850.0},
                ]}}
            if "clist/get" in url:
                if not with_sectors:
                    return None
                return {"data": {"diff": self._sector_rows((params or {}).get("po"))}}
            return None
        return patch.object(pipeline, "safe_request", side_effect=fake)

    # ------------------------------------------------------------------
    # 采集层
    # ------------------------------------------------------------------
    def test_fetch_market_panorama_parses_all_blocks(self):
        with self._install_fake_requests():
            result = pipeline.fetch_market_panorama()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["source"], "东方财富·A股全景")
        self.assertEqual(result["content_date"], "2026-09-08")
        self.assertEqual(result["quote_time"], "2026-09-08 15:00:00")
        self.assertEqual(result["is_today"], pipeline._today_display() == "2026-09-08")

        # ① 指数表现：按 spec 顺序保留八大宽基，名称统一为正式中文名
        self.assertEqual(len(result["indices"]), 8)
        self.assertEqual([i["name"] for i in result["indices"]],
                         [label for _, label in pipeline.PANORAMA_INDEX_SPECS])
        self.assertEqual(result["indices"][0]["price"], 3123.45)
        self.assertEqual(result["indices"][0]["chg_pct"], 1.25)

        # ② 涨跌家数：沪深京三市合计 + 涨跌比 + 情绪定调
        b = result["breadth"]
        self.assertEqual((b["up"], b["down"], b["flat"]), (4050, 1300, 150))
        self.assertEqual(b["ratio"], 3.12)
        self.assertEqual(b["mood"], "普涨强势")
        self.assertFalse(b["partial"])

        # ③ 成交额：沪深京合计 + 上一交易日环比（K 线末根日期==报价日时取前一根）
        t = result["turnover"]
        self.assertAlmostEqual(t["total"], 5.1e11 + 6.2e11 + 8.0e9)
        self.assertAlmostEqual(t["sh_sz"], 5.1e11 + 6.2e11)
        self.assertAlmostEqual(t["prev_total"], 4.8e11 + 6.0e11 + 7.0e9)
        self.assertAlmostEqual(t["chg_pct"], (t["total"] / t["prev_total"] - 1) * 100, places=6)

        # ④ 南北向资金：RPT_MUTUAL_DEAL_HISTORY 的 005/006 成交总额（百万元→亿元）
        north = result["north"]
        self.assertTrue(north["available"])
        self.assertEqual(north["amount_yi"], 1350.25)
        self.assertEqual(north["date"], "2026-09-08")
        self.assertTrue(north["south_available"])
        self.assertEqual(north["south_amount_yi"], 88.50)
        self.assertEqual(north["south_date"], "2026-09-08")
        self.assertIn("2024-08-19", north["policy_note"])

        # ⑤ 板块热力：领涨 TOP 涨幅降序、领跌 TOP 跌幅最深在前
        leading = result["sectors"]["leading"]
        lagging = result["sectors"]["lagging"]
        self.assertEqual(len(leading), pipeline.PANORAMA_SECTOR_TOP_N)
        self.assertEqual([r["chg_pct"] for r in leading],
                         sorted((r["chg_pct"] for r in leading), reverse=True))
        self.assertEqual([r["chg_pct"] for r in lagging],
                         sorted((r["chg_pct"] for r in lagging)))
        self.assertEqual(leading[0]["lead_stock"], "领涨股0")
        self.assertEqual(leading[0]["main_inflow"], 1.5e9)

    def test_fetch_market_panorama_unavailable_when_quote_request_fails(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_market_panorama()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["indices"], [])
        self.assertIsNone(result["breadth"])
        self.assertIsNone(result["turnover"])

    def test_fetch_market_panorama_degrades_per_subblock(self):
        # 指数 / 宽度在线，K 线、北向、板块全挂：整体仍 success，对应子块缺席并标 partial
        with self._install_fake_requests(with_kline=False, with_hsgt=False, with_sectors=False):
            result = pipeline.fetch_market_panorama()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["indices"]), 8)
        self.assertIsNotNone(result["turnover"])
        self.assertIsNone(result["turnover"]["prev_total"])
        self.assertIsNone(result["turnover"]["chg_pct"])
        self.assertFalse(result["north"]["available"])
        self.assertFalse(result["north"]["south_available"])
        self.assertEqual(result["sectors"], {"leading": [], "lagging": []})
        self.assertTrue(result["partial"])
        self.assertIn("北向", result["error"])
        self.assertIn("南向", result["error"])
        self.assertIn("板块热力", result["error"])

    def test_breadth_mood_thresholds(self):
        self.assertEqual(pipeline._panorama_breadth_mood(2.0), "普涨强势")
        self.assertEqual(pipeline._panorama_breadth_mood(1.2), "偏多震荡")
        self.assertEqual(pipeline._panorama_breadth_mood(0.8), "多空均衡")
        self.assertEqual(pipeline._panorama_breadth_mood(0.5), "偏空承压")
        self.assertEqual(pipeline._panorama_breadth_mood(0.49), "普跌弱势")
        self.assertEqual(pipeline._panorama_breadth_mood(None), "数据不足")

    def test_northbound_previous_close_selection_when_latest_row_is_today(self):
        """最新行日期==今天时，取它前一行作为「前一收盘」（南向同规则）。"""
        payload = {"result": {"data": [
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-04 00:00:00", "DEAL_AMT": 10000.0},
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-07 00:00:00", "DEAL_AMT": 20000.0},
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 30000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-04 00:00:00", "DEAL_AMT": 1000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-07 00:00:00", "DEAL_AMT": 2000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 3000.0},
        ]}}
        with patch.object(pipeline, "safe_request", return_value=payload), \
             patch.object(pipeline, "_today_display", return_value="2026-09-08"):
            north = pipeline._fetch_panorama_northbound()
        self.assertTrue(north["available"])
        self.assertEqual(north["date"], "2026-09-07")
        self.assertEqual(north["amount_yi"], 200.0)   # 20000 百万元 ÷ 100
        self.assertTrue(north["south_available"])
        self.assertEqual(north["south_date"], "2026-09-07")
        self.assertEqual(north["south_amount_yi"], 20.0)

    def test_northbound_uses_last_row_when_latest_is_not_today(self):
        """最新行不是今天（盘前/非交易日/休市）时，最后一行即最近完整交易日。"""
        payload = {"result": {"data": [
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-04 00:00:00", "DEAL_AMT": 10000.0},
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-07 00:00:00", "DEAL_AMT": 20000.0},
            {"MUTUAL_TYPE": "005", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 30000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-04 00:00:00", "DEAL_AMT": 1000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-07 00:00:00", "DEAL_AMT": 2000.0},
            {"MUTUAL_TYPE": "006", "TRADE_DATE": "2026-09-08 00:00:00", "DEAL_AMT": 3000.0},
        ]}}
        with patch.object(pipeline, "safe_request", return_value=payload), \
             patch.object(pipeline, "_today_display", return_value="2026-09-09"):
            north = pipeline._fetch_panorama_northbound()
        self.assertTrue(north["available"])
        self.assertEqual(north["date"], "2026-09-08")
        self.assertEqual(north["amount_yi"], 300.0)
        self.assertEqual(north["south_date"], "2026-09-08")
        self.assertEqual(north["south_amount_yi"], 30.0)

    def test_format_amount_keeps_minus_sign_for_main_outflow(self):
        # 板块主力净流入（f62）常为负：负号必须保留，不能只显示绝对值或原始大数
        self.assertEqual(pipeline._format_amount(-1.2e9), "-12.00亿")
        self.assertEqual(pipeline._format_amount(-8.0e4), "-8.00万")
        self.assertEqual(pipeline._format_amount(-500), "-500.00")
        # 非负值行为保持不变
        self.assertEqual(pipeline._format_amount(1.5e9), "15.00亿")
        self.assertEqual(pipeline._format_amount("—"), "—")

    # ------------------------------------------------------------------
    # 渲染层
    # ------------------------------------------------------------------
    def _panorama_payload(self):
        return pipeline._source_result(
            "东方财富·A股全景", "success", is_today=True, content_date="2026-09-08",
            indices=[
                {"code": "000001", "name": "上证指数", "price": 3123.45, "chg_pct": 1.25,
                 "amount": 5.1e11, "chg": 38.50},
                {"code": "399001", "name": "深证成指", "price": 10456.78, "chg_pct": -0.62,
                 "amount": 6.2e11, "chg": -65.30},
            ],
            breadth={"up": 4050, "down": 1300, "flat": 150, "ratio": 3.12,
                     "mood": "普涨强势", "partial": False,
                     "markets": {"沪": {"up": 1800, "down": 500, "flat": 60},
                                 "深": {"up": 2100, "down": 700, "flat": 80},
                                 "京": {"up": 150, "down": 100, "flat": 10}}},
            turnover={"total": 1.138e12, "sh_sz": 1.13e12, "prev_total": 1.087e12,
                      "chg_pct": 4.69,
                      "by_market": {"沪": 5.1e11, "深": 6.2e11, "京": 8.0e9},
                      "partial": False},
            north={"available": True, "amount_yi": 1350.25, "date": "2026-09-08",
                   "south_available": True, "south_amount_yi": 88.50,
                   "south_date": "2026-09-08",
                   "policy_note": pipeline.PANORAMA_NORTH_POLICY_NOTE, "error": None},
            sectors={
                "leading": [{"code": "BK100", "name": "领涨板块甲", "chg_pct": 3.50,
                             "main_inflow": 1.5e9, "lead_stock": "领涨牛股", "lead_stock_pct": 9.9}],
                "lagging": [{"code": "BK200", "name": "领跌板块乙", "chg_pct": -2.10,
                             "main_inflow": -8.0e8, "lead_stock": "领跌熊股", "lead_stock_pct": -6.5}],
            },
            quote_time="2026-09-08 15:00:00")

    def test_panorama_section_renders_in_guizang_theme(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = self._panorama_payload()
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908")
        self.assertIn("A股大盘全景复盘", html)
        self.assertIn("指数表现", html)
        self.assertIn("上证指数", html)
        self.assertIn("3,123.45", html)
        self.assertIn("涨跌家数", html)
        self.assertIn("4,050 家", html)
        self.assertIn("沪深京合计", html)
        self.assertIn("普涨强势", html)
        self.assertIn("3.12", html)
        self.assertIn("成交额", html)
        self.assertIn("南北向资金（前一收盘）", html)
        self.assertIn("北向资金", html)
        self.assertIn("1,350.25 亿元", html)
        self.assertIn("南向成交总额", html)
        self.assertIn("88.50 亿元", html)
        self.assertNotIn("2024-08-19", html)       # 披露口径说明已精简
        self.assertIn("板块热力", html)
        self.assertIn("领涨板块甲", html)
        self.assertIn("领跌板块乙", html)
        self.assertIn("领涨牛股", html)
        # guizang 页面只允许 GZ_* 色板，像素主题高对比色不得泄漏
        for leaked in (pipeline.C_RED, pipeline.C_GREEN, pipeline.C_AMBER,
                       pipeline.C_LEMON, pipeline.C_CYAN):
            self.assertNotIn(leaked, html, f"像素主题配色 {leaked} 泄漏进 guizang 页面")

    def test_panorama_section_renders_in_pixel_theme(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = self._panorama_payload()
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908", theme="pixel")
        self.assertIn("A股大盘全景复盘", html)
        self.assertIn("指数表现", html)
        self.assertIn("涨跌家数", html)
        self.assertIn("▲ 上涨 4,050 家", html)
        self.assertIn("普涨强势", html)
        self.assertIn("南北向资金（前一收盘）", html)
        self.assertIn("北向资金", html)
        self.assertIn("南向成交总额", html)
        self.assertIn("1,350.25 亿元", html)
        self.assertIn("88.50 亿元", html)
        self.assertIn("板块热力", html)
        self.assertIn("领涨板块甲", html)

    def test_panorama_section_absent_and_audited_when_unavailable(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = pipeline._source_result(
            "东方财富·A股全景", "unavailable", indices=[], breadth=None, turnover=None,
            north={"available": False, "amount_yi": None, "date": None,
                   "south_available": False, "south_amount_yi": None,
                   "south_date": None,
                   "policy_note": pipeline.PANORAMA_NORTH_POLICY_NOTE, "error": "offline"},
            sectors={"leading": [], "lagging": []}, quote_time=None, error="offline")
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908")
        self.assertNotIn("A股大盘全景复盘", html)   # 栏目标题不渲染
        self.assertIn("A股大盘全景", html)           # 数据审计栏仍留痕
        self.assertIn("暂缺", html)
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 9)  # 源数与是否有数据无关

    def test_panorama_counts_in_audit_and_eligibility(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = self._panorama_payload()
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908")
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 9)  # 审计源数固定，与实收数据无关
        ok, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(ok)
        # check_push_eligibility 按实收数据源动态计数（rich fixture 未含流动性源 → 8 项缺 1）
        n_dict_sources = len([v for v in data.values() if isinstance(v, dict)])
        self.assertIn(f"/{n_dict_sources}", reason)
        # 全景单独作为唯一「当天」源时也能通过当天检验，证明它真正计入推送门禁
        ok_solo, reason_solo = pipeline.check_push_eligibility(
            {"A股大盘全景": self._panorama_payload()})
        self.assertTrue(ok_solo)
        self.assertIn("1/1", reason_solo)


class ReportInnerDedupeTests(unittest.TestCase):
    """2026-09-09 页内去重：同一标题 / 数字在单份日报只出现一次。"""

    RISK_TITLE = "美股暴跌引发全球市场恐慌情绪蔓延"

    def _dedupe_data(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["实时行情"]["quotes"]["深证成指"] = {
            "price": 12345.67, "change_pct": -2.5, "currency": "CNY"}
        data["实时行情"]["quotes"]["恒生指数"] = {
            "price": 25000.0, "change_pct": 0.8, "currency": "HKD"}
        data["全球头条"]["headlines"].append({
            "title": self.RISK_TITLE, "source": "测试源",
            "url": "", "published_cst": "2026-08-02 11:00", "is_today": True})
        return data

    def test_pixel_risk_shown_title_renders_reference_only(self):
        """正文已展示的风险标题：风险区仅引用定位，全文只出现一次。"""
        html = pipeline.generate_report(
            self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme="pixel")
        self.assertEqual(html.count(self.RISK_TITLE), 1)  # 全文只在正文全球头条出现
        self.assertIn("「全球头条」第02条", html)          # 风险区仅引用定位
        self.assertIn('href="#h-gh-02"', html)             # 引用可跳回正文
        self.assertIn('id="h-gh-02"', html)                # 正文锚点存在
        self.assertIn("命中：", html)                      # 引用携带命中关键词（新增信息）
        res = pipeline.build_ai_analysis(self._dedupe_data())
        risk = [r for r in res["risks"] if r["title"] == self.RISK_TITLE][0]
        self.assertTrue(risk["shown"])
        self.assertIn("暴跌", risk["keywords"])

    def test_guizang_risk_reference_and_tech_aggregate(self):
        """guizang 主题同样去重：风险引用 + 动能聚合。"""
        html = pipeline.generate_report(
            self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme="guizang")
        self.assertEqual(html.count(self.RISK_TITLE), 1)
        self.assertIn("「全球头条」第02条", html)
        self.assertIn('href="#h-gh-02"', html)
        self.assertIn("指数动能", html)
        self.assertIn("4 个指数", html)
        self.assertNotIn("明细数值见「行情速览」", html)

    def test_tech_aggregate_counts_match_quotes(self):
        """动能聚合的涨跌家数与输入行情一致（3 涨 / 1 跌 / 0 平）。"""
        html = pipeline.generate_report(
            self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme="pixel")
        self.assertIn("指数动能聚合（4 个指数）", html)
        self.assertIn("▲ 3", html)
        self.assertIn("▼ 1", html)
        res = pipeline.build_ai_analysis(self._dedupe_data())
        self.assertEqual(res["tech_stats"]["count"], 4)
        self.assertEqual(
            (res["tech_stats"]["ups"], res["tech_stats"]["downs"], res["tech_stats"]["flats"]),
            (3, 1, 0))

    def test_market_section_shows_hk_indices_in_both_themes(self):
        """恒生指数补缺：双主题行情速览都有港股双指数小节。"""
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertIn("港股双指数", html)
            self.assertIn("恒生指数", html)

    def test_multi_factor_matrix_does_not_repeat_quotes(self):
        """多因子矩阵不再复述报价数字：价格只在行情速览出现一次。"""
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                self._dedupe_data(), "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertEqual(html.count("12,345.67"), 1, f"theme={theme}")  # 千分位价格仅出现一次
            # 涨跌幅：行情速览明细 + 页首「今日结论」摘要各一次
            self.assertLessEqual(html.count("-2.50%"), 2, f"theme={theme}")

    def test_unshown_channel_risk_keeps_full_title(self):
        """正文截断未展示的风险标题（港股频道第 4 条）：风险区保留全文。"""
        data = self._dedupe_data()
        videos = data["港股名家频道"]["channels"][0]["videos"]
        videos.extend([
            {"title": "午盘点评：恒指窄幅震荡", "video_id": f"v{i}",
             "url": f"https://www.youtube.com/watch?v=v{i}",
             "published": "2026-08-02T02:00:00+00:00",
             "published_cst": "2026-08-02 10:00", "is_today": True}
            for i in (2, 3)
        ])
        videos.append({
            "title": "恒指爆雷股预警名单更新", "video_id": "v4",
            "url": "https://www.youtube.com/watch?v=v4",
            "published": "2026-08-02T08:00:00+00:00",
            "published_cst": "2026-08-02 16:00", "is_today": True})
        html = pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="pixel")
        # 第 4 条正文不展示（只展示前 3 条），风险区必须保留全文以免信息丢失
        self.assertIn("恒指爆雷股预警名单更新", html)
        self.assertNotIn("h-hk-01-04", html)  # 正文无此锚点，不做引用跳转
        res = pipeline.build_ai_analysis(data)
        risk = [r for r in res["risks"] if r["title"] == "恒指爆雷股预警名单更新"][0]
        self.assertFalse(risk["shown"])


class NewsSentimentFactorTests(unittest.TestCase):
    """AI 新闻情绪因子：词表评分 / 个股归因 / 4 因子数学 / 历史 / 双主题渲染。"""

    def _senti_data(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["全球头条"]["headlines"].extend([
            {"title": "A股股票3大涨创新高，机构上调评级", "source": "华尔街见闻",
             "url": "", "published_cst": "2026-08-02 10:00", "is_today": True},
            {"title": "A股股票3获北向资金净流入超十亿", "source": "财联社",
             "url": "", "published_cst": "2026-08-02 12:00", "is_today": True},
            {"title": "港股股票1暴跌，爆雷风险预警", "source": "智通财经",
             "url": "", "published_cst": "2026-08-02 11:00", "is_today": True},
            # 72h 窗口（2026-08-02 23:59 起算）之外 → 不计入情绪评分/归因
            {"title": "7月30日旧闻：A股股票3不涨令人失望", "source": "旧源",
             "url": "", "published_cst": "2026-07-30 08:00", "is_today": False},
        ])
        return data

    def _senti_history(self):
        return {"version": 1, "stocks": {"A股:000003": {
            "market": "A股", "code": "000003", "name": "A股股票3", "days": {
                "20260727": {"pos": 0, "neu": 0, "neg": 1, "total": 1, "score": -1.0},
                "20260728": {"pos": 0, "neu": 1, "neg": 1, "total": 2, "score": -0.5},
                "20260729": {"pos": 0, "neu": 0, "neg": 0, "total": 0, "score": None},
                "20260730": {"pos": 1, "neu": 1, "neg": 0, "total": 2, "score": 0.5},
                "20260731": {"pos": 1, "neu": 0, "neg": 0, "total": 1, "score": 1.0},
                "20260801": {"pos": 2, "neu": 0, "neg": 0, "total": 2, "score": 1.0},
            }}}}

    def test_headline_scoring_basic(self):
        pos = pipeline._score_headline_sentiment("A股股票3大涨创新高，机构上调评级")
        self.assertEqual(pos["s"], 1)
        self.assertIn("大涨", pos["pos"])
        neg = pipeline._score_headline_sentiment("港股股票1暴跌，爆雷风险预警")
        self.assertEqual(neg["s"], -1)
        self.assertIn("暴跌", neg["neg"])
        neu = pipeline._score_headline_sentiment("公司发布例行公告")
        self.assertEqual(neu["s"], 0)
        self.assertEqual(neu["pos"], [])
        self.assertEqual(neu["neg"], [])

    def test_headline_negation_flip(self):
        down = pipeline._score_headline_sentiment("A股不涨令人失望")
        self.assertEqual(down["s"], -1)   # 不+涨 → 翻转为负
        self.assertIn("涨", down["neg"])
        up = pipeline._score_headline_sentiment("大盘不跌")
        self.assertEqual(up["s"], 1)      # 不+跌 → 翻转为正

    def test_headline_overlap_longest_first(self):
        r = pipeline._score_headline_sentiment("市场暴跌引发恐慌")
        self.assertEqual(r["neg"], ["暴跌"])  # 不与「跌」重复计数
        self.assertEqual(r["neg_n"], 1)

    def test_headline_traditional_chinese(self):
        r = pipeline._score_headline_sentiment("港股創新高，北水淨流入")
        self.assertEqual(r["s"], 1)
        self.assertTrue(r["pos"])

    def test_attribution_and_72h_window(self):
        res = pipeline.build_news_sentiment(self._senti_data(), "20260802", None)
        self.assertTrue(res["available"])
        self.assertEqual(res["total_matched"], 2)
        self.assertEqual(res["scored_headlines"], 3)  # 3 条窗口内标题被归因
        self.assertEqual(res["unattributed_n"], 3)    # 全球头条/东财/港股频道各1条大盘级
        a3 = [s for s in res["stocks"] if s["code"] == "000003"][0]
        self.assertEqual(a3["total"], 2)  # 72h 窗口之外（07-30）旧闻未计入
        self.assertEqual(a3["score"], 1.0)
        self.assertEqual(a3["label"], "偏多")
        # 与报告日同一自然日的标题才进入「今日」桶（供 MOM/ANV 与历史落盘）
        self.assertEqual(res["today_counts"]["A股:000003"]["total"], 2)

    def test_72h_window_includes_recent_prior_day(self):
        # 报告日前 48h 内（08-01）的标题计入 DNS 窗口，但只落 08-01，不进今日桶
        data = NewLayoutRenderingTests()._rich_data()
        corpus = {"version": 1, "items": [
            {"title": "A股股票3大涨创新高，机构上调评级", "source": "华尔街见闻",
             "section": "全球头条", "ts": "2026-08-02 10:00", "date": "2026-08-02"},
            {"title": "A股股票3获北向资金净流入超十亿", "source": "财联社",
             "section": "全球头条", "ts": "2026-08-02 12:00", "date": "2026-08-02"},
            {"title": "A股股票3昨晚暴跌，爆雷风险预警", "source": "智通财经",
             "section": "东财快讯", "ts": "2026-08-01 23:00", "date": "2026-08-01"},
        ]}
        res = pipeline.build_news_sentiment(data, "20260802", None,
                                            news_corpus=corpus)
        a3 = [s for s in res["stocks"] if s["code"] == "000003"][0]
        self.assertEqual((a3["pos"], a3["neg"]), (2, 1))     # 72h 窗口含 08-01
        self.assertAlmostEqual(a3["score"], 1 / 3)
        self.assertEqual(a3["headlines"][-1]["old"], True)   # 旧日标题带 old 标记
        self.assertIn("08-01", pipeline._senti_headline_sub(a3["headlines"][-1]))
        self.assertEqual(res["today_counts"]["A股:000003"]["total"], 2)  # 今日桶只含 08-02

    def test_news_corpus_merge_dedupe_prune_roundtrip(self):
        # news_history.json 的 合并(按 日期+标题 去重) / 剪枝 / 损坏回退
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "news_history.json")
            corpus = pipeline._load_news_corpus(path)  # 缺失 → 空存档
            self.assertEqual(corpus["items"], [])
            fresh = [
                {"title": "央行降准0.5个百分点", "date": "2026-08-02",
                 "source": "新华社", "section": "全球头条", "ts": "2026-08-02 09:00"},
                {"title": "央行降准0.5个百分点", "date": "2026-08-02",  # 同日重复 → 去重
                 "source": "财联社", "section": "东财快讯", "ts": "2026-08-02 10:00"},
                {"title": "统计局公布CPI", "date": "2026-08-01",
                 "source": "统计局", "section": "全球头条", "ts": ""},
            ]
            pipeline._merge_news_corpus(corpus, fresh)
            pipeline._merge_news_corpus(corpus, fresh)  # 幂等：再并一次不增加
            self.assertEqual(len(corpus["items"]), 2)
            pipeline._save_news_corpus(path, corpus)
            loaded = pipeline._load_news_corpus(path)
            self.assertEqual(len(loaded["items"]), 2)
            loaded["items"].append({"title": "老新闻", "date": "2026-07-01",
                                    "source": "", "section": "", "ts": ""})
            pipeline._prune_news_corpus(loaded, "2026-08-02")  # 保留 ~18 日
            self.assertEqual([i["title"] for i in loaded["items"]],
                             ["央行降准0.5个百分点", "统计局公布CPI"])
            bad_path = str(Path(directory) / "broken.json")
            Path(bad_path).write_text("not json{{{", encoding="utf-8")
            self.assertEqual(pipeline._load_news_corpus(bad_path)["items"], [])

    def test_daily_score_math(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["全球头条"]["headlines"].extend([
            {"title": "美股股票0大涨创新高", "source": "s", "url": "",
             "published_cst": "2026-08-02 10:00", "is_today": True},
            {"title": "美股股票0获机构上调评级", "source": "s", "url": "",
             "published_cst": "2026-08-02 11:00", "is_today": True},
            {"title": "美股股票0发布例行公告", "source": "s", "url": "",
             "published_cst": "2026-08-02 12:00", "is_today": True},
            {"title": "美股股票0遭大股东减持", "source": "s", "url": "",
             "published_cst": "2026-08-02 13:00", "is_today": True},
        ])
        res = pipeline.build_news_sentiment(data, "20260802", None)
        s0 = [s for s in res["stocks"] if s["code"] == "000000"][0]
        self.assertEqual((s0["pos"], s0["neu"], s0["neg"]), (2, 1, 1))
        self.assertAlmostEqual(s0["score"], 0.25)  # (2−1)/4
        self.assertEqual(s0["label"], "偏多")

    def test_momentum_math_and_label(self):
        res = pipeline.build_news_sentiment(
            self._senti_data(), "20260802", self._senti_history())
        a3 = [s for s in res["stocks"] if s["code"] == "000003"][0]
        mom = a3["momentum"]
        self.assertTrue(mom["enough"])
        self.assertEqual((mom["short_n"], mom["long_n"]), (3, 6))
        self.assertAlmostEqual(mom["short_mean"], 1.0)
        self.assertAlmostEqual(mom["long_mean"], 1 / 3)
        self.assertAlmostEqual(mom["value"], 2 / 3)
        self.assertEqual(mom["label"], "加速转暖")

    def test_momentum_insufficient_cold_start(self):
        res = pipeline.build_news_sentiment(self._senti_data(), "20260802", None)
        hk1 = [s for s in res["stocks"] if s["code"] == "000001"][0]
        self.assertFalse(hk1["momentum"]["enough"])
        self.assertEqual(hk1["momentum"]["need"], "2/5")

    def test_volume_abnormal_flag(self):
        data = NewLayoutRenderingTests()._rich_data()
        for i in range(4):
            data["全球头条"]["headlines"].append({
                "title": f"美股股票0发布例行公告（{i}）", "source": "s", "url": "",
                "published_cst": "2026-08-02 10:00", "is_today": True})
        days = {}
        for n, (day, total) in enumerate([("20260727", 1), ("20260728", 1),
                                          ("20260729", 2), ("20260730", 1),
                                          ("20260731", 2), ("20260801", 1)]):
            days[day] = {"pos": 0, "neu": total, "neg": 0, "total": total, "score": 0.0}
        history = {"version": 1, "stocks": {"美股:000000": {
            "market": "美股", "code": "000000", "name": "美股股票0", "days": days}}}
        res = pipeline.build_news_sentiment(data, "20260802", history)
        s0 = [s for s in res["stocks"] if s["code"] == "000000"][0]
        vol = s0["volume"]
        self.assertTrue(vol["enough"])
        self.assertTrue(vol["abnormal"])  # 今日4条 > 均值1.33+2σ(1.03)
        self.assertEqual(vol["label"], "异常放量")
        self.assertGreater(vol["z"], 5.0)

    def test_volume_insufficient_few_days(self):
        history = {"version": 1, "stocks": {"A股:000003": {
            "market": "A股", "code": "000003", "name": "A股股票3",
            "days": {"20260801": {"pos": 1, "neu": 0, "neg": 0,
                                  "total": 1, "score": 1.0}}}}}
        res = pipeline.build_news_sentiment(
            self._senti_data(), "20260802", history)
        a3 = [s for s in res["stocks"] if s["code"] == "000003"][0]
        self.assertFalse(a3["volume"]["enough"])
        self.assertEqual(a3["volume"]["n"], 1)

    def test_history_update_merge_prune_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "sentiment_history.json")
            universe = [
                {"market": "A股", "code": "000003", "name": "A股股票3",
                 "key": "A股:000003"},
                {"market": "A股", "code": "000004", "name": "A股股票4",
                 "key": "A股:000004"},
            ]
            history = pipeline._load_sentiment_history(path)  # 缺失 → 空历史
            self.assertEqual(history["stocks"], {})
            counts = {"A股:000003": {"pos": 2, "neu": 0, "neg": 0, "total": 2}}
            pipeline._save_sentiment_history(
                path, pipeline._update_sentiment_history(
                    history, "20260802", universe, counts))
            loaded = pipeline._load_sentiment_history(path)
            day = loaded["stocks"]["A股:000003"]["days"]["20260802"]
            self.assertEqual(day["score"], 1.0)
            zero = loaded["stocks"]["A股:000004"]["days"]["20260802"]
            self.assertEqual(zero["total"], 0)
            self.assertIsNone(zero["score"])  # 零报道日无评分
            # 同日重复落盘幂等
            pipeline._save_sentiment_history(
                path, pipeline._update_sentiment_history(
                    loaded, "20260802", universe, counts))
            reloaded = pipeline._load_sentiment_history(path)
            self.assertEqual(reloaded["stocks"], loaded["stocks"])
            # 超 45 天的数据被修剪，无保留日的个股被清理
            reloaded["stocks"]["A股:000003"]["days"]["20260601"] = {
                "pos": 1, "neu": 0, "neg": 0, "total": 1, "score": 1.0}
            reloaded["stocks"]["过期股"] = {"market": "A股", "code": "", "name": "x",
                                            "days": {"20260601": {
                                                "pos": 0, "neu": 0, "neg": 0,
                                                "total": 0, "score": None}}}
            pruned = pipeline._update_sentiment_history(
                reloaded, "20260810", universe, {})
            self.assertNotIn("20260601",
                             pruned["stocks"]["A股:000003"]["days"])
            self.assertIn("20260802", pruned["stocks"]["A股:000003"]["days"])
            self.assertNotIn("过期股", pruned["stocks"])

    def test_history_corrupt_file_falls_back_to_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sentiment_history.json"
            path.write_text("not json{{{", encoding="utf-8")
            history = pipeline._load_sentiment_history(str(path))
            self.assertEqual(history["stocks"], {})

    def test_by_market_top5_with_per_stock_comment_reason(self):
        res = pipeline.build_news_sentiment(self._senti_data(), "20260802", None)
        by_market = res["by_market"]
        self.assertEqual([m["market"] for m in by_market], ["A股", "港股", "美股"])
        for mb in by_market:
            self.assertEqual(len(mb["stocks"]), pipeline.HOT_STOCK_TOP_N)
        a3 = next(s for s in by_market[0]["stocks"] if s["code"] == "000003")
        self.assertTrue(a3["matched"])
        self.assertAlmostEqual(a3["score"], 1.0)
        self.assertIn("AI情绪分", a3["comment"])
        self.assertIn("近72小时命中 2 条相关新闻", a3["comment"])
        self.assertIn("命中情绪词", a3["reason"])
        self.assertIn("正面主要来自", a3["reason"])
        hk1 = next(s for s in by_market[1]["stocks"] if s["code"] == "000001")
        self.assertTrue(hk1["matched"])
        self.assertAlmostEqual(hk1["score"], -1.0)
        self.assertIn("负面主要来自", hk1["reason"])
        a0 = next(s for s in by_market[0]["stocks"] if s["code"] == "000000")
        self.assertFalse(a0["matched"])
        self.assertIsNone(a0["score"])
        self.assertIn("近72小时无相关点名新闻", a0["comment"])
        self.assertIn("窗口内标题未通过精确名/别名代码/行业概念归因到该股", a0["reason"])
        self.assertIn("暂无评分", a0["label"])

    def test_build_news_sentiment_available_without_match(self):
        # 无归因但榜单存在 → 栏目仍可渲染（逐股「暂无评分」），available 由榜单宇宙决定
        res = pipeline.build_news_sentiment(
            NewLayoutRenderingTests()._rich_data(), "20260802", None)
        self.assertTrue(res["available"])
        self.assertTrue(res["by_market"])
        self.assertEqual(res["total_matched"], 0)
        stocks = [s for mb in res["by_market"] for s in mb["stocks"]]
        self.assertTrue(all(not s["matched"] for s in stocks))
        self.assertTrue(all(s["score"] is None for s in stocks))

    def test_pixel_render_contains_factors(self):
        html = pipeline.generate_report(
            self._senti_data(), "2026年8月2日 · 周日", "20260802",
            theme="pixel", sentiment_history=self._senti_history())
        self.assertIn("AI 新闻情绪因子", html)
        self.assertIn("A股股票3", html)
        self.assertIn("DNS +1.00", html)
        self.assertIn("MOM +0.67", html)
        self.assertIn("加速转暖", html)
        self.assertIn("z=+0.8", html)
        self.assertIn("S+1", html)
        self.assertIn("S−1", html)
        self.assertIn("命中：大涨", html)
        self.assertIn("样本不足", html)  # 无历史的港股股票1
        self.assertIn("总结评论", html)   # 2026-09-09 逐股 AI 总结评论
        self.assertIn("原因", html)      # 逐股评论原因
        self.assertIn("A股 · 成交量前5", html)

    def test_guizang_render_contains_factors(self):
        html = pipeline.generate_report(
            self._senti_data(), "2026年8月2日 · 周日", "20260802",
            theme="guizang", sentiment_history=self._senti_history())
        self.assertIn("AI 新闻情绪因子", html)
        self.assertIn("DNS +1.00", html)
        self.assertIn("▲ S+1", html)  # 黑白模式用符号区分方向
        self.assertIn("▼ S−1", html)
        self.assertIn("MOM +0.67", html)
        self.assertIn("AI 情绪分", html)
        self.assertIn("原因", html)
        self.assertIn("A股 · 成交量前5", html)
        self.assertNotIn("暂无评分", html)   # 未被点名的个股不再占位

    def test_per_stock_render_without_attribution(self):
        # 2026-09-27 精简排版：窗口内标题未点名任何榜单个股时栏目整体缺席，
        # 不再逐股输出「暂无评分」占位，也不伪造 DNS 数值。
        data = NewLayoutRenderingTests()._rich_data()  # 标题未提及任何榜单个股
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertNotIn("AI 新闻情绪因子", html)
            self.assertNotIn("暂无评分", html)
            self.assertNotIn("DNS +", html)
            self.assertNotIn("S+1", html)

    def test_absent_without_hot_rankings(self):
        # 热门榜单（个股宇宙）缺席且无当天标题 → 栏目缺席
        data = NewLayoutRenderingTests()._rich_data()
        for src in ("全球头条", "东财快讯", "港股名家频道"):
            data[src] = pipeline._source_result(src, "unavailable", headlines=[],
                                                channels=[], error="offline")
        data["热门榜单"] = pipeline._source_result(
            "东方财富热门榜", "unavailable", markets={}, error="offline")
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertNotIn("AI 新闻情绪因子", html)
            self.assertNotIn("样本不足：", html)

    def test_cold_start_renders_with_insufficient_labels(self):
        html = pipeline.generate_report(
            self._senti_data(), "2026年8月2日 · 周日", "20260802",
            theme="pixel")  # 不传历史 → 冷启动
        self.assertIn("AI 新闻情绪因子", html)
        self.assertIn("DNS +1.00", html)  # 日度因子不受影响
        self.assertIn("MOM 样本不足", html)
        self.assertIn("ANV 样本不足", html)


class PolicyFactorTests(unittest.TestCase):
    """政策因子：关键词矩阵 / 行业 PSI / 总结 / 首位渲染。

    2026-09-09 起标题窗口放宽为近 15 个自然日（含报告日）：
    单日无政策但近 15 日有政策/宏观新闻时栏目照常出现；更早（窗口外）
    的标题不参与。引擎调用统一带 date_str=报告日（YYYYMMDD）固定锚点，
    与生产 main() 一致。
    """

    def _policy_data(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["全球头条"]["headlines"].extend([
            {"title": "央行宣布降准0.5个百分点释放长期资金", "source": "新华社",
             "url": "", "published_cst": "2026-08-02 09:00", "is_today": True},
            {"title": "新能源汽车补贴政策延续，最高补2万", "source": "财联社",
             "url": "", "published_cst": "2026-08-02 10:00", "is_today": True},
            {"title": "美国加征半导体关税，商务部回应", "source": "环球网",
             "url": "", "published_cst": "2026-08-02 11:00", "is_today": True},
            {"title": "机构预计短期暂不降息", "source": "旧逻辑",
             "url": "", "published_cst": "2026-08-02 12:00", "is_today": True},
            # 报告日前一天（08-01）的政策旧闻：15 日窗口内 → 计入，标 old
            {"title": "昨日：证监会约谈多家券商", "source": "旧源",
             "url": "", "published_cst": "2026-08-01 10:00", "is_today": False},
        ])
        data["东财快讯"]["headlines"].append({
            "title": "证监会约谈多家券商，严查违规行为", "source": "东方财富",
            "url": "", "time": "2026-08-02 13:00", "is_today": True})
        return data

    def _minimal_data(self, titles_today):
        return {"全球头条": pipeline._source_result(
            "test", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": t, "source": "s", "url": "",
                        "published_cst": "2026-08-02 10:00", "is_today": True}
                       for t in titles_today])}

    def test_easing_fixed_weights(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["央行宣布降准0.5个百分点释放长期资金"]), "20260802")
        self.assertTrue(res["available"])
        scores = {s["name"]: s["score"] for s in res["industries"]}
        self.assertEqual(scores, {"银行": -1, "证券": 2, "地产链": 2,
                                  "消费": 1, "科技成长": 1})
        self.assertEqual(res["broad_score"], 1)
        self.assertEqual(res["broad_label"], "偏暖")
        self.assertEqual(res["dim_counts"], {"货币宽松": 1})
        self.assertEqual(res["window_days"], 15)   # 标题窗口 = 近 15 自然日
        self.assertEqual(res["total_headlines"], 1)
        head = res["headlines"][0]
        self.assertEqual(head["date"], "2026-08-02")
        self.assertFalse(head["old"])              # 当日标题不带日期前缀

    def test_support_attributes_mentioned_industries(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["新能源汽车补贴政策延续，最高补2万"]), "20260802")
        scores = {s["name"]: s["score"] for s in res["industries"]}
        self.assertEqual(scores, {"新能源": 2, "汽车": 2})
        self.assertEqual(res["broad_score"], 0)  # 有行业归因，不落宽基
        head = res["headlines"][0]
        self.assertEqual(head["dims"], ["产业扶持"])
        self.assertEqual(head["direction"], 1)

    def test_regulation_without_industry_falls_to_broad(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["监管部门发布新规规范行业发展"]), "20260802")
        self.assertTrue(res["available"])
        self.assertEqual(res["industries"], [])
        self.assertEqual(res["broad_score"], -1)
        self.assertEqual(res["broad_label"], "偏冷")
        self.assertEqual(res["headlines"][0]["industries"], [])

    def test_negated_trigger_skipped(self):
        res = pipeline.build_policy_factor(self._minimal_data(
            ["机构预计短期暂不降息", "央行年内不会降准"]), "20260802")
        self.assertFalse(res["available"])  # 否定修饰的触发词不计入
        self.assertEqual(res["policy_n"], 0)

    def test_prior_day_policy_news_within_window_counts_as_old(self):
        # 15 日窗口含报告日前一天：08-01 的降准标题计入，并带 old 标记
        data = {"全球头条": pipeline._source_result(
            "test", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": "央行宣布降准0.5个百分点", "source": "s",
                        "url": "", "published_cst": "2026-08-01 10:00",
                        "is_today": False}])}
        res = pipeline.build_policy_factor(data, "20260802")
        self.assertTrue(res["available"])
        self.assertEqual(res["policy_n"], 1)
        self.assertEqual(res["headlines"][0]["date"], "2026-08-01")
        self.assertTrue(res["headlines"][0]["old"])  # 旧日标题渲染 MM-DD 前缀
        self.assertEqual(res["headlines"][0]["old"], True)

    def test_outside_15day_window_excluded(self):
        # 2026-08-02 − 14 自然日 = 07-19 起；07-15 的旧闻在窗口外 → 不参与
        data = {"全球头条": pipeline._source_result(
            "test", "success", is_today=True, content_date="2026-08-02",
            headlines=[{"title": "央行宣布降准0.5个百分点", "source": "s",
                        "url": "", "published_cst": "2026-07-15 10:00",
                        "is_today": False}])}
        res = pipeline.build_policy_factor(data, "20260802")
        self.assertFalse(res["available"])
        self.assertEqual(res["policy_n"], 0)
        self.assertEqual(res["total_headlines"], 0)

    def test_multi_trigger_same_dimension_counts_once(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["降准降息双落地"]), "20260802")
        self.assertEqual(res["dim_counts"], {"货币宽松": 1})  # 同维度只计一次
        scores = {s["name"]: s["score"] for s in res["industries"]}
        self.assertEqual(scores["证券"], 2)  # 权重只落一次

    def test_traditional_triggers(self):
        res = pipeline.build_policy_factor(
            self._minimal_data(["人行降準0.5厘釋放流動性"]), "20260802")
        self.assertTrue(res["available"])
        self.assertEqual(res["broad_score"], 1)
        self.assertEqual(res["dim_counts"], {"货币宽松": 1})

    def test_aggregation_and_summary(self):
        res = pipeline.build_policy_factor(self._policy_data(), "20260802")
        # 降息 + 降准 + 补贴 + 关税 + 约谈×2（含 08-01 旧闻，15 日窗口内）
        # = 6 条；「暂不降息」否定不计入
        self.assertEqual(res["policy_n"], 6)
        self.assertEqual(res["total_headlines"], 9)
        self.assertEqual(res["dim_counts"],
                         {"货币宽松": 2, "产业扶持": 1, "监管收紧": 2, "贸易壁垒": 1})
        self.assertEqual(res["broad_score"], 2)
        self.assertEqual(res["broad_label"], "偏暖")
        self.assertEqual([w["score"] for w in res["winners"]], [4, 2, 2, 2, 2])
        self.assertEqual(
            {w["name"] for w in res["winners"]},
            {"地产链", "科技成长", "新能源", "汽车", "消费"})
        self.assertEqual([w["name"] for w in res["losers"]], ["半导体", "银行"])
        # 证券多空相抵（+2/+2/−2/−2）后 score 归零但仍在榜上
        sec = [s for s in res["industries"] if s["name"] == "证券"][0]
        self.assertEqual((sec["score"], sec["count"]), (0, 4))
        self.assertIn("近15日窗口内检出政策类新闻 6 条", res["summary"])
        self.assertIn("（占窗口资讯 6/9）", res["summary"])
        self.assertIn("PSI +2", res["summary"])
        self.assertIn("偏暖", res["summary"])
        self.assertIn("货币宽松×2", res["summary"])
        # 08-01 旧闻计入并带 old 标记（渲染时加 MM-DD 前缀）
        yesterday = [h for h in res["headlines"] if "昨日" in h["title"]][0]
        self.assertTrue(yesterday["old"])
        self.assertEqual(yesterday["date"], "2026-08-01")
        self.assertEqual(yesterday["dims"], ["监管收紧"])

    def test_macro_data_dimension_counts_cpi_ppi(self):
        # 2026-09-09 增补：CPI/PPI/统计局等宏观数据视为政策因子输入，
        # 让“0 政策新闻”的宏观数据日也能出栏目（不再整日缺席）
        res = pipeline.build_policy_factor(self._minimal_data(
            ["国家统计局：8月份CPI同比温和回升，PPI同比涨幅扩大"]), "20260802")
        self.assertTrue(res["available"])
        self.assertEqual(res["policy_n"], 1)
        self.assertEqual(res["dim_counts"], {"宏观数据": 1})
        self.assertEqual(res["broad_score"], 1)   # 中性偏暖启发式 → 大盘 PSI +1
        names = {s["name"] for s in res["winners"]}
        self.assertIn("消费", names)               # CPI 回升利多消费
        self.assertIn("有色金属", names)           # PPI 涨幅扩大利多上游资源
        self.assertIn("政策及宏观数据类新闻 1 条", res["summary"])

    def test_pixel_renders_first_with_summary(self):
        html = pipeline.generate_report(
            self._policy_data(), "2026年8月2日 · 周日", "20260802", theme="pixel")
        self.assertIn("LVL 01 // CONCLUSION", html)        # 结论先行，政策定调进入结论
        self.assertIn("// POLICY SHOCK", html)
        self.assertLess(html.find("// POLICY SHOCK"), html.find("// QUANT STRATEGY"))
        self.assertIn("政策冲击指数", html)
        self.assertIn("PSI +2", html)
        self.assertIn("政策类新闻 6 条", html)
        self.assertIn("地产链", html)
        # 旧日政策标题以 MM-DD 前缀标注
        self.assertIn("08-01 ·", html)
        self.assertIn("昨日：证监会约谈多家券商", html)

    def test_guizang_renders_first_with_summary(self):
        html = pipeline.generate_report(
            self._policy_data(), "2026年8月2日 · 周日", "20260802", theme="guizang")
        self.assertLess(html.find("政策因子</h2>"), html.find("每日量化策略（板块趋势跟踪）</h2>"))
        self.assertLess(html.find("今日结论</h2>"), html.find("政策因子</h2>"))
        self.assertIn("PSI +2", html)
        self.assertIn("6 条（近 15 日）", html)
        self.assertIn("行业冲击榜", html)
        self.assertNotIn("政策因子口径", html)          # 口径说明已移除
        self.assertIn("08-01 ·", html)

    def test_absent_without_policy_news(self):
        data = self._minimal_data(["美股三大指数集体收涨"])
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertNotIn("政策因子", html)

    def test_main_stage_result_honored(self):
        data = self._policy_data()
        html = pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="pixel",
            policy_result={"available": False})  # main 阶段结果优先
        self.assertNotIn("政策因子", html)
        html2 = pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="pixel",
            policy_result=None)  # 缺省时渲染侧兜底构建
        self.assertIn("政策因子", html2)



class NationalPolicySourceTests(unittest.TestCase):
    """中国政府网官方政策源：解析、降级、存档和双主题溯源。"""

    GOV_HTML = """
    <html><body>
      <ul class="policy-list">
        <li><a href="/zhengce/content/2026/08/content_7070001.htm">
          <span>国务院关于推进绿色低碳发展的意见</span>
        </a><span class="date">2026年8月2日</span></li>
        <li><a href="https://www.gov.cn/zhengce/202607/content_7070002.html">
          国务院办公厅关于做好就业工作的通知
        </a><time>2026-07-31</time></li>
        <li><a href="/zhengce/content/2026/08/content_7070003.htm">没有日期的政策办法</a></li>
        <li><a href="https://example.com/zhengce/content/2026/08/content_7070004.htm">
          第三方转载，不应作为官方政策
        </a><span>2026-08-02</span></li>
        <li><a href="/zhengce/202608/index.htm">政策栏目导航，不是正文</a></li>
        <li><a href="javascript:alert(1)">脚本链接</a></li>
      </ul>
    </body></html>
    """

    def test_parser_keeps_only_official_policy_articles_and_dates(self):
        items = pipeline._parse_gov_policy_html(self.GOV_HTML, limit=10)
        self.assertEqual([item["title"] for item in items], [
            "国务院关于推进绿色低碳发展的意见",
            "国务院办公厅关于做好就业工作的通知",
            "没有日期的政策办法",
        ])
        self.assertEqual(items[0]["url"],
                         "https://www.gov.cn/zhengce/content/2026/08/content_7070001.htm")
        self.assertEqual(items[0]["date"], "2026-08-02")
        self.assertEqual(items[1]["date"], "2026-07-31")
        self.assertEqual(items[2]["date"], "")
        self.assertEqual(items[2]["published_cst"], "—")
        self.assertTrue(all(item["official"] for item in items))

    def test_parser_accepts_bytes_and_limit(self):
        items = pipeline._parse_gov_policy_html(self.GOV_HTML.encode("utf-8"), limit=2)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source"], "中国政府网")

    def test_fetch_falls_back_to_policy_home(self):
        with patch.object(pipeline, "safe_request", side_effect=[None, self.GOV_HTML]) as request:
            result = pipeline.fetch_gov_policy()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["official"])
        self.assertEqual(result["page_url"], pipeline.GOV_POLICY_FALLBACK_URL)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(result["headlines"]), 3)

    def test_fetch_is_explicitly_unavailable_without_history_fallback(self):
        with patch.object(pipeline, "safe_request", return_value=None):
            result = pipeline.fetch_gov_policy()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["headlines"], [])
        self.assertTrue(result["official"])
        self.assertIn("gov.cn", result["page_url"])

    def test_official_fields_reach_corpus_and_neutral_policy_factor(self):
        parsed = pipeline._parse_gov_policy_html(self.GOV_HTML, limit=1)
        data = {"国家政策": pipeline._source_result(
            "中国政府网·最新政策", "success", headlines=parsed)}
        items = pipeline._collect_headline_items(data, "2026-08-02")
        self.assertEqual(items[0]["url"], parsed[0]["url"])
        self.assertTrue(items[0]["official"])
        corpus = {"version": 1, "items": []}
        pipeline._merge_news_corpus(corpus, items)
        self.assertEqual(corpus["items"][0]["url"], parsed[0]["url"])
        self.assertTrue(corpus["items"][0]["official"])

        result = pipeline.build_policy_factor(data, "20260802")
        self.assertTrue(result["available"])
        self.assertEqual(result["official_n"], 1)
        self.assertEqual(result["dim_counts"], {"政策发布": 1})
        self.assertIn("中国政府网官方发布 1 条", result["summary"])

    def test_both_themes_render_safe_official_original_link(self):
        data = {"国家政策": pipeline._source_result(
            "中国政府网·最新政策", "success", headlines=[{
                "title": "国务院发布稳增长政策",
                "source": "中国政府网",
                "url": "https://www.gov.cn/zhengce/content/2026/08/content_7070009.htm?a=1&b=2",
                "date": "2026-08-02",
                "published_cst": "2026-08-02",
                "official": True,
            }])}
        for theme in ("pixel", "guizang"):
            html = pipeline.generate_report(
                data, "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertIn("官方原文", html)
            self.assertIn("中国政府网（官方发布）", html)
            self.assertIn("https://www.gov.cn/zhengce/content/2026/08/content_7070009.htm?a=1&amp;b=2", html)
            self.assertLess(html.find("政策因子"), html.find("盘点总结"))


class SectionReadingOrderTests(unittest.TestCase):
    """2026-09-27：按人类阅读逻辑固定栏目顺序（两主题共用 _collect_report_parts）。

    结论先行 → 分栏展开（行情速览 → A股大盘全景 → 政策因子 → 每日量化策略（板块趋势跟踪） →
    资讯：全球头条 → 东财快讯 → A股资讯 → 港股名家频道 → AI 新闻情绪因子）→
    盘点总结收尾。无数据栏目缺席但不打乱其余顺序。
    """

    def _full_data(self):
        data = NewsSentimentFactorTests()._senti_data()  # 行情/频道/全球/东财/榜单 + 个股标题
        data["全球头条"]["headlines"].append({
            "title": "央行宣布降准0.5个百分点释放长期资金", "source": "新华社",
            "url": "", "published_cst": "2026-08-02 09:00", "is_today": True})
        data["A股资讯"] = pipeline._source_result(
            "新浪财经", "success", is_today=True, content_date="2026-08-02",
            headlines=["A股市场放量上涨，沪指重返整数关口"])
        data["A股大盘全景"] = MarketPanoramaTests()._panorama_payload()
        return data

    # guizang 栏目标题统一以 </h2> 收尾，用它定位真实栏目头，避免命中
    # 每日量化策略内部的「→ 「全球头条」第N条」等跨栏目引用文字。
    GUIZANG_ORDER = [
        "今日结论</h2>",
        "行情速览</h2>",
        "A股大盘全景复盘</h2>",
        "政策因子</h2>",
        "每日量化策略（板块趋势跟踪）</h2>",
        "全球头条</h2>",
        "东方财富快讯</h2>",
        "A股资讯</h2>",
        "港股名家频道</h2>",
        "AI 新闻情绪因子</h2>",
        "盘点总结</h2>",
    ]

    def test_guizang_section_reading_order(self):
        html = pipeline.generate_report(
            self._full_data(), "2026年8月2日 · 周日", "20260802")  # 默认 guizang
        positions = [html.find(h) for h in self.GUIZANG_ORDER]
        self.assertNotIn(-1, positions, "存在未渲染的栏目标题")
        self.assertEqual(positions, sorted(positions),
                         "栏目顺序不符合阅读逻辑:\n" + "\n".join(
                             f"  {h}: {p}" for h, p in zip(self.GUIZANG_ORDER, positions)))

    def test_pixel_lvl_numbering_follows_reading_order(self):
        html = pipeline.generate_report(
            self._full_data(), "2026年8月2日 · 周日", "20260802", theme="pixel")
        order = [
            "LVL 01 // CONCLUSION",
            "LVL 02 // MARKET SNAPSHOT", "LVL 03 // A-SHARE PANORAMA",
            "LVL 04 // POLICY SHOCK", "LVL 05 // QUANT STRATEGY",
            "LVL 06 // GLOBAL HEADLINES", "LVL 07 // EASTMONEY WIRE",
            "LVL 08 // A-SHARE DESK", "LVL 09 // HK GURU CHANNELS",
            "LVL 10 // NEWS SENTIMENT", "LVL 11 // WRAP-UP",
        ]
        positions = [html.find(s) for s in order]
        self.assertNotIn(-1, positions, "存在未渲染的 LVL 关卡")
        self.assertEqual(positions, sorted(positions),
                         "LVL 关卡编号顺序不符合阅读逻辑:\n" + "\n".join(
                             f"  {s}: {p}" for s, p in zip(order, positions)))

    def test_order_skips_missing_sections_without_shifting_rest(self):
        # 无新闻/无政策/无情绪归因（缺席栏目）时，剩余栏目顺序与编号仍正确
        data = self._full_data()
        for src in ("全球头条", "东财快讯", "港股名家频道"):
            data[src] = pipeline._source_result(
                src, "unavailable", headlines=[], channels=[], error="offline")
        data["A股资讯"] = pipeline._source_result(
            "新浪财经", "unavailable", headlines=[], error="offline")
        data["热门榜单"] = pipeline._source_result(
            "东方财富热门榜", "unavailable", markets={}, error="offline")
        html = pipeline.generate_report(
            data, "2026年8月2日 · 周日", "20260802", theme="pixel")
        order = ["LVL 01 // CONCLUSION", "LVL 02 // MARKET SNAPSHOT",
                 "LVL 03 // A-SHARE PANORAMA", "LVL 04 // QUANT STRATEGY",
                 "LVL 05 // WRAP-UP"]
        positions = [html.find(s) for s in order]
        self.assertNotIn(-1, positions, "缺席栏目后剩余关卡渲染不完整")
        self.assertEqual(positions, sorted(positions))
        self.assertNotRegex(html, r"LVL \d+ // POLICY SHOCK")
        self.assertNotRegex(html, r"LVL \d+ // NEWS SENTIMENT")


class ConciseLayoutTests(unittest.TestCase):
    """2026-09-27 精简排版：结论先行、去说明、去无效 / 缺失内容。"""

    def _data(self):
        data = SectionReadingOrderTests()._full_data()
        data["港股名家频道"]["channels"].append({
            "name": "过期频道", "desc": "频道简介不应出现", "url": "",
            "is_today": False,
            "videos": [{"title": "两年前的旧视频", "url": "https://www.youtube.com/watch?v=old",
                        "published_cst": "2024-07-30 16:52", "is_today": False}],
        })
        return data

    def test_conclusion_first_and_summary_last(self):
        html = pipeline.generate_report(self._data(), "2026年8月2日 · 周日", "20260802")
        self.assertLess(html.find("今日结论</h2>"), html.find("行情速览</h2>"))
        self.assertIn("市场倾向", html)
        self.assertIn("核心判断", html)
        self.assertGreater(html.find("盘点总结</h2>"), html.find("AI 新闻情绪因子</h2>"))
        self.assertIn("今日盘点", html)
        self.assertIn("数据覆盖", html)
        self.assertNotIn("本次数据可用性", html)

    def test_stale_channel_and_explanations_removed(self):
        for theme in ("guizang", "pixel"):
            html = pipeline.generate_report(
                self._data(), "2026年8月2日 · 周日", "20260802", theme=theme)
            self.assertNotIn("两年前的旧视频", html)
            self.assertNotIn("过期频道", html)
            self.assertNotIn("数据暂缺", html)
            self.assertNotIn("/*", html)                      # 像素脚注
            self.assertNotIn("每个频道列出最新", html)
            self.assertNotIn("非交易时段显示最近收盘", html)
        guizang = pipeline.generate_report(self._data(), "2026年8月2日 · 周日", "20260802")
        self.assertNotIn("频道简介不应出现", guizang)
        self.assertNotIn("香港著名股評人", guizang)
        self.assertNotIn("每日量化策略（板块趋势跟踪）由公开数据经确定性规则合成", guizang)

    def test_concise_detail_drops_disclaimers(self):
        self.assertEqual(
            pipeline._concise_detail("发布于 2026-09-27 08:00（北京时间）· 社区观点未经核实"),
            "发布于 2026-09-27 08:00")
        self.assertEqual(pipeline._concise_detail("官网公开榜单；数值为抓取快照"), "")
        self.assertEqual(pipeline._concise_detail("营收 TTM 1.2 万亿 · PE 30"), "营收 TTM 1.2 万亿 · PE 30")


class SectionAiJudgeTests(unittest.TestCase):
    """逐栏目 AI 研判（规则合成）：概率化多空判断确定性、且只附在有数据的栏目。"""

    def test_prob_mapping_and_labels(self):
        p = pipeline._ai_judge_prob
        self.assertEqual(p(0, 0), 50)
        self.assertEqual(p(1, 1), 50)
        self.assertEqual(p(3, 1), 72)   # 50+45*0.5=72.5 → 72（银行家舍入）
        self.assertEqual(p(1, 3), 28)
        self.assertEqual(p(100, 0), 95)   # 全偏一侧也绝不绝对化
        self.assertEqual(p(0, 100), 5)
        self.assertEqual(pipeline._ai_judge_label(60), ("▲", "偏多"))
        self.assertEqual(pipeline._ai_judge_label(40), ("▼", "偏空"))
        self.assertEqual(pipeline._ai_judge_label(50), ("■", "中性"))

    def _sample_data(self):
        return {
            "实时行情": pipeline._source_result("quote", "success", quotes={
                "标普500": {"price": 6100, "change_pct": 1.2},
                "纳斯达克": {"price": 19000, "change_pct": 2.1},
                "WTI 原油": {"price": 70, "change_pct": -0.8},
            }),
            "Reddit": pipeline._public_site_result("Reddit", [
                {"title": "$TSLA rally to the moon, YOLO and record high",
                 "url": "https://www.reddit.com/r/wallstreetbets/comments/1/a/",
                 "detail": "发布于 2026-09-27 10:00（北京时间）",
                 "published_cst": "2026-09-27 10:00", "community": "r/wallstreetbets",
                 "is_today": True},
                {"title": "$NVDA dump risk",
                 "url": "https://www.reddit.com/r/stocks/comments/2/b/",
                 "detail": "发布于 2026-09-27 11:00（北京时间）",
                 "published_cst": "2026-09-27 11:00", "community": "r/stocks",
                 "is_today": True},
            ], latest="2026-09-27"),
            "全球头条": pipeline._source_result("google", "success", is_today=True,
                                                content_date="2026-09-27",
                                                headlines=[{"title": "美联储释放降息信号，AI 算力需求走强",
                                                            "source": "新华网", "url": "",
                                                            "published_cst": "2026-09-27 09:00",
                                                            "is_today": True}]),
        }

    def test_notes_only_for_sections_with_data_and_valid_probs(self):
        notes = pipeline.build_section_ai_notes(self._sample_data())
        self.assertEqual(set(notes), {"MARKET SNAPSHOT", "TREND CLUES", "GLOBAL HEADLINES"})
        for note in notes.values():
            self.assertEqual(note["bull_pct"] + note["bear_pct"], 100)
            self.assertTrue(5 <= note["bull_pct"] <= 95)
            self.assertIn("→ 预测：", note["text"])

    def test_reddit_note_tickers_and_direction(self):
        notes = pipeline.build_section_ai_notes(self._sample_data())
        n = notes["TREND CLUES"]
        self.assertIn("TSLA×1", n["text"])
        self.assertIn("NVDA×1", n["text"])
        # 多词 rally/moon/yolo/record high=4 > 空词 dump=1 → 偏多
        self.assertEqual(n["label"], "偏多")
        self.assertGreater(n["bull_pct"], 50)

    def test_market_note_and_render_in_both_themes(self):
        data = self._sample_data()
        notes = pipeline.build_section_ai_notes(data)
        # 2 涨 1 跌且涨幅合计 > 跌幅 → 偏多
        self.assertEqual(notes["MARKET SNAPSHOT"]["label"], "偏多")
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for theme in ("guizang", "pixel"):
                with self.subTest(theme=theme):
                    report = pipeline.generate_report(
                        data, "2026年9月27日 · 周日", "20260927", theme=theme)
                    # 有数据的 3 个栏目各一条研判行
                    self.assertEqual(report.count("⌁ AI 研判"), 3)
                    self.assertIn("多头", report)
                    self.assertIn("空头", report)
                    self.assertRegex(report, r"多头 \d{2}%")
                    # 研判行位于所属栏目内：首条研判在趋势跟踪线索栏目之前
                    self.assertLess(report.find("⌁ AI 研判"),
                                    report.find("每日量化策略趋势跟踪线索"))
        # 无任何数据 → 不出现研判行
        empty = {"实时行情": pipeline._source_result("quote", "unavailable", error="offline")}
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            report = pipeline.generate_report(empty, "2026年9月27日 · 周日", "20260927")
        self.assertNotIn("⌁ AI 研判", report)


class EconCalendarTests(unittest.TestCase):
    """「未来 N 天影响经济时间点」栏目（东方财富财经日历 RPT_CPH_FECALENDAR）。

    全程离线：接口用 mock 响应替换 safe_request。重点守住四件事——
    ① 筛选口径确定可复现（噪音必须被剔除、重要度分级稳定）；
    ② 窗口诚实（栏目写「未来 30 天」就不能出现 T+30 之外的行）；
    ③ 前瞻日程不得单独打开推送闸门（is_today=False + snapshot=True）；
    ④ 版面裁剪必须如实披露被裁条数，绝不静默丢内容。
    """

    TODAY = dt.date(2026, 9, 28)

    # ---------- 工具 ----------
    @staticmethod
    def _row(day, hm, name, city, ftype="经济数据", std="2"):
        return {"START_DATE": f"{day} {hm}:00", "END_DATE": None, "FE_CODE": "demo",
                "FE_NAME": name, "FE_TYPE": ftype, "STD_TYPE_CODE": std, "CITY": city}

    def _day(self, offset):
        return (self.TODAY + dt.timedelta(days=offset)).isoformat()

    def _rows(self):
        """一批覆盖三类内容 + 各类噪音的样本行。"""
        return [
            # 经济数据：中美核心读数（★★★）、其他主要市场（★★）
            self._row(self._day(1), "09:30", "中国:制造业PMI(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI:同比(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI:环比(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI(报告期:2026年09月)", "中国"),
            self._row(self._day(4), "20:30", "美国:非农就业人数(报告期:2026年09月)", "美国"),
            self._row(self._day(21), "10:00", "欧元区:PMI(报告期:2026年10月)", "欧元区"),
            # 事件：主要央行议息（★★★）、中国宏观决策会议（★★★）、小国央行（★★）、展会（★）
            self._row(self._day(28), "02:00", "美联储议息会议", "华盛顿", "美联储议息会议", "1"),
            self._row(self._day(20), "10:00", "国民经济运行情况发布会", "北京",
                      "国民经济运行情况发布会", "1"),
            self._row(self._day(17), "15:00", "泰国央行公布利率决议", "曼谷", "利率决议", "1"),
            self._row(self._day(13), "09:00", "2026上海国际汽车工业展览会", "上海", "展览会", "1"),
            # 动态：会议纪要 / 周报（★★）、一般资讯（★）
            self._row(self._day(9), "02:00", "美联储公布货币政策会议纪要", "美国", "", "2"),
            self._row(self._day(15), "16:00", "台积电公布月度营业额", "中国台湾", "", "2"),
            # 噪音：个股事项 / 非保留地区 / 冗余子序列 / 「:值」结尾 / 超长条目
            self._row(self._day(6), "09:30", "中国:新股申购:某某科技", "中国", "", "2"),
            self._row(self._day(8), "16:00", "中国:库存:铁矿石:46港", "中国"),
            self._row(self._day(8), "09:30", "泰国:CPI:同比(报告期:2026年09月)", "泰国"),
            self._row(self._day(9), "09:30", "中国:GDP:现价(报告期:2026年09月)", "中国"),
            self._row(self._day(10), "20:30", "美国:货物出口金额:值", "美国"),
            self._row(self._day(12), "09:30", "中国:某超长条目" + "很长" * 30, "中国"),
            # 远期口径：条目保留、误导性报告期标注丢掉
            self._row(self._day(16), "09:30", "中国:CPI:同比(报告期:2027年07月)", "中国"),
        ]

    def _fetch(self, rows=None, count=None, pages=1):
        """用 mock 响应跑一次抓取；pages>1 时验证翻页。"""
        rows = self._rows() if rows is None else rows
        total = len(rows) if count is None else count
        calls = []

        def fake_request(url, headers=None, params=None, timeout=15, is_json=True):
            calls.append(params)
            page = int(params["pageNumber"])
            if page > pages:
                return {"success": True, "result": {"count": total, "data": []}}
            per = max(1, len(rows) // pages)
            chunk = rows[(page - 1) * per:page * per] if page <= pages else []
            return {"success": True, "result": {"count": total, "data": chunk}}

        with patch.object(pipeline, "safe_request", fake_request), \
             patch.object(pipeline.time, "sleep", lambda *_: None):
            res = pipeline.fetch_econ_calendar(today=self.TODAY)
        return res, calls

    def _data(self, cal=None, with_today_source=True):
        data = {}
        if with_today_source:
            data["实时行情"] = pipeline._source_result(
                "quote", "success", is_today=True, content_date=self.TODAY.isoformat(),
                quotes={"上证指数": {"price": 3812.66, "change_pct": 0.31}})
        if cal is not None:
            data["财经日历"] = cal
        return data

    def _report(self, data, theme="guizang"):
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False), \
             patch.object(pipeline, "HK_QUANT_ENABLED", False):
            return pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928",
                                            theme=theme)

    # ---------- ① 筛选口径 ----------
    def test_classify_keeps_core_readings_and_drops_noise(self):
        kept = [it for it in (pipeline._cal_classify(r) for r in self._rows()) if it]
        names = [it["name"] for it in kept]
        self.assertIn("制造业PMI", names)
        self.assertIn("非农就业人数", names)
        # 噪音必须全部剔除
        for noise in ("新股申购", "铁矿石", "现价", "货物出口金额", "某超长条目"):
            self.assertNotIn(noise, "".join(names), f"{noise} 不应进正文")
        # 非保留地区的读数不进正文（泰国 CPI），但小国央行「事件」仍保留为 ★★
        self.assertFalse(any(it["city"] == "泰国" and it["kind"] == 0 for it in kept))
        self.assertTrue(any("泰国央行" in it["name"] for it in kept))

    def test_importance_tiers_are_stable(self):
        kept = [it for it in (pipeline._cal_classify(r) for r in self._rows()) if it]
        by_name = {it["name"]: it for it in kept}
        self.assertEqual(by_name["制造业PMI"]["imp"], 3)          # 中国一级读数
        self.assertEqual(by_name["非农就业人数"]["imp"], 3)        # 美国一级读数
        self.assertEqual(by_name["PMI"]["imp"], 2)                # 欧元区一级读数 → ★★
        self.assertEqual(by_name["美联储议息会议"]["imp"], 3)
        self.assertEqual(by_name["国民经济运行情况发布会"]["imp"], 3)
        self.assertEqual(by_name["泰国央行公布利率决议"]["imp"], 2)  # 小国央行
        self.assertEqual(by_name["2026上海国际汽车工业展览会"]["imp"], 1)  # 展会
        self.assertEqual(by_name["美联储公布货币政策会议纪要"]["kind"], 2)  # 动态
        self.assertLessEqual(by_name["美联储公布货币政策会议纪要"]["imp"], 2)

    def test_event_importance_reads_name_not_city_field(self):
        """事件行的 CITY 常是城市名（华盛顿 / 法兰克福），不能拿它当国家判定。"""
        fed = pipeline._cal_classify(self._row(self._day(5), "02:00", "美联储议息会议",
                                               "华盛顿", "美联储议息会议", "1"))
        self.assertEqual(fed["imp"], 3)
        minor = pipeline._cal_classify(self._row(self._day(5), "15:00", "某国央行公布利率决议",
                                                 "未知市", "利率决议", "1"))
        self.assertEqual(minor["imp"], 2)

    def test_far_future_period_label_dropped_but_item_kept(self):
        item = pipeline._cal_classify(
            self._row(self._day(16), "09:30", "中国:CPI:同比(报告期:2027年07月)", "中国"))
        self.assertIsNotNone(item, "远期口径不应整条丢掉")
        self.assertEqual(item["period"], "", "误导性报告期标注必须丢掉")
        normal = pipeline._cal_classify(
            self._row(self._day(11), "09:30", "中国:CPI:同比(报告期:2026年09月)", "中国"))
        self.assertEqual(normal["period"], "2609")
        self.assertEqual(pipeline._cal_period_label("2609", self.TODAY), "9月")
        self.assertEqual(pipeline._cal_period_label("2701", self.TODAY), "2027年1月")

    def test_dedupe_merges_same_indicator_variants_into_one_row(self):
        rows = [
            self._row(self._day(11), "09:30", "中国:CPI:同比(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI:环比(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:CPI(报告期:2026年09月)", "中国"),
            self._row(self._day(11), "09:30", "中国:核心CPI:同比(报告期:2026年09月)", "中国"),
        ]
        items = pipeline._cal_dedupe([it for it in (pipeline._cal_classify(r) for r in rows) if it])
        cpi = [it for it in items if pipeline._cal_base_of(it["name"]) == "CPI"]
        self.assertEqual(len(cpi), 1, "同比 / 环比 / 裸名应合并成一行")
        self.assertEqual(cpi[0]["kou"], ["同比", "环比"])
        self.assertIn("CPI:同比/环比", pipeline._cal_item_text(cpi[0], self.TODAY))
        # 核心CPI 是另一个指标，不能被合并掉
        self.assertTrue(any("核心CPI" in it["name"] for it in items))

    def test_strip_country_prefix_without_hurting_real_words(self):
        self.assertEqual(pipeline._cal_strip_country("美国:CPI:同比", "美国"), "CPI:同比")
        self.assertEqual(pipeline._cal_strip_country("美国EIA原油库存", "美国"), "EIA原油库存")
        # 「中国银行间同业拆借」里的「中国」是词的一部分，不能剥
        self.assertEqual(pipeline._cal_strip_country("中国银行间同业拆借", "中国"),
                         "中国银行间同业拆借")

    # ---------- ② 窗口诚实 ----------
    def test_rows_outside_window_are_clamped_locally(self):
        rows = self._rows() + [self._row(self._day(32), "19:00", "欧洲央行公布利率决议",
                                         "法兰克福", "利率决议", "1")]
        res, _ = self._fetch(rows=rows)
        self.assertEqual(res["status"], "success")
        dates = {it["date"] for it in res["items"]}
        self.assertNotIn(self._day(32), dates, "T+32 不得出现在「未来30天」栏目里")
        self.assertNotIn(self._day(32), res["window"])
        self.assertTrue(all(self.TODAY.isoformat() <= d <= self._day(30) for d in dates))

    def test_paging_follows_server_count(self):
        rows = self._rows()
        res, calls = self._fetch(rows=rows, count=len(rows) * 2, pages=2)
        self.assertEqual(res["status"], "success")
        self.assertGreaterEqual(len(calls), 2, "count 未取满时必须继续翻页")
        self.assertEqual(calls[0]["reportName"], "RPT_CPH_FECALENDAR")
        self.assertIn("START_DATE>='2026-09-28'", calls[0]["filter"])
        self.assertIn("START_DATE<'2026-10-29'", calls[0]["filter"])

    def test_failure_degrades_to_zanque_with_reason(self):
        with patch.object(pipeline, "safe_request", lambda *a, **k: None):
            res = pipeline.fetch_econ_calendar(today=self.TODAY)
        self.assertEqual(res["status"], "failed")
        self.assertTrue(res.get("error"), "失败必须给出原因，不能静默")
        self.assertEqual(res["items"], [])
        self.assertFalse(res.get("is_today"))
        self.assertFalse(res.get("snapshot"))

    def test_empty_window_is_reported_as_failure_not_as_empty_calendar(self):
        with patch.object(pipeline, "safe_request",
                          lambda *a, **k: {"success": True, "result": {"count": 0, "data": []}}):
            res = pipeline.fetch_econ_calendar(today=self.TODAY)
        self.assertEqual(res["status"], "failed")
        self.assertIn("接口未返回窗口内日程", res["error"])

    # ---------- ③ 推送闸门与审计口径 ----------
    def test_calendar_alone_never_unlocks_push_gate(self):
        """前瞻日程不是「当天内容」：只有它成功时仍不得推送（防旧内容/空报告）。"""
        res, _ = self._fetch()
        can_push, reason = pipeline.check_push_eligibility(self._data(res, with_today_source=False))
        self.assertFalse(can_push)
        self.assertIn("当天检验未通过", reason)
        self.assertFalse(res["is_today"])
        self.assertTrue(res["snapshot"], "应标为「今日抓取」快照，而不是当天发布")

    def test_calendar_does_not_change_today_source_count(self):
        res, _ = self._fetch()
        base = self._report(self._data(with_today_source=True))
        with_cal = self._report(self._data(res))
        meta_base = pipeline._report_meta(base)
        meta_cal = pipeline._report_meta(with_cal)
        self.assertEqual(meta_cal["today_sources"], meta_base["today_sources"])
        self.assertEqual(meta_cal["total_sources"], meta_base["total_sources"] + 1)

    def test_absent_calendar_keeps_source_count_unchanged(self):
        """OCTOPUS_CALENDAR=0 时不采集 → 不进审计，总源数与改动前一致（+1 只在采集时发生）。"""
        base = pipeline._report_meta(self._report(self._data(with_today_source=True)))
        res, _ = self._fetch()
        with_cal = pipeline._report_meta(self._report(self._data(res)))
        self.assertEqual(base["total_sources"], 9, "基础审计源数量不应被本次改动改变")
        self.assertEqual(with_cal["total_sources"], base["total_sources"] + 1)

    def test_failed_calendar_is_named_in_coverage_line(self):
        with patch.object(pipeline, "safe_request", lambda *a, **k: None):
            res = pipeline.fetch_econ_calendar(today=self.TODAY)
        html = self._report(self._data(res))
        self.assertNotIn("未来30天影响经济时间点", html, "抓取失败的栏目不进正文")
        self.assertRegex(html, r"暂缺：[^<]*财经日历")

    # ---------- ④ 排版与披露 ----------
    def test_section_renders_right_after_conclusion_in_both_themes(self):
        res, _ = self._fetch()
        for theme, markers in (
            ("guizang", ["今日结论</h2>", "未来30天影响经济时间点</h2>", "行情速览</h2>"]),
            ("pixel", ["LVL 01 // CONCLUSION", "LVL 02 // ECON CALENDAR",
                       "LVL 03 // MARKET SNAPSHOT"]),
        ):
            html = self._report(self._data(res), theme=theme)
            positions = [html.find(m) for m in markers]
            self.assertNotIn(-1, positions, f"{theme} 栏目缺失: {markers}")
            self.assertEqual(positions, sorted(positions),
                             f"{theme} 新栏目必须紧跟今日结论、在行情速览之前")

    def test_section_body_carries_window_summary_and_star_levels(self):
        res, _ = self._fetch()
        html = self._report(self._data(res))
        for text in ("窗口摘要", "时间窗口", "时间点合计", "央行议息 / 重要会议",
                     "中国关键读数", "美国关键读数", "最密集日", "筛选口径",
                     "逐日时间点（北京时间）", "★★★", "美联储议息会议"):
            self.assertIn(text, html, f"摘要/正文缺少 {text}")
        self.assertIn("未来 30 天", html)
        # 每个列出的时间点都要能看到地区与类型标签（数据 / 事件 / 动态）
        self.assertIn("数据", html)
        self.assertIn("事件", html)

    def test_row_cap_discloses_every_dropped_item_by_level(self):
        rows = []
        for i in range(70):                      # 造出远超上限的 ★★★ 条目
            rows.append(self._row(self._day(1 + i % 29), f"{9 + i % 8}:30",
                                  f"中国:CPI:同比{i}(报告期:2026年09月)", "中国"))
        res, _ = self._fetch(rows=rows)
        limit = pipeline.ECON_CALENDAR_MAX_ROWS
        self.assertEqual(len(res["items"]), limit)
        self.assertEqual(res["dropped"], len(rows) - limit)
        self.assertEqual(sum(int(v) for v in res["dropped_imp"].values()), res["dropped"])
        digest = pipeline._cal_digest(res, self.TODAY)
        total_line = dict(digest["pairs"])["时间点合计"]
        self.assertIn(f"版面另有 {res['dropped']} 条未列出", total_line)
        self.assertIn("★★★", total_line, "被裁条目的重要度分布必须写清楚")

    def test_low_importance_rows_are_cut_before_core_readings(self):
        rows = self._rows() + [
            self._row(self._day(2), "09:00", f"某展会{i}届博览会", "上海", "博览会", "1")
            for i in range(80)
        ]
        with patch.object(pipeline, "ECON_CALENDAR_MAX_ROWS", 20):
            res, _ = self._fetch(rows=rows)
        names = "".join(it["name"] for it in res["items"])
        self.assertIn("美联储议息会议", names, "★★★ 事件不能被 ★ 级展会挤掉")
        self.assertIn("制造业PMI", names)
        self.assertLessEqual(sum(1 for it in res["items"] if it["imp"] == 1), 20 - 8)

    def test_digest_counts_match_items(self):
        res, _ = self._fetch()
        digest = pipeline._cal_digest(res, self.TODAY)
        pairs = dict(digest["pairs"])
        counts = pipeline._cal_imp_counts(res["items"])
        self.assertIn(f"{len(res['items'])} 个", pairs["时间点合计"])
        self.assertIn(f"★★★ {counts['3']}", pairs["时间点合计"])
        day_items = sum(len(items) for _d, _l, _t, items in digest["days"])
        self.assertEqual(day_items, len(res["items"]), "逐日展开必须与条目数一致")
        # 摘要里点名的时间点必须真的在列表里（不得凭空生成日程）
        for label in ("央行议息 / 重要会议", "中国关键读数", "美国关键读数"):
            for chunk in re.split(r"[、,]", pairs[label].split(" 等 ")[0]):
                name = chunk.split(" ", 1)[-1].strip()
                if name and name != "窗口内暂无":
                    self.assertIn(name[:6], "".join(it["name"] for it in res["items"]),
                                  f"{label} 里的 {name} 不在抓取结果中")

    def test_calendar_block_renders_in_both_kits_and_stays_balanced(self):
        res, _ = self._fetch()
        for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
            block = kit.calendar_block(res)
            self.assertIn("窗口摘要", block)
            self.assertEqual(block.count("<table"), block.count("</table>"),
                             "表格必须成对闭合（微信端半截标签会整页崩版）")

    def test_calendar_only_cli_mode_prints_without_pushing(self):
        res, _ = self._fetch()
        with patch.object(pipeline, "fetch_econ_calendar", lambda days=None: res), \
             patch.object(pipeline, "push_to_wechat", lambda *a, **k: self.fail("研究模式不得推送")), \
             patch.object(pipeline, "generate_report", lambda *a, **k: self.fail("研究模式不得生成日报")):
            self.assertEqual(pipeline.calendar_only_report(), 0)


if __name__ == "__main__":
    unittest.main()
