"""十站投研栏目的离线解析、降级、主题渲染及推送门禁测试（不访问网站/不写历史报告）。"""
import html
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


def rss_item(title, url, dt, summary=""):
    date = dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    return (f"<item><title>{html.escape(title)}</title><link>{html.escape(url)}</link>"
            f"<pubDate>{date}</pubDate><description>{html.escape(summary)}</description></item>")


def rss(*items):
    return "<rss version='2.0'><channel>" + "".join(items) + "</channel></rss>"


def snowflake(dt):
    return ((int(dt.timestamp() * 1000) - 1288834974657) << 22) + 1


class PublicSitesTests(unittest.TestCase):
    def test_url_allowlist_and_clean_text(self):
        self.assertEqual(pipeline._public_url("/stocks/AKAM", "https://www.trackserenity.com/"),
                         "https://www.trackserenity.com/stocks/AKAM")
        for url in ("javascript:alert(1)", "http://www.reddit.com/r/stocks",
                    "https://seekingalpha.com.evil.net/path", "//evil.net/path",
                    "https://www.koyfin.com\\@evil.net/", "https://foo.com/<script>"):
            self.assertEqual(pipeline._public_url(url, "https://www.koyfin.com/"), "")
        self.assertEqual(pipeline._public_text("<b>ETF</b> &amp; market\n news"), "ETF & market news")

    def test_article_rss_keeps_only_dated_relevant_source_and_72_hours(self):
        now = datetime(2026, 9, 27, 14, tzinfo=pipeline.CST)
        feed = rss(
            rss_item("OLD stale", "https://seekingalpha.com/article/old", now - timedelta(hours=80)),
            rss_item("Yesterday &amp; earnings", "https://seekingalpha.com/article/one",
                     now - timedelta(hours=26)),
            rss_item("New company thesis", "https://seekingalpha.com/article/two",
                     now - timedelta(hours=1)),
            rss_item("Injected", "https://evil.example/article", now - timedelta(hours=1)),
        )
        feed = feed.replace("</channel>",
                            "<item><title>No zone</title><link>https://seekingalpha.com/article/naive</link>"
                            "<pubDate>2026-09-27T13:00:00</pubDate></item></channel>")
        items, latest = pipeline._public_rss_items(feed, "https://seekingalpha.com/feed.xml", now=now)
        self.assertEqual([it["url"] for it in items],
                         ["https://seekingalpha.com/article/two", "https://seekingalpha.com/article/one"])
        self.assertEqual([it["is_today"] for it in items], [True, False])
        self.assertEqual(latest, "2026-09-27")
        self.assertTrue(all("发布于" in it["detail"] for it in items))

    def test_seeking_alpha_and_koyfin_stale_is_unavailable_not_today(self):
        now = datetime.now(pipeline.CST)
        good = rss(rss_item("A public earnings headline", "https://seekingalpha.com/article/1",
                            now - timedelta(hours=2)))
        old = rss(rss_item("Last month blog", "https://www.koyfin.com/blog/last-month",
                           now - timedelta(days=29)))
        with patch.object(pipeline, "safe_request", side_effect=[good, old]):
            sa = pipeline.fetch_seeking_alpha()
            koyfin = pipeline.fetch_koyfin()
        self.assertTrue(sa["is_today"])
        self.assertEqual(sa["status"], "success")
        self.assertNotIn("rating", str(sa["items"]).lower())
        self.assertFalse(koyfin["is_today"])
        self.assertEqual(koyfin["status"], "unavailable")
        self.assertIn("72小时", koyfin["error"])
        self.assertFalse(koyfin["items"])

    def test_ten_site_registry_and_global_three_item_limit(self):
        self.assertEqual(len(pipeline.PUBLIC_SITE_NAMES), 10)
        self.assertEqual(pipeline.PUBLIC_SITE_DISPLAY_N, 3)
        self.assertEqual(pipeline.PUBLIC_SITE_ITEM_LIMIT, 3)
        self.assertEqual(set(pipeline.PUBLIC_SITE_NAMES), set(pipeline.PUBLIC_SITE_DESCRIPTIONS))
        items = [{"title": str(i), "url": "https://fred.stlouisfed.org/", "is_today": False}
                 for i in range(5)]
        self.assertEqual(len(pipeline._public_site_result("FRED", items)["items"]), 3)

    def test_etf_database_rss_keeps_three_recent_articles_and_summaries(self):
        now = datetime.now(pipeline.CST)
        feed = rss(*(rss_item(f"ETF research {i}", f"https://etfdb.com/articles/{i}/",
                              now - timedelta(hours=i), "Holdings, expense ratio and dividend details")
                     for i in range(4)))
        with patch.object(pipeline, "safe_request", return_value=feed):
            result = pipeline.fetch_etf_database()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["items"]), 3)
        self.assertIn("ETF research 0", result["items"][0]["title"])
        self.assertIn("Holdings, expense ratio", result["items"][0]["detail"])
        self.assertTrue(all("发布于" in item["detail"] for item in result["items"]))

    def test_macromicro_uses_visible_latest_stats_and_marks_partial_data(self):
        chart = ("<html><h2>Latest Stats</h2><table><tr><td>2026-08-31</td>"
                 "<td>3.63%</td></tr></table><p>High &amp; Low</p><p>hidden navigation</p></html>")
        stats, data_date = pipeline._macromicro_latest_stats(chart)
        self.assertIn("3.63%", stats)
        self.assertEqual(data_date, "2026-08-31")
        self.assertNotIn("hidden navigation", stats)
        self.assertEqual(pipeline._macromicro_latest_stats(
            "<h2>Latest Stats</h2><p>1980-01-01</p><p>0.0000%</p>"), ("", None))
        with patch.object(pipeline, "safe_request", side_effect=[chart, None, chart]):
            result = pipeline.fetch_macro_micro()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["items"]), 2)
        self.assertIn("利率 / 流动性", result["items"][0]["title"])
        self.assertIn("暂缺图表：通胀趋势", result["note"])
        self.assertFalse(result["is_today"])

    def test_fred_csv_parsing_yoy_and_three_macro_cards(self):
        cpi_csv = ("observation_date,CPIAUCSL\n2025-08-01,100\n"
                   "2026-08-01,103\n2026-09-01,.\n")
        observations = pipeline._parse_fred_csv(cpi_csv, "CPIAUCSL")
        self.assertEqual(observations, [("2025-08-01", 100.0), ("2026-08-01", 103.0)])
        self.assertEqual(pipeline._parse_fred_csv(
            cpi_csv, "CPIAUCSL", start_date="2026-01-01"), [("2026-08-01", 103.0)])
        self.assertAlmostEqual(pipeline._fred_yoy(observations), 3.0)

        def fake_request(url, **kwargs):
            series_id = url.split("id=", 1)[1].split("&", 1)[0]
            if series_id in ("DFF", "DGS10"):
                rows = "2026-09-24,4.1\n2026-09-25,4.2"
            else:
                rows = "2025-08-01,100\n2026-08-01,103"
            return f"observation_date,{series_id}\n{rows}\n"

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_fred()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["items"]), 3)
        self.assertIn("联邦基金有效利率 4.20%", result["items"][0]["detail"])
        self.assertIn("M2货币供应量", result["items"][0]["detail"])
        self.assertIn("同比 +3.00%", result["items"][1]["detail"])
        self.assertTrue(all("（2026-08-01）" in item["detail"] for item in result["items"][1:]))
        self.assertIn("观测日期", result["note"])

    STOCKANALYSIS_HTML = """<table><tr><th>No.</th><th>Symbol</th><th>Company Name</th>
    <th>Views</th><th>Market Cap</th><th>% Change</th></tr>
    <tr><td>1</td><td><a href="/stocks/aapl/">AAPL</a></td><td>Apple Inc.</td>
    <td>1.2M</td><td>$3.0T</td><td>0.5%</td></tr>
    <tr><td>2</td><td><a href="/stocks/msft/">MSFT</a></td><td>Microsoft Corp.</td>
    <td>900K</td><td>$2.8T</td><td>0.2%</td></tr>
    <tr><td>3</td><td><a href="/stocks/nvda/">NVDA</a></td><td>NVIDIA Corp.</td>
    <td>800K</td><td>$2.5T</td><td>-1.0%</td></tr>
    <tr><td>4</td><td><a href="https://evil.example/stocks/evil/">EVIL</a></td><td>Injected</td>
    <td>700K</td><td>$1T</td><td>2.0%</td></tr></table>
    <p>Updated: Sep 27, 2026, 7:30 AM EDT.</p>"""

    def test_stockanalysis_selects_three_valid_in_site_trending_links(self):
        rows = pipeline._stockanalysis_trending_rows(self.STOCKANALYSIS_HTML)
        self.assertEqual([row["symbol"] for row in rows], ["AAPL", "MSFT", "NVDA"])
        with patch.object(pipeline, "safe_request", return_value=self.STOCKANALYSIS_HTML):
            result = pipeline.fetch_stockanalysis()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["items"]), 3)
        self.assertTrue(result["snapshot"])
        self.assertEqual(pipeline._stockanalysis_updated_date(self.STOCKANALYSIS_HTML), "2026-09-27")
        self.assertIn("浏览量排名 #1", result["items"][0]["detail"])
        self.assertIn("榜单原站更新时间：2026-09-27", result["note"])
        self.assertIn("不代表买入推荐", result["note"])

    FINVIZ_HTML = """<html><script><table><tr><td>fake</td></tr></table></script>
    <table><tr><th>No.</th><th>Name</th><th>Perf Week</th><th>Change %</th></tr>
    <tr><td>1</td><td><a href="screener?f=sec_technology&amp;v=141">Technology</a></td>
      <td>3.06%</td><td>0.85%</td></tr>
    <tr><td>2</td><td><a href="screener?f=sec_energy&amp;v=141">Energy</a></td>
      <td>-2.89%</td><td>-0.96%</td></tr>
    <tr><td>3</td><td><a href="screener?f=sec_financial&amp;v=141">Financial</a></td>
      <td>-1.26%</td><td>0.79%</td></tr></table></html>"""
    PATTERN_HTML = """<table><tr><th>Ticker</th><th>Company</th></tr>
    <tr><td><a href="quote.ashx?t=NVDA">NVDA</a></td><td>NVIDIA</td></tr>
    <tr><td><a href="quote.ashx?t=AMD">AMD</a></td><td>AMD</td></tr></table>"""

    def test_finviz_sector_sort_and_pattern_are_public_snapshots(self):
        sectors = pipeline._finviz_sector_rows(self.FINVIZ_HTML)
        self.assertEqual(len(sectors), 3)
        self.assertEqual(sectors[0]["week"], 3.06)
        with patch.object(pipeline, "safe_request", side_effect=[self.FINVIZ_HTML, self.PATTERN_HTML]):
            result = pipeline.fetch_finviz()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["snapshot"])
        self.assertEqual(len(result["items"]), 3)
        self.assertIn("Technology +0.85%", result["items"][0]["title"])
        self.assertIn("Energy -0.96%", result["items"][0]["title"])
        self.assertIn("NVDA / AMD", result["items"][1]["title"])
        self.assertIn("热力图", result["items"][2]["title"])
        self.assertTrue(all(not it["is_today"] for it in result["items"]))
        self.assertEqual(pipeline._finviz_sector_rows("<html>Cloudflare</html>"), [])
        with patch.object(pipeline, "safe_request", return_value=None):
            self.assertEqual(pipeline.fetch_finviz()["status"], "unavailable")

    def test_cmc_four_rankings_validate_csv_and_report_partial_failure(self):
        def fake_request(url, **kwargs):
            metric = next((column for _, target, column in pipeline._CMC_RANKINGS if target == url), None)
            if metric == "earnings_ttm":
                return "<html>access denied</html>"
            return (f"Rank,Name,Symbol,{metric}\n"
                    f"1,Alpha Inc,ALPH,{42.5 if metric == 'pe_ratio_ttm' else 2300000000000}\n"
                    f"2,Beta Holdings,BETA,{9.23 if metric == 'pe_ratio_ttm' else 1200000000000}\n"
                    f"3,Gamma Corp,GAMM,{13.1 if metric == 'pe_ratio_ttm' else 700000000000}\n")

        with patch.object(pipeline, "safe_request", side_effect=fake_request):
            result = pipeline.fetch_companies_marketcap()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["snapshot"])
        self.assertEqual(len(result["items"]), 3)
        self.assertIn("2.30 万亿美元", result["items"][0]["title"])
        self.assertIn("市值", result["items"][0]["detail"])
        self.assertIn("营收 TTM", result["items"][0]["detail"])
        self.assertIn("市盈率（从低到高）", result["items"][0]["detail"])
        self.assertIn("42.50 倍", result["items"][0]["detail"])
        self.assertIn("利润 TTM", result["note"])
        self.assertIn("不代表买入建议", result["note"])
        self.assertEqual(pipeline._parse_cmc_csv("Not a CSV", "marketcap"), [])
        self.assertEqual(pipeline._parse_cmc_csv("Rank,Name,Symbol,marketcap\n1,Bad,BAD,nan", "marketcap"), [])
        with patch.object(pipeline, "safe_request", return_value=None):
            self.assertEqual(pipeline.fetch_companies_marketcap()["status"], "unavailable")

    def test_reddit_four_communities_rss_then_public_json_and_partial_403(self):
        now = datetime.now(pipeline.CST)
        atom_date = (now - timedelta(hours=1)).astimezone(timezone.utc).isoformat()
        atom = ("<feed xmlns='http://www.w3.org/2005/Atom'><entry>"
                "<title>Tech shares &amp; valuations</title>"
                "<link rel='alternate' href='https://www.reddit.com/r/stocks/comments/abc/a/'/>"
                f"<published>{atom_date}</published></entry></feed>")
        payload = {"data": {"children": [{"data": {
            "title": "Global earnings", "permalink": "/r/investing/comments/def/b/",
            "created_utc": (now - timedelta(hours=2)).timestamp(), "stickied": False,
        }}]}}

        def fake_request(url, **kwargs):
            if "/r/stocks/" in url and url.endswith(".rss?t=day&limit=10"):
                return atom
            if "/r/investing/" in url and ".json" in url:
                return payload
            return None  # 模拟 wsb / ValueInvesting 的 403

        with patch.object(pipeline, "safe_request", side_effect=fake_request) as req:
            result = pipeline.fetch_reddit()
        self.assertEqual([it["title"].split("：")[0] for it in result["items"]],
                         ["r/stocks", "r/investing"])
        self.assertTrue(result["is_today"])
        self.assertIn("r/wallstreetbets", result["note"])
        self.assertIn("r/ValueInvesting", result["note"])
        self.assertEqual(req.call_count, 7)  # RSS * 4 + JSON 兜底 * 3
        self.assertEqual(pipeline._reddit_json_items({"data": {"children": [{"data": {
            "title": "Bad", "created_utc": now.timestamp(),
            "permalink": "https://evil.example/r/stocks/comments/1"}}]}}), [])
        with patch.object(pipeline, "safe_request", return_value=None):
            failed = pipeline.fetch_reddit()
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(failed["items"], [])

    def test_trackserenity_sorts_posts_verifies_x_timestamp_and_skips_old_cards(self):
        # 公开原帖的 ID 可独立核对站点所写的无时区日期确为北京时间。
        actual = pipeline._serenity_x_dt("https://x.com/aleabitoreddit/status/2103490181525631382")
        self.assertEqual(actual.strftime("%Y-%m-%d %H:%M"), "2026-09-25 22:21")
        now = datetime(2026, 9, 27, 14, tzinfo=pipeline.CST)
        a = now - timedelta(hours=39)
        b = now - timedelta(hours=18)
        old = now - timedelta(days=80)

        def post(dt, body, *, shown=None, card=""):
            stamp = shown or dt.strftime("%Y-%m-%d %H:%M")
            return (f"<article><b>Serenity</b><time>{stamp}</time><p>{html.escape(body)}</p>"
                    f"{card}<a href='https://x.com/aleabitoreddit/status/{snowflake(dt)}'>"
                    "Open on X</a></article>")

        page = "<html><body>" + "".join([
            post(old, "$OLD old opinion"),
            post(a, "$AKAM buys memory for AI workloads",
                 card="<a href='/stocks/AKAM'>AKAM $9999 since mention</a>"),
            post(b, "$SPY equities and inflation remain linked"),
            post(b - timedelta(hours=1), "$NO do not show", shown="2000-01-01 00:00"),
            post(b - timedelta(hours=2), "Happy birthday, followers!"),
        ]) + "</body></html>"
        items, latest = pipeline._parse_serenity_posts(page, now=now)
        self.assertEqual(len(items), 2)
        self.assertIn("$SPY", items[0]["title"])
        self.assertIn("$AKAM", items[1]["title"])
        self.assertEqual(latest, b.strftime("%Y-%m-%d"))
        self.assertNotIn("9999", " ".join(it["title"] for it in items))
        self.assertNotIn("$OLD", str(items))
        self.assertNotIn("$NO", str(items))
        split = (f"<time>{a.strftime('%Y-%m-%d %H:%M')}</time>"
                 f"<p>$<span>AMD</span> supplies CPUs</p>"
                 f"<a href='https://x.com/aleabitoreddit/status/{snowflake(a)}'>Open on X</a>")
        split_items, _ = pipeline._parse_serenity_posts(split, now=now)
        self.assertEqual(split_items[0]["symbols"], ["AMD"])
        thesis = ("<h2>Serenity Thesis for $AKAM</h2><p>Serenity (@aleabitoreddit) investment "
                  "thesis and position context from public X posts.</p>"
                  "<p>Upstream memory demand could benefit the supply chain.</p><h2>Financials</h2>")
        self.assertIn("Upstream memory", pipeline._serenity_thesis(thesis, "AKAM"))
        self.assertEqual(pipeline._serenity_thesis("<html>login</html>", "AKAM"), "")

    def test_trackserenity_thesis_is_optional_not_a_fabricated_fresh_rating(self):
        dt = datetime.now(pipeline.CST) - timedelta(hours=1)
        page = (f"<time>{dt.strftime('%Y-%m-%d %H:%M')}</time><p>$AKAM supply chain demand</p>"
                f"<a href='https://x.com/aleabitoreddit/status/{snowflake(dt)}'>Open on X</a>")
        stock = ("<h2>Serenity Thesis for $AKAM</h2><p>Serenity (@aleabitoreddit) investment "
                 "thesis and position context from public X posts.</p>"
                 "<p>Compute demand is the thesis behind this investment.</p><h2>Financials</h2>")
        with patch.object(pipeline, "safe_request", side_effect=[page, stock]):
            result = pipeline.fetch_trackserenity()
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["items"]), 2)
        self.assertFalse(result["items"][1]["is_today"])
        self.assertIn("未标注", result["items"][1]["detail"])
        self.assertNotIn("AI 评分", result["items"][1]["title"])
        with patch.object(pipeline, "safe_request", return_value="<html>login</html>"):
            self.assertEqual(pipeline.fetch_trackserenity()["status"], "unavailable")

    def test_parallel_results_collect_and_error_isolation(self):
        funcs = ("fetch_macro_micro", "fetch_seeking_alpha", "fetch_finviz", "fetch_reddit",
                 "fetch_companies_marketcap", "fetch_trackserenity", "fetch_koyfin",
                 "fetch_etf_database", "fetch_stockanalysis", "fetch_fred")
        patches = []
        for name, attr in zip(pipeline.PUBLIC_SITE_NAMES, funcs):
            if name == "Reddit":
                patches.append(patch.object(pipeline, attr, side_effect=ValueError("broken feed")))
            else:
                patches.append(patch.object(pipeline, attr, return_value=pipeline._public_site_result(
                    name, [{"title": "Sample", "url": pipeline.PUBLIC_SITE_URLS[name],
                            "is_today": False}])))
        for p in patches:
            p.start()
        try:
            results = pipeline.fetch_public_sites()
        finally:
            for p in reversed(patches):
                p.stop()
        self.assertEqual(tuple(results), pipeline.PUBLIC_SITE_NAMES)
        self.assertEqual(results["Reddit"]["status"], "unavailable")
        self.assertEqual(len(results), 10)
        # 每天原有的基础数据源仍执行，十站投研并入同一份数据而非额外发送消息。
        legacy = ("fetch_market_snapshot", "fetch_market_panorama", "fetch_gov_policy",
                  "fetch_hk_channels", "fetch_google_news", "fetch_sina_headlines",
                  "fetch_eastmoney_news", "fetch_hot_stocks")
        with patch.object(pipeline, "time", types.SimpleNamespace(sleep=lambda s: None)):
            mocks = [patch.object(pipeline, fn, return_value={"status": "unavailable"}) for fn in legacy]
            for p in mocks:
                p.start()
            try:
                with patch.object(pipeline, "fetch_public_sites", return_value=results):
                    data = pipeline.collect_all_data()
            finally:
                for p in reversed(mocks):
                    p.stop()
        self.assertEqual(len(data), 18)
        self.assertEqual(data["Seeking Alpha"]["status"], "success")

    def test_public_digest_precedes_market_in_both_themes(self):
        data = {
            "Seeking Alpha": pipeline._public_site_result("Seeking Alpha", [
                {"title": "Actual public research", "url": "https://seekingalpha.com/article/1",
                 "detail": "发布于 2026-09-27 08:00", "is_today": True}]),
            "实时行情": pipeline._source_result("sample quote", "success", quotes={
                "标普500": {"price": 6123.45, "change_pct": 1.25}}),
        }
        with patch.object(pipeline, "AI_ANALYSIS_ENABLED", False):
            for kit in (pipeline.GUIZANG_KIT, pipeline.PIXEL_KIT):
                titles = [s[1] for s in pipeline._collect_report_parts(data, kit)["sections"]]
                # 结论先行 → 行情数据 → 投研资讯 → 盘点收尾
                self.assertLess(titles.index("行情速览"), titles.index("每日量化策略投研"))
                self.assertEqual(titles[-1], "盘点总结")

    def test_two_themes_render_audited_sites_and_preserve_today_gate(self):
        results = {name: pipeline._public_site_result(name, [], error="受限或没有新文章")
                   for name in pipeline.PUBLIC_SITE_NAMES}
        results["Seeking Alpha"] = pipeline._public_site_result("Seeking Alpha", [
            {"title": 'Analyst &amp; earnings <img src=x onerror="alert(1)">',
             "url": "https://seekingalpha.com/article/1?source=feed&topic=stock",
             "detail": "发布于 2026-09-27 08:00（北京时间）", "is_today": True}],
            latest="2026-09-27")
        results["CompaniesMarketCap"] = pipeline._public_site_result("CompaniesMarketCap", [
            {"title": "市值：1. Alpha $2.30万亿", "url": "https://companiesmarketcap.com/",
             "detail": "今日抓取快照，非今日财报", "is_today": False}],
            latest="2026-09-27", snapshot=True)
        results["Reddit"]["note"] = "r/stocks · 403"
        results["Seeking Alpha"]["items"].append(
            {"title": "Unsafe", "url": "javascript:alert(1)", "detail": "bad"})
        for theme in ("guizang", "pixel"):
            with self.subTest(theme=theme):
                report = pipeline.generate_report(results, "2026年9月27日 · 周日", "20260927", theme=theme)
                self.assertIn("每日量化策略投研", report)
                self.assertIn("Seeking Alpha", report)
                self.assertIn("CompaniesMarketCap", report)
                # 失败站点只在盘点总结的「数据覆盖」里点名，不展开说明
                self.assertIn("暂缺：", report)
                self.assertIn("MacroMicro", report)
                self.assertIn("FRED", report)
                self.assertNotIn(pipeline.PUBLIC_SITE_DESCRIPTIONS["MacroMicro"], report)
                self.assertNotIn("受限或没有新文章", report)
                self.assertIn("今日抓取" if theme == "guizang" else "SNAPSHOT", report)
                self.assertNotIn("今日抓取快照，非今日财报", report)   # 纯说明性详情已剔除
                self.assertIn("https://seekingalpha.com/article/1?source=feed&amp;topic=stock", report)
                self.assertNotIn("onerror", report)
                self.assertNotIn('href="javascript:', report)
                self.assertNotIn("Unsafe", report)
                self.assertEqual(pipeline._report_meta(report)["total_sources"], 18)
                self.assertGreaterEqual(pipeline._report_meta(report)["today_sources"], 2)
        can_push, reason = pipeline.check_push_eligibility(results)
        self.assertTrue(can_push)
        self.assertIn("快照", reason)
        captured, reason = pipeline.check_push_eligibility({
            "CompaniesMarketCap": results["CompaniesMarketCap"]})
        self.assertTrue(captured)  # 当天采集到的榜单快照可组成日报，但不得声称财报当日发布
        self.assertIn("非当日发布", reason)
        failed = {name: pipeline._public_site_result(name, [], error="HTTP 403")
                  for name in pipeline.PUBLIC_SITE_NAMES}
        self.assertFalse(pipeline.check_push_eligibility(failed)[0])
        for theme in ("guizang", "pixel"):
            report = pipeline.generate_report(failed, "2026年9月27日 · 周日", "20260927", theme=theme)
            self.assertNotIn("每日量化策略投研", report)  # 失败仅在盘点总结里点名
            self.assertIn("暂缺：", report)
            self.assertNotIn("HTTP 403", report)
            self.assertEqual(pipeline._report_meta(report)["total_sources"], 18)


if __name__ == "__main__":
    unittest.main()
