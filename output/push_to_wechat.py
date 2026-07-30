#!/usr/bin/env python3
"""PushPlus 微信推送脚本"""
import json
import urllib.request

TOKEN = "507a6c0cf9cf46229f5f3c5107a967cc"
TITLE = "🐙 章鱼AI·全景分析 | 2026年7月30日"

# 读取HTML内容
with open("/home/user/02/output/daily_report_20260730.html", "r", encoding="utf-8") as f:
    content = f.read()

# 构建请求
payload = {
    "token": TOKEN,
    "title": TITLE,
    "content": content,
    "template": "html",
    "channel": "wechat"
}

data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(
    "https://www.pushplus.plus/send",
    data=data,
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
        print("✅ PushPlus 返回:", json.dumps(result, ensure_ascii=False, indent=2))
except Exception as e:
    print(f"❌ 推送失败: {e}")
    # 尝试打印更多信息
    import traceback
    traceback.print_exc()
