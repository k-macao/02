#!/usr/bin/env python3
"""
🐙 章鱼 AI · PushPlus 自动推送脚本

功能：
  1. 自动扫描 output/ 目录下最新的日报 HTML
  2. 通过 PushPlus 推送到微信
  3. 支持指定文件、Token、标题

用法：
  python3 push.py                          # 推送最新的日报
  python3 push.py -f output/xxx.html       # 推送指定文件
  python3 push.py -t "自定义标题"          # 自定义标题
  python3 push.py --list                   # 列出所有可推送文件

环境变量：
  PUSHPUS_TOKEN     PushPlus token（可选，默认使用内置 token）
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

# ============ 默认配置 ============
DEFAULT_TOKEN = "507a6c0cf9cf46229f5f3c5107a967cc"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))  # push.py 就在 output/ 里
# ==================================

CST = timezone(timedelta(hours=8))  # 中国标准时间


def find_latest_html(directory: str) -> str | None:
    """在目录中找最新的 daily_report_*.html"""
    pattern = os.path.join(directory, "daily_report_*.html")
    candidates = sorted(glob.glob(pattern), reverse=True)
    return candidates[0] if candidates else None


def list_all_html(directory: str) -> list[str]:
    """列出所有日报 HTML"""
    pattern = os.path.join(directory, "daily_report_*.html")
    return sorted(glob.glob(pattern), reverse=True)


def extract_date_from_filename(path: str) -> str:
    """从文件名提取日期 YYYY-MM-DD"""
    m = re.search(r"(\d{4})(\d{2})(\d{2})", os.path.basename(path))
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return datetime.now(CST).strftime("%Y-%m-%d")


def send_via_pushplus(token: str, title: str, content: str) -> dict:
    """通过 PushPlus 发送消息"""
    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": "html",
        "channel": "wechat",
    }

    # 尝试多个 endpoint
    endpoints = [
        "https://www.pushplus.plus/send",
        "https://pushplus.hxtrip.com/send",
    ]

    last_error = None
    for url in endpoints:
        try:
            print(f"   🔗 尝试: {url}")
            # 优先用 requests
            try:
                import requests

                resp = requests.post(url, json=payload, timeout=30)
                return resp.json()
            except ImportError:
                import urllib.request

                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url, data=data, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_error = e
            print(f"   ⚠️ {url} 不可用: {e}")
            continue

    raise RuntimeError(f"所有 PushPlus 端点均不可达，最后错误: {last_error}")


def main():
    parser = argparse.ArgumentParser(
        description="🐙 章鱼AI · PushPlus 微信推送",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 push.py                     # 推送最新的日报
  python3 push.py -f output/daily_report_20260730.html
  python3 push.py -t "自定义标题"
  python3 push.py --list              # 查看所有可推送文件
  python3 push.py --dry-run           # 预览但不推送
        """,
    )
    parser.add_argument("-f", "--file", help="指定 HTML 文件路径")
    parser.add_argument("-t", "--title", help="自定义推送标题")
    parser.add_argument(
        "--token", help="PushPlus token（默认使用内置 token）", default=None
    )
    parser.add_argument("--list", action="store_true", help="列出所有日报文件")
    parser.add_argument("--dry-run", action="store_true", help="预览内容，不真正推送")
    args = parser.parse_args()

    # 列出模式
    if args.list:
        files = list_all_html(OUTPUT_DIR)
        if not files:
            print("📭 没有找到任何日报文件。")
            return
        print(f"📂 {OUTPUT_DIR}/ 中共有 {len(files)} 个日报：\n")
        for i, f in enumerate(files, 1):
            date = extract_date_from_filename(f)
            size = os.path.getsize(f)
            print(f"  {i:2d}. {os.path.basename(f)}  |  {date}  |  {size:,} 字节")
        return

    # 确定文件
    html_file = args.file
    if html_file:
        if not os.path.exists(html_file):
            print(f"❌ 文件不存在: {html_file}")
            sys.exit(1)
    else:
        html_file = find_latest_html(OUTPUT_DIR)
        if not html_file:
            print(f"❌ {OUTPUT_DIR}/ 中无日报文件，请先生成日报。")
            sys.exit(1)

    # 读取
    print(f"📄 读取: {html_file}")
    with open(html_file, "r", encoding="utf-8") as f:
        content = f.read()
    print(f"   {len(content):,} 字符")

    # 标题
    date_str = extract_date_from_filename(html_file)
    title = args.title or f"🐙 章鱼AI·全景分析 | {date_str}"
    token = args.token or os.environ.get("PUSHPUS_TOKEN") or DEFAULT_TOKEN

    print(f"📌 标题: {title}")
    print(f"🔑 Token: {token[:8]}...")

    # 预览
    if args.dry_run:
        print("\n📋 === 内容预览（前500字符）===")
        print(content[:500])
        print("...")
        print(f"📋 === 共 {len(content):,} 字符 ===\n")
        print("✅ Dry-run 完成，未实际推送。")
        return

    # 推送
    print("\n🚀 正在推送到微信...")
    try:
        result = send_via_pushplus(token, title, content)
        print("\n📬 服务器响应:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("code") == 200:
            print("\n🎉 推送成功！请查看微信消息。")
        else:
            print(f"\n⚠️ 推送返回异常状态: {result.get('msg', result)}")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ 推送失败: {e}")
        print("💡 提示：请确认本机网络可访问 pushplus.plus")
        sys.exit(1)


if __name__ == "__main__":
    main()
