"""每日量化策略趋势跟踪线索（Reddit 单一来源）的离线解析、降级、主题渲染及推送门禁测试（不访问网站/不写历史报告）。"""
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

# CI 装有 requests；本地最小环境没有时仅提供导入占位，请求一律 mock。
sys.modules.setdefault("requests", types.SimpleNamespace())
PATH = Path(__file__).parents[1] / "output" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_public_sites_test", PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)


def heat_html(score, comments):
    """模拟 Reddit RSS <content type="html"> 里的热度片段（XML 转义后的 HTML）。"""
    return (f"&lt;div class=&quot;score unvoted&quot; title=&quot;{score}&quot;&gt;{score} points&lt;/div&gt; "
            f"&lt;span class=&quot;number-of-comments&quot;&gt;{comments} comments&lt;/span&gt;")


def atom_entry(title, url, dt, content=""):
    date = dt.astimezone(timezone.utc).isoformat()
    return (f"<entry><title>{title}</title>"
            f"<link rel='alternate' href='{url}'/>"
            f"<published>{date}</published>"
            f"<content type='html'>{content}</content></entry>")


def atom(*entries):
    return ("<feed xmlns='http://www.w3.org/2005/Atom'>"
            + "".join(entries) + "</feed>")


def reddit_child(title, permalink, dt, *, stickied=False, score=0, comments=0):
    return {"data": {
        "title": title, "permalink": permalink,
        "created_utc": dt.timestamp(), "stickied": stickied,
        "score": score, "num_comments": comments,
    }}


class SentimentFactorTests(unittest.TestCase):
    def test_url_allowlist_is_reddit_only(self):
        # Reddit 主机（www / 裸域 / old）放行
        self.assertEqual(pipeline._public_url("/r/stocks/comments/abc/x/", "https://www.reddit.com/"),
                         "https://www.reddit.com/r/stocks/comments/abc/x/")
        self.assertEqual(pipeline._public_url("https://old.reddit.com/r/stocks/comments/1/y/", ""),
                         "https://old.reddit.com/r/stocks/comments/1/y/")
        # 非 Reddit 来源（原十站）现在一律拒绝，防止标题/链接注入
        for url in ("javascript:alert(1)", "http://www.reddit.com/r/stocks",
                    "https://reddit.evil.net/r/stocks", "https://finviz.com/map.ashx?t=sec",
                    "https://fred.stlouisfed.org/series/DFF", "//evil.net/path",
                    "https://www.reddit.com/<script>"):
            self.assertEqual(pipeline._public_url(url, "https://www.reddit.com/"), "", url)
        self.assertEqual(pipeline._public_text("<b>ETF</b> &amp; market\n news"), "ETF & market news")

    def test_single_source_registry_ten_boards_five_posts(self):
        self.assertEqual(pipeline.PUBLIC_SITE_NAMES, ("Reddit",))
        self.assertEqual(set(pipeline.PUBLIC_SITE_NAMES), set(pipeline.PUBLIC_SITE_DESCRIPTIONS))
        self.assertEqual(len(pipeline._REDDIT_BOARDS), 10)
        self.assertEqual(len(set(board[0] for board in pipeline._REDDIT_BOARDS)), 10)
        self.assertEqual(pipeline.REDDIT_POSTS_PER_BOARD, 5)
        # 用户点名的四个板块必须在列
        for named in ("stocks", "investing", "wallstreetbets", "ValueInvesting"):
            self.assertIn(named, [board[0] for board in pipeline._REDDIT_BOARDS])
        # 结果容器不再对总条数做「每站 3 条」截断
        items = [{"title": str(i), "url": "https://www.reddit.com/", "is_today": False}
                 for i in range(50)]
        self.assertEqual(len(pipeline._public_site_result("Reddit", items)["items"]), 50)

    def test_reddit_heat_extracted_from_feed_html(self):
        self.assertEqual(
            pipeline._reddit_heat_from_html(
                f'<div class="score">1,234 points</div><span>56 comments</span>'),
            " · 1,234 赞 · 56 评论")
        self.assertEqual(pipeline._reddit_heat_from_html("<p>no heat data here</p>"), "")
        self.assertEqual(pipeline._reddit_heat_from_html(None), "")

    def test_hot_feed_keeps_rank_order_not_time_and_caps_five_per_board(self):
        now = datetime(2026, 9, 27, 14, 0, tzinfo=pipeline.CST)
        base = "https://www.reddit.com/r/stocks/"
        no_zone = ("<entry><title>No zone</title>"  # 无时区的裸日期 → 剔除
                   "<link rel='alternate' href='" + base + "comments/5/e/'/>"
                   "<published>2026-09-27T14:00:00</published></entry>")
        feed = atom(
            atom_entry("Hottest but oldest", base + "comments/1/a/",
                       now - timedelta(hours=20), content=heat_html(512, 234)),
            atom_entry("Fresh", base + "comments/2/b/", now - timedelta(hours=1)),
            atom_entry("Fresh2", base + "comments/3/c/", now - timedelta(hours=2)),
            atom_entry("Stale", base + "comments/4/d/",
                       now - timedelta(hours=80)),  # 超 72h 窗口剔除
            no_zone,
            atom_entry("Dup", base + "comments/2/b/", now - timedelta(hours=3)),  # 重复链接剔除
            atom_entry("RankSix", base + "comments/6/f/", now - timedelta(hours=4)),
            atom_entry("RankSeven", base + "comments/7/g/", now - timedelta(hours=5)),
        )
        items, latest = pipeline._reddit_hot_items(
            feed, "stocks", "https://www.reddit.com/r/stocks/", now=now)
        # 保留 feed（热度榜）顺序而不是发布时间顺序，且超 72h / 无时区 / 重复链接剔除
        self.assertEqual([it["title"] for it in items],
                         ["Hottest but oldest", "Fresh", "Fresh2", "RankSix", "RankSeven"])
        self.assertEqual(len(items), 5)  # 每板块最多 5 条样本
        self.assertEqual(latest, now.strftime("%Y-%m-%d"))
        self.assertTrue(all(it["community"] == "r/stocks" for it in items))
        self.assertIn("512 赞", items[0]["detail"])
        self.assertIn("234 评论", items[0]["detail"])
        self.assertTrue(all("发布于" in it["detail"] for it in items))
        # 全部条目超窗时返回空
        old = atom(atom_entry("Old", "https://www.reddit.com/r/stocks/comments/9/h/",
                              now - timedelta(days=3, hours=1)))
        self.assertEqual(pipeline._reddit_hot_items(old, "stocks", "https://www.reddit.com/r/stocks/", now=now),
                         ([], None))

    def test_json_fallback_reads_score_comments_and_skips_bad_posts(self):
        now = datetime(2026, 9, 27, 14, 0, tzinfo=pipeline.CST)
        payload = {"data": {"children": [
            reddit_child("WSB hot 0", "/r/wallstreetbets/comments/a1/p1/",
                         now - timedelta(hours=1), stickied=False, score=100, comments=50),
            reddit_child("Pinned rules", "/r/wallstreetbets/comments/a2/p2/",
                         now - timedelta(hours=2), stickied=True, score=999, comments=10),
            reddit_child("WSB hot 1", "/r/wallstreetbets/comments/a3/p3/",
                         now - timedelta(hours=3), stickied=False, score=80, comments=40),
            reddit_child("WSB hot 2", "/r/wallstreetbets/comments/a4/p4/",
                         now - timedelta(hours=4), stickied=False, score=70),
            reddit_child("Injected", "https://evil.example/r/wallstreetbets/comments/x/",
                         now - timedelta(hours=5), score=60, comments=5),
            reddit_child("Too old", "/r/wallstreetbets/comments/a5/p5/",
                         now - timedelta(days=4), score=50, comments=5),
        ]}}
        items, latest = pipeline._reddit_json_items(payload, "wallstreetbets", now=now)
        self.assertEqual([it["title"] for it in items], ["WSB hot 0", "WSB hot 1", "WSB hot 2"])
        self.assertEqual(items[0]["url"], "https://www.reddit.com/r/wallstreetbets/comments/a1/p1/")
        self.assertIn("100 赞", items[0]["detail"])
        self.assertIn("50 评论", items[0]["detail"])
        self.assertIn("70 赞", items[2]["detail"])
        self.assertNotIn("评论", items[2]["detail"])  # 无评论数时不显示
        self.assertEqual(latest, now.strftime("%Y-%m-%d"))
        # 非 dict / 缺 children 的 payload 一律安全返回空
        self.assertEqual(pipeline._reddit_json_items(None, "stocks", now=now), ([], None))
        self.assertEqual(pipeline._reddit_json_items({"data": {}}, "stocks", now=now), ([], None))

    def test_fetch_reddit_parallel_boards_json_fallback_and_partial_403(self):
        now = datetime.now(pipeline.CST)
        stocks_feed = atom(*[
            atom_entry(f"Stocks hot {i}", f"https://www.reddit.com/r/stocks/comments/s{i}/t{i}/",
                       now - timedelta(hours=i + 1),
                       content=heat_html(512 - i, 234 - i) if i == 0 else "")
            for i in range(7)  # 7 条热帖 → 只保留前 5 条样本
        ])
        investing_feed = atom(*[
            atom_entry(f"Investing hot {i}", f"https://www.reddit.com/r/investing/comments/v{i}/t{i}/",
                       now - timedelta(hours=i + 1))
            for i in range(2)
        ])
        wsb_payload = {"data": {"children": [
            reddit_child(f"WSB hot {i}", f"/r/wallstreetbets/comments/w{i}/t{i}/",
                         now - timedelta(hours=i + 1), score=100 - i * 10, comments=50 - i * 5)
            for i in range(3)
        ]}}

        def fake_request(url, **kwargs):
            community = url.split("/r/")[1].split("/")[0]
            if url.endswith("hot/.rss?limit=10"):
                return {"stocks": stocks_feed, "investing": investing_feed}.get(community)
            if url.endswith("hot.json?limit=10"):
                return {"wallstreetbets": wsb_payload}.get(community)
            return None  # 其余板块 RSS / JSON 全部 403

        with patch.object(pipeline, "safe_request", side_effect=fake_request) as req:
            result = pipeline.fetch_reddit()
        # 板块顺序展示：r/stocks 5 条 → r/investing 2 条 → r/wallstreetbets 3 条
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["is_today"])
        self.assertEqual([it["community"] for it in result["items"]],
                         ["r/stocks"] * 5 + ["r/investing"] * 2 + ["r/wallstreetbets"] * 3)
        self.assertEqual(len(result["items"]), 10)
        self.assertEqual(result["content_date"], now.strftime("%Y-%m-%d"))
        self.assertEqual(result["items"][0]["title"], "Stocks hot 0")
        self.assertIn("512 赞", result["items"][0]["detail"])
        self.assertIn("100 赞", result["items"][7]["detail"])  # JSON 兜底的热度
        # 10 次 RSS + 8 次 JSON 兜底（stocks/investing 的 RSS 成功，不再试 JSON）
        self.assertEqual(req.call_count, 18)
        # 暂缺板块如实点名
        for missing in ("r/ValueInvesting", "r/economics", "r/wallstreet", "r/options",
                        "r/Forex", "r/pennystocks", "r/personalfinance"):
            self.assertIn(missing, result["note"])
        self.assertIn("热度不等于事实", result["note"])
        with patch.object(pipeline, "safe_request", return_value=None):
            failed = pipeline.fetch_reddit()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["items"], [])
        for board in ("r/stocks", "r/personalfinance"):
            self.assertIn(board, failed["note"])

    def test_public_sites_single_source_isolation(self):
        with patch.object(pipeline, "fetch_reddit", side_effect=ValueError("broken feed")):
            results = pipeline.fetch_public_sites()
        self.assertEqual(tuple(results), ("Reddit",))
        self.assertEqual(results["Reddit"]["status"], "unavailable")

    def test_collect_all_data_has_base_sources_plus_reddit(self):
        legacy = ("fetch_market_snapshot", "fetch_market_panorama", "fetch_gov_policy",
                  "fetch_hk_channels", "fetch_google_news", "fetch_sina_headlines",
                  "fetch_eastmoney_news", "fetch_hot_stocks", "fetch_hk_quant",
                  "fetch_econ_calendar")
        reddit = pipeline._public_site_result(
            "Reddit", [{"title": "Sample", "url": "https://www.reddit.com/r/stocks/comments/1/x/",
                        "is_today": True}])
        with patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
            mocks = [patch.object(pipeline, fn, return_value={"status": "unavailable"})
                     for fn in legacy]
            for p in mocks:
                p.start()
            try:
                with patch.object(pipeline, "fetch_public_sites", return_value={"Reddit": reddit}):
                    data = pipeline.collect_all_data()
            finally:
                for p in reversed(mocks):
                    p.stop()
        # 10 个基础数据源（含港股量化引擎与未来30天财经日历）+ Reddit 趋势跟踪线索
        self.assertEqual(sorted(data), sorted((
            "实时行情", "A股大盘全景", "国家政策", "港股名家频道", "全球头条",
            "A股资讯", "东财快讯", "热门榜单", "港股量化", "财经日历", "Reddit")))
        self.assertEqual(data["Reddit"]["status"], "success")

    def _reddit_data(self):
        items = []
        for i in range(7):  # 超 5 条 → 渲染端只保留板块前 5 条
            items.append({
                "title": f"Stocks hot {i}",
                "url": f"https://www.reddit.com/r/stocks/comments/s{i}/t{i}/",
                "detail": f"发布于 2026-09-27 10:0{i}（北京时间） · 100 赞 · 10 评论",
                "published_cst": f"2026-09-27 10:0{i}", "community": "r/stocks",
                "is_today": True})
        for i in range(3):
            items.append({
                "title": f"WSB hot {i}",
                "url": f"https://www.reddit.com/r/wallstreetbets/comments/w{i}/t{i}/",
                "detail": f"发布于 2026-09-27 09:0{i}（北京时间） · 90 赞",
                "published_cst": f"2026-09-27 09:0{i}", "community": "r/wallstreetbets",
                "is_today": True})
        items.append({"title": "Unsafe", "url": "javascript:alert(1)",
                      "detail": "bad", "published_cst": "2026-09-27 09:00",
                      "community": "r/stocks", "is_today": True})
        return {"Reddit": pipeline._public_site_result("Reddit", items, latest="2026-09-27"),
                "实时行情": pipeline._source_result("sample quote", "success", quotes={
                    "标普500": {"price": 6123.45, "change_pct": 1.25}})}

    def test_sentiment_section_renders_boards_capped_in_both_themes(self):
        data = self._reddit_data()
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for theme in ("guizang", "pixel"):
                with self.subTest(theme=theme):
                    report = pipeline.generate_report(data, "2026年9月27日 · 周日", "20260927", theme=theme)
                    self.assertIn("每日量化策略趋势跟踪线索", report)
                    self.assertNotIn("每日量化情绪因子", report)  # 旧栏目名不得回潮
                    self.assertNotIn("每日量化策略投研", report)
                    # 板块子标题（有数据的板块）
                    self.assertIn("r/stocks", report)
                    self.assertIn("个股讨论", report)
                    self.assertIn("r/wallstreetbets", report)
                    self.assertIn("散户投机风向", report)
                    # 无数据的板块不进正文
                    self.assertNotIn("r/ValueInvesting", report)
                    # 每板块最多 5 条样本：第 6 / 7 条被裁剪
                    self.assertIn("Stocks hot 4", report)
                    self.assertNotIn("Stocks hot 5", report)
                    self.assertNotIn("Stocks hot 6", report)
                    # 链接与热度保留
                    self.assertIn("https://www.reddit.com/r/stocks/comments/s0/t0/", report)
                    self.assertIn("100 赞", report)
                    # 非法 URL 条目整体剔除，不注入
                    self.assertNotIn('href="javascript:', report)
                    self.assertNotIn("Unsafe", report)
                    # 审计口径：9 个基础数据源（含港股量化引擎）+ Reddit
                    self.assertEqual(pipeline._report_meta(report)["total_sources"], 10)
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)
        self.assertIn("当天", reason)

    def test_section_position_and_gate_in_both_themes(self):
        data = self._reddit_data()
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
                titles = [s[1] for s in pipeline._collect_report_parts(data, kit)["sections"]]
                # 结论先行 → 行情数据 → 趋势跟踪线索 → 资讯 → 盘点收尾
                self.assertLess(titles.index("行情速览"), titles.index("每日量化策略趋势跟踪线索"))
                self.assertEqual(titles[-1], "盘点总结")

    def test_section_absent_and_failures_named_when_reddit_down(self):
        failed = {"Reddit": pipeline._public_site_result("Reddit", [], error="HTTP 403")}
        for theme in ("guizang", "pixel"):
            report = pipeline.generate_report(failed, "2026年9月27日 · 周日", "20260927", theme=theme)
            self.assertNotIn("每日量化策略趋势跟踪线索", report)  # 整栏缺席，失败仅在盘点总结里点名
            self.assertIn("暂缺：", report)
            self.assertIn("Reddit", report)
            self.assertNotIn("HTTP 403", report)
            # 9 个基础数据源 + Reddit（未采集财经日历时不进审计）
            self.assertEqual(pipeline._report_meta(report)["total_sources"], 10)
        self.assertFalse(pipeline.check_push_eligibility(failed)[0])


if __name__ == "__main__":
    unittest.main()
