"""无需网络的日报新鲜度回归测试。"""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
