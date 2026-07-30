#!/bin/bash
# ============================================================
# 🐙 章鱼AI · 全自动推送（cron / 定时任务用）
# ============================================================
# 每次运行都重新抓取全网数据 → 分析 → 生成日报 → 推送到微信
#
# 用法：
#   直接运行:  ./auto_push.sh
#   cron:      0 8 * * * cd /path/to/02 && ./output/auto_push.sh >> /tmp/octopus.log 2>&1
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

PIPELINE="$SCRIPT_DIR/pipeline.py"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S CST')] 🐙 $*"; }

log "====== 自动推送任务启动 ======"

if [ ! -f "$PIPELINE" ]; then
    log "❌ 找不到 pipeline.py: $PIPELINE"
    exit 1
fi

# 全流程运行
log "开始数据采集 → 分析 → 生成 → 推送 ..."
python3 "$PIPELINE" "$@" 2>&1 | while IFS= read -r line; do
    log "$line"
done

EXIT_CODE=${PIPESTATUS[0]}

if [ $EXIT_CODE -eq 0 ]; then
    log "🎉 任务完成"
else
    log "⚠️ 任务异常退出，退出码: $EXIT_CODE"
fi

exit $EXIT_CODE
