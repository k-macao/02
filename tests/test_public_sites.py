"""每日量化策略趋势跟踪线索（Reddit / StockTwits / Hacker News / ApeWisdom 多来源）的
离线解析、降级、主题渲染及推送门禁测试（不访问网站/不写历史报告）。"""
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

NOW = datetime.now(pipeline.CST)


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


def st_message(msg_id, body, hours_ago, *, user="trader_one", sentiment=None):
    """构造 StockTwits 公开符号流的一条 message（created_at 为显式 UTC Z 时间）。"""
    created = (NOW - timedelta(hours=hours_ago)) \
        .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    msg = {"id": msg_id, "body": body, "created_at": created,
           "user": {"username": user}, "entities": {}}
    if sentiment:
        msg["entities"] = {"sentiment": {"basic": sentiment}}
    return msg


def hn_hit(object_id, title, hours_ago, *, points=10, comments=5):
    """构造 Algolia 检索返回的一条 story（created_at 为显式 UTC Z 时间）。"""
    created = (NOW - timedelta(hours=hours_ago)) \
        .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"objectID": object_id, "title": title, "created_at": created,
            "points": points, "num_comments": comments}


class SentimentFactorTests(unittest.TestCase):
    def test_url_allowlist_is_multi_source(self):
        # Reddit 主机（www / 裸域 / old）放行
        self.assertEqual(pipeline._public_url("/r/stocks/comments/abc/x/", "https://www.reddit.com/"),
                         "https://www.reddit.com/r/stocks/comments/abc/x/")
        self.assertEqual(pipeline._public_url("https://old.reddit.com/r/stocks/comments/1/y/", ""),
                         "https://old.reddit.com/r/stocks/comments/1/y/")
        # 其余三源主机放行
        self.assertEqual(pipeline._public_url("/Googler911/message/123", "https://stocktwits.com/"),
                         "https://stocktwits.com/Googler911/message/123")
        self.assertEqual(pipeline._public_url("/item?id=49863864", "https://news.ycombinator.com/"),
                         "https://news.ycombinator.com/item?id=49863864")
        self.assertEqual(pipeline._public_url("/stocks/MU/", "https://apewisdom.io/"),
                         "https://apewisdom.io/stocks/MU/")
        # 未列入白名单的站点一律拒绝，防止标题/链接注入
        for url in ("javascript:alert(1)", "http://www.reddit.com/r/stocks",
                    "https://reddit.evil.net/r/stocks", "https://finviz.com/map.ashx?t=sec",
                    "https://fred.stlouisfed.org/series/DFF", "//evil.net/path",
                    "https://evil.stocktwits.com/message/1", "https://news.ycombinator.com.evil.net/item?id=1",
                    "https://www.reddit.com/<script>"):
            self.assertEqual(pipeline._public_url(url, "https://www.reddit.com/"), "", url)
        self.assertEqual(pipeline._public_text("<b>ETF</b> &amp; market\n news"), "ETF & market news")

    def test_source_registry_four_sources_and_shape_constants(self):
        self.assertEqual(pipeline.PUBLIC_SITE_NAMES, ("Reddit", "StockTwits", "Hacker News", "ApeWisdom"))
        self.assertEqual(set(pipeline.PUBLIC_SITE_NAMES), set(pipeline.PUBLIC_SITE_DESCRIPTIONS))
        self.assertEqual(set(pipeline.PUBLIC_SITE_NAMES), set(pipeline.PUBLIC_SITE_URLS))
        # Reddit：10 个板块、每板块 5 条，用户点名的四个板块必须在列
        self.assertEqual(len(pipeline._REDDIT_BOARDS), 10)
        self.assertEqual(len(set(board[0] for board in pipeline._REDDIT_BOARDS)), 10)
        self.assertEqual(pipeline.REDDIT_POSTS_PER_BOARD, 5)
        for named in ("stocks", "investing", "wallstreetbets", "ValueInvesting"):
            self.assertIn(named, [board[0] for board in pipeline._REDDIT_BOARDS])
        # StockTwits：8 个标的、每标的 5 条
        self.assertEqual(pipeline.STOCKTWITS_POSTS_PER_SYMBOL, 5)
        symbols = [s for s, _ in pipeline.STOCKTWITS_SYMBOLS]
        self.assertEqual(len(symbols), len(set(symbols)) == 8 and 8)
        for named in ("SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMD", "META"):
            self.assertIn(named, symbols)
        # Hacker News：6 组关键词（quant 不误伤 quantum），取前 8
        self.assertEqual(pipeline.HN_TOP_N, 8)
        self.assertEqual(len(pipeline.HN_QUERIES), 6)
        import re
        self.assertIsNone(re.search(pipeline.HN_QUERIES[0][1], "Quantum computing progress", re.I))
        self.assertIsNotNone(re.search(pipeline.HN_QUERIES[0][1], "A quant explains", re.I))
        # ApeWisdom：提及榜前 10
        self.assertEqual(pipeline.APEWISDOM_TOP_N, 10)
        # 结果容器不再对总条数做「每站 3 条」截断
        items = [{"title": str(i), "url": "https://www.reddit.com/", "is_today": False}
                 for i in range(50)]
        self.assertEqual(len(pipeline._public_site_result("Reddit", items)["items"]), 50)

    # ------------------------------------------------------------
    # Reddit（原单源行为全部保留）
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # StockTwits：trader 社交媒体公开符号流
    # ------------------------------------------------------------
    def test_stocktwits_items_parse_stance_and_skip_bad_rows(self):
        payload = {"messages": [
            st_message(201, "$SPY calls only, breakout", 1, user="bull_trader", sentiment="Bullish"),
            st_message(202, "crash incoming, hedged", 2, user="bear_trader", sentiment="Bearish"),
            st_message(203, "no stance here", 3),
            st_message(204, "bad date row", 4),
            st_message(205, "evil user row", 5, user="bad user"),  # 用户名带空格 → 外链非法 → 剔除
        ]}
        payload["messages"][3]["created_at"] = "2026-09-27 16:00:00"  # 无显式 UTC 时区 → 剔除
        items, latest = pipeline._stocktwits_items(payload, "SPY", "标普500ETF", now=NOW)
        self.assertEqual([it["community"] for it in items], ["$SPY"] * 3)
        self.assertEqual(items[0]["sentiment"], "Bullish")
        self.assertIn("标注看多", items[0]["detail"])
        self.assertIn("@bull_trader", items[0]["detail"])
        self.assertIn("标注看空", items[1]["detail"])
        self.assertNotIn("标注", items[2]["detail"])  # 无标注不显示立场，不猜测
        self.assertEqual(items[0]["url"], "https://stocktwits.com/bull_trader/message/201")
        self.assertTrue(all("发布于" in it["detail"] for it in items))
        self.assertEqual(latest, NOW.strftime("%Y-%m-%d"))
        # 非 dict / 缺 messages 的 payload 一律安全返回空
        self.assertEqual(pipeline._stocktwits_items(None, "SPY", "x", now=NOW), ([], None))
        self.assertEqual(pipeline._stocktwits_items({"messages": []}, "SPY", "x", now=NOW), ([], None))

    def test_fetch_stocktwits_partial_symbols_and_order(self):
        def fake_request(url, **kwargs):
            if url.endswith("/SPY.json"):
                return {"messages": [st_message(301, "spy 1", 1), st_message(302, "spy 2", 2)]}
            if url.endswith("/NVDA.json"):
                return {"messages": [st_message(303, "nvda 1", 1)]}
            return None  # 其余标的不可用

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_stocktwits()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["is_today"])
        # 按标的常量顺序展示：SPY → NVDA（中间的 QQQ 暂缺不占位）
        self.assertEqual([it["community"] for it in result["items"]], ["$SPY"] * 2 + ["$NVDA"])
        for missing in ("$QQQ", "$TSLA", "$AAPL", "$MSFT", "$AMD", "$META"):
            self.assertIn(missing, result["note"])
        self.assertIn("观点未经核实", result["note"])
        with patch.object(pipeline, "safe_request", return_value=None):
            failed = pipeline.fetch_stocktwits()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["items"], [])
        self.assertIn("$SPY", failed["note"])

    # ------------------------------------------------------------
    # Hacker News：Algolia 公开检索（金融/量化关键词，按点赞排序）
    # ------------------------------------------------------------
    def test_hn_items_regex_filter_heat_and_link(self):
        payload = {"hits": [
            hn_hit("5001", "A quant explains the options boom", 2, points=120, comments=88),
            hn_hit("5002", "Quantum computing progress", 3, points=300),  # quantum 不误伤 → 剔除
            hn_hit("5003", "Old quant story", 100, points=500),           # 超 72h 窗口 → 剔除
        ]}
        quant_re = pipeline.HN_QUERIES[0][1]
        items, latest = pipeline._hn_items(payload, quant_re, "量化", now=NOW)
        self.assertEqual([it["title"] for it in items], ["A quant explains the options boom"])
        self.assertEqual(items[0]["url"], "https://news.ycombinator.com/item?id=5001")
        self.assertEqual(items[0]["community"], "HN·量化")
        self.assertIn("120 赞", items[0]["detail"])
        self.assertIn("88 讨论", items[0]["detail"])
        # 最新日期取条目自身的北京时间（跨午夜运行也一致）
        self.assertEqual(latest, items[0]["published_cst"][:10])
        self.assertEqual(pipeline._hn_items(None, quant_re, "量化", now=NOW), ([], None))
        self.assertEqual(pipeline._hn_items({"hits": []}, quant_re, "量化", now=NOW), ([], None))

    def test_fetch_hackernews_merges_queries_dedups_and_sorts_by_points(self):
        def fake_request(url, **kwargs):
            self.assertEqual(url, "https://hn.algolia.com/api/v1/search_by_date")
            query = (kwargs.get("params") or {}).get("query")
            if query == "quant":
                return {"hits": [hn_hit("6001", "A quant explains the rally", 1, points=30),
                                 hn_hit("6002", "Quantum hype", 1, points=999)]}
            if query == "stock market":
                return {"hits": [hn_hit("6003", "Stock market outlook darkens", 2, points=77, comments=12),
                                 hn_hit("6001", "A quant explains the rally", 1, points=30)]}  # 跨查询去重
            return {"hits": []}

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_hackernews()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["is_today"])
        # 合并去重后按点赞降序取前 8
        self.assertEqual([it["url"] for it in result["items"]],
                         ["https://news.ycombinator.com/item?id=6003",
                          "https://news.ycombinator.com/item?id=6001"])
        self.assertEqual(result["content_date"], NOW.strftime("%Y-%m-%d"))
        self.assertIn("观点未经核实", result["note"])
        with patch.object(pipeline, "safe_request", return_value=None):
            failed = pipeline.fetch_hackernews()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["items"], [])
        self.assertIn("近72小时", failed["note"])

    # ------------------------------------------------------------
    # ApeWisdom：社媒提及趋势榜（今日抓取快照）
    # ------------------------------------------------------------
    def test_apewisdom_items_trend_annotations_and_cap(self):
        payload = {"results": [
            {"rank": 1, "ticker": "MU", "name": "Micron Technology", "mentions": 42, "upvotes": 118,
             "rank_24h_ago": 2, "mentions_24h_ago": 75},
            {"rank": 2, "ticker": "spy", "name": "SPDR S&P 500 ETF", "mentions": 40, "upvotes": 105,
             "rank_24h_ago": None, "mentions_24h_ago": None},  # 新上榜（小写归一化为大写）
            {"rank": 2, "ticker": "SPY", "name": "dup", "mentions": 1, "upvotes": 1},  # 重复剔除
            {"rank": 3, "ticker": "BYD", "name": "Boyd Gaming", "mentions": 27, "upvotes": 203,
             "rank_24h_ago": 1, "mentions_24h_ago": 5},
            {"rank": 4, "ticker": "VOO", "name": "Vanguard S&P 500 ETF", "mentions": 23, "upvotes": 85,
             "rank_24h_ago": 4, "mentions_24h_ago": 35},
            {"rank": 5, "ticker": "<script>", "name": "x", "mentions": 9},  # 非法 ticker 剔除
            {"rank": None, "ticker": "BAD", "name": "x", "mentions": 9},    # 无排名剔除
        ]}
        items, latest = pipeline._apewisdom_items(payload, now=NOW)
        self.assertEqual([it["community"] for it in items], ["$MU", "$SPY", "$BYD", "$VOO"])
        self.assertIn("提及 42 次", items[0]["detail"])
        self.assertIn("24h 前 75 次", items[0]["detail"])
        self.assertIn("▲ 较24h前升 1 位", items[0]["detail"])
        self.assertIn("新上榜", items[1]["detail"])
        self.assertIn("▼ 较24h前降 2 位", items[2]["detail"])
        self.assertIn("■ 排名持平", items[3]["detail"])
        self.assertEqual(items[0]["url"], "https://apewisdom.io/stocks/MU/")
        self.assertEqual(items[1]["title"], "SPY · SPDR S&P 500 ETF")
        self.assertTrue(all(it["is_today"] for it in items))
        self.assertEqual(latest, NOW.strftime("%Y-%m-%d"))
        self.assertEqual(pipeline._apewisdom_items(None, now=NOW), ([], None))

    def test_fetch_apewisdom_snapshot_semantics(self):
        payload = {"results": [{"rank": 1, "ticker": "MU", "name": "Micron Technology",
                                "mentions": 42, "upvotes": 118, "rank_24h_ago": 2}]}
        with patch.object(pipeline, "safe_request", return_value=payload):
            result = pipeline.fetch_apewisdom()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["snapshot"])   # 快照语义：不冒充当日发布
        self.assertTrue(result["is_today"])
        self.assertIn("快照", result["note"])
        self.assertEqual(result["items"][0]["community"], "$MU")
        with patch.object(pipeline, "safe_request", return_value=None):
            failed = pipeline.fetch_apewisdom()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["items"], [])

    # ------------------------------------------------------------
    # 四源隔离 / 采集注册 / 渲染与门禁
    # ------------------------------------------------------------
    def test_public_sites_multi_source_isolation(self):
        ok = pipeline._public_site_result(
            "StockTwits", [{"title": "x", "url": "https://stocktwits.com/a/message/1",
                            "is_today": True}])
        with patch.object(pipeline, "fetch_reddit", side_effect=ValueError("broken feed")), \
             patch.object(pipeline, "fetch_stocktwits", return_value=ok), \
             patch.object(pipeline, "fetch_hackernews",
                          return_value=pipeline._public_site_result("Hacker News", [])), \
             patch.object(pipeline, "fetch_apewisdom",
                          return_value=pipeline._public_site_result("ApeWisdom", [])):
            results = pipeline.fetch_public_sites()
        self.assertEqual(tuple(results), pipeline.PUBLIC_SITE_NAMES)
        self.assertEqual(results["Reddit"]["status"], "unavailable")   # 单源失败不拖垮其余
        self.assertEqual(results["StockTwits"]["status"], "success")

    def test_collect_all_data_has_eight_base_plus_four_public(self):
        legacy = ("fetch_market_snapshot", "fetch_market_panorama", "fetch_gov_policy",
                  "fetch_hk_channels", "fetch_google_news", "fetch_sina_headlines",
                  "fetch_eastmoney_news", "fetch_hot_stocks")
        publics = {name: pipeline._public_site_result(name, [])
                   for name in pipeline.PUBLIC_SITE_NAMES}
        with patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
            mocks = [patch.object(pipeline, fn, return_value={"status": "unavailable"})
                     for fn in legacy]
            for p in mocks:
                p.start()
            try:
                with patch.object(pipeline, "fetch_public_sites", return_value=publics):
                    data = pipeline.collect_all_data()
            finally:
                for p in reversed(mocks):
                    p.stop()
        self.assertEqual(len(data), 12)  # 8 个基础数据源 + 4 个社媒/论坛趋势跟踪来源
        for name in pipeline.PUBLIC_SITE_NAMES:
            self.assertIn(name, data)

    def _multi_source_data(self):
        reddit_items = [
            {"title": "$TSLA rally to the moon, YOLO and record high",
             "url": "https://www.reddit.com/r/wallstreetbets/comments/1/a/",
             "detail": "发布于 2026-09-27 10:00（北京时间） · 512 赞 · 234 评论",
             "published_cst": "2026-09-27 10:00", "community": "r/wallstreetbets",
             "is_today": True},
            {"title": "$NVDA dump risk",
             "url": "https://www.reddit.com/r/stocks/comments/2/b/",
             "detail": "发布于 2026-09-27 11:00（北京时间）",
             "published_cst": "2026-09-27 11:00", "community": "r/stocks",
             "is_today": True},
            {"title": "Unsafe", "url": "javascript:alert(1)",
             "detail": "bad", "published_cst": "2026-09-27 09:00",
             "community": "r/stocks", "is_today": True},
        ]
        st_items = [
            {"title": "$SPY calls only, breakout",
             "url": "https://stocktwits.com/bull_trader/message/201",
             "detail": "发布于 2026-09-27 10:00（北京时间） · @bull_trader · 标注看多",
             "published_cst": "2026-09-27 10:00", "community": "$SPY",
             "symbol_label": "标普500ETF", "sentiment": "Bullish", "is_today": True},
            {"title": "$NVDA earnings hedged",
             "url": "https://stocktwits.com/bear_trader/message/202",
             "detail": "发布于 2026-09-27 09:30（北京时间） · @bear_trader · 标注看空",
             "published_cst": "2026-09-27 09:30", "community": "$NVDA",
             "symbol_label": "英伟达", "sentiment": "Bearish", "is_today": True},
        ]
        hn_items = [
            {"title": "A quant explains the options boom",
             "url": "https://news.ycombinator.com/item?id=5001",
             "detail": "发布于 2026-09-26 09:00（北京时间） · 120 赞 · 88 讨论",
             "published_cst": "2026-09-26 09:00", "community": "HN·量化",
             "points": 120, "is_today": False},
        ]
        aw_items = [
            {"title": "MU · Micron Technology",
             "url": "https://apewisdom.io/stocks/MU/",
             "detail": "提及 42 次（24h 前 75 次） · 热度 118 · 榜单第 1 · ▲ 较24h前升 1 位",
             "published_cst": "2026-09-27 17:00", "community": "$MU", "is_today": True},
        ]
        return {
            "Reddit": pipeline._public_site_result("Reddit", reddit_items, latest="2026-09-27"),
            "StockTwits": pipeline._public_site_result("StockTwits", st_items, latest="2026-09-27"),
            "Hacker News": pipeline._public_site_result("Hacker News", hn_items, latest="2026-09-26"),
            "ApeWisdom": pipeline._public_site_result("ApeWisdom", aw_items,
                                                      latest="2026-09-27", snapshot=True),
        }

    def test_trend_section_renders_all_sources_in_both_themes(self):
        data = self._multi_source_data()
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for theme in ("guizang", "pixel"):
                with self.subTest(theme=theme):
                    report = pipeline.generate_report(data, "2026年9月27日 · 周日", "20260927",
                                                      theme=theme)
                    self.assertIn("每日量化策略趋势跟踪线索", report)
                    self.assertNotIn("每日量化情绪因子", report)  # 旧栏目名不得回潮
                    self.assertNotIn("每日量化策略投研", report)
                    # 四个来源全部出现
                    for name in pipeline.PUBLIC_SITE_NAMES:
                        self.assertIn(name, report)
                    # Reddit 板块分组
                    self.assertIn("r/stocks", report)
                    self.assertIn("个股讨论", report)
                    self.assertIn("r/wallstreetbets", report)
                    # StockTwits 标的分组 + 立场标注
                    self.assertIn("$SPY", report)
                    self.assertIn("标普500ETF", report)
                    self.assertIn("标注看多", report)
                    # HN 关键词分组 + 讨论页链接
                    self.assertIn("HN·量化", report)
                    self.assertIn("https://news.ycombinator.com/item?id=5001", report)
                    # ApeWisdom 榜单
                    self.assertIn("MU · Micron Technology", report)
                    self.assertIn("https://apewisdom.io/stocks/MU/", report)
                    # 非法 URL 条目整体剔除，不注入
                    self.assertNotIn('href="javascript:', report)
                    self.assertNotIn("Unsafe", report)
                    # 审计口径：8 个基础数据源 + 4 个社媒/论坛来源
                    self.assertEqual(pipeline._report_meta(report)["total_sources"], 12)
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)
        self.assertIn("当天", reason)

    def test_section_renders_when_reddit_down_but_others_up(self):
        data = self._multi_source_data()
        data["Reddit"] = pipeline._public_site_result("Reddit", [], error="HTTP 403")
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            report = pipeline.generate_report(data, "2026年9月27日 · 周日", "20260927",
                                              theme="guizang")
        # Reddit 挂了其余三源照常出栏目（独立降级）
        self.assertIn("每日量化策略趋势跟踪线索", report)
        self.assertIn("StockTwits", report)
        self.assertIn("Hacker News", report)
        self.assertIn("ApeWisdom", report)
        can_push, _reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)  # 三个社媒源含当天内容，推送门禁通过

    def test_section_absent_and_failures_named_when_all_sources_down(self):
        failed = {name: pipeline._public_site_result(name, [], error="down")
                  for name in pipeline.PUBLIC_SITE_NAMES}
        for theme in ("guizang", "pixel"):
            report = pipeline.generate_report(failed, "2026年9月27日 · 周日", "20260927", theme=theme)
            self.assertNotIn("每日量化策略趋势跟踪线索", report)  # 整栏缺席，失败仅在盘点总结里点名
            self.assertIn("暂缺：", report)
            for name in pipeline.PUBLIC_SITE_NAMES:
                self.assertIn(name, report)
            self.assertNotIn("down", report)
            self.assertEqual(pipeline._report_meta(report)["total_sources"], 12)
        self.assertFalse(pipeline.check_push_eligibility(failed)[0])

    def test_legacy_reddit_only_sample_still_renders_and_gates(self):
        data = self._multi_source_data()
        data.pop("StockTwits"), data.pop("Hacker News"), data.pop("ApeWisdom")
        data["实时行情"] = pipeline._source_result("sample quote", "success", quotes={
            "标普500": {"price": 6123.45, "change_pct": 1.25}})
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for theme in ("guizang", "pixel"):
                with self.subTest(theme=theme):
                    report = pipeline.generate_report(data, "2026年9月27日 · 周日", "20260927",
                                                      theme=theme)
                    self.assertIn("每日量化策略趋势跟踪线索", report)
                    self.assertIn("r/stocks", report)
                    self.assertNotIn("StockTwits", report)  # 未采集的来源不出现在正文
                    self.assertEqual(pipeline._report_meta(report)["total_sources"], 9)
        can_push, reason = pipeline.check_push_eligibility(data)
        self.assertTrue(can_push)
        self.assertIn("当天", reason)


if __name__ == "__main__":
    unittest.main()
