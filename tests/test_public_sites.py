"""趋势跟踪（多平台信息员）的离线解析、降级、主题渲染及推送门禁测试。

覆盖四个公开平台：Reddit（板块热门帖）、StockTwits（趋势榜 + 平台情绪标签）、
TradingView（Ideas RSS）、Bogleheads（论坛 RSS）；全部请求均 mock，不访问网站。"""
import importlib.util
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
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


def rss_item(title, link, dt, description=""):
    return (f"<item><title>{title}</title><link>{link}</link>"
            f"<pubDate>{format_datetime(dt)}</pubDate>"
            f"<description>{description}</description></item>")


def rss(*items):
    return ("<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'>"
            "<channel><title>feed</title>" + "".join(items) + "</channel></rss>")


def reddit_child(title, permalink, dt, *, stickied=False, score=0, comments=0):
    return {"data": {
        "title": title, "permalink": permalink,
        "created_utc": dt.timestamp(), "stickied": stickied,
        "score": score, "num_comments": comments,
    }}


class SentimentFactorTests(unittest.TestCase):
    def test_url_allowlist_covers_only_trend_platforms(self):
        # 四个平台主机（含 www / 裸域）放行
        self.assertEqual(pipeline._public_url("/r/stocks/comments/abc/x/", "https://www.reddit.com/"),
                         "https://www.reddit.com/r/stocks/comments/abc/x/")
        self.assertEqual(pipeline._public_url("https://old.reddit.com/r/stocks/comments/1/y/", ""),
                         "https://old.reddit.com/r/stocks/comments/1/y/")
        self.assertEqual(pipeline._public_url("/symbol/MU", "https://stocktwits.com/"),
                         "https://stocktwits.com/symbol/MU")
        self.assertEqual(
            pipeline._public_url("https://www.tradingview.com/chart/NQ1!/abc/", ""),
            "https://www.tradingview.com/chart/NQ1!/abc/")
        self.assertEqual(
            pipeline._public_url("https://www.bogleheads.org/forum/viewtopic.php?p=1#p1", ""),
            "https://www.bogleheads.org/forum/viewtopic.php?p=1#p1")
        # 平台之外的来源一律拒绝，防止标题/链接注入
        for url in ("javascript:alert(1)", "http://www.reddit.com/r/stocks",
                    "https://reddit.evil.net/r/stocks", "https://finviz.com/map.ashx?t=sec",
                    "https://fred.stlouisfed.org/series/DFF", "//evil.net/path",
                    "https://www.reddit.com/<script>", "https://stocktwits.evil.net/symbol/MU",
                    "https://xueqiu.com/statuses/hot/listV2.json"):
            self.assertEqual(pipeline._public_url(url, "https://www.reddit.com/"), "", url)
        self.assertEqual(pipeline._public_text("<b>ETF</b> &amp; market\n news"), "ETF & market news")

    def test_multi_platform_registry_ten_boards_five_posts(self):
        self.assertEqual(pipeline.PUBLIC_SITE_NAMES,
                         ("Reddit", "StockTwits", "TradingView", "Bogleheads"))
        self.assertEqual(set(pipeline.PUBLIC_SITE_NAMES), set(pipeline.PUBLIC_SITE_DESCRIPTIONS))
        self.assertEqual(set(pipeline.PUBLIC_SITE_NAMES), set(pipeline.PUBLIC_SITE_URLS))
        self.assertEqual(pipeline._active_public_site_names(), pipeline.PUBLIC_SITE_NAMES)
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

    def test_public_sites_multi_platform_isolation(self):
        """单个平台失败只影响该平台；其余平台照常返回，顺序与注册表一致。"""
        stocktwits = pipeline._public_site_result(
            "StockTwits", [{"title": "MU · Micron", "url": "https://stocktwits.com/symbol/MU",
                            "is_today": True}])
        with patch.object(pipeline, "fetch_reddit", side_effect=ValueError("broken feed")), \
             patch.object(pipeline, "fetch_stocktwits", return_value=stocktwits), \
             patch.object(pipeline, "fetch_tradingview", side_effect=ValueError("blocked")), \
             patch.object(pipeline, "fetch_bogleheads",
                          return_value=pipeline._public_site_result("Bogleheads", [])):
            results = pipeline.fetch_public_sites()
        self.assertEqual(tuple(results), pipeline.PUBLIC_SITE_NAMES)
        self.assertEqual(results["Reddit"]["status"], "unavailable")
        self.assertEqual(results["StockTwits"]["status"], "success")
        self.assertEqual(results["TradingView"]["status"], "unavailable")
        self.assertEqual(results["Bogleheads"]["status"], "unavailable")
        # 禁用开关：OCTOPUS_TREND_PLATFORMS 过滤后为空则回落全部平台
        with patch.dict("os.environ", {"OCTOPUS_TREND_PLATFORMS": "reddit, bogleheads"}):
            self.assertEqual(pipeline._active_public_site_names(), ("Reddit", "Bogleheads"))
        with patch.dict("os.environ", {"OCTOPUS_TREND_PLATFORMS": "unknown"}):
            self.assertEqual(pipeline._active_public_site_names(), pipeline.PUBLIC_SITE_NAMES)

    def test_collect_all_data_has_base_sources_plus_trend_platforms(self):
        legacy = ("fetch_market_snapshot", "fetch_market_panorama", "fetch_gov_policy",
                  "fetch_hk_channels", "fetch_google_news", "fetch_fed_trend",
                  "fetch_geo_trend", "fetch_eastmoney_news", "fetch_hot_stocks",
                  "fetch_hk_quant", "fetch_econ_calendar")
        platforms = {
            "Reddit": pipeline._public_site_result(
                "Reddit", [{"title": "Sample", "url": "https://www.reddit.com/r/stocks/comments/1/x/",
                            "is_today": True}]),
            "StockTwits": pipeline._public_site_result(
                "StockTwits", [{"title": "MU · Micron", "url": "https://stocktwits.com/symbol/MU",
                                "is_today": True}]),
            "TradingView": pipeline._public_site_result(
                "TradingView", [{"title": "Nasdaq 100 (NQ)", "url": "https://www.tradingview.com/chart/NQ1!/x/",
                                 "is_today": True}]),
            "Bogleheads": pipeline._public_site_result(
                "Bogleheads", [{"title": "Why Bonds EVER", "url": "https://www.bogleheads.org/forum/viewtopic.php?p=1#p1",
                                "is_today": True}]),
        }
        with patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
            mocks = [patch.object(pipeline, fn, return_value={"status": "unavailable"})
                     for fn in legacy]
            for p in mocks:
                p.start()
            try:
                with patch.object(pipeline, "fetch_public_sites", return_value=platforms):
                    data = pipeline.collect_all_data()
            finally:
                for p in reversed(mocks):
                    p.stop()
        # 9 个基础数据源（含港股量化引擎与未来30天财经日历；A股资讯已移除）
        # + 2 个 AI趋势分析专题源（美联储 / 地缘政治）+ 4 个趋势平台
        self.assertEqual(sorted(data), sorted((
            "实时行情", "A股大盘全景", "国家政策", "港股名家频道", "全球头条",
            "美联储趋势", "地缘政治趋势",
            "东财快讯", "热门榜单", "港股量化", "财经日历",
            "Reddit", "StockTwits", "TradingView", "Bogleheads")))
        self.assertEqual(data["Reddit"]["status"], "success")
        self.assertEqual(data["StockTwits"]["status"], "success")

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
                    title_pin = "TREND TRACKING" if theme == "pixel" else "趋势跟踪</h2>"
                    self.assertIn(title_pin, report)  # 真实栏目标题，不是页面标题
                    self.assertNotIn("每日量化策略趋势跟踪线索", report)  # 旧栏目名不得回潮
                    self.assertNotIn("每日量化情绪因子", report)
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
                    # 审计口径：8 个基础数据源（含港股量化引擎）+ Reddit 趋势线索
                    self.assertEqual(pipeline._report_meta(report)["total_sources"], 9)
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)
        self.assertIn("当天", reason)

    def test_section_position_and_gate_in_both_themes(self):
        data = self._reddit_data()
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
                titles = [s[1] for s in pipeline._collect_report_parts(data, kit)["sections"]]
                # 结论先行（今日预判）→ 行情数据 → 趋势跟踪 → 资讯 → 总结收尾
                self.assertLess(titles.index("行情速览"), titles.index("趋势跟踪"))
                self.assertLess(titles.index("今日预判"), titles.index("行情速览"))
                self.assertNotIn("每日量化策略趋势跟踪线索", titles)  # 旧栏目名不得回潮
                self.assertEqual(titles[-1], "总结")

    def test_section_absent_and_failures_named_when_reddit_down(self):
        failed = {"Reddit": pipeline._public_site_result("Reddit", [], error="HTTP 403")}
        for theme in ("guizang", "pixel"):
            report = pipeline.generate_report(failed, "2026年9月27日 · 周日", "20260927", theme=theme)
            self.assertNotIn("趋势跟踪</h2>", report)      # 整栏缺席（guizang 标题）
            self.assertNotIn("TREND TRACKING", report)      # 像素关卡名同样不出现
            self.assertNotIn("每日量化策略趋势跟踪线索", report)  # 旧栏目名不得回潮
            self.assertIn("暂缺：", report)
            self.assertIn("Reddit", report)
            self.assertNotIn("HTTP 403", report)
            # 8 个基础数据源 + Reddit（未采集财经日历时不进审计）
            self.assertEqual(pipeline._report_meta(report)["total_sources"], 9)
        self.assertFalse(pipeline.check_push_eligibility(failed)[0])


    # ------------------------------------------------------------------
    # 2026-09-28 多平台信息员：新增平台的离线解析与降级
    # ------------------------------------------------------------------
    def test_stocktwits_trending_ranks_platform_summary_and_sentiment_labels(self):
        now = datetime.now(pipeline.CST)
        summary_at = (now - timedelta(minutes=30)).astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")

        def fake_request(url, **kwargs):
            if url.endswith("trending/symbols.json"):
                return {"symbols": [
                    {"symbol": "MU", "title": "Micron Technology Inc", "rank": 2,
                     "watchlist_count": 217113,
                     "trends": {"summary": "Bulls expect a beat while bears warn on margins.",
                                "summary_at": summary_at}},
                    {"symbol": "BTC.X", "title": "Bitcoin", "rank": 1,
                     "watchlist_count": 681982,
                     "trends": {"summary": "Bullish posts point to ETF demand.",
                                "summary_at": summary_at}},
                    {"symbol": "BAD SYMBOL", "title": "Injected", "rank": 3,
                     "watchlist_count": 1, "trends": {"summary_at": summary_at}},
                ]}
            if "/streams/symbol/" in url:
                return {"messages": [
                    {"entities": {"sentiment": {"basic": "Bullish"}}},
                    {"entities": {"sentiment": {"basic": "Bullish"}}},
                    {"entities": {"sentiment": {"basic": "Bearish"}}},
                    {"entities": {"sentiment": None}},
                    {"entities": {}},
                    "not-a-dict",
                ]}
            return None

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_stocktwits()
        self.assertEqual(result["source"], "StockTwits")
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["is_today"])
        # 按平台 rank 排序（不是请求返回顺序），非法 symbol 构造出的 URL 被 allowlist 拒绝
        self.assertEqual([it["symbol"] for it in result["items"]], ["BTC.X", "MU"])
        self.assertEqual(result["items"][0]["community"], "平台趋势榜")
        detail = result["items"][1]["detail"]
        self.assertIn("平台趋势榜 #2", detail)
        self.assertIn("关注 217,113 人", detail)
        self.assertIn("平台多空摘要", detail)
        self.assertIn("近 5 条消息平台标签：看多 2 / 看空 1", detail)
        self.assertIn("不复制消息正文", result["note"])
        # 接口不可用 → 整平台暂缺，不伪造
        with patch.object(pipeline, "safe_request", return_value=None):
            failed = pipeline.fetch_stocktwits()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["items"], [])

    def test_tradingview_rss_drops_foreign_hosts_and_stale_items(self):
        now = datetime.now(pipeline.CST)
        feed = rss(
            rss_item("Nasdaq 100 (NQ) Analysis, Key-Zones, Setup for Mon",
                     "https://www.tradingview.com/chart/NQ1!/abc/",
                     now - timedelta(hours=1)),
            rss_item("Foreign host idea", "https://evil.example/chart/NQ1!/abc/",
                     now - timedelta(hours=2)),
            rss_item("Stale idea", "https://www.tradingview.com/chart/NQ1!/old/",
                     now - timedelta(hours=100)),
        )
        with patch.object(pipeline, "safe_request", return_value=feed):
            result = pipeline.fetch_tradingview()
        self.assertEqual(result["source"], "TradingView")
        self.assertEqual([it["title"] for it in result["items"]],
                         ["Nasdaq 100 (NQ) Analysis, Key-Zones, Setup for Mon"])
        self.assertEqual(result["items"][0]["community"], "交易员观点")
        self.assertTrue(result["items"][0]["is_today"])
        self.assertIn("非投资建议", result["note"])
        with patch.object(pipeline, "safe_request", return_value=None):
            self.assertEqual(pipeline.fetch_tradingview()["status"], "unavailable")

    def test_bogleheads_rss_splits_board_and_topic(self):
        now = datetime.now(pipeline.CST)
        feed = rss(
            rss_item("Investing - Theory, News &amp; General • Re: Why Bonds EVER when you have TIPS?",
                     "https://www.bogleheads.org/forum/viewtopic.php?p=8865896#p8865896",
                     now - timedelta(hours=2)),
            rss_item("Personal Consumer Issues • Auto Maintenance",
                     "https://www.bogleheads.org/forum/viewtopic.php?p=8865892#p8865892",
                     now - timedelta(hours=3)),
        )
        with patch.object(pipeline, "safe_request", return_value=feed):
            result = pipeline.fetch_bogleheads()
        self.assertEqual(result["source"], "Bogleheads")
        titles = [it["title"] for it in result["items"]]
        groups = [it["community"] for it in result["items"]]
        self.assertEqual(titles, ["Why Bonds EVER when you have TIPS?", "Auto Maintenance"])
        self.assertEqual(groups, ["投资理论 · 新闻 · 综合", "个人消费"])
        self.assertTrue(all(it["is_today"] for it in result["items"]))
        with patch.object(pipeline, "safe_request", return_value=None):
            self.assertEqual(pipeline.fetch_bogleheads()["status"], "unavailable")

    def _platform_item(self, platform, title, url, community, *, today=True):
        return {"title": title, "url": url, "detail": "发布于 2026-09-28 09:00（北京时间）",
                "community": community, "platform": platform, "published_cst": "2026-09-28 09:00",
                "is_today": today}

    def test_trend_section_renders_without_reddit_and_names_missing_platform(self):
        """旧版整栏依赖 Reddit；新版任一平台有样本即渲染，缺失平台在数据覆盖里点名。"""
        data = {
            "实时行情": pipeline._source_result("q", "success", is_today=True,
                                               content_date="2026-09-28",
                                               quotes={"标普500": {"price": 6123.45,
                                                                   "change_pct": 1.25}}),
            "Reddit": pipeline._public_site_result("Reddit", [], error="HTTP 403"),
            "StockTwits": pipeline._public_site_result("StockTwits", [
                self._platform_item("StockTwits", "MU · Micron Technology Inc",
                                    "https://stocktwits.com/symbol/MU", "平台趋势榜")]),
            "TradingView": pipeline._public_site_result("TradingView", [
                self._platform_item("TradingView", "Nasdaq 100 (NQ) Analysis",
                                    "https://www.tradingview.com/chart/NQ1!/abc/", "交易员观点")]),
            "Bogleheads": pipeline._public_site_result("Bogleheads", [], error="offline"),
        }
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                report = pipeline.generate_report(data, "2026年9月28日 · 周一", "20260928",
                                                  theme=theme)
                self.assertIn("TREND TRACKING" if theme == "pixel" else "趋势跟踪</h2>", report)
                self.assertIn("多平台信息员", report)
                self.assertIn("StockTwits", report)
                self.assertIn("TradingView", report)
                self.assertIn("交易员观点", report)
                self.assertNotIn("Bogleheads", report.split("数据覆盖")[0])  # 失败平台不进正文
                self.assertRegex(report, r"暂缺：[^<]*Reddit[^<]*Bogleheads")
                self.assertEqual(pipeline._report_meta(report)["total_sources"], 12)  # 8 基础 + 4 平台
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)
        self.assertIn("当天", reason)


if __name__ == "__main__":
    unittest.main()
