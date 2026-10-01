"""🗄️ 市场数据库（隐藏功能）回归测试 —— 全部离线，不发任何网络请求。

覆盖四件事：
  ① 多源契约：源头 >3（5 路，其中 4 路参与比价）、每路可换镜像、代码映射正确、
     单只标的异常不拖垮整路源、单路全失败只记 failed；
  ② 交叉验证：一致 / 离群 / 滞后 / 冲突 / 孤证五种判定，共识价只用可信源；
  ③ 自我检查：源覆盖、标的覆盖、数值合理性、跨时段与跨日跳变、非交易日不误判；
  ④ 落库与 AI 数据集：日期命名文件、同日三档合并、同档重拉覆盖留痕、哈希防改写、
     特征只用过去（截断不变性）、标签只用未来、jsonl / csv 导出、ai_context 新鲜度。

网络层用 FixtureHttp 注入（与 octopus_quant 的 fetch_json 注入同一思路），
因此本测试可在无网络环境下完整跑通。
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone

sys.modules.setdefault("requests", types.SimpleNamespace())

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")
if OUTPUT_DIR not in sys.path:
    sys.path.insert(0, OUTPUT_DIR)

import market_db as m  # noqa: E402

CST = timezone(timedelta(hours=8))
DAY1 = datetime(2026, 10, 1, 8, 0, 12, tzinfo=CST)      # 周四
DAY2 = datetime(2026, 10, 2, 12, 30, 20, tzinfo=CST)    # 周五
SATURDAY = datetime(2026, 10, 3, 12, 30, 5, tzinfo=CST)

SYMBOLS = ["^HSI", "0700.HK", "000001.SS", "MSFT"]
PRICES = {"^HSI": 26123.4, "0700.HK": 629.5, "000001.SS": 3842.19, "MSFT": 512.3}
PREV = {"^HSI": 26016.0, "0700.HK": 625.6, "000001.SS": 3830.3, "MSFT": 513.3}


def stamp(moment: datetime) -> int:
    return int(moment.timestamp())


def _em_payload(prices, prev, deviate, when):
    diff = []
    for sym, price in prices.items():
        secid = m.em_secid(sym)
        if not secid:
            continue
        market, code = secid.split(".", 1)
        value = round(price * deviate.get(sym, 1.0), 4)
        diff.append({"f2": value, "f3": 0.5, "f4": 0.1, "f5": 10000, "f6": 1.2e8,
                     "f12": code, "f13": int(market) if market.isdigit() else market, "f14": sym,
                     "f15": round(value * 1.01, 4), "f16": round(value * 0.99, 4),
                     "f17": round(value * 0.995, 4), "f18": prev.get(sym), "f124": stamp(when)})
    return {"data": {"diff": diff}}


def _sina_payload(prices, prev, deviate, when):
    lines = []
    for sym, price in prices.items():
        code = m.sina_code(sym)
        if not code:
            continue
        value = round(price * deviate.get(sym, 1.0), 4)
        date_str, clock = when.strftime("%Y-%m-%d"), when.strftime("%H:%M:%S")
        prev_close = prev.get(sym)
        if code.startswith("hk"):
            parts = [sym, sym, f"{value*0.999:.3f}", f"{prev_close:.3f}", f"{value*1.01:.3f}",
                     f"{value*0.99:.3f}", f"{value:.3f}", "3.900", "0.623"] + ["0"] * 20 + [date_str, clock]
        else:
            parts = [sym, f"{value*0.999:.3f}", f"{prev_close:.3f}", f"{value:.3f}",
                     f"{value*1.01:.3f}", f"{value*0.99:.3f}", "0", "0", "1000", "1.2e8"] \
                + ["0"] * 20 + [date_str, clock]
        lines.append(f'var hq_str_{code}="' + ",".join(parts) + '";')
    return "\n".join(lines)


def _tencent_payload(prices, prev, deviate, when):
    lines = []
    for sym, price in prices.items():
        code = m.tencent_code(sym)
        if not code:
            continue
        value = round(price * deviate.get(sym, 1.0), 4)
        parts = [""] * 40
        parts[1], parts[2] = sym, code
        parts[3], parts[4], parts[5] = f"{value:.3f}", f"{prev.get(sym):.3f}", f"{value*0.999:.3f}"
        parts[30] = when.strftime("%Y%m%d%H%M%S")
        parts[33], parts[34], parts[37] = f"{value*1.01:.3f}", f"{value*0.99:.3f}", "1.2e8"
        lines.append(f'v_{code}="' + "~".join(parts) + '";')
    return "\n".join(lines)


def _yahoo_payload(sym, prices, prev, deviate, when):
    value = round(prices[sym] * deviate.get(sym, 1.0), 4)
    return {"chart": {"result": [{"meta": {
        "regularMarketPrice": value, "chartPreviousClose": prev.get(sym),
        "regularMarketTime": stamp(when), "regularMarketDayHigh": round(value * 1.01, 4),
        "regularMarketDayLow": round(value * 0.99, 4), "regularMarketOpen": round(value * 0.998, 4),
        "regularMarketVolume": 10000, "shortName": sym}}]}}


class FixtureHttp:
    """按 URL 路由的假 HTTP：可模拟单源失败、滞后时间、单源偏离、单只抛异常。"""

    def __init__(self, prices=None, prev=None, *, fail=(), lag_minutes=None, deviate=None,
                 when=None, raise_for=()):
        self.prices = dict(prices or PRICES)
        self.prev = dict(prev or PREV)
        self.fail = set(fail)
        self.lag_minutes = dict(lag_minutes or {})
        self.deviate = {k: dict(v) for k, v in (deviate or {}).items()}
        self.when = when or DAY1
        self.raise_for = set(raise_for)
        self.calls = []

    def _moment(self, source):
        return self.when - timedelta(minutes=self.lag_minutes.get(source, 0))

    def get(self, url, headers=None, timeout=None, is_text=False):
        self.calls.append(url)
        if "ulist.np" in url:
            source = "eastmoney"
            if source in self.fail:
                return None, "模拟失败"
            return _em_payload(self.prices, self.prev, self.deviate.get(source, {}),
                               self._moment(source)), None
        if "hq.sinajs" in url:
            source = "sina"
            if source in self.fail:
                return None, "模拟失败"
            return _sina_payload(self.prices, self.prev, self.deviate.get(source, {}),
                                 self._moment(source)), None
        if "qt.gtimg" in url:
            source = "tencent"
            if source in self.fail:
                return None, "模拟失败"
            return _tencent_payload(self.prices, self.prev, self.deviate.get(source, {}),
                                    self._moment(source)), None
        if "finance.yahoo.com" in url:
            source = "yahoo"
            sym = url.split("/chart/")[1].split("?")[0]
            if source in self.fail or sym in self.raise_for:
                return None, "模拟失败"
            if sym not in self.prices:
                return None, "无此标的"
            return _yahoo_payload(sym, self.prices, self.prev, self.deviate.get(source, {}),
                                  self._moment(source)), None
        if "kline/get" in url:
            if "em_kline" in self.fail:
                return None, "模拟失败"
            from urllib.parse import parse_qs, urlparse
            secid = parse_qs(urlparse(url).query).get("secid", [""])[0]
            sym = next((s for s in self.prices if m.em_secid(s) == secid), None)
            if not sym:
                return None, "无此标的"
            return {"data": {"klines": [f"2026-09-30,{self.prev[sym]*0.999:.2f},"
                                        f"{self.prev[sym]:.2f},{self.prev[sym]*1.01:.2f},"
                                        f"{self.prev[sym]*0.99:.2f},10000,1.2e8"]}}, None
        return None, "无路由"


class TempRootCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="octopus_db_test_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def pull(self, http=None, slot="0800", now=DAY1, **kw):
        return m.pull(slot, root=self.root, http=http or FixtureHttp(), now=now,
                      symbols=SYMBOLS, verbose=False, **kw)


# ======================================================================
# ① 注册表与代码映射
# ======================================================================
class RegistryTests(unittest.TestCase):
    def test_more_than_three_sources_and_price_peers(self):
        """源头 >3：注册表至少 4 路，其中至少 4 路参与比价。"""
        self.assertGreaterEqual(len(m.SOURCES), 4)
        self.assertGreaterEqual(sum(1 for s in m.SOURCES.values() if s["price_peer"]), 4)
        for key, spec in m.SOURCES.items():
            with self.subTest(source=key):
                self.assertTrue(spec["hosts"])
                self.assertTrue(all(host and "/" not in host for host in spec["hosts"]))
                self.assertTrue(spec["label"])

    def test_hosts_are_mirror_sets(self):
        self.assertGreaterEqual(len(m.SOURCES["eastmoney"]["hosts"]), 2)
        self.assertGreaterEqual(len(m.SOURCES["yahoo"]["hosts"]), 2)
        self.assertGreaterEqual(len(m.SOURCES["em_kline"]["hosts"]), 2)

    def test_code_mappings(self):
        self.assertEqual(m.em_secid("0700.HK"), "116.00700")
        self.assertEqual(m.em_secid("^HSI"), "100.HSI")
        self.assertEqual(m.em_secid("000001.SS"), "1.000001")
        self.assertEqual(m.em_secid("399006.SZ"), "0.399006")
        self.assertEqual(m.em_secid("MSFT"), "105.MSFT")
        self.assertEqual(m.sina_code("0700.HK"), "hk00700")
        self.assertEqual(m.sina_code("^HSTECH"), "hkHSTECH")
        self.assertEqual(m.sina_code("000001.SS"), "sh000001")
        self.assertEqual(m.sina_code("MSFT"), "")            # 新浪美股字段口径不同，不纳入
        self.assertEqual(m.tencent_code("0700.HK"), "hk00700")
        self.assertEqual(m.tencent_code("MSFT"), "usMSFT")

    def test_universe_covers_hk_and_more(self):
        codes = [code for _n, code, _mk in m.symbol_universe()]
        self.assertIn("^HSI", codes)
        self.assertIn("0700.HK", codes)
        self.assertGreaterEqual(len(codes), 20)
        self.assertEqual(len(codes), len(set(codes)))         # 不重复
        self.assertEqual(m.market_of("0700.HK"), "HK")
        self.assertEqual(m.market_of("^GSPC"), "US")
        self.assertEqual(m.market_of("000001.SS"), "A")

    def test_slots_and_schedule(self):
        self.assertEqual(m.SLOTS, ("0800", "1230", "1700"))
        self.assertEqual(m.scheduled_at("2026-10-01", "1230"), "2026-10-01 12:30:00")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 8, 2, tzinfo=CST)), "0800")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 12, 30, tzinfo=CST)), "1230")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 17, 1, tzinfo=CST)), "1700")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 21, 0, tzinfo=CST)), "1700")
        self.assertEqual(m.resolve_slot("auto", datetime(2026, 10, 1, 3, 0, tzinfo=CST)), "0800")


# ======================================================================
# ② 各源适配器
# ======================================================================
class AdapterTests(unittest.TestCase):
    def test_parse_sina_a_and_hk(self):
        rows = {}
        text = _sina_payload(PRICES, PREV, {}, DAY1)
        for match in __import__("re").finditer(r'hq_str_(\w+)="([^"]*)"', text):
            rows[match.group(1)] = m._parse_sina_line(match.group(1), match.group(2))
        self.assertAlmostEqual(rows["hk00700"]["price"], PRICES["0700.HK"], places=3)
        self.assertEqual(rows["hk00700"]["prev_close"], PREV["0700.HK"])
        self.assertTrue(rows["hk00700"]["quote_time"].startswith("2026-10-01"))
        self.assertAlmostEqual(rows["sh000001"]["price"], PRICES["000001.SS"], places=3)
        self.assertEqual(rows["sh000001"]["name"], "000001.SS")

    def test_parse_tencent_and_yahoo_and_kline(self):
        text = _tencent_payload(PRICES, PREV, {}, DAY1)
        payload = text.split('"')[1]
        row = m._parse_tencent_line(payload)
        self.assertAlmostEqual(row["price"], PRICES["^HSI"], places=3)
        self.assertEqual(row["quote_time"], "2026-10-01 08:00:12")
        yahoo = m._yahoo_quote_from_chart(_yahoo_payload("MSFT", PRICES, PREV, {}, DAY1))
        self.assertAlmostEqual(yahoo["price"], PRICES["MSFT"], places=3)
        self.assertIsNone(m._yahoo_quote_from_chart({"chart": {"result": []}}))
        kline = m._em_kline_last_close({"data": {"klines": ["2026-09-30,1,2,3,0.5,7,8"]}})
        self.assertEqual(kline["close"], 2.0)
        self.assertEqual(kline["date"], "2026-09-30")
        self.assertIsNone(m._em_kline_last_close({"data": {}}))

    def test_invalid_payload_marks_source_failed(self):
        class Empty(FixtureHttp):
            def get(self, url, headers=None, timeout=None, is_text=False):
                if "ulist.np" in url:
                    return {"data": {"diff": []}}, None
                return super().get(url, headers=headers, timeout=timeout, is_text=is_text)

        result = m.fetch_eastmoney(SYMBOLS, Empty())
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["error"])

    def test_one_bad_symbol_does_not_break_yahoo_source(self):
        http = FixtureHttp(raise_for={"000001.SS"})
        result = m.fetch_yahoo(SYMBOLS, http)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("000001.SS", result["quotes"])
        self.assertIn("0700.HK", result["quotes"])

    def test_all_sources_cover_quotes_for_universe(self):
        http = FixtureHttp()
        for key, fetcher in m.FETCHERS.items():
            with self.subTest(source=key):
                result = fetcher(SYMBOLS, http)
                self.assertEqual(result["status"], "ok")
                self.assertTrue(result["quotes"])
                self.assertEqual(result["key"], key)


# ======================================================================
# ③ 交叉验证
# ======================================================================
class CrossValidateTests(unittest.TestCase):
    def _by_source(self, price=100.0, **overrides):
        out = {}
        for key in ("eastmoney", "sina", "tencent", "yahoo"):
            value = overrides.get(key, price)
            out[key] = {"price": value, "prev_close": 99.0, "quote_time": "2026-10-01 12:30:00",
                        "name": key, "open": None, "high": None, "low": None, "volume": None,
                        "amount": None, "change_pct": None}
        return out

    def test_agree_high_confidence(self):
        res = m.cross_validate("0700.HK", self._by_source())
        self.assertEqual(res["verdict"], "一致")
        self.assertEqual(res["confidence"], m.CONF_HIGH)
        self.assertEqual(res["n_agree"], 4)
        self.assertAlmostEqual(res["price"], 100.0, places=6)
        self.assertEqual(res["outliers"], [])

    def test_outlier_flagged_and_excluded(self):
        res = m.cross_validate("0700.HK", self._by_source(yahoo=103.0))
        self.assertIn("yahoo", res["outliers"])
        self.assertTrue(res["by_source"]["yahoo"]["outlier"])
        self.assertEqual(res["verdict"], "一致")
        self.assertAlmostEqual(res["price"], 100.0, places=6)     # 共识价不含离群源

    def test_lagged_source_flagged(self):
        by_source = self._by_source()
        by_source["yahoo"]["quote_time"] = "2026-10-01 11:30:00"   # 落后 60 分钟
        res = m.cross_validate("0700.HK", by_source)
        self.assertIn("yahoo", res["lagged"])
        self.assertTrue(res["by_source"]["yahoo"]["lagged"])
        self.assertEqual(res["n_agree"], 4)                        # 滞后源仍参与一致性统计

    def test_conflict_verdict(self):
        res = m.cross_validate("0700.HK", {"eastmoney": self._by_source()["eastmoney"],
                                           "sina": dict(self._by_source()["sina"], price=106.0)})
        self.assertEqual(res["verdict"], "冲突")
        self.assertEqual(res["confidence"], m.CONF_LOW)
        self.assertGreater(res["spread_pct"], m.CONFLICT_PCT)

    def test_single_source_is_single_evidence(self):
        res = m.cross_validate("0700.HK", {"eastmoney": self._by_source()["eastmoney"]})
        self.assertEqual(res["verdict"], "孤证")
        self.assertEqual(res["confidence"], m.CONF_SINGLE)

    def test_eod_close_cross_check(self):
        res = m.cross_validate("0700.HK", self._by_source(),
                               eod_close={"close": 99.05, "date": "2026-09-30"})
        check = res["eod_close_check"]
        self.assertTrue(check["ok"])
        self.assertLess(check["dev_pct"], m.SOFT_TOL_PCT)

    def test_non_peer_source_excluded_from_price_consensus(self):
        by_source = self._by_source()
        by_source["em_kline"] = {"close": 12.0, "date": "2026-09-30"}
        res = m.cross_validate("0700.HK", by_source)
        self.assertAlmostEqual(res["price"], 100.0, places=6)
        self.assertNotIn("em_kline", res["sources"])


# ======================================================================
# ④ 自我检查
# ======================================================================
class SelfCheckTests(TempRootCase):
    def test_clean_slot_scores_full(self):
        result = self.pull(slot="1230", now=DAY1.replace(hour=12, minute=30, second=12))
        slot = result["doc"]["slots"]["1230"]
        self.assertEqual(slot["self_check"]["score"], 100)
        self.assertTrue(slot["self_check"]["ok"])
        self.assertEqual(slot["cross_check"]["sources_ok"], 5)
        self.assertEqual(slot["cross_check"]["symbols_ok"], len(SYMBOLS))
        self.assertEqual(slot["cross_check"]["agreement_rate"], 1.0)

    def test_source_shortage_and_coverage_penalised(self):
        result = self.pull(http=FixtureHttp(fail={"sina", "tencent"}))
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertFalse(check["sources_min"]["ok"])
        self.assertLess(result["self_check"]["score"], 100)
        self.assertFalse(result["self_check"]["ok"])

    def test_low_symbol_coverage_penalised(self):
        http = FixtureHttp(prices={"^HSI": PRICES["^HSI"]}, prev={"^HSI": PREV["^HSI"]})
        result = m.pull("1230", root=self.root, http=http, now=DAY1,
                        symbols=SYMBOLS, verbose=False)      # 只有 1 只标的能取到
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertFalse(check["symbol_coverage"]["ok"])

    def test_numeric_sanity_flags_wild_change(self):
        bad_prev = {"^HSI": PRICES["^HSI"] / 1.6, "0700.HK": PREV["0700.HK"],
                    "000001.SS": PREV["000001.SS"], "MSFT": PREV["MSFT"]}
        result = self.pull(http=FixtureHttp(prev=bad_prev))
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertFalse(check["numeric_sanity"]["ok"])

    def test_slot_jump_alert_across_slots(self):
        self.pull(slot="0800", now=DAY1, http=FixtureHttp())
        jumped = {k: v * 1.2 for k, v in PRICES.items()}
        result = self.pull(slot="1230", now=DAY1,
                           http=FixtureHttp(prices=jumped, prev=PRICES))
        alerts = " ".join(result["self_check"]["alerts"])
        self.assertIn("跨时段跳变", alerts)

    def test_weekend_freshness_not_penalised(self):
        result = self.pull(now=SATURDAY)
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertTrue(check["freshness"]["ok"])            # 休市不算缺陷
        self.assertTrue(check["freshness"]["warn_only"])
        self.assertIn("非交易日", check["freshness"]["detail"])
        self.assertFalse(result["doc"]["slots"]["0800"]["trading_day"])

    def test_stale_quotes_alert_on_trading_day(self):
        # 行情时间停在昨天：节假日 / 盘前都会出现隔夜价，因此只亮灯扣分、不判「缺陷」
        stale = FixtureHttp(when=datetime(2026, 9, 30, 12, 0, tzinfo=CST))
        result = self.pull(http=stale)
        check = {c["name"]: c for c in result["self_check"]["checks"]}
        self.assertFalse(check["freshness"]["ok"])
        self.assertTrue(check["freshness"]["warn_only"])
        self.assertIn("可能休市或源延迟", check["freshness"]["detail"])
        self.assertLess(result["self_check"]["score"], 100)
        self.assertTrue(any("freshness" in a for a in result["self_check"]["alerts"]))
        self.assertTrue(result["doc"]["slots"]["0800"]["trading_day"])


# ======================================================================
# ⑤ 落库 / 文件 / 哈希
# ======================================================================
class DatabaseFileTests(TempRootCase):
    def test_file_named_by_date_and_three_slots_merged(self):
        for slot, moment in (("0800", DAY1), ("1230", DAY1),
                             ("1700", DAY1.replace(hour=17, minute=0))):
            self.pull(slot=slot, now=moment)
        path = os.path.join(self.root, "20261001.json")
        self.assertTrue(os.path.isfile(path))
        doc = json.load(open(path, encoding="utf-8"))
        self.assertEqual(list(doc["slots"]), ["0800", "1230", "1700"])
        self.assertEqual(doc["schema"], m.SCHEMA)
        self.assertEqual(doc["audit"]["pull_count"], 3)
        self.assertEqual(doc["ai"]["slots_present"], ["0800", "1230", "1700"])
        self.assertGreater(doc["ai"]["row_count"], 0)

    def test_repull_same_slot_overwrites_and_audits(self):
        self.pull(slot="1230", now=DAY1)
        self.pull(slot="1230", now=DAY1.replace(minute=31))
        doc = json.load(open(os.path.join(self.root, "20261001.json"), encoding="utf-8"))
        self.assertEqual(list(doc["slots"]), ["1230"])
        self.assertEqual(doc["audit"]["pull_count"], 2)
        self.assertFalse(doc["audit"]["pulls"][0]["overwrote"])
        self.assertTrue(doc["audit"]["pulls"][1]["overwrote"])

    def test_all_sources_failed_writes_nothing(self):
        http = FixtureHttp(fail={"eastmoney", "sina", "tencent", "yahoo", "em_kline"})
        result = m.pull("1230", root=self.root, http=http, now=DAY1, symbols=SYMBOLS, verbose=False)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["written"])
        self.assertEqual(os.listdir(self.root), [])

    def test_dry_run_writes_nothing(self):
        result = self.pull(dry_run=True)
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(os.listdir(self.root), [])

    def test_integrity_detects_tampering(self):
        self.pull()
        path = os.path.join(self.root, "20261001.json")
        self.assertTrue(m.verify(self.root, all_days=True, verbose=False)["ok"])
        doc = json.load(open(path, encoding="utf-8"))
        doc["slots"]["0800"]["quotes"]["^HSI"]["price"] = 1.234     # 手工改价
        json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        report = m.verify(self.root, all_days=True, verbose=False)
        self.assertFalse(report["ok"])
        self.assertTrue(any("哈希" in p for p in report["problems"]))

    def test_verify_reports_missing_slots(self):
        self.pull(slot="1230", now=DAY1)
        report = m.verify(self.root, all_days=True, verbose=False)
        self.assertTrue(any("缺 2 档" in a for a in report["alerts"]))

    def test_prune_keeps_recent_days(self):
        for offset in range(3):
            day = DAY1 - timedelta(days=offset)
            m.pull("1230", root=self.root, http=FixtureHttp(when=day), now=day,
                   symbols=SYMBOLS, verbose=False)
        self.assertEqual(len(m.load_days(self.root)), 3)
        info = m.prune(self.root, 2, verbose=False)
        self.assertEqual(len(info["removed"]), 1)
        self.assertEqual(len(m.load_days(self.root)), 2)


# ======================================================================
# ⑥ AI 数据集（特征因果 / 标签前瞻 / 导出 / 上下文）
# ======================================================================
class DatasetTests(TempRootCase):
    def _build_days(self, days=3):
        """逐日逐档落库（与线上一致：每次都合并进当天文件）。"""
        price = dict(PRICES)
        for day_index in range(days):
            for slot, hour, minute in (("0800", 8, 1), ("1230", 12, 31), ("1700", 17, 1)):
                moment = DAY1 + timedelta(days=day_index, hours=hour - 8, minutes=minute - 12)
                prev = {k: v for k, v in price.items()}
                price = {k: round(v * (1 + 0.01 * (day_index + 1) * 0.1), 4) for k, v in price.items()}
                http = FixtureHttp(prices=price, prev=prev, when=moment)
                m.pull(slot, root=self.root, http=http, now=moment,
                       symbols=SYMBOLS, verbose=False)

    def test_feature_truncation_invariance(self):
        """截断未来数据不改变过去行情的特征（无未来函数）。"""
        self._build_days(3)
        docs = m.load_days(self.root)
        full, _meta = m.build_dataset(docs=docs)
        cut, _meta2 = m.build_dataset(docs=docs[:-1])            # 去掉最后一天
        by_key = {(r["date"], r["slot"], r["symbol"]): r for r in full}
        for row in cut:
            key = (row["date"], row["slot"], row["symbol"])
            self.assertIn(key, by_key)
            self.assertEqual(row["features"], by_key[key]["features"])

    def test_labels_only_from_later_snapshots(self):
        self._build_days(2)
        rows, meta = m.build_dataset(root=self.root)
        self.assertEqual(len(meta["dates"]), 2)
        last = [r for r in rows if r["date"] == "2026-10-02" and r["slot"] == "1700"]
        self.assertTrue(last)
        for row in last:                                          # 最后一档没有任何后续数据
            self.assertIsNone(row["labels"]["next_slot_ret"])
            self.assertIsNone(row["labels"]["eod_ret"])
        first = next(r for r in rows if r["date"] == "2026-10-01" and r["slot"] == "0800"
                     and r["symbol"] == "^HSI")
        self.assertIsNotNone(first["labels"]["next_slot_ret"])
        self.assertIsNotNone(first["labels"]["eod_ret"])
        self.assertIsNotNone(first["labels"]["next_day_eod_ret"])
        self.assertEqual(first["features"]["ret_day_open"], 0.0)
        self.assertIsNone(first["features"]["ret_prev_slot"])       # 当天第一档没有前档

    def test_export_jsonl_and_csv(self):
        self._build_days(1)
        self.assertTrue(m.load_days(self.root))
        jsonl = os.path.join(self.root, "ai.jsonl")
        csv_path = os.path.join(self.root, "ai.csv")
        info = m.export_dataset(jsonl, fmt="jsonl", root=self.root)
        self.assertGreater(info["rows"], 0)
        first = json.loads(open(jsonl, encoding="utf-8").readline())
        self.assertIn("features", first)
        self.assertIn("labels", first)
        m.export_dataset(csv_path, fmt="csv", root=self.root)
        header = open(csv_path, encoding="utf-8").readline().strip()
        self.assertIn("f_price", header)
        self.assertIn("y_eod_ret", header)

    def test_ai_context_quality_flags(self):
        self._build_days(1)
        last_slot = DAY1.replace(hour=16, minute=49, second=12)
        ctx = m.ai_context(root=self.root, symbols=["^HSI"], now=last_slot)
        self.assertTrue(ctx["available"])
        self.assertEqual(list(ctx["quotes"]), ["^HSI"])
        self.assertEqual(ctx["self_check_score"], 100)
        self.assertFalse(ctx["stale"])
        self.assertEqual(ctx["sources_ok"], 5)
        later = m.ai_context(root=self.root, now=last_slot + timedelta(days=2))
        self.assertTrue(later["stale"])                     # 超过 max_age_hours 默认 18 小时
        self.assertEqual(m.load_days(self.root)[0]["date_compact"], "20261001")

    def test_empty_db_context_is_unavailable(self):
        ctx = m.ai_context(root=self.root)
        self.assertFalse(ctx["available"])
        self.assertTrue(ctx["reason"])


# ======================================================================
# ⑦ CLI 与 pipeline 隐藏入口
# ======================================================================
class CliTests(TempRootCase):
    def test_cli_pull_verify_stats_export_ai_context(self):
        rc = m.main(["pull", "--slot", "1230"], http=FixtureHttp(), root=self.root,
                    now=DAY1.replace(hour=12, minute=30, second=12))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "20261001.json")))
        self.assertEqual(m.main(["verify", "--all"], root=self.root), 0)
        self.assertEqual(m.main(["stats", "--days", "3"], root=self.root), 0)
        out = os.path.join(self.root, "dataset.jsonl")
        self.assertEqual(m.main(["export", "--out", out], root=self.root), 0)
        self.assertTrue(os.path.getsize(out) > 0)
        self.assertEqual(m.main(["ai-context"], root=self.root), 0)

    def test_cli_pull_returns_one_when_everything_fails(self):
        http = FixtureHttp(fail={"eastmoney", "sina", "tencent", "yahoo", "em_kline"})
        rc = m.main(["pull"], http=http, root=self.root, now=DAY1)
        self.assertEqual(rc, 1)

    def test_unknown_slot_rejected(self):
        with self.assertRaises(SystemExit):
            m.pull("9999", root=self.root, http=FixtureHttp(), now=DAY1, verbose=False)


class PipelineHiddenEntryTests(unittest.TestCase):
    """隐藏入口：--help 不显示 --stock-db，但参数本身可用。"""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "pipeline_under_market_db_test", os.path.join(OUTPUT_DIR, "pipeline.py"))
        cls.pipeline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.pipeline)

    def _run(self, argv):
        old = sys.argv
        sys.argv = ["pipeline.py", *argv]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = self.pipeline.main()
        except SystemExit as exc:                     # --help 走 argparse 的退出
            rc = exc.code
        finally:
            sys.argv = old
        return rc, buf.getvalue()

    def test_help_does_not_advertise_hidden_feature(self):
        rc, out = self._run(["--help"])
        self.assertEqual(rc, 0)
        self.assertNotIn("stock-db", out)
        self.assertNotIn("market_db", out)
        self.assertIn("--sources", out)               # 正常参数仍在

    def test_hidden_flag_is_still_usable(self):
        rc, out = self._run(["--stock-db", "stats", "--stock-db-days", "1"])
        self.assertEqual(rc, 0)
        self.assertIn("市场数据库", out)


if __name__ == "__main__":
    unittest.main()
