#!/usr/bin/env python3
"""本地预览：把 日报排版示例.html 作为首页展示（仅开发用）。"""
import http.server
import os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
SAMPLE = os.path.join(ROOT, "日报排版示例.html")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/日报排版示例.html"
        return super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    http.server.HTTPServer(("0.0.0.0", 8900), Handler).serve_forever()
