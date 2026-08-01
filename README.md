# 02
# 🐙 章鱼 AI · 全景分析 · 全网多模型协同

## ⚡ 一键运行

```bash
cd /path/to/02
python3 output/push.py           # ①采集 → ②分析 → ③生成日报 → ④当天检验 → ⑤推送到微信
```

**每次运行都会重新抓取数据、原子更新日报；新版规则：**
- **没有数据的区块不会出现在页面里，也不推送空内容**；
- 每个区块标注 **✅ 当天 / 🕓 非当天 / ⚠️ 无数据**，页面顶部有「📅 当天内容检验」横幅；
- **只有至少一个数据源抓到「当天」内容才自动推送日报**；否则不推日报，但会向你推一条
  **「检验未通过」纯文本告警**（含各来源状态与处理建议），避免彻底沉默；
- **推送失败绝不静默**：PushPlus 报错、未配置 `PUSHPLUS_TOKEN` 或告警发送失败时，流程以
  **退出码 1** 结束，GitHub Actions 会显红并触发失败通知，不再出现“运行成功却没推送”的假象；
- **推送自动重试 + 失败告警到微信**：PushPlus 返回「发送频繁 / 稍后再试 / 服务器繁忙」或
  网络异常、HTTP 429/5xx 时，按 **10s → 30s → 60s** 退避自动重试（最多 4 次）；而
  「当日额度已达上限 / token 失效 / 内容违规」等重试无意义的错误**不重试、立即失败**。
  每次失败日志都带 PushPlus 原始 `code/msg`，可直接在 Actions 日志定位。日报多次推送仍失败时，
  会再发一条**纯文本「推送失败」告警**（含原因与三条处理建议）——微信侧能直接看到发生了什么，
  而不是只看到 Actions 变红（此时退出码仍为 1，因为日报确实未送达）；
- **推送标题带当日时分**（如 `🐙 章鱼AI日报 08/01 18:30`）：同一天多次手动推送不会因标题
  完全重复被反垃圾/去重拦截，也便于区分每一次推送；
- 页面内容已重新加入 **YouTube 财经资讯与新闻频道**（RSS 抓取，无需 API Key）；
- 全部数据源不可用时生成明确标注“数据暂缺”的状态报告，默认不推送，避免把旧内容当作新日报。

## 🎛️ 高级用法

```bash
python3 output/pipeline.py                      # 全流程（当天检验通过才推送）
python3 output/pipeline.py --no-push            # 只生成日报，不推送
python3 output/pipeline.py --dry-run            # 采集+预览，不推送
python3 output/pipeline.py -o custom.html       # 指定输出路径
python3 output/pipeline.py --manual             # 手动推送模式（重新抓取→生成→当天检验→推送）
python3 output/pipeline.py --manual --force-push # 手动强制推送（内容非当天也推，谨慎）
python3 output/pipeline.py --push-only          # 推送实际最后更新的 HTML（再次执行当天检验）
python3 output/pipeline.py --push-only output/daily_report_20260730.html  # 推送指定文件（非当天会被拒绝）
python3 output/pipeline.py --force-push-old     # 允许 --push-only 推送不带新鲜度标记的旧版文件（不推荐）
python3 output/pipeline.py --allow-incomplete-push # 全部数据源故障时仍推送“数据暂缺”状态报告
python3 output/pipeline.py --list               # 列出已生成的日报
```

## 🖐 手动推送

```bash
./output/manual_push.sh              # 手动推送：当天检验通过才推送
./output/manual_push.sh --force      # 手动强制推送（内容非当天也推送，谨慎）
./output/manual_push.sh --no-push    # 只重新生成日报，不推送
```

也可以在 GitHub 仓库的 **Actions → 🐙 章鱼AI · 手动抓取推送 → Run workflow** 点按钮手动触发，
支持两个勾选项：**no_push**（仅生成不推送）与 **force_push**（当天检验未通过也强制推送，谨慎）。

## ⏰ 定时自动运行

**GitHub Actions**：`.github/workflows/octopus-daily.yml` 每天两班——北京时间 **08:00** 与
**21:00**。注意 GitHub 定时任务在高负载时可能延迟（极端情况数小时），属平台行为；
推送失败工作流会显红并通知，不会再静默通过。

**自有服务器 crontab**：

```bash
crontab -e
# 每天早 8 点自动采集+生成+推送（当天检验通过才会推）
0 8 * * * cd /path/to/02 && ./output/auto_push.sh >> /tmp/octopus.log 2>&1
```

## 📊 数据流

```
🌐 全网数据源                     📄 本地输出
┌──────────────────────┐      ┌─────────────────────┐
│ YouTube 财经频道(RSS) │──┐   │ daily_report_*.html │
│ Reddit WSB           │──┤   │ latest.html         │
│ Yahoo Finance        │──┼──→│                     │
│ 新浪财经              │──┤ ②分析 └─────────┬───────────┘
│ TradingKey           │──┤ ③生成              │
│ Bloomberg / CNBC     │──┘  ④当天检验        │
└──────────────────────┘                  ┌────▼─────┐
                                          │ PushPlus │
                                          │   微信   │
                                          └──────────┘
```

## 📁 文件结构

```
output/
├── pipeline.py          ← 🧠 核心引擎（采集→分析→生成→当天检验→推送）
├── push.py              ← 🚀 快捷入口（= pipeline.py）
├── auto_push.sh         ← 🔁 Bash 版（cron 用）
├── manual_push.sh       ← 🖐 手动推送脚本（当天检验，--force 可强制）
├── daily_report_*.html  ← 📰 每日生成的日报
└── latest.html          ← 📎 最新一份日报的副本
```

> YouTube 财经频道列表在 `output/pipeline.py` 顶部的 `YOUTUBE_CHANNELS` 中配置，
> 每个频道可填 `channel_id`（最稳）或 `handle`（运行时自动解析，解析失败标记暂缺）。

## 📜 版权

章鱼 AI，仅供参考。全网境内外检索公开行情，由多个大模型协同推理决策，
包括但不限于 Claude、ChatGPT、Gemini、Grok、Qwen 以及 Kimi，
提供多任务分析数据支持。
