"""无需网络的日报新鲜度回归测试。"""
import importlib.util
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
            "Yahoo头条": pipeline._source_result("test news", "unavailable", headlines=[], error="offline"),
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

    def test_save_replaces_existing_file_and_latest_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "report.html"
            target.write_text("old", encoding="utf-8")
            old_report_dir = pipeline.REPORT_DIR
            try:
                pipeline.REPORT_DIR = directory
                pipeline.save_report("new", str(target), {})
            finally:
                pipeline.REPORT_DIR = old_report_dir
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
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
            self.assertRegex(Path(actual).name, r"daily_report_20260801_\d{6}(?:_\d+)?\.html")
            self.assertEqual(Path(actual).read_text(encoding="utf-8"), "newest")
            self.assertEqual((Path(directory) / "latest.html").read_text(encoding="utf-8"), "newest")

    # ------------------------------------------------------------------
    # 新版：YouTube 财经频道 + 空区块不渲染 + 当天检验
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
            "YouTube财经频道": pipeline._source_result(
                "test yt", "success", is_today=yt_today, content_date="2026-08-01",
                channels=[{
                    "name": "测试财经频道",
                    "url": "https://www.youtube.com/@test",
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
            ),
            "Yahoo头条": pipeline._source_result("test news", "unavailable", headlines=[], error="offline"),
            "A股资讯": pipeline._source_result("test sina", "unavailable", headlines=[], error="offline"),
            "韩股半导体": pipeline._source_result("test korea", "unavailable", headlines=[], error="offline"),
            "Reddit WSB热议": pipeline._source_result("test wsb", "unavailable", stocks=[], error="offline"),
        }
        return data

    def test_new_layout_renders_youtube_section_and_badges(self):
        html = pipeline.generate_report(self._sample_data(), "2026年8月1日 · 周六", "20260801")
        self.assertIn("YouTube 财经资讯与新闻频道", html)
        self.assertIn("测试财经频道", html)
        self.assertIn("今日市场解读", html)
        self.assertIn("当天", html)          # 当天徽标
        self.assertIn("当天内容检验", html)   # 检验横幅

    def test_new_layout_omits_empty_sections_and_keeps_meta(self):
        data = self._sample_data()
        data["YouTube财经频道"] = pipeline._source_result("test yt", "unavailable", channels=[], error="offline")
        data["Yahoo头条"] = pipeline._source_result("test news", "success", is_today=True,
                                                    content_date="2026-08-01",
                                                    headlines=["一则今天的全球头条"])
        html = pipeline.generate_report(data, "2026年8月1日 · 周六", "20260801")
        # 没有数据的 YouTube 区块不渲染主体卡片
        self.assertNotIn("YouTube 财经资讯与新闻频道", html)
        # 页脚状态清单仍留痕（含“数据暂缺”字样）
        self.assertIn("数据暂缺", html)
        self.assertIn("本次数据可用性", html)
        # 元信息可供 --push-only 二次当天检验
        meta = pipeline._report_meta(html)
        self.assertEqual(meta["date"], "20260801")
        self.assertGreaterEqual(meta["today_sources"], 1)
        self.assertEqual(meta["total_sources"], 6)

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
                 for k in ["实时行情", "YouTube财经频道", "Yahoo头条", "A股资讯", "韩股半导体", "Reddit WSB热议"]}
        can_push, reason = pipeline.check_push_eligibility(empty)
        self.assertFalse(can_push)
        self.assertIn("0/", reason)

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
            "Yahoo头条": pipeline._source_result("n", "success", is_today=True,
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
            "Yahoo头条": pipeline._source_result("n", "unavailable", headlines=[], error="offline"),
        }
        text = pipeline.build_no_push_alert_text("抓到 1/2 个来源，但没有一个属于当天内容",
                                                 data, "/tmp/daily_report_20260801.html")
        self.assertIn("当天内容检验未通过", text)
        self.assertIn("抓到 1/2 个来源", text)
        self.assertIn("实时行情：🕓 非当天（数据日期 2026-07-31）", text)
        self.assertIn("Yahoo头条：⚠️ 无数据", text)
        self.assertIn("force_push", text)                      # 给出人工处理入口
        self.assertIn("daily_report_20260801.html", text)      # 报告文件可追溯


class MainExitCodeTests(unittest.TestCase):
    """main() 退出码：应推未推成 → 1；有意跳过 / 推送成功 / 告警送达 → 0。"""

    def _today_data(self):
        return {
            "Yahoo头条": pipeline._source_result("n", "success", is_today=True,
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


if __name__ == "__main__":
    unittest.main()
