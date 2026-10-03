"""栏目内段落灰底交替（_gz_zebra_bands / gz_section）回归测试。

2026-09-30 需求：栏目内部的相邻内容块（小节标题+首块 / 资讯卡片 / 表格 /
脚注 / 提示）按 纯白 ↔ 浅灰 #F2F2F2 两档背景交替铺底，读视线跟着色带走。
"""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

sys.modules.setdefault("requests", types.SimpleNamespace())
MODULE_PATH = Path(__file__).parents[1] / "output" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline_under_test_zebra", MODULE_PATH)
pipeline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pipeline)
# 本文件只测版面交替，用 gz_note 当通用内容块；入门版（默认）下 gz_note 不输出说明文字，
# 这里固定打开 --notes 语义，让脚注块照常生成。
pipeline.set_notes_requested(True)

ZEBRA = pipeline.GZ_ZEBRA
WRAP_OPEN = f'<div style="background:{ZEBRA};padding:4px 8px;margin:2px 0;">'


def top_level_chunks(html):
    """把内容串拆回顶层块序列，便于断言交替顺序。"""
    return [html[a:b] for a, b in pipeline._gz_top_level_spans(html)]


class ZebraBandTests(unittest.TestCase):
    def test_alternates_white_and_gray_per_top_level_block(self):
        content = "".join(pipeline.gz_note(f"块{i}") for i in (1, 2, 3, 4))
        banded = pipeline._gz_zebra_bands(content)
        # 奇数带（第 2、4 块）铺灰，偶数带（第 1、3 块）保持纯白原样
        self.assertIn(WRAP_OPEN + pipeline.gz_note("块2") + "</div>", banded)
        self.assertIn(WRAP_OPEN + pipeline.gz_note("块4") + "</div>", banded)
        self.assertEqual(banded.count(f"background:{ZEBRA}"), 2)
        self.assertNotIn(WRAP_OPEN + pipeline.gz_note("块1"), banded)
        self.assertNotIn(WRAP_OPEN + pipeline.gz_note("块3"), banded)

    def test_no_content_loss_and_order_preserved(self):
        content = (
            pipeline.gz_note("脚注甲")
            + "<!--BODY-->"  # 推进标记：不计块、也不许丢
            + pipeline.gz_subsection("子节标题")
            + pipeline.gz_data_table(["A", "B"], [["1", "2"]])
            + pipeline.gz_note("脚注乙")
            + "\n"
        )
        banded = pipeline._gz_zebra_bands(content)
        for token in ("脚注甲", "<!--BODY-->", "子节标题", "脚注乙", "<table", "</table>"):
            self.assertIn(token, banded)
        # 剥掉灰底包装层后，应还原出全部原始块（顺序不变）
        stripped = banded.replace(WRAP_OPEN, "").replace("</div>" + pipeline.gz_note("脚注乙"),
                                                         pipeline.gz_note("脚注乙"))
        for token in ("脚注甲", "子节标题", "脚注乙"):
            self.assertIn(token, stripped)

    def test_subsection_heading_joins_following_block(self):
        content = (
            pipeline.gz_note("引子")
            + pipeline.gz_subsection("风险预算")
            + pipeline.gz_data_table(["指标", "值"], [["预算", "10%"]])
        )
        banded = pipeline._gz_zebra_bands(content)
        # 第 0 带 = 引子（白），第 1 带 = 子节标题 + 表格（同一层灰底）
        head_at = banded.index("风险预算")
        wrap_open = banded.rfind(WRAP_OPEN, 0, head_at)
        self.assertGreater(wrap_open, banded.index("引子</div>"))
        table_at = banded.index("<table", head_at)
        wrap_close = banded.index("</div>", table_at)
        # 标题与表格之间不得再出现灰底开标签（同带）；带内 = 包装层 + 子标题，恰好 2 个 <div>
        self.assertEqual(banded.count("<div", wrap_open, wrap_close), 2)

    def test_news_cards_are_individually_banded(self):
        cards = "".join(pipeline.gz_item_row("◆", f"条目{i}") for i in range(3))
        banded = pipeline._gz_zebra_bands(cards)
        self.assertEqual(banded.count(f"background:{ZEBRA}"), 1)  # 仅第 2 张卡铺灰
        self.assertIn(WRAP_OPEN + pipeline.gz_item_row("◆", "条目1") + "</div>", banded)

    def test_single_block_and_plain_table_body_untouched(self):
        lone = pipeline.gz_note("唯一一块")
        self.assertEqual(pipeline._gz_zebra_bands(lone), lone)
        trs = "<tr><td>甲</td></tr><tr><td>乙</td></tr>"
        # <tr> 开头的内容在 gz_section 里先合成整表，再整块跳过交替（不许把 <tr> 包进 div）
        section = pipeline.gz_section("01", "TEST", "标题", trs)
        self.assertIn("<table", section)
        self.assertNotIn(f'<div style="background:{ZEBRA}', section)

    def test_banding_covers_full_report_and_stays_inline_only(self):
        data = {
            "全球头条": pipeline._source_result(
                "test news", "success",
                headlines=[{"title": f"头条{i}", "source": "测试源",
                            "published_cst": f"2026-09-30 10:0{i}"} for i in range(4)]),
        }
        html = pipeline.generate_report(data, "2026年9月30日 · 周三", "20260930",
                                        theme="guizang")
        self.assertIn(f"background:{ZEBRA}", html)
        # 纯内联样式：不引入 <style> / class（微信 PushPlus 清洗安全）
        self.assertNotIn("<style", html)
        self.assertNotIn('class="', html)
        # 标签守恒：灰底包裹不破坏 div 配对
        self.assertEqual(html.count("<div"), html.count("</div>"))


if __name__ == "__main__":
    unittest.main()
