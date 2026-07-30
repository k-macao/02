#!/usr/bin/env python3
"""
🐙 章鱼 AI · 一键推送
每次运行都先抓取最新数据 → 分析 → 生成 → 推送。
"""
import os, sys, subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(SCRIPT_DIR, "pipeline.py")

if "--list" in sys.argv:
    import glob
    files = sorted(glob.glob(os.path.join(SCRIPT_DIR, "daily_report_*.html")), reverse=True)
    if not files:
        print("No report files yet.")
    else:
        print(f"{len(files)} reports:\n")
        for i, f in enumerate(files, 1):
            print(f"  {i:2d}. {os.path.basename(f)}  ({os.path.getsize(f):,} bytes)")
    sys.exit(0)

cmd = [sys.executable, PIPELINE] + sys.argv[1:]
sys.exit(subprocess.call(cmd))
