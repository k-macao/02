#!/usr/bin/env python3
"""行业轮动数据源探测页的本地服务（开发/核查用，不参与推送）。

- `/`                → 探测页（output/diag/sector_rotation_probe.html）；
                       页面在浏览器里用 JSONP 直连东方财富（沙箱出口访问不到该域名，
                       借用户浏览器取证），并把结果 POST 回本站；
- `POST /collect`    → 把浏览器探测结果写入 output/diag/probe_from_browser.json；
- `/result`          → 以 JSON 返回最近一次浏览器探测结果（便于核查）。

用法：
    python3 output/probe_server.py            # 默认 0.0.0.0:8901
    PORT=8902 python3 output/probe_server.py
"""
import http.server
import json
import os
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(ROOT, "diag", "sector_rotation_probe.html")
RESULT = os.path.join(ROOT, "diag", "probe_from_browser.json")
MAX_BODY = 512 * 1024


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_html(self, code, body):
        self._send(code, body, ctype="text/html; charset=utf-8")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            if not os.path.isfile(PAGE):
                self._send_html(404, b"<meta charset='utf-8'>probe page missing")
                return
            with open(PAGE, "rb") as f:
                self._send_html(200, f.read())
            return
        if path == "/result":
            if os.path.isfile(RESULT):
                with open(RESULT, "rb") as f:
                    self._send(200, f.read())
            else:
                self._send(200, b'{"note": "no browser probe result yet"}')
            return
        self._send(404, b'{"error": "not found"}')

    def do_HEAD(self):
        self._send(204, b"")

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/collect":
            self._send(404, b'{"error": "not found"}')
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length > MAX_BODY:
            self._send(413, b'{"error": "payload too large"}')
            return
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send(400, b'{"error": "invalid json"}')
            return
        os.makedirs(os.path.dirname(RESULT), exist_ok=True)
        temp = RESULT + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(temp, RESULT)
        print("📥 已收到浏览器探测结果 → " + RESULT, flush=True)
        self._send(204, b"")

    def log_message(self, fmt, *args):          # 精简访问日志
        print("%s - %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8901"))
    print(f"🔎 行业轮动探测页: http://0.0.0.0:{port}/  （结果: /result）", flush=True)
    http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
