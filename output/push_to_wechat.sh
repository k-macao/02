#!/bin/bash
# PushPlus 推送脚本
TOKEN="507a6c0cf9cf46229f5f3c5107a967cc"
TITLE="🐙 章鱼AI·全景分析 | 2026年7月30日"

# 读取HTML内容并进行JSON转义
CONTENT=$(python3 -c "
import json, sys
with open('/home/user/02/output/daily_report_20260730.html', 'r') as f:
    content = f.read()
print(json.dumps(content))
")

# 发送到PushPlus
curl -s -X POST "https://www.pushplus.plus/send" \
  -H "Content-Type: application/json" \
  -d "{
    \"token\": \"$TOKEN\",
    \"title\": \"$TITLE\",
    \"content\": $CONTENT,
    \"template\": \"html\",
    \"channel\": \"wechat\"
  }" | python3 -m json.tool

