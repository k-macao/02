# 🐙 章鱼 AI · 全景分析 · 全网多模型协同

## 📁 项目结构

```
output/
├── daily_report_20260730.html   ← 📰 微信适配 HTML 日报
├── push.py                      ← 🚀 统一推送脚本（推荐）
└── auto_push.sh                 ← 🔁 Bash 版自动推送（cron 用）
```

## 🚀 推送方式

### 方式一：CLI 推送（推荐）

```bash
# 自动推送最新日报
python3 output/push.py

# 指定文件
python3 output/push.py -f output/daily_report_20260730.html

# 预览不推送
python3 output/push.py --dry-run

# 列出所有日报
python3 output/push.py --list
```

### 方式二：Bash 脚本

```bash
./output/auto_push.sh            # 推送最新
./output/auto_push.sh 20260730   # 推送指定日期
```

### 方式三：Cron 定时任务

```bash
crontab -e
# 每天早 8 点自动推送
0 8 * * * cd /path/to/02 && ./output/auto_push.sh >> /tmp/octopus_push.log 2>&1
```

## 🤖 GitHub Actions 自动推送

将以下内容保存为 `.github/workflows/push-daily.yml`，即可每天 08:00 (北京时间) 自动推送：

```yaml
name: 🐙 章鱼AI · 自动推送日报

on:
  schedule:
    - cron: "0 0 * * *"           # UTC 00:00 = 北京时间 08:00
  workflow_dispatch:               # 手动触发

jobs:
  push-to-wechat:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: 推送最新日报
        env:
          PUSHPUS_TOKEN: ${{ secrets.PUSHPUS_TOKEN }}
        run: |
          pip install requests
          python3 output/push.py
```

> **⚠️ 还需要在 GitHub 仓库 Settings → Secrets and variables → Actions 中添加 `PUSHPUS_TOKEN` = `507a6c0cf9cf46229f5f3c5107a967cc`**

---

## 💬 数据源

| 平台 | 抓取内容 |
|------|----------|
| Reddit | r/wallstreetbets · r/stocks · r/investing |
| Moomoo | 社区讨论 · 行情分析 |
| 新浪财经 | A股 · 亚太市场 |
| Bloomberg / Reuters | 全球宏观 |
| SCMP · 韩国经济日报 | 亚太芯片 |

## 📜 版权

章鱼 AI，仅供参考。全网境内外检索公开行情，由多个大模型协同推理决策，
包括但不限于 Claude、ChatGPT、Gemini、Grok、Qwen 以及 Kimi，
提供多任务分析数据支持。
