# 02
# 🐙 章鱼 AI · 全景分析 · 全网多模型协同

## ⚡ 一键运行

```bash
cd /path/to/02
python3 output/push.py           # ①采集 → ②分析 → ③生成日报 → ④推送到微信
```

**每次运行都会重新抓取数据、原子更新日报；全部数据源不可用时会生成明确标注“数据暂缺”的状态报告，默认不推送，避免把旧内容当作新日报。**

## 🎛️ 高级用法

```bash
python3 output/pipeline.py                  # 全流程
python3 output/pipeline.py --no-push        # 只生成日报，不推送
python3 output/pipeline.py --dry-run        # 采集+预览，不推送
python3 output/pipeline.py -o custom.html   # 指定输出路径
python3 output/pipeline.py --push-only output/daily_report_20260730.html  # 只推送带新鲜度标记的已有文件
python3 output/pipeline.py --allow-incomplete-push # 全部数据源故障时仍推送“数据暂缺”状态报告（默认不推送）
python3 output/push.py --list               # 列出已生成的日报
```

## ⏰ 定时自动运行（cron）

```bash
crontab -e
# 每天早 8 点自动采集+生成+推送
0 8 * * * cd /path/to/02 && ./output/auto_push.sh >> /tmp/octopus.log 2>&1
```

## 📊 数据流

```
🌐 全网数据源                     📄 本地输出
┌──────────────┐              ┌─────────────────────┐
│ Reddit WSB   │──┐           │ daily_report_*.html │
│ Yahoo Finance│──┤  ①采集     │ latest.html         │
│ 新浪财经      │──┼─────────→ │                     │
│ TradingKey   │──┤  ②分析     └─────────┬───────────┘
│ Bloomberg    │──┘  ③生成              │ ④推送
│ SCMP         │                         │
└──────────────┘                    ┌────▼─────┐
                                    │ PushPlus │
                                    │   微信   │
                                    └──────────┘
```

## 📁 文件结构

```
output/
├── pipeline.py          ← 🧠 核心引擎（采集→分析→生成→推送）
├── push.py              ← 🚀 快捷入口（= pipeline.py）
├── auto_push.sh         ← 🔁 Bash 版（cron 用）
├── daily_report_*.html  ← 📰 每日生成的日报
└── latest.html          ← 📎 最新一份日报的副本
```

## 📜 版权

章鱼 AI，仅供参考。全网境内外检索公开行情，由多个大模型协同推理决策，
包括但不限于 Claude、ChatGPT、Gemini、Grok、Qwen 以及 Kimi，
提供多任务分析数据支持。
