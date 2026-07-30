#!/usr/bin/env python3
"""
🐙 章鱼 AI · 一键推送
= = = = = = = = = = = = =

每次都先抓取最新数据 → 分析 → 生成日报 → 再推送。

用法：
  python3 push.py              # 全流程（采集+生成+推送）
  python3 push.py --no-push    # 只采集+生成，不推送
  python3 push.py --dry-run    # 采集+预览，不推送
  python3 push.py --list       # 列出所有已生成的日报文件

这是 pipeline.py 的快捷入口。
"""

import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(SCRIPT_DIR, "pipeline.py")


def main():
    # 如果只是想列出文件
    if len(sys.argv) >= 2 and sys.argv[1] == "--list":
        import glob
        pattern = os.path.join(SCRIPT_DIR, "daily_report_*.html")
        files = sorted(glob.glob(pattern), reverse=True)
        if not files:
            print("📭 没有日报文件。运行 push.py 即可生成。")
            return
        print(f"📂 共 {len(files)} 个日报：\n")
        for i, f in enumerate(files, 1):
            size = os.path.getsize(f)
            print(f"  {i:2d}. {os.path.basename(f)}  ({size:,} 字节)")
        return

    # 直接调用 pipeline.py
    if os.path.exists(PIPELINE):
        os.execv(sys.executable, [sys.executable, PIPELINE] + sys.argv[1:])
    else:
        print(f"❌ 找不到 {PIPELINE}")
        sys.exit(1)


if __name__ == "__main__":
    main()
