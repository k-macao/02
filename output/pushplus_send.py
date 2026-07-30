#!/usr/bin/env python3
"""
🐙 章鱼 AI · 全景分析 · PushPlus 推送脚本
在本地环境运行此脚本，将日报推送到微信。

使用方法：
  python3 pushplus_send.py
  或
  pip install requests && python3 pushplus_send.py
"""
import json
import sys

# ========== 配置 ==========
PUSHPUS_TOKEN = "507a6c0cf9cf46229f5f3c5107a967cc"
TITLE = "🐙 章鱼AI·全景分析 | 2026年7月30日"
HTML_FILE = "output/daily_report_20260730.html"  # 相对于脚本目录
# ==========================

import os
script_dir = os.path.dirname(os.path.abspath(__file__))
html_path = os.path.join(script_dir, HTML_FILE)

try:
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    print(f"✅ 已读取 HTML 文件: {html_path} ({len(content)} 字符)")
except FileNotFoundError:
    print(f"❌ 找不到文件: {html_path}")
    sys.exit(1)

payload = {
    "token": PUSHPUS_TOKEN,
    "title": TITLE,
    "content": content,
    "template": "html",
    "channel": "wechat"
}

# 尝试用 requests 库，否则用 urllib
try:
    import requests
    resp = requests.post("https://www.pushplus.plus/send", json=payload, timeout=30)
    result = resp.json()
    print("📤 PushPlus 返回:", json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("code") == 200:
        print("🎉 推送成功！请查看微信消息。")
    else:
        print(f"⚠️ 推送返回非预期状态: {result}")
except ImportError:
    import urllib.request
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print("📤 PushPlus 返回:", json.dumps(result, ensure_ascii=False, indent=2))
            if result.get("code") == 200:
                print("🎉 推送成功！请查看微信消息。")
    except Exception as e:
        print(f"❌ 推送失败: {e}")
        print("💡 请确认网络可访问 pushplus.plus，并检查 token 是否有效。")
