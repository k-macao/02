#!/bin/bash
# ============================================================
# 🐙 章鱼AI · 全自动推送（cron / 定时任务用）
# 每次运行都重新抓取全网数据 → 分析 → 生成 → 推送
# ============================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"
log() { echo "[$(TZ='Asia/Macau' date '+%Y-%m-%d %H:%M:%S CST')] 🐙 $*"; }
log "====== 自动推送任务启动 ======"
python3 "$SCRIPT_DIR/pipeline.py" "$@" 2>&1 | while IFS= read -r line; do log "$line"; done
log "任务结束"
