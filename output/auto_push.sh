#!/bin/bash
# ============================================================
# 🐙 章鱼AI · 自动推送（cron / 定时任务用）
# ============================================================
# 用法：
#   直接运行:  ./auto_push.sh
#   指定日期:  ./auto_push.sh 20260730
#   指定文件:  ./auto_push.sh -f output/daily_report_20260730.html
#
# 搭配 cron:
#   crontab -e
#   0 8 * * * cd /path/to/02 && ./output/auto_push.sh >> /tmp/octopus_push.log 2>&1
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
cd "$REPO_DIR"

# --- 配置 ---
PUSHPUS_TOKEN="${PUSHPUS_TOKEN:-507a6c0cf9cf46229f5f3c5107a967cc}"
# ------------

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# 找最新日报
latest_html() {
    ls -1t "$REPO_DIR"/output/daily_report_*.html 2>/dev/null | head -1
}

# 一键推送
do_push() {
    local html_file="$1"
    local title="${2:-}"

    log "📄 推送文件: $html_file"

    # 提取日期
    local date_str
    date_str=$(echo "$html_file" | grep -oP '\d{8}' | head -1)
    if [ -z "$date_str" ]; then
        date_str=$(TZ='Asia/Macau' date +%Y%m%d)
    fi

    local push_title="${title:-🐙 章鱼AI·全景分析 | ${date_str:0:4}-${date_str:4:2}-${date_str:6:2}}"
    log "📌 标题: $push_title"

    local content
    content=$(python3 -c "
import json, sys
with open('$html_file', 'r') as f:
    print(json.dumps(f.read()))
")

    local resp
    resp=$(curl -s -w "\n%{http_code}" --connect-timeout 15 --max-time 30 \
        -X POST "https://www.pushplus.plus/send" \
        -H "Content-Type: application/json" \
        -d "{\"token\":\"$PUSHPUS_TOKEN\",\"title\":\"$push_title\",\"content\":$content,\"template\":\"html\",\"channel\":\"wechat\"}")

    local http_code
    http_code=$(echo "$resp" | tail -1)
    local body
    body=$(echo "$resp" | head -n -1)

    log "📬 HTTP $http_code | $body"

    if echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('code')==200 else 1)" 2>/dev/null; then
        log "🎉 推送成功！"
        return 0
    else
        log "⚠️ 推送异常"
        return 1
    fi
}

# ===== 主流程 =====
HTML_FILE=""

if [ $# -ge 2 ] && [ "$1" = "-f" ]; then
    HTML_FILE="$2"
elif [ $# -ge 1 ] && [[ "$1" =~ ^[0-9]{8}$ ]]; then
    HTML_FILE="$REPO_DIR/output/daily_report_${1}.html"
else
    HTML_FILE=$(latest_html)
fi

if [ -z "$HTML_FILE" ] || [ ! -f "$HTML_FILE" ]; then
    log "❌ 没有可用日报文件"
    ls -la "$REPO_DIR/output/" 2>/dev/null || echo "output/ 为空"
    exit 1
fi

do_push "$HTML_FILE"
