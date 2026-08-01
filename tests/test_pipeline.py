"""无需网络的日报新鲜度回归测试。"""
import importlib.util
import os
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
            "韩股半导体": pipeline._source_result("test korea", "unavailable", headlines=[], error="offline"),
            "Reddit WSB热议": pipeline._source_result("test wsb", "unavailable", stocks=[], error="offline"),
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
            "韩股半导体": pipeline._source_result("test korea", "unavailable", headlines=[], error="offline"),
            "Reddit WSB热议": pipeline._source_result("test wsb", "unavailable", stocks=[], error="offline"),
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
        self.assertEqual(meta["total_sources"], 8)

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
                 for k in ["实时行情", "港股名家频道", "全球头条", "A股资讯", "韩股半导体", "Reddit WSB热议"]}
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
        self.assertEqual(html.count("▶️"), pipeline.CHANNEL_TOP_N)  # 每频道只列前 3 条
        self.assertIn("视频0", html)
        self.assertIn("视频2", html)
        self.assertNotIn("视频3", html)  # 第 4/5 条不展示

    def test_unsupported_channel_block_marks_zhanque(self):
        ch = {"name": "港股交易員（微博大V）", "desc": "測試",
              "note": "微博需登录 / 反爬限制，暂不支持自动抓取"}
        html = pipeline._channel_block(ch)
        self.assertIn("暂缺", html)
        self.assertIn("微博需登录", html)
        self.assertNotIn("▶️", html)  # 没有伪造内容

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
    """2026-08-02 新增：东方财富快讯（5 条最新新闻）与热门榜单（A股/港股/美股涨幅前十）。"""

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
        def fake_request(url, params=None, **kw):
            return {"data": {"diff": [
                {"f12": f"60000{i}", "f14": f"股票{i}", "f2": "10.5", "f3": "9.87"}
                for i in range(10)
            ]}}

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_hot_stocks()
        self.assertEqual(result["status"], "success")
        self.assertEqual(set(result["markets"].keys()), {"A股", "港股", "美股"})
        self.assertEqual(len(result["markets"]["A股"]["stocks"]), 10)
        self.assertEqual(result["markets"]["港股"]["stocks"][0]["code"], "600000")
        self.assertEqual(result["markets"]["美股"]["stocks"][9]["change_pct"], "9.87")

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
        self.assertIn("热门榜单", html)
        self.assertIn("A股涨幅前十", html)
        self.assertIn("美股涨幅前十", html)
        self.assertIn("美联储释放降息信号", html)
        # 不再渲染 AI 总览相关元素
        self.assertNotIn("AI 总览", html)
        self.assertNotIn("栏目 AI 研判表", html)
        self.assertNotIn("Gemini", html)
        self.assertNotIn("GEMINI", html)
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["total_sources"], 8)  # 数据源扩展到 8 个


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


if __name__ == "__main__":
    unittest.main()
