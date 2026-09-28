"""每日量化策略趋势跟踪线索（Reddit 板块热帖 + 全网 20 个新闻源头·港股挖掘）的离线解析、
降级、主题渲染及推送门禁测试（不访问网站/不写历史报告）。"""
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
                  "fetch_weekly_forecast", "fetch_sector_rotation", "fetch_econ_calendar")
        reddit = pipeline._public_site_result(
            "Reddit", [{"title": "Sample", "url": "https://www.reddit.com/r/stocks/comments/1/x/",
                        "is_today": True}])
        news = pipeline._source_result(pipeline.HK_NEWS_SOURCE_NAME, "unavailable",
                                       sources=[], analysis=None, error="offline")
        with patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
            mocks = [patch.object(pipeline, fn, return_value={"status": "unavailable"})
                     for fn in legacy]
            for p in mocks:
                p.start()
            try:
                with patch.object(pipeline, "fetch_public_sites", return_value={"Reddit": reddit}):
                    with patch.object(pipeline, "fetch_hk_news_sources", return_value=news):
                        data = pipeline.collect_all_data()
            finally:
                for p in reversed(mocks):
                    p.stop()
        # 12 个基础数据源（含行业轮动、港股量化引擎、每周走势预测与未来30天财经日历）+ Reddit + 全网新闻源头
        self.assertEqual(sorted(data), sorted((
            "实时行情", "A股大盘全景", "国家政策", "港股名家频道", "全球头条",
            "A股资讯", "东财快讯", "热门榜单", "港股量化", "每周走势预测",
            "财经日历", "行业轮动", "Reddit", pipeline.HK_NEWS_SOURCE_NAME)))
        self.assertEqual(data["Reddit"]["status"], "success")
        self.assertEqual(data[pipeline.HK_NEWS_SOURCE_NAME]["status"], "unavailable")

    def test_collect_all_data_skips_news_sources_when_disabled(self):
        legacy = ("fetch_market_snapshot", "fetch_market_panorama", "fetch_gov_policy",
                  "fetch_hk_channels", "fetch_google_news", "fetch_sina_headlines",
                  "fetch_eastmoney_news", "fetch_hot_stocks", "fetch_hk_quant",
                  "fetch_weekly_forecast", "fetch_sector_rotation", "fetch_econ_calendar")
        with patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
            mocks = [patch.object(pipeline, fn, return_value={"status": "unavailable"})
                     for fn in legacy]
            for p in mocks:
                p.start()
            try:
                with patch.object(pipeline, "fetch_public_sites", return_value={}):
                    with patch.object(pipeline, "fetch_hk_news_sources",
                                      side_effect=AssertionError("开关关闭时不得调用")):
                        with patch.object(pipeline, "HK_NEWS_ENABLED", False):
                            data = pipeline.collect_all_data()
            finally:
                for p in reversed(mocks):
                    p.stop()
        self.assertNotIn(pipeline.HK_NEWS_SOURCE_NAME, data)

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


def _rss_feed(items):
    """构造 RSS 2.0 文档；items 为 (title, link, pubDate) 元组列表。"""
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><pubDate>{p}</pubDate></item>"
        for t, u, p in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'


class HKNewsSourceTests(unittest.TestCase):
    """全网 20 个新闻源头：注册表 / 白名单 / 港股挖掘 / 规则分析 / 栏目渲染（离线 mock）。"""

    @staticmethod
    def _rfc(dt):
        # 固定英文星期/月份，避免本地化差异（parsedate 按英文解析）
        return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    def _fetch_result(self, feeds):
        def fake_request(url, **kwargs):
            return feeds.get(url)
        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            return pipeline.fetch_hk_news_sources()

    def _sample_feeds(self):
        now = datetime.now(pipeline.CST)
        fresh = now - timedelta(hours=2)
        stale = now - timedelta(hours=96)
        srcs = pipeline.HK_NEWS_SOURCES
        # 源0（RTHK）：5 条窗口内（4 港股相关 + 1 无关）+ 1 过期 + 1 无时区
        feeds = {
            srcs[0]["feed"]: _rss_feed([
                ("港股反弹，恒指收复25000点",
                 "https://news.rthk.hk/rthk/news/1/a.html", self._rfc(fresh)),
                ("南向资金净买入超百亿港元",
                 "https://news.rthk.hk/rthk/news/1/b.html", self._rfc(fresh)),
                ("香港金管局维持基本利率不变",
                 "https://news.rthk.hk/rthk/news/1/c.html", self._rfc(fresh)),
                ("港股跳水，恒指跌破25000点",
                 "https://news.rthk.hk/rthk/news/1/d.html", self._rfc(fresh)),
                ("Wall Street slips as yields rise",
                 "https://news.rthk.hk/rthk/news/1/e.html", self._rfc(fresh)),
                ("恒指昨日收跌", "https://news.rthk.hk/rthk/news/1/f.html", self._rfc(stale)),
                ("港股开盘", "https://news.rthk.hk/rthk/news/1/g.html",
                 "Mon, 28 Sep 2026 01:00:00"),
            ]),
            # 源1（HKET）：2 条当天港股相关
            srcs[1]["feed"]: _rss_feed([
                ("港股通ETF获大额净买入，恒指升1%",
                 "https://www.hket.com/article/1/a.html", self._rfc(fresh)),
                ("香港零售销售回暖带动本地消费股",
                 "https://www.hket.com/article/1/b.html", self._rfc(fresh)),
            ]),
            # 源2（SCMP）：窗口内 1 条但与港股无关 → status ok、无港股命中
            srcs[2]["feed"]: _rss_feed([
                ("UK inflation cools, pound steadies",
                 "https://www.scmp.com/article/1/x", self._rfc(fresh)),
            ]),
            # 源3（HKEX）：链接落在白名单外 → 条目剔除，不计入
            srcs[3]["feed"]: _rss_feed([
                ("港股交易安排调整", "https://evil.example.com/x", self._rfc(fresh)),
            ]),
        }
        return feeds

    def test_registry_twenty_sources_https_hosts_and_regions(self):
        self.assertEqual(len(pipeline.HK_NEWS_SOURCES), 20)
        self.assertEqual(pipeline.HK_NEWS_TOTAL, 20)
        names = [s["name"] for s in pipeline.HK_NEWS_SOURCES]
        self.assertEqual(len(set(names)), 20)
        from collections import Counter
        self.assertEqual(Counter(s["region"] for s in pipeline.HK_NEWS_SOURCES),
                         {"香港": 7, "内地": 7, "国际": 6})
        for s in pipeline.HK_NEWS_SOURCES:
            self.assertTrue(s["feed"].startswith("https://"), s["name"])
            self.assertTrue(s["url"].startswith("https://"), s["name"])
            self.assertTrue(s["hosts"], s["name"])
            self.assertTrue(s["desc"], s["name"])

    def test_news_url_whitelist_is_per_source_host(self):
        self.assertEqual(pipeline._news_url("https://www.hket.com/rss/finance",
                                            ("www.hket.com",)),
                         "https://www.hket.com/rss/finance")
        for bad in ("http://www.hket.com/x", "https://evil.com/x",
                    "https://www.hket.com@evil.com/x", "javascript:alert(1)",
                    "https://www.hket.com/<script>", "//evil.net/path"):
            self.assertEqual(pipeline._news_url(bad, ("www.hket.com",)), "", bad)

    def test_hk_relevance_keywords(self):
        for hit in ("恒指收跌1%", "港股通资金流入", "Hang Seng closes higher",
                    "Hong Kong stocks rally", "港府公布财政预算", "Southbound flow grows"):
            self.assertRegex(hit, pipeline._HK_NEWS_KW_RE)
        for miss in ("Wall Street closes higher", "A股沪指窄幅震荡",
                     "Fed keeps rates unchanged", "Macau gaming revenue rises"):
            self.assertNotRegex(miss, pipeline._HK_NEWS_KW_RE)

    def test_fetch_filters_window_relevance_and_caps(self):
        result = self._fetch_result(self._sample_feeds())
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["is_today"])
        records = {r["name"]: r for r in result["sources"]}
        self.assertEqual(len(result["sources"]), 20)

        r0 = records[pipeline.HK_NEWS_SOURCES[0]["name"]]
        self.assertEqual(r0["status"], "ok")
        self.assertEqual(r0["scanned"], 5)          # 过期 + 无时区两条被剔除
        self.assertEqual(r0["hk_n"], 4)             # 挖掘口径 = 全部港股相关
        self.assertEqual(len(r0["items"]), 3)       # 展示口径 = 每源上限 3 条
        self.assertEqual(r0["hk_n"] - len(r0["items"]), 1)
        self.assertEqual(r0["today"], 5)
        self.assertIn("港股反弹，恒指收复25000点", [it["title"] for it in r0["items"]])
        self.assertNotIn("Wall Street slips as yields rise",
                         [it["title"] for it in r0["items"]])
        self.assertTrue(all(it["published_cst"] for it in r0["items"]))

        r2 = records[pipeline.HK_NEWS_SOURCES[2]["name"]]
        self.assertEqual(r2["status"], "ok")        # 抓得到但无港股命中
        self.assertEqual(r2["hk_n"], 0)
        self.assertEqual(r2["items"], [])

        r3 = records[pipeline.HK_NEWS_SOURCES[3]["name"]]
        self.assertEqual(r3["status"], "empty")     # 白名单外链接被剔除 → 无有效内容
        self.assertEqual(r3["hk_n"], 0)

        failed = [r for r in result["sources"] if r["status"] == "fail"]
        self.assertEqual(len(failed), 16)           # 其余 16 源未配置 feed 返回
        self.assertIn("暂缺", result["note"])
        self.assertIn(pipeline.HK_NEWS_SOURCES[5]["name"], result["note"])
        self.assertTrue(result["partial"])

        an = result["analysis"]
        self.assertEqual(an["ok_n"], 3)
        self.assertEqual(an["fail_n"], 16)
        self.assertEqual(an["scanned"], 8)
        self.assertEqual(an["hk_n"], 6)             # 4 + 2
        self.assertEqual(an["total"], 20)
        self.assertGreaterEqual(an["bull"], 2)      # 反弹/升 → 多头证据
        self.assertGreaterEqual(an["bear"], 1)      # 跳水 → 空头证据
        self.assertEqual(an["prob"] + (100 - an["prob"]), 100)
        self.assertTrue(5 <= an["prob"] <= 95)
        self.assertIn("南向资金", an["themes"])

    def test_fetch_all_failed_is_unavailable_without_history_fallback(self):
        result = self._fetch_result({})
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["items"] if "items" in result else [], [])
        self.assertFalse(result["is_today"])
        self.assertIn("72", result["error"])
        self.assertEqual(len(result["sources"]), 20)

    def test_disabled_switch_returns_unavailable(self):
        with patch.object(pipeline, "HK_NEWS_ENABLED", False):
            with patch.object(pipeline, "safe_request",
                              side_effect=AssertionError("关闭时不得请求网络")):
                result = pipeline.fetch_hk_news_sources()
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("OCTOPUS_HK_NEWS=0", result["error"])

    def test_analysis_note_prefers_news_and_merges_reddit(self):
        news = self._fetch_result(self._sample_feeds())
        reddit = pipeline._public_site_result("Reddit", [
            {"title": "$TSLA rally to the moon", "url": "https://www.reddit.com/r/stocks/comments/1/a/",
             "detail": "发布于 2026-09-28 10:00（北京时间）", "published_cst": "2026-09-28 10:00",
             "community": "r/stocks", "is_today": True}])
        notes = pipeline.build_section_ai_notes({pipeline.HK_NEWS_SOURCE_NAME: news, "Reddit": reddit})
        n = notes["TREND CLUES"]
        self.assertIn("20 源扫描", n["text"])
        self.assertIn("港股相关", n["text"])
        self.assertIn("Reddit 热帖 1 条", n["text"])
        self.assertIn("→ 预测：", n["text"])
        self.assertIn("非投资建议", n["text"])
        self.assertEqual(n["bull_pct"] + n["bear_pct"], 100)
        self.assertTrue(5 <= n["bull_pct"] <= 95)

    def test_news_only_data_still_renders_section_and_unlocks_gate(self):
        news = self._fetch_result(self._sample_feeds())
        data = {pipeline.HK_NEWS_SOURCE_NAME: news}
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for theme in ("guizang", "pixel"):
                with self.subTest(theme=theme):
                    report = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928",
                                                      theme=theme)
                    self.assertIn("每日量化策略趋势跟踪线索", report)
                    self.assertIn("全网新闻源头 ×20", report)
                    self.assertIn("港股相关 6 条", report)      # 汇总行 4+2
                    self.assertIn("港股反弹，恒指收复25000点", report)
                    self.assertIn("香港经济日报 HKET·财经", report)
                    self.assertNotIn("Wall Street slips as yields rise", report)
                    # 9 个基础数据源 + 全网新闻源头（无 Reddit 键）
                    self.assertEqual(pipeline._report_meta(report)["total_sources"], 10)
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)
        self.assertIn("当天", reason)

    def test_news_and_reddit_render_together_with_audit_count(self):
        news = self._fetch_result(self._sample_feeds())
        reddit = pipeline._public_site_result("Reddit", [
            {"title": "Stocks hot 0", "url": "https://www.reddit.com/r/stocks/comments/s0/t0/",
             "detail": "发布于 2026-09-28 10:00（北京时间） · 100 赞",
             "published_cst": "2026-09-28 10:00", "community": "r/stocks", "is_today": True}])
        data = {pipeline.HK_NEWS_SOURCE_NAME: news, "Reddit": reddit}
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            report = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928")
        self.assertIn("全网新闻源头 ×20", report)
        self.assertIn("Reddit", report)
        self.assertIn("r/stocks", report)
        # 9 个基础数据源 + 全网新闻源头 + Reddit
        self.assertEqual(pipeline._report_meta(report)["total_sources"], 11)
        # 审计行标签
        parts = pipeline._collect_report_parts(data, pipeline.GUIZANG_KIT)
        self.assertEqual(parts["total"], 11)

    def test_unsafe_item_url_never_rendered(self):
        news = self._fetch_result(self._sample_feeds())
        # 手工注入一条白名单外链接（模拟被篡改的数据）
        news["sources"][0]["items"].append({
            "title": "注入测试", "url": "https://evil.example.com/payload",
            "published_cst": "2026-09-28 10:00", "is_today": True,
            "detail": "发布于 2026-09-28 10:00（北京时间）"})
        data = {pipeline.HK_NEWS_SOURCE_NAME: news}
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            report = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928")
        self.assertNotIn("evil.example.com", report)
        self.assertNotIn("注入测试", report)


if __name__ == "__main__":
    unittest.main()
