"""超长日报「尽量合并」分条推送 + PushPlus 频率排队的离线回归测试（不发 HTTP 请求）。

覆盖：
  - 栏目头 / 正文锚点解析（_section_title_text / _split_section_units）；
  - 顺序装箱（_pack_section_units）：整栏装箱、切栏续接、碎片保护、条数取最小；
  - 整页拆分（_split_html_for_push）：每条 ≤ 单条上限、外壳与页脚齐全、标签平衡、
    正文一个字不丢、横幅如实标注「承接上条（续）」「本条未完」；
  - PushPlus「1 分钟 N 次请求」排队（_push_rate_wait / _wait_push_rate_limit）。
"""
import importlib.util
import re
import sys
import types
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

# pipeline 在导入时只需要 requests 存在；本测试不发出 HTTP 请求。
sys.modules.setdefault("requests", types.SimpleNamespace())
MODULE_PATH = Path(__file__).parents[1] / "output" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_push_split_under_test", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)

_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
              "meta", "param", "source", "track", "wbr", "rect", "line", "circle",
              "path", "polyline", "polygon", "ellipse"}
_TITLE_RE = re.compile(r"(<title>)(.*?)(</title>)", re.S)
_BANNER_RE = re.compile(r"<table[^>]*>.*?已尽量合并推送.*?</table>", re.S)
_SHELL = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
          '<meta name="octopus-theme" content="guizang"><title>测试日报</title>'
          '</head><body><table><tr><td>')          # 外层容器故意不闭合，由页脚闭合
_TAIL = "</td></tr></table></body></html>"


def _text(html):
    """去注释、去标签、去空白后的纯文本（用于「内容一个字不丢」比对）。"""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html))


class _BalanceChecker(HTMLParser):
    """检查 HTML 标签是否自闭合平衡（错配的标签记进 bad）。"""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.bad = []

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.bad.append(tag)


def _balanced(html):
    checker = _BalanceChecker()
    checker.feed(html)
    return checker.stack == [] and checker.bad == []


def _mk_unit(title, body_html, accent="行情速览"):
    """造一个 (栏目头, 栏目名, 正文) 单元：栏目头带标题，正文是已平衡的 HTML。"""
    header = pipeline.gz_section("01", "market", accent, "").split(
        pipeline.SECTION_BODY_MARK)[0]
    header = header.replace(f">{pipeline._esc(accent)}</h2>", f">{pipeline._esc(title)}</h2>")
    return header, title, pipeline.gz_shell(body_html, pad="0 0 32px")


def _section(num, title, body, accent="行情速览"):
    """按 guizang 主题造一个完整栏目（栏目头 + <!--BODY--> + 正文）。"""
    header, _, content = _mk_unit(title, body, accent=accent)
    return header + pipeline.SECTION_BODY_MARK + content


def _report(sections):
    body = pipeline.PART_BREAK_MARK + pipeline.PART_BREAK_MARK.join(sections)
    return _SHELL + body + "\n" + pipeline.DOC_FOOT_MARK + _TAIL


class SectionUnitTests(unittest.TestCase):
    """栏目头 / 正文锚点的解析。"""

    def test_guizang_section_title_is_extracted(self):
        head = pipeline.gz_section("01", "market", "行情速览", "正文").split(
            pipeline.SECTION_BODY_MARK)[0]
        self.assertEqual(pipeline._section_title_text(head), "行情速览")

    def test_pixel_section_title_is_extracted(self):
        head = pipeline._section("01", "行情速览", "港股名家频道", "正文").split(
            pipeline.SECTION_BODY_MARK)[0]
        self.assertEqual(pipeline._section_title_text(head), "港股名家频道")

    def test_long_title_is_shortened_for_banner(self):
        head = pipeline.gz_section("01", "market", "甲" * 60, "正文").split(
            pipeline.SECTION_BODY_MARK)[0]
        title = pipeline._section_title_text(head)
        self.assertTrue(title.endswith("…"))
        self.assertLessEqual(len(title), 29)

    def test_legacy_section_without_anchor_keeps_whole_html(self):
        units = pipeline._split_section_units(["<div>老版栏目</div>"])
        self.assertEqual(units, [("", "", "<div>老版栏目</div>")])

    def test_section_is_split_into_header_and_body(self):
        units = pipeline._split_section_units([_section("01", "行情速览", "<p>甲</p>")])
        header, title, content = units[0]
        self.assertEqual(title, "行情速览")
        self.assertTrue(header.endswith("</td></tr></table>"))
        self.assertTrue(content.startswith("<table"))
        self.assertNotIn(pipeline.SECTION_BODY_MARK, header + content)


class PackSectionUnitsTests(unittest.TestCase):
    """顺序装箱：条数取最小，但绝不切出碎片条。"""

    def test_whole_sections_share_one_part_when_they_fit(self):
        units = [_mk_unit("甲栏", "<p>" + "甲" * 300 + "</p>"),
                 _mk_unit("乙栏", "<p>" + "乙" * 300 + "</p>")]
        budget = sum(len(header + content) for header, _, content in units) + 10
        chunks, titles = pipeline._pack_section_units(units, budget)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(titles, [""])
        self.assertLessEqual(len(chunks[0]), budget)
        self.assertIn("甲栏", _text(chunks[0]))
        self.assertIn("乙栏", _text(chunks[0]))

    def test_section_is_cut_to_fill_current_part_and_continued(self):
        # 第一栏很小、第二栏很长：第二栏应被切开填满第一条，续片重开栏目头
        units = [_mk_unit("第一栏", "<p>" + "甲" * 400 + "</p>"),
                 _mk_unit("第二栏", "<p>" + "乙" * 6000 + "</p>")]
        budget = len(units[0][0] + units[0][2]) + 3000
        chunks, titles = pipeline._pack_section_units(units, budget, min_split=500)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(titles[0], "")
        self.assertEqual(titles[1], "第二栏")
        self.assertTrue(chunks[1].startswith(units[1][0]))
        for chunk in chunks[:-1]:
            self.assertLessEqual(len(chunk), budget)
            self.assertGreater(len(chunk), budget - 400)   # 每条都填满，不浪费额度
        self.assertEqual(_text("".join(chunks)).count("乙"), 6000)   # 一个字不丢

    def test_tiny_leftover_moves_whole_section_to_next_part(self):
        units = [_mk_unit("第一栏", "<p>" + "甲" * 400 + "</p>"),
                 _mk_unit("第二栏", "<p>" + "乙" * 400 + "</p>")]
        budget = len(units[0][0] + units[0][2]) + 200      # 剩余空间 < min_split
        chunks, titles = pipeline._pack_section_units(units, budget, min_split=1500)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(titles, ["", ""])
        self.assertEqual(_text(chunks[0]).count("乙"), 0)   # 不切出碎片条
        self.assertEqual(_text(chunks[1]).count("乙"), 400)

    def test_long_unbreakable_text_is_cut_at_text_boundary(self):
        # 一整段没有任何标签的长正文：退一步切在正文中间，仍能合并、且不丢字
        units = [_mk_unit("第一栏", "乙" * 9000)]
        chunks, titles = pipeline._pack_section_units(units, 4000, min_split=500)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 4000)
        self.assertEqual(_text("".join(chunks)).count("乙"), 9000)      # 一个字不丢
        self.assertGreaterEqual(_text("".join(chunks)).count("第一栏"), 1)  # 栏目头仍在

    def test_every_piece_is_tag_balanced(self):
        units = [_mk_unit("甲栏", "<table><tr><td>" + "甲" * 5000 + "</td></tr></table>"),
                 _mk_unit("乙栏", "<table><tr><td>" + "乙" * 5000 + "</td></tr></table>")]
        chunks, _ = pipeline._pack_section_units(units, 3000, min_split=500)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertTrue(_balanced(chunk), chunk[:120])


class SplitHtmlForPushTests(unittest.TestCase):
    """整页拆分：合并到最少条数，同时保证每条都是完整、标签平衡、内容不丢的 HTML。"""

    def _split(self, html, limit, **kwargs):
        parts = pipeline._split_html_for_push(html, limit, "fake.html", **kwargs)
        self.assertIsNotNone(parts)
        return parts

    def _chunks(self, html, parts):
        """按拆分器自己的规则还原每条正文（去掉外壳、横幅、页脚）。"""
        first = html.find(pipeline.PART_BREAK_MARK)
        foot = html.find(pipeline.DOC_FOOT_MARK)
        shell = html[:first]
        tail = html[foot + len(pipeline.DOC_FOOT_MARK):]
        chunks = []
        for index, part in enumerate(parts, 1):
            head = _TITLE_RE.sub(
                lambda m: f"{m.group(1)}{m.group(2)}（第 {index}/{len(parts)} 条）{m.group(3)}",
                shell, count=1)
            self.assertTrue(part.startswith(head), "每条都要带完整刊头")
            self.assertTrue(part.endswith(tail), "每条都要带页脚与闭合标签")
            inner = part[len(head):len(part) - len(tail)]
            banner = _BANNER_RE.search(inner)
            self.assertIsNotNone(banner, "每条都要有条序横幅")
            chunks.append(inner[banner.end():])
        return chunks

    def test_parts_never_exceed_limit_and_keep_every_character(self):
        sections = [_section("00", "全篇速览", "<p>" + "甲" * 4000 + "</p>"),
                    _section("01", "行情速览", "<p>" + "乙" * 9000 + "</p>"),
                    _section("02", "全球头条", "<p>" + "丙" * 3000 + "</p>")]
        html = _report(sections)
        parts = self._split(html, 6000)
        for part in parts:
            self.assertLessEqual(len(part), 6000)
            self.assertTrue(_balanced(part))
        chunks = self._chunks(html, parts)
        merged = _text("".join(chunks))
        # 每个栏目名都要出现（续片重开栏目头时会出现多次，缺失则说明内容被丢了）
        for title in ("全篇速览", "行情速览", "全球头条"):
            self.assertIn(title, merged)
        # 正文一个字符不丢：三段正文的字符数完全一致
        original = _text(html[html.find(pipeline.PART_BREAK_MARK):
                              html.find(pipeline.DOC_FOOT_MARK)])
        for filler in "甲乙丙":
            self.assertEqual(merged.count(filler), original.count(filler))

    def test_every_part_but_the_last_is_filled_to_the_limit(self):
        # 三栏各 ~9000 字：必须切栏续接，而不是「一栏一条」白多推几条
        sections = [_section(f"0{i}", f"栏目{i}", "<p>" + "甲" * 9000 + "</p>")
                    for i in range(3)]
        html = _report(sections)
        parts = self._split(html, 22000)
        for part in parts[:-1]:
            self.assertGreater(len(part), 22000 * 0.9)

    def test_merging_uses_fewer_parts_than_whole_section_packing(self):
        # 同一条日报：允许栏目内续接时，条数必须比「整栏装箱」少（这正是「尽量合并」）
        sections = [_section(f"0{i}", f"栏目{i}", "<p>" + "甲" * 4000 + "</p>")
                    for i in range(3)]
        html = _report(sections)
        limit = int(len(sections[0]) * 1.8)      # 一条装得下 1 栏多一点，装不下 2 整栏
        merged = self._split(html, limit)
        with patch.object(pipeline, "PUSHPLUS_SPLIT_MIN_BODY", 10 ** 9):   # 只允许整栏装箱
            packed = self._split(html, limit)
        self.assertLess(len(merged), len(packed))
        for part in merged + packed:
            self.assertLessEqual(len(part), limit)

    def test_banners_tell_reader_where_the_section_continues(self):
        sections = [_section("00", "行情速览", "<p>" + "甲" * 6000 + "</p>"),
                    _section("01", "全球头条", "<p>" + "乙" * 6000 + "</p>")]
        html = _report(sections)
        parts = self._split(html, 4000)
        self.assertGreater(len(parts), 1)
        self.assertNotIn("承接上条", parts[0])
        self.assertIn("本条未完", parts[0])
        self.assertIn("承接上条「行情速览」（续）", parts[1])
        self.assertIn("承接上条", parts[-1])

    def test_legacy_report_without_body_anchor_still_merges(self):
        # 旧版日报没有 <!--BODY-->：续片不带栏目头，但同样按上限填满、内容不丢
        sections = ["<div>" + "旧" * 5000 + "</div>", "<div>" + "版" * 5000 + "</div>"]
        html = _report(sections)
        parts = self._split(html, 4000)
        for part in parts:
            self.assertLessEqual(len(part), 4000)
            self.assertTrue(_balanced(part))
        chunks = self._chunks(html, parts)
        self.assertEqual(_text("".join(chunks)), _text("".join(sections)))

    def test_report_without_anchors_returns_none(self):
        self.assertIsNone(pipeline._split_html_for_push("<html>" + "字" * 500 + "</html>", 100))

    def test_tail_cut_keeps_honest_banner_when_max_parts_exceeded(self):
        sections = [_section(f"0{i}", f"栏目{i}", "<p>" + "甲" * 2000 + "</p>")
                    for i in range(4)]
        html = _report(sections)
        parts = self._split(html, 6000, max_parts=2)
        self.assertEqual(len(parts), 2)
        self.assertIn("已达单次推送条数上限", parts[-1])
        self.assertIn("完整日报", parts[-1])


class PushRateLimitTests(unittest.TestCase):
    """PushPlus 频率限制排队：窗口内请求数达上限时先等待，再放行。"""

    class _Clock:
        def __init__(self):
            self.now = 0.0
            self.slept = []

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.slept.append(seconds)
            self.now += seconds

    def setUp(self):
        pipeline._PUSH_REQUEST_TIMES.clear()

    def tearDown(self):
        pipeline._PUSH_REQUEST_TIMES.clear()

    def test_wait_is_zero_below_limit(self):
        self.assertEqual(pipeline._push_rate_wait([0.0, 1.0], 2.0, window=60, limit=5), 0.0)

    def test_wait_until_oldest_request_leaves_the_window(self):
        history = [0.0, 1.0, 2.0, 3.0, 4.0]
        self.assertAlmostEqual(
            pipeline._push_rate_wait(history, 10.0, window=60, limit=5), 50.0)

    def test_sixth_request_waits_for_the_window(self):
        clock = self._Clock()
        with patch.object(pipeline.time, "monotonic", clock.monotonic), \
                patch.object(pipeline.time, "sleep", clock.sleep), \
                patch.object(pipeline, "PUSHPLUS_RATE_WINDOW", 60.0), \
                patch.object(pipeline, "PUSHPLUS_RATE_MAX", 5):
            for _ in range(6):
                pipeline._wait_push_rate_limit()
        self.assertEqual(len(clock.slept), 1)
        self.assertAlmostEqual(clock.slept[0], 60.0, places=6)
        # 窗口滑过后早期请求已被清理，只剩最新一次请求在队列里
        self.assertEqual(len(pipeline._PUSH_REQUEST_TIMES), 1)

    def test_pacing_can_be_disabled(self):
        clock = self._Clock()
        with patch.object(pipeline.time, "monotonic", clock.monotonic), \
                patch.object(pipeline.time, "sleep", clock.sleep), \
                patch.object(pipeline, "PUSHPLUS_RATE_MAX", 0):
            for _ in range(20):
                pipeline._wait_push_rate_limit()
        self.assertEqual(clock.slept, [])


if __name__ == "__main__":
    unittest.main()
