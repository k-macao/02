"""无需网络的日报新鲜度回归测试。"""
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
        self.assertIn("数据暂缺", html)
        self.assertIn("本次数据可用性", html)
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
        # 页脚状态清单仍留痕（含“数据暂缺”字样）
        self.assertIn("数据暂缺", html)
        self.assertIn("本次数据可用性", html)
        # 元信息可供 --push-only 二次当天检验
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["date"], "20260801")
        self.assertGreaterEqual(meta["today_sources"], 1)
        self.assertEqual(meta["total_sources"], 8)  # 8 个数据源（2026-09-08 新增「A股大盘全景」；Reddit / 韩股已移除）

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




class LiquidityReportTests(unittest.TestCase):
    """新增：AI 研判分析最近收盘 A股、港股、美股成交量与流动性报告。"""

    def _liquidity_data(self):
        markets = {}
        for label in ["A股", "港股", "美股"]:
            stocks = [{
                "code": f"000{i:03d}", "name": f"{label}股票{i}", "price": 10 + i,
                "change_pct": 1.0 if i % 3 else -0.5,
                "amount": 100000000 - i * 1000000,
                "turnover": 2.5 + i * 0.1,
            } for i in range(12)]
            markets[label] = {"desc": label, **pipeline._analyze_liquidity_market(label, stocks)}
        return pipeline._source_result(
            "东方财富流动性", "success", is_today=True, content_date="2026-08-02",
            markets=markets, summary="A股流动性评分相对领先；美股头部成交集中度最高。",
            sample_size=300)

    def test_fetch_liquidity_report_parses_a_and_hk(self):
        def fake_request(url, params=None, **kw):
            return {"data": {"diff": [
                {"f12": f"00{i:04d}", "f14": f"样本{i}", "f2": 10 + i,
                 "f3": 1.2 if i % 2 else -0.3, "f6": 50000000 - i * 100000,
                 "f8": 2.0 + i * 0.01}
                for i in range(20)
            ]}}

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_liquidity_report()
        self.assertEqual(result["status"], "success")
        self.assertEqual(set(result["markets"].keys()), {"A股", "港股", "美股"})
        self.assertEqual(result["markets"]["A股"]["sample_count"], 20)
        self.assertIn("score", result["markets"]["港股"])
        self.assertIn("score", result["markets"]["美股"])
        self.assertIn("summary", result)

    def test_liquidity_report_renders_in_generate_report(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A港美流动性"] = self._liquidity_data()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")
        self.assertIn("AI 研判 · 最近 A股、港股、美股成交量与流动性分析", html)
        self.assertIn("三大市场交投研判", html)
        self.assertIn("A股成交量与流动性研判：", html)
        self.assertIn("港股成交量与流动性研判：", html)
        self.assertIn("美股成交量与流动性研判：", html)
        self.assertIn("流动性评分", html)
        self.assertIn("AI 定性", html)
        # 2026-08-06 起不展示个股排名表（TOP5 VOLUME 流动性锚点已移除）
        self.assertNotIn("TOP5 VOLUME", html)
        self.assertNotIn("流动性锚点", html)
        # 榜单个股只作为 AI 研判的输入：不再出现在「WATCH LIST // 明日关注」个股清单
        # （2026-08-06 起该面板只保留主题行），仅作为交投研判中活跃标的的提及。
        self.assertIn("A股股票0", html)
        self.assertIn("港股股票0", html)
        self.assertIn("美股股票0", html)
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 8)  # 8 个数据源（2026-09-08 新增「A股大盘全景」；Reddit / 韩股已移除）

    def test_volume_and_liquidity_analysis_html_synthesizes_hot_and_liq(self):
        liq = self._liquidity_data()
        hot = NewLayoutRenderingTests()._rich_data()["热门榜单"]
        html_block = pipeline._build_volume_and_liquidity_analysis_html(liq, hot)
        self.assertIn("A股成交量与流动性研判：", html_block)
        self.assertIn("港股成交量与流动性研判：", html_block)
        self.assertIn("美股成交量与流动性研判：", html_block)
        self.assertIn("A股股票0", html_block)
        self.assertIn("流动性评分", html_block)
        self.assertIn("头部前十成交集中度", html_block)

    def test_multi_factor_ai_conclusions_include_yahoo_and_four_100word_conclusions(self):
        liq = self._liquidity_data()
        hot = NewLayoutRenderingTests()._rich_data()["热门榜单"]
        market = pipeline._source_result(
            "Yahoo Finance Chart", "success", is_today=True, content_date="2026-08-02",
            quotes={"标普500": {"price": 6000.0, "change_pct": 1.0, "volume": 12000000},
                    "上证指数": {"price": 3100.0, "change_pct": 0.5, "volume": 350000000},
                    "恒生指数": {"price": 18000.0, "change_pct": 1.2, "volume": 150000000}})
        data = NewLayoutRenderingTests()._rich_data()
        html = pipeline._build_multi_factor_ai_conclusions_html(liq, hot, market, data)
        self.assertIn("◆ 整体市场 · 雅虎行情、环境·政治·地缘 多因子 AI 结论", html)
        self.assertIn("◆ A股 · 雅虎行情、成交量、流动性与多因子 AI 结论", html)
        self.assertIn("◆ 港股 · 雅虎行情、成交量、流动性与多因子 AI 结论", html)
        self.assertIn("◆ 美股 · 雅虎行情、成交量、流动性与多因子 AI 结论", html)
        self.assertIn("雅虎", html)
        self.assertIn("环境", html)
        self.assertIn("政治", html)
        self.assertIn("地缘", html)
        self.assertIn("观点一", html)
        self.assertIn("观点二", html)
        self.assertIn("观点三", html)
        self.assertIn("每观点一句话", html)

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
        self.assertIn("热门榜单", html)  # 仍作为数据源出现在数据审计栏
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
        self.assertEqual(meta["total_sources"], 8)  # 数据源共 8 个（2026-09-08 新增「A股大盘全景」；Reddit / 韩股已移除）


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
        self.assertIn("LVL 01 // AI READ", html)
        self.assertIn("AI CORE OUTPUT", html)
        self.assertIn("AI 主结论 // CORE THESIS", html)
        self.assertIn("READ THIS FIRST // 先看结论", html)
        self.assertIn("▲ 涨 +1.25%", html)  # 标普行情
        self.assertIn("▼ 跌 -2.50%", html)  # 深证行情
        self.assertIn("▼ -2.50%", html)     # AI 盘研判 TECH READ 的 compact 徽标
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
        self.assertIn("WATCH LIST // 明日关注", html)
        self.assertIn("★ THEME UNLOCKED // AI/算力、半导体/芯片", html)
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

    def test_guizang_page_style_tokens_and_vertical_layout(self):
        data = NewLayoutRenderingTests()._rich_data()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")  # 默认 = guizang
        self.assertIn(f"<title>{pipeline.REPORT_TITLE}</title>", html)
        self.assertIn(pipeline.GZ_PAPER, html)
        self.assertIn(pipeline.GZ_PAPER_TINT, html)   # 仅结论使用浅色背景
        self.assertIn(pipeline.GZ_INK, html)
        for old_color in ("#30342F", "#D5D7D3", "#B7FF3C"):
            self.assertNotIn(old_color, html)
        self.assertIn("max-width:760px;margin:0 auto", html)
        self.assertIn("padding:0 24px", html)
        self.assertIn("padding:40px 0 16px", html)
        self.assertIn("line-height:1.85", html)
        self.assertNotIn("user-scalable=no", html)
        self.assertNotIn("●", html)
        self.assertNotIn("○", html)
        self.assertNotIn("SYS_TIME:", html)
        self.assertEqual(html.count("<h1 "), 1)
        self.assertGreater(html.count("<h2 "), 1)
        # 字体分工：衬线标题 + 非衬线正文 + 等宽元信息；短字体栈避免
        # 数百次重复后撑破 PushPlus 10 万字符上限。
        self.assertIn("Songti SC", html)
        self.assertIn("PingFang SC", html)
        self.assertIn("font-family:monospace", html)
        self.assertNotIn("IBM Plex Mono", html)
        # 发丝线与留白
        self.assertIn(pipeline.GZ_HAIR, html)
        # 中文标题，不再重复英文栏目编号。
        self.assertNotIn("01 · AI READ", html)
        self.assertIn("AI 盘研判</h2>", html)
        self.assertIn("▲ 涨", html)
        # 涨跌三重编码保留（颜色 + 箭头 + 文字）
        self.assertIn("▲ 涨 +1.25%", html)
        self.assertNotIn("OCTOPUS_OS", html)          # 不再是像素主题
        # 微信稳排：刊头单列、无 inline-block 胶囊、无 nowrap 挤爆、无 8px 英文 kicker
        self.assertNotIn("white-space:nowrap", html)
        self.assertNotIn("display:inline-block", html)
        self.assertNotIn('width="33%"', html)
        self.assertNotIn("font-size:8px", html)
        self.assertIn("bgcolor=", html.lower())
        self.assertIn("font-size:16px", html)

    def test_minimal_news_card_leads_with_title_and_keeps_source(self):
        html = pipeline.gz_headline_row({
            "title": "港股市场观察", "source": "测试来源", "published_cst": "2026-09-08 10:00"
        }, 1)
        self.assertLess(html.index("港股市场观察"), html.index("测试来源"))
        self.assertIn("2026-09-08 10:00", html)
        self.assertNotIn(">01", html)
        self.assertIn("padding:20px 0", html)

    def test_minimal_section_retains_freshness_without_dark_panels(self):
        html = pipeline.gz_section("01", "MARKET SNAPSHOT", "行情速览", "原始内容",
                                   pipeline.gz_badge("非当天 2026-09-07", "warn"), "数据来源")
        for text in ("行情速览", "原始内容", "非当天 2026-09-07", "数据来源"):
            self.assertIn(text, html)
        self.assertNotIn("MARKET SNAPSHOT", html)
        self.assertNotIn("#30342F", html)

    def test_guizang_inline_only_with_remote_koboyo_icons(self):
        data = NewLayoutRenderingTests()._rich_data()
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")
        low = html.lower()
        self.assertNotIn("<style", low)
        self.assertNotIn("<script", low)
        images = re.findall(r'<img\b[^>]*>', html)
        # 图片 = 每个栏目标题 1 枚大图标 + 刊头 64px 章鱼 + 刊头栏目图标列（去重后的全部栏目图标）
        self.assertEqual(len(images), html.count("<h2 ") + 1 + len(pipeline.KOBOYO_MASTHEAD_ICONS))
        for image in images:
            self.assertRegex(image, r'src="https://koboyo\.com/icons/svg/[a-z]+\.svg"')
            self.assertIn('alt=""', image)
            self.assertIn('aria-hidden="true"', image)
            self.assertRegex(image, r'width="(?:32|40|64)"')
            self.assertRegex(image, r'height="(?:32|40|64)"')
        self.assertNotIn("<svg", low)                 # 只用链接，不内嵌或保存图标
        self.assertNotIn("data:image", low)
        self.assertNotIn("link rel", low)             # 无外部 CSS
        self.assertNotIn("onload", low)
        self.assertNotIn("onclick", low)
        self.assertNotIn("webgl", low)

    def test_japanese_design_uses_grayscale_and_serif_headings(self):
        html = pipeline.generate_report(NewLayoutRenderingTests()._rich_data(), "测试日期", "20260908")
        for color in re.findall(r"#[0-9A-Fa-f]{6}", html):
            self.assertEqual(color[1:3], color[3:5], color)
            self.assertEqual(color[3:5], color[5:7], color)
        for heading in re.findall(r'<h[12]\b[^>]*>', html):
            self.assertIn("Hiragino Mincho ProN", heading)
            self.assertIn("Songti SC", heading)
            self.assertIn("letter-spacing:", heading)
            self.assertIn("font-weight:700", heading)   # 标题统一加粗宋体
        for h1 in re.findall(r'<h1\b[^>]*>', html):
            self.assertIn("font-size:34px", h1)          # 主标题加大
        for h2 in re.findall(r'<h2\b[^>]*>', html):
            self.assertIn("font-size:26px", h2)          # 栏目标题加大
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
        self.assertIn('width="64"', icon)
        self.assertNotIn('onerror', icon)
        self.assertIn('loading="eager"', pipeline.gz_icon("octopus", 48, masthead=True))
        self.assertIn('loading="lazy"', pipeline.gz_icon("brain"))

    def test_guizang_market_table_becomes_vertical_rowline(self):
        data = ReportFreshnessTests()._sample_data()
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801")
        # rowline：每条行情一行（左等宽指数名 / 右价格 + 涨跌徽标），无横向列
        self.assertIn("6,123", html)                  # 标普500 价格
        self.assertIn("数据暂缺", html)                # 缺失指数明确标注
        self.assertIn("border-top:1px solid " + pipeline.GZ_HAIR, html)
        self.assertIn("border-bottom:1px solid " + pipeline.GZ_HAIR, html)
        self.assertIn("全球与美股", html)
        self.assertIn("A股四指数", html)

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

    def test_guizang_signal_matrix_keeps_direction_probability_and_evidence(self):
        data = NewLayoutRenderingTests()._rich_data()
        liq = LiquidityReportTests()._liquidity_data()
        data["A港美流动性"] = liq
        html = pipeline.generate_report(data, "2026年8月2日 · 周日", "20260802")
        # 因子分析 → 杂志式信号矩阵
        self.assertIn("信号矩阵", html)
        self.assertIn("MULTI-FACTOR AI THESIS", html)
        # 三因子（环境/政治/地缘）+ 证据句保留
        self.assertIn("01 · ENV 环境", html)
        self.assertIn("02 · POL 政治", html)
        self.assertIn("03 · GEO 地缘", html)
        self.assertIn("美联储利率转向预期的博弈", html)
        # 概率（规则估算，涨跌颜色区分）：整体市场 P 75%（+1.25%）、A股 P 58%（+0.40%）
        self.assertIn("P 75%", html)
        self.assertIn("P 58%", html)
        self.assertIn("概率为规则估算", html)
        self.assertIn("研判概率", html)                # 研判概率标签
        # 涨跌颜色保留
        self.assertIn(pipeline.GZ_UP, html)
        self.assertIn(pipeline.GZ_DOWN, html)

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
        self.assertEqual(meta["total_sources"], 8)  # 8 个数据源（含 A股大盘全景）


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

    def _install_fake_requests(self, with_kline=True, with_kamt=True, with_sectors=True):
        def fake(url, params=None, **kw):
            if "ulist.np" in url:
                return {"data": {"diff": self._indices_diff()}}
            if "stock/kline" in url:
                if not with_kline:
                    return None
                base = {"1.000001": 4.8e11, "0.399001": 6.0e11, "0.899050": 7.0e9}[
                    (params or {}).get("secid")]
                return {"data": {"klines": [f"2026-09-07,{base}", f"2026-09-08,{base * 1.05:.0f}"]}}
            if "kamt.kline" in url:
                if not with_kamt:
                    return None
                return {"data": {"s2n": ["2026-09-08,-,1350.25"], "n2s": []}}
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

        # ④ 北向资金：净买列为 "-"，取行内最后一个数值作为成交总额（亿元）
        north = result["north"]
        self.assertTrue(north["available"])
        self.assertEqual(north["amount_yi"], 1350.25)
        self.assertEqual(north["date"], "2026-09-08")
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
        with self._install_fake_requests(with_kline=False, with_kamt=False, with_sectors=False):
            result = pipeline.fetch_market_panorama()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["indices"]), 8)
        self.assertIsNotNone(result["turnover"])
        self.assertIsNone(result["turnover"]["prev_total"])
        self.assertIsNone(result["turnover"]["chg_pct"])
        self.assertFalse(result["north"]["available"])
        self.assertEqual(result["sectors"], {"leading": [], "lagging": []})
        self.assertTrue(result["partial"])
        self.assertIn("北向", result["error"])
        self.assertIn("板块热力", result["error"])

    def test_breadth_mood_thresholds(self):
        self.assertEqual(pipeline._panorama_breadth_mood(2.0), "普涨强势")
        self.assertEqual(pipeline._panorama_breadth_mood(1.2), "偏多震荡")
        self.assertEqual(pipeline._panorama_breadth_mood(0.8), "多空均衡")
        self.assertEqual(pipeline._panorama_breadth_mood(0.5), "偏空承压")
        self.assertEqual(pipeline._panorama_breadth_mood(0.49), "普跌弱势")
        self.assertEqual(pipeline._panorama_breadth_mood(None), "数据不足")

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
        self.assertIn("普涨强势", html)
        self.assertIn("3.12", html)
        self.assertIn("成交额", html)
        self.assertIn("北向资金", html)
        self.assertIn("1,350.25 亿元", html)
        self.assertIn("2024-08-19", html)          # 披露口径说明
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
        self.assertIn("北向资金", html)
        self.assertIn("板块热力", html)
        self.assertIn("领涨板块甲", html)

    def test_panorama_section_absent_and_audited_when_unavailable(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = pipeline._source_result(
            "东方财富·A股全景", "unavailable", indices=[], breadth=None, turnover=None,
            north={"available": False, "amount_yi": None, "date": None,
                   "policy_note": pipeline.PANORAMA_NORTH_POLICY_NOTE, "error": "offline"},
            sectors={"leading": [], "lagging": []}, quote_time=None, error="offline")
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908")
        self.assertNotIn("A股大盘全景复盘", html)   # 栏目标题不渲染
        self.assertIn("A股大盘全景", html)           # 数据审计栏仍留痕
        self.assertIn("暂缺", html)
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 8)  # 源数与是否有数据无关

    def test_panorama_counts_in_audit_and_eligibility(self):
        data = NewLayoutRenderingTests()._rich_data()
        data["A股大盘全景"] = self._panorama_payload()
        html = pipeline.generate_report(data, "2026年9月8日 · 周二", "20260908")
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 8)  # 审计源数固定，与实收数据无关
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


if __name__ == "__main__":
    unittest.main()
