#!/bin/bash
# ============================================================
# 🐙 章鱼AI · 全自动推送（cron / 定时任务用）
# 每次运行都重新抓取全网数据 → 分析 → 生成 → 推送
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# 目录切换前置校验，失败给出明确提示
if ! cd "$REPO_DIR"; then
    echo "❌ 错误：无法切换到仓库目录 $REPO_DIR"
    exit 1
fi

# 日志函数：改用兼容性更广的上海时区（与澳门同属东八区）
log() {
    echo "[$(TZ='Asia/Shanghai' date '+%Y-%m-%d %H:%M:%S CST')] 🐙 $*"
}

log "====== 自动推送任务启动 ======"

# 用进程替换替代管道，避免子shell + 退出码误判问题
# 同时处理最后一行无换行的边界情况
while IFS= read -r line || [[ -n "$line" ]]; do
    log "$line"
done < <(python3 "$SCRIPT_DIR/pipeline.py" "$@" 2>&1)

log "任务结束"
