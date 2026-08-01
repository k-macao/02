#!/usr/bin/env python3
"""
🐙 章鱼 AI · 一键推送
每次运行都先清理历史 HTML 报告 → 抓取最新数据 → 分析 → 生成 → 当天检验 → 推送。

常用:
  python3 output/push.py                        # 全流程（当天检验通过才推送）
  python3 output/push.py --manual               # 手动推送模式
  python3 output/push.py --manual --force-push  # 手动强制推送（内容非当天也推）
  python3 output/push.py --push-only            # 推送实际最后更新的日报（不清理）
  python3 output/push.py --list                 # 列出已生成的日报（不清理）
"""
import os
import sys
import subprocess
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(SCRIPT_DIR, "pipeline.py")
# 日报输出目录与pipeline保持一致：pipeline.py所在的目录
REPORT_DIR = os.path.dirname(PIPELINE)


def list_reports():
    """列出所有已生成的日报文件"""
    pattern = os.path.join(REPORT_DIR, "daily_report_*.html")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        print("暂无日报文件。")
        return 0

    print(f"共找到 {len(files)} 份日报：\n")
    for idx, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        print(f"  {idx:2d}. {filename}  ({size:,} 字节)")
    return 0


def main():
    # --list 模式
    if "--list" in sys.argv:
        sys.exit(list_reports())

    # 前置校验：pipeline.py 是否存在
    if not os.path.isfile(PIPELINE):
        print(f"❌ 错误：找不到流水线脚本 {PIPELINE}")
        print(f"   请检查脚本路径是否正确，当前脚本目录：{SCRIPT_DIR}")
        sys.exit(1)

    # 透传参数执行pipeline
    cmd = [sys.executable, PIPELINE] + sys.argv[1:]
    returncode = subprocess.call(cmd)

    # 退出码归一化：负数（信号终止）统一转为正数
    if returncode < 0:
        print(f"\n⚠️  进程被信号终止，信号码：{-returncode}")
        sys.exit(1)

    sys.exit(returncode)


if __name__ == "__main__":
    main()
