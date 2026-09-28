#!/usr/bin/env python3
"""
🐙 章鱼 AI · 全网多模型协同 · 每日财经日报流水线
每次运行都重新抓取全网最新数据 → 分析 → 生成 → 当天检验 → 推送

核心规则（2026-08-02 新版，当天修订）：
  1. 没有数据的区块不出现在页面里，也不推送空内容。
  1.1 手动 / 自动推送前先清理 output/ 目录下的全部历史 HTML 报告（含
      daily_report_*.html 与 latest.html），再抓取数据并生成新报告；
      避免历史残留文件（含旧版本特征）被误推或被 latest.html 引用。
      --push-only / --list / --dry-run / --quant-only / --calendar-only 不清理
      （前者基于旧文件，后四者不写文件）。
  2. 每次生成后先做「当天内容检验」：每个数据源标注 ✅当天 / 🕓非当天 / ⚠️无数据，
     只有当「至少一个数据源含当天内容」时才自动推送日报；否则不推日报，
     但会推一条「纯文本告警」说明原因与各来源状态，避免彻底沉默。
  3. 页面内容包含「港股名家频道」区块：香港股评人/财经平台的 YouTube 与通用 RSS
     抓取（无需 API Key），每频道列出最新 3 条；需登录平台明确标注「暂缺」及原因，
     不伪造内容。
  4. 「全球头条」改用 Google News 数据源（替换原 Yahoo Finance News）：直接抓
     Google News 中文版，标题本身即中文，无需翻译。
  5. 新增「东方财富快讯」区块：东方财富免费公开接口的最新 5 条财经新闻。
  6. 新增「热门榜单」数据源：最近交易日收盘后 A股/港股/美股 成交量前五
     （东方财富 push2 免费接口）。2026-08-06 起不再单独渲染三个成交量榜单栏目，
     原始榜单数据仅作为 AI 盘研判与数据审计的信号源；
     页面只保留 AI 盘研判结果。
  6.1 新增「A股大盘全景复盘」栏目（数据源：东方财富 push2/push2his 免费接口）：
      ① 指数表现——上证 / 深证 / 创业板 / 科创50 / 北证50 / 沪深300 / 上证50 / 中证500
      最新价、涨跌幅与成交额；② 涨跌家数——沪深京市场宽度（上涨/下跌/平盘家数、
      涨跌比与情绪定调）；③ 成交额——沪深京合计与上一交易日环比（日 K 补齐前值）；
      ④ 南北向资金——港交所 2024-08-19 起停披净买入，按最近完整交易日（前一收盘）
      展示北向、南向成交总额与披露口径说明，绝不编造净买入；⑤ 板块热力——行业板块领涨/领跌 TOP5（附主力
      净流入与领涨股）。子块独立降级：单个接口失败只隐藏对应子块，指数与宽度全缺
      时整个栏目才缺席；规则合成，非投资建议。
  6.2 逐栏目 AI 研判（2026-09-27 新增）：每个有数据的内容栏目（行情速览 / A股大盘全景复盘 /
      政策因子 / 全球头条 / 东方财富快讯 / A股资讯 / 每日量化策略趋势跟踪线索 / 港股名家频道 /
      AI 新闻情绪因子）正文末尾追加一行概率化多空判断：
      「⌁ AI 研判 ▲偏多 / ▼偏空 / ■中性 · 多头 x% / 空头 y% — 栏内证据 → 预测：结论」。
      概率 = 50 + 45*(多−空)/(多+空)，夹在 5%–95%（持平 50%，绝不绝对化）；≥60% 偏多 /
      ≤40% 偏空 / 其间中性；多头 + 空头恒 100%。证据仅取自该栏目已抓取数据；结论类栏目
      （今日结论 / AI 盘研判 / 盘点总结）与前瞻日程类栏目（未来30天影响经济时间点：
      日程不含方向信息，只给「最密集日 + 事件密度提示」）不附加，栏目无数据自然缺席。
      规则合成，非投资建议。
  6.3 新增「未来30天影响经济时间点」栏目（2026-09-28，日报开头第一个数据栏目）：
      数据源为东方财富财经日历（数据中心公开报表 RPT_CPH_FECALENDAR，无需密钥，
      START_DATE 即北京时间）。服务端只支持按日期过滤，故一次拉全窗口 + 翻页，
      再在本地按写死的口径筛选：保留 数据（中美欧日英港等市场的宏观读数）/
      事件（央行议息、国民经济运行情况发布会、中央全会等重要会议）/ 动态（央行官员
      讲话、货币政策会议纪要、CFTC 周度持仓）三类，剔除个股事项、非保留地区读数、
      冗余子序列与超长条目；同一天同一指标的 同比/环比/初值/终值 多行合并为一行。
      重要度 ★★★（中美一级读数 + 主要央行议息与中国宏观决策会议）/ ★★ / ★；
      抓取后本地再夹一次窗口，栏目写「未来 N 天」就绝不出现窗口外的行。
      正文行数上限（默认 60）只作版面保护，被裁条数按重要度如实写进摘要。
      前瞻性日程属于「今日抓取快照」而非当天发布内容：is_today=False + snapshot=True，
      因此它永远不会单独把日报推过当天检验闸门；抓取失败则整栏缺席并在盘点总结点名。
      OCTOPUS_CALENDAR=0 关闭、OCTOPUS_CALENDAR_DAYS 调窗口、OCTOPUS_CALENDAR_ROWS 调行数。
  4. 支持手动推送：--manual / manual_push.sh / GitHub Actions 手动按钮（可勾选 force_push），
     内容非当天时可用 --force-push 强制推送（谨慎）。
  5. 任何「应当推送却失败」的情况（PushPlus 报错、未配置 PUSHPLUS_TOKEN、网络异常，
     含「检验未通过」告警发送失败）都以退出码 1 结束：GitHub Actions 会显红并触发
     失败通知，杜绝“推送失败却显示成功”的假象。
  6. PushPlus 推送对「发送频繁 / 稍后再试 / 服务器繁忙 / 网络异常 / HTTP 429·5xx」
     等可恢复错误按 10s→30s→60s 退避自动重试（最多 4 次）；对「当日配额已达上限、
     token 失效、内容违规」等重试无意义的错误不重试、立即失败。日报多次推送仍失败时
     会再发一条纯文本「推送失败」告警（含 PushPlus 返回的 code/msg 与处理建议），
     让微信侧也能感知原因，而不是只看到 Actions 变红。
  7. 推送标题带当日时分（如 08/01 18:30）：同一天多次手动推送不会因标题完全重复
     触发反垃圾/去重拦截，也便于区分每一次推送。
  7.1 页面风格：复古像素游戏（RETRO PIXEL MARKET QUEST v3）——
     暗色街机终端底、霓虹青 / 电光蓝 / 像素黄 / 品红，纯直角像素块 + 3px 硬描边 + 实色阴影；
     等宽字体栈（Courier New / Lucida Console / monospace，回退苹方/雅黑）。刊头含纯 HTML 8-bit
     章鱼图标；每个 LVL 关卡配独立 44px 大图标砖。涨跌用高对比底色 + ▲涨 / ▼跌 / ■平三重
     编码，并覆盖行情等板块。AI 盘研判首屏使用 AI CORE 主控卡、方向 / 信号分 /
     置信度计分板和大字号「AI 主结论」，板块 / 技术 / 风险 / 关注各自成独立像素面板；窗口标题栏
     升级为 OCTOPUS_OS v3。成交量榜单不再单独成栏，只保留 AI 研判结果。
     硬约束：全部内联样式 + 表格布局（微信/PushPlus 会剥离 <style> 与 class）。
  8. PushPlus 内容上限与「分条完整推送」（2026-09-28 起）：单条上限按会员额度 10 万字
     （可用环境变量 PUSHPLUS_MAX_CONTENT_CHARS 覆盖）。日报 HTML 超过上限时**不再截断丢内容**，
     而是按栏目边界拆成 N 条消息依次推送（标题追加 1/N、2/N…，条间等待
     PUSHPLUS_PART_DELAY 秒避开频率限制）：每条 = 原文档头部外壳（含刊头）+ 条序横幅 +
     若干完整栏目 + 页脚与闭合标签，因此每条都是独立、标签平衡、样式一致的 HTML，
     微信端排版与单条推送相同，全部内容按原顺序送达。单个栏目自身就超预算时，再按完整
     标签边界细分并在续片里原样重开父标签，同样不丢字。所需条数超过 PUSHPLUS_MAX_PARTS
     （默认 12）时，前 N-1 条完整推送、收尾条截断并附「完整日报」链接，且横幅如实说明
     未推完，绝不假装全文已送达。PUSHPLUS_MULTIPART=0 可整体关闭分条，回退到旧的
     「按标签边界截断 + 完整版链接」；旧版日报文件没有分条标记时同样自动回退。
     注意：分条会按条数消耗 PushPlus 当日额度（25 万字日报约 3 条）。
     磁盘 / GitHub 上的日报文件始终是一份完整版，不受推送拆分影响。
  9. 「AI 盘研判」栏目：基于当日多源信号（实时行情、热门榜单、全球/东财/A股头条、
     港股名家频道观点）做确定性规则合成，输出跨市场综合研判（情绪定调 +
     信号分 + 置信度、板块热度、技术速读、风险提示、明日关注主题）。无需大模型 API、
     可复现、不伪造内容，明确标注「非投资建议」；数据源不足时该区块自动缺席。
     2026-09-09 起页内去重：指数动能只保留聚合（明细数值见「行情速览」），
     风险提示对正文已展示的标题仅引用定位（栏目 + 序号 + 命中关键词 + 锚点），
     多因子矩阵不再复述雅虎逐只报价。
  10. 「AI 新闻情绪因子」栏目：按「最近交易日 A股 / 港股 / 美股 成交量前五」
      逐股输出 AI 新闻情绪分与总结评论（含原因）。标题窗口为近
      SENTI_WINDOW_HOURS=72 小时（含历史存档），对窗口内标题逐条词表评分（S，
      附命中词）并按热门榜单个股名归因；每只上榜股输出 DNS 情绪=
      (正−负)/总数（72h 窗口口径）、MOM 情绪动量=近3有评分日均−近20有评分日均、
      ANV 异常新闻量=今日条数 vs 近30天均值±σ（z 值，>均值+2σ 标异常；
      MOM/ANV 与跨日基线按自然日口径，存 output/sentiment_history.json，随日报
      提交），以及「总结评论 + 原因」（由命中标题、词表、动量与新闻量规则生成）。
      窗口内无相关点名新闻的上榜股明确显示「暂无评分」与原因，不凭价格涨跌反推
      新闻情绪；无热门榜单则栏目缺席。标题存档存 output/news_history.json
      （每次运行合并本次抓取并按 日期+标题 去重）。冷启动/样本不足明确标注。
      渲染位置：各资讯栏目之后。规则合成、非投资建议。
  11. 「港股量化引擎」（output/octopus_quant/，2026-09-28 起）：把整条流程按量化
      思维重构成六个可独立测试的层——providers(数据) → features(五因子特征) →
      probability(分桶+保序+逻辑回归校准 / 推进式回测) → liquidity(资金流动性) →
      engine(编排) → render(呈现)，外加「预测留痕 → 次日按真实收盘结算」的反馈闭环
      （output/quant_history.json）。核心栏目三个：**量化预测总览**（概率 + 95% 区间 +
      波动分位 + 模型可信度 + 预测复盘）、**港股概率走势分析**（恒指/恒科/国企指数 +
      个股池逐只概率 + 市场宽度 + 五因子拆解）、**资金流动性分析**（南向/北向成交总额
      与 z 值分位、恒指量能、Amihud 非流动性、CR5 集中度、主力资金流、流动性综合分
      0~100 与对概率的有界修正）。概率全部由「同一套因子在自身历史上滚动重算 →
      分桶 + 保序 + 逻辑回归校准」得到，并经推进式回测检验（每步只用过去数据），
      夹在 5%~95%，非投资建议；数据取不到时对应子块明确显示「暂缺」，绝不编造。
  12. 「政策因子」栏目：抓取后、推送前单独构建，推送页首位渲染。除资讯标题外，
      直接读取中国政府网「最新政策」官方页面，保留发布日期与 gov.cn 原文链接；
      近 POLICY_WINDOW_DAYS=15 日窗口（自然日，含历史存档）内标题做政策维度识别
      （货币/监管/扶持/财政/地产/开放/贸易/宏观数据——宏观数据含 CPI / PPI /
      社融 / 统计局 等经济数据口径），经关键词矩阵映射到行业受益/受损权重，
      汇总为 PolicyShockIndex（行业 PSI 与大盘 PSI，附规则生成的总结）。官方条例、
      规划、办法等没有方向性触发词时按中性「政策发布」纳入；触发词被否定修饰时跳过；
      窗口内零政策/宏观新闻时栏目缺席。规则合成、非投资建议。

退出码约定：
  0 = 正常完成（含 --no-push / --dry-run 等有意的跳过，或检验未通过但告警已送达）；
  1 = 应当推送却失败，或用法错误。

用法:
  python3 output/pipeline.py                  # 全流程（当天检验通过才推送）
  python3 output/pipeline.py --no-push        # 只生成，不推送
  python3 output/pipeline.py --dry-run        # 采集+预览，不推送
  python3 output/pipeline.py -o custom.html   # 指定输出路径
  python3 output/pipeline.py --manual         # 手动推送模式
  python3 output/pipeline.py --manual --force-push   # 手动强制推送（内容非当天）
  python3 output/pipeline.py --push-only              # 推送实际最后更新的一份日报（当天检验）
  python3 output/pipeline.py --push-only path/to/report.html
  python3 output/pipeline.py --list           # 列出日报

退出码：0 = 正常完成；1 = 应当推送却失败 / 用法错误（GitHub Actions 据此标红）。
"""
import os
import sys
import time
import argparse
import random
import re
import glob
import json
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from html import unescape as _html_unescape
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    print("❌ 缺少依赖 requests，请运行: pip install requests")
    sys.exit(1)

# ============================================================
# 全局配置
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = SCRIPT_DIR

# ============================================================
# 港股量化引擎（output/octopus_quant/）
# ------------------------------------------------------------
# 分层：providers(数据) → features(特征) → probability(概率/校准/回测) →
#       liquidity(资金流动性) → engine(编排) → render(呈现)。
# pipeline 只做两件事：注入取数函数 ``safe_request``、注入排版套件 ``kit``；
# 量化包不反向依赖日报，因此可完全离线单测（见 tests/test_quant.py）。
# 另有反馈闭环：每次预测写入 output/quant_history.json，之后按真实收盘结算
# 「方向命中 / 区间命中 / Brier」，模型表现自己记账。
# ============================================================
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import octopus_quant as _quant  # noqa: E402

QUANT_HISTORY_FILENAME = "quant_history.json"
# 量化引擎开关：OCTOPUS_QUANT=0 或 --no-quant 可整体跳过（离线/赶时间时用）
HK_QUANT_ENABLED = str(os.environ.get("OCTOPUS_QUANT", "1")).strip().lower() not in ("0", "false", "no")
# 是否逐只跑个股概率（关掉后只出指数与流动性，明显更快）
HK_QUANT_STOCKS = str(os.environ.get("OCTOPUS_QUANT_STOCKS", "1")).strip().lower() not in ("0", "false", "no")

# 时区
CST = timezone(timedelta(hours=8))  # 北京时间 / 澳门时间（东八区）

# PushPlus 配置
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_URL = "https://www.pushplus.plus/send"
# PushPlus 内容长度上限：实名用户 2 万字、会员用户 10 万字（账号已升级会员，默认按 10 万）。
# 超过上限的内容会被平台截断，截断点常落在标签中间，导致微信端整页排版崩坏
# （表现为整页只剩浅灰背景、正文缺失）。因此发送前先按完整标签边界截断并闭合标签，
# 末尾附「完整版」链接；磁盘上的日报文件始终保留完整版。
# 如账号额度变化，可用环境变量 PUSHPLUS_MAX_CONTENT_CHARS 覆盖（如 20000 / 100000）。
PUSHPLUS_MAX_CONTENT_CHARS = int(os.environ.get("PUSHPLUS_MAX_CONTENT_CHARS", "100000"))
# 完整推送（2026-09-28 起）：单条上限固定按 10 万字（会员额度），但日报不再被截断——
# 超过上限时按「完整标签边界 + 栏目边界」拆成多条微信消息（1/n、2/n…）依次推送，
# 全部内容都会送达。每条消息都是结构完整、标签自闭合的独立 HTML，
# 并沿用原文档的 <head>／外层包裹与页尾，微信端排版与单条推送一致。
# PUSHPLUS_MULTIPART=0 可关闭拆分，回退到旧行为（按标签边界截断 + 完整版链接）。
PUSHPLUS_MULTIPART = str(os.environ.get("PUSHPLUS_MULTIPART", "1")).strip().lower() not in ("0", "false", "no")
# 多条推送之间的间隔秒数，避免触发 PushPlus「发送频繁」频率限制（每条仍各自退避重试）。
PUSHPLUS_PART_DELAY = float(os.environ.get("PUSHPLUS_PART_DELAY", "2"))
# 渲染时插入的两个「分条标记」（HTML 注释，浏览器与微信端都不可见，不影响阅读）：
#   PART_BREAK_MARK —— 每个栏目之前，拆分时切在这里，保证每条消息都从完整栏目开始；
#   DOC_FOOT_MARK   —— 页脚（免责声明）之前，它到文末的部分就是「页脚 + 全部闭合标签」。
# 有了这两个标记，超长日报就能被切成 N 份「各自都是完整可渲染的 HTML 文档」：
# 每份 = 原文档头部外壳（含刊头）+ 条序横幅 + 若干完整栏目 + 页脚 + 闭合标签，
# 微信端排版与单条推送完全一致，且全部内容按原顺序送达。
PART_BREAK_MARK = "<!--SPLIT-->"
DOC_FOOT_MARK = "<!--FOOT-->"
# 单份日报最多拆成多少条（防御性上限：正常 25 万字日报约 3 条）
PUSHPLUS_MAX_PARTS = int(os.environ.get("PUSHPLUS_MAX_PARTS", "12"))

# 默认「一对一」直发自己（不携带 topic 字段）；如需一对多群组推送，
# 显式设置环境变量 PUSHPLUS_TOPIC=群组编码（例如 oai.1）。
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")

# ============================================================
# 推送主题（2026-08-21 起，一对一 / 一对多推送共用）
# ============================================================
# guizang —— 默认主题：参考 guizang-ppt-skill 的 Style A「电子杂志 × 电子墨水」
#   （github.com/op7418/guizang-ppt-skill），改造成适合微信阅读的竖版长页面：
#   白色正文、黑底白字的紧凑标题、圆体字与 2px 实线分隔。微信优先：单列满宽；
#   行情 / 全景 / 情绪总览 / 政策冲击 / 数据审计等结构化数据用键值表整合。
#   图标在白底独立显示，正文与次要文字保持纯黑 / 深灰；不依赖颜色区分涨跌。
#   纯内联样式，不依赖 WebGL / JavaScript / 外部 CSS，兼容 PushPlus / 微信详情页。
# pixel   —— 旧版 Retro Pixel Market Quest 主题（可切换回退，行为保持不变）。
PUSH_THEMES = ("guizang", "pixel")
DEFAULT_PUSH_THEME = "guizang"


def _resolve_push_theme(name=None):
    """归一化推送主题：空 / 非法值一律回落到默认主题 guizang。"""
    theme = name if name is not None else os.environ.get("OCTOPUS_PUSH_THEME", "")
    theme = str(theme or "").strip().lower()
    return theme if theme in PUSH_THEMES else DEFAULT_PUSH_THEME


# 当前默认主题（环境变量 OCTOPUS_PUSH_THEME 可覆盖；命令行 --theme 优先）
PUSH_THEME = _resolve_push_theme()

# 请求头
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# ------------------------------------------------------------
# 港股名家频道（内容渠道配置，2026-08-02 起按用户指定列表）
# 每个频道可配置：
#   kind = "youtube"  → YouTube 频道，通过公开 RSS 抓取（无需 API Key），
#                       填 channel_id（最稳）或 handle（运行时自动解析，失败标记暂缺）
#   kind = "rss"      → 通用 RSS / Atom 源（如 Medium、Substack）
#   kind = "manual"   → 需登录 / 平台限制，暂无法自动抓取（页面标注「暂缺」及原因，不伪造内容）
# 每频道在日报中列出最新 CHANNEL_TOP_N 条内容。
# 需要增删频道或接入新平台时直接改这个列表即可。
# ------------------------------------------------------------
CHANNEL_TOP_N = 3

# 正文资讯栏目的展示条数（与 _collect_report_parts 的切片口径一致）。
# 风险引用去重依赖此口径：超出展示条数的风险标题正文不可见，风险提示保留全文。
GH_DISPLAY_N = 8    # 全球头条展示前 8 条
EM_DISPLAY_N = 5    # 东财快讯展示前 5 条
SINA_DISPLAY_N = 5  # A股资讯展示前 5 条

# ------------------------------------------------------------
# 未来 N 天影响经济时间点（东方财富财经日历 RPT_CPH_FECALENDAR）
# 放在日报开头：先看清「未来 30 天哪些时点会动市场」，再读今天的盘。
# 接口是东财数据中心公开报表（与「A股大盘全景复盘」的南北向资金同一台主机），无需密钥；
# START_DATE 为北京时间（形如 2026-10-28 20:30:00）。服务端只支持按日期过滤
# （按 CITY / FE_TYPE 过滤返回空），所以一次拉全窗口（翻页）再在本地按重要度筛选。
# 筛选口径全部写死在下面的常量里：确定性计算、可复现、不调大模型、不伪造内容；
# 读不到就在栏目与审计里如实标「暂缺」及原因。
# 前瞻性日程不属于「当天发布的内容」→ is_today=False + snapshot=True，
# 因此它永远不会单独把日报推过当天检验闸门（见 check_push_eligibility）。
# ------------------------------------------------------------
def _env_int(name, default, lo, hi):
    """读整数环境变量：非法值回落 default，合法值夹在 [lo, hi]。"""
    try:
        value = int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


ECON_CALENDAR_ENABLED = str(os.environ.get("OCTOPUS_CALENDAR", "1")).strip().lower() not in ("0", "false", "no")
ECON_CALENDAR_DAYS = _env_int("OCTOPUS_CALENDAR_DAYS", 30, 1, 120)      # 前瞻窗口天数
ECON_CALENDAR_MAX_ROWS = _env_int("OCTOPUS_CALENDAR_ROWS", 60, 5, 300)  # 正文行数上限（版面保护）
ECON_CALENDAR_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
ECON_CALENDAR_REPORT = "RPT_CPH_FECALENDAR"
ECON_CALENDAR_COLUMNS = "START_DATE,END_DATE,FE_CODE,FE_NAME,FE_TYPE,STD_TYPE_CODE,CITY"
ECON_CALENDAR_PAGE = "https://data.eastmoney.com/cjrl/default.html"  # 溯源页（完整日历）
ECON_CALENDAR_SOURCE = "东方财富财经日历"
ECON_CALENDAR_PAGE_SIZE = 500   # 服务端单页上限
ECON_CALENDAR_MAX_PAGES = 8     # 30 天窗口实测 1 页足够，翻页只为窗口调大时兜底

# 保留地区：只留有定价权的市场，其余地区的读数不进正文（全窗口原始日程一月 300+ 条）。
CALENDAR_KEEP_CITY = (
    "中国", "美国", "欧元区", "欧盟", "日本", "英国", "中国香港",
    "加拿大", "澳大利亚", "韩国", "瑞士", "新西兰", "OPEC",
)
CALENDAR_CORE_CITY = ("中国", "美国")                     # 一级读数在这两个市场给 ★★★
CALENDAR_MAJOR_CITY = CALENDAR_CORE_CITY + ("欧元区", "欧盟", "日本", "英国")
# 事件类的最高重要度判定：① 中国宏观决策会议直接最高；② 主要央行 + 议息/决议动作。
# 注意：事件行的 CITY 字段常是城市名（如「华盛顿」「法兰克福」）而不是国家，
# 所以重要度只按名称里的「机构 + 动作」判定，不依赖地区字段。
CALENDAR_EVENT_TOP = (
    "国民经济运行情况发布会", "中国共产党中央全会", "中央全会", "中央经济工作会议",
    "政府工作报告", "全国人民代表大会", "政治局会议", "国务院常务会议",
)
CALENDAR_EVENT_ORG = (
    "美联储", "联邦储备", "欧洲央行", "欧央行", "日本央行", "英国央行", "瑞士央行",
    "加拿大央行", "澳洲联储", "新西兰联储", "韩国央行", "中国人民银行", "中国央行",
)
CALENDAR_EVENT_ACT = (
    "议息", "利率决议", "利率决定", "货币政策", "决议", "会议纪要", "发布会",
)
# 一级读数：真正驱动资产定价的宏观数据
CALENDAR_TIER3_KW = (
    "CPI", "PPI", "PCE", "GDP", "PMI", "非农", "失业率", "利率决议", "M2",
    "货币供应", "社融", "社会融资", "新增信贷", "LPR", "MLF", "工业增加值",
    "社会消费品零售", "固定资产投资", "进出口", "贸易帐", "贸易差额",
    "外汇储备", "工业企业利润", "货币政策会议纪要",
)
# 二级读数：重要但非核心（EIA 原油库存是每周真正推动油价的读数，显式保留）
CALENDAR_TIER2_KW = (
    "ISM", "初请", "ADP", "耐用品", "工业产出", "新屋", "成屋", "营建",
    "产能利用率", "零售销售", "消费者信心", "景气", "职位空缺", "时薪",
    "制造业", "服务业", "综合", "经济展望", "就业", "工业订单",
    "EIA原油库存", "EIA汽油库存", "EIA精炼油库存", "库欣原油库存",
    "出口", "进口", "利率", "汇率", "信贷", "贷款",
)
# 动态类（无 FE_TYPE：央行官员讲话 / 会议纪要 / 周报）里价值高的信号
CALENDAR_DYN_TIER2 = (
    "美联储主席", "美联储公布", "货币政策会议纪要", "利率决议", "主席鲍威尔",
    "非农", "议息", "CFTC", "OPEC", "月报",
)
# 个股事项：与「宏观时间点」无关，直接剔除（否则每只新股都是一条噪音）
CALENDAR_DROP_KW = (
    "新股申购", "新股上市", "限售解禁", "分红", "送转", "股东大会",
    "增持", "减持", "回购", "股权激励", "停牌", "复牌",
)
# 同名指标的冗余子序列（户籍口径失业率 / 现价 GDP / 汇率中间价…）
CALENDAR_DROP_NAME_KW = ("人口数", "现价", "折年数", "期末汇率", "人民币汇率", "战略储备", "预测年度")
CALENDAR_DROP_NAME_SFX = (":值",)   # 仅当名称以「:值」结尾才丢（否则会误杀「EIA原油库存:变动值」）
# 展会 / 论坛：对交易价值低，只给一星（正文触顶时最先被裁掉）
CALENDAR_LOW_KW = (
    "展览会", "博览会", "展会", "交易会", "糖酒会", "车展",
    "高峰论坛", "交流会议", "研讨会", "论坛",
)
CALENDAR_MAX_NAME_LEN = 40          # 超长条目（移仓换月提醒 / 停摆公告）既是噪音又占版面
CALENDAR_NOISE_TAG = ("[同传]", "（同传）", "(同传)", "【同传】")
CALENDAR_KIND_LABELS = {0: "数据", 1: "事件", 2: "动态"}
# 归一化时剥掉的修饰词：必须先归一化再判「是不是同一个指标」，
# 否则「CPI:当月同比」「CPI:累计同比」「CPI:季调:环比」会被当成三个指标，一天排出 6 行。
CALENDAR_CANON_DROP = ("季调", "非季调", "初值", "终值", "修正值", "预估值",
                       "折年率", "年化", "当月", "总计", "总值", "数据", "报告")
CALENDAR_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# 每日量化策略趋势跟踪线索：源头数据只保留 Reddit 一个来源（2026-09-27 起由十站投研精简）。
# 只读取公开热帖 feed，不登录、不绕过付费墙、不复制帖子正文；
# 扫描 10 个财经 / 投资 / 金融 / 经济类板块，每个板块取热门帖子 5 条作为样本数据，
# 捕捉散户讨论风向与热门标的。板块顺序同时用于抓取、栏目和审计展示。
PUBLIC_SITE_NAMES = ("Reddit",)
PUBLIC_SITE_URLS = {
    "Reddit": "https://www.reddit.com/",
}
PUBLIC_SITE_DESCRIPTIONS = {
    "Reddit": "散户讨论风向与热门标的：10 个财经/投资/金融/经济类板块各取热门帖子 5 条为样本",
}
PUBLIC_SITE_WINDOW_HOURS = 72  # 帖子按发布时间过滤
REDDIT_POSTS_PER_BOARD = 5     # 每个板块的热门帖样本条数

HK_CHANNELS = [
    # ── 港股股评人 YouTube 频道（可自动抓取）─────────────────
    {"name": "郭思治（郭Sir）",
     "desc": "香港著名股評人，專注大盤技術走勢。",
     "kind": "youtube", "handle": "@KwokSirFinance"},

    # ── 需登录 / 暂未提供可抓取源（明确标注暂缺）────────────
    {"name": "曾廣標（股票分析）",
     "desc": "資深股評人，專注細價股與價值挖掘。",
     "kind": "manual",
     "note": "暂无官方可抓取频道；旧视频散见于「港股直播室 @hongkongstock」（2023 年后未更新）"},
    {"name": "陸羽仁（金融肉搏戰）",
     "desc": "老牌專欄，分析港股大局與政經關係。",
     "kind": "manual",
     "note": "信報專欄，非 YouTube；暂不支持自动抓取"},
    {"name": "青姐（胡孟青）",
     "desc": "風格辛辣，直擊港股市場痛點與散戶心態。",
     "kind": "manual",
     "note": "暂无官方频道；节目「胡孟青拆局」发布于 AASTOCKS 频道（@AASTOCKS_AATV）"},
    {"name": "智通財經App（微信公众号）",
     "desc": "每日推送港股早報與板塊機會。",
     "kind": "manual",
     "note": "微信公众号需登录，暂不支持自动抓取"},
    {"name": "港股那點事（格隆匯）（微信公众号）",
     "desc": "深度剖析港股上市公司實力。",
     "kind": "manual",
     "note": "微信公众号需登录，暂不支持自动抓取"},
    {"name": "球友大白（雪球 KOL）",
     "desc": "長線跟蹤港股高股息、藍籌股。",
     "kind": "manual",
     "note": "雪球需登录 / 反爬限制，暂不支持自动抓取"},
    {"name": "香港投資筆記（Medium）",
     "desc": "獨立分析師發表深度個股研究。",
     "kind": "rss", "feed_url": "",
     "note": "请提供 Medium 地址后接入 RSS"},
    {"name": "港股策略通訊（Substack）",
     "desc": "付費/免費的深度行業趨勢報告。",
     "kind": "rss", "feed_url": "",
     "note": "请提供 Substack 地址后接入 RSS"},
    {"name": "港股交易員（微博大V）",
     "desc": "實時更新盤中異動與傳聞。",
     "kind": "manual",
     "note": "微博需登录 / 反爬限制，暂不支持自动抓取"},

    # ── 第二批（2026-08-02 追加，用户指定）──────────────────
    {"name": "施凌部署",
     "desc": "結合宏觀經濟與技術分析的知名財經頻道；施凌部署為「我要做富翁」旗下品牌，於該官方頻道發布。",
     "kind": "youtube", "handle": "@Money-Tab"},
    {"name": "BofA Global Research（美銀研究）",
     "desc": "解讀大行對港股策略的官方影音；BofA Global Research 內容於 Bank of America 官方頻道發布（Must Read Research 系列）。",
     "kind": "youtube", "handle": "@BankofAmerica"},
    {"name": "秒投（ShareNews / StockViva）",
     "desc": "邀請多位香港股評人進行直播分析。",
     "kind": "youtube", "handle": "@StockViva"},
    {"name": "C基金 - 李浩德",
     "desc": "基金經理視角，分析港股大盤與科技股。",
     "kind": "youtube", "handle": "@CFund_Channel"},
    {"name": "Finance730",
     "desc": "探討香港財經、地產及股市走勢的專業網媒。",
     "kind": "youtube", "handle": "@Finance730hk"},
    {"name": "紅猴（Red Monkey）",
     "desc": "深度分析港股價值投資與公司基本面。",
     "kind": "manual",
     "note": "未找到独立官方频道；其视频散见于「成家網上投資課程」等第三方频道（多为 2022 年前旧内容）"},
    {"name": "米高（Michael）的財經頻道",
     "desc": "專注港股短線操作與期指分析。",
     "kind": "manual",
     "note": "未能在 YouTube 检索到明确的「米高 Michael 財經頻道」，请提供频道链接或 handle 后接入"},
    {"name": "小斯財經",
     "desc": "用深入淺出的方式講解港股與新股申購。",
     "kind": "manual",
     "note": "未能在 YouTube 检索到明确的「小斯財經」频道，请提供频道链接或 handle 后接入"},
    {"name": "智富同學會",
     "desc": "分享技術指標與港股實戰策略。",
     "kind": "manual",
     "note": "未检索到「智富同學會」独立频道；疑似相关频道「智富財經 Invest Smarter @investsmarter536」，如需接入请确认"},
    {"name": "港股研究社（Bilibili）",
     "desc": "面向內地投資者的港股解讀視頻（B站 UP 主，UID 613310838）。",
     "kind": "rss", "feed_url": "https://rsshub.app/bilibili/user/video/613310838",
     "note": "通过 RSSHub 抓取 Bilibili 投稿；如公共实例被限流，可更换其他 RSSHub 实例"},
]

YT_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}

# ============================================================
# 工具函数
# ============================================================
def _now():
    """返回当前北京时间字符串"""
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def _today_str():
    """返回今天日期字符串 YYYYMMDD"""
    return datetime.now(CST).strftime("%Y%m%d")


def _today_display():
    """返回今天的日期字符串 YYYY-MM-DD"""
    return datetime.now(CST).strftime("%Y-%m-%d")


def _date_display():
    """返回中文日期显示"""
    now = datetime.now(CST)
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{now.year}年{now.month}月{now.day}日 · {weekdays[now.weekday()]}"


def _esc(s):
    """HTML 转义"""
    if not s:
        return ""
    return (s.replace("&", "&amp;")
              .replace("<", "&lt;")
              .replace(">", "&gt;")
              .replace('"', "&quot;")
              .replace("'", "&#x27;"))


def _cst_from_iso(iso_str):
    """把 ISO8601 时间转为北京时间 datetime；失败返回 None。"""
    if not iso_str:
        return None
    try:
        iso = iso_str.replace("Z", "+00:00")
        return datetime.fromisoformat(iso).astimezone(CST)
    except Exception:
        return None


def _date_is_today(dt):
    """判断某个 datetime 是否属于今天（北京时间）。"""
    return bool(dt and dt.strftime("%Y%m%d") == _today_str())


def safe_request(url, headers=None, params=None, timeout=15, is_json=True):
    """安全请求，失败返回 None"""
    try:
        h = {**DEFAULT_HEADERS, **(headers or {})}
        resp = requests.get(url, headers=h, params=params, timeout=timeout)
        resp.raise_for_status()
        if is_json:
            return resp.json()
        return resp.text
    except Exception as e:
        print(f"  ⚠️ 请求失败 [{url[:60]}...]: {e}")
        return None


# ============================================================
# 数据新鲜度与实时行情
# ============================================================
def _format_amount(val):
    """格式化成交额：显示亿/万，保留两位小数；负数保留负号（如主力净流出）。"""
    try:
        v = float(val)
        sign = "-" if v < 0 else ""
        a = abs(v)
        if a >= 1e8:
            return f"{sign}{a/1e8:.2f}亿"
        if a >= 1e4:
            return f"{sign}{a/1e4:.2f}万"
        return f"{v:.2f}"
    except (TypeError, ValueError):
        return str(val or "—")


def _source_result(source, status, is_today=False, content_date=None, **payload):
    """统一记录来源、抓取时间、当天标记和失败状态；绝不把历史文案伪装成实时数据。

    is_today      —— 该来源的内容是否属于「当天」（按北京时间判断）
    content_date  —— 该来源最新内容的日期（如最后收盘日 / 最新视频发布日），用于展示
    """
    return {
        "source": source, "status": status, "fetched_at": _now(),
        "is_today": bool(is_today), "content_date": content_date,
        **payload,
    }


def _source_note(item):
    """供 HTML 使用的数据来源状态（纯文字溯源行；状态以色块徽标另行表达）。"""
    if item.get("status") == "success":
        return f"{item.get('source', '数据源')} · 抓取于 {item.get('fetched_at', '—')}"
    detail = _esc(item.get("error", "暂时不可用"))
    return f"{item.get('source', '数据源')} 数据暂缺（{detail}）· 抓取于 {item.get('fetched_at', '—')}"


def fetch_market_snapshot():
    """从 Yahoo Chart API 获取实际最新收盘/最新报价，不提供历史数字兜底。"""
    print("📡 正在抓取全球/A股实时行情...")
    specs = [
        ("道琼斯指数", "%5EDJI"), ("标普500", "%5EGSPC"), ("纳斯达克", "%5EIXIC"),
        ("WTI 原油", "CL=F"), ("微软 MSFT", "MSFT"), ("Meta META", "META"),
        ("上证指数", "000001.SS"), ("深证成指", "399001.SZ"),
        ("创业板指", "399006.SZ"), ("科创50", "000688.SS"),
        ("恒生指数", "%5EHSI"), ("恒生科技", "%5EHSTECH"),
    ]
    quotes, failures, last_dates = {}, [], []
    for label, symbol in specs:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5d&interval=1d"
        data = safe_request(url)
        try:
            result = data["chart"]["result"][0]
            quote_0 = result["indicators"]["quote"][0]
            closes = [x for x in quote_0["close"] if x is not None]
            volumes = [x for x in quote_0.get("volume", []) if x is not None]
            if len(closes) < 2:
                raise ValueError("报价记录不足")
            price, previous = closes[-1], closes[-2]
            vol = volumes[-1] if volumes else 0
            quotes[label] = {"price": price, "change_pct": (price / previous - 1) * 100,
                             "volume": vol,
                             "currency": result.get("meta", {}).get("currency", "")}
            # 最后收盘日期（用于当天检验；非交易时段为最近交易日）
            ts_list = result.get("timestamp") or []
            if ts_list:
                last = datetime.fromtimestamp(ts_list[-1], CST).strftime("%Y-%m-%d")
                last_dates.append(last)
        except (KeyError, TypeError, IndexError, ValueError, ZeroDivisionError) as exc:
            failures.append(f"{label}: {exc}")
    status = "success" if quotes else "unavailable"
    content_date = max(last_dates) if last_dates else None
    is_today = content_date == _today_display()
    if quotes:
        print(f"  ✅ 成功抓取 {len(quotes)}/{len(specs)} 个实时行情（数据日期 {content_date}）")
    else:
        print("  ⚠️ 实时行情暂不可用；日报将明确显示数据暂缺")
    return _source_result("Yahoo Finance Chart", status,
                          is_today=is_today, content_date=content_date,
                          quotes=quotes,
                          error="；".join(failures[:2]) or None,
                          partial=len(quotes) != len(specs))


def _quote_value(market, label, precision=2):
    quote = market.get("quotes", {}).get(label)
    if not quote:
        return f'<span style="color:{C_FAINT};">■ 数据暂缺</span>', C_FAINT
    price = quote["price"]
    pct = float(quote["change_pct"])
    color = C_GREEN if pct > 0 else (C_RED if pct < 0 else C_AMBER)
    # 数值用白色、涨跌用带箭头的高对比色块；即使用户存在色觉差异，也能靠 ▲/▼/■ 判断。
    value = (f'<span style="display:inline-block;color:{C_INK};font-size:13px;font-weight:900;'
             f'font-family:{FONT_MONO};padding-right:6px;">{price:,.{precision}f}</span>'
             f'{_trend_badge(pct)}')
    return value, color


# 数据源 1：全球头条（Google News 中文版）
# ============================================================
GOOGLE_NEWS_RSS = {
    "zh": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
}


def _rfc2822_cst(pub_raw):
    """解析 RFC 2822 时间（如 Google News pubDate）为北京时间 datetime；失败返回 None。"""
    if not pub_raw:
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pub_raw).astimezone(CST)
    except Exception:
        return None


def fetch_google_news():
    """抓取 Google News 商业/财经头条（替换原 Yahoo Finance News 数据源）。

    直接抓 Google News 中文版，标题本身即中文，无需翻译；
    每条返回 {title, source, url, published_cst, is_today}。
    """
    print("📡 正在抓取 Google News 全球头条...")
    url = GOOGLE_NEWS_RSS["zh"]
    xml_text = safe_request(url, is_json=False, timeout=15)

    items = []
    if xml_text:
        try:
            root = ET.fromstring(xml_text)
            for item in root.findall("channel/item")[:12]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub = (item.findtext("pubDate") or "").strip()
                if not title:
                    continue
                # Google News 标题形如「原标题 - 来源名」，拆出来源
                src = ""
                m = re.search(r"\s+-\s+([^-]+)$", title)
                if m:
                    src = m.group(1).strip()
                    title = title[: m.start()].strip()
                pub_dt = _rfc2822_cst(pub)
                items.append({
                    "title": title,
                    "source": src,
                    "url": link,
                    "published": pub,
                    "published_cst": pub_dt.strftime("%Y-%m-%d %H:%M") if pub_dt else "—",
                    "is_today": _date_is_today(pub_dt),
                })
        except Exception as exc:
            print(f"  ⚠️ Google News RSS 解析失败: {exc}")

    if not items:
        print("  ⚠️ Google News 暂不可用，不显示历史兜底头条")
        return _source_result("Google News", "unavailable", headlines=[], error="未取得有效新闻")

    content_date = max((it["published_cst"][:10] for it in items if it["published_cst"] != "—"), default=None)
    is_today = any(it["is_today"] for it in items)
    print(f"  ✅ 成功抓取 {len(items)} 条全球头条（中文源，最新 {content_date}）")
    return _source_result("Google News", "success",
                          is_today=is_today, content_date=content_date,
                          headlines=items[:8])

# 数据源 2：国家政策官方网站（中国政府网「最新政策」）
# ============================================================
# 中国政府网是国务院办公厅主办的中央人民政府门户网站。这里直接读取其「最新政策」
# 页面，不经过搜索引擎、转载媒体或 RSSHub；每条政策保留政府网原文链接与发布日期，
# 作为政策因子的独立输入。页面结构偶有调整，因此解析采用标准库正则，并只接受
# gov.cn/zhengce/ 下的政策正文链接，避免把导航、图片和第三方链接误计入因子。
GOV_POLICY_URL = "https://www.gov.cn/zhengce/zuixin/"
GOV_POLICY_FALLBACK_URL = "https://www.gov.cn/zhengce/"
GOV_POLICY_URLS = (GOV_POLICY_URL, GOV_POLICY_FALLBACK_URL)
GOV_POLICY_SOURCE_NAME = "中国政府网·最新政策"
NATIONAL_POLICY_TOP_N = int(os.environ.get("OCTOPUS_NATIONAL_POLICY_TOP_N", "30"))

_GOV_POLICY_ARTICLE_RE = re.compile(
    r"/zhengce/(?:content/)?20\d{2}(?:(?:\d{2})|(?:[-_/]\d{1,2}){1,2})/content_\d+\.html?$",
    re.I,
)
_GOV_POLICY_DATE_RE = re.compile(
    r"(?<!\d)(20\d{2})\s*(?:[-/.年－—])\s*(\d{1,2})\s*(?:[-/.月－—])\s*(\d{1,2})\s*(?:日|号)?",
)


def _strip_html_text(fragment):
    """去掉 HTML 标签并解码实体，供政府网列表标题/日期解析使用。"""
    fragment = fragment or ""
    fragment = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", fragment)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = _html_unescape(fragment).replace("\xa0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", fragment).strip()


def _normalise_policy_date(value):
    """把政府网常见的 YYYY-MM-DD / YYYY/MM/DD / 中文日期归一化。"""
    if not value:
        return ""
    match = _GOV_POLICY_DATE_RE.search(str(value))
    if not match:
        return ""
    year, month, day = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _gov_policy_date_after_anchor(html_text, anchor_end, anchor_start):
    """从政策链接所在列表项提取发布日期；没有明确日期时返回空字符串。

    日期必须来自链接附近的可见列表文本，不从 URL 的月份或抓取日期推断，
    这样不会把未知发布日期伪装成当天政策。
    """
    lower = html_text.lower()
    item_end_match = re.search(r"</li\s*>", lower[anchor_end:anchor_end + 1200], re.I)
    if item_end_match:
        item_end = anchor_end + item_end_match.start()
    else:
        # 非 li 模板也常把每项写成连续的 div/a；避免把下一条政策的日期
        # 错配给当前标题，只在下一个链接前寻找当前项的尾部日期。
        next_anchor = re.search(r"<a\b", lower[anchor_end:], re.I)
        item_end = (anchor_end + next_anchor.start()
                    if next_anchor else anchor_end + 800)
    item_end = min(len(html_text), item_end)
    tail = _strip_html_text(html_text[anchor_end:item_end])
    date = _normalise_policy_date(tail)
    if date:
        return date

    # 少数模板把日期放在链接前的同一 <li> 中。
    item_start = lower.rfind("<li", 0, anchor_start)
    if item_start >= 0:
        prefix = _strip_html_text(html_text[item_start:anchor_start])
        date = _normalise_policy_date(prefix)
    return date


def _parse_gov_policy_html(html_text, limit=None):
    """解析中国政府网「最新政策」列表，返回带官方原文链接的政策条目。

    返回字段兼容新闻标题存档：title/source/url/date/published_cst/is_today/official。
    只有政策正文链接会被接受；没有日期的条目仍保留展示，但不会进入自然日政策窗口。
    """
    if isinstance(html_text, bytes):
        html_text = html_text.decode("utf-8", errors="replace")
    if not isinstance(html_text, str) or not html_text.strip():
        return []
    try:
        limit = max(1, int(NATIONAL_POLICY_TOP_N if limit is None else limit))
    except (TypeError, ValueError):
        limit = 30

    items, seen = [], set()
    anchor_re = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a\s*>", re.I | re.S)
    for match in anchor_re.finditer(html_text):
        attrs = match.group("attrs")
        href_match = re.search(r'\bhref\s*=\s*(["\'])(.*?)\1', attrs, re.I | re.S)
        if not href_match:
            continue
        href = _html_unescape(href_match.group(2).strip())
        url = urljoin(GOV_POLICY_URL, href)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not (
                host == "gov.cn" or host.endswith(".gov.cn")):
            continue
        path = parsed.path or ""
        if not _GOV_POLICY_ARTICLE_RE.search(path):
            continue
        title = _strip_html_text(match.group("body"))
        if len(title) < 2:
            continue
        date = _gov_policy_date_after_anchor(html_text, match.end(), match.start())
        key = (url, title)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title[:200],
            "source": "中国政府网",
            "url": url,
            "date": date,
            "time": date,
            "published_cst": date or "—",
            "is_today": bool(date and date == _today_display()),
            "official": True,
        })
        if len(items) >= limit:
            break
    return items


def fetch_gov_policy():
    """抓取中国政府网最新政策，作为政策因子的官方发布信息源。

    优先读取 ``/zhengce/zuixin/``，该页面失败或结构变化时再读取政策首页。
    不以历史存档兜底：抓不到官方页面就明确返回 unavailable。
    """
    print("📡 正在抓取中国政府网·最新政策（政策因子官方源）...")
    failures = []
    for url in GOV_POLICY_URLS:
        html_text = safe_request(url, is_json=False, timeout=15)
        items = _parse_gov_policy_html(html_text)
        if not items:
            failures.append(f"{url}: 未解析到政策正文")
            continue
        dates = [it["date"] for it in items if it.get("date")]
        content_date = max(dates) if dates else None
        is_today = any(it.get("is_today") for it in items)
        print(f"  ✅ 中国政府网抓取 {len(items)} 条最新政策（最新发布 {content_date or '日期暂缺'}）")
        return _source_result(
            GOV_POLICY_SOURCE_NAME, "success", is_today=is_today,
            content_date=content_date, headlines=items,
            official=True, page_url=url,
            error="；".join(failures[:1]) or None,
            partial=len(items) < min(5, NATIONAL_POLICY_TOP_N),
        )

    print("  ⚠️ 中国政府网最新政策暂不可用，不使用历史政策兜底")
    return _source_result(
        GOV_POLICY_SOURCE_NAME, "unavailable", headlines=[], official=True,
        page_url=GOV_POLICY_URL, error="；".join(failures[:2]) or "未取得官方政策信息",
    )


# 公开两个语义等价的入口，便于外部定时任务/测试按「国家政策」或「政府网」命名调用。
fetch_national_policy = fetch_gov_policy
fetch_national_policy_updates = fetch_gov_policy
fetch_national_policies = fetch_gov_policy


# 数据源 3：东方财富快讯（免费 API，5 条最新新闻）
# ============================================================
EASTMONEY_NEWS_URLS = [
    "https://np-weblist.eastmoney.com/comm/web/getNewsByColumns",
    "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns",
]


def fetch_eastmoney_news():
    """抓取东方财富最新财经新闻（免费接口，无 API Key，取 5 条）。"""
    print("📡 正在抓取东方财富快讯...")
    params = {
        "client": "web", "biz": "web_news_col", "column": "350",
        "order": "1", "needInteractData": "0",
        "page_index": "1", "page_size": "10",
    }
    news, content_dates = [], []
    for url in EASTMONEY_NEWS_URLS:
        data = safe_request(url, params=params, timeout=12)
        if not data:
            continue
        try:
            lst = ((data.get("data") or {}).get("list")) or []
        except AttributeError:
            lst = []
        for it in lst[:10]:
            title = re.sub(r"<[^>]+>", "", (it.get("title") or it.get("name") or "")).strip()
            if not title:
                continue
            raw_time = str(it.get("showTime") or it.get("createTime") or it.get("publishTime") or "")
            news.append({
                "title": title[:120],
                "url": it.get("url") or it.get("articleUrl") or "",
                "time": raw_time[:16],
                "summary": re.sub(r"<[^>]+>", "", (it.get("summary") or it.get("digest") or ""))[:80],
                "is_today": raw_time[:10] == _today_display(),
            })
            if raw_time[:10]:
                content_dates.append(raw_time[:10])
        if news:
            break

    if not news:
        print("  ⚠️ 东方财富快讯暂不可用，不显示历史兜底资讯")
        return _source_result("东方财富", "unavailable", headlines=[], error="未取得有效资讯")
    content_date = max(content_dates) if content_dates else None
    is_today = any(n["is_today"] for n in news)
    print(f"  ✅ 成功抓取 {len(news)} 条东财快讯（最新 {content_date or '—'}）")
    return _source_result("东方财富", "success",
                          is_today=is_today, content_date=content_date,
                          headlines=news[:5])


# ============================================================
# 数据源 4：热门榜单（最近交易日收盘后 A股/港股/美股 成交量前五）
# ============================================================
HOT_STOCK_TOP_N = 5

HOT_STOCK_MARKETS = {
    "A股": {"fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "desc": "沪深京 A 股"},
    "港股": {"fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2", "desc": "港股主板"},
    "美股": {"fs": "m:105,m:106,m:107", "desc": "美股（纽交所/纳斯达克/美交所）"},
}


def fetch_hot_stocks():
    """抓取最近一个交易日收盘后的 A股/港股/美股成交量前五（东方财富 push2 免费接口）。

    返回 _source_result：markets={市场名: {"desc", "stocks":[{code,name,price,amount}]}}
    """
    print(f"📡 正在抓取 A股/港股/美股成交量前{HOT_STOCK_TOP_N}...")
    markets = {}
    any_stock = False
    for label, cfg in HOT_STOCK_MARKETS.items():
        params = {
            "pn": "1", "pz": str(HOT_STOCK_TOP_N), "po": "1", "np": "1", "fltt": "2", "invt": "2",
            "fid": "f6", "fs": cfg["fs"], "fields": "f2,f3,f4,f6,f12,f14",
        }
        data = safe_request("https://push2.eastmoney.com/api/qt/clist/get",
                            params=params, timeout=12)
        stocks = []
        try:
            diff = ((data or {}).get("data") or {}).get("diff") or []
            for it in diff[:HOT_STOCK_TOP_N]:
                name = str(it.get("f14") or "").strip()
                if not name:
                    continue
                stocks.append({
                    "code": str(it.get("f12") or ""),
                    "name": name,
                    "price": it.get("f2"),
                    "change_pct": it.get("f3"),
                    "amount": it.get("f6"),
                })
        except Exception:
            stocks = []
        markets[label] = {"desc": cfg["desc"], "stocks": stocks}
        if stocks:
            any_stock = True
        print(f"  {'✅' if stocks else '⚠️'} {label}成交量前{HOT_STOCK_TOP_N}: {len(stocks)} 只")

    if not any_stock:
        print("  ⚠️ 热门榜单暂不可用，不显示历史兜底榜单")
        return _source_result("东方财富热门榜", "unavailable", markets=markets,
                              error="push2 接口未返回有效数据")

    # 榜单即最近交易日收盘数据；标注数据日期为最近交易日（无法从接口取得时用当天）
    content_date = _today_display()
    print("  ✅ 热门榜单抓取完成（数据为最近交易日收盘后）")
    return _source_result("东方财富热门榜", "success",
                          is_today=True, content_date=content_date,
                          markets=markets)


# ============================================================
# 数据源 5：A股大盘全景复盘
# （指数表现 + 涨跌家数 + 成交额 + 北向资金 + 板块热力）
# ------------------------------------------------------------
# 使用东方财富 push2 / push2his 免费公开接口（与「热门榜单」同源）：
#   · 指数表现：ulist.np/get 一次返回八大宽基指数最新价、涨跌幅与成交额；
#   · 涨跌家数：指数行情附带的交易所统计字段 f104/f105/f106（沪市 = 上证指数、
#     深市 = 深证成指、京市 = 北证50）合计为沪深京市场宽度；
#   · 成交额：沪深京指数成分成交额（f6，元）合计；上一交易日成交额用
#     push2his 日 K（fields2=f51,f57）补齐，用于计算环比增减；
#   · 南北向资金：港交所自 2024-08-19 起停止披露南北向实时 / 每日净买入额，仅盘后
#     公布当日成交总额。本模块按东财数据中心历史报表 RPT_MUTUAL_DEAL_HISTORY 取
#     最近 N 条披露记录（MUTUAL_TYPE=005 北向合计 / 006 南向合计），按「前一收盘」
#     规则取最近一个完整交易日（最新行是今天则取前一日；否则取最后一日），
#     将 DEAL_AMT（百万元）换算为亿元；读取不到就明确标注暂缺——绝不编造净买入数字；
#   · 板块热力：clist/get 行业板块（fs=m:90+t:2）按涨跌幅排序，取领涨 / 领跌
#     各 PANORAMA_SECTOR_TOP_N 名，附主力净流入与领涨股。
# 任何一个子请求失败只影响对应子块；八大指数与市场宽度全失败才整体标记
# unavailable。规则合成（情绪定调等）确定性可复现，均为非投资建议。
# ============================================================
PANORAMA_INDEX_SPECS = [
    ("1.000001", "上证指数"), ("0.399001", "深证成指"),
    ("0.399006", "创业板指"), ("1.000688", "科创50"),
    ("0.899050", "北证50"), ("1.000300", "沪深300"),
    ("1.000016", "上证50"), ("1.000905", "中证500"),
]
# 各交易所「全市场涨跌家数」的载体指数（f104/f105/f106 为该交易所股票统计）
PANORAMA_BREADTH_SOURCES = [("1.000001", "沪"), ("0.399001", "深"), ("0.899050", "京")]
PANORAMA_SECTOR_TOP_N = int(os.environ.get("OCTOPUS_PANORAMA_SECTOR_TOP_N", "5"))
PANORAMA_NORTH_POLICY_NOTE = (
    "港交所自 2024-08-19 起停止披露南北向资金实时 / 每日净买入额，仅盘后公布当日成交总额；"
    "本页按最近一个完整交易日（前一收盘）展示北向、南向成交总额，不再估算净买入。")


def _panorama_float(val):
    """把东财字段（可能为 "-" / None / ""）转成 float；不可解析返回 None。"""
    try:
        if val is None or val == "-" or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _panorama_int(val):
    """同 _panorama_float，但转成 int（涨跌家数等统计字段）。"""
    num = _panorama_float(val)
    return int(num) if num is not None else None


def _fetch_panorama_indices():
    """一次请求拉取全部宽基指数行情；返回 (按 PANORAMA_INDEX_SPECS 排序的指数列表,
    {代码: 行情}, 报价时间字符串|None)。"""
    params = {
        "fltt": "2", "invt": "2",
        "secids": ",".join(secid for secid, _ in PANORAMA_INDEX_SPECS),
        "fields": "f2,f3,f4,f6,f12,f14,f15,f16,f17,f18,f104,f105,f106,f124",
    }
    data = safe_request("https://push2.eastmoney.com/api/qt/ulist.np/get",
                        params=params, timeout=12)
    rows = ((data or {}).get("data") or {}).get("diff") or []
    by_code, quote_ts = {}, []
    for it in rows:
        code = str(it.get("f12") or "")
        price = _panorama_float(it.get("f2"))
        chg_pct = _panorama_float(it.get("f3"))
        if not code or price is None or chg_pct is None:
            continue
        by_code[code] = {
            "code": code,
            "name": str(it.get("f14") or "").strip() or code,
            "price": price, "chg_pct": chg_pct,
            "chg": _panorama_float(it.get("f4")),
            "amount": _panorama_float(it.get("f6")),
            "open": _panorama_float(it.get("f17")), "high": _panorama_float(it.get("f15")),
            "low": _panorama_float(it.get("f16")), "prev_close": _panorama_float(it.get("f18")),
            "up": _panorama_int(it.get("f104")), "down": _panorama_int(it.get("f105")),
            "flat": _panorama_int(it.get("f106")),
        }
        ts = _panorama_int(it.get("f124"))
        if ts:
            quote_ts.append(ts)
    indices = []
    for secid, label in PANORAMA_INDEX_SPECS:
        row = by_code.get(secid.split(".", 1)[1])
        if row:
            row["name"] = label  # 统一正式中文名，规避行情源简称差异
            indices.append(row)
    quote_time = (datetime.fromtimestamp(max(quote_ts), CST).strftime("%Y-%m-%d %H:%M:%S")
                  if quote_ts else None)
    return indices, by_code, quote_time


def _fetch_panorama_prev_amounts():
    """取沪 / 深 / 京载体指数最近两根日 K 的成交额（fields2=f51,f57，单位元）。

    返回 {secid: [(日期, 成交额), ...]}；单交易所失败只影响该交易所。
    """
    out = {}
    for secid, _ in PANORAMA_BREADTH_SOURCES:
        params = {"secid": secid, "klt": "101", "fqt": "0", "lmt": "2", "end": "20500101",
                  "fields1": "f1,f2,f3", "fields2": "f51,f57"}
        data = safe_request("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                            params=params, timeout=12)
        pairs = []
        try:
            klines = (((data or {}).get("data") or {}).get("klines")) or []
            for line in klines[-2:]:
                parts = str(line).split(",")
                if len(parts) >= 2:
                    amt = _panorama_float(parts[1])
                    if amt is not None:
                        pairs.append((parts[0].strip(), amt))
        except Exception:
            pairs = []
        out[secid] = pairs
    return out


PANORAMA_HSGT_HISTORY_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _fetch_panorama_northbound():
    """南北向资金：2024-08-19 起不再披露净买入，读最近完整交易日（前一收盘）成交总额。

    数据源：东财数据中心历史报表 RPT_MUTUAL_DEAL_HISTORY。
    其中 MUTUAL_TYPE=005 为「北向合计」（沪股通+深股通）、006 为「南向合计」
    （港股通沪+港股通深）；DEAL_AMT 为该日成交总额（单位：百万元），
    披露口径调整后北向净买额列缺失，但成交总额仍更新。

    前一天收盘口径：若最新日期记录等于今天，则取它前一日（最近完整交易日）；
    否则取最后一日（盘前 / 非交易日 / 当日尚未收市场景下，最后一日即最近完整交易日）。
    读不到任何数值 → available=False / south_available=False 并给出原因。
    """
    params = {
        "reportName": "RPT_MUTUAL_DEAL_HISTORY",
        "columns": "ALL",
        "pageNumber": "1",
        "pageSize": "40",
        "sortColumns": "TRADE_DATE,MUTUAL_TYPE",
        "sortTypes": "-1,1",
        "source": "WEB",
        "client": "WEB",
    }
    data = safe_request(PANORAMA_HSGT_HISTORY_URL, params=params, timeout=12)
    note = PANORAMA_NORTH_POLICY_NOTE
    today_date = _today_display()

    def _pick(rows):
        """按「前一收盘」规则从 成交总额记录 里取最近一个完整交易日数据。

        rows 为该方向（北向=005 / 南向=006）的逐日记录；
        DEAL_AMT 单位百万元，转换为亿元（÷100）。
        """
        parsed = []
        for it in rows or []:
            raw_date = str(it.get("TRADE_DATE") or "")[:10]
            deal_amt = _panorama_float(it.get("DEAL_AMT"))
            if not raw_date or deal_amt is None:
                continue
            parsed.append((raw_date, deal_amt))
        parsed.sort(key=lambda item: item[0])
        if not parsed:
            return {"available": False, "amount_yi": None, "date": None,
                    "error": "接口未返回有效记录"}
        # 最新行是今天 → 取前一行作为「前一收盘」；否则最后一行即最近完整交易日。
        idx_today = next((i for i, (d, _) in enumerate(parsed) if d == today_date), None)
        if idx_today is not None and idx_today > 0:
            date, deal_amt = parsed[idx_today - 1]
        else:
            date, deal_amt = parsed[-1]
        if deal_amt is None:
            return {"available": False, "amount_yi": None, "date": date,
                    "error": "披露口径内暂无成交总额数值"}
        return {"available": True, "amount_yi": deal_amt / 100.0,
                "date": date, "error": None}

    try:
        root = ((data or {}).get("result") or {}).get("data") or []
        north = _pick([it for it in root if str(it.get("MUTUAL_TYPE") or "") == "005"])
        south = _pick([it for it in root if str(it.get("MUTUAL_TYPE") or "") == "006"])
    except Exception as exc:
        north = {"available": False, "amount_yi": None, "date": None, "error": str(exc)}
        south = {"available": False, "amount_yi": None, "date": None, "error": str(exc)}

    return {
        "available": bool(north["available"]),
        "amount_yi": north["amount_yi"],
        "date": north["date"],
        "error": north.get("error"),
        "south_available": bool(south["available"]),
        "south_amount_yi": south["amount_yi"],
        "south_date": south["date"],
        "south_error": south.get("error"),
        "policy_note": note,
    }


def _fetch_panorama_sectors():
    """行业板块领涨 / 领跌各 PANORAMA_SECTOR_TOP_N 名（fs=m:90+t:2，按涨跌幅排序）。"""
    result = {"leading": [], "lagging": []}
    for key, po in (("leading", "1"), ("lagging", "0")):
        params = {"pn": "1", "pz": str(PANORAMA_SECTOR_TOP_N), "po": po, "np": "1",
                  "fltt": "2", "invt": "2", "fid": "f3", "fs": "m:90+t:2",
                  "fields": "f2,f3,f12,f14,f62,f104,f105,f128,f136"}
        data = safe_request("https://push2.eastmoney.com/api/qt/clist/get",
                            params=params, timeout=12)
        rows = []
        try:
            diff = ((data or {}).get("data") or {}).get("diff") or []
            for it in diff[:PANORAMA_SECTOR_TOP_N]:
                name = str(it.get("f14") or "").strip()
                chg = _panorama_float(it.get("f3"))
                if not name or chg is None:
                    continue
                rows.append({
                    "code": str(it.get("f12") or ""), "name": name, "chg_pct": chg,
                    "main_inflow": _panorama_float(it.get("f62")),
                    "up": _panorama_int(it.get("f104")), "down": _panorama_int(it.get("f105")),
                    "lead_stock": str(it.get("f128") or "").strip(),
                    "lead_stock_pct": _panorama_float(it.get("f136")),
                })
        except Exception:
            rows = []
        result[key] = rows
    return result


def _panorama_breadth_mood(ratio):
    """由涨跌比给出确定性情绪定调（阈值规则，可复现，非投资建议）。"""
    if ratio is None:
        return "数据不足"
    if ratio >= 2.0:
        return "普涨强势"
    if ratio >= 1.2:
        return "偏多震荡"
    if ratio >= 0.8:
        return "多空均衡"
    if ratio >= 0.5:
        return "偏空承压"
    return "普跌弱势"


def fetch_market_panorama():
    """抓取 A股大盘全景复盘：指数表现 / 涨跌家数 / 成交额 / 北向资金 / 板块热力。"""
    print("📡 正在抓取 A股大盘全景复盘（指数/涨跌家数/成交额/北向/板块）...")
    errors = []

    indices, by_code, quote_time = _fetch_panorama_indices()

    # ---- 涨跌家数（沪深京合计）----
    breadth = None
    b_parts, b_missing = {}, []
    for secid, exch in PANORAMA_BREADTH_SOURCES:
        row = by_code.get(secid.split(".", 1)[1])
        if row and row.get("up") is not None and row.get("down") is not None:
            b_parts[exch] = {"up": row["up"], "down": row["down"], "flat": row.get("flat")}
        else:
            b_missing.append(exch)
    if b_parts:
        up = sum(p["up"] for p in b_parts.values())
        down = sum(p["down"] for p in b_parts.values())
        flat = sum((p.get("flat") or 0) for p in b_parts.values())
        ratio = round(up / down, 2) if down else None
        breadth = {"up": up, "down": down, "flat": flat, "ratio": ratio,
                   "mood": _panorama_breadth_mood(ratio),
                   "markets": b_parts, "partial": bool(b_missing)}

    # ---- 成交额（沪深京合计 + 较上一交易日环比）----
    turnover = None
    amount_by_exch = {}
    for secid, exch in PANORAMA_BREADTH_SOURCES:
        row = by_code.get(secid.split(".", 1)[1])
        if row and row.get("amount"):
            amount_by_exch[exch] = row["amount"]
    if amount_by_exch:
        prev_total = None
        try:
            klines = _fetch_panorama_prev_amounts()
            quote_date = (quote_time or "")[:10] or None
            prev_sum, prev_ok = 0.0, 0
            for secid, _ in PANORAMA_BREADTH_SOURCES:
                pairs = klines.get(secid) or []
                if not pairs:
                    continue
                # 最新一根 K 线日期 == 指数报价日 → 其前一根才是「上一交易日」；
                # 否则最新一根即最近完整交易日（盘前 / 盘中 / 非交易日场景）。
                if quote_date and len(pairs) >= 2 and pairs[-1][0] == quote_date:
                    prev_pair = pairs[-2]
                else:
                    prev_pair = pairs[-1]
                if prev_pair and prev_pair[1]:
                    prev_sum += prev_pair[1]
                    prev_ok += 1
            if prev_ok >= 2 and prev_sum > 0:  # 至少沪深两市齐备才给环比，避免口径误导
                prev_total = prev_sum
        except Exception as exc:
            errors.append(f"上日成交额: {exc}")
        cur_total = sum(amount_by_exch.values())
        turnover = {
            "total": cur_total,
            "sh_sz": amount_by_exch.get("沪", 0.0) + amount_by_exch.get("深", 0.0),
            "by_market": amount_by_exch,
            "prev_total": prev_total,
            "chg_pct": (cur_total / prev_total - 1) * 100 if prev_total else None,
            "partial": len(amount_by_exch) < 3,
        }

    # ---- 南北向资金（前一收盘成交总额启发式读取 + 披露政策说明）----
    north = _fetch_panorama_northbound()
    if not north.get("available"):
        errors.append(f"北向成交总额: {north.get('error') or '暂缺'}")
    if not north.get("south_available"):
        errors.append(f"南向成交总额: {north.get('south_error') or '暂缺'}")

    # ---- 板块热力（领涨 / 领跌行业板块）----
    sectors = _fetch_panorama_sectors()
    if not sectors["leading"] and not sectors["lagging"]:
        errors.append("板块热力: 行业板块接口未返回有效数据")

    if not indices and not breadth:
        print("  ⚠️ A股大盘全景暂不可用；日报将明确显示数据暂缺")
        return _source_result("东方财富·A股全景", "unavailable",
                              indices=[], breadth=None, turnover=None,
                              north=north, sectors=sectors, quote_time=quote_time,
                              error="；".join(errors[:3]) or "push2 接口未返回有效数据")

    content_date = (quote_time or "")[:10] or _today_display()
    is_today = content_date == _today_display()
    north_ok = "✓" if (north.get("available") and north.get("south_available")) else \
               ("部分" if (north.get("available") or north.get("south_available")) else "暂缺")
    print(f"  ✅ 全景复盘：指数 {len(indices)} 只 / "
          f"涨跌家数 {'齐' if breadth else '缺'} / "
          f"板块 {len(sectors['leading'])}+{len(sectors['lagging'])} / "
          f"南北向 {north_ok}")
    return _source_result("东方财富·A股全景", "success",
                          is_today=is_today, content_date=content_date,
                          indices=indices, breadth=breadth, turnover=turnover,
                          north=north, sectors=sectors, quote_time=quote_time,
                          error="；".join(errors[:3]) or None,
                          partial=bool(errors or (breadth or {}).get("partial")))


# ============================================================
# 数据源 6：A股资讯（新浪财经）
# ============================================================
def fetch_sina_headlines():
    """抓取新浪财经 A 股资讯"""
    print("📡 正在抓取 A 股资讯...")

    headlines = []

    # 新浪滚动新闻 API
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    params = {
        "pageid": "153",
        "lid": "2509",
        "num": "20",
        "page": "1",
    }

    data = safe_request(url, params=params)

    if data and "result" in data and "data" in data["result"]:
        for item in data["result"]["data"][:10]:
            title = item.get("title", "") or item.get("intro", "")
            if title:
                headlines.append(title.strip())

    # 首页兜底
    if not headlines:
        sina_url = "https://finance.sina.com.cn/"
        html = safe_request(sina_url, is_json=False)
        if html:
            titles = re.findall(r'target="_blank"[^>]*>([^<]{10,100})</a>', html)
            for t in titles[:10]:
                clean = t.strip()
                if clean and not clean.startswith("http"):
                    headlines.append(clean)

    if not headlines:
        print("  ⚠️ 新浪财经暂不可用，不显示历史兜底资讯")
        return _source_result("新浪财经", "unavailable", headlines=[], error="未取得有效资讯")
    print(f"  ✅ 成功抓取到 {len(headlines)} 条 A 股资讯（本次抓取 = 当天内容）")
    return _source_result("新浪财经", "success",
                          is_today=True, content_date=_today_display(),
                          headlines=headlines[:5])


# 数据源 7：港股名家频道（YouTube / 通用 RSS / 需登录平台）
# ============================================================
def resolve_channel_id(channel):
    """解析频道的 channel_id：优先使用配置的 channel_id，否则通过 handle 页面解析。"""
    cid = channel.get("channel_id")
    if cid:
        return cid
    handle = (channel.get("handle") or "").lstrip("@")
    if not handle:
        return None
    html = safe_request(f"https://www.youtube.com/@{handle}", is_json=False, timeout=12)
    if not html:
        return None
    m = re.search(r'"channelId":"(UC[0-9A-Za-z_-]{22})"', html)
    if m:
        return m.group(1)
    m = re.search(r'"externalId":"(UC[0-9A-Za-z_-]{22})"', html)
    return m.group(1) if m else None


def _channel_item(title, url, pub_raw):
    """把一条频道内容的标题/链接/发布时间整理成统一结构（北京时间 + 是否当天）。"""
    pub_cst = _cst_from_iso(pub_raw)
    if pub_cst is None:  # 兼容 RSS 2.0 的 RFC 2822 格式（如 Fri, 01 Aug 2026 12:00:00 +0800）
        try:
            from email.utils import parsedate_to_datetime
            pub_cst = parsedate_to_datetime(pub_raw).astimezone(CST)
        except Exception:
            pub_cst = None
    return {
        "title": title,
        "url": url,
        "published": pub_raw,
        "published_cst": pub_cst.strftime("%Y-%m-%d %H:%M") if pub_cst else "—",
        "is_today": _date_is_today(pub_cst),
    }


def _parse_rss_items(xml_text, limit=8):
    """解析通用 RSS 2.0 / Atom 源，保留标题、摘要、链接与发布时间。"""
    items = []
    try:
        root = ET.fromstring(xml_text or "")
    except Exception:
        return []
    # RSS 2.0
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is not None:
            for item in channel.findall("item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub = (item.findtext("pubDate")
                       or item.findtext("dc:date", namespaces={"dc": "http://purl.org/dc/elements/1.1/"})
                       or "")
                summary = (item.findtext("description")
                           or item.findtext("content:encoded", namespaces={
                               "content": "http://purl.org/rss/1.0/modules/content/"})
                           or "")
                if title:
                    parsed = _channel_item(title, link, pub)
                    parsed["summary"] = summary
                    items.append(parsed)
                if len(items) >= limit:
                    break
    # Atom
    elif root.tag.endswith("feed"):
        for entry in root.findall("a:entry", YT_NS):
            title = (entry.findtext("a:title", "", YT_NS) or "").strip()
            link = ""
            for ln in entry.findall("a:link", YT_NS):
                if (ln.get("rel") or "alternate") == "alternate":
                    link = ln.get("href") or ""
                    break
            pub = (entry.findtext("a:published", "", YT_NS)
                   or entry.findtext("a:updated", "", YT_NS) or "")
            summary = (entry.findtext("a:summary", "", YT_NS)
                       or entry.findtext("a:content", "", YT_NS) or "")
            if title:
                parsed = _channel_item(title, link, pub)
                parsed["summary"] = summary
                items.append(parsed)
            if len(items) >= limit:
                break
    return items


def fetch_hk_channels():
    """抓取「港股名家频道」的最新内容。

    - kind="youtube"：YouTube 频道 RSS（无需 API Key），返回最新视频；
    - kind="rss"    ：通用 RSS / Atom 源（Medium、Substack 等）；
    - kind="manual" ：需登录 / 未配置来源，放入 unsupported（页面标注「暂缺」及原因，
                      绝不伪造内容）。

    返回 _source_result：channels=已抓取频道、unsupported=需登录/未配置频道。
    """
    print("📡 正在抓取港股名家频道...")
    channels, unsupported, failures = [], [], []
    for ch in HK_CHANNELS:
        name = ch.get("name", "?")
        kind = ch.get("kind", "youtube")

        if kind == "manual":
            unsupported.append({"name": name, "desc": ch.get("desc", ""),
                                "note": ch.get("note", "平台需登录，暂不支持自动抓取")})
            continue

        if kind == "rss":
            feed_url = (ch.get("feed_url") or "").strip()
            if not feed_url:
                unsupported.append({"name": name, "desc": ch.get("desc", ""),
                                    "note": ch.get("note", "未配置 feed 地址")})
                continue
            xml_text = safe_request(feed_url, is_json=False, timeout=12)
            items = _parse_rss_items(xml_text, limit=8)
            if items:
                channels.append({
                    "name": name, "desc": ch.get("desc", ""), "source": "RSS",
                    "url": feed_url, "videos": items,
                    "is_today": any(v["is_today"] for v in items),
                    "newest_date": next((v["published_cst"] for v in items if v["is_today"]),
                                        items[0]["published_cst"]),
                })
            else:
                msg = "自动抓取失败（源可能需登录/被限流，或地址无效），暂缺"
                unsupported.append({"name": name, "desc": ch.get("desc", ""), "note": msg})
                failures.append(f"{name}: {msg}")
            continue

        # kind == "youtube"
        cid = resolve_channel_id(ch)
        if not cid:
            msg = "无法解析频道 ID（handle 可能不存在或页面结构变化），暂缺"
            unsupported.append({"name": name, "desc": ch.get("desc", ""), "note": msg})
            failures.append(f"{name}: {msg}")
            continue
        xml_text = safe_request(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
            is_json=False, timeout=12,
        )
        videos = []
        try:
            root = ET.fromstring(xml_text or "")
            for entry in root.findall("a:entry", YT_NS)[:8]:
                title = (entry.findtext("a:title", "", YT_NS) or "").strip()
                published = entry.findtext("a:published", "", YT_NS) or ""
                vid = entry.findtext("yt:videoId", "", YT_NS) or ""
                if not title:
                    continue
                pub_cst = _cst_from_iso(published)
                videos.append({
                    "title": title,
                    "video_id": vid,
                    "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
                    "published": published,
                    "published_cst": pub_cst.strftime("%Y-%m-%d %H:%M") if pub_cst else "—",
                    "is_today": _date_is_today(pub_cst),
                })
        except Exception as exc:
            failures.append(f"{name}: {exc}")

        if videos:
            handle = (ch.get("handle") or "").lstrip("@")
            channel_url = f"https://www.youtube.com/@{handle}" if handle else \
                          f"https://www.youtube.com/channel/{cid}"
            channels.append({
                "name": name, "desc": ch.get("desc", ""), "source": "YouTube",
                "url": channel_url, "videos": videos,
                "is_today": any(v["is_today"] for v in videos),
                "newest_date": next((v["published_cst"] for v in videos if v["is_today"]),
                                    videos[0]["published_cst"]),
            })
        else:
            msg = "自动抓取失败（RSS 暂无内容或网络异常），暂缺"
            unsupported.append({"name": name, "desc": ch.get("desc", ""), "note": msg})
            failures.append(f"{name}: {msg}")

    # 全部已抓取频道中最新内容的日期（用于当天检验）
    all_dates = [v["published_cst"][:10] for ch in channels for v in ch["videos"]]
    newest_date = max(all_dates) if all_dates else None
    is_today = any(ch["is_today"] for ch in channels)

    if channels:
        print(f"  ✅ 成功抓取 {len(channels)}/{len(HK_CHANNELS)} 个频道"
              + (f"（含当天内容）" if is_today else f"（最新内容日期 {newest_date}）"))
        if unsupported:
            print(f"  🕐 {len(unsupported)} 个频道需登录/未配置，标注暂缺："
                  + "、".join(u["name"] for u in unsupported))
        return _source_result("港股名家频道", "success",
                              is_today=is_today, content_date=newest_date,
                              channels=channels, unsupported=unsupported,
                              error="；".join(failures[:3]) or None,
                              partial=len(channels) + len(unsupported) != len(HK_CHANNELS))

    if unsupported:
        print("  ⚠️ 暂无可自动抓取的频道；需登录/未配置：" + "、".join(u["name"] for u in unsupported))
        return _source_result("港股名家频道", "unavailable", channels=[], unsupported=unsupported,
                              error="；".join(failures[:3]) or "全部频道需登录或未配置自动抓取源")

    print("  ⚠️ 港股名家频道暂不可用，不显示历史内容兜底")
    return _source_result("港股名家频道", "unavailable", channels=[], unsupported=[],
                          error="；".join(failures[:3]) or "未取得有效内容")


# ============================================================
# 每日量化策略趋势跟踪线索：单一来源 Reddit（仅标题/热度/原始链接，不复制帖子正文）
# ============================================================
_PUBLIC_ALLOWED_HOSTS = {
    "reddit.com", "www.reddit.com", "old.reddit.com",
}


def _public_url(raw, base=""):
    """外链仅允许已列出的源站 HTTPS 主机，防止外部标题/链接注入日报。"""
    if not raw or any(c.isspace() or c in ('<', '>', '\\') for c in str(raw).strip()):
        return ""
    try:
        url = urljoin(base, str(raw).strip())
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname not in _PUBLIC_ALLOWED_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            return ""
    except ValueError:
        return ""
    return url


def _public_text(value, limit=160):
    """清理站点文本，限制每条摘录长度；HTML 转义在渲染时统一处理。"""
    text = re.sub(r"<[^>]*>", " ", _html_unescape(str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("…" if len(text) > limit else "")


def _public_recent(dt, now=None, hours=PUBLIC_SITE_WINDOW_HOURS):
    if not dt or dt.tzinfo is None:
        return False
    age = (now or datetime.now(CST)) - dt.astimezone(CST)
    return -timedelta(minutes=5) <= age <= timedelta(hours=hours)


def _public_site_result(name, items, *, latest=None, snapshot=False, note="", error=None):
    """保留全部可核实样本（条数上限已由采集端按板块/条数控制）；
    快照的「当天」是当日采集，不冒充当日发文/实时价格。"""
    items = [item for item in (items or []) if isinstance(item, dict)]
    is_today = bool(items) and (snapshot or any(it.get("is_today") for it in items))
    return _source_result(
        name, "success" if items else "unavailable", is_today=is_today,
        content_date=latest, url=PUBLIC_SITE_URLS[name], items=items,
        snapshot=bool(snapshot and items), note=note,
        error=error or ("未取得可核实的公开内容" if not items else None),
    )


# 10 个财经 / 投资 / 金融 / 经济类板块：(板块名, 中文名)；顺序用于抓取、栏目与审计展示。
_REDDIT_BOARDS = (
    ("stocks", "个股讨论"),
    ("investing", "综合投资"),
    ("wallstreetbets", "散户投机风向"),
    ("ValueInvesting", "价值投资"),
    ("economics", "宏观经济"),
    ("wallstreet", "华尔街金融"),
    ("options", "期权交易"),
    ("Forex", "外汇市场"),
    ("pennystocks", "小盘热股"),
    ("personalfinance", "个人理财"),
)
_REDDIT_HEADERS = {"User-Agent": "octopus-daily/1.0 (+https://github.com/k-macao/02)"}
_REDDIT_HOSTS = ("reddit.com", "www.reddit.com", "old.reddit.com")
# RSS 公开正文片段里的「N points / M comments」热度写法（JSON 兜底用 score/num_comments 字段）。
_REDDIT_HEAT_RE = re.compile(
    r"(\d[\d,.]*\s*k?)\s*points?\s*(\d[\d,.]*\s*k?)\s*comments?", re.I)


def _reddit_heat_from_html(fragment):
    """从 RSS 公开帖子片段提取热度数据；无法核实时返回空串，不猜测。"""
    text = re.sub(r"<[^>]*>", " ", _html_unescape(str(fragment or "")))
    m = _REDDIT_HEAT_RE.search(text)
    if not m:
        return ""
    return f" · {m.group(1).strip()} 赞 · {m.group(2).strip()} 评论"


def _reddit_item(community, title, url, published, *, heat="", now=None):
    """组装单条热帖样本：community 供栏目按板块分组，发布时间统一北京时间。"""
    now = now or datetime.now(CST)
    pub = published.strftime("%Y-%m-%d %H:%M")
    return {
        "title": title,
        "url": url,
        "detail": f"发布于 {pub}（北京时间）{heat}",
        "published_cst": pub,
        "community": community,
        "is_today": published.date() == now.date(),
    }


def _reddit_hot_items(xml_text, community, base, *, now=None):
    """解析板块公开热门（hot）feed，保留 feed 排序（即站点热度榜）。

    只接受带可验证发布时间的条目；超出 72 小时窗口的剔除；
    返回 (items, 最新日期)，每板块最多保留 REDDIT_POSTS_PER_BOARD 条。
    """
    parsed = _parse_rss_items(xml_text, limit=40)
    now = now or datetime.now(CST)
    items, latest, seen = [], None, set()
    for row in parsed:
        if len(items) >= REDDIT_POSTS_PER_BOARD:
            break
        raw_date = str(row.get("published") or "").strip()
        # 没有显式时区就不能确定自然日，拒绝用运行机器的本地时区猜测。
        if not re.search(r"(?:Z|[+-]\d{2}:?\d{2}|\bGMT|\bUTC)$", raw_date, re.I):
            continue
        pub = row.get("published_cst") or ""
        try:
            dt = datetime.strptime(pub, "%Y-%m-%d %H:%M").replace(tzinfo=CST)
        except ValueError:
            continue
        url = _public_url(row.get("url"), base)
        title = _public_text(row.get("title"), 125)
        if not (url and title and _public_recent(dt, now)):
            continue
        if url in seen:
            continue
        if not latest or dt > latest:
            latest = dt
        seen.add(url)
        items.append(_reddit_item(
            f"r/{community}", title, url, dt,
            heat=_reddit_heat_from_html(row.get("summary")), now=now))
    return items, (latest.strftime("%Y-%m-%d") if latest else None)


def _reddit_json_items(payload, community, *, now=None):
    """公开 feed 不可用时，仅读公开帖子 JSON 的标题/发帖时间/热度/永久链接。"""
    try:
        children = payload["data"]["children"]
    except (TypeError, KeyError):
        return [], None
    if not isinstance(children, list):
        return [], None
    now = now or datetime.now(CST)
    items, latest, seen = [], None, set()
    for child in children:
        if len(items) >= REDDIT_POSTS_PER_BOARD:
            break
        post = child.get("data", {}) if isinstance(child, dict) else {}
        if not isinstance(post, dict) or post.get("stickied") or post.get("over_18"):
            continue
        try:
            published = datetime.fromtimestamp(float(post["created_utc"]), timezone.utc).astimezone(CST)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            continue
        url = _public_url(post.get("permalink"), "https://www.reddit.com/")
        title = _public_text(post.get("title"), 125)
        if not (url and title and _public_recent(published, now)):
            continue
        if url in seen:
            continue
        if not latest or published > latest:
            latest = published
        seen.add(url)
        heat = ""
        try:
            score = int(post.get("score") or 0)
            comments = int(post.get("num_comments") or 0)
            if score > 0:
                heat = f" · {score:,} 赞" + (f" · {comments:,} 评论" if comments else "")
        except (TypeError, ValueError):
            heat = ""
        items.append(_reddit_item(f"r/{community}", title, url, published, heat=heat, now=now))
    return items, (latest.strftime("%Y-%m-%d") if latest else None)


def fetch_reddit():
    """逐板块并行读取公开热门（hot）feed；失败时试一次公开 JSON，再失败如实暂缺。

    每个板块取热门帖子前 5 条作为样本数据，栏目按板块顺序展示；
    社区观点未经核实，热度不等于事实或投资建议。
    """
    name = "Reddit"
    now = datetime.now(CST)

    def _fetch_board(board):
        community, _label = board
        base = f"https://www.reddit.com/r/{community}/"
        limit = REDDIT_POSTS_PER_BOARD * 2
        xml = safe_request(f"{base}hot/.rss?limit={limit}",
                           headers={**_REDDIT_HEADERS, "Accept": "application/atom+xml,application/xml"},
                           is_json=False, timeout=8)
        items, latest = _reddit_hot_items(xml, community, base, now=now)
        if not items:
            payload = safe_request(f"{base}hot.json?limit={limit}",
                                   headers={**_REDDIT_HEADERS, "Accept": "application/json"},
                                   timeout=8)
            items, latest = _reddit_json_items(payload, community, now=now)
        return community, items, latest

    board_results = {}
    with ThreadPoolExecutor(max_workers=len(_REDDIT_BOARDS)) as executor:
        futures = {executor.submit(_fetch_board, board): board
                   for board in _REDDIT_BOARDS}
        for future in futures:
            try:
                _community, items, latest = future.result()
            except Exception:
                items, latest = [], None
            board_results[_community] = (items, latest)

    items, unavailable, latest = [], [], None
    for community, _label in _REDDIT_BOARDS:
        board_items, board_latest = board_results[community]
        if board_latest and (not latest or board_latest > latest):
            latest = board_latest
        if board_items:
            items.extend(board_items)
        else:
            unavailable.append(f"r/{community}")
    note = ("只收录公开热帖的标题与热度作为趋势跟踪线索，供判断散户讨论风向与热门标的；"
            "社区观点未经核实，热度不等于事实或投资建议。")
    if unavailable:
        note += " 暂缺（访问受限或近72小时无新帖）：" + "、".join(unavailable) + "。"
    error = "十个板块的公开 feed / JSON 均不可用或近72小时无可验证的新帖"
    return _public_site_result(name, items, latest=latest, note=note, error=error)


def fetch_public_sites():
    """单一来源 Reddit 独立运行，失败不会拖垮主日报；始终返回审计记录。"""
    fetchers = (
        ("Reddit", fetch_reddit),
    )
    results = {}
    with ThreadPoolExecutor(max_workers=len(fetchers)) as executor:
        futures = [(name, executor.submit(fn)) for name, fn in fetchers]
        for name, future in futures:
            try:
                result = future.result()
                if (not isinstance(result, dict) or result.get("source") != name
                        or result.get("status") not in ("success", "unavailable")
                        or not isinstance(result.get("items"), list)):
                    raise ValueError("采集返回格式异常")
            except Exception as exc:
                print(f"  ⚠️ {name} 采集失败（{type(exc).__name__}）")
                result = _public_site_result(name, [], error="公开数据解析失败或暂时不可用")
            results[name] = result
            print(f"  {'✅' if result['status'] == 'success' else '⚠️'} {name}: "
                  f"{len(result.get('items') or [])} 条热帖样本")
    return results


# ============================================================
# 数据采集主函数
# ============================================================
def fetch_hk_quant():
    """数据源 8：港股量化引擎（概率预测 + 资金流动性 + 推进式校验）。

    跑通整条量化流水线：Yahoo 港股指數/个股日线 → 五因子 → 历史滚动重算 →
    分桶+保序+逻辑回归校准 → 推进式回测 → 沪深港通/成交/深度的流动性画像 →
    预测留痕。任一环节取不到数据就按「暂缺」降级，绝不用历史数字冒充实时。
    """
    print("📡 正在运行港股量化引擎（恒指/恒科日线 · 港股蓝筹 · 沪深港通 · 港股成交）...")
    if not HK_QUANT_ENABLED:
        print("  ⏭ 量化引擎已关闭（OCTOPUS_QUANT=0 / --no-quant）")
        return _source_result("港股量化引擎", "unavailable", result=None,
                              error="本次运行已关闭量化引擎")
    try:
        res = _quant.run_quant(
            safe_request,
            history_path=os.path.join(REPORT_DIR, QUANT_HISTORY_FILENAME),
            enable_stocks=HK_QUANT_STOCKS)
    except Exception as exc:                       # 引擎异常不影响日报其它栏目
        print(f"  ⚠️ 量化引擎异常：{exc}")
        return _source_result("港股量化引擎", "unavailable", result=None, error=str(exc))

    if not res.get("available"):
        print(f"  ⚠️ 量化引擎暂不可用：{res.get('reason')}")
        return _source_result("港股量化引擎", "unavailable", result=None,
                              error=str(res.get("reason") or "样本不足"))

    head = res.get("headline") or {}
    if head.get("available"):
        print(f"  ✅ 量化预测：{head['text']}")
    liq = res.get("liquidity") or {}
    if liq.get("score") is not None:
        print(f"  ✅ 流动性综合分 {liq['score']:.0f}/100（{liq['label']}）")
    return _source_result("港股量化引擎", "success",
                          is_today=(res.get("as_of") == _today_display()),
                          content_date=res.get("as_of"),
                          result=res)


# ============================================================
# 未来 N 天影响经济时间点：抓取 + 筛选（东方财富财经日历）
# ------------------------------------------------------------
# 三类内容（缺一不可）：
#   kind 0 经济数据 —— 中/美/欧/日/英等市场的宏观读数发布（CPI、非农、LPR…）
#   kind 1 事件     —— 各国央行议息会议、国民经济运行情况发布会、中央全会等
#   kind 2 动态     —— 央行官员讲话、货币政策会议纪要、EIA/CFTC 周度报告
# 重要度 imp：3 最高（央行议息 + 中美核心读数）/ 2 重要 / 1 一般（展会论坛等）。
# 全部为确定性规则，写死在上方常量里：可复现、不预测方向、不伪造任何日程；
# 接口读不到就如实降级为「暂缺 + 原因」，绝不用推算日期冒充数据源。
# ============================================================
def _cal_date_obj(date_str):
    """'YYYY-MM-DD' → date；非法返回 None。"""
    try:
        return datetime.strptime(str(date_str or "")[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _cal_clean_tags(name):
    """去掉名称里没有信息量的标注（同日可能同时存在带与不带标注的两条）。"""
    name = str(name or "")
    for tag in CALENDAR_NOISE_TAG:
        name = name.replace(tag, "")
    return name.strip()


def _cal_split_period(name):
    """拆出「(报告期:2026年09月)」→ (基础名, '2609')；无报告期时第二位为空串。"""
    name = str(name or "").strip()
    match = re.match(r"^(.*?)\s*[（(]报告期[:：]([^）)]*)[)）]\s*$", name)
    if not match:
        return name, ""
    base = match.group(1).strip()
    ym = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", match.group(2) or "")
    if ym:
        return base, ym.group(1)[2:] + ym.group(2).zfill(2)
    return base, (match.group(2) or "").strip()


def _cal_strip_country(name, city):
    """剥掉「美国:」「美国EIA…」这类地区前缀（地区已单独成列，前缀会重复显示）。

    只在后面跟冒号或 ASCII 字母数字时才剥：「美国EIA原油库存」能处理，
    而「中国银行间同业拆借」这种地区名本就是词一部分的不会被误伤。
    """
    name = str(name or "").strip()
    city = str(city or "").strip()
    if not city or not name.startswith(city) or len(name) <= len(city):
        return name
    rest = name[len(city):]
    for sep in (":", "："):
        if rest.startswith(sep):
            return rest[len(sep):].strip()
    if rest[0].isascii() and (rest[0].isalnum() or rest[0] in "._-"):
        return rest.strip()
    return name


def _cal_canon(name):
    """归一化指标名：统一冒号/括号并剥掉「季调/初值/当月」等修饰词。"""
    n = str(name or "").replace("：", ":").replace("（", "(").replace("）", ")")
    for word in CALENDAR_CANON_DROP:
        n = n.replace(word, "")
    while "::" in n:
        n = n.replace("::", ":")
    return n.strip(": ")


def _cal_kou(name):
    """取口径（同比 / 环比）；东财同一指标常同时排两行，偶尔还多一条裸名。"""
    n = _cal_canon(name)
    if n.endswith("同比"):
        return "同比"
    if n.endswith("环比"):
        return "环比"
    return ""


def _cal_base_of(name):
    """去掉口径后的基础指标名，用于判断「同一天同一指标排了几行」。"""
    n = _cal_canon(name)
    for suffix in (":同比", ":环比", "同比", "环比"):
        if n.endswith(suffix):
            return n[:-len(suffix)].strip(": ")
    return n


def _cal_period_ok(date_str, period):
    """报告期与发布日相差过远视为异常标注：正常经济数据报告期领先发布日 0~4 个月。

    实测东财部分行会给出「报告期:2027年07月」这种远期口径挂在 2026 年的日期上，
    原样展示会让人误读，因此只丢标注、不丢这条时间点。
    """
    if not period or len(period) != 4:
        return True
    day = _cal_date_obj(date_str)
    if not day:
        return False
    try:
        p_year, p_month = 2000 + int(period[:2]), int(period[2:])
    except (TypeError, ValueError):
        return False
    if not 1 <= p_month <= 12:
        return False
    return 0 <= (day.year * 12 + day.month) - (p_year * 12 + p_month) <= 4


def _cal_period_label(period, today=None):
    """'2609' → '9月'（同年）/ '2027年1月'（跨年）；无法解析时原样返回。"""
    period = str(period or "")
    if len(period) != 4 or not period.isdigit():
        return period
    year, month = 2000 + int(period[:2]), int(period[2:])
    if not 1 <= month <= 12:
        return period
    base = today or datetime.now(CST).date()
    return f"{month}月" if year == base.year else f"{year}年{month}月"


def _cal_item_text(item, today=None):
    """时间点正文（纯文本）：名称（含合并后的口径）+ 报告期 + 类型标签。

    如「CPI：同比/环比 · 9月 · 数据」「非农就业人数 · 9月 · 数据」。
    """
    item = item if isinstance(item, dict) else {}
    name = str(item.get("name") or "").strip()
    kous = [k for k in (item.get("kou") or []) if k]
    if kous:
        name = f"{_cal_base_of(name)}:{'/'.join(kous)}"
    parts = [name]
    period = _cal_period_label(item.get("period"), today)
    if period:
        parts.append(period)
    kind_label = CALENDAR_KIND_LABELS.get(item.get("kind"), "")
    if kind_label:
        parts.append(kind_label)
    return " · ".join(p for p in parts if p)


def _cal_event_imp(text, low=False):
    """事件类重要度：中国宏观决策会议 → ★★★；主要央行的议息/决议动作 → ★★★；
    其余事件（小国央行、行业会议）→ ★★；展会论坛 → ★。"""
    text = str(text or "")
    if any(k in text for k in CALENDAR_EVENT_TOP):
        return 3
    if (any(k in text for k in CALENDAR_EVENT_ORG)
            and any(k in text for k in CALENDAR_EVENT_ACT)):
        return 3
    return 1 if low else 2


def _cal_classify(row):
    """把一条东财日历原始记录判成结构化时间点；判定为噪音时返回 None。"""
    if not isinstance(row, dict):
        return None
    raw_name = _cal_clean_tags(row.get("FE_NAME"))
    start = str(row.get("START_DATE") or "")
    date_str = start[:10]
    if not raw_name or not _cal_date_obj(date_str):
        return None
    if len(raw_name) > CALENDAR_MAX_NAME_LEN:
        return None
    if any(k in raw_name for k in CALENDAR_DROP_KW):
        return None                       # 个股事项：与宏观时间点无关
    if any(k in raw_name for k in CALENDAR_DROP_NAME_KW):
        return None                       # 冗余子序列（户籍失业率 / 现价 GDP…）
    if any(raw_name.endswith(k) for k in CALENDAR_DROP_NAME_SFX):
        return None

    city = str(row.get("CITY") or "").strip()
    ftype = str(row.get("FE_TYPE") or "").strip()
    std = str(row.get("STD_TYPE_CODE") or "").strip()
    base, period = _cal_split_period(raw_name)
    low = any(k in base for k in CALENDAR_LOW_KW)
    # 地区已单独成列，名称里的「美国:」「美国EIA…」前缀会重复显示（事件行的 CITY
    # 常是城市名，此时前缀剥不掉、原样保留，不会误伤）。
    item = {"date": date_str, "time": start[11:16], "city": city,
            "name": _cal_strip_country(base, city), "period": period}

    # ① 事件类：FE_TYPE 直接给出事件名（美联储议息会议 / 国民经济运行情况发布会…）
    if ftype and ftype != "经济数据":
        item.update(kind=1, imp=_cal_event_imp(ftype + base, low), period="")
        return item
    # ② 事件类：无 FE_TYPE 但报表类型标记为事件
    if std in ("1", "3"):
        item.update(kind=1, imp=_cal_event_imp(base, low), period="")
        return item
    # ③ 动态类：无 FE_TYPE（央行官员讲话 / 会议纪要 / 周度报告）
    #    动态行没有确认的国家 + 指标结构，最高只给 ★★，不冒充 ★★★。
    if not ftype:
        if (any(k in base for k in CALENDAR_DYN_TIER2)
                or any(k in base for k in CALENDAR_TIER3_KW)
                or (any(k in base for k in CALENDAR_TIER2_KW) and city in CALENDAR_KEEP_CITY)):
            imp = 2
        else:
            imp = 1
        item.update(kind=2, imp=imp, period="")
        return item
    # ④ 经济数据：只保留有定价权的市场 + 一二级读数
    if city not in CALENDAR_KEEP_CITY:
        return None
    if any(k in base for k in CALENDAR_TIER3_KW):
        imp = 3 if city in CALENDAR_CORE_CITY else 2
    elif any(k in base for k in CALENDAR_TIER2_KW):
        imp = 2 if city in CALENDAR_MAJOR_CITY else 1
    else:
        return None
    item.update(kind=0, imp=imp,
                period=period if _cal_period_ok(date_str, period) else "")
    return item


def _cal_dedupe(items):
    """同一天同一指标的多口径行合并成一行：口径并进 kou 列表（如「CPI:同比/环比」）。

    东财常把同一指标按 同比 / 环比 / 初值 / 终值 排成多行，逐行列出会让同一天
    出现 3~6 条重复。本栏只回答「什么时候发」，所以合并为一行、口径全部保留：
    既不丢信息也不刷屏。事件 / 动态行按（日期, 时间, 归一化名称）去重。
    """
    merged, order = {}, []
    for it in items:
        if it.get("kind") == 0:
            key = (it.get("date"), it.get("city"), _cal_base_of(it.get("name")))
        else:
            key = (it.get("date"), it.get("time"), _cal_canon(it.get("name")))
        hit = merged.get(key)
        if hit is None:
            kou = _cal_kou(it.get("name"))
            merged[key] = dict(it, kou=[kou] if kou else [])
            order.append(key)
            continue
        kou = _cal_kou(it.get("name"))
        if kou and kou not in hit["kou"]:
            hit["kou"].append(kou)
        hit["imp"] = max(int(hit.get("imp") or 0), int(it.get("imp") or 0))
        if kou and not _cal_kou(hit.get("name")):
            hit["name"] = it.get("name")     # 有口径的行信息量更高，用它当代表名
        if it.get("period") and not hit.get("period"):
            hit["period"] = it.get("period")
        if str(it.get("time") or "99:99") < str(hit.get("time") or "99:99"):
            hit["time"] = it.get("time")     # 同指标多行取最早那个时点
    out = []
    for key in order:
        it = merged[key]
        it["kou"].sort(key=lambda k: (0 if k == "同比" else (1 if k == "环比" else 2)))
        out.append(it)
    return out


def _cal_sort_key(item):
    return (str(item.get("date") or ""), str(item.get("time") or "99:99"))


def _cal_cut_priority(item):
    """裁剪优先级：重要度高者优先；同级里「数据 / 事件」优先于「动态」（讲话、
    周报最容易刷屏）；再同级按时间先后。"""
    kind = int(item.get("kind") or 0)
    return (-(int(item.get("imp") or 0)), 1 if kind == 2 else 0) + _cal_sort_key(item)


def _cal_select(items, max_rows=None):
    """正文行数裁剪：按优先级保留到上限，返回 (kept, dropped)。

    kept 按（日期, 时间）排序；dropped 是被裁掉的条目列表，调用方据此如实披露
    各重要度被裁了多少条（绝不静默丢内容）。上限只是版面保护，正常月份
    ★★★ / ★★ 都能全部列出。
    """
    limit = int(max_rows or ECON_CALENDAR_MAX_ROWS)
    if limit <= 0 or len(items) <= limit:
        return sorted(items, key=_cal_sort_key), []
    ranked = sorted(items, key=_cal_cut_priority)[:limit]
    kept_ids = {id(it) for it in ranked}
    dropped = [it for it in items if id(it) not in kept_ids]
    ranked.sort(key=_cal_sort_key)
    return ranked, dropped


def _cal_imp_counts(items):
    """按重要度统计条数 → {"3": n, "2": n, "1": n}（摘要与裁剪披露共用）。"""
    counts = {"3": 0, "2": 0, "1": 0}
    for it in items or []:
        if isinstance(it, dict):
            counts[str(max(1, min(3, int(it.get("imp") or 1))))] += 1
    return counts


def _cal_imp_text(counts):
    """{"3":2,"2":5,"1":0} → '★★★ 2 / ★★ 5 / ★ 0'（零值档省略）。"""
    parts = [f"{'★' * int(level)} {counts.get(level) or 0}"
             for level in ("3", "2", "1") if counts.get(level)]
    return " / ".join(parts) or "—"


def _cal_day_label(date_str, today=None):
    """('10-28 周二', 30)：月日 + 星期 + 距今 T+n（今天为 0）。"""
    day = _cal_date_obj(date_str)
    if not day:
        return str(date_str or ""), None
    base = today or datetime.now(CST).date()
    return f"{day.month:02d}-{day.day:02d} {CALENDAR_WEEKDAYS[day.weekday()]}", (day - base).days


def _cal_countdown(t_plus):
    """T+n 的中文说法：0 → 今天，1 → 明天，其余 → T+n；非法值返回空串。"""
    if not isinstance(t_plus, int):
        return ""
    if t_plus == 0:
        return "今天"
    if t_plus == 1:
        return "明天"
    return f"T+{t_plus}" if t_plus > 0 else ""


def _cal_digest(res, today=None):
    """把抓取结果整理成两主题共用的中性结构（纯文本，渲染端各自上色）。

    返回 {"pairs": [(标签, 值)], "days": [(日期, 日期标签, T+n, [时间点])]}。
    摘要里的每个数字都来自本次抓取结果：确定性合成、不引入新数据、不预测方向。
    """
    res = res if isinstance(res, dict) else {}
    items = [it for it in (res.get("items") or []) if isinstance(it, dict)]
    base = today or datetime.now(CST).date()
    pairs = []
    window = str(res.get("window") or "")
    if window:
        pairs.append(("时间窗口", window))
    if not items:
        pairs.append(("时间点合计", "0 个 · 窗口内未筛出影响经济的时间点"
                                    f"（原始日程 {int(res.get('raw_count') or 0)} 条）"))
        return {"pairs": pairs, "days": []}

    counts = _cal_imp_counts(items)
    n3 = counts.get("3") or 0
    total_txt = f"{len(items)} 个 · {_cal_imp_text(counts)}"
    dropped = int(res.get("dropped") or 0)
    if dropped > 0:
        # 被版面裁掉的条目按重要度如实披露：读者能看出 ★★★ 是否已全部列出。
        total_txt += (f"（版面另有 {dropped} 条未列出："
                      f"{_cal_imp_text(res.get('dropped_imp') or {})}）")
    pairs.append(("时间点合计", total_txt))

    def _picked(pred, limit=4):
        """命中的时间点压成「10-29 名称」短标签，超出 limit 时如实给出总数。"""
        hit = [it for it in items if pred(it)]
        if not hit:
            return ""
        labels = []
        for it in hit[:limit]:
            label, _ = _cal_day_label(it.get("date"), base)
            name = str(it.get("name") or "")[:22]
            labels.append(f"{label.split(' ')[0]} {name}".strip())
        text = "、".join(labels)
        return f"{text} 等 {len(hit)} 项" if len(hit) > limit else text

    top_events = _picked(lambda it: it.get("kind") == 1 and (it.get("imp") or 0) >= 3)
    pairs.append(("央行议息 / 重要会议", top_events or "窗口内暂无"))
    pairs.append(("中国关键读数",
                  _picked(lambda it: it.get("kind") == 0 and it.get("city") == "中国"
                          and (it.get("imp") or 0) >= 2) or "窗口内暂无"))
    pairs.append(("美国关键读数",
                  _picked(lambda it: it.get("kind") == 0 and it.get("city") == "美国"
                          and (it.get("imp") or 0) >= 2) or "窗口内暂无"))

    by_day = {}
    for it in items:
        by_day.setdefault(str(it.get("date") or ""), []).append(it)
    hot_date = sorted(by_day, key=lambda d: (-len(by_day[d]), d))[0]
    hot_label, hot_t = _cal_day_label(hot_date, base)
    dense_days = sum(1 for group in by_day.values() if len(group) >= 3)
    if n3 >= 4 or dense_days >= 3:
        verdict = "事件密度偏高，注意窗口内的波动放大"
    elif n3:
        verdict = "事件分布相对均衡"
    else:
        verdict = "窗口内无最高级事件"
    pairs.append(("最密集日", f"{hot_label}（{len(by_day[hot_date])} 项"
                             f"{' · ' + _cal_countdown(hot_t) if hot_t else ''}）· {verdict}"
                             "（规则合成，非方向判断）"))
    pairs.append(("筛选口径",
                  f"东财全窗口 {int(res.get('raw_count') or 0)} 条 → 命中 "
                  f"{int(res.get('matched') or 0)} 条 → 正文 {len(items)} 条；"
                  "保留中美欧日英港宏观读数 / 央行议息与重要会议 / 央行动态，"
                  "剔除个股事项、展会论坛与同指标冗余口径"))

    days = []
    for date_str in sorted(by_day):
        label, t_plus = _cal_day_label(date_str, base)
        group = sorted(by_day[date_str], key=lambda it: (str(it.get("time") or "99:99"),
                                                         -(it.get("imp") or 0)))
        days.append((date_str, label, t_plus, group))
    return {"pairs": pairs, "days": days}


def _calendar_table_rows(res, cell_builder, today=None):
    """两主题共用：摘要键值 + 逐日展平成表格行（cell_builder 决定各主题的配色）。"""
    digest = _cal_digest(res, today)
    rows = []
    for _date, label, t_plus, items in digest.get("days") or []:
        for i, it in enumerate(items):
            rows.append(cell_builder(label, t_plus, it, first=(i == 0)))
    return digest, rows


def fetch_econ_calendar(days=None, today=None):
    """抓取未来 N 天影响经济的时间点（东方财富财经日历，公开接口无需密钥）。

    返回 _source_result：
      items     —— [{date, time, city, name, imp, kind, period}]，已排序并按上限裁剪；
      raw_count —— 窗口内原始日程条数；matched —— 命中筛选口径的条数；
      dropped   —— 因正文行数上限被裁掉的一般级条数；window —— 窗口文字。
    任何异常都如实降级为 status=failed + error 原因，绝不用推算日期冒充数据源。
    前瞻性日程 is_today=False + snapshot=True：只作「今日抓取」，不参与当天检验计数。
    """
    window_days = int(days or ECON_CALENDAR_DAYS)
    base = today or datetime.now(CST).date()
    end = base + timedelta(days=window_days)
    window = f"{base.isoformat()} ~ {end.isoformat()} · 未来 {window_days} 天"
    # 服务端只支持按日期过滤（按 CITY / FE_TYPE 过滤返回空），故拉全窗口后本地筛。
    flt = (f"(START_DATE>='{base.isoformat()}')"
           f"(START_DATE<'{(end + timedelta(days=1)).isoformat()}')")
    referer = {"Referer": "https://data.eastmoney.com/"}
    rows, page, error = [], 1, ""
    while page <= ECON_CALENDAR_MAX_PAGES:
        params = {
            "reportName": ECON_CALENDAR_REPORT,
            "columns": ECON_CALENDAR_COLUMNS,
            "filter": flt,
            "pageNumber": str(page),
            "pageSize": str(ECON_CALENDAR_PAGE_SIZE),
            "sortColumns": "START_DATE",
            "sortTypes": "1",
            "source": "WEB",
            "client": "WEB",
        }
        payload = safe_request(ECON_CALENDAR_URL, headers=referer, params=params, timeout=15)
        if not isinstance(payload, dict):
            error = "接口无响应或非 JSON"
            break
        result = payload.get("result")
        result = result if isinstance(result, dict) else {}
        batch = [r for r in (result.get("data") or [])
                 if isinstance(r, dict) and r.get("FE_NAME") and r.get("START_DATE")]
        rows.extend(batch)
        try:
            count = int(result.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if not batch or (count and len(rows) >= count):
            break
        page += 1
        time.sleep(0.3)

    # 服务端过滤之外再本地夹一次窗口：栏目写的是「未来 N 天」，就绝不能出现 T+N 之外的行。
    in_window = []
    for r in rows:
        day = _cal_date_obj(str(r.get("START_DATE") or "")[:10])
        if day and base <= day <= end:
            in_window.append(r)
    rows = in_window

    if not rows:
        reason = error or "接口未返回窗口内日程"
        print(f"  ⚠️ 财经日历暂缺：{reason}")
        return _source_result(ECON_CALENDAR_SOURCE, "failed", is_today=False,
                              content_date=base.isoformat(), error=reason,
                              items=[], raw_count=0, matched=0, dropped=0,
                              window=window, days=window_days,
                              page=ECON_CALENDAR_PAGE)

    items = [it for it in (_cal_classify(r) for r in rows) if it]
    items = _cal_dedupe(items)
    kept, dropped = _cal_select(items)
    dropped_imp = _cal_imp_counts(dropped)
    print(f"  📅 财经日历：原始 {len(rows)} 条 → 命中 {len(items)} 条 → 正文 {len(kept)} 条"
          + (f"（版面裁掉 {len(dropped)} 条）" if dropped else "") + f"（{window}）")
    return _source_result(ECON_CALENDAR_SOURCE, "success", is_today=False,
                          content_date=base.isoformat(), snapshot=True,
                          items=kept, raw_count=len(rows), matched=len(items),
                          dropped=len(dropped), dropped_imp=dropped_imp,
                          window=window, days=window_days,
                          page=ECON_CALENDAR_PAGE)


def collect_all_data():
    """采集所有数据源"""
    print("\n" + "=" * 50)
    print("🔍 开始全网数据采集")
    print("=" * 50)

    data = {}
    data["实时行情"] = fetch_market_snapshot()
    time.sleep(0.5)
    data["A股大盘全景"] = fetch_market_panorama()
    time.sleep(0.5)
    # 政策因子的独立官方输入：直接读取中国政府网最新政策，不以媒体转载替代。
    data["国家政策"] = fetch_gov_policy()
    time.sleep(0.5)
    data["港股名家频道"] = fetch_hk_channels()
    time.sleep(0.5)

    data["全球头条"] = fetch_google_news()
    time.sleep(0.5)

    data["A股资讯"] = fetch_sina_headlines()
    time.sleep(0.5)

    data["东财快讯"] = fetch_eastmoney_news()
    time.sleep(0.5)

    data["热门榜单"] = fetch_hot_stocks()
    time.sleep(0.5)

    data["港股量化"] = fetch_hk_quant()
    time.sleep(0.5)

    if ECON_CALENDAR_ENABLED:
        print(f"\n📅 正在抓取未来 {ECON_CALENDAR_DAYS} 天影响经济时间点（东方财富财经日历）...")
        data["财经日历"] = fetch_econ_calendar()
        time.sleep(0.5)

    print("\n📰 正在采集每日量化策略趋势跟踪线索（Reddit 十个板块热门帖）...")
    data.update(fetch_public_sites())

    print("\n✅ 数据采集完成！")
    return data


# ============================================================
# HTML 组件（设计系统：复古像素游戏 · MARKET QUEST v3）
# ------------------------------------------------------------
# 版式语言：
#  · 暗色街机终端底 + 霓虹青 / 品红 / 电光蓝 / 像素黄
#  · 纯直角像素风：0 圆角、3px 硬描边 + 实色阴影，像 8-bit 卡带界面
#  · 等宽像素字体栈，中文回退苹方/雅黑；不依赖外部字体、图片或 SVG
#  · 纯 HTML 像素章鱼 + 每栏独立 44px 图标砖，图标始终先于文字建立层级
#  · 涨跌 = 高对比颜色底块 + ▲/▼/■ + 涨/跌/平，兼顾色觉差异
#  · AI = 首屏主控卡 + 关键指标计分板 + 大字号主结论 + 四个独立面板
# 硬约束：仍全部内联样式 + 表格布局，兼容微信/PushPlus
# ============================================================
# 复古游戏像素调色板
C_BG = "#050711"
C_PAPER = "#101426"
C_INK = "#F4F7FF"
C_ACCENT = "#39FFB6"
C_ACCENT_DEEP = "#FFFFFF"
C_ACCENT_SOFT = "#303A60"
C_ACCENT_MAGENTA = "#FF3CAC"
C_CYAN = "#22DFFF"
C_VIOLET = "#A98CFF"
C_MUTED = "#A6AEC9"
C_FAINT = "#747D9F"
C_HAIR = "#29314E"
C_ZEBRA = "#181D34"
C_LEMON = "#FFE66D"
C_MINT = "#39FFB6"
# 涨跌色不仅靠文字色区分，还配合 ▲/▼、深色底块与硬描边，保证微信深色页面中一眼可辨。
C_RED = "#FF5576"
C_GREEN = "#35F29A"
C_AMBER = "#FFD166"
C_BLUE = "#22DFFF"
C_MAGENTA = "#FF3CAC"
C_UP_BG = "#082B22"
C_DOWN_BG = "#34131F"
C_FLAT_BG = "#302711"
C_AI_BG = "#17152F"
FONT = ("'Courier New', Courier, 'Lucida Console', monospace, "
        "PingFang SC, Microsoft YaHei, sans-serif")
FONT_MONO = "'Courier New', Courier, monospace"

# ============================================================
# GUIZANG 主题调色板：简洁研报（保留主题名，兼容既有推送配置）
# —— 黑白编辑排版、圆体粗标题与留白（墨水屏优先）；涨跌 / 风险由符号和文字表达。
# ============================================================
GZ_PAPER = "#FFFFFF"        # 页面与正文统一白底（墨水屏只有黑/白，不铺任何灰底）
GZ_PAPER_TINT = GZ_PAPER    # 旧版 7% 灰底在墨水屏上会抖成脏点，首屏结论改纯白 + 粗分隔线
GZ_INK = "#000000"          # 正文纯黑；标题背景用黑色，标题文字反白
GZ_INK_TINT = GZ_PAPER      # 兼容旧调用，不再使用深色幕封
GZ_HAIR = "#8A8A8A"         # 分隔线：1px 发丝线在墨水屏上会断裂/消失，改为 2px 中灰
GZ_HAIR_INK = GZ_HAIR
GZ_HAIR_W = 2               # 分隔线粗细（墨水屏需要够粗才稳定显示）
GZ_CREAM = GZ_INK
GZ_META = "#3A3A3A"         # 次要文字：#6B6B6B 在墨水屏 16 级灰阶上偏淡，加深保证可读
GZ_META_INK = GZ_META
GZ_NEON = GZ_INK            # 旧版标题 token，不再使用荧光色
GZ_UP = GZ_INK             # 黑白模式：用 ▲ 涨 / ▼ 跌 / ■ 平 区分
GZ_DOWN = GZ_INK
GZ_FLAT = GZ_META
GZ_UP_INK = GZ_UP
GZ_DOWN_INK = GZ_DOWN
GZ_FLAT_INK = GZ_FLAT
GZ_WARN = GZ_INK
GZ_WARN_INK = GZ_WARN
REPORT_TITLE = "章鱼 AI·全景分析 —量化策略（趋势跟踪）"
# 字体：全篇统一圆体 + 粗字重，为墨水屏（电子墨水 / Kindle / e-reader）优化。
#   'Yuanti SC' 是苹果官方简体圆体（iOS 13+ / macOS 10.15+），圆笔无衬线、字腔开阔，
#   在 16 级灰阶的墨水屏上笔画不糊、字距不挤，是当前最合适的首选。
#   'Hiragino Maru Gothic ProN'（日文圆体）补位；'PingFang SC' 兜底简体，
#   Android 无系统简体圆体，会落到系统黑体——回退后仍是粗体高对比，不会变细发丝。
# 微信会把每个内联 font-family 原样计入消息长度；长字体栈在一份日报中重复数十次，
# 曾令 11.6 万字符的正文触发 PushPlus 10 万字符截断。因此全篇只保留这一条短栈，
# 并让 GZ_SERIF / GZ_SANS / GZ_MONO 三个历史 token 全部指向它——标题、正文、元信息
# 不再各用各的字体栈，一处改动即全篇生效，字符成本也比三栈并存更低。
GZ_FONT = "'Yuanti SC','Hiragino Maru Gothic ProN','PingFang SC',sans-serif"
GZ_SERIF = GZ_FONT         # 兼容旧调用：标题（不再用衬线，统一圆体）
GZ_SANS = GZ_FONT          # 兼容旧调用：正文
GZ_MONO = GZ_FONT          # 兼容旧调用：元信息（不再用等宽）
GZ_W_BODY = 500            # 墨水屏不要细笔画：正文用 Medium
GZ_W_BOLD = 700            # 标题 / 徽标 / 数值：Bold
# 字号阶梯：图标独立，刊头/栏目标题收紧，关键数字仍醒目（微信详情页可缩放）。
GZ_ICON_MASTHEAD = 128   # 刊头章鱼
GZ_ICON_SECTION = 96     # 栏目图标（落在标题上方）
GZ_ICON_ROW = 72         # 刊头栏目图标横排
GZ_ICON_MIN, GZ_ICON_MAX = 16, 160


# 环境变量 OCTOPUS_FONT_SCALE 一处控制 guizang 主题的全部字号（默认 0.85＝整体缩小）。
DEFAULT_FONT_SCALE = 0.85
GZ_FS_FLOOR = 7


def _resolve_font_scale(value=None):
    """归一化字号缩放系数：空值 / 非法值回落到 0.85，范围夹在 0.5–1.5 之间。"""
    raw = value if value is not None else os.environ.get("OCTOPUS_FONT_SCALE", "")
    try:
        scale = float(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_FONT_SCALE
    if scale != scale or scale in (float("inf"), float("-inf")):  # NaN / inf
        return DEFAULT_FONT_SCALE
    return max(0.5, min(1.5, scale))


def _gz_fs(base, scale=None):
    """把设计基准字号按缩放系数四舍五入，保留原有阶梯比例与层级关系。

    日报页面上所有字号都经过这一个函数，``OCTOPUS_FONT_SCALE`` 一处调整即可整体
    放大或缩小（图标尺寸是独立常量，不受此系数影响）。下限 7px 防止极端系数下
    元信息被压到不可读；用「加 0.5 再取整」而非 ``round()``，避免 10×0.85=8.5 被
    银行家舍入成 8，让正文与元信息塌成同一字号。
    """
    factor = _resolve_font_scale() if scale is None else _resolve_font_scale(scale)
    return max(GZ_FS_FLOOR, int(base * factor + 0.5))


GZ_FS_DISPLAY = _gz_fs(40)    # 刊头主标题：默认 34px（原 48px）
GZ_FS_SECTION = _gz_fs(30)    # 栏目标题：默认 26px（原 37px）
GZ_FS_PRICE = _gz_fs(36)      # 行情价格、成交额、市场倾向等关键数字
GZ_FS_BODY = _gz_fs(10)       # 普通正文
GZ_FS_META = _gz_fs(9)        # 次要说明与元信息
GZ_FS_METER = _gz_fs(14)      # 信号格 ●○ 字号


# Koboyo 官方图标详情页公开的 SVG 直链；不下载、不内嵌、不代理。
# 许可：https://koboyo.com/icons/license（允许个人及商业网站使用）。
KOBOYO_ICON_BASE = "https://koboyo.com/icons/svg/"
KOBOYO_SECTION_ICONS = {
    "ECON CALENDAR": "card-calendar",
    "AI READ": "brain",
    "POLICY SHOCK": "document",
    "MARKET SNAPSHOT": "chart",
    "A-SHARE PANORAMA": "chart",
    "HK GURU CHANNELS": "camera",
    "GLOBAL HEADLINES": "globe",
    "EASTMONEY WIRE": "newspaper",
    "A-SHARE DESK": "newspaper",
    "DATA AUDIT": "document",
    "CONCLUSION": "brain",
    "WRAP-UP": "document",
    "TREND CLUES": "brain",
    "QUANT FORECAST": "chart",
    "HK PROBABILITY": "chart",
    "LIQUIDITY FLOW": "chart",
}


# 刊头多图标横排：全部栏目手绘图标（按栏目顺序去重）在刊头一次排开，直观预览各栏目。
KOBOYO_MASTHEAD_ICONS = tuple(dict.fromkeys(KOBOYO_SECTION_ICONS.values()))


def gz_icon(name, size=None, *, masthead=False, inline=False):
    """装饰性远程 SVG；即使外链被微信屏蔽，独立文字标题仍完整可读。"""
    if name not in {"octopus", *KOBOYO_SECTION_ICONS.values()}:
        name = "document"
    if size is None:
        size = GZ_ICON_MASTHEAD if masthead else GZ_ICON_SECTION
    size = max(GZ_ICON_MIN, min(GZ_ICON_MAX, int(size)))
    if masthead:
        spacing = "display:block;margin:0 0 24px;"
    elif inline:
        spacing = "vertical-align:middle;margin:0 16px 16px 0;"
    else:
        spacing = "display:block;margin:0 0 16px;"
    loading = "eager" if masthead else "lazy"
    return (f'<img src="{KOBOYO_ICON_BASE}{name}.svg" width="{size}" height="{size}" '
            f'alt="" aria-hidden="true" loading="{loading}" decoding="async" '
            f'style="width:{size}px;height:{size}px;object-fit:contain;border:0;{spacing}">')


def gz_masthead_icon_row(size=None):
    """刊头栏目图标列：多图标显示；外链失效时仅少一行装饰，刊头文字仍完整。"""
    size = GZ_ICON_ROW if size is None else size
    icons = "".join(gz_icon(name, size, inline=True) for name in KOBOYO_MASTHEAD_ICONS)
    return f'<div style="padding-top:24px;line-height:1;">{icons}</div>'


def _sq(color=C_ACCENT, size=8):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">■</span>'


def _star(color=C_ACCENT, size=10):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">◆</span>'


def _heart(color=C_ACCENT_MAGENTA, size=10):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">⚡</span>'


def _flower(color=C_CYAN, size=10):
    return f'<span style="color:{color};font-size:{size}px;line-height:1;font-family:{FONT_MONO};">✚</span>'


def _percent_number(value):
    """把数字 / ``+1.23%`` 文本转成 float；无法转换时返回 None。"""
    try:
        if isinstance(value, str):
            value = value.replace("%", "").replace(",", "").strip()
        return float(value)
    except (TypeError, ValueError):
        return None


def _trend_badge(value, compact=False):
    """渲染高辨识度涨跌像素徽标：颜色、箭头和文字三重编码。"""
    pct = _percent_number(value)
    if pct is None:
        return (f'<span style="display:inline-block;border:1px solid {C_FAINT};background:{C_ZEBRA};'
                f'color:{C_FAINT};padding:1px 6px;font-size:10px;font-weight:900;'
                f'font-family:{FONT_MONO};box-shadow:2px 2px 0 #000;white-space:nowrap;">■ --</span>')
    if pct > 0:
        color, bg, arrow, word = C_GREEN, C_UP_BG, "▲", "涨"
    elif pct < 0:
        color, bg, arrow, word = C_RED, C_DOWN_BG, "▼", "跌"
    else:
        color, bg, arrow, word = C_AMBER, C_FLAT_BG, "■", "平"
    label = f"{arrow} {pct:+.2f}%" if compact else f"{arrow} {word} {pct:+.2f}%"
    if pct == 0:
        label = f"{arrow} 0.00%" if compact else f"{arrow} {word} 0.00%"
    return (f'<span style="display:inline-block;border:1px solid {color};background:{bg};'
            f'color:{color};padding:1px 6px;font-size:10px;font-weight:900;line-height:17px;'
            f'font-family:{FONT_MONO};box-shadow:2px 2px 0 #000;white-space:nowrap;">{label}</span>')


def _signal_meter(value, maximum, color=C_CYAN, cells=5):
    """用实体像素格显示信号强度，不依赖 CSS 渐变或外部图标。"""
    maximum = max(1, int(maximum or 1))
    lit = max(1, min(cells, round(float(value or 0) / maximum * cells))) if value else 0
    return (f'<span style="color:{color};font-family:{FONT_MONO};font-size:10px;letter-spacing:1px;">'
            f'{"■" * lit}</span><span style="color:{C_ACCENT_SOFT};font-family:{FONT_MONO};'
            f'font-size:10px;letter-spacing:1px;">{"□" * (cells - lit)}</span>')


def _pixel_octopus(pixel=4):
    """纯 HTML 8-bit 章鱼图标；无需图片资源，PushPlus/微信可直接渲染。"""
    pattern = (
        "00111100",
        "01111110",
        "11211211",
        "11111111",
        "01111110",
        "01011010",
        "11011011",
        "10000001",
    )
    cells = []
    for row in pattern:
        tds = []
        for bit in row:
            bg = C_ACCENT if bit == "1" else (C_BG if bit == "2" else "")
            # bgcolor / width / height 是邮件客户端兼容性最高的表格像素写法，也比重复长 style 更省推送字数。
            bg_attr = f' bgcolor="{bg}"' if bg else ""
            tds.append(f'<td width="{pixel}" height="{pixel}"{bg_attr}>&nbsp;</td>')
        cells.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<table role="img" aria-label="章鱼像素图标" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;margin:0 auto;font-size:0;line-height:0;">'
            f'{"".join(cells)}</table>')

def _badge(text, kind="ok"):
    styles = {
        "ok":   (C_GREEN, C_UP_BG, C_GREEN),
        "warn": (C_AMBER, C_FLAT_BG, C_AMBER),
        "bad":  (C_RED, C_DOWN_BG, C_RED),
        "ai":   (C_LEMON, C_AI_BG, C_VIOLET),
    }
    color, bg, border = styles.get(kind, styles["ok"])
    dot = "◆" if kind == "ai" else "●"
    return (f'<span style="display:inline-block;border:1px solid {border};color:{color};'
            f'background:{bg};padding:1px 7px;margin-left:6px;font-size:10px;font-weight:900;'
            f'font-family:{FONT_MONO};letter-spacing:1px;line-height:17px;'
            f'box-shadow:2px 2px 0 #000;vertical-align:middle;'
            f'white-space:nowrap;">[{dot} {_esc(text)}]</span>')


_SECTION_ICON_META = {
    "ECON CALENDAR": ("▦", "30-DAY", C_LEMON, C_FLAT_BG),
    "AI READ": ("◆", "AI", C_LEMON, C_AI_BG),
    "POLICY SHOCK": ("§", "POLICY", C_AMBER, C_FLAT_BG),
    "MARKET SNAPSHOT": ("▲", "MKT", C_GREEN, C_UP_BG),
    "HK GURU CHANNELS": ("▶", "TV", C_MAGENTA, "#301226"),
    "GLOBAL HEADLINES": ("▤", "NEWS", C_CYAN, "#092836"),
    "EASTMONEY WIRE": ("!", "WIRE", C_AMBER, C_FLAT_BG),
    "A-SHARE DESK": ("¥", "CN", C_RED, C_DOWN_BG),
    "DATA AUDIT": ("✓", "LOG", C_GREEN, C_UP_BG),
    "CONCLUSION": ("★", "TL;DR", C_LEMON, C_AI_BG),
    "WRAP-UP": ("✓", "RECAP", C_GREEN, C_UP_BG),
    "TREND CLUES": ("◉", "TREND", C_MAGENTA, "#301226"),
    "QUANT FORECAST": ("◈", "FORECAST", C_CYAN, "#092836"),
    "HK PROBABILITY": ("◈", "HK-PROB", C_MAGENTA, "#301226"),
    "LIQUIDITY FLOW": ("≈", "FLOW", C_CYAN, "#092836"),
}


def _section_visual(kicker):
    """返回栏目像素图标、短标签与强调色。"""
    return _SECTION_ICON_META.get(kicker, ("■", "DATA", C_ACCENT, C_UP_BG))


def _pixel_icon(kicker, size=44):
    """大尺寸栏目图标砖；ASCII/几何符号在微信字体回退时仍清晰。"""
    glyph, label, color, bg = _section_visual(kicker)
    glyph_size = max(20, round(size * 0.43))
    return (f'<table width="{size}" height="{size}" cellpadding="0" cellspacing="0" '
            f'style="width:{size}px;height:{size}px;border-collapse:collapse;border:1px solid {color};'
            f'background:{bg};box-shadow:4px 4px 0 #000;">'
            f'<tr><td align="center" valign="middle" style="padding:2px;color:{color};'
            f'font-family:{FONT_MONO};font-weight:900;line-height:1;">'
            f'<div style="font-size:{glyph_size}px;line-height:{glyph_size}px;">{glyph}</div>'
            f'<div style="font-size:8px;line-height:10px;letter-spacing:.5px;">{label}</div>'
            f'</td></tr></table>')


def _pixel_table(headers, rows, aligns=None, widths=None):
    """pixel 主题的多列数据表（等宽字体 + 霓虹表头；单元格内容由调用方转义）。

    widths 为各列百分比（如 ("17%", "13%", "70%")）：表格是 table-layout:fixed，
    给出列宽才能让「窄日期 + 窄时间 + 宽正文」这类排版不被平均分配。
    """
    rows = [list(r) for r in (rows or [])]
    if not rows:
        return ""
    n = len(headers) if headers else len(rows[0])
    if n <= 0:
        return ""
    aligns = list(aligns or (["left"] + ["right"] * (n - 1)))
    aligns = (aligns + ["left"] * n)[:n]
    widths = (list(widths) + [None] * n)[:n] if widths else [None] * n

    def _width_css(i):
        return f"width:{widths[i]};" if widths[i] else ""

    def _width_attr(i):
        return f' width="{widths[i]}"' if widths[i] else ""

    head = "".join(
        f'<td{_width_attr(i)} align="{aligns[i]}" style="{_width_css(i)}padding:5px 6px;'
        f'border-bottom:1px solid {C_ACCENT};'
        f'font-size:10px;font-weight:900;color:{C_CYAN};letter-spacing:.5px;'
        f'font-family:{FONT_MONO};text-align:{aligns[i]};">{_esc(h)}</td>'
        for i, h in enumerate(headers or []))
    body = []
    for row in rows:
        body.append("<tr>" + "".join(
            f'<td{_width_attr(i)} align="{aligns[i]}" valign="top" style="{_width_css(i)}padding:5px 6px;'
            f'border-bottom:1px solid {C_HAIR};font-size:11px;color:{C_INK};'
            f'line-height:1.6;font-family:{FONT_MONO};text-align:{aligns[i]};">'
            f'{row[i] if i < len(row) else ""}</td>' for i in range(n)) + "</tr>")
    head_row = f"<tr>{head}</tr>" if headers else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="width:100%!important;border-collapse:collapse;table-layout:fixed;">'
            f'{head_row}{"".join(body)}</table>')


def _pixel_panel(title, body, color=C_CYAN, icon="■"):
    """AI 等重点内容使用的 8-bit 面板：高对比标题条 + 硬边框。"""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-top:12px;border:1px solid {color};background:#0C1122;box-shadow:4px 4px 0 #000;">'
            f'<tr><td style="padding:5px 9px;background:{color};color:{C_BG};font-size:10px;'
            f'font-weight:900;font-family:{FONT_MONO};letter-spacing:1px;">{icon} {title}</td></tr>'
            f'<tr><td style="padding:8px 10px;">{body}</td></tr></table>')


def _alert(text, color=C_AMBER, bg=None):
    bg_color = bg or "#1A1E33"
    return (f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
            f'margin-bottom:10px;border:1px solid {color};background:{bg_color};'
            f'box-shadow:4px 4px 0 #000;">'
            f'<tr><td style="padding:8px 10px;font-size:11px;color:{color};font-weight:900;'
            f'font-family:{FONT_MONO};line-height:1.6;letter-spacing:.5px;">'
            f'[ ! ALERT ]&nbsp;{text}</td></tr></table>')

def _ledger_table(rows, pad):
    html = '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
    for label, value, *color in rows:
        val_color = color[0] if color else C_INK
        html += (f'<tr><td style="padding:{pad} 0;border-bottom:1px solid {C_HAIR};'
                 f'font-size:12px;color:{C_INK};vertical-align:top;line-height:1.5;'
                 f'font-family:{FONT_MONO};" '
                 f'width="46%">{label}</td>'
                 f'<td style="padding:{pad} 0;border-bottom:1px solid {C_HAIR};'
                 f'font-size:12px;font-weight:900;color:{val_color};text-align:right;'
                 f'line-height:1.5;font-variant-numeric:tabular-nums;'
                 f'font-family:{FONT_MONO};" width="54%">{value}</td></tr>')
    return html + '</table>'

def _data_table(rows):
    return _ledger_table(rows, "8px")

def _mini_table(rows):
    return _ledger_table(rows, "6px")

def _note(text):
    """像素主题的口径脚注：精简排版（2026-09-27）起不再输出说明性文字。"""
    return ""

def _subsection(text):
    return (f'<div style="border-top:1px solid {C_ACCENT_SOFT};margin-top:12px;padding:8px 0 2px;'
            f'font-size:12px;font-weight:900;color:{C_CYAN};letter-spacing:1px;'
            f'font-family:{FONT_MONO};text-transform:uppercase;">'
            f'<span style="color:{C_ACCENT};">▶</span> {text}</div>')

def _source_badge(item):
    if item.get("status") != "success":
        return _badge("OFFLINE", "bad")
    if item.get("snapshot"):
        return _badge("TODAY'S SNAPSHOT", "ok")
    if item.get("is_today"):
        return _badge("LIVE", "ok")
    return _badge(f"LAG {item.get('content_date') or '-'}", "warn")

def _item_row(icon, text, sub="", icon_color=C_ACCENT, row_bg="transparent", anchor=None):
    sub_html = (f'<div style="font-size:10px;color:{C_MUTED};letter-spacing:.3px;'
                f'padding-top:3px;line-height:1.6;font-family:{FONT_MONO};">{sub}</div>' if sub else "")
    anchor_attr = f' id="{_esc(anchor)}"' if anchor else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0"{anchor_attr} style="border-collapse:collapse;'
            f'background:{row_bg};">'
            f'<tr><td width="32" valign="top" style="padding:8px 4px 8px 0;border-bottom:1px solid {C_HAIR};'
            f'font-size:11px;font-weight:900;color:{icon_color};line-height:1.6;'
            f'font-family:{FONT_MONO};">{icon}</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid {C_HAIR};font-size:12px;'
            f'color:{C_INK};line-height:1.7;font-family:{FONT_MONO};">{text}{sub_html}</td></tr></table>')

def _headline_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "--"
    display = it.get("title") if isinstance(it, dict) else it
    sub = ""
    if isinstance(it, dict):
        parts = []
        if it.get("source"):
            parts.append(it["source"])
        if it.get("published_cst") and it["published_cst"] != "—":
            parts.append(it["published_cst"])
        sub = " | ".join(parts)
    anchor = f"h-gh-{index:02d}" if isinstance(index, int) else None
    return _item_row(f"[{marker}]", _esc(display[:120]), _esc(sub[:140]), anchor=anchor)

def _em_news_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "--"
    anchor = f"h-em-{index:02d}" if isinstance(index, int) else None
    if isinstance(it, dict):
        title = it.get("title") or ""
        sub = " :: ".join(x for x in (it.get("time", ""), it.get("summary", "")) if x)
        return _item_row(f"[{marker}]", _esc(title[:120]), _esc(sub[:110]), anchor=anchor)
    return _item_row(f"[{marker}]", _esc(it[:120]), anchor=anchor)

def _channel_block(ch, ch_idx=None):
    """渲染单个港股频道；ch_idx 为正文展示序号（1-based），用于风险引用锚点。"""
    name = _esc(ch.get("name", "?"))
    desc = _esc(ch.get("desc", ""))
    url = _esc(ch.get("url", ""))
    videos = ch.get("videos") or []
    if not videos:
        note = _esc(ch.get("note") or "OFFLINE :: NO SIGNAL [暂缺]")
        return (f'<div style="margin:12px 0;border:1px solid {C_FAINT};background:{C_ZEBRA};'
                f'padding:10px 12px;box-shadow:4px 4px 0 #000;">'
                f'<div style="font-size:12px;font-weight:900;color:{C_FAINT};font-family:{FONT_MONO};">[X {name} {_badge("暂缺", "bad")}]</div>'
                f'<div style="font-size:10px;color:{C_MUTED};padding-top:3px;font-family:{FONT_MONO};">{desc}</div>'
                f'<div style="font-size:10px;color:{C_MUTED};line-height:1.6;font-family:{FONT_MONO};margin-top:4px;">> {note}</div></div>')
    badge = _badge("LIVE", "ok") if ch.get("is_today") else _badge("ARCHIVE", "warn")
    messages = []
    top_n = videos[:CHANNEL_TOP_N]
    for vi, v in enumerate(top_n):
        title = _esc(v.get("title", "")[:110])
        pub = _esc(v.get("published_cst", ""))
        link = f'<a href="{_esc(v.get("url", "#"))}" style="color:{C_INK};text-decoration:none;border-bottom:1px dotted {C_ACCENT};">{title}</a>'
        bubble_bg = "#15182B" if vi % 2 == 0 else "#1A1E33"
        border_c = C_ACCENT if vi % 2 == 0 else C_CYAN
        label = ">> FEED" if vi % 2 == 0 else ">> UPDATE"
        new_tag = f' <span style="color:{C_ACCENT_MAGENTA};font-weight:900;background:#2A1320;border:1px solid {C_ACCENT_MAGENTA};padding:0 3px;">[NEW]</span>' if v.get("is_today") else ""
        anchor_attr = f' id="h-hk-{ch_idx:02d}-{vi + 1:02d}"' if isinstance(ch_idx, int) else ""
        messages.append((f'<table width="100%" cellpadding="0" cellspacing="0"{anchor_attr} style="border-collapse:collapse;margin-top:6px;"><tr><td align="left">'
                         f'<div style="display:block;max-width:100%;text-align:left;background:{bubble_bg};border:1px solid {border_c};'
                         f'padding:6px 8px;box-shadow:3px 3px 0 #000;font-size:11px;color:{C_INK};line-height:1.6;font-family:{FONT_MONO};">'
                         f'<div style="font-size:9px;font-weight:900;color:{border_c};letter-spacing:1px;">{label} :: {pub}{new_tag}</div>'
                         f'<div style="padding-top:3px;">> {link}</div></div></td></tr></table>'))
    return (f'<div style="margin:12px 0;border:1px solid {C_ACCENT};background:#0F1222;padding:10px 12px;box-shadow:6px 6px 0 #000;">'
            f'<div style="font-size:12px;font-weight:900;color:{C_ACCENT_DEEP};font-family:{FONT_MONO};">'
            f'<span style="display:inline-block;background:{C_ACCENT};color:#000;padding:0 4px;margin-right:6px;">CH</span>'
            f'<a href="{url}" style="color:{C_INK};text-decoration:none;">{name}</a> {badge}</div>'
            f'<div style="font-size:10px;color:{C_MUTED};padding:4px 0 2px;font-family:{FONT_MONO};">{desc} :: <b style="color:{C_CYAN};">[8-BIT FEED]</b></div>'
            f'{"".join(messages)}</div>')

def _status_footer(sources):
    lines = []
    for name, s in sources:
        if s.get("status") == "success":
            lines.append((_sq(C_GREEN, 8),
                          f'<b style="color:{C_INK};font-family:{FONT_MONO};">{_esc(name)}</b> {_source_badge(s)}'
                          f' <span style="color:{C_MUTED};font-family:{FONT_MONO};">@ {_esc(s.get("fetched_at", "—"))}</span>'))
        else:
            detail = _esc(s.get("error", "暂时不可用"))
            lines.append((_sq(C_RED, 8),
                          f'<b style="color:{C_INK};font-family:{FONT_MONO};">{_esc(name)}</b> [x FAIL] '
                          f'<span style="color:{C_MUTED};font-family:{FONT_MONO};">({detail}) @ {_esc(s.get("fetched_at", "—"))}</span>'))
    rows = "".join(
        f'<tr><td width="22" valign="top" style="padding:5px 0;border-bottom:1px solid {C_HAIR};font-family:{FONT_MONO};">{marker}</td>'
        f'<td style="padding:5px 0;border-bottom:1px solid {C_HAIR};font-size:11px;'
        f'color:{C_MUTED};line-height:1.7;font-family:{FONT_MONO};">{line}</td></tr>'
        for marker, line in lines)
    return f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">{rows}</table>'

def _report_meta(html):
    def g(name):
        m = re.search(rf'name="octopus-{name}" content="([^\"]+)"', html)
        return m.group(1) if m else None
    try:
        today_sources = int(g("today-sources") or 0)
    except (TypeError, ValueError):
        today_sources = 0
    try:
        total_sources = int(g("total-sources") or 0)
    except (TypeError, ValueError):
        total_sources = 0
    return {
        "date": g("report-date"),
        "generated_at": g("generated-at"),
        "today_sources": today_sources,
        "total_sources": total_sources,
    }

def _masthead_cell(label, value, value_color=C_INK, first=False):
    border = "" if first else f"border-left:1px solid {C_HAIR};"
    padding = "0" if first else "12px"
    return (f'<td width="33%" valign="top" style="padding:8px 0;{border}">'
            f'<div style="padding-left:{padding};">'
            f'<div style="font-size:8px;font-weight:900;color:{C_ACCENT};letter-spacing:1px;font-family:{FONT_MONO};">{label}</div>'
            f'<div style="font-size:11px;font-weight:900;color:{value_color};padding-top:3px;'
            f'font-family:{FONT_MONO};font-variant-numeric:tabular-nums;">{value}</div></div></td>')

def _section(num, kicker_en, title, content, badge_html="", caption=""):
    """栏目头使用独立大图标砖；AI 栏目以黄色关卡色单独强调。"""
    _, _, section_color, _ = _section_visual(kicker_en)
    badge_cell = (f'<td align="right" valign="middle" style="padding-left:6px;">{badge_html}</td>'
                  if badge_html else "")
    caption_html = (f'<div style="font-size:10px;color:{C_MUTED};letter-spacing:.3px;'
                    f'padding:7px 0 8px 56px;line-height:1.6;font-family:{FONT_MONO};">'
                    f'<span style="color:{section_color};">└─</span> {caption}</div>'
                    if caption else '<div style="padding-bottom:7px;"></div>')
    return f'''
<div style="border-top:1px solid {section_color};margin-top:28px;padding-top:12px;">
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
<tr>
<td width="52" valign="middle" style="padding-right:10px;">{_pixel_icon(kicker_en)}</td>
<td valign="middle">
<div style="font-family:{FONT_MONO};font-size:9px;font-weight:900;color:{section_color};letter-spacing:1px;line-height:1.3;">LVL {num} // {kicker_en}</div>
<div style="font-size:17px;font-weight:900;color:{C_ACCENT_DEEP};letter-spacing:.5px;padding-top:4px;line-height:1.35;font-family:{FONT_MONO};">{title}<span style="color:{section_color};">_</span></div>
</td>
{badge_cell}
</tr>
</table>
{caption_html}
{content}
</div>'''


# ============================================================
# GUIZANG 主题排版（简洁研报 · 微信单列）
# —— 白底、克制标题与宽留白；纯内联样式与表格布局，保持 PushPlus 兼容。
# ============================================================

def _quote_parts(market, label, precision=2):
    """主题无关的行情取值：(价格字符串, 涨跌幅 float|None)；缺失返回 (None, None)。"""
    quote = (market.get("quotes", {}) or {}).get(label)
    if not quote:
        return None, None
    try:
        price_str = f"{float(quote['price']):,.{precision}f}"
    except (TypeError, ValueError, KeyError):
        return None, None
    return price_str, _percent_number(quote.get("change_pct", 0))


def gz_trend_badge(value, compact=False):
    """涨跌：颜色 + 箭头 + 涨/跌/平。不用 inline-block / nowrap，避免微信挤爆。"""
    pct = _percent_number(value)
    if pct is None:
        return f'<span style="color:{GZ_FLAT};font-weight:700;">■ 暂缺</span>'
    if pct > 0:
        color, arrow, word = GZ_UP, "▲", "涨"
    elif pct < 0:
        color, arrow, word = GZ_DOWN, "▼", "跌"
    else:
        color, arrow, word = GZ_FLAT, "■", "平"
    if compact:
        label = f"{arrow} {pct:+.2f}%"
    elif pct == 0:
        label = f"{arrow} {word} 0.00%"
    else:
        label = f"{arrow} {word} {pct:+.2f}%"
    return f'<span style="color:{color};font-weight:700;">{label}</span>'


def gz_meter(value, maximum, cells=5, lit=GZ_INK, off=GZ_HAIR, size=None):
    """信号格放大到可读字号；微信忽略 letter-spacing 也仍能看出实心/空心。"""
    if size is None:
        size = GZ_FS_METER
    maximum = max(1, int(maximum or 1))
    n = max(1, min(cells, round(float(value or 0) / maximum * cells))) if value else 0
    return (f'<span style="color:{lit};font-size:{size}px;">{ "●" * n }</span>'
            f'<span style="color:{off};font-size:{size}px;">{ "○" * (cells - n) }</span>')


def gz_badge(text, kind="ok", on_ink=False):
    """纯文字状态，不用胶囊/nowrap。"""
    if on_ink:
        styles = {"ok": GZ_UP_INK, "warn": GZ_WARN_INK, "bad": GZ_DOWN_INK, "ai": GZ_NEON}
    else:
        styles = {"ok": GZ_UP, "warn": GZ_WARN, "bad": GZ_DOWN, "ai": GZ_INK}
    color = styles.get(kind, GZ_INK)
    return f'<span style="color:{color};font-weight:{GZ_W_BOLD};font-size:{GZ_FS_META}px;">{_esc(text)}</span>'


def gz_source_badge(item, on_ink=False):
    if item.get("status") != "success":
        return gz_badge("暂缺", "bad", on_ink)
    if item.get("snapshot"):
        return gz_badge("今日抓取", "ok", on_ink)
    if item.get("is_today"):
        return gz_badge("当天", "ok", on_ink)
    return gz_badge(f"非当天 {item.get('content_date') or '-'}", "warn", on_ink)


def gz_shell(inner, bg=None, pad="20px 0", hair=False, anchor=None, border_css=""):
    """微信最稳的单元：一张满宽表、一格 td、bgcolor 双写。anchor 为风险引用锚点。

    border_css 用于墨水屏分区：灰底会被墨水屏抖成脏点，改用实线边框划分区块。
    """
    bg_attr = f' bgcolor="{bg}"' if bg else ""
    bg_css = f"background:{bg};" if bg else ""
    hair_css = f"border-bottom:{GZ_HAIR_W}px solid {GZ_HAIR};" if hair else ""
    anchor_attr = f' id="{_esc(anchor)}"' if anchor else ""
    return (
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0"{bg_attr}{anchor_attr} '
        f'style="width:100%!important;border-collapse:collapse;table-layout:fixed;">'
        f'<tr><td{bg_attr} align="left" valign="top" '
        f'style="padding:{pad};{bg_css}{hair_css}{border_css}">{inner}</td></tr></table>'
    )



def _gz_missing(text="■ 数据暂缺"):
    return f'<span style="color:{GZ_FLAT};">{text}</span>'


def _gz_num(text):
    return f'<span style="font-family:{GZ_MONO};font-weight:700;">{text}</span>'


def gz_data_table(headers, rows, aligns=None, kv=False, row_anchors=None, widths=None):
    """微信兼容满宽数据表。

    整表一张 ``width=100%`` + ``width:100%!important``，``table-layout:fixed``；
    不用 ``nowrap`` / ``inline-block`` / ``width="33%"``；行全部包在本函数的
    ``<table>`` 里，不产出裸 ``<tr>``。``kv=True`` 时第一列为元信息色标签。
    ``widths`` 为各列百分比（如 ``("17%", "13%", "70%")``）：表格是
    ``table-layout:fixed``，给出列宽才能让窄列（日期 / 时间）不被平均分配；
    属性与内联样式双写，兼容微信客户端的 HTML 清洗。
    """
    rows = [list(r) for r in (rows or [])]
    if not rows:
        return ""
    n = len(headers) if headers else len(rows[0])
    if n <= 0:
        return ""
    if aligns is None:
        aligns = ["left"] + ["right"] * (n - 1) if n > 1 else ["left"]
    aligns = (list(aligns) + ["left"] * n)[:n]
    widths = (list(widths) + [None] * n)[:n] if widths else [None] * n
    anchors = list(row_anchors or [])
    while len(anchors) < len(rows):
        anchors.append(None)

    def _cell(html, i, *, head=False, kv_label=False, anchor=None):
        pad_r = "0" if i == n - 1 else "10px"
        if head:
            border = f"border-bottom:{GZ_HAIR_W}px solid {GZ_INK};"
            size, color, weight = GZ_FS_META, GZ_META, "700"
        elif kv_label:
            border = f"border-bottom:{GZ_HAIR_W}px solid {GZ_HAIR};"
            size, color, weight = GZ_FS_META, GZ_META, GZ_W_BODY
        else:
            border = f"border-bottom:{GZ_HAIR_W}px solid {GZ_HAIR};"
            size, color, weight = GZ_FS_BODY, GZ_INK, GZ_W_BODY
        align = aligns[i]
        id_attr = f' id="{_esc(anchor)}"' if anchor else ""
        width_attr = f' width="{widths[i]}"' if widths[i] else ""
        width_css = f"width:{widths[i]};" if widths[i] else ""
        return (
            f'<td{id_attr}{width_attr} valign="top" align="{align}" '
            f'style="{width_css}padding:10px {pad_r} 10px 0;{border}'
            f'font-size:{size}px;color:{color};font-weight:{weight};'
            f'line-height:1.45;text-align:{align};">{html}</td>'
        )

    trs = []
    if headers:
        trs.append("<tr>" + "".join(
            _cell(_esc(h), i, head=True) for i, h in enumerate(headers)
        ) + "</tr>")
    for ri, row in enumerate(rows):
        tds = []
        for i in range(n):
            val = row[i] if i < len(row) else ""
            tds.append(_cell(
                val, i,
                kv_label=(kv and i == 0),
                anchor=(anchors[ri] if i == 0 else None),
            ))
        trs.append("<tr>" + "".join(tds) + "</tr>")
    table = (
        f'<table width="100%" border="0" cellpadding="0" cellspacing="0" '
        f'style="width:100%!important;border-collapse:collapse;table-layout:fixed;">'
        f'{"".join(trs)}</table>'
    )
    return gz_shell(table, bg=GZ_PAPER, pad="4px 0 16px")


def gz_kv_table(pairs):
    """多行键值并入一张两列表，避免一条数据一张卡。"""
    pairs = [(a, b) for a, b in (pairs or [])]
    if not pairs:
        return ""
    return gz_data_table(None, pairs, aligns=("left", "right"), kv=True)


def gz_note(text):
    return gz_shell(
        f'<div style="font-size:{GZ_FS_META}px;color:{GZ_META};line-height:1.85;">{_esc(text)}</div>',
        pad="16px 0")


def gz_subsection(text):
    return gz_shell(
        f'<div style="font-size:{GZ_FS_BODY}px;font-weight:700;color:{GZ_INK};font-family:{GZ_SANS};'
        f'padding-top:8px;border-top:{GZ_HAIR_W}px solid {GZ_HAIR};line-height:1.5;">{text}</div>',
        pad="28px 0 12px")


def gz_rowline(label_html, right_html, pad="8px"):
    """兼容旧调用：单行键值并入两列表格。"""
    return gz_kv_table([(label_html, right_html)])


def gz_table(rows_html):
    """兼容旧调用：内容已是完整卡片时原样拼接。"""
    return rows_html or ""


def gz_rows(rows_html):
    """每条已是独立满宽表，拼接即可。"""
    return rows_html or ""


def _gz_quote_row(label, price_str, pct):
    if price_str is None:
        miss = _gz_missing()
        return [_esc(label), miss, miss]
    badge = gz_trend_badge(pct) if pct is not None else _gz_missing()
    return [_esc(label), _gz_num(price_str), badge]


def gz_market_row(label, price_str, pct):
    """兼容旧调用：单行行情并入三列表。"""
    return gz_data_table(["名称", "最新价", "涨跌"], [_gz_quote_row(label, price_str, pct)])


def gz_market_section(market):
    def _block(title, specs):
        rows = []
        for label, precision in specs:
            price_str, pct = _quote_parts(market, label, precision)
            if price_str is None:
                continue          # 缺失品种不出「数据暂缺」行
            rows.append(_gz_quote_row(label, price_str, pct))
        if not rows:
            return ""
        return gz_subsection(title) + gz_data_table(["名称", "最新价", "涨跌"], rows)

    return (
        _block("全球与美股", [("道琼斯指数", 0), ("标普500", 0), ("纳斯达克", 0),
                             ("WTI 原油", 2), ("微软 MSFT", 2), ("Meta META", 2)])
        + _block("A股四指数", [("上证指数", 2), ("深证成指", 2), ("创业板指", 2), ("科创50", 2)])
        # 2026-09-09 补缺：恒生双指数早已在抓取（Yahoo），但从未在行情速览展示；
        # 动能明细表移除后，这里是它们唯一的展示位置。
        + _block("港股双指数", [("恒生指数", 2), ("恒生科技", 2)])
    )


def gz_panorama_block(pan):
    """guizang 版「A股大盘全景复盘」：指数 / 涨跌家数 / 成交额 / 南北向 / 板块热力，均用表格。"""
    parts = []

    indices = pan.get("indices") or []
    if indices:
        rows = []
        for idx in indices:
            pct = idx.get("chg_pct")
            badge = gz_trend_badge(pct) if pct is not None else _gz_missing()
            amt = _format_amount(idx["amount"]) if idx.get("amount") else "—"
            rows.append([_esc(idx["name"]), _gz_num(f'{idx["price"]:,.2f}'), badge, amt])
        parts.append(gz_subsection("指数表现") + gz_data_table(
            ["指数", "最新价", "涨跌", "成交额"], rows))

    b = pan.get("breadth")
    if b:
        b_rows = []
        for exch, p in (b.get("markets") or {}).items():
            b_rows.append([
                _esc(exch),
                f'{p["up"]:,} 家',
                f'{p["down"]:,} 家',
                f'{(p.get("flat") or 0):,} 家',
            ])
        b_rows.append([
            "沪深京合计",
            f'{b["up"]:,} 家',
            f'{b["down"]:,} 家',
            f'{b["flat"]:,} 家',
        ])
        parts.append(
            gz_subsection("涨跌家数")
            + gz_data_table(["市场", "上涨", "下跌", "平盘"], b_rows)
            + gz_kv_table([(
                "涨跌比 / 情绪定调",
                (f'{b["ratio"]:.2f}' if b.get("ratio") is not None else "—")
                + f' · {_esc(b.get("mood") or "—")}',
            )])
        )

    t = pan.get("turnover")
    if t:
        chg = t.get("chg_pct")
        chg_html = f' 较上一交易日 {gz_trend_badge(chg)}' if chg is not None else ""
        t_pairs = []
        for exch, amt in (t.get("by_market") or {}).items():
            t_pairs.append((f"{exch}市成交额", _format_amount(amt)))
        t_pairs.append(("沪深京成交额合计", _format_amount(t["total"]) + chg_html))
        if t.get("prev_total"):
            t_pairs.append(("上一交易日合计（沪深京）", _format_amount(t["prev_total"])))
        parts.append(gz_subsection("成交额") + gz_kv_table(t_pairs))

    north = pan.get("north") or {}
    if north:
        flow_pairs = []
        if north.get("available") and north.get("amount_yi") is not None:
            flow_pairs.append((f"北向成交总额（{north.get('date') or '—'}）",
                               _gz_num(f'{north["amount_yi"]:,.2f} 亿元')))
        if north.get("south_available") and north.get("south_amount_yi") is not None:
            flow_pairs.append((f"南向成交总额（{north.get('south_date') or north.get('date') or '—'}）",
                               _gz_num(f'{north["south_amount_yi"]:,.2f} 亿元')))
        if flow_pairs:
            parts.append(gz_subsection("南北向资金（前一收盘）") + gz_kv_table(flow_pairs))

    sec = pan.get("sectors") or {}
    for title, key in (("板块热力 · 领涨行业 TOP", "leading"),
                       ("板块热力 · 领跌行业 TOP", "lagging")):
        items = sec.get(key) or []
        if items:
            s_rows = []
            for it in items:
                badge = gz_trend_badge(it.get("chg_pct"))
                inflow = _format_amount(it["main_inflow"]) if it.get("main_inflow") is not None else "—"
                lead = _esc(it["lead_stock"]) if it.get("lead_stock") else "—"
                lead_pct = it.get("lead_stock_pct")
                if lead != "—" and lead_pct is not None:
                    lead = f"{lead} {lead_pct:+.2f}%"
                s_rows.append([_esc(it["name"]), badge, inflow, lead])
            parts.append(gz_subsection(title) + gz_data_table(
                ["板块", "涨跌", "主力净流入", "领涨股"], s_rows))

    return "".join(parts)


def _cal_gz_cells(day_label, t_plus, item, first=False):
    """guizang 日历表的一行：日期（当天首行附 T+n）/ 时间 / 星号 + 地区 + 时间点。

    墨水屏只有黑白：重要度用「星号数量 + 字重 + 灰阶」区分，不依赖颜色。
    """
    item = item if isinstance(item, dict) else {}
    imp = max(1, min(3, int(item.get("imp") or 1)))
    day_html = ""
    if first:
        day_html = f'<b style="color:{GZ_INK};font-family:{GZ_SANS};">{_esc(day_label)}</b>'
        when = _cal_countdown(t_plus)
        if when:
            day_html += (f'<div style="font-size:{GZ_FS_META}px;color:{GZ_META};'
                         f'padding-top:2px;">{_esc(when)}</div>')
    star_style = (f"color:{GZ_INK};font-weight:{GZ_W_BOLD};" if imp >= 3
                  else (f"color:{GZ_INK};" if imp == 2 else f"color:{GZ_META};"))
    city = str(item.get("city") or "").strip()
    city_html = f'<span style="color:{GZ_META};">{_esc(city)}</span> · ' if city else ""
    body = (f'<span style="{star_style}">{"★" * imp}</span> '
            f'{city_html}{_esc(_cal_item_text(item))}')
    return [day_html, _esc(str(item.get("time") or "—")), body]


def gz_calendar_block(res):
    """黑白研报版「未来 N 天影响经济时间点」：窗口摘要表 + 全窗口一张三列日历表。"""
    digest, rows = _calendar_table_rows(res, _cal_gz_cells)
    parts = []
    pairs = digest.get("pairs") or []
    if pairs:
        parts.append(gz_subsection("窗口摘要"))
        parts.append(gz_data_table(None, [[_esc(a), _esc(b)] for a, b in pairs],
                                   aligns=("left", "left"), kv=True,
                                   widths=("26%", "74%")))
    if rows:
        parts.append(gz_subsection("逐日时间点（北京时间）"))
        parts.append(gz_data_table(["日期", "时间", "影响经济的时间点"], rows,
                                   aligns=("left", "left", "left"),
                                   widths=("17%", "13%", "70%")))
    return "".join(parts)


def _gz_news_card(marker, title, sub="", anchor=None):
    # Headlines lead; source and timestamp sit quietly underneath. No list-number chrome.
    meta = (f'<div style="font-size:{GZ_FS_META}px;color:{GZ_META};line-height:1.7;padding-top:8px;">'
            f'{_esc(sub)}</div>' if sub else "")
    return gz_shell(
        f'<div style="font-size:{GZ_FS_BODY}px;color:{GZ_INK};line-height:1.85;">{title}</div>{meta}',
        pad="20px 0", hair=True, anchor=anchor)


def gz_headline_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "—"
    display = it.get("title") if isinstance(it, dict) else it
    parts = []
    if isinstance(it, dict):
        if it.get("source"):
            parts.append(it["source"])
        if it.get("published_cst") and it.get("published_cst") != "—":
            parts.append(it["published_cst"])
    anchor = f"h-gh-{index:02d}" if isinstance(index, int) else None
    return _gz_news_card(marker, _esc(display[:120]), " · ".join(parts), anchor=anchor)


def gz_em_news_row(it, index=None):
    marker = f"{index:02d}" if isinstance(index, int) else "—"
    anchor = f"h-em-{index:02d}" if isinstance(index, int) else None
    if isinstance(it, dict):
        title = it.get("title") or ""
        sub = " · ".join(x for x in (it.get("time", ""), it.get("summary", "")) if x)
    else:
        title, sub = it, ""
    return _gz_news_card(marker, _esc(title[:120]), sub, anchor=anchor)


def gz_item_row(icon, text, sub="", icon_color=None, row_bg=None, anchor=None):
    marker = icon if icon else "—"
    return _gz_news_card(marker, text, sub, anchor=anchor)


def gz_channel_block(ch, ch_idx=None):
    """渲染单个港股频道；ch_idx 为正文展示序号（1-based），用于风险引用锚点。"""
    name = _esc(ch.get("name", "?"))
    desc = _esc(ch.get("desc", ""))
    url = _esc(ch.get("url", ""))
    videos = ch.get("videos") or []
    if not videos:
        note = _esc(ch.get("note") or "暂缺")
        return gz_shell(
            f'<div style="font-size:{GZ_FS_BODY}px;font-weight:700;color:{GZ_FLAT};">{name} · 暂缺</div>'
            f'<div style="font-size:{GZ_FS_META}px;color:{GZ_META};padding-top:4px;line-height:1.6;">{desc} · {note}</div>',
            bg=GZ_PAPER, pad="20px 0")
    badge = gz_source_badge({"status": "success", "is_today": True}) if ch.get("is_today") else ""
    name_link = f'<a href="{url}" style="color:{GZ_INK};text-decoration:none;">{name}</a>' if url else name
    rows, anchors = [], []
    for vi, v in enumerate(videos[:CHANNEL_TOP_N], 1):
        title = _esc(v.get("title", "")[:110])
        pub = _esc(v.get("published_cst", ""))
        link = f'<a href="{_esc(v.get("url", "#"))}" style="color:{GZ_INK};text-decoration:none;">{title}</a>'
        new_tag = (f' <span style="color:{GZ_UP};font-weight:700;">当天</span>'
                   if v.get("is_today") else "")
        rows.append([link + new_tag, pub])
        anchors.append(f"h-hk-{ch_idx:02d}-{vi:02d}" if isinstance(ch_idx, int) else None)
    head = gz_shell(
        f'<div style="font-size:{GZ_FS_BODY}px;font-weight:700;color:{GZ_INK};font-family:{GZ_SANS};line-height:1.4;">'
        f'{name_link}{" · " + badge if badge else ""}</div>',
        bg=GZ_PAPER, pad="20px 0 4px")
    return head + gz_data_table(["标题", "时间"], rows, aligns=("left", "right"), row_anchors=anchors)


def gz_status_footer(sources):
    rows = []
    for name, s in sources:
        if s.get("status") == "success":
            rows.append([
                _esc(name),
                gz_source_badge(s),
                f'<span style="color:{GZ_META};">{_esc(s.get("fetched_at", "—"))}</span>',
            ])
        else:
            detail = _esc(s.get("error", "暂时不可用"))
            rows.append([
                _esc(name),
                gz_badge("暂缺", "bad"),
                f'<span style="color:{GZ_META};">{detail} · {_esc(s.get("fetched_at", "—"))}</span>',
            ])
    return gz_data_table(["来源", "状态", "抓取"], rows, aligns=("left", "left", "right"))


def gz_alert(text, color=None):
    c = color or GZ_INK
    return gz_shell(
        f'<div style="font-size:{GZ_FS_BODY}px;color:{GZ_INK};line-height:1.85;border-left:2px solid {c};'
        f'padding-left:12px;">{text}</div>',
        bg=GZ_PAPER, pad="20px 0")


def gz_masthead_cell(label, value, value_color=GZ_CREAM, first=False):
    """兼容旧调用：刊头已改为单列，此函数不再用于页面。"""
    return (f'<div style="font-size:{GZ_FS_META}px;color:{GZ_META_INK};padding-top:6px;">'
            f'{label} · <span style="color:{value_color};font-weight:700;">{value}</span></div>')


def gz_section(num, kicker_en, title, content, badge_html="", caption=""):
    """编辑栏目：图标留在白底，缩小的栏目标题以黑底白字显示（墨水屏）。"""
    content = content or ""
    if content.lstrip().startswith("<tr"):
        content = (f'<table width="100%" cellpadding="0" cellspacing="0" '
                   f'style="width:100%!important;border-collapse:collapse;">{content}</table>')
    cap = (f'<div style="font-size:{GZ_FS_META}px;color:{GZ_META};padding-top:10px;line-height:1.8;">{caption}</div>'
           if caption else "")
    badge = (f'<div style="font-size:{GZ_FS_META}px;padding-top:8px;">{badge_html}</div>' if badge_html else "")
    # bgcolor + 内联 background 双写：微信即使移除部分 CSS，白字仍有黑底；
    # 黑色 SVG 图标放在黑底之外，避免装饰图标消失。
    title_bar = gz_shell(
        f'<h2 style="margin:0;background:{GZ_INK};font-size:{GZ_FS_SECTION}px;'
        f'font-weight:{GZ_W_BOLD};color:{GZ_PAPER};font-family:{GZ_SERIF};'
        f'letter-spacing:1px;line-height:1.4;">{_esc(title)}</h2>',
        bg=GZ_INK, pad="12px 16px")
    head = gz_shell(
        f'<div style="border-top:{GZ_HAIR_W}px solid {GZ_HAIR};padding-top:28px;">'
        f'{gz_icon(KOBOYO_SECTION_ICONS.get(kicker_en, "document"))}</div>'
        f'{title_bar}{cap}{badge}', bg=GZ_PAPER, pad="40px 0 16px")
    body = gz_shell(content, bg=GZ_PAPER, pad="0 0 12px")
    return head + body


def gz_ai_analysis_block(res):
    """AI 盘研判 · 依据展开：倾向与核心判断已置顶到「今日结论」，关注主题收在「盘点总结」。"""
    out = []
    if res["sectors_strong"]:
        out.append(gz_subsection("板块热度") + gz_data_table(
            ["板块", "提及"],
            [[_esc(sec), f"{cnt} 次"] for sec, cnt in res["sectors_strong"]]))
        if res["sectors_weak"]:
            out.append(gz_shell(
                f'<div style="font-size:{GZ_FS_BODY}px;color:{GZ_DOWN};font-weight:700;line-height:1.6;">'
                f'▼ 承压板块 · {" / ".join(_esc(s) for s in res["sectors_weak"])}</div>',
                bg=GZ_PAPER, pad="12px 0"))
    tech_stats = res.get("tech_stats") or {}
    if tech_stats.get("count"):
        band_palette = {"强势": GZ_UP, "偏强": GZ_UP, "震荡": GZ_WARN,
                        "偏弱": GZ_DOWN, "弱势": GZ_DOWN}
        breadth = (
            f'<span style="color:{GZ_UP};font-weight:700;">▲ {tech_stats.get("ups", 0)}</span> / '
            f'<span style="color:{GZ_DOWN};font-weight:700;">▼ {tech_stats.get("downs", 0)}</span> / '
            f'<span style="color:{GZ_FLAT};font-weight:700;">■ {tech_stats.get("flats", 0)}</span>'
            f' · 平均 {gz_trend_badge(tech_stats.get("avg"), compact=True)}')
        extremes = []
        for tag, info in (("最强", tech_stats.get("best") or {}),
                          ("最弱", tech_stats.get("worst") or {})):
            if info.get("label"):
                extremes.append(
                    f'{tag} {_esc(info["label"])} '
                    f'<span style="color:{band_palette.get(info.get("band"), GZ_INK)};">'
                    f'{_esc(info.get("band", ""))}</span>')
        tech_pairs = [(f'{tech_stats["count"]} 个指数', breadth)]
        if extremes:
            tech_pairs.append(("两极", " · ".join(extremes)))
        if res.get("tech_read"):
            tech_pairs.append(("解读", _esc(res["tech_read"])))
        out.append(gz_subsection("指数动能") + gz_kv_table(tech_pairs))
    if res["risks"]:
        risk_cards = []
        for risk in res["risks"]:
            if risk.get("shown") and risk.get("anchor"):
                # 已在正文展示：仅引用定位（栏目 + 序号），全文不重复出现
                main = (f'<a href="#{_esc(risk["anchor"])}" '
                        f'style="color:{GZ_INK};font-weight:700;text-decoration:none;">'
                        f'→ {_esc(_risk_ref_label(risk))}</a>')
                sub = _risk_ref_detail(risk)
            else:
                sub_bits = [risk.get("source") or "", risk.get("time") or ""]
                if risk.get("keywords"):
                    sub_bits.append("命中：" + "/".join(risk["keywords"]))
                main = _esc((risk.get("title") or "")[:110])
                sub = " · ".join(x for x in sub_bits if x)
            risk_cards.append(gz_item_row("!", main, sub))
        out.append(gz_subsection("风险提示") + "".join(risk_cards))
    return "".join(out)


def _gz_direction_prob(chg):
    if chg is None:
        return None
    return 50 + min(30, int(round(abs(chg) * 20)))


def _gz_factor_sentiment(text):
    bull = sum(text.count(w) for w in _AI_BULL_WORDS)
    bear = sum(text.count(w) for w in _AI_BEAR_WORDS)
    if bull > bear:
        return "▲", GZ_UP
    if bear > bull:
        return "▼", GZ_DOWN
    return "■", GZ_FLAT


def _gz_market_change(quotes, labels):
    chgs = []
    for lbl in labels:
        q = (quotes or {}).get(lbl)
        if isinstance(q, dict):
            p = _percent_number(q.get("change_pct", 0))
            if p is not None:
                chgs.append(p)
    return (sum(chgs) / len(chgs)) if chgs else None





# ============================================================
# 主题渲染套件：把 pixel / guizang 两套布局助手统一成栏目拼版接口
# ============================================================
class _RenderKit:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _pixel_market_section(market):
    def _block(title, specs):
        rows = []
        for label, precision in specs:
            if _quote_parts(market, label, precision)[0] is None:
                continue          # 缺失品种不出「数据暂缺」行
            value, color = _quote_value(market, label, precision)
            rows.append((label, value, color))
        return (_subsection(title) + _data_table(rows)) if rows else ""

    return (_block("全球与美股", [("道琼斯指数", 0), ("标普500", 0), ("纳斯达克", 0),
                                 ("WTI 原油", 2), ("微软 MSFT", 2), ("Meta META", 2)])
            + _block("A股四指数", [("上证指数", 2), ("深证成指", 2), ("创业板指", 2), ("科创50", 2)])
            + _block("港股双指数", [("恒生指数", 2), ("恒生科技", 2)]))


def _panorama_block(pan):
    """pixel 版「A股大盘全景复盘」：指数表现 / 涨跌家数 / 成交额 / 北向资金 / 板块热力。"""
    parts = []

    # 1) 指数表现
    indices = pan.get("indices") or []
    if indices:
        rows = []
        for idx in indices:
            pct = idx.get("chg_pct")
            color = C_GREEN if (pct or 0) > 0 else (C_RED if (pct or 0) < 0 else C_AMBER)
            amt = (f' <span style="color:{C_FAINT};font-size:10px;">'
                   f'成交额 {_format_amount(idx["amount"])}</span>') if idx.get("amount") else ""
            left = f'<b style="color:{C_INK};">{_esc(idx["name"])}</b>{amt}'
            right = f'{idx["price"]:,.2f} {_trend_badge(pct)}'
            rows.append((left, right, color))
        parts.append(_subsection("指数表现") + _mini_table(rows))

    # 2) 涨跌家数（市场宽度）
    b = pan.get("breadth")
    if b:
        meter = _signal_meter(b["up"], max(1, b["up"] + b["down"]), color=C_CYAN, cells=5)
        breadth_line = (f'<span style="color:{C_GREEN};font-weight:900;">▲ 上涨 {b["up"]:,} 家</span>'
                        f' <span style="color:{C_MUTED};">/</span> '
                        f'<span style="color:{C_RED};font-weight:900;">▼ 下跌 {b["down"]:,} 家</span>'
                        f' <span style="color:{C_MUTED};">/</span> '
                        f'<span style="color:{C_AMBER};font-weight:900;">■ 平盘 {b["flat"]:,} 家</span>')
        ratio_txt = f'{b["ratio"]:.2f}' if b.get("ratio") is not None else "—"
        rows = [("沪深京市场宽度", breadth_line),
                ("涨跌比 / 情绪", f'{meter} <b style="color:{C_LEMON};">{ratio_txt}</b>'
                              f' · {_esc(b.get("mood") or "—")}')]
        blk = _subsection("涨跌家数") + _mini_table(rows)
        if b.get("partial"):
            blk += _note("部分交易所涨跌家数暂缺，本栏为已取得市场的合计。")
        parts.append(blk)

    # 3) 成交额
    t = pan.get("turnover")
    if t:
        chg = t.get("chg_pct")
        chg_html = (f' 较上一交易日 {_trend_badge(chg, compact=True)}' if chg is not None
                    else f' <span style="color:{C_FAINT};font-size:10px;">（环比暂缺）</span>')
        line = (f'<span style="color:{C_LEMON};font-size:15px;font-weight:900;">'
                f'{_format_amount(t["total"])}</span>{chg_html}')
        rows = [("沪深京成交额合计", line)]
        if t.get("prev_total"):
            rows.append(("上一交易日合计（沪深京）", _format_amount(t["prev_total"])))
        parts.append(_subsection("成交额") + _mini_table(rows))

    # 4) 南北向资金（前一收盘成交总额 + 披露口径说明）
    north = pan.get("north") or {}
    if north:
        north_val = (f'<span style="color:{C_CYAN};font-weight:900;">'
                     f'{north["amount_yi"]:,.2f} 亿元</span>') \
            if (north.get("available") and north.get("amount_yi") is not None) \
            else f'<span style="color:{C_FAINT};">■ 数据暂缺</span>'
        south_val = (f'<span style="color:{C_CYAN};font-weight:900;">'
                     f'{north["south_amount_yi"]:,.2f} 亿元</span>') \
            if (north.get("south_available") and north.get("south_amount_yi") is not None) \
            else f'<span style="color:{C_FAINT};">■ 数据暂缺</span>'
        parts.append(_subsection("南北向资金（前一收盘）")
                     + _mini_table([
                         (f'北向成交总额（{_esc(north.get("date") or "—")}）', north_val),
                         (f'南向成交总额（{_esc(north.get("south_date") or north.get("date") or "—")}）', south_val),
                     ])
                     + _note(north.get("policy_note") or PANORAMA_NORTH_POLICY_NOTE))

    # 5) 板块热力
    sec = pan.get("sectors") or {}
    for title, key in (("板块热力 · 领涨行业 TOP", "leading"),
                       ("板块热力 · 领跌行业 TOP", "lagging")):
        items = sec.get(key) or []
        if not items:
            continue
        rows = []
        for it in items:
            sub_bits = []
            if it.get("main_inflow") is not None:
                sub_bits.append(f'主力{_format_amount(it["main_inflow"])}')
            if it.get("lead_stock"):
                lead_pct = it.get("lead_stock_pct")
                sub_bits.append(f'领涨 {_esc(it["lead_stock"])}'
                                + (f' {lead_pct:+.2f}%' if lead_pct is not None else ''))
            sub = (f' <span style="color:{C_FAINT};font-size:10px;">{" · ".join(sub_bits)}</span>'
                   if sub_bits else "")
            rows.append((f'{_esc(it["name"])}{sub}', _trend_badge(it.get("chg_pct"), compact=True)))
        parts.append(_subsection(title) + _mini_table(rows))

    if pan.get("quote_time"):
        parts.append(_note(
            f"数据截至 {_esc(pan['quote_time'])}（北京时间）；成交额「亿/万」为本地换算。"
            "板块按行业涨跌幅排序。规则合成，非投资建议。"))
    return "".join(parts)


def _cal_pixel_cells(day_label, t_plus, item, first=False):
    """pixel 日历表的一行：日期（当天首行附 T+n）/ 时间 / 星号 + 地区 + 时间点。"""
    item = item if isinstance(item, dict) else {}
    imp = max(1, min(3, int(item.get("imp") or 1)))
    color = C_LEMON if imp >= 3 else (C_CYAN if imp == 2 else C_MUTED)
    day_html = ""
    if first:
        day_html = f'<b style="color:{C_INK};">{_esc(day_label)}</b>'
        when = _cal_countdown(t_plus)
        if when:
            day_html += (f'<div style="font-size:9px;color:{C_FAINT};padding-top:2px;">'
                         f'{_esc(when)}</div>')
    city = str(item.get("city") or "").strip()
    city_html = f'<span style="color:{C_FAINT};">{_esc(city)}</span> ' if city else ""
    body = (f'<span style="color:{color};font-weight:900;">{"★" * imp}</span> '
            f'{city_html}{_esc(_cal_item_text(item))}')
    return [day_html, _esc(str(item.get("time") or "—")), body]


def _calendar_block(res):
    """pixel 版「未来 N 天影响经济时间点」：窗口摘要 + 全窗口一张三列日历表。"""
    digest, rows = _calendar_table_rows(res, _cal_pixel_cells)
    parts = []
    pairs = digest.get("pairs") or []
    if pairs:
        parts.append(_subsection("窗口摘要"))
        parts.append(_pixel_table(None, [[_esc(a), _esc(b)] for a, b in pairs],
                                  aligns=("left", "left"), widths=("26%", "74%")))
    if rows:
        parts.append(_subsection("逐日时间点（北京时间）"))
        parts.append(_pixel_table(["日期", "时间", "影响经济的时间点"], rows,
                                  aligns=("left", "left", "left"),
                                  widths=("17%", "13%", "70%")))
    return "".join(parts)


# ============================================================
# 精简排版（2026-09-27）：结论先行 → 分栏展开 → 盘点收尾
# ——正文不再出现口径说明 / 免责声明脚注、「数据暂缺」占位行、抓取失败的来源
#   与过期内容；来源状态只在末尾「盘点总结」里压成一行。
# ============================================================
REPORT_STALE_DAYS = 7          # 频道视频 / 全球头条超过 N 天视为过期，不进正文

# 详情字段里纯说明性质的片段（免责声明、口径提示），渲染时剔除。
_CONCISE_DROP_MARKERS = (
    "未经核实", "仅供", "不是交易信号", "不抓取", "非今日", "抓取快照", "不代表",
    "休市时", "官网公开榜单", "原站入口", "站点未标注",
)


def _concise_detail(text):
    """保留详情里的数据与时间，去掉免责 / 口径说明片段。"""
    parts = [p.strip() for p in re.split(r"\s*·\s*", str(text or "")) if p.strip()]
    kept = [p for p in parts if not any(m in p for m in _CONCISE_DROP_MARKERS)]
    return " · ".join(kept).replace("（北京时间）", "")


def _report_date_obj(date_str):
    try:
        return datetime.strptime(str(date_str), "%Y%m%d").date()
    except (TypeError, ValueError):
        return datetime.now(CST).date()


def _is_stale(stamp, anchor_date, days=REPORT_STALE_DAYS):
    """``YYYY-MM-DD…`` 早于报告日 ``days`` 天以上 → 过期；无法解析的时间不判过期。"""
    try:
        d = datetime.strptime(str(stamp)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return (anchor_date - d).days > days


def _prune_report_data(data, date_str=None):
    """渲染前剔除过期内容（不改动原始 data，存档 / 推送门禁不受影响）。

    - 港股名家频道：只留近 ``REPORT_STALE_DAYS`` 天的视频，全部过期的频道整体移除；
    - 全球头条：去掉发布超过 ``REPORT_STALE_DAYS`` 天的标题。
    AI 盘研判 / 情绪因子与正文使用同一份裁剪数据，锚点序号保持一致。
    """
    anchor = _report_date_obj(date_str or _today_str())
    out = dict(data or {})
    yt = out.get("港股名家频道")
    if isinstance(yt, dict) and yt.get("channels"):
        channels = []
        for ch in yt.get("channels") or []:
            videos = [v for v in (ch.get("videos") or [])
                      if not _is_stale(v.get("published_cst"), anchor)]
            if videos:
                channels.append({**ch, "videos": videos})
        out["港股名家频道"] = {**yt, "channels": channels}
    google = out.get("全球头条")
    if isinstance(google, dict) and google.get("headlines"):
        heads = [h for h in google.get("headlines") or []
                 if not (isinstance(h, dict) and _is_stale(h.get("published_cst"), anchor))]
        out["全球头条"] = {**google, "headlines": heads}
    return out


def _short_source(item):
    """栏目副标题只留来源名，抓取时间 / 口径说明不再重复。"""
    return _esc(str((item or {}).get("source") or ""))


def _trend_clues_block(data, kit):
    """两主题共用：Reddit 趋势跟踪线索 —— 10 个板块的热门帖样本（每板块至多 5 条）。

    无数据的板块不进正文；缺失板块只在盘点总结的「数据覆盖」里点名。
    """
    color = GZ_INK if kit is GUIZANG_KIT else C_CYAN
    source = data.get("Reddit") or {}
    if source.get("status") != "success":
        return ""
    by_board = {}
    for item in source.get("items") or []:
        if isinstance(item, dict):
            by_board.setdefault(str(item.get("community") or ""), []).append(item)
    rows = []
    homepage = _public_url(PUBLIC_SITE_URLS["Reddit"])
    latest = _public_text(source.get("content_date") or "", 30)
    heading = (f'<a href="{_esc(homepage)}" style="color:{color};text-decoration:underline;">'
               f'<b>Reddit</b></a> {kit.source_badge(source)}')
    rows.append(kit.item_row("", heading, _esc(latest)))
    for community, label in _REDDIT_BOARDS:
        board_items = [it for it in by_board.get(f"r/{community}", [])
                       if isinstance(it, dict)][:REDDIT_POSTS_PER_BOARD]
        if not board_items:
            continue
        rows.append(kit.item_row("▤", f'<b>{_esc(f"r/{community}")}</b> · {_esc(label)}',
                                 f"热门帖样本 {len(board_items)} 条"))
        for pick_no, item in enumerate(board_items, 1):
            url = _public_url(item.get("url"), PUBLIC_SITE_URLS["Reddit"])
            title = _public_text(item.get("title"), 235)
            if not (url and title):
                continue
            link = (f'<a href="{_esc(url)}" style="color:{color};text-decoration:underline;">'
                    f'{_esc(title)}</a>')
            rows.append(kit.item_row(f"{pick_no:02d}", link,
                                     _esc(_concise_detail(_public_text(item.get("detail"), 210)))))
    return kit.rows("".join(rows)) if rows else ""


def _market_brief(market, labels, kit):
    """「道指 ▲+0.93% · 标普 ▲+0.51%」式一行行情摘要；缺失项直接略过。"""
    bits = []
    for label, short in labels:
        _, pct = _quote_parts(market or {}, label)
        if pct is not None:
            bits.append(f"{_esc(short)} {kit.trend(pct, compact=True)}")
    return " · ".join(bits)


def _conclusion_pairs(kit, ai_result, market, pan, policy, quant=None):
    """页首「今日结论」：倾向 → 量化预测 → 核心判断 → 各市场一句话 → 政策定调。"""
    pairs = []
    # 量化预测置顶：概率 + 区间 + 模型可信度，一眼看到「结论与把握有多大」
    if quant and quant.get("available"):
        head = quant.get("headline") or {}
        if head.get("available"):
            pairs.append(("量化预测",
                          f'<b>{_esc(head.get("arrow", "■"))} '
                          f'{_esc(head.get("label", "中性"))} '
                          f'{head.get("p_up", 0) * 100:.0f}%</b>'
                          f' · {_esc(quant.get("target_label") or "下一交易日")}'))
    if ai_result and ai_result.get("available"):
        score = int(ai_result["score"])
        arrow = "▲" if score > 8 else ("▼" if score < -8 else "■")
        pairs.append(("市场倾向", f'<b>{_esc(ai_result["sentiment_label"])} {arrow}</b>'
                                 f' · 信号 {score:+d} · 置信度 {_esc(ai_result["confidence"])}'))
        if ai_result.get("reason"):
            pairs.append(("核心判断", _esc(ai_result["reason"])))
    if pan and pan.get("status") == "success":
        bits = []
        sh = next((i for i in (pan.get("indices") or []) if i.get("name") == "上证指数"), None)
        if sh and sh.get("price") is not None:
            bits.append(f'上证 {sh["price"]:,.2f} {kit.trend(sh.get("chg_pct"), compact=True)}')
        b = pan.get("breadth") or {}
        if b:
            bits.append(f'{_esc(b.get("mood") or "")}（涨 {b.get("up", 0):,} / 跌 {b.get("down", 0):,}）')
        t = pan.get("turnover") or {}
        if t.get("total"):
            chg = t.get("chg_pct")
            bits.append(f'成交 {_format_amount(t["total"])}'
                        + (f' {kit.trend(chg, compact=True)}' if chg is not None else ""))
        if bits:
            pairs.append(("A股", " · ".join(bits)))
    elif market and market.get("status") == "success":
        line = _market_brief(market, [("上证指数", "上证"), ("深证成指", "深成")], kit)
        if line:
            pairs.append(("A股", line))
    if market and market.get("status") == "success":
        us = _market_brief(market, [("道琼斯指数", "道指"), ("标普500", "标普"), ("纳斯达克", "纳指")], kit)
        if us:
            pairs.append(("美股", us))
        hk = _market_brief(market, [("恒生指数", "恒指"), ("恒生科技", "恒科")], kit)
        if hk:
            pairs.append(("港股", hk))
    if policy and policy.get("available"):
        line = f'PSI {policy["broad_score"]:+d}（{_esc(policy["broad_label"])}）'
        if policy.get("winners"):
            line += " · 受益 " + "、".join(_esc(w["name"]) for w in policy["winners"][:2])
        if policy.get("losers"):
            line += " · 承压 " + "、".join(_esc(w["name"]) for w in policy["losers"][:2])
        pairs.append(("政策", line))
    return pairs


def _summary_pairs(ai_result, pan, policy, source_items, today_n, total, quant=None):
    """末尾「盘点总结」：结论回顾 → 模型校准与预测追踪 → 明日关注 → 风险 → 数据覆盖。"""
    pairs = []
    if quant and quant.get("available"):
        v1 = (quant.get("validation") or {}).get(1) or {}
        if v1:
            sig = ""
            if v1.get("z") is not None:
                sig = ("（显著）" if abs(v1["z"]) >= 1.96 else
                       "（弱显著）" if abs(v1["z"]) >= 1.28 else "（不显著）")
            pairs.append(("模型校准",
                          f'推进式回测 {v1.get("n", 0)} 日 · 命中 '
                          f'{(v1.get("hit_rate") or 0) * 100:.0f}% · 基准 '
                          f'{(v1.get("base_rate") or 0) * 100:.0f}%{sig}'))
        jr = quant.get("journal") or {}
        if jr.get("n"):
            bits = [f'已结算 {jr["n"]} 次 · 方向命中 {(jr.get("hit_rate") or 0) * 100:.0f}%']
            if jr.get("band_hit_rate") is not None:
                bits.append(f'区间命中 {jr["band_hit_rate"] * 100:.0f}%')
            if jr.get("brier") is not None:
                bits.append(f'Brier {jr["brier"]:.3f}')
            pairs.append(("预测追踪", _esc(" · ".join(bits))))
    recap = []
    if ai_result and ai_result.get("available"):
        recap.append(f'整体{ai_result["sentiment_label"]}')
    b = (pan or {}).get("breadth") or {}
    if (pan or {}).get("status") == "success" and b.get("mood"):
        recap.append(f'A股{b["mood"]}')
    if policy and policy.get("available"):
        recap.append(f'政策{policy["broad_label"]}')
    if recap:
        pairs.append(("今日盘点", _esc("｜".join(recap))))
    if ai_result and ai_result.get("themes"):
        pairs.append(("明日关注", _esc(ai_result["themes"])))
    if ai_result and ai_result.get("risks"):
        counts = {}
        for r in ai_result["risks"]:
            for kw in r.get("keywords") or []:
                counts[kw] = counts.get(kw, 0) + 1
        if counts:
            kws = "、".join(f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
            pairs.append(("风险关注", _esc(kws)))
    elif ai_result and ai_result.get("available"):
        pairs.append(("风险关注", "未检出显著风险舆情"))
    missing = [name for name, s in source_items if s.get("status") != "success"]
    cover = f"当天 {today_n}/{total} 源"
    if missing:
        cover += " · 暂缺：" + "、".join(missing)
    pairs.append(("数据覆盖", _esc(cover)))
    return pairs


# 阅读顺序：结论 → 前瞻日程（未来30天影响经济时间点）→ 数据（行情 / 全景 / 政策 / 研判依据）
#           → 趋势跟踪线索与资讯 → 新闻情绪 → 盘点。
REPORT_SECTION_ORDER = (
    "CONCLUSION",
    "ECON CALENDAR",
    "QUANT FORECAST", "HK PROBABILITY", "LIQUIDITY FLOW",
    "MARKET SNAPSHOT", "A-SHARE PANORAMA", "POLICY SHOCK", "AI READ",
    "TREND CLUES", "GLOBAL HEADLINES", "EASTMONEY WIRE", "A-SHARE DESK",
    "HK GURU CHANNELS", "NEWS SENTIMENT",
    "WRAP-UP",
)


# ============================================================
# 逐栏目 AI 研判（规则合成）：概率化多空判断 + 分析预测总结
# —— 每个有实际数据的栏目末尾追加一行「⌁ AI 研判」：
#    多头 xx% / 空头 xx%（概率夹在 5%~95%，绝不绝对化）+ 一句判断/预测。
#    证据全部来自该栏目自身数据（涨跌方向 / 热度 / 关键词命中 / 归因结果），
#    确定性计算、可复现、不调外部大模型、不伪造内容；定位参考，非投资建议。
# ============================================================
_REDDIT_BULL_RE = re.compile(
    r"\b(rall(?:y|ied)|surge\w*|soar\w*|pump\w*|moon\w*|yolo|bullish|breakout|rebound|"
    r"recover\w*|upgrade\w*|record high|all-?time high|beat\w*|boom\w*)\b", re.I)
_REDDIT_BEAR_RE = re.compile(
    r"\b(crash\w*|dump\w*|tank\w*|plunge\w*|selloff|bearish|short\w*|fud|scam|"
    r"bankrupt\w*|layoff\w*|warn\w*|loss\w*|correction|decline\w*|tumble\w*|"
    r"slump\w*|sank|sink\w*)\b", re.I)
_REDDIT_TICKER_RE = re.compile(r"\$([A-Za-z]{1,5})\b")


def _ai_judge_prob(bull, bear):
    """多空证据量 → 多头概率（5%~95%）；证据持平 50%，全偏一侧最高 95%（绝不绝对化）。"""
    total = bull + bear
    if total <= 0:
        return 50
    return int(max(5, min(95, round(50 + 45 * (bull - bear) / total))))


def _ai_judge_label(prob):
    """概率 → 方向标记与多空定调（60% 以上偏多 / 40% 以下偏空 / 其间中性）。"""
    if prob >= 60:
        return "▲", "偏多"
    if prob <= 40:
        return "▼", "偏空"
    return "■", "中性"


def _judge_note(prob, text):
    mark, label = _ai_judge_label(prob)
    return {"bull_pct": prob, "bear_pct": 100 - prob, "mark": mark,
            "label": label, "text": text}


def _zh_title_bull_bear(titles):
    """中文标题词表命中计数（复用 AI 盘研判多/空词表）。"""
    bull = bear = 0
    for t in titles:
        txt = str(t or "")
        bull += sum(txt.count(w) for w in _AI_BULL_WORDS)
        bear += sum(txt.count(w) for w in _AI_BEAR_WORDS)
    return bull, bear


def _top_themes(titles, top_n=2):
    """按板块关键词命中量取主题；无任何命中时返回空（不猜）。"""
    counts = {}
    for name, words in AI_SECTOR_KEYWORDS.items():
        for t in titles:
            txt = str(t or "")
            hits = sum(txt.count(w) for w in words)
            if hits:
                counts[name] = counts.get(name, 0) + hits
    if not counts:
        return []
    return [name for name, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]]


def build_section_ai_notes(data, *, policy=None, senti=None):
    """为有内容的数据栏目生成逐栏 AI 研判（概率多空 + 预测）。

    返回 {kicker: note}；仅真实有数据的栏目出研判。结论型栏目
    （今日结论 / AI 盘研判 / 盘点总结）本身即总结判断，不重复追加。
    注意：text 内数据片段必须已 _esc（渲染端不再二次转义）。
    """
    notes = {}

    # ① 行情速览：涨跌家数 + 最强/最弱 → 方向定调
    market = data.get("实时行情") or {}
    if market.get("status") == "success":
        rows = []
        for label, q in (market.get("quotes") or {}).items():
            pct = _percent_number((q or {}).get("change_pct"))
            if pct is not None:
                rows.append((str(label), pct))
        if rows:
            bull = round(sum(max(p, 0) for _, p in rows), 4)
            bear = round(sum(max(-p, 0) for _, p in rows), 4)
            prob = _ai_judge_prob(bull, bear)
            up_n = sum(1 for _, p in rows if p > 0)
            down_n = sum(1 for _, p in rows if p < 0)
            strongest, weakest = max(rows, key=lambda r: r[1]), min(rows, key=lambda r: r[1])
            if down_n == 0 and up_n > 0:
                verdict = "普涨格局，关注量能延续性"
            elif up_n == 0 and down_n > 0:
                verdict = "普跌格局，防御为主"
            else:
                verdict = "结构分化，跟随强势方向"
            notes["MARKET SNAPSHOT"] = _judge_note(
                prob, f"{len(rows)} 项报价 涨{up_n} / 跌{down_n}（最强 {_esc(strongest[0])}、"
                      f"最弱 {_esc(weakest[0])}）→ 预测：{verdict}")

    # ② A股大盘全景：市场宽度 + 成交额环比 + 领涨板块 → 三票合成
    pan = data.get("A股大盘全景") or {}
    if pan.get("status") == "success":
        b = pan.get("breadth") or {}
        t = pan.get("turnover") or {}
        lead = ((pan.get("sectors") or {}).get("leading") or [{}])[0]
        bull = bear = 0
        up, down = b.get("up") or 0, b.get("down") or 0
        if up > down:
            bull += 2 if (b.get("ratio") or 0) >= 1.2 else 1
        elif down > up:
            bear += 2 if (b.get("ratio") or 0) <= 0.8 else 1
        chg = _percent_number(t.get("chg_pct"))
        if chg is not None:
            if chg > 1:
                bull += 1
            elif chg < -1:
                bear += 1
        lead_pct = _percent_number(lead.get("chg_pct"))
        if lead_pct is not None:
            if lead_pct >= 2:
                bull += 1
            elif lead_pct < 0:
                bear += 1
        prob = _ai_judge_prob(bull, bear)
        _mark, label = _ai_judge_label(prob)
        if label == "偏多":
            verdict = "宽度与情绪偏多，进攻略优"
        elif label == "偏空":
            verdict = "宽度与情绪偏空，防御优先"
        else:
            verdict = "震荡结构，等量能定方向"
        bits = [f"宽度 {_esc(str(b.get('mood') or '—'))}",
                f"成交{'放量' if (chg or 0) > 0 else '缩量'}"]
        if lead.get("name"):
            bits.append(f"领涨 {_esc(str(lead['name']))}")
        notes["A-SHARE PANORAMA"] = _judge_note(prob, "，".join(bits) + f" → 预测：{verdict}")

    # ③ 政策因子：PSI 方向 + 受益/承压行业 → 实施节奏预测
    if isinstance(policy, dict) and policy.get("available"):
        score = int(policy.get("broad_score") or 0)
        prob = _ai_judge_prob(max(score, 0), max(-score, 0))
        _mark, label = _ai_judge_label(prob)
        if label == "偏多":
            verdict = "政策顺风，关注未来 15 日落地节奏"
        elif label == "偏空":
            verdict = "政策压力，关注受影响行业回撤"
        else:
            verdict = "政策中性，关注边际变化"
        detail = f"方向 {_esc(str(policy.get('broad_label') or '中性'))}"
        winners = policy.get("winners") or []
        losers = policy.get("losers") or []
        if winners:
            detail += "，受益 " + "、".join(_esc(str(w.get('name'))) for w in winners[:2])
        if losers:
            detail += "，承压 " + "、".join(_esc(str(l.get('name'))) for l in losers[:2])
        notes["POLICY SHOCK"] = _judge_note(prob, f"{detail} → 预测：{verdict}")

    # ④ 趋势跟踪线索（Reddit）：多空词命中 + 热股提取 → 散户情绪判断
    reddit = data.get("Reddit") or {}
    if reddit.get("status") == "success" and reddit.get("items"):
        items = [it for it in reddit["items"] if isinstance(it, dict)]
        bull = bear = 0
        tickers = {}
        for it in items:
            title = str(it.get("title") or "")
            bull += len(_REDDIT_BULL_RE.findall(title))
            bear += len(_REDDIT_BEAR_RE.findall(title))
            for sym in _REDDIT_TICKER_RE.findall(title):
                key = sym.upper()
                tickers[key] = tickers.get(key, 0) + 1
        prob = _ai_judge_prob(bull, bear)
        _mark, label = _ai_judge_label(prob)
        boards_n = len({it.get("community") for it in items if it.get("community")})
        top = [f"{s}×{c}" for s, c in sorted(tickers.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        detail = f"十板块扫描 {len(items)} 条热帖（{boards_n} 板块有数据）"
        if top:
            detail += "，热股 " + "、".join(_esc(t) for t in top)
        detail += f"，多空词 {bull} 多 / {bear} 空"
        notes["TREND CLUES"] = _judge_note(
            prob, f"{detail} → 预测：散户情绪{label}，关注高热标的与基本面背离（观点非事实）")

    # ⑤ 资讯类栏目：全球头条 / 东财快讯 / A股资讯（多空词 + 热门主题）
    for kick, source_key, noun in (("GLOBAL HEADLINES", "全球头条", "条头条"),
                                   ("EASTMONEY WIRE", "东财快讯", "条快讯"),
                                   ("A-SHARE DESK", "A股资讯", "条资讯")):
        src = data.get(source_key) or {}
        titles = []
        for h in (src.get("headlines") or []):
            t = h if isinstance(h, str) else str((h or {}).get("title") or "")
            if t:
                titles.append(t)
        if not titles:
            continue
        bull, bear = _zh_title_bull_bear(titles)
        prob = _ai_judge_prob(bull, bear)
        _mark, label = _ai_judge_label(prob)
        themes = _top_themes(titles)
        detail = f"{len(titles)} {noun}：多空词 {bull} 多 / {bear} 空"
        if themes:
            detail += "，热门主题 " + "、".join(_esc(t) for t in themes)
        watch = _esc(themes[0]) if themes else "后续进展"
        notes[kick] = _judge_note(prob, f"{detail} → 预测：头条情绪{label}，关注 {watch}")

    # ⑥ 港股名家频道：更新频道数 + 观点词命中 → 名家观点定调
    yt = data.get("港股名家频道") or {}
    yt_live = yt.get("channels") or []
    if yt_live:
        titles = [str(v.get("title") or "")
                  for ch in yt_live for v in (ch.get("videos") or [])]
        titles = [t for t in titles if t]
        bull, bear = _zh_title_bull_bear(titles)
        active_n = sum(1 for ch in yt_live if ch.get("is_today"))
        prob = _ai_judge_prob(bull, bear)
        _mark, label = _ai_judge_label(prob)
        themes = _top_themes(titles, top_n=1)
        focus = _esc(themes[0]) if themes else "大盘技术面"
        notes["HK GURU CHANNELS"] = _judge_note(
            prob, f"今日 {active_n} 频道有新内容，观点 {bull} 多 / {bear} 空"
                  f" → 预测：名家观点整体{label}，关注：{focus}")

    # ⑦ AI 新闻情绪因子：已归因个股的正负命中合计 → 整体新闻情绪
    if isinstance(senti, dict) and senti.get("total_matched"):
        stocks = [s for s in (senti.get("stocks") or []) if isinstance(s, dict)]
        if stocks:
            bull = sum(int(s.get("pos") or 0) for s in stocks)
            bear = sum(int(s.get("neg") or 0) for s in stocks)
            prob = _ai_judge_prob(bull, bear)
            _mark, label = _ai_judge_label(prob)
            best = max(stocks, key=lambda s: float(s.get("score") or 0))
            worst = min(stocks, key=lambda s: float(s.get("score") or 0))
            notes["NEWS SENTIMENT"] = _judge_note(
                prob, f"归因 {senti.get('total_matched')} 只（前 {len(stocks)} 只评分），"
                      f"最强 {_esc(str(best.get('name')))}、最弱 {_esc(str(worst.get('name')))}"
                      f" → 预测：新闻情绪{label}，关注情绪与价格背离")

    return notes


def _ai_judge_row(note, kit):
    """逐栏 AI 研判行（两主题共用）：⌁ AI 研判 ▲ 偏多 · 多头 68% / 空头 32% — 判断预测。"""
    bull_c, bear_c, flat_c = kit.ok_color, kit.bad_color, kit.warn_color
    lc = (bull_c if note["label"] == "偏多"
          else bear_c if note["label"] == "偏空" else flat_c)
    head = (f'<span style="color:{lc};font-weight:900;">⌁ AI 研判 {note["mark"]} {note["label"]}</span>'
            f' · <span style="color:{bull_c};font-weight:900;">多头 {note["bull_pct"]}%</span>'
            f' / <span style="color:{bear_c};font-weight:900;">空头 {note["bear_pct"]}%</span>')
    return kit.item_row("⌁", f"{head} — {note['text']}")


def _collect_report_parts(data, kit, sentiment_history=None, date_str=None,
                            policy_result=None, news_corpus=None):
    """提取逐栏目内容与当天检验统计（两主题共用；仅渲染套件不同）。

    sentiment_history: 跨日情绪基线（AI 新闻情绪因子动量/新闻量窗口用）；
    date_str: 报告日期 YYYYMMDD（划分今日与历史的界线），缺省取当天；
    policy_result: main 1.6 阶段单独构建的政策因子结果，缺省时兜底构建；
    news_corpus: 跨运行标题存档（output/news_history.json），缺省时因子只用
    本次抓取标题（测试 / 冷启动路径）。
    """
    # 审计口径（当天源 / 总源）基于原始抓取结果；正文渲染用裁剪掉过期内容的副本。
    raw_yt = data.get("港股名家频道", {})
    raw_google = data.get("全球头条", {})
    data = _prune_report_data(data, date_str)
    market = data.get("实时行情", {})
    pan = data.get("A股大盘全景", {}) or {}
    # 官方源作为政策因子输入；兼容外部调用仍使用旧的「中国政府网」键名。
    gov_policy = data.get("国家政策")
    if not isinstance(gov_policy, dict):
        gov_policy = data.get("中国政府网", {}) or {}
    yt = data.get("港股名家频道", {})
    yt_live = yt.get("channels", [])        # 近期有内容的频道
    google = data.get("全球头条", {})
    gh_headlines = google.get("headlines", [])
    sina = data.get("A股资讯", {})
    sina_headlines = sina.get("headlines", [])
    em = data.get("东财快讯", {})
    em_headlines = em.get("headlines", [])
    hot = data.get("热门榜单", {}) or {}

    source_items = [
        ("实时行情", market),
        ("A股大盘全景", pan),
        ("国家政策（中国政府网）", gov_policy),
        ("港股名家频道", raw_yt),
        ("全球头条", raw_google),
        ("A股资讯", sina),
        ("东财快讯", em),
        ("热门榜单", hot),
        ("港股量化引擎（概率/流动性）", data.get("港股量化") or {}),
    ]
    # 前瞻日程（未来 N 天影响经济时间点）：关掉采集时不进审计，总源数保持不变。
    # 它是「今日抓取的日程快照」而非当天发布的内容，因此不计入当天源（当天检验不受影响）。
    if isinstance(data.get("财经日历"), dict):
        source_items.append((f"财经日历（未来{ECON_CALENDAR_DAYS}天时间点）", data["财经日历"]))
    # 仅运行过十站采集时加入审计；外部旧调用若无新键仍维持原来的基础数据源数量。
    source_items.extend((name, data[name]) for name in PUBLIC_SITE_NAMES if name in data)

    total = len(source_items)
    today_n = sum(1 for _, s in source_items if s.get("is_today"))
    content_n = sum(1 for _, s in source_items if s.get("status") == "success")

    # ---- 栏目拼版：结论先行 → 分栏展开 → 盘点收尾（有内容才渲染）----
    blocks = {}  # kicker -> (kicker_en, title, content, badge_html, caption)

    policy = {}
    ai_result = {}
    if AI_ANALYSIS_ENABLED:
        policy = policy_result if policy_result is not None else \
            build_policy_factor(data, date_str, news_corpus)
        ai_result = build_ai_analysis(data)

    # ---- 量化三栏：预测总览 → 港股概率走势 → 资金流动性（结论之后优先展示）----
    quant = {}
    quant_src = data.get("港股量化") or {}
    if isinstance(quant_src, dict):
        quant = quant_src.get("result") or {}
    if quant.get("available"):
        quant_badge = kit.badge("量化模型", "ai")
        fc_html = _quant.render.render_forecast(quant, kit)
        if fc_html:
            blocks["QUANT FORECAST"] = (
                "QUANT FORECAST", "量化预测总览", fc_html, quant_badge, "")
        hk_html = _quant.render.render_hk_probability(quant, kit)
        if hk_html:
            blocks["HK PROBABILITY"] = (
                "HK PROBABILITY", "港股概率走势分析", hk_html, quant_badge, "")
        lq_html = _quant.render.render_liquidity(quant, kit)
        if lq_html:
            blocks["LIQUIDITY FLOW"] = (
                "LIQUIDITY FLOW", "资金流动性分析", lq_html,
                kit.source_badge(quant_src), _short_source(quant_src))

    # ⓪ 未来 N 天影响经济时间点（开头栏目：先看清日程窗口，再读今天的盘）
    cal = data.get("财经日历") or {}
    if cal.get("status") == "success":
        cal_html = kit.calendar_block(cal)
        if cal_html:
            cal_days = int(cal.get("days") or ECON_CALENDAR_DAYS)
            blocks["ECON CALENDAR"] = (
                "ECON CALENDAR", f"未来{cal_days}天影响经济时间点", cal_html,
                kit.source_badge(cal), _short_source(cal),
            )

    # ① 行情速览（逐项行情的唯一展示位置；缺失的品种不出行）
    if market.get("status") == "success":
        market_html = kit.market_section(market)
        if market_html:
            blocks["MARKET SNAPSHOT"] = (
                "MARKET SNAPSHOT", "行情速览", market_html,
                kit.source_badge(market), _short_source(market),
            )

    # ② A股大盘全景复盘
    if pan.get("status") == "success":
        blocks["A-SHARE PANORAMA"] = (
            "A-SHARE PANORAMA", "A股大盘全景复盘", kit.panorama_block(pan),
            kit.source_badge(pan), _short_source(pan),
        )

    # ③ 政策因子
    if policy.get("available"):
        blocks["POLICY SHOCK"] = (
            "POLICY SHOCK", "政策因子", kit.policy_block(policy), kit.ai_badge(), "",
        )

    # ④ AI 盘研判（倾向 / 结论已置顶，此处只展开依据）
    if ai_result.get("available"):
        blocks["AI READ"] = (
            "AI READ", "AI 盘研判", kit.ai_block(ai_result), kit.ai_badge(), "",
        )

    # ⑤ 每日量化策略趋势跟踪线索：单一来源 Reddit（抓取成功且有条目才渲染）
    if (data.get("Reddit") or {}).get("status") == "success":
        digest = _trend_clues_block(data, kit)
        if digest:
            blocks["TREND CLUES"] = ("TREND CLUES", "每日量化策略趋势跟踪线索", digest, "", "")

    # ⑥ 资讯：全球头条 / 东财快讯 / A股资讯 / 港股名家频道
    if gh_headlines:
        gh_items = kit.rows("".join(kit.headline_row(it, i)
                                    for i, it in enumerate(gh_headlines[:GH_DISPLAY_N], 1)))
        blocks["GLOBAL HEADLINES"] = ("GLOBAL HEADLINES", "全球头条", gh_items,
                                      kit.source_badge(google), _short_source(google))
    if em_headlines:
        em_items = kit.rows("".join(kit.em_news_row(it, i)
                                    for i, it in enumerate(em_headlines[:EM_DISPLAY_N], 1)))
        blocks["EASTMONEY WIRE"] = ("EASTMONEY WIRE", "东方财富快讯", em_items,
                                    kit.source_badge(em), _short_source(em))
    if sina_headlines:
        sina_items = kit.rows("".join(kit.item_row(f"{i:02d}", _esc(h[:120]),
                                                   anchor=f"h-cn-{i:02d}")
                                      for i, h in enumerate(sina_headlines[:SINA_DISPLAY_N], 1)))
        blocks["A-SHARE DESK"] = ("A-SHARE DESK", "A股资讯", sina_items,
                                  kit.source_badge(sina), _short_source(sina))
    if yt_live:
        channel_blocks = "".join(kit.channel_block(ch, c) for c, ch in enumerate(yt_live, 1))
        blocks["HK GURU CHANNELS"] = (
            "HK GURU CHANNELS", "港股名家频道", channel_blocks,
            kit.source_badge(yt), f"{len(yt_live)} 个频道有近期更新",
        )

    # ⑦ AI 新闻情绪因子：只有真正归因到个股时才出现（样本不足不再占位）
    senti_result = {}
    if AI_ANALYSIS_ENABLED:
        senti_result = build_news_sentiment(data, date_str or _today_str(),
                                            sentiment_history,
                                            news_corpus=news_corpus)
        if senti_result.get("by_market") and senti_result.get("total_matched"):
            blocks["NEWS SENTIMENT"] = (
                "NEWS SENTIMENT", "AI 新闻情绪因子",
                kit.sentiment_block(senti_result), kit.ai_badge(), "",
            )

    # 页首结论 / 末尾盘点
    conclusion = _conclusion_pairs(kit, ai_result, market, pan, policy, quant=quant)
    if conclusion:
        blocks["CONCLUSION"] = ("CONCLUSION", "今日结论", kit.kv(conclusion), "", "")
    summary = _summary_pairs(ai_result, pan, policy, source_items, today_n, total,
                             quant=quant)
    blocks["WRAP-UP"] = ("WRAP-UP", "盘点总结", kit.kv(summary), "", "")

    sections = [blocks[k] for k in REPORT_SECTION_ORDER if k in blocks]

    # ⑧ 逐栏目 AI 研判：有实际数据的数据栏目末尾追加「⌁ AI 研判」行
    #    （概率化多空判断 + 一句分析预测；规则合成，结论型栏目不重复）。
    judge_notes = build_section_ai_notes(
        data, policy=policy if (isinstance(policy, dict) and policy.get("available")) else None,
        senti=senti_result if (isinstance(senti_result, dict) and senti_result.get("available")) else None)
    if judge_notes:
        new_sections = []
        for kick, title, content, badge, caption in sections:
            note = judge_notes.get(kick)
            if note:
                content = content + _ai_judge_row(note, kit)
            new_sections.append((kick, title, content, badge, caption))
        sections = new_sections

    return {
        "sections": sections,
        "total": total,
        "today_n": today_n,
        "content_n": content_n,
        "market": market,
    }


# ============================================================
# 报告生成（RETRO PIXEL 排版：终端 + 关卡 + 审计 + COLOPHON）
# ——只渲染有内容的区块；每个区块带来源、抓取时间与「当天/非当天/无数据」徽标
# ============================================================
# ============================================================
# AI 盘研判（规则 / 启发式合成，无需大模型 API）
# ------------------------------------------------------------
# 基于当日已抓取的多源信号（实时行情、热门榜单、全球/东财/A股头条、
# 港股名家频道观点）做确定性合成，输出一个跨市场综合研判：
#   情绪定调（多/空/中性 + 信号分 + 置信度）、板块热度、技术速读、
#   风险提示、明日关注主题。全部由规则计算，可复现、不调外部大模型、
#   不伪造内容；明确标注「非投资建议」。
# 2026-08-06 起 WATCH LIST // 明日关注 不再列出榜单个股，只保留主题行；
# 个股仅作为板块热度与交投研判的输入。
# 2026-09-09 起页内去重：指数动能只保留聚合（明细数值见「行情速览」），
# 风险提示对正文已展示的标题仅引用定位（栏目 + 序号 + 命中关键词 + 锚点跳转），
# 正文截断未展示的（如港股第 4 条及以后）保留全文；多因子矩阵不再复述雅虎逐只报价。
# 如需接大模型，可在 build_ai_analysis 内增加 LLM 分支（保留本规则作兜底）。
# ============================================================
AI_ANALYSIS_ENABLED = True

# 板块关键词：从行情/榜单/头条文本中识别板块提及热度
AI_SECTOR_KEYWORDS = {
    "半导体/芯片": ["半导体", "芯片", "集成电路", "晶圆", "中芯", "寒武纪", "北方华创",
                   "韦尔", "兆易", "设备", "光刻"],
    "AI/算力": ["AI", "人工智能", "算力", "大模型", "英伟达", "NVIDIA", "GPU",
                "光模块", "CPO", "服务器", "数据中心"],
    "新能源/锂电": ["新能源", "锂电", "电池", "光伏", "储能", "宁德", "比亚迪",
                    "逆变器", "氢能"],
    "医药/生物": ["医药", "生物", "创新药", "疫苗", "CRO", "制药", "医疗", "器械"],
    "地产/基建": ["地产", "房地产", "物业", "基建", "建材", "水泥", "建筑", "新城"],
    "金融/银行": ["银行", "券商", "保险", "证券", "信托", "金控", "信贷"],
    "消费": ["消费", "白酒", "食品", "饮料", "零售", "家电", "免税", "餐饮"],
    "黄金/有色": ["黄金", "有色", "铜", "铝", "稀土", "金属", "矿业", "锂矿"],
    "军工": ["军工", "国防", "航空", "船舶", "卫星", "航天"],
    "汽车": ["汽车", "整车", "零部件", "特斯拉", "理想", "蔚来", "小鹏", "小米汽车"],
}

# 舆情多/空关键词（子串匹配，叠加计数）
_AI_BULL_WORDS = ["涨", "升", "新高", "利好", "反弹", "回暖", "走强", "突破",
                  "创新高", "提振", "超预期", "上扬", "收涨", "飘红", "乐观",
                  "复苏", "宽松", "加码", "扩容"]
_AI_BEAR_WORDS = ["跌", "崩", "暴跌", "下挫", "走弱", "回落", "风险", "危机",
                  "警告", "抛售", "利空", "制裁", "衰退", "违约", "加息",
                  "缩表", "监管", "承压", "亏损", "爆雷", "破位", "跳水", "低迷"]
# 风险/宏观风险关键词（用于风险舆情与承压板块识别）
_AI_RISK_KEYWORDS = ["风险", "危机", "警告", "崩", "暴跌", "制裁", "衰退", "违约",
                     "加息", "缩表", "监管", "爆雷", "破位", "跳水", "利空",
                     "承压", "亏损", "诉讼", "调查", "处罚", "关税", "地缘",
                     "降级", "做空", "冻结", "停牌"]
# 风险否定词：标题同时含这些词时，往往「利空出尽/风险偏好走强」，不计入风险项
_AI_RISK_NEGATION = ["利好", "走强", "回暖", "收涨", "飘红", "超预期", "出尽",
                     "消退", "缓解", "复苏", "反弹", "宽松", "加码"]


def _ai_is_risk_title(title):
    """标题含风险关键词但同时又含利好/走强等否定词时，视为非风险项。"""
    if not any(k in title for k in _AI_RISK_KEYWORDS):
        return False
    return not any(n in title for n in _AI_RISK_NEGATION)


def _risk_ref_label(risk):
    """风险引用定位（主题无关）：正文栏目 + 条目序号，与渲染锚点一一对应。"""
    section = risk.get("section") or ""
    if risk.get("channel"):
        section = f"{section} · {risk['channel']}"
    return f"「{section}」第{risk.get('index', 0):02d}条"


def _risk_ref_detail(risk):
    """引用辅助定位：正文可见的发布时间 + 命中关键词（后者为新增信息）。"""
    bits = []
    if risk.get("section") == "全球头条" and risk.get("source"):
        bits.append(risk["source"])
    moment = risk.get("time") or ""
    if moment and moment != "—":
        bits.append(moment)
    kws = risk.get("keywords") or []
    if kws:
        bits.append("命中：" + "/".join(kws))
    return " · ".join(bits)


def _ai_label(points):
    """把信号分映射为情绪标签（中文 + 英文 kicker）。"""
    if points >= 25:
        return "偏多", "BULLISH-LEANING"
    if points > 8:
        return "温和偏多", "MILDLY BULLISH"
    if points >= -8:
        return "中性", "NEUTRAL"
    if points > -25:
        return "温和偏空", "MILDLY BEARISH"
    return "偏空", "BEARISH"


def _ai_band(pct):
    """把单指数涨跌幅映射到动能档位（中文 + 语义色）。"""
    if pct >= 2:
        return "强势", C_GREEN
    if pct >= 0.5:
        return "偏强", C_GREEN
    if pct > -0.5:
        return "震荡", C_AMBER
    if pct > -2:
        return "偏弱", C_RED
    return "弱势", C_RED


def build_ai_analysis(data):
    """规则合成跨市场综合研判（A股 + 港股 + 美股）。

    返回 dict；available=False 时调用方不渲染该区块（避免空分析）。
    纯确定性计算：不调用任何大模型 API，可复现，不伪造内容。
    """
    market = data.get("实时行情", {}) or {}
    quotes = market.get("quotes", {}) or {}
    hot = data.get("热门榜单", {}) or {}
    hot_markets = hot.get("markets", {}) or {}
    google = data.get("全球头条", {}) or {}
    em = data.get("东财快讯", {}) or {}
    sina = data.get("A股资讯", {}) or {}
    yt = data.get("港股名家频道", {}) or {}

    google_headlines = google.get("headlines", []) or []
    em_headlines = em.get("headlines", []) or []
    sina_headlines = sina.get("headlines", []) or []
    yt_channels = yt.get("channels", []) or []

    # —— 1. 文本与结构化信号汇总 ——
    texts = []
    for it in google_headlines:
        if isinstance(it, dict):
            texts.append(it.get("title", ""))
    for it in em_headlines:
        if isinstance(it, dict):
            texts.append(it.get("title", ""))
            texts.append(it.get("summary", ""))
    texts += [h for h in sina_headlines if isinstance(h, str)]
    for ch in yt_channels:
        for v in ch.get("videos", []) or []:
            texts.append(v.get("title", ""))
    all_text = " ".join(t for t in texts if t)

    # 结构化头条（含正文出处定位），用于风险项展示。
    # 每个条目：title / source / section（正文栏目名）/ index（栏目内序号，1-based，
    # 与渲染侧展示顺序一致）/ anchor（正文锚点 id）/ shown（该标题是否已在正文
    # 栏目展示）/ time（发布时间，供无序号栏目定位）/ channel（港股频道名）。
    # 全球头条 / 东财快讯 / A股资讯的存储条数 == 展示条数（8/5/5），shown 恒为 True；
    # 港股频道每频道存储最多 8 条、正文只展示前 CHANNEL_TOP_N 条，其余 shown=False。
    headlines_struct = []
    for i, it in enumerate(google_headlines, 1):
        if isinstance(it, dict):
            headlines_struct.append({
                "title": it.get("title", ""), "source": it.get("source", ""),
                "section": "全球头条", "index": i, "anchor": f"h-gh-{i:02d}",
                "shown": i <= GH_DISPLAY_N,
                "time": it.get("published_cst") or "", "channel": "",
            })
    for i, it in enumerate(em_headlines, 1):
        if isinstance(it, dict):
            headlines_struct.append({
                "title": it.get("title", ""), "source": "东方财富",
                "section": "东财快讯", "index": i, "anchor": f"h-em-{i:02d}",
                "shown": i <= EM_DISPLAY_N,
                "time": it.get("time") or "", "channel": "",
            })
    for i, h in enumerate(sina_headlines, 1):
        if isinstance(h, str):
            headlines_struct.append({
                "title": h, "source": "新浪财经",
                "section": "A股市场", "index": i, "anchor": f"h-cn-{i:02d}",
                "shown": i <= SINA_DISPLAY_N,
                "time": "", "channel": "",
            })
    for c, ch in enumerate(yt_channels, 1):
        for v, video in enumerate(ch.get("videos", []) or [], 1):
            headlines_struct.append({
                "title": video.get("title", ""), "source": ch.get("name", ""),
                "section": "港股名家频道", "index": v,
                "anchor": f"h-hk-{c:02d}-{v:02d}",
                "shown": v <= CHANNEL_TOP_N,
                "time": video.get("published_cst") or "", "channel": ch.get("name", ""),
            })

    # 热门榜单个股不再单独列入关注清单（2026-08-06 起 WATCH LIST 只保留主题行）；
    # 个股仍作为 AI 盘研判输入：板块热度识别与活跃标的提及。

    # —— 2. 情绪打分 ——
    changes = []
    for q in quotes.values():
        try:
            changes.append(float(q["change_pct"]))
        except (TypeError, ValueError, KeyError):
            pass

    present = [m for m, md in hot_markets.items() if (md or {}).get("stocks")]

    bull = sum(all_text.count(w) for w in _AI_BULL_WORDS)
    bear = sum(all_text.count(w) for w in _AI_BEAR_WORDS)
    net = bull - bear

    points = 0.0
    signals = 0
    if changes:
        avg = sum(changes) / len(changes)
        points += max(-40, min(40, avg * 6))
        signals += 1
    if present:
        points += {3: 6, 2: 3, 1: 1}.get(len(present), 0)
        signals += 1
    if all_text:
        points += max(-20, min(20, net * 2))
        signals += 1
    points = max(-100, min(100, round(points)))

    has_data = bool(changes) or bool(present) or bool(all_text)
    if not has_data or not AI_ANALYSIS_ENABLED:
        return {"available": False}

    sentiment_label, sentiment_en = _ai_label(points)
    sentiment_color = C_GREEN if points > 8 else (C_RED if points < -8 else C_AMBER)
    confidence = {3: "高", 2: "中", 1: "低"}.get(signals, "低")

    reason_parts = []
    if changes:
        reason_parts.append(f"主要指数平均{sum(changes) / len(changes):+.2f}%")
    if present:
        reason_parts.append(f"{len(present)} 个市场榜单活跃")
    if all_text:
        tone = "多" if net > 0 else ("空" if net < 0 else "平")
        reason_parts.append(f"舆情净{tone}（利好 {int(bull)} / 利空 {int(bear)}）")
    reason = "；".join(reason_parts) + "。" if reason_parts else "信号不足。"

    # —— 3. 板块热度 ——
    sector_counts = {}
    for sec, kws in AI_SECTOR_KEYWORDS.items():
        c = sum(all_text.count(k) for k in kws)
        if c:
            sector_counts[sec] = c
    sectors_strong = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:4]

    # 承压板块：出现在真正风险舆情中的板块
    risk_titles = [h["title"] for h in headlines_struct if _ai_is_risk_title(h["title"])]
    risk_joined = " ".join(risk_titles)
    sectors_weak = [sec for sec, kws in AI_SECTOR_KEYWORDS.items()
                   if any(k in risk_joined for k in kws)][:3]

    # —— 4. 技术速读（指数动能聚合；2026-09-09 起不再逐条复述行情数值）——
    # 行情明细数字的唯一展示位置是「行情速览」；此处只保留聚合（涨跌家数、
    # 平均涨跌、最强/最弱点名）与 AI 解读，避免同一数字在页内出现三次
    # （旧版：行情速览 + 指数动能明细表 + 多因子矩阵雅虎明细行）。
    # tech_rows 保留（兼容既有调用），渲染侧改用 tech_stats。
    tech_rows = []
    tech_moves = []  # (label, pct, band)，供聚合与最强/最弱点名
    for label, q in quotes.items():
        try:
            pct = float(q["change_pct"])
        except (TypeError, ValueError, KeyError):
            continue
        band, bcolor = _ai_band(pct)
        tech_rows.append((label, f"{pct:+.2f}%", band, bcolor))
        tech_moves.append((label, pct, band))
    ups = sum(1 for p in changes if p > 0)
    downs = sum(1 for p in changes if p < 0)
    flats = sum(1 for p in changes if p == 0)
    tech_avg = (sum(changes) / len(changes)) if changes else None
    tech_best = max(tech_moves, key=lambda m: m[1]) if tech_moves else None
    tech_worst = min(tech_moves, key=lambda m: m[1]) if tech_moves else None
    tech_stats = {
        "count": len(tech_moves), "ups": ups, "downs": downs, "flats": flats,
        "avg": tech_avg,
        "best": {"label": tech_best[0], "band": tech_best[2]} if tech_best else None,
        "worst": {"label": tech_worst[0], "band": tech_worst[2]} if tech_worst else None,
    }
    if ups > downs:
        tech_read = "多数指数上行，动能偏强，留意上方整数关口与前高。"
    elif downs > ups:
        tech_read = "多数指数承压，短线偏弱，关注近期支撑与量能变化。"
    else:
        tech_read = "指数分化/震荡，方向待明朗，宜控制仓位、等待确认。"

    # —— 5. 风险提示（去重引用；2026-09-09 起不再复述正文已展示的标题全文）——
    # 同一标题只保留首次命中的出处（跨栏目重复标题不再重复列出）；
    # shown=True 的条目渲染为「栏目 + 序号 + 命中关键词」引用并锚点跳转，
    # 全文只在正文栏目出现一次；shown=False（正文截断未展示，如港股频道
    # 第 4 条及以后）的条目保留全文展示，以免信息丢失。
    risks = []
    _seen_risk_titles = set()
    for h in headlines_struct:
        title = h["title"]
        if not title or not _ai_is_risk_title(title) or title in _seen_risk_titles:
            continue
        _seen_risk_titles.add(title)
        risks.append({
            **h,
            "keywords": [k for k in _AI_RISK_KEYWORDS if k in title][:3],
        })
        if len(risks) >= 5:
            break

    # —— 6. 明日关注 ——
    # 2026-08-06 起 WATCH LIST // 明日关注 不再列出榜单个股（原最多 8 只），
    # 只保留「主题关注」一行：主题来自板块热度前列，个股仅作为研判输入不单独展示。
    themes = "、".join(sec for sec, _ in sectors_strong[:3])

    return {
        "available": True,
        "score": int(points),
        "confidence": confidence,
        "sentiment_label": sentiment_label,
        "sentiment_en": sentiment_en,
        "sentiment_color": sentiment_color,
        "reason": reason,
        "sectors_strong": sectors_strong,
        "sectors_weak": sectors_weak,
        "tech_rows": tech_rows,
        "tech_stats": tech_stats,
        "tech_read": tech_read,
        "risks": risks,
        "themes": themes,
    }


def _ai_analysis_block(res):
    """渲染「AI 盘研判」：AI 主结论优先、指标卡分层、内容使用独立像素面板。"""
    color = res["sentiment_color"]
    score = int(res["score"])

    def metric_cell(label, value, value_color, first=False):
        border = "" if first else f"border-left:1px solid {C_ACCENT_SOFT};"
        return (f'<td width="33%" valign="top" style="padding:8px 6px;{border}text-align:center;">'
                f'<div style="font-size:8px;color:{C_MUTED};font-family:{FONT_MONO};font-weight:900;'
                f'letter-spacing:1px;">{label}</div>'
                f'<div style="font-size:15px;color:{value_color};font-family:{FONT_MONO};font-weight:900;'
                f'padding-top:3px;line-height:1.25;">{value}</div></td>')

    # AI 主控卡：大图标 + 情绪结论 + 三个关键指标，先于所有明细出现。
    hero = (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'border:1px solid {C_VIOLET};background:{C_AI_BG};box-shadow:7px 7px 0 #000;">'
        f'<tr><td colspan="2" style="padding:5px 9px;background:{C_VIOLET};color:{C_BG};'
        f'font-size:10px;font-weight:900;font-family:{FONT_MONO};letter-spacing:1px;">'
        f'◆ AI CORE OUTPUT // 章鱼 AI 主控台</td></tr>'
        f'<tr><td width="68" valign="middle" style="padding:12px 4px 10px 12px;">'
        f'{_pixel_icon("AI READ", 54)}</td>'
        f'<td valign="middle" style="padding:12px 12px 10px 8px;">'
        f'<div style="font-size:9px;color:{C_LEMON};font-family:{FONT_MONO};font-weight:900;'
        f'letter-spacing:2px;">MARKET BIAS // 市场倾向</div>'
        f'<div style="font-size:28px;color:{color};font-family:{FONT_MONO};font-weight:900;'
        f'line-height:1.15;padding-top:4px;text-shadow:2px 2px 0 #000;">'
        f'{_esc(res["sentiment_label"])} <span style="font-size:14px;">{("▲" if score > 8 else ("▼" if score < -8 else "■"))}</span></div>'
        f'<div style="font-size:9px;color:{C_MUTED};font-family:{FONT_MONO};font-weight:900;'
        f'letter-spacing:1px;padding-top:4px;">{_esc(res["sentiment_en"])} // RULESET v3</div>'
        f'</td></tr>'
        f'<tr><td colspan="2" style="padding:0 10px 11px;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'border:1px solid {C_ACCENT_SOFT};background:#0A0E1D;"><tr>'
        f'{metric_cell("DIRECTION / 方向", _esc(res["sentiment_label"]), color, True)}'
        f'{metric_cell("SIGNAL / 信号分", f"{score:+d}", color)}'
        f'{metric_cell("CONF / 置信度", _esc(res["confidence"]), C_LEMON)}'
        f'</tr></table>'
        f'<div style="padding-top:8px;font-size:9px;color:{C_MUTED};font-family:{FONT_MONO};">'
        f'SIGNAL POWER&nbsp; {_signal_meter(abs(score), 100, color, 10)}</div>'
        f'</td></tr></table>'
    )

    # 主结论使用高亮黄框与更大的正文，避免被后续表格淹没。
    conclusion_body = (
        f'<div style="font-size:9px;color:{C_LEMON};font-weight:900;font-family:{FONT_MONO};'
        f'letter-spacing:1px;">READ THIS FIRST // 先看结论</div>'
        f'<div style="font-size:14px;color:{C_INK};font-weight:900;line-height:1.9;'
        f'font-family:{FONT_MONO};padding-top:4px;">{_esc(res["reason"])}</div>'
    )
    conclusion_html = _pixel_panel("AI 主结论 // CORE THESIS", conclusion_body, C_LEMON, "◆")

    # 板块热度：命中数同时用像素能量条编码。
    if res["sectors_strong"]:
        max_hits = max(cnt for _, cnt in res["sectors_strong"])
        sec_rows = [
            (f'<span style="color:{C_CYAN};font-weight:900;">✚</span> {_esc(sec)}',
             f'{_signal_meter(cnt, max_hits, C_CYAN)} '
             f'<span style="color:{C_INK};font-size:10px;">{cnt} HIT</span>', C_INK)
            for sec, cnt in res["sectors_strong"]
        ]
        sectors_body = _mini_table(sec_rows)
    else:
        sectors_body = (f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;'
                        f'font-family:{FONT_MONO};">■ NO SECTOR SIGNAL</div>')
    if res["sectors_weak"]:
        sectors_body += (f'<div style="font-size:11px;color:{C_RED};margin-top:8px;padding:6px 8px;'
                         f'line-height:1.7;font-family:{FONT_MONO};font-weight:900;border:1px solid {C_RED};'
                         f'background:{C_DOWN_BG};">▼ 承压板块 // '
                         f'{" / ".join(_esc(s) for s in res["sectors_weak"])}</div>')
    sectors_html = _pixel_panel("SECTOR SCAN // 板块热度", sectors_body, C_CYAN, "✚")

    # 指数动能聚合：明细数值只在「行情速览」展示，此处仅保留聚合与解读（2026-09-09 去重）。
    tech_stats = res.get("tech_stats") or {}
    if tech_stats.get("count"):
        _band_color = {"强势": C_GREEN, "偏强": C_GREEN, "震荡": C_AMBER,
                       "偏弱": C_RED, "弱势": C_RED}
        ups_n, downs_n = tech_stats.get("ups", 0), tech_stats.get("downs", 0)
        flats_n = tech_stats.get("flats", 0)
        breadth_line = (f'<span style="color:{C_GREEN};font-weight:900;">▲ {ups_n}</span> / '
                        f'<span style="color:{C_RED};font-weight:900;">▼ {downs_n}</span> / '
                        f'<span style="color:{C_AMBER};font-weight:900;">■ {flats_n}</span>'
                        f' · 平均 {_trend_badge(tech_stats.get("avg"), compact=True)}')
        extremes = []
        for tag, info in (("最强", tech_stats.get("best") or {}),
                          ("最弱", tech_stats.get("worst") or {})):
            if info.get("label"):
                bcolor = _band_color.get(info.get("band"), C_INK)
                extremes.append(
                    f'{tag} <b style="color:{C_INK};">{_esc(info["label"])}</b> '
                    f'<span style="color:{bcolor};font-weight:900;">'
                    f'[{_esc(info.get("band", ""))}]</span>')
        tech_body = _mini_table([
            (f'指数动能聚合（{tech_stats["count"]} 个指数）', breadth_line),
            ("动能两极", " · ".join(extremes) if extremes else "—"),
        ])
    else:
        tech_body = (f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;'
                     f'font-family:{FONT_MONO};">■ NO MARKET DATA</div>')
    tech_body += (f'<div style="font-size:12px;color:{C_INK};padding:8px 8px 2px;'
                  f'line-height:1.8;font-family:{FONT_MONO};font-weight:700;">'
                  f'<span style="color:{C_VIOLET};font-weight:900;">◆ AI 解读：</span>'
                  f'{_esc(res["tech_read"])}</div>')
    tech_html = _pixel_panel("TECH READ // 指数动能", tech_body, C_VIOLET, "▲")

    # 风险与关注分别用红色、黄色面板，视觉层级与语义一致。
    # 风险条目去重（2026-09-09）：正文已展示的标题仅引用定位，不再复述全文。
    if res["risks"]:
        risk_rows = []
        for i, risk in enumerate(res["risks"]):
            bg = C_DOWN_BG if i % 2 == 0 else "transparent"
            if risk.get("shown") and risk.get("anchor"):
                main = (f'<a href="#{_esc(risk["anchor"])}" '
                        f'style="color:{C_RED};font-weight:900;text-decoration:none;'
                        f'border-bottom:1px dotted {C_RED};">→ {_esc(_risk_ref_label(risk))}</a>')
                sub = _risk_ref_detail(risk)
            else:
                # 正文截断未展示（如港股频道第 4 条及以后）：保留全文以免信息丢失
                sub_bits = [risk.get("source") or "", risk.get("time") or ""]
                if risk.get("keywords"):
                    sub_bits.append("命中：" + "/".join(risk["keywords"]))
                main = _esc((risk.get("title") or "")[:110])
                sub = " | ".join(x for x in sub_bits if x)
            risk_rows.append(_item_row("!", main, _esc(sub[:140]),
                                      icon_color=C_RED, row_bg=bg))
        risk_rows.append(
            f'<div style="font-size:10px;color:{C_MUTED};padding:6px 0 2px;'
            f'line-height:1.7;font-family:{FONT_MONO};">'
            f'已在正文栏目展示的风险条目仅引用定位 // 全文见原栏目，不重复展示</div>')
        risk_body = "".join(risk_rows)
    else:
        risk_body = (f'<div style="font-size:11px;color:{C_GREEN};padding:4px 0;'
                     f'font-family:{FONT_MONO};font-weight:900;">✓ CLEAR // 未检出显著风险舆情</div>')
    risk_html = _pixel_panel("RISK LOG // 风险提示", risk_body, C_RED, "!")

    # 明日关注：2026-08-06 起不再列出榜单个股，面板只保留主题行（THEME UNLOCKED）。
    if res["themes"]:
        watch_body = (f'<div style="font-size:12px;color:{C_BG};font-weight:900;line-height:1.7;'
                      f'font-family:{FONT_MONO};background:{C_LEMON};padding:7px 9px;'
                      f'box-shadow:3px 3px 0 #000;">★ THEME UNLOCKED // {_esc(res["themes"])}</div>')
    else:
        watch_body = (f'<div style="font-size:11px;color:{C_FAINT};padding:4px 0;'
                      f'font-family:{FONT_MONO};">■ NO WATCH THEME</div>')
    watch_html = _pixel_panel("WATCH LIST // 明日关注", watch_body, C_LEMON, "⌖")

    note_html = _note("AI 盘研判由公开数据经确定性规则合成 // RULESET v3 // 动能聚合 + 风险引用去重 // 非投资建议，决策需独立判断")
    return hero + conclusion_html + sectors_html + tech_html + risk_html + watch_html + note_html


# ============================================================
# AI 新闻情绪因子（NEWS SENTIMENT FACTORS · 确定性词表规则）
# ------------------------------------------------------------
# 2026-09-09 起按用户要求改为「逐股」：对最近成交日 A股 / 港股 / 美股
# 成交量前五（热门榜单 HOT_STOCK_TOP_N），逐只输出 AI 新闻情绪分、总结评论
# 与原因（由命中标题、词表、MOM 动量、ANV 新闻量确定性规则生成）。
# 窗口内（近 SENTI_WINDOW_HOURS=72 小时，含历史存档）标题逐条词表评分
# （HeadlineSentiment），按热门榜单个股名归因，输出 4 个因子：
#   DNS 窗口新闻情绪 ＝ (正−负)/总数（近 72h 标题窗口口径）
#   MOM 情绪动量 SentimentMomentum ＝ 近3个有评分日均值 − 近20个有评分日均值
#   ANV 异常新闻量 AbnormalNewsVolume ＝ 今日条数 vs 近30天均值±σ（z 值；
#       今日条数 > 均值+2σ 标异常放量；MOM/ANV 为自然日口径）
#   S   标题情绪 HeadlineSentiment ＝ 每条标题的词表净情绪（+1/0/−1，附命中词）
# 跨日窗口依赖 output/sentiment_history.json（随日报由 Actions 提交回库；
# main 流程：采集后加载 → 渲染 → 保存报告后落盘；--dry-run 只读不写；
# 同日多次运行按日期键覆盖，保证幂等；零报道日记 total=0、score=None）。
# 标题窗口内容依赖 output/news_history.json（每次运行合并本次抓取标题，
# 报告保存后原子落盘，随日报一并提交回库）。
# 窗口内无相关新闻的上榜股显示「暂无评分」并给出原因，绝不凭价格涨跌反推；
# 热门榜单缺席时栏目缺席。如需接大模型做标题标注，只需替换
# _score_headline_sentiment（调用方只依赖返回结构 {"s","pos","neg"}，
# 保留本规则作兜底）。
# ============================================================
SENTI_DISPLAY_N = 15       # 情绪栏目最多展示的已归因个股（页面按三大市场成交量前五逐股展示）
SENTI_MOM_SHORT_N = 3      # 动量短期窗口（有评分日，含今日）
SENTI_MOM_LONG_N = 20      # 动量长期窗口（有评分日，含今日）
SENTI_MOM_MIN_SHORT = 2    # 动量短期最少样本
SENTI_MOM_MIN_LONG = 5     # 动量长期最少样本
SENTI_VOL_WINDOW_N = 30    # 新闻量历史窗口（天，含零报道日，不含今日）
SENTI_VOL_MIN_DAYS = 5     # 新闻量最少历史样本
SENTI_HISTORY_KEEP_DAYS = 45  # 历史文件每只个股保留天数
SENTIMENT_HISTORY_FILENAME = "sentiment_history.json"

# ---- 因子标题窗口（2026-09-09 起从「当天 / 24h」放宽）----
# 政策因子：近 POLICY_WINDOW_DAYS=15 天内的政策 / 宏观新闻（自然日，含当日）；
# 新闻情绪因子：近 SENTI_WINDOW_HOURS=72 小时内的新闻（标题窗口）。
# 单次运行能抓到的标题只有 1-2 天 → 多日窗口依赖跨运行存档
# output/news_history.json（与 sentiment_history.json 同模式：每次运行合并
# 本次抓取 → 渲染使用 → 报告保存后原子落盘；GitHub Actions 一并提交回库，
# 同日重复运行按 日期+标题 去重，幂等）。情绪因子中 MOM / ANV 与跨日基线
# 仍按自然日口径（每只个股「当日」= 报告日当天新闻的桶），不受 72h 窗口影响。
SENTI_WINDOW_HOURS = 72          # 情绪标题窗口（小时，截至锚定时刻）
POLICY_WINDOW_DAYS = 15          # 政策标题窗口（自然日，含锚定日）
NEWS_HISTORY_KEEP_DAYS = POLICY_WINDOW_DAYS + 3   # 存档保留天数（含窗口余量）
NEWS_HISTORY_FILENAME = "news_history.json"

# 情绪词表：以 AI 盘研判 bull/bear 词为底，增加财报/资金/事件类词汇与
# 繁体变体（港股标题多为繁体）。命中按非重叠最长优先计数。
_SENTI_POS_WORDS = sorted(set(_AI_BULL_WORDS + [
    "大涨", "暴涨", "飙升", "飙涨", "涨停", "一字涨停", "历史新高",
    "好于预期", "盈利", "获利", "扭亏", "扭亏为盈", "增长", "大增",
    "翻倍", "翻番", "分红", "派息", "回购", "增持", "举牌", "买入评级",
    "上调评级", "获批", "获准", "中标", "签约", "合作", "收购", "注资",
    "扩产", "投产", "订单", "放量", "净流入", "流入", "纳入", "利好兑现",
    "大漲", "暴漲", "飆升", "漲停", "歷史新高", "超預期", "扭虧",
    "增長", "分紅", "回購", "上調", "買入", "獲批", "中標", "簽約",
    "收購", "淨流入",
]))
_SENTI_NEG_WORDS = sorted(set(_AI_BEAR_WORDS + [
    "大跌", "重挫", "崩盘", "熔断", "跌停", "一字跌停", "历史新低",
    "创新低", "下跌", "下滑", "下降", "减少", "骤降", "腰斩", "巨亏",
    "预亏", "预减", "首亏", "裁员", "召回", "诉讼", "调查", "问询",
    "立案", "处罚", "违约", "破产", "退市", "停牌", "做空", "降级",
    "关税", "流出", "净流出", "减持", "套现", "解禁", "计提", "商誉减值",
    "爆仓", "断供", "地雷", "出逃", "冻结", "崩盤", "熔斷", "歷史新低",
    "減少", "虧損", "巨虧", "裁員", "訴訟", "調查", "處罰", "違約",
    "破產", "降級", "關稅", "淨流出", "減持", "套現", "爆倉",
]))
_SENTI_NEGATORS = set("不没未无非否莫勿毋别")

# ---- 个股别名 / 行业概念归因（2026-09-09 增强）----
# 别名词典：{别名 → (market, code)}，用于标题中出现的简称 / 英文名 / 俗称归因。
# 仅覆盖高频出现的通用别名，不依赖大模型；新别名可在此追加。
_STOCK_ALIASES = {
    # A 股
    "宁德时代": ("A股", "300750"), "宁德": ("A股", "300750"), "CATL": ("A股", "300750"),
    "中际旭创": ("A股", "300308"), "旭创": ("A股", "300308"),
    "东山精密": ("A股", "002384"),
    "新易盛": ("A股", "300502"),
    "亨通光电": ("A股", "600487"), "亨通": ("A股", "600487"),
    "比亚迪": ("A股", "002594"), "BYD": ("A股", "002594"),
    "中国平安": ("A股", "601318"), "平安": ("A股", "601318"),
    "贵州茅台": ("A股", "600519"), "茅台": ("A股", "600519"),
    "招商银行": ("A股", "600036"), "招行": ("A股", "600036"),
    "工商银行": ("A股", "601398"), "工行": ("A股", "601398"),
    "建设银行": ("A股", "601939"), "建行": ("A股", "601939"),
    "农业银行": ("A股", "601288"), "农行": ("A股", "601288"),
    "中国银行": ("A股", "601988"),
    "中信证券": ("A股", "600030"), "中信": ("A股", "600030"),
    "隆基绿能": ("A股", "601012"), "隆基": ("A股", "601012"),
    "紫金矿业": ("A股", "601899"), "紫金": ("A股", "601899"),
    "中芯国际": ("A股", "688981"), "中芯": ("A股", "688981"),
    "海康威视": ("A股", "002415"), "海康": ("A股", "002415"),
    "立讯精密": ("A股", "002475"), "立讯": ("A股", "002475"),
    "药明康德": ("A股", "603259"), "药明": ("A股", "603259"),
    "恒瑞医药": ("A股", "600276"), "恒瑞": ("A股", "600276"),
    "三一重工": ("A股", "600031"), "三一": ("A股", "600031"),
    "科大讯飞": ("A股", "002230"), "讯飞": ("A股", "002230"),
    "龙版传媒": ("A股", "605577"), "龙版": ("A股", "605577"),
    "江波龙": ("A股", "301308"),
    # 港股
    "腾讯": ("港股", "00700"), "腾讯控股": ("港股", "00700"),
    "美团": ("港股", "03690"),
    "阿里巴巴": ("港股", "09988"), "阿里": ("港股", "09988"),
    "小米": ("港股", "01810"), "小米集团": ("港股", "01810"),
    "快手": ("港股", "01024"),
    "京东": ("港股", "09618"), "京东集团": ("港股", "09618"),
    "百度": ("港股", "09888"), "百度集团": ("港股", "09888"),
    "网易": ("港股", "09999"),
    "友邦": ("港股", "01299"), "友邦保险": ("港股", "01299"), "AIA": ("港股", "01299"),
    "海底捞": ("港股", "06862"),
    "优地机器人": ("港股", "02549"),
    "稀美资源": ("港股", "01536"),
    "长和": ("港股", "00001"), "长实": ("港股", "01113"),
    "汇丰": ("港股", "00005"), "汇丰控股": ("港股", "00005"),
    "港交所": ("港股", "00388"),
    # 美股
    "英伟达": ("美股", "NVDA"), "NVIDIA": ("美股", "NVDA"),
    "苹果": ("美股", "AAPL"), "Apple": ("美股", "AAPL"),
    "特斯拉": ("美股", "TSLA"), "Tesla": ("美股", "TSLA"),
    "微软": ("美股", "MSFT"), "Microsoft": ("美股", "MSFT"),
    "谷歌": ("美股", "GOOGL"), "Google": ("美股", "GOOGL"), "Alphabet": ("美股", "GOOGL"),
    "亚马逊": ("美股", "AMZN"), "Amazon": ("美股", "AMZN"),
    "Meta": ("美股", "META"), "脸书": ("美股", "META"), "Facebook": ("美股", "META"),
    "博通": ("美股", "AVGO"), "Broadcom": ("美股", "AVGO"), "AVGO": ("美股", "AVGO"),
    "台积电": ("美股", "TSM"), "TSMC": ("美股", "TSM"),
    "AMD": ("美股", "AMD"),
    "Intel": ("美股", "INTC"), "英特尔": ("美股", "INTC"),
    "美光": ("美股", "MU"), "Micron": ("美股", "MU"),
    "OpenAI": ("美股", "NVDA"),  # OpenAI 新闻通常与 NVDA 高度相关
    "Anthropic": ("美股", "NVDA"),  # AI 安全公司，归入 AI 算力链
}

# 行业 / 概念板块关键词 → 关联个股（market, code）列表。
# 标题提到行业 / 概念时，关联相关上榜个股（弱归因，标记 tag="sector"）。
_SECTOR_KEYWORDS = {
    "AI": [("A股", "300308"), ("A股", "300502"), ("美股", "NVDA"), ("港股", "00700"), ("港股", "09888")],
    "人工智能": [("A股", "300308"), ("A股", "300502"), ("美股", "NVDA"), ("港股", "00700")],
    "机器人": [("A股", "300308"), ("港股", "02549")],
    "人形机器人": [("A股", "300308"), ("港股", "02549")],
    "光模块": [("A股", "300308"), ("A股", "300502")],
    "半导体": [("A股", "688981"), ("美股", "NVDA"), ("美股", "AMD"), ("美股", "INTC"), ("美股", "MU")],
    "芯片": [("A股", "688981"), ("美股", "NVDA"), ("美股", "AMD"), ("美股", "INTC"), ("美股", "MU")],
    "新能源": [("A股", "300750"), ("A股", "601012"), ("A股", "002594"), ("港股", "01810")],
    "锂电": [("A股", "300750")],
    "电池": [("A股", "300750")],
    "光伏": [("A股", "601012")],
    "消费": [("A股", "600519"), ("港股", "06862"), ("港股", "03690")],
    "白酒": [("A股", "600519")],
    "银行": [("A股", "601318"), ("A股", "600036"), ("A股", "601398"), ("A股", "601939")],
    "券商": [("A股", "600030")],
    "黄金": [("A股", "601899"), ("港股", "00388")],
    "石油": [("港股", "00857")],
    "天然气": [("港股", "00857")],
    "房地产": [("港股", "00001"), ("港股", "01113")],
    "恒指": [("港股", "02800"), ("港股", "02828")],
    "恒生": [("港股", "02800"), ("港股", "02828")],
    "恒生科技": [("港股", "03033")],
    "标普": [("美股", "SPY")],
    "纳斯达克": [("美股", "QQQ")],
    "纳指": [("美股", "QQQ")],
    "期权": [("美股", "SPY"), ("美股", "QQQ")],
    "CPI": [("A股", "601318"), ("A股", "600036")],
    "PPI": [("A股", "601899")],
}


def _match_words_non_overlap(title, words):
    """词表最长优先非重叠匹配，返回 [(词, 起始下标)]（按出现顺序）。"""
    spans = []
    occupied = [False] * len(title)
    for word in sorted(words, key=len, reverse=True):
        if not word:
            continue
        start = 0
        while True:
            idx = title.find(word, start)
            if idx < 0:
                break
            if not any(occupied[idx:idx + len(word)]):
                spans.append((word, idx))
                for j in range(idx, idx + len(word)):
                    occupied[j] = True
            start = idx + 1
    spans.sort(key=lambda item: item[1])
    return spans


def _score_headline_sentiment(title):
    """标题情绪评分：正负命中数之差取符号，S∈{+1,0,−1}。

    命中词紧邻的前一字为否定词（不/没/未/无/非/否…）时翻转极性。
    返回 {"s","pos","neg","pos_n","neg_n"}（pos/neg 为展示用命中词，各≤3）。
    """
    title = title or ""
    pos_hits, neg_hits = [], []
    for word, idx in _match_words_non_overlap(title, _SENTI_POS_WORDS):
        flipped = idx > 0 and title[idx - 1] in _SENTI_NEGATORS
        (neg_hits if flipped else pos_hits).append(word)
    for word, idx in _match_words_non_overlap(title, _SENTI_NEG_WORDS):
        flipped = idx > 0 and title[idx - 1] in _SENTI_NEGATORS
        (pos_hits if flipped else neg_hits).append(word)
    pos_n, neg_n = len(pos_hits), len(neg_hits)
    net = pos_n - neg_n
    return {"s": 1 if net > 0 else (-1 if net < 0 else 0),
            "pos": pos_hits[:3], "neg": neg_hits[:3],
            "pos_n": pos_n, "neg_n": neg_n}


def _extract_stock_universe(hot):
    """从热门榜单提取个股宇宙 [{market, code, name, key}]（按 key 去重）。"""
    universe = []
    seen = set()
    markets = (hot or {}).get("markets", {}) or {}
    for market, payload in markets.items():
        for s in (payload or {}).get("stocks", []) or []:
            name = (s.get("name") or "").strip().replace(" ", "").replace("\u3000", "")
            if len(name) < 2:
                continue
            code = str(s.get("code") or "").strip()
            key = f"{market}:{code or name}"
            if key in seen:
                continue
            seen.add(key)
            universe.append({"market": market, "code": code, "name": name, "key": key})
    universe.sort(key=lambda u: len(u["name"]), reverse=True)
    return universe


def _attribute_headline(title, universe):
    """标题归因到个股（增强版 2026-09-09）：

    三层归因：
    1. 精确全名匹配（标题含 universe 中个股全名）；
    2. 别名 / 代码匹配（标题含 _STOCK_ALIASES 中的别名，或含个股代码）；
    3. 行业 / 概念板块归因（标题含 _SECTOR_KEYWORDS 中的关键词，弱归因）。

    返回 [universe_item]，每个 universe_item 额外带 tag 字段：
    - "name"  = 精确全名匹配
    - "alias" = 别名 / 代码匹配
    - "sector" = 行业概念弱归因
    一条标题可归因多只。去重（同一 key 只归因一次，优先强归因）。
    """
    if not title:
        return []
    universe_by_key = {u["key"]: u for u in universe}
    matched = {}  # key → (universe_item, tag_priority)
    # 1) 精确全名
    for u in universe:
        if u["name"] in title:
            if u["key"] not in matched:
                item = dict(u)
                item["tag"] = "name"
                matched[u["key"]] = (item, 0)
    # 2) 别名 / 代码
    for alias, (mkt, code) in _STOCK_ALIASES.items():
        if alias not in title:
            continue
        target_key = f"{mkt}:{code}"
        if target_key in universe_by_key and target_key not in matched:
            item = dict(universe_by_key[target_key])
            item["tag"] = "alias"
            matched[target_key] = (item, 1)
    # 代码直接匹配（如标题含 "300308"）
    for u in universe:
        if u["key"] in matched:
            continue
        code = u.get("code") or ""
        if code and len(code) >= 3 and code in title:
            item = dict(u)
            item["tag"] = "alias"
            matched[u["key"]] = (item, 1)
    # 3) 行业 / 概念（弱归因，只补充未被强归因的 key）
    for keyword, targets in _SECTOR_KEYWORDS.items():
        if keyword not in title:
            continue
        for mkt, code in targets:
            target_key = f"{mkt}:{code}"
            if target_key in universe_by_key and target_key not in matched:
                item = dict(universe_by_key[target_key])
                item["tag"] = "sector"
                matched[target_key] = (item, 2)
    # 按优先级排序（name > alias > sector）
    result = [item for item, _ in sorted(matched.values(), key=lambda x: x[1])]
    return result


def _factor_anchor_dt(date_str):
    """因子窗口的锚定时刻（北京时间）。

    生产运行（报告日 == 系统今天）→ 锚定当前时刻，保证「近 72 小时」严格从
    此刻起算；固定日期调用（测试 / 历史演示，报告日 ≠ 今天）→ 锚定报告日
    23:59:59，让夹具数据可复现、窗口确定性可断言。
    """
    try:
        report_day = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=CST)
    except (TypeError, ValueError):
        return datetime.now(CST)
    now = datetime.now(CST)
    if now.strftime("%Y%m%d") == date_str:
        return now
    return report_day.replace(hour=23, minute=59, second=59)


def _norm_item_ts(value):
    """把标题级时间规范成 "YYYY-MM-DD HH:MM"（北京时间字符串）；无法解析 → ""。"""
    if not isinstance(value, str):
        return ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})", value.strip())
    return f"{m.group(1)} {m.group(2)}" if m else ""


def _norm_item_date(value):
    """把标题级日期规范成 ``YYYY-MM-DD``；支持政府网的中文/斜杠日期。"""
    return _normalise_policy_date(value) if value else ""


def _collect_headline_items(data, default_date):
    """收集本次抓取的全部标题 → [{title, source, section, ts, date, ...}]。

    不再按「是否当天」过滤——是否进入窗口由 _filter_headlines_window 决定。
    ts = 标题级时间（有真实发布时间才给，如 Google News / 东财 / 港股频道），
    无发布时间的标题（如新浪滚动字符串）ts=""、date=default_date（采集日）；
    中国政府网条目还保留 url/official 字段供政策因子溯源。
    """
    items = []

    def _add(title, source, section, ts_raw, *, date_raw=None, url="", official=False):
        title = (title or "").strip()
        if not title:
            return
        ts = _norm_item_ts(ts_raw)
        # date_raw=None 表示沿用旧来源的采集日兜底；官方政策源显式传入 date，
        # 缺失发布日期时保留空值，避免把未知日期误算为当天政策。
        date = (_norm_item_date(date_raw) if date_raw is not None
                else (ts[:10] if ts else default_date))
        item = {
            "title": title[:200], "source": (source or "").strip(),
            "section": (section or "").strip(), "ts": ts, "date": date,
        }
        if url:
            item["url"] = str(url).strip()
        if official:
            item["official"] = True
        items.append(item)

    google = data.get("全球头条", {}) or {}
    for h in google.get("headlines", []) or []:
        if isinstance(h, dict):
            _add(h.get("title"), h.get("source"), "全球头条", h.get("published_cst"))
    em = data.get("东财快讯", {}) or {}
    for h in em.get("headlines", []) or []:
        if isinstance(h, dict):
            _add(h.get("title"), "东方财富", "东财快讯", h.get("time"))
    sina = data.get("A股资讯", {}) or {}
    for h in sina.get("headlines", []) or []:
        _add(h if isinstance(h, str) else (h.get("title") if isinstance(h, dict) else ""),
             "新浪财经", "A股市场", "")
    yt = data.get("港股名家频道", {}) or {}
    for ch in yt.get("channels", []) or []:
        ch_name = ch.get("name", "港股频道")
        for v in ch.get("videos", []) or []:
            _add(v.get("title"), ch_name, "港股名家频道", v.get("published_cst"))

    # 中国政府网官方政策单独进入标题存档；政策因子会在同一窗口内对其做矩阵映射。
    # 兼容手工调用传入的旧键名「中国政府网」。
    gov_policy = data.get("国家政策")
    if not isinstance(gov_policy, dict):
        gov_policy = data.get("中国政府网", {}) or {}
    for h in gov_policy.get("headlines", []) or []:
        if isinstance(h, dict):
            # 解析器会显式写入 date；兼容外部传入的只有 published_cst/time
            # 的官方记录，但仍不向缺失日期回填采集日。
            date_raw = (h["date"] if "date" in h
                        else (h.get("published_cst") or h.get("time", "")))
            _add(
                h.get("title"), h.get("source") or "中国政府网", "国家政策",
                h.get("published_cst") or h.get("time", ""),
                date_raw=date_raw, url=h.get("url", ""), official=True,
            )
    return items


def _filter_headlines_window(items, anchor_dt, days=None, hours=None):
    """按窗口过滤标题（保留原顺序）。

    - days（政策）：近 N 个自然日（含锚定日）。按标题 date 字段判断——存档中的
      无时间戳标题以其采集日归档，日归档即落在窗口内；ts 仅作 date 缺省补充；
    - hours（情绪）：近 N 小时，按标题 ts 精确判断；无时间戳的标题只有在
      采集日 == 锚定日时才计入（仅当天抓取可确认属于当天资讯，旧日无时间戳
      标题无法证明落点，宁可排除也不误纳入）。
    """
    anchor_date = anchor_dt.strftime("%Y-%m-%d")
    if days is not None:
        start_date = (anchor_dt - timedelta(days=max(1, int(days)) - 1)).strftime("%Y-%m-%d")
    out = []
    for it in items or []:
        ts = _norm_item_ts(it.get("ts"))
        if ts:
            try:
                dt = datetime.strptime(ts[:16], "%Y-%m-%d %H:%M").replace(tzinfo=CST)
            except (TypeError, ValueError):
                dt = None
        else:
            dt = None
        date = (it.get("date") or "")[:10]
        if not date and dt is not None:
            date = dt.strftime("%Y-%m-%d")
        if days is not None:
            if not (start_date <= date <= anchor_date):
                continue
        if hours is not None:
            if dt is not None:
                if not (anchor_dt - timedelta(hours=hours) <= dt <= anchor_dt):
                    continue
            else:
                if date != anchor_date:
                    continue
        out.append(it)
    return out


def _load_news_corpus(path):
    """读取新闻标题存档（缺失/损坏 → 空存档并告警，不中断日报）。"""
    fresh = {"version": 1, "items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            corpus = json.load(f)
    except FileNotFoundError:
        print("  ℹ️ 无新闻标题存档，本次仅本次抓取标题可用（窗口随运行次数累积）")
        return fresh
    except (OSError, ValueError) as exc:
        print(f"  ⚠️ 新闻标题存档读取失败（{exc}），本次按空存档处理")
        return fresh
    if not isinstance(corpus, dict) or not isinstance(corpus.get("items"), list):
        print("  ⚠️ 新闻标题存档结构异常，本次按空存档处理")
        return fresh
    corpus.setdefault("version", 1)
    return corpus


def _save_news_corpus(path, corpus):
    """原子落盘新闻标题存档。"""
    corpus["updated_cst"] = _now()
    _atomic_write(path, json.dumps(corpus, ensure_ascii=False, indent=1))
    print(f"  💾 新闻标题存档已更新: {path}（{len(corpus.get('items', []))} 条在窗口内）")


def _merge_news_corpus(corpus, fresh_items):
    """把本次抓取并入存档：按 日期+标题 去重（同日重复运行幂等）。

    官方政策条目即使和媒体标题同名，也会为已有记录补上中国政府网原文链接、
    官方来源与发布日期；这样同一条政策不会因多个资讯源重复计权，同时保留官方溯源。
    """
    items = list(corpus.setdefault("items", []))
    positions = {
        (it.get("date", ""), it.get("title", "")): index
        for index, it in enumerate(items)
        if isinstance(it, dict)
    }
    added = 0
    for it in fresh_items or []:
        if not isinstance(it, dict):
            continue
        key = (it.get("date", ""), it.get("title", ""))
        if not key[1]:
            continue
        if key in positions:
            # 同标题优先采用官方来源；普通来源缺失 URL 时也可补入已有链接，
            # 但不会让媒体信息覆盖已经确认的中国政府网官方记录。
            existing = items[positions[key]]
            is_official = bool(it.get("official"))
            if is_official and not existing.get("official"):
                existing["source"] = it.get("source", existing.get("source", ""))
                existing["section"] = it.get("section", existing.get("section", ""))
                existing["official"] = True
            if it.get("url") and (is_official or not existing.get("url")):
                existing["url"] = it["url"]
            if it.get("ts") and (is_official or not existing.get("ts")):
                existing["ts"] = it["ts"]
            continue
        positions[key] = len(items)
        entry = {"title": it["title"], "source": it.get("source", ""),
                 "section": it.get("section", ""), "ts": it.get("ts", ""),
                 "date": it.get("date", "")}
        if it.get("url"):
            entry["url"] = it["url"]
        if it.get("official"):
            entry["official"] = True
        items.append(entry)
        added += 1
    corpus["items"] = items
    if added:
        print(f"  🗂 新闻标题存档 +{added} 条（累计 {len(items)} 条）")
    return corpus


def _prune_news_corpus(corpus, anchor_date):
    """剪掉早于存档窗口的旧标题（按 date 自然日）。"""
    try:
        base = datetime.strptime(anchor_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return corpus
    cutoff = (base - timedelta(days=max(1, NEWS_HISTORY_KEEP_DAYS) - 1)).strftime("%Y-%m-%d")
    items = [it for it in corpus.get("items", []) if (it.get("date") or "") >= cutoff]
    corpus["items"] = items
    return corpus


def _load_sentiment_history(path):
    """读取情绪历史（缺失/损坏 → 空历史并告警，不中断日报）。"""
    fresh = {"version": 1, "stocks": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except FileNotFoundError:
        print("  ℹ️ 无情绪历史文件，本次冷启动（动量/新闻量标样本不足）")
        return fresh
    except (OSError, ValueError) as exc:
        print(f"  ⚠️ 情绪历史读取失败（{exc}），本次按冷启动处理")
        return fresh
    if not isinstance(history, dict) or not isinstance(history.get("stocks"), dict):
        print("  ⚠️ 情绪历史结构异常，本次按冷启动处理")
        return fresh
    history.setdefault("version", 1)
    return history


def _save_sentiment_history(path, history):
    """原子落盘情绪历史。"""
    history["updated_cst"] = _now()
    _atomic_write(path, json.dumps(history, ensure_ascii=False, indent=1))
    print(f"  💾 情绪历史已更新: {path}（{len(history.get('stocks', {}))} 只个股有基线）")


def _update_sentiment_history(history, date_str, universe, today_counts):
    """把今日计数并入历史（同日多次运行按日期键覆盖，保证幂等）。

    universe 中零报道个股记 total=0、score=None：无评分，不计情绪均值，
    计入新闻量基线。每只个股仅保留最近 SENTI_HISTORY_KEEP_DAYS 天。
    """
    stocks = history.setdefault("stocks", {})
    try:
        cutoff = (datetime.strptime(date_str, "%Y%m%d")
                  - timedelta(days=SENTI_HISTORY_KEEP_DAYS)).strftime("%Y%m%d")
    except ValueError:
        cutoff = ""
    for stock in universe:
        entry = stocks.get(stock["key"])
        if not isinstance(entry, dict):
            entry = {"market": stock["market"], "code": stock["code"],
                     "name": stock["name"], "days": {}}
            stocks[stock["key"]] = entry
        entry["market"] = stock["market"]
        entry["code"] = stock["code"]
        entry["name"] = stock["name"]
        if not isinstance(entry.get("days"), dict):
            entry["days"] = {}
        counts = today_counts.get(stock["key"]) or {}
        pos = counts.get("pos", 0) or 0
        neu = counts.get("neu", 0) or 0
        neg = counts.get("neg", 0) or 0
        total = counts.get("total", 0) or 0
        entry["days"][date_str] = {
            "pos": pos, "neu": neu, "neg": neg, "total": total,
            "score": round((pos - neg) / total, 4) if total else None,
        }
    for key in list(stocks):
        entry = stocks[key]
        if not isinstance(entry, dict) or not isinstance(entry.get("days"), dict):
            del stocks[key]
            continue
        for day in [d for d in entry["days"] if d < cutoff]:
            del entry["days"][day]
        if not entry["days"]:
            del stocks[key]
    return history


def _sentiment_momentum(day_scores):
    """情绪动量：近3个有评分日均值 − 近20个有评分日均值。

    day_scores: [(date, score)] 降序，首位为今日（调用方保证仅含已评分日）。
    样本不足（短期<2 或 长期<5）时 enough=False，渲染侧明确标注。
    """
    short = [s for _, s in day_scores[:SENTI_MOM_SHORT_N]]
    long = [s for _, s in day_scores[:SENTI_MOM_LONG_N]]
    short_n, long_n = len(short), len(long)
    if short_n < SENTI_MOM_MIN_SHORT or long_n < SENTI_MOM_MIN_LONG:
        return {"enough": False, "short_n": short_n, "long_n": long_n,
                "need": f"{SENTI_MOM_MIN_SHORT}/{SENTI_MOM_MIN_LONG}"}
    short_mean = sum(short) / short_n
    long_mean = sum(long) / long_n
    value = short_mean - long_mean
    label = "加速转暖" if value >= 0.15 else ("加速转冷" if value <= -0.15 else "平稳")
    return {"enough": True, "value": value, "short_mean": short_mean,
            "long_mean": long_mean, "short_n": short_n, "long_n": long_n,
            "label": label}


def _sentiment_volume(today_total, prior_totals):
    """异常新闻量：今日条数 vs 历史均值±σ（z 值；>均值+2σ 标异常）。

    prior_totals: 今日之前每日条数（含零报道日）。历史<5 天时
    enough=False，渲染侧明确标注。
    """
    prior_totals = [t for t in prior_totals if type(t) in (int, float)]
    n = len(prior_totals)
    if n < SENTI_VOL_MIN_DAYS:
        return {"enough": False, "n": n, "need": SENTI_VOL_MIN_DAYS,
                "today": today_total}
    mean = sum(prior_totals) / n
    var = sum((t - mean) ** 2 for t in prior_totals) / (n - 1)
    std = var ** 0.5
    if std <= 1e-9:
        z = 0.0 if today_total == mean else (9.99 if today_total > mean else -9.99)
        z_display = "σ=0"
    else:
        z = (today_total - mean) / std
        z_display = f"{z:+.1f}"
    abnormal = today_total > mean + 2 * std
    label = "异常放量" if abnormal else ("交投偏热" if z >= 1 else "正常")
    return {"enough": True, "today": today_total, "mean": mean, "std": std,
            "z": z, "z_display": z_display, "abnormal": abnormal, "n": n,
            "label": label}


def build_news_sentiment(data, date_str, history=None, display_n=SENTI_DISPLAY_N,
                         news_corpus=None):
    """构建 AI 新闻情绪因子结果（渲染与历史落盘共用同一口径）。

    - 标题窗口：近 SENTI_WINDOW_HOURS=72 小时（news_corpus 缺省时退化为只用
      本次抓取标题，仍按 72h 过滤）；
    - 个股归因 / 评分 / DNS 展示：基于窗口内全部标题；
    - MOM / ANV 与历史落盘：按自然日口径——「今日」= 窗口内标题中日期等于
      报告日的桶（today_counts 只含当日，供 sentiment_history 按日键写历史，
      与历史基线同量纲）。

    history: _load_sentiment_history 读到的跨日基线（可为 None/{}，冷启动时
    动量/新闻量标样本不足）。返回 available/stocks/universe/today_counts 等。
    """
    history = history if isinstance(history, dict) else {}
    past = history.get("stocks") or {}
    universe = _extract_stock_universe(data.get("热门榜单", {}) or {})
    anchor_dt = _factor_anchor_dt(date_str)
    anchor_date = anchor_dt.strftime("%Y-%m-%d")
    try:
        today_iso = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        today_iso = anchor_date
    if isinstance(news_corpus, dict) and isinstance(news_corpus.get("items"), list):
        raw = news_corpus["items"]
    else:
        raw = _collect_headline_items(data, anchor_date)
    headlines = _filter_headlines_window(raw, anchor_dt, hours=SENTI_WINDOW_HOURS)
    per_stock = {}
    unattributed = 0
    unattributed_headlines = []  # 未归因标题（用于"热门话题"子栏目）
    for order, head in enumerate(headlines):
        targets = _attribute_headline(head["title"], universe)
        scored = _score_headline_sentiment(head["title"])
        if not targets:
            unattributed += 1
            unattributed_headlines.append({
                "title": head["title"], "source": head["source"],
                "section": head["section"], "s": scored["s"],
                "pos_hits": scored["pos"], "neg_hits": scored["neg"],
                "date": (head.get("date") or "")[:10],
                "old": (head.get("date") or "")[:10] != today_iso and bool(head.get("date")),
                "order": order,
            })
            continue
        is_today_item = (head.get("date") or "")[:10] == today_iso
        for stock in targets:
            tag = stock.get("tag", "name")
            slot = per_stock.setdefault(stock["key"], {
                "info": stock, "pos": 0, "neu": 0, "neg": 0,
                "day_pos": 0, "day_neu": 0, "day_neg": 0, "headlines": [],
                "tags": set()})
            slot["tags"].add(tag)
            if scored["s"] > 0:
                slot["pos"] += 1
                if is_today_item:
                    slot["day_pos"] += 1
            elif scored["s"] < 0:
                slot["neg"] += 1
                if is_today_item:
                    slot["day_neg"] += 1
            else:
                slot["neu"] += 1
                if is_today_item:
                    slot["day_neu"] += 1
            slot["headlines"].append({
                "title": head["title"], "source": head["source"],
                "section": head["section"], "s": scored["s"],
                "pos_hits": scored["pos"], "neg_hits": scored["neg"],
                "date": (head.get("date") or "")[:10],
                "old": is_today_item is False and bool(head.get("date")),
                "order": order, "tag": tag,
            })
    all_stocks = []
    today_counts = {}
    for key, slot in per_stock.items():
        total = slot["pos"] + slot["neu"] + slot["neg"]
        if total < 1:
            continue
        score = (slot["pos"] - slot["neg"]) / total
        day_total = slot["day_pos"] + slot["day_neu"] + slot["day_neg"]
        if day_total >= 1:
            today_counts[key] = {"pos": slot["day_pos"], "neu": slot["day_neu"],
                                 "neg": slot["day_neg"], "total": day_total}
        days = (past.get(key) or {}).get("days", {}) or {}
        prior = sorted(((day, val) for day, val in days.items() if day < date_str),
                       reverse=True)
        scored_days = [(day, val["score"]) for day, val in prior
                       if isinstance(val, dict) and type(val.get("score")) in (int, float)]
        today_score = (round((slot["day_pos"] - slot["day_neg"]) / day_total, 4)
                       if day_total >= 1 else None)
        day_scores = ([(date_str, today_score)] if today_score is not None else []) + scored_days
        momentum = _sentiment_momentum(day_scores)
        raw_totals = [val.get("total", 0) for _, val in prior[:SENTI_VOL_WINDOW_N]
                      if isinstance(val, dict)]
        volume = _sentiment_volume(day_total, raw_totals)
        slot["headlines"].sort(key=lambda h: (-abs(h["s"]), h["order"]))
        info = slot["info"]
        tags = slot.get("tags", set())
        best_tag = "name" if "name" in tags else ("alias" if "alias" in tags else "sector")
        all_stocks.append({
            "market": info["market"], "code": info["code"], "name": info["name"],
            "key": info["key"],
            "total": total, "pos": slot["pos"], "neu": slot["neu"], "neg": slot["neg"],
            "score": score,
            "label": "偏多" if score > 0.2 else ("偏空" if score < -0.2 else "中性"),
            "momentum": momentum, "volume": volume,
            "headlines": slot["headlines"],
            "best_tag": best_tag,
        })
    all_stocks.sort(key=lambda s: (-s["total"], -abs(s["score"]), s["name"]))
    by_market = _build_senti_by_market(data, all_stocks)
    # 未归因标题情绪关键词频率（不重复展示标题本身，避免与正文重复）
    unattr_keyword_freq = {}
    for h in unattributed_headlines:
        for w in (h.get("pos_hits") or []):
            unattr_keyword_freq[w] = unattr_keyword_freq.get(w, 0) + 1
        for w in (h.get("neg_hits") or []):
            unattr_keyword_freq[w] = unattr_keyword_freq.get(w, 0) + 1
    unattr_pos_n = sum(1 for h in unattributed_headlines if h.get("s") and h["s"] > 0)
    unattr_neg_n = sum(1 for h in unattributed_headlines if h.get("s") and h["s"] < 0)
    unattr_neu_n = sum(1 for h in unattributed_headlines if h.get("s") == 0)
    # 跨市场情绪总览
    market_summary = _build_market_sentiment_summary(all_stocks, by_market)
    return {
        "available": bool(universe),
        "date": date_str,
        "stocks": all_stocks[:display_n],
        "by_market": by_market,
        "total_matched": len(all_stocks),
        "universe_n": len(universe),
        "scored_headlines": len(headlines) - unattributed,
        "unattributed_n": unattributed,
        "unattributed_pos_n": unattr_pos_n,
        "unattributed_neg_n": unattr_neg_n,
        "unattributed_neu_n": unattr_neu_n,
        "unattributed_keywords": sorted(unattr_keyword_freq.items(),
                                        key=lambda x: -x[1])[:10],
        "window_hours": SENTI_WINDOW_HOURS,
        "window_text": f"{anchor_dt:%m-%d %H:%M}",
        "corpus_n": len(headlines),
        "universe": universe,
        "today_counts": today_counts,
        "market_summary": market_summary,
    }


def _build_market_sentiment_summary(all_stocks, by_market):
    """构建跨市场情绪总览（渲染用）：整体 DNS、各市场情绪、最热/最冷个股。"""
    if not all_stocks:
        return {"available": False}
    total_pos = sum(s["pos"] for s in all_stocks)
    total_neg = sum(s["neg"] for s in all_stocks)
    total_neu = sum(s["neu"] for s in all_stocks)
    total_n = total_pos + total_neg + total_neu
    overall_dns = (total_pos - total_neg) / total_n if total_n else 0
    overall_label = "偏多" if overall_dns > 0.2 else ("偏空" if overall_dns < -0.2 else "中性")
    # 各市场情绪
    market_dns = {}
    for mb in by_market:
        mkt = mb["market"]
        mkt_stocks = [s for s in mb.get("stocks") or [] if s.get("matched")]
        if not mkt_stocks:
            market_dns[mkt] = {"matched": 0, "dns": None, "label": "暂无"}
            continue
        mkt_pos = sum(s["pos"] for s in mkt_stocks)
        mkt_neg = sum(s["neg"] for s in mkt_stocks)
        mkt_neu = sum(s["neu"] for s in mkt_stocks)
        mkt_n = mkt_pos + mkt_neg + mkt_neu
        mkt_dns = (mkt_pos - mkt_neg) / mkt_n if mkt_n else 0
        mkt_label = "偏多" if mkt_dns > 0.2 else ("偏空" if mkt_dns < -0.2 else "中性")
        market_dns[mkt] = {"matched": len(mkt_stocks), "total": mkt_n,
                           "dns": round(mkt_dns, 2), "label": mkt_label,
                           "pos": mkt_pos, "neg": mkt_neg, "neu": mkt_neu}
    # 最热 / 最冷个股（仅已匹配的）
    matched = [s for s in all_stocks if s["total"] >= 1]
    hottest = max(matched, key=lambda s: s["score"]) if matched else None
    coldest = min(matched, key=lambda s: s["score"]) if matched else None
    most_covered = max(matched, key=lambda s: s["total"]) if matched else None
    return {
        "available": True,
        "overall_dns": round(overall_dns, 2),
        "overall_label": overall_label,
        "total_n": total_n,
        "total_pos": total_pos,
        "total_neg": total_neg,
        "total_neu": total_neu,
        "market_dns": market_dns,
        "hottest": hottest,
        "coldest": coldest,
        "most_covered": most_covered,
    }


SENTI_MARKET_ORDER = ("A股", "港股", "美股")


def _build_senti_stock_comment(s):
    """按确定性规则生成单只"AI 新闻情绪评分 + 总结评论 + 原因"（2026-09-09 丰富版）。

    只使用窗口内真实命中的标题数与词表命中词；无新闻就不评分不评级，
    绝不凭消息面或价格涨跌反推新闻情绪。
    """
    if not s.get("matched"):
        return ("近72小时无相关点名新闻，AI 暂不评分。",
                "窗口内标题未通过精确名/别名代码/行业概念归因到该股，无新闻证据时不评论其新闻情绪。")
    score = round(float(s.get("score") or 0.0), 2)
    total = int(s.get("total") or 0)
    pos = int(s.get("pos") or 0)
    neu = int(s.get("neu") or 0)
    neg = int(s.get("neg") or 0)
    label = s.get("label") or "中性"
    # 归因类型统计
    tag_counts = {}
    for h in s.get("headlines", []) or []:
        t = h.get("tag", "name")
        tag_counts[t] = tag_counts.get(t, 0) + 1
    tag_labels = {"name": "精确名", "alias": "别名/代码", "sector": "行业概念"}
    tag_order = ("name", "alias", "sector")
    tag_parts = [f'{tag_labels.get(t, t)}{n}条' for t, n in
                 sorted(tag_counts.items(), key=lambda x: tag_order.index(x[0])
                        if x[0] in tag_order else 99)]
    tag_note = f"（归因：{' / '.join(tag_parts)}）" if tag_parts else ""
    comment = (f"AI情绪分 {score:+.2f}（{label}）：近72小时命中 {total} 条相关新闻{tag_note}，"
               f"正面 {pos} 条 / 中性 {neu} 条 / 负面 {neg} 条。")
    parts = []
    hits = []
    for h in s.get("headlines", []) or []:
        hits.extend(h.get("pos_hits") or [])
        hits.extend(h.get("neg_hits") or [])
    hits = list(dict.fromkeys(hits))[:5]
    if hits:
        parts.append("命中情绪词：" + "、".join(hits))
    pos_heads = [h["title"] for h in s.get("headlines") if h.get("s") and h["s"] > 0]
    neg_heads = [h["title"] for h in s.get("headlines") if h.get("s") and h["s"] < 0]
    neu_heads = [h["title"] for h in s.get("headlines") if h.get("s") == 0]
    if pos_heads:
        parts.append("正面主要来自「" + pos_heads[0][:40] + "」" +
                     (f"等 {len(pos_heads)} 条" if len(pos_heads) > 1 else ""))
    if neg_heads:
        parts.append("负面主要来自「" + neg_heads[0][:40] + "」" +
                     (f"等 {len(neg_heads)} 条" if len(neg_heads) > 1 else ""))
    if neu_heads and not pos_heads and not neg_heads:
        parts.append("中性报道为主：「" + neu_heads[0][:40] + "」" +
                     (f"等 {len(neu_heads)} 条" if len(neu_heads) > 1 else ""))
    # 来源分布
    source_counts = {}
    for h in s.get("headlines", []) or []:
        sec = h.get("section", "")
        source_counts[sec] = source_counts.get(sec, 0) + 1
    if source_counts:
        src_parts = [f'{sec}{n}条' for sec, n in
                     sorted(source_counts.items(), key=lambda x: -x[1])]
        parts.append("来源：" + "、".join(src_parts))
    mom = s.get("momentum") or {}
    if mom.get("enough"):
        parts.append(f"情绪动量 {float(mom['value']):+.2f}（{mom['label']}）")
    else:
        parts.append("情绪动量样本不足")
    vol = s.get("volume") or {}
    if vol.get("enough"):
        parts.append(f"今日新闻量 {vol['today']} 条（{vol['label']}，z={vol['z_display']}）")
    else:
        parts.append("新闻量历史样本不足")
    reason = "；".join(parts) + "。" if parts else "基于窗口内命中标题的词表净情绪合成。"
    return comment, reason


def _build_senti_by_market(data, all_stocks):
    """把评过分 / 未评分的个股按「A股·港股·美股 成交前五」分组，补上总结评论与原因。

    榜单顺序优先；榜单缺失某市场时该市场不出现；所有上榜个股都会展示，
    包括窗口内没有相关新闻的股票（matched=False，明确说明无法评分的原因）。
    """
    hot = (data or {}).get("热门榜单", {}) or {}
    by_key = {(s.get("market"), s.get("code") or s.get("name")): s for s in all_stocks}
    result = []
    for market in SENTI_MARKET_ORDER:
        payload = (hot.get("markets") or {}).get(market) or {}
        rows = (payload.get("stocks") or [])[:HOT_STOCK_TOP_N]
        if not rows:
            continue
        market_stocks = []
        for it in rows:
            code = str(it.get("code") or "")
            name = (it.get("name") or "").strip()
            if not name:
                continue
            matched = by_key.get((market, code or name))
            if matched:
                item = dict(matched)
                item["matched"] = True
            else:
                item = {
                    "market": market, "code": code, "name": name,
                    "key": f"{market}:{code or name}",
                    "matched": False, "total": 0, "pos": 0, "neu": 0, "neg": 0,
                    "score": None, "label": "暂无评分",
                    "momentum": {"enough": False}, "volume": {"enough": False},
                    "headlines": [],
                }
            item["comment"], item["reason"] = _build_senti_stock_comment(item)
            market_stocks.append(item)
        result.append({"market": market, "stocks": market_stocks})
    return result


def _senti_factor_lines(s):
    """个股 3 因子的展示文案（双主题共用；返回 [(标签, 文案)]）。

    DNS 为近 SENTI_WINDOW_HOURS=72h 标题窗口口径；MOM/ANV 为自然日口径。
    """
    mom = s["momentum"]
    if mom["enough"]:
        mom_line = (f'MOM {mom["value"]:+.2f}（近{mom["short_n"]}日均'
                    f'{mom["short_mean"]:+.2f} vs 近{mom["long_n"]}日均'
                    f'{mom["long_mean"]:+.2f} · {mom["label"]}）')
    else:
        mom_line = (f'MOM 样本不足（n={mom["short_n"]}/{mom["long_n"]}，'
                    f'需≥{mom["need"]}，含今日）')
    vol = s["volume"]
    if vol["enough"]:
        flag = " · ⚠异常放量" if vol["abnormal"] else ""
        vol_line = (f'ANV 今日{vol["today"]}条（近{vol["n"]}天均{vol["mean"]:.1f}条 '
                    f'σ{vol["std"]:.1f} z={vol["z_display"]} · {vol["label"]}{flag}）')
    else:
        vol_line = f'ANV 样本不足（历史n={vol["n"]}，需≥{vol["need"]}天）'
    return [
        (f"{SENTI_WINDOW_HOURS}h 情绪",
         f'DNS {s["score"]:+.2f}（正{s["pos"]}/中{s["neu"]}/负{s["neg"]} · {s["label"]}）'),
        ("情绪动量", mom_line),
        ("新闻量", vol_line),
    ]


def _senti_headline_sub(h):
    """标题行副文案：栏目 · 来源 · 命中词（双主题共用）；72h 窗口内旧日标题前缀日期。"""
    hits = (h["pos_hits"] or []) + (h["neg_hits"] or [])
    hit_txt = f'命中：{"/".join(hits[:3])}' if hits else "无情绪词"
    base = f'{h["section"]} · {h["source"]} · {hit_txt}'
    date = (h.get("date") or "")[:10]
    if h.get("old") and date:
        return f'{date[5:]} · {base}'
    return base


def _pixel_sentiment_block(res):
    """像素主题：AI 新闻情绪因子——按「A股/港股/美股 成交量前五」逐股评分 + 总结评论 + 原因（2026-09-09 丰富版）。"""
    by_market = res.get("by_market") or []
    total_stocks = sum(len(mb.get("stocks") or []) for mb in by_market)
    ms = res.get("market_summary") or {}
    overview_rows = [
        ("标的范围", f'A股/港股/美股 成交量前 {HOT_STOCK_TOP_N} · 共 {total_stocks} 只'),
        ("窗口内有点名", f'{res["total_matched"]} 只（精确名/别名代码/行业概念归因）'),
        ("标题窗口", f'近 {res.get("window_hours") or SENTI_WINDOW_HOURS} 小时（截至 {res.get("window_text") or "—"}）'),
        ("归因未命中", f'{res["unattributed_n"]} 条（已入下方「市场情绪关键词」）'),
    ]
    head = _mini_table(overview_rows)
    # 市场情绪全景
    summary_cards = []
    if ms.get("available"):
        arrow = "▲" if ms["overall_dns"] > 0.2 else ("▼" if ms["overall_dns"] < -0.2 else "■")
        if ms["overall_dns"] > 0.2:
            color = C_GREEN
        elif ms["overall_dns"] < -0.2:
            color = C_RED
        else:
            color = C_AMBER
        summary_rows = [
            ("整体 DNS", f'<span style="color:{color};font-weight:900;">{ms["overall_dns"]:+.2f}</span>'
                         f'（{ms["overall_label"]} · 正{ms["total_pos"]}/中{ms["total_neu"]}/负{ms["total_neg"]}）'),
        ]
        for mkt in SENTI_MARKET_ORDER:
            md = ms.get("market_dns", {}).get(mkt)
            if not md:
                continue
            if md.get("dns") is None:
                summary_rows.append((f"{mkt}", f'■ 窗口内无匹配'))
            else:
                mkt_color = C_GREEN if md["dns"] > 0.2 else (C_RED if md["dns"] < -0.2 else C_AMBER)
                summary_rows.append((
                    f"{mkt}",
                    f'<span style="color:{mkt_color};font-weight:900;">DNS {md["dns"]:+.2f}</span>'
                    f'（{md["label"]} · {md["matched"]}只）'))
        callouts = []
        if ms.get("hottest"):
            h = ms["hottest"]
            callouts.append(f'最暖：{h["name"]}（{h["score"]:+.2f}）')
        if ms.get("coldest") and ms["coldest"]["key"] != (ms.get("hottest") or {}).get("key"):
            c = ms["coldest"]
            callouts.append(f'最冷：{c["name"]}（{c["score"]:+.2f}）')
        if ms.get("most_covered"):
            m = ms["most_covered"]
            callouts.append(f'最多：{m["name"]}（{m["total"]}条）')
        if callouts:
            summary_rows.append(("关键信号", " · ".join(callouts)))
        summary_cards.append(_pixel_panel(
            f"MARKET OVERVIEW // {arrow} {ms['overall_label']}",
            _mini_table(summary_rows), color, arrow))
    # 逐市场逐股
    cards = []
    for mb in by_market:
        cards.append(_subsection(f'{_esc(mb["market"])} · 成交量前{HOT_STOCK_TOP_N}'))
        for s in mb.get("stocks") or []:
            if not s.get("matched"):
                body = _mini_table([
                    ("AI 情绪分", "暂无评分"),
                    ("总结评论", _esc(s.get("comment") or "窗口内无相关新闻，AI 暂不评分。")),
                    ("原因", _esc(s.get("reason") or "窗口内标题未点名该股，无新闻证据时不评论。")),
                ])
                cards.append(_pixel_panel(
                    f"STOCK SENTI // {_esc(s['name'])} {_esc(s['code'])} · {s['market']} · ■ 暂无评分",
                    body, C_AMBER, "■"))
                continue
            if s["score"] > 0.2:
                color, icon = C_GREEN, "▲"
            elif s["score"] < -0.2:
                color, icon = C_RED, "▼"
            else:
                color, icon = C_AMBER, "■"
            rows = [
                ("AI 情绪分", f'<span style="color:{color};font-weight:900;">{s["score"]:+.2f}</span>'
                              f'（正{s["pos"]}/中{s["neu"]}/负{s["neg"]} · {_esc(s["label"])}）'),
                ("总结评论", _esc(s.get("comment") or "")),
                ("原因", _esc(s.get("reason") or "")),
            ]
            body = _mini_table(rows) + _mini_table(_senti_factor_lines(s))
            evidence = []
            for h in s["headlines"][:5]:
                badge, bcolor = {1: ("S+1", C_GREEN), -1: ("S−1", C_RED),
                                 0: ("S0", C_AMBER)}[h["s"]]
                tag_mark = ""
                if h.get("tag") == "alias":
                    tag_mark = ' <span style="font-size:10px;color:#888;">[别名]</span>'
                elif h.get("tag") == "sector":
                    tag_mark = ' <span style="font-size:10px;color:#888;">[行业]</span>'
                evidence.append(_item_row(
                    "»", f'<b style="color:{bcolor};">[{badge}]</b> {_esc(h["title"][:70])}{tag_mark}',
                    _esc(_senti_headline_sub(h))))
            more = len(s["headlines"]) - 5
            if more > 0:
                evidence.append(
                    f'<div style="font-size:10px;color:{C_MUTED};padding:4px 0;'
                    f'line-height:1.7;font-family:{FONT_MONO};">'
                    f'＋其余 {more} 条已计入因子（按情绪强度仅展示前 5 条）</div>')
            body += "".join(evidence)
            cards.append(_pixel_panel(
                f"STOCK SENTI // {_esc(s['name'])} {_esc(s['code'])} · {s['market']} · {_esc(s['label'])}",
                body, color, icon))
    # 未归因市场级情绪关键词
    unattr_n = res.get("unattributed_n") or 0
    unattr_keywords = res.get("unattributed_keywords") or []
    topic_cards = []
    if unattr_n > 0:
        topic_rows = [
            ("未归因", f'{unattr_n} 条（正{res.get("unattributed_pos_n") or 0}/中{res.get("unattributed_neu_n") or 0}/负{res.get("unattributed_neg_n") or 0}）'),
        ]
        if unattr_keywords:
            kw_parts = [f'{kw}×{n}' for kw, n in unattr_keywords[:8]]
            topic_rows.append(("高频情绪词", "、".join(kw_parts)))
        else:
            topic_rows.append(("高频情绪词", "无显著情绪词命中"))
        topic_cards.append(_pixel_panel(
            f"MARKET MOOD // 未归因{unattr_n}条市场级情绪",
            _mini_table(topic_rows), C_AMBER, "■"))
    note = _note(f"AI 新闻情绪分按近{SENTI_WINDOW_HOURS}h 窗口标题词表评分逐股合成；"
                 "归因三层：精确名 → 别名/代码 → 行业/概念关键词（后两者标[别名]/[行业]）；"
                 "总结评论与原因由命中标题/词表、动量与新闻量确定性规则生成；无新闻的榜单个股明确标注「暂无评分」，"
                 "不凭价格涨跌反推新闻情绪；MOM/ANV 按自然日口径 // RULESET v3 // 非投资建议")
    return head + "".join(summary_cards) + "".join(cards) + "".join(topic_cards) + note

def _senti_empty_counts(res):
    """情绪因子占位用的统一计数（双主题共用）。返回 (n_window, universe_n)。"""
    n_today = (res.get("scored_headlines") or 0) + (res.get("unattributed_n") or 0)
    universe_n = res.get("universe_n") or 0
    return n_today, universe_n


def _pixel_sentiment_empty_block(res):
    """像素主题：AI 新闻情绪因子「样本不足」占位（72h 窗口有标题但无归因时代替整栏消失）。"""
    n_today, universe_n = _senti_empty_counts(res)
    if universe_n:
        cover = f"0 / {universe_n} 只榜单个股被窗口内标题点名"
    else:
        cover = "热门榜单暂缺 → 无个股宇宙可归因"
    head = _mini_table([
        ("窗口标题", f"{n_today} 条（近 {SENTI_WINDOW_HOURS}h，全部尝试归因）"),
        ("个股宇宙", f"{universe_n} 只（来自热门榜单）" if universe_n else "0 只（热门榜单暂缺）"),
        ("归因结果", cover),
    ])
    body = (head
            + _note(f"DNS/MOM/ANV 需要「标题→榜单个股」的归因样本：近 {SENTI_WINDOW_HOURS}h 标题未点名榜单个股 → "
                    "无样本可出分，明确标注而非伪造。有榜单个股被点名报道时本栏目自动恢复。"))
    return (_alert(f"SAMPLE INSUFFICIENT // 样本不足：{n_today} 条标题（近{SENTI_WINDOW_HOURS}h）均未点名榜单个股", C_AMBER)
            + _pixel_panel("STOCK SENTI // 样本不足", body, C_AMBER, "■")
            + _note(f"因子口径：DNS=(正−负)/总数（近{SENTI_WINDOW_HOURS}h 窗口标题）；MOM=近3有评分日均−近20有评分日均；"
                    "ANV:今日条数>30天均值+2σ标异常（MOM/ANV 按自然日） // RULESET v3 // 非投资建议"))


def gz_sentiment_block(res):
    """谷藏主题：AI 新闻情绪因子——按「A股/港股/美股 成交量前五」逐股评分 + 总结评论 + 原因（2026-09-09 丰富版）。"""
    by_market = res.get("by_market") or []
    total_stocks = sum(len(mb.get("stocks") or []) for mb in by_market)
    ms = res.get("market_summary") or {}
    out = []
    # ① 总览：一行覆盖面
    out.append(gz_kv_table([
        ("覆盖", f'三市成交量前 {HOT_STOCK_TOP_N} 共 {total_stocks} 只 · 有新闻 {res["total_matched"]} 只'
                 f' · 近 {res.get("window_hours") or SENTI_WINDOW_HOURS}h'),
    ]))
    # ② 市场情绪全景
    if ms.get("available"):
        arrow = "▲" if ms["overall_dns"] > 0.2 else ("▼" if ms["overall_dns"] < -0.2 else "■")
        out.append(gz_subsection(f'市场情绪全景 {arrow} {ms["overall_label"]}'))
        ms_pairs = [(
            "整体 DNS",
            f'{ms["overall_dns"]:+.2f}（{ms["overall_label"]} · '
            f'正{ms["total_pos"]}/中{ms["total_neu"]}/负{ms["total_neg"]} · '
            f'共{ms["total_n"]}条归因标题）')]
        for mkt in SENTI_MARKET_ORDER:
            md = ms.get("market_dns", {}).get(mkt)
            if not md:
                continue
            if md.get("dns") is None:
                continue          # 无匹配市场不占行
            else:
                mkt_arrow = "▲" if md["dns"] > 0.2 else ("▼" if md["dns"] < -0.2 else "■")
                ms_pairs.append((
                    f"{mkt} {mkt_arrow}",
                    f'DNS {md["dns"]:+.2f}（{md["label"]} · '
                    f'{md["matched"]}只 · 正{md["pos"]}/中{md["neu"]}/负{md["neg"]}）'))
        callouts = []
        if ms.get("hottest"):
            h = ms["hottest"]
            callouts.append(f'情绪最暖：{h["name"]}（DNS {h["score"]:+.2f} · {h["label"]}）')
        if ms.get("coldest") and ms["coldest"]["key"] != (ms.get("hottest") or {}).get("key"):
            c = ms["coldest"]
            callouts.append(f'情绪最冷：{c["name"]}（DNS {c["score"]:+.2f} · {c["label"]}）')
        if ms.get("most_covered"):
            m = ms["most_covered"]
            callouts.append(f'报道最多：{m["name"]}（{m["total"]}条）')
        if callouts:
            ms_pairs.append(("关键信号", _esc(" · ".join(callouts))))
        out.append(gz_kv_table(ms_pairs))
    # ③ 逐市场逐股
    for mb in by_market:
        scored = [st for st in (mb.get("stocks") or []) if st.get("matched")]
        if not scored:
            continue              # 该市场无个股被点名 → 不出「暂无评分」占位
        out.append(gz_subsection(f'{_esc(mb["market"])} · 成交量前{HOT_STOCK_TOP_N}'))
        for s in scored:
            arrow = "▲" if s["score"] > 0.2 else ("▼" if s["score"] < -0.2 else "■")
            title = f'{s["name"]} {s["code"]}' if s["code"] else s["name"]
            tag_label = {"name": "精确名", "alias": "别名/代码", "sector": "行业概念"}.get(
                s.get("best_tag", "name"), "")
            out.append(gz_subsection(
                f'{_esc(title)} · {s["market"]} {arrow}'
                f' <span style="font-size:{GZ_FS_META}px;color:{GZ_META};font-weight:{GZ_W_BODY};">归因：{tag_label}</span>'))
            stock_pairs = [
                ("AI 情绪分", _esc(s.get("comment") or "")),
                ("原因", _esc(s.get("reason") or "")),
            ]
            for label, line in _senti_factor_lines(s):
                if "样本不足" in line:
                    continue      # 冷启动的动量 / 新闻量不出行
                stock_pairs.append((label, _esc(line)))
            out.append(gz_kv_table(stock_pairs))
            for h in s["headlines"][:3]:
                badge = {1: "▲ S+1", -1: "▼ S−1", 0: "■ S0"}[h["s"]]
                tag_mark = ""
                if h.get("tag") == "alias":
                    tag_mark = f' <span style="font-size:{GZ_FS_META}px;color:{GZ_META};">[别名]</span>'
                elif h.get("tag") == "sector":
                    tag_mark = f' <span style="font-size:{GZ_FS_META}px;color:{GZ_META};">[行业]</span>'
                out.append(gz_item_row(
                    "»",
                    f'<b style="color:{GZ_INK};">{badge}</b> {_esc(h["title"][:70])}{tag_mark}',
                    _senti_headline_sub(h)))
    # ④ 未归因市场级情绪关键词（避免重复展示已在正文出现的标题）
    unattr_n = res.get("unattributed_n") or 0
    unattr_keywords = res.get("unattributed_keywords") or []
    if unattr_n > 0:
        mood_pairs = [("未归因标题",
                       f'{unattr_n} 条 · 正{res.get("unattributed_pos_n") or 0} / '
                       f'中{res.get("unattributed_neu_n") or 0} / 负{res.get("unattributed_neg_n") or 0}')]
        if unattr_keywords:
            kw_parts = [f'{kw}×{n}' for kw, n in unattr_keywords[:8]]
            mood_pairs.append(("高频情绪词", _esc("、".join(kw_parts))))
        out.append(gz_subsection("市场情绪关键词") + gz_kv_table(mood_pairs))
    return "".join(out)


def gz_sentiment_empty_block(res):
    """谷藏主题：AI 新闻情绪因子「样本不足」占位（72h 窗口有标题但无归因时代替整栏消失）。"""
    n_today, universe_n = _senti_empty_counts(res)
    if universe_n:
        cover = f"0 / {universe_n} 只榜单个股被窗口内标题点名"
    else:
        cover = "热门榜单暂缺 → 无个股宇宙可归因"
    out = [
        gz_shell(
            f'<div style="font-size:{GZ_FS_BODY}px;font-weight:700;color:{GZ_INK};line-height:1.6;">'
            f'■ 样本不足：{n_today} 条标题（近{SENTI_WINDOW_HOURS}h）均未点名榜单个股</div>',
            pad="8px 0"),
        gz_kv_table([
            ("窗口标题", f"{n_today} 条（近 {SENTI_WINDOW_HOURS}h，全部尝试归因）"),
            ("个股宇宙", f"{universe_n} 只（来自热门榜单）" if universe_n
             else "0 只（热门榜单暂缺）"),
            ("归因结果", cover),
        ]),
    ]
    out.append(gz_note(
        f"DNS/MOM/ANV 需要「标题→榜单个股」的归因样本：近 {SENTI_WINDOW_HOURS}h 标题未点名榜单个股 → "
        "无样本可出分，明确标注而非伪造；有榜单个股被点名报道时本栏目自动恢复。因子口径："
        f"DNS=(正−负)/总数（近{SENTI_WINDOW_HOURS}h 窗口标题）；MOM=近3有评分日均−近20有评分日均；"
        "ANV:今日条数>30天均值+2σ标异常（MOM/ANV 按自然日）。非投资建议。"))
    return "".join(out)


# ============================================================
# 政策因子（POLICY SHOCK · 确定性关键词矩阵）
# ------------------------------------------------------------
# 抓取后、推送前单独构建（main 1.6 阶段），推送页首位栏目渲染。
# 逻辑：识别政策类新闻（监管/扶持/货币/财政/地产/贸易/宏观数据等维度），经
# 关键词矩阵映射到行业受益/受损权重，汇总为 PolicyShockIndex：
#   行业 PSI ＝ 该行业在今日政策新闻中的权重之和（正=受益，负=承压）
#   大盘 PSI ＝ 宽基权重之和（>0 偏暖 / <0 偏冷 / =0 中性）
# 维度分两类：固定映射（货币/财政/地产/宏观数据，直接给行业权重）与
# 行业归因（扶持/监管/开放/贸易，按标题提及的行业落权重；无提及
# 落宽基小权重并标注宽基）。触发词被否定词修饰时跳过（如"暂不降准"）。
# 中国政府网条目额外带 official=True：即使标题没有方向性触发词，也按「政策发布」
# 中性维度纳入政策因子并保留官方原文链接，避免官方发布的条例/规划因标题措辞不同而漏检。
# 只统计近 POLICY_WINDOW_DAYS=15 日窗口内标题（复用标题收集器，含历史存档，
# 无 ts 的标题按 date 判断，当天标题自然在窗口内）；窗口内零政策/宏观新闻时
# 栏目缺席，不伪造。
# ============================================================
POLICY_DISPLAY_INDUSTRIES = 5   # 受益/承压榜单各展示的行业数
POLICY_DISPLAY_HEADLINES = 8    # 政策新闻逐条展示上限

# 政策维度矩阵：triggers 命中即该维度命中（同一维度每条只计一次，
# 权重只落一次）；weights 为固定行业映射，needs_industry 为行业归因。
_POLICY_DIMENSIONS = [
    {"id": "easing", "label": "货币宽松",
     "triggers": ["降准", "降息", "双降", "LPR", "MLF", "逆回购", "宽松",
                  "放水", "加大投放", "呵护流动性", "保持流动性",
                  "降準", "寬鬆"],
     "weights": {"银行": -1, "证券": +2, "地产链": +2, "消费": +1,
                 "科技成长": +1, "大盘": +1}},
    {"id": "tightening", "label": "货币收紧",
     "triggers": ["加息", "缩表", "收紧流动性", "回笼资金", "縮表", "收緊"],
     "weights": {"银行": +1, "证券": -2, "地产链": -2, "消费": -1,
                 "科技成长": -1, "大盘": -1}},
    {"id": "support", "label": "产业扶持",
     "triggers": ["产业政策", "新质生产力", "专项资金", "重大项目",
                  "大力发展", "政策支持", "培育壮大", "扶持", "补贴",
                  "国补", "補貼"],
     "needs_industry": True, "weight": +2, "broad_weight": +1},
    {"id": "regulation", "label": "监管收紧",
     "triggers": ["立案调查", "窗口指导", "反垄断", "约谈", "罚单",
                  "监管", "规范", "整顿", "严查", "重罚",
                  "監管", "約談", "罰單", "反壟斷", "整頓", "嚴查"],
     "needs_industry": True, "weight": -2, "broad_weight": -1},
    {"id": "fiscal", "label": "财政发力",
     "triggers": ["特别国债", "增发国债", "专项债", "化债", "减税",
                  "降费", "赤字", "财政", "財政", "專項債", "減稅"],
     "weights": {"基建链": +2, "消费": +1, "大盘": +1}},
    {"id": "property_ease", "label": "地产松绑",
     "triggers": ["认房不认贷", "下调首付", "降低首付", "城中村改造",
                  "白名单", "松绑", "收储", "鬆綁"],
     "weights": {"地产链": +2, "银行": +1, "大盘": +1}},
    {"id": "property_tight", "label": "地产收紧",
     "triggers": ["限购", "限贷", "限售", "限購", "限貸"],
     "weights": {"地产链": -2, "银行": -1, "大盘": -1}},
    {"id": "opening", "label": "开放准入",
     "triggers": ["负面清单", "对外开放", "扩大开放", "准入", "自贸",
                  "放开", "试点", "負面清單", "對外開放", "準入",
                  "自貿", "試點"],
     "needs_industry": True, "weight": +1, "broad_weight": +1},
    {"id": "trade_barrier", "label": "贸易壁垒",
     "triggers": ["实体清单", "出口管制", "加征", "关税", "制裁",
                  "断供", "關稅", "斷供", "實體清單"],
     "needs_industry": True, "weight": -2, "broad_weight": -1},
    # 宏观数据（2026-09-09 增补）：CPI / PPI / 社融 / 统计局等经济数据口径。
    # 规则启发式：按“数据温和向好”统一计中性偏暖（CPI 回升利多消费与再通胀链、
    # PPI 涨幅扩大利多上游资源），方向细分留给后续增强；触发词同样受否定修饰保护。
    {"id": "macro", "label": "宏观数据",
     "triggers": ["CPI", "PPI", "PMI", "社融", "M2", "GDP", "新增信贷",
                  "新增人民币贷款", "社会消费品零售总额", "工业增加值",
                  "统计局", "经济数据", "宏观数据", "通胀", "物价", "通脹"],
     "weights": {"大盘": +1, "消费": +1, "有色金属": +1,
                 "煤炭能源": +1, "钢铁化工": +1}},
]

# 官方列表里的条例、规划、办法等本身就是政策信息，但标题不一定含有「扶持」或
# 「监管」触发词。仅对 official=True 的政府网条目使用该中性兜底维度，避免普通
# 媒体标题中的「发布」被误判；权重为 0，表示已纳入政策信息但不擅自判断方向。
_OFFICIAL_POLICY_DIMENSION = {
    "id": "official_publication", "label": "政策发布",
    "weights": {"大盘": 0},
}

# 行业别名词表（归因维度用；匹配最长优先，如"锂电"优先于"锂"）。
_POLICY_INDUSTRIES = {
    "新能源": ["新能源", "光伏", "风电", "储能", "锂电池", "锂电",
              "充电桩", "新能源", "光伏"],
    "半导体": ["半导体", "集成电路", "芯片", "晶圆", "半導體", "芯片"],
    "医药": ["生物医药", "创新药", "医药", "医疗", "疫苗", "中药",
            "醫藥", "醫療"],
    "汽车": ["新能源车", "智能驾驶", "无人驾驶", "汽车", "汽車"],
    "军工": ["军工", "国防", "軍工"],
    "AI算力": ["人工智能", "大模型", "数据中心", "算力", "机器人", "AI"],
    "消费": ["食品饮料", "消费", "零售", "白酒", "餐饮", "旅游", "家电"],
    "地产链": ["房地产", "地产", "楼市", "建材", "水泥",
              "房地產", "地產"],
    "银行": ["银行"],
    "证券": ["证券", "券商", "期货", "證券"],
    "保险": ["保险", "保險"],
    "有色金属": ["有色", "稀土", "黄金", "铜", "铝", "锂", "钴",
                "镍", "鎳"],
    "煤炭能源": ["煤炭", "石油", "原油", "天然气", "电力", "火电",
                "水电", "核电"],
    "钢铁化工": ["钢铁", "化工", "化纤", "纯碱", "鋼鐵"],
    "农业": ["农业", "种业", "粮食", "猪肉", "养殖"],
    "传媒游戏": ["传媒", "游戏", "版号", "影视", "廣告", "遊戲"],
    "基建链": ["工程机械", "基建", "建筑", "高铁", "轨交"],
    "科技成长": ["平台经济", "互联网", "科技", "软件", "电子", "互聯網"],
    "出口链": ["跨境电商", "出口", "外贸", "航运", "港口"],
}
_POLICY_INDUSTRY_ALIASES = {}
for _ind_name, _ind_aliases in _POLICY_INDUSTRIES.items():
    for _alias in _ind_aliases:
        _POLICY_INDUSTRY_ALIASES.setdefault(_alias, _ind_name)
_POLICY_INDUSTRY_ALIAS_LIST = list(_POLICY_INDUSTRY_ALIASES)


def _match_policy_triggers(title, triggers):
    """维度触发词匹配：最长优先非重叠；前2字含否定词视为否定表述，跳过。"""
    hits = []
    for word, idx in _match_words_non_overlap(title, triggers):
        window = title[max(0, idx - 2):idx]
        if any(ch in _SENTI_NEGATORS for ch in window):
            continue
        hits.append(word)
    return hits


def _match_policy_industries(title):
    """标题提及的行业（别名最长优先非重叠匹配，按出现顺序去重）。"""
    found = []
    for alias, _ in _match_words_non_overlap(title, _POLICY_INDUSTRY_ALIAS_LIST):
        industry = _POLICY_INDUSTRY_ALIASES[alias]
        if industry not in found:
            found.append(industry)
    return found


def _policy_summary(policy_n, total_n, dim_counts, broad_score, broad_label,
                    winners, losers, official_n=0):
    """规则生成的政策总结（纯数据转述，无伪造）。"""
    if policy_n == 0:
        return "窗口内未检出显著政策新闻。"
    dims = "、".join(f"{k}×{v}" for k, v in
                     sorted(dim_counts.items(), key=lambda kv: (-kv[1], kv[0])))
    # 含「宏观数据」维度（CPI/PPI/统计局等）时，称谓用「政策及宏观数据类新闻」更贴切
    kind = "政策及宏观数据类新闻" if "宏观数据" in dim_counts else "政策类新闻"
    parts = [f"近{POLICY_WINDOW_DAYS}日窗口内检出{kind} {policy_n} 条（占窗口资讯 "
             f"{policy_n}/{total_n}），覆盖维度：{dims}；"
             f"大盘政策冲击指数 PSI {broad_score:+d}（{broad_label}）。"]
    if official_n:
        parts.append(f"其中中国政府网官方发布 {official_n} 条。")
    if winners:
        parts.append("受益居前：" + "、".join(
            f'{w["name"]}{w["score"]:+d}（{w["count"]}条）' for w in winners[:3]) + "。")
    if losers:
        parts.append("承压居前：" + "、".join(
            f'{w["name"]}{w["score"]:+d}（{w["count"]}条）' for w in losers[:3]) + "。")
    if not winners and not losers:
        if official_n and set(dim_counts).issubset({"政策发布"}):
            parts.append("已纳入中国政府网官方政策发布信息，但标题未给出明确方向；行业冲击暂不判定。")
        else:
            parts.append("各行业冲击相互抵消，无显著受益/承压方向。")
    return "".join(parts)


def build_policy_factor(data, date_str=None, news_corpus=None):
    """构建政策因子（抓取后、推送前单独构建；推送页首位栏目）。

    标题窗口：近 POLICY_WINDOW_DAYS=15 日（自然日，含锚定日；news_corpus 为
    跨运行标题存档，缺省时只用本次抓取标题，仍按 15 日窗口过滤）。中国政府网
    直接发布的条目带 official=True、官方原文 URL；即使没有方向性触发词也按
    「政策发布」中性维度纳入。窗口内零政策/宏观新闻时 available=False，栏目缺席。
    """
    anchor_dt = _factor_anchor_dt(date_str) if date_str else datetime.now(CST)
    anchor_date = anchor_dt.strftime("%Y-%m-%d")
    if isinstance(news_corpus, dict) and isinstance(news_corpus.get("items"), list):
        raw = news_corpus["items"]
    else:
        raw = _collect_headline_items(data, anchor_date)
    headlines = _filter_headlines_window(raw, anchor_dt, days=POLICY_WINDOW_DAYS)
    try:
        today_iso = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d") \
            if date_str else anchor_date
    except (TypeError, ValueError):
        today_iso = anchor_date
    industry_scores = {}
    broad_score = 0
    broad_count = 0
    dim_counts = {}
    official_n = 0
    policy_heads = []
    for head in headlines:
        title = head["title"]
        hit_dims = []
        for dim in _POLICY_DIMENSIONS:
            triggers = _match_policy_triggers(title, dim["triggers"])
            if triggers:
                hit_dims.append(dim)
        # 直采的政府网政策正文是官方政策证据。没有方向性词时也保留为中性
        # 政策事件，确保「条例/规划/决定」等正式发布信息不被资讯词表漏掉。
        if not hit_dims and head.get("official"):
            hit_dims.append(_OFFICIAL_POLICY_DIMENSION)
        if not hit_dims:
            continue
        head_industries = []
        head_net = 0
        head_dims = []
        for dim in hit_dims:
            head_dims.append(dim["label"])
            dim_counts[dim["label"]] = dim_counts.get(dim["label"], 0) + 1
            if "weights" in dim:
                pairs = list(dim["weights"].items())
            else:
                mentioned = _match_policy_industries(title)
                if mentioned:
                    pairs = [(ind, dim["weight"]) for ind in mentioned]
                else:
                    pairs = [("大盘", dim["broad_weight"])]
            for ind, w in pairs:
                head_net += w
                if ind == "大盘":
                    broad_score += w
                    broad_count += 1
                else:
                    slot = industry_scores.setdefault(
                        ind, {"score": 0, "count": 0, "dims": set()})
                    slot["score"] += w
                    slot["count"] += 1
                    slot["dims"].add(dim["label"])
                    if ind not in head_industries:
                        head_industries.append(ind)
        item_date = (head.get("date") or "")[:10]
        is_official = bool(head.get("official"))
        if is_official:
            official_n += 1
        policy_heads.append({
            "title": title, "source": head.get("source", ""),
            "section": head.get("section", ""), "url": head.get("url", ""),
            "official": is_official,
            "dims": head_dims, "industries": head_industries,
            "direction": 1 if head_net > 0 else (-1 if head_net < 0 else 0),
            "net": head_net,
            "date": item_date,
            "old": item_date not in ("", today_iso),
        })
    industries = [{
        "name": name, "score": v["score"], "count": v["count"],
        "dims": sorted(v["dims"]),
        "direction": "受益" if v["score"] > 0 else ("承压" if v["score"] < 0 else "中性"),
    } for name, v in industry_scores.items()]
    industries.sort(key=lambda s: (-s["score"], s["name"]))
    winners = [s for s in industries if s["score"] > 0][:POLICY_DISPLAY_INDUSTRIES]
    losers = sorted((s for s in industries if s["score"] < 0),
                    key=lambda s: (s["score"], s["name"]))[:POLICY_DISPLAY_INDUSTRIES]
    broad_label = "偏暖" if broad_score > 0 else ("偏冷" if broad_score < 0 else "中性")
    summary = _policy_summary(len(policy_heads), len(headlines), dim_counts,
                              broad_score, broad_label, winners, losers, official_n)
    return {
        "available": bool(policy_heads),
        "policy_n": len(policy_heads),
        "official_n": official_n,
        "total_headlines": len(headlines),
        "dim_counts": dim_counts,
        "broad_score": broad_score,
        "broad_count": broad_count,
        "broad_label": broad_label,
        "industries": industries,
        "winners": winners,
        "losers": losers,
        "headlines": policy_heads,
        "summary": summary,
        "window_days": POLICY_WINDOW_DAYS,
        "corpus_n": len(headlines),
    }


def _policy_headline_markup(headline, color=C_INK):
    """渲染政策标题，并为官方发布条目保留可点击的原文链接。

    标题来自外部页面，正文必须先转义；仅允许 http/https 链接进入 href，
    避免把存档中的异常值变成脚本属性。中国政府网解析器本身还会限制域名为
    ``*.gov.cn``，这里的通用校验用于兼容手工注入的测试/历史数据。
    """
    title = _esc((headline.get("title") or "")[:60])
    url = str(headline.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
        title = (f'<a href="{_esc(url)}" style="color:{color};text-decoration:none;'
                 f'border-bottom:1px dotted {color};">{title}</a>')
        if headline.get("official"):
            title += (f' <span style="font-size:10px;color:{color};font-weight:900;">'
                      "[官方原文]</span>")
    return title


def _policy_source_text(headline):
    """政策条目的可读来源标签；官方条目明确标注发布主体。"""
    source = headline.get("source") or "政策资讯"
    return f"{source}（官方发布）" if headline.get("official") else source


def _pixel_policy_block(res):
    """像素主题：政策因子（总结置顶 + PSI 行业榜 + 政策新闻逐条）。"""
    if res["broad_score"] > 0:
        color, icon = C_GREEN, "▲"
    elif res["broad_score"] < 0:
        color, icon = C_RED, "▼"
    else:
        color, icon = C_AMBER, "■"
    summary_html = (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
        f'margin-bottom:10px;border:1px solid {color};background:#0C1020;box-shadow:4px 4px 0 #000;">'
        f'<tr><td style="padding:10px 12px;">'
        f'<div style="font-size:9px;color:{color};font-weight:900;font-family:{FONT_MONO};'
        f'letter-spacing:1px;">POLICY READ // 政策因子总结</div>'
        f'<div style="font-size:12px;color:{C_INK};font-weight:700;line-height:1.8;'
        f'font-family:{FONT_MONO};padding-top:4px;">{_esc(res["summary"])}</div>'
        f'</td></tr></table>')
    dims_line = " · ".join(f"{k}×{v}" for k, v in sorted(
        res["dim_counts"].items(), key=lambda kv: (-kv[1], kv[0]))) or "—"
    head = _mini_table([
        ("政策新闻", f'{res["policy_n"]} 条（占近 {res.get("window_days") or POLICY_WINDOW_DAYS} 日窗口资讯 '
                     f'{res["policy_n"]}/{res["total_headlines"]}）'),
        ("大盘冲击", f'PSI <b style="color:{color};">{res["broad_score"]:+d}</b>'
                     f'（{res["broad_count"]}次映射 · {res["broad_label"]}）'),
        ("覆盖维度", _esc(dims_line)),
    ])
    if res.get("official_n"):
        head += _mini_table([("官方来源", f'中国政府网官方发布 {res["official_n"]} 条')])
    board = []
    for s in res["winners"]:
        board.append((f'▲ {_esc(s["name"])}',
                      f'PSI <b style="color:{C_GREEN};">+{s["score"]}</b>'
                      f'（{s["count"]}条 · {_esc("/".join(s["dims"]))}）'))
    for s in res["losers"]:
        board.append((f'▼ {_esc(s["name"])}',
                      f'PSI <b style="color:{C_RED};">{s["score"]}</b>'
                      f'（{s["count"]}条 · {_esc("/".join(s["dims"]))}）'))
    rows = []
    for h in res["headlines"][:POLICY_DISPLAY_HEADLINES]:
        if h["direction"] > 0:
            arrow, bcolor = "▲", C_GREEN
        elif h["direction"] < 0:
            arrow, bcolor = "▼", C_RED
        else:
            arrow, bcolor = "■", C_AMBER
        inds = "、".join(h["industries"][:4]) if h["industries"] else "大盘（宽基）"
        sub = (f'{"/".join(h["dims"])} · 影响：{inds} · {h["section"]} · '
               f'{_policy_source_text(h)}')
        if h.get("old") and h.get("date"):
            sub = f'{h["date"][5:]} · {sub}'
        rows.append(_item_row(
            "◆", f'<b style="color:{bcolor};">[{arrow} {h["net"]:+d}]</b> '
            f'{_policy_headline_markup(h, C_INK)}', _esc(sub)))
    more = len(res["headlines"]) - POLICY_DISPLAY_HEADLINES
    if more > 0:
        rows.append(
            f'<div style="font-size:10px;color:{C_MUTED};padding:4px 0;'
            f'line-height:1.7;font-family:{FONT_MONO};">'
            f'＋其余 {more} 条已计入指数（仅展示前 {POLICY_DISPLAY_HEADLINES} 条）</div>')
    body = head + (_mini_table(board) if board else "") + "".join(rows)
    note = _note(f"政策因子口径：近 {res.get('window_days') or POLICY_WINDOW_DAYS} 日窗口标题 → 政策维度触发词命中 → "
                 "关键词矩阵映射行业权重 → 汇总PSI；触发词被否定修饰时跳过 // RULESET v3 // 非投资建议")
    return summary_html + _pixel_panel("POLICY SHOCK // 政策冲击指数", body, color, icon) + note


def gz_policy_block(res):
    """政策因子（黑白模式：方向只用 ▲▼■ 符号区分）。定调已置顶到「今日结论」。"""
    dims_line = " · ".join(f"{k}×{v}" for k, v in sorted(
        res["dim_counts"].items(), key=lambda kv: (-kv[1], kv[0]))) or "—"
    window = res.get("window_days") or POLICY_WINDOW_DAYS
    pairs = [
        ("大盘冲击", f'PSI {res["broad_score"]:+d} · {_esc(res["broad_label"])}'),
        ("政策新闻", f'{res["policy_n"]} 条（近 {window} 日）'
                     + (f'，其中政府网官方 {res["official_n"]} 条' if res.get("official_n") else "")),
        ("覆盖维度", _esc(dims_line)),
    ]
    out = [gz_kv_table(pairs)]
    board = []
    for s in res["winners"]:
        board.append([f'▲ {_esc(s["name"])}', f'+{s["score"]}', f'{s["count"]}条',
                      _esc("/".join(s["dims"]))])
    for s in res["losers"]:
        board.append([f'▼ {_esc(s["name"])}', f'{s["score"]}', f'{s["count"]}条',
                      _esc("/".join(s["dims"]))])
    if board:
        out.append(gz_subsection("行业冲击榜")
                   + gz_data_table(["行业", "PSI", "条数", "维度"], board))
    heads = res["headlines"][:POLICY_DISPLAY_HEADLINES]
    if heads:
        out.append(gz_subsection("重点政策新闻"))
    for h in heads:
        badge = "▲" if h["direction"] > 0 else ("▼" if h["direction"] < 0 else "■")
        inds = "、".join(h["industries"][:4]) if h["industries"] else "大盘"
        bits = [h["date"][5:] if h.get("date") else "", "/".join(h["dims"]),
                f"影响 {inds}", _policy_source_text(h)]
        sub = " · ".join(_esc(x) for x in bits if x)
        out.append(gz_item_row(
            "◆", f'<b style="color:{GZ_INK};">{badge} {h["net"]:+d}</b> '
            f'{_policy_headline_markup(h, GZ_INK)}', sub))
    return "".join(out)


PIXEL_KIT = _RenderKit(
    market_section=_pixel_market_section,
    channel_block=_channel_block,
    headline_row=_headline_row,
    em_news_row=_em_news_row,
    item_row=_item_row,
    # pixel 的行函数每条已是独立 <table>，拼接后无需再包一层。
    rows=lambda html: html or "",
    note=_note,
    alert=_alert,
    status_footer=_status_footer,
    source_badge=_source_badge,
    ai_badge=lambda: _badge("AI 合成", "ai"),
    ai_block=_ai_analysis_block,
    sentiment_block=_pixel_sentiment_block,
    sentiment_empty_block=_pixel_sentiment_empty_block,
    senti_empty_badge=lambda: _badge("样本不足", "warn"),
    policy_block=_pixel_policy_block,
    panorama_block=_panorama_block,
    calendar_block=_calendar_block,
    # ---- 量化栏目需要的排版原语（注入给 octopus_quant.render）----
    esc=_esc,
    table=lambda headers, rows, aligns=None: _pixel_table(headers, rows, aligns),
    sub=_subsection,
    meter=lambda value, maximum: _signal_meter(value, maximum),
    badge=_badge,
    section=_section,
    kv=lambda pairs: _data_table([(label, value) for label, value in pairs]),
    trend=_trend_badge,
    ok_color=C_GREEN, warn_color=C_AMBER, bad_color=C_RED,
)

GUIZANG_KIT = _RenderKit(
    market_section=gz_market_section,
    channel_block=gz_channel_block,
    headline_row=gz_headline_row,
    em_news_row=gz_em_news_row,
    item_row=gz_item_row,
    rows=gz_rows,
    note=gz_note,
    alert=gz_alert,
    status_footer=gz_status_footer,
    # 徽标置于标题黑条下方的白底区域，保留状态与来源信息。
    source_badge=lambda item: gz_source_badge(item),
    ai_badge=lambda: gz_badge("AI 合成", "ai"),
    ai_block=gz_ai_analysis_block,
    sentiment_block=gz_sentiment_block,
    sentiment_empty_block=gz_sentiment_empty_block,
    senti_empty_badge=lambda: gz_badge("样本不足", "warn"),
    policy_block=gz_policy_block,
    panorama_block=gz_panorama_block,
    calendar_block=gz_calendar_block,
    # ---- 量化栏目需要的排版原语（注入给 octopus_quant.render）----
    esc=_esc,
    table=lambda headers, rows, aligns=None: gz_data_table(headers, rows, aligns=aligns),
    sub=gz_subsection,
    meter=lambda value, maximum: gz_meter(value, maximum, cells=5),
    badge=lambda text, kind="ok": gz_badge(text, kind),
    section=gz_section,
    kv=gz_kv_table,
    trend=gz_trend_badge,
    ok_color=GZ_UP, warn_color=GZ_WARN, bad_color=GZ_DOWN,
)


def _harden_wechat_table_widths(html):
    """把 ``width=100%`` 同步写进内联 style，防止微信把日报压成半屏。

    PushPlus/微信详情页的 HTML 清洗器会在部分客户端移除 ``table`` 的 ``width``
    属性，却保留内联 ``style``。旧版最外层表格只有 ``width=\"100%\"``，属性被
    清洗后便按内容固有宽度收缩，实际截图中整份日报只占约半个屏幕，标题和日期也
    被逐字折行。双写 HTML 属性和 CSS（并使用 ``!important``）可兼容两条渲染链路。
    """
    def patch(match):
        tag = match.group(0)
        if re.search(r'width\s*:\s*100%\s*!important', tag, re.I):
            return tag
        if re.search(r'\bstyle\s*=\s*(["\'])', tag, re.I):
            return re.sub(
                r'(\bstyle\s*=\s*["\'])',
                r'\1width:100%!important;',
                tag,
                count=1,
                flags=re.I,
            )
        return tag[:-1] + ' style="width:100%!important;">'

    return re.sub(
        r'<table\b[^>]*\bwidth\s*=\s*(["\'])100%\1[^>]*>',
        patch,
        html,
        flags=re.I,
    )


def generate_report(data, date_display, date_str, theme=None, sentiment_history=None,
                    policy_result=None, news_corpus=None):
    """生成完整的 HTML 日报（按推送主题分发排版）。

    theme: "guizang"（默认 · 简洁白底研报）/ "pixel"（旧版复古像素）。
    sentiment_history: 跨日情绪基线（AI 新闻情绪因子用），缺省冷启动。
    policy_result: 政策因子结果（main 单独构建），缺省时渲染侧兜底构建。
    news_corpus: 跨运行标题存档（output/news_history.json），供 15 日/72h 窗口。
    """
    theme = _resolve_push_theme(theme)
    if theme == "guizang":
        html = generate_report_guizang(data, date_display, date_str,
                                       sentiment_history=sentiment_history,
                                       policy_result=policy_result,
                                       news_corpus=news_corpus)
    else:
        html = generate_report_pixel(data, date_display, date_str,
                                     sentiment_history=sentiment_history,
                                     policy_result=policy_result,
                                     news_corpus=news_corpus)
    return _harden_wechat_table_widths(html)


def generate_report_guizang(data, date_display, date_str, sentiment_history=None,
                                policy_result=None, news_corpus=None):
    """黑白研报（墨水屏优先）：紧凑的黑底白字标题、白底图标、结构化表格与单列留白。"""
    parts = _collect_report_parts(data, GUIZANG_KIT,
                                  sentiment_history=sentiment_history,
                                  date_str=date_str,
                                  policy_result=policy_result,
                                  news_corpus=news_corpus)
    sections = parts["sections"]
    total = parts["total"]
    today_n = parts["today_n"]
    # 每个栏目前都插入分条标记（含第一栏）：日报超过微信单条上限时，推送侧据此
    # 按「完整栏目」把日报拆成多条消息，绝不把某一栏切成两半，也不丢任何内容。
    content_html = "".join(
        PART_BREAK_MARK + GUIZANG_KIT.section(f"{i:02d}", kicker, title, content, badge, caption)
        for i, (kicker, title, content, badge, caption) in enumerate(sections, 1))
    generated_at = _now()
    masthead_title_bar = gz_shell(
        f'<h1 style="margin:0;background:{GZ_INK};font-size:{GZ_FS_DISPLAY}px;'
        f'font-weight:{GZ_W_BOLD};color:{GZ_PAPER};font-family:{GZ_SERIF};'
        f'letter-spacing:1px;line-height:1.4;">{_esc(REPORT_TITLE)}</h1>',
        bg=GZ_INK, pad="14px 18px")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<meta name="format-detection" content="telephone=no">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<meta name="octopus-theme" content="guizang">
<title>{REPORT_TITLE}</title>
</head>
<body bgcolor="{GZ_PAPER}" style="margin:0;padding:0;background:{GZ_PAPER};font-family:{GZ_SANS};color:{GZ_INK};font-size:{GZ_FS_BODY}px;font-weight:{GZ_W_BODY};line-height:1.85;-webkit-text-size-adjust:100%;word-break:break-word;overflow-wrap:break-word;word-wrap:break-word;">
<table width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="{GZ_PAPER}" style="width:100%!important;border-collapse:collapse;table-layout:fixed;background:{GZ_PAPER};">
<tr><td align="center" valign="top" style="padding:0 24px;">
<table width="100%" border="0" cellpadding="0" cellspacing="0" style="width:100%!important;max-width:760px;margin:0 auto;border-collapse:collapse;table-layout:fixed;"><tr><td>

<table width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="{GZ_PAPER}" style="width:100%!important;border-collapse:collapse;table-layout:fixed;">
<tr><td align="left" valign="top" style="padding:64px 0 24px;">
{gz_icon("octopus", masthead=True)}
<div style="font-size:{GZ_FS_META}px;color:{GZ_META};line-height:1.8;">{_esc(date_display)}</div>
<div style="padding-top:18px;">{masthead_title_bar}</div>
<div style="font-size:{GZ_FS_META}px;color:{GZ_META};padding-top:16px;line-height:1.8;">更新于 {_esc(generated_at)} · 当天源 {today_n}/{total}</div>
{gz_masthead_icon_row()}
</td></tr>
</table>

{content_html}

{DOC_FOOT_MARK}
<table width="100%" border="0" cellpadding="0" cellspacing="0" bgcolor="{GZ_PAPER}" style="width:100%!important;border-collapse:collapse;table-layout:fixed;background:{GZ_PAPER};">
<tr><td bgcolor="{GZ_PAPER}" align="left" valign="top" style="padding:40px 0 56px;background:{GZ_PAPER};">
<div style="font-size:{GZ_FS_META}px;color:{GZ_META};line-height:1.8;border-top:{GZ_HAIR_W}px solid {GZ_HAIR};padding-top:12px;">
仅供参考，非投资建议。
</div>
</td></tr>
</table>

</td></tr>
</table>
</td></tr></table>
</body>
</html>"""
    return html


def generate_report_pixel(data, date_display, date_str, sentiment_history=None,
                              policy_result=None, news_corpus=None):
    """生成完整 HTML 日报（旧版 RETRO PIXEL 排版：终端 + 关卡 + 审计 + COLOPHON）。

    - 每个区块都带来源、抓取时间与「当天/非当天/无数据」徽标；
    - 没有抓到内容的区块不出现在页面主体，仅在数据审计栏留痕；
    - 当天内容检验仍作为推送门禁，但不在页面顶部单独显示横幅。
    """
    parts = _collect_report_parts(data, PIXEL_KIT,
                                  sentiment_history=sentiment_history,
                                  date_str=date_str,
                                  policy_result=policy_result,
                                  news_corpus=news_corpus)
    sections = parts["sections"]
    total = parts["total"]
    today_n = parts["today_n"]
    content_n = parts["content_n"]

    # 6. 拼版：栏目编号按渲染顺序生成（只在场的栏目占用编号）
    # 每个栏目前都插入分条标记（含第一栏），供超长日报按完整栏目分条推送
    content_html = "".join(
        PART_BREAK_MARK + PIXEL_KIT.section(f"{i:02d}", kicker, title, content, badge, caption)
        for i, (kicker, title, content, badge, caption) in enumerate(sections, 1))

    # 7. 拼接完整 HTML（头部嵌入元信息，供 --push-only 二次当天检验）
    generated_at = _now()
    src_color = C_GREEN if today_n > 0 else (C_AMBER if content_n > 0 else C_RED)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<meta name="octopus-report-date" content="{date_str}">
<meta name="octopus-generated-at" content="{generated_at}">
<meta name="octopus-today-sources" content="{today_n}">
<meta name="octopus-total-sources" content="{total}">
<meta name="octopus-theme" content="pixel">
<title>章鱼AI · 财经作战日志 | RETRO PIXEL EDITION</title>
</head>
<body style="margin:0;padding:0;background:{C_BG};font-family:{FONT};color:{C_INK};font-size:13px;line-height:1.7;-webkit-text-size-adjust:100%;">

<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:680px;margin:0 auto;background:{C_BG};">
<tr><td style="padding:12px 10px;">

<!-- 外框：像素终端窗口 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:{C_PAPER};border:1px solid {C_ACCENT};box-shadow:8px 8px 0 #000;">
<tr><td style="padding:0;">

<!-- 标题栏：像 8-bit 窗口 title bar -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:{C_ACCENT};"><tr>
<td style="padding:5px 8px;font-family:{FONT_MONO};font-size:10px;font-weight:900;color:#000;letter-spacing:1px;">OCTOPUS_OS v3.0 // PIXEL.MARKET.QUEST</td>
<td align="right" style="padding:5px 8px;font-family:{FONT_MONO};font-size:10px;font-weight:900;color:#000;">[−][□][×]</td>
</tr></table>

<div style="padding:18px 18px 20px;">

<!-- 刊头 masthead：纯 HTML 像素章鱼 + 游戏卡带标题 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
<tr>
<td width="56" valign="middle" style="padding-right:10px;">
<table width="48" height="48" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid {C_ACCENT};background:#080C18;box-shadow:5px 5px 0 #000;"><tr><td align="center" valign="middle">{_pixel_octopus(4)}</td></tr></table>
</td>
<td valign="middle"><div style="font-size:11px;color:{C_ACCENT};font-weight:900;letter-spacing:2px;font-family:{FONT_MONO};">OCTOPUS AI</div><div style="font-size:9px;color:{C_CYAN};letter-spacing:1px;font-family:{FONT_MONO};padding-top:3px;">[ RETRO FINANCE CARTRIDGE ]</div></td>
<td align="right" valign="middle"><span style="font-size:8px;font-weight:900;color:{C_ACCENT_MAGENTA};letter-spacing:2px;font-family:{FONT_MONO};border:1px solid {C_ACCENT_MAGENTA};padding:2px 5px;background:#301226;box-shadow:2px 2px 0 #000;">PLAYER 01</span></td>
</tr>
</table>

<div style="font-size:27px;font-weight:900;color:{C_ACCENT_DEEP};letter-spacing:.5px;line-height:1.3;padding-top:16px;font-family:{FONT_MONO};text-shadow:3px 3px 0 {C_ACCENT_SOFT};">财经作战日志<span style="color:{C_ACCENT};">_</span></div>
<div style="font-size:10px;font-weight:900;color:{C_CYAN};letter-spacing:2px;padding-top:5px;font-family:{FONT_MONO};">DAILY MARKET QUEST // SIGNAL · AI · FLOW · UTC+8</div>
<div style="margin-top:12px;border-top:1px solid {C_ACCENT};border-bottom:1px solid {C_ACCENT_MAGENTA};height:5px;font-size:0;line-height:0;"><span style="color:{C_ACCENT};">■■■■</span></div>

<!-- 导语：终端开机文字 -->
<div style="margin-top:14px;border:1px solid {C_CYAN};background:#091321;padding:10px 12px;font-size:11px;color:{C_INK};line-height:1.8;font-family:{FONT_MONO};box-shadow:5px 5px 0 #000;">
<span style="color:{C_ACCENT};font-weight:900;">▶ BOOT</span> MARKET DATA LOADED<br>
<span style="color:{C_LEMON};font-weight:900;">◆ AI</span> CORE ANALYSIS READY<br>
<span style="color:{C_ACCENT_MAGENTA};font-weight:900;">■ MODE</span> RETRO PIXEL // 仅渲染有效数据，无数据关卡自动隐藏
</div>

<!-- 视觉图例：颜色 + 方向符号双重编码 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:12px;border:1px solid {C_ACCENT_SOFT};background:#090D1A;box-shadow:3px 3px 0 #000;">
<tr>
<td width="33%" align="center" style="padding:7px 3px;border-right:1px solid {C_ACCENT_SOFT};font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_GREEN};">▲ 涨 / UP</td>
<td width="33%" align="center" style="padding:7px 3px;border-right:1px solid {C_ACCENT_SOFT};font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_RED};">▼ 跌 / DOWN</td>
<td width="34%" align="center" style="padding:7px 3px;font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_LEMON};">◆ AI / CORE</td>
</tr>
</table>

<!-- 期号元信息栅格：像状态栏 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-top:1px solid {C_ACCENT_SOFT};border-bottom:1px solid {C_ACCENT_SOFT};margin-top:14px;background:#0F1222;">
<tr>
{_masthead_cell("DATE", _esc(date_display), first=True)}
{_masthead_cell("BOOT TIME", _esc(generated_at))}
{_masthead_cell("LIVE SRC", f"{today_n} / {total}", src_color)}
</tr>
</table>

<!-- 内容关卡列表 -->
{content_html}

{DOC_FOOT_MARK}
<!-- 版权页 colophon：像素终端关机界面 -->
<div style="border-top:1px solid {C_ACCENT};margin-top:26px;padding-top:12px;background:#0F1222;padding:12px;">
<div style="font-family:{FONT_MONO};font-size:10px;font-weight:900;color:{C_ACCENT};letter-spacing:2px;">{ _heart(C_ACCENT, 10) } OCTOPUS-CHAN // SYSTEM SHUTDOWN</div>
<div style="font-size:10px;color:{C_MUTED};line-height:1.8;padding-top:6px;font-family:{FONT_MONO};">
> 仅供投资参考，非投资建议。行情与榜单来自公开数据，未抓取到内容的栏目自动隐藏，不以历史内容充数。<br>
> RENDER MODE: RETRO PIXEL 8-BIT // 大图标关卡卡牌 // AI CORE 高亮<br>
> TREND KEY: [▲ 涨 / UP] [▼ 跌 / DOWN] [■ 平 / FLAT] [◆ AI CORE]
</div>
<div style="font-size:9px;color:{C_FAINT};letter-spacing:.5px;line-height:1.6;padding-top:6px;font-family:{FONT_MONO};">
DATA_SRC: China Gov Policy · HK GURU (YT/RSS) · Google News · EastMoney · Sina · AI_RULE<br>
SYS_TIME: {_esc(generated_at)} · LOG_DATE: {date_str} · BUILD: OCTO-PIXEL-QUEST v3<br>
<span style="color:{C_ACCENT};">█</span><span style="color:{C_CYAN};">▓</span><span style="color:{C_ACCENT_MAGENTA};">▒</span> PRESS START TO CONTINUE
</div>
</div>

</div>

</td></tr>
</table>

</td></tr>
</table>
</body>
</html>"""


    return html


# ============================================================
# PushPlus 推送
# ============================================================
# 可恢复错误的退避重试节奏：首次 + 3 次重试（共最多 4 次尝试）
PUSH_RETRY_BACKOFF = (10, 30, 60)

# 配额/凭证/内容类错误关键字：重试无意义，立即失败，避免浪费仅剩的额度。
_PUSH_FATAL_KEYWORDS = (
    "已达上限", "已用完", "超出今日", "超过今日", "今日已达", "发送次数",
    "token错误", "token 错误", "token 无效", "token无效", "用户不存在",
    "敏感", "违规",
)

# 频率/服务器类错误关键字：稍等重试通常可以恢复。
_PUSH_RETRYABLE_KEYWORDS = (
    "频繁", "太快", "频率", "稍后再试", "稍后重试", "请重试", "繁忙",
    "too many", "frequent", "rate limit", "busy", "retry", "timeout", "超时",
)


def _push_failure_kind(http_status=None, code=None, msg=""):
    """把一次推送失败分类：

    transient —— 频率/服务器/网络类，按 PUSH_RETRY_BACKOFF 重试；
    fatal     —— 配额/凭证/内容类，重试无意义，立即失败；
    unknown   —— 无法归类的业务错误，不重试，立即失败并把 code/msg 打进日志。
    """
    if isinstance(http_status, int) and (http_status == 429 or http_status >= 500):
        return "transient"
    if isinstance(http_status, int) and 400 <= http_status < 500:
        return "fatal"
    low = (msg or "").lower()
    # 先看致命关键字，避免「已达上限，请稍后再试」被误判成可重试
    if any(k in low for k in _PUSH_FATAL_KEYWORDS):
        return "fatal"
    if any(k in low for k in _PUSH_RETRYABLE_KEYWORDS):
        return "transient"
    return "unknown"


# ------------------------------------------------------------
# PushPlus 内容上限截断
# ------------------------------------------------------------
# 自闭合 / void 标签（不会消耗闭合标签）
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}
# 匹配完整标签（含属性中带引号的 > ），用于按标签边界安全截断
_TAG_RE = re.compile(r"<(?P<close>/)?(?P<tag>[a-zA-Z][a-zA-Z0-9]*)"
                     r"(?P<attrs>(?:\"[^\"]*\"|'[^']*'|[^>\"'])*)>")


def _build_truncate_notice(report_name=None):
    """生成截断提示条：说明推送被截断、磁盘完整版不受影响，并附完整版链接（如有）。"""
    link = ""
    if report_name:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if repo:
            url = (f"https://raw.githubusercontent.com/{repo}/main/output/"
                   f"{report_name}")
            link = (f'<div style="padding-top:6px;"><a href="{url}" '
                    f'style="color:{C_ACCENT};font-weight:700;text-decoration:none;">'
                    f"→ 查看完整日报（{report_name}）</a></div>")
    fname = f"（完整版文件：{report_name}）" if report_name else ""
    return (f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;margin-top:8px;background:{C_ZEBRA};'
            f'border:1px solid {C_HAIR};border-left:1px solid {C_AMBER};"><tr><td '
            f'style="padding:8px 10px;font-size:11px;color:{C_AMBER};line-height:1.75;">'
            f"微信推送有内容长度上限，本消息已自动截断；仓库中的完整日报不受影响{fname}。"
            f"{link}</td></tr></table>")


def _truncate_html_for_push(html, limit=PUSHPLUS_MAX_CONTENT_CHARS, report_name=None):
    """把 HTML 截断到 PushPlus 内容上限以内：只切在完整标签边界，并逆序补全所有未闭合标签。

    返回 (截断后的 html, 是否发生了截断)。磁盘上的日报文件不会被改动——完整版始终保留，
    微信推送只发截断后的版本，末尾附完整版链接/文件名，避免平台截断导致整页排版崩坏。
    """
    if len(html) <= limit:
        return html, False

    notice = _build_truncate_notice(report_name)

    stack = []          # 未闭合标签栈
    candidates = []     # (完整标签结束位置, 该位置时的标签栈快照)
    for m in _TAG_RE.finditer(html):
        end = m.end()
        if end > limit:
            break
        tag, closing = m.group("tag").lower(), bool(m.group("close"))
        if tag not in _VOID_TAGS:
            if closing:
                if stack and stack[-1] == tag:
                    stack.pop()
                # 不匹配时保持栈不变：由下面的逆序补闭合保证结果合法
            else:
                stack.append(tag)
        candidates.append((end, stack.copy()))

    # 从最后一个候选点向前找：正文 + 截断提示 + 逆序闭合标签 的总长不超过上限。
    # 越靠前的候选点未闭合标签越少，闭合标签越短，因此总能找到可用点。
    for end, stack_at_cut in reversed(candidates):
        closers = "".join(f"</{t}>" for t in reversed(stack_at_cut))
        if len(html[:end]) + len(notice) + len(closers) <= limit:
            return html[:end] + notice + closers, True

    # 极端情况：任何截断点都放不下 → 只发截断提示，保证微信端仍能看到说明与完整版入口
    return notice, True


# ------------------------------------------------------------
# PushPlus 分条完整推送（2026-09-28 起）
# ------------------------------------------------------------
# 日报（含港股量化引擎后）常有 15~25 万字，远超单条 10 万字上限；旧做法在 10 万字处
# 截断，等于每天有近六成内容根本没送到微信。改为「分条完整推送」：
#   渲染时在栏目前插入分条标记（PART_BREAK_MARK）、在页脚前插入 DOC_FOOT_MARK，
#   于是任意一份日报都能被切成 头部外壳 + 若干完整栏目 + 页脚外壳 三段；
#   拆分时按栏目边界装箱，每条消息都是「结构完整、标签自闭合、样式一致」的独立 HTML，
#   微信端读起来就是同一份日报的连续几页，一个字都不丢。
# 单个栏目自身就超预算时，再按完整标签边界切，并在续片里原样重开父标签（保留属性），
# 因此任何上限配置下都不会丢内容、也不会出现半截标签导致的整页排版崩坏。

def _opening_tag_name(open_tag):
    """从完整开标签原文里取标签名（小写）；解析失败返回空串。"""
    m = re.match(r"<\s*([a-zA-Z][a-zA-Z0-9]*)", open_tag or "")
    return m.group(1).lower() if m else ""


def _scan_open_tags(html, limit):
    """扫描 html 前 limit 字符内的完整标签，返回可安全切点列表。

    元素为 (标签结束位置, 未闭合开标签原文列表)；开标签保留原始属性，
    续片据此原样重开父容器，样式不会丢。
    """
    stack = []
    candidates = []
    for m in _TAG_RE.finditer(html):
        if m.end() > limit:
            break
        tag, closing = m.group("tag").lower(), bool(m.group("close"))
        if tag not in _VOID_TAGS:
            if closing:
                if stack and _opening_tag_name(stack[-1]) == tag:
                    stack.pop()
                # 不匹配时保持栈不变：由逆序补闭合保证结果合法
            else:
                stack.append(m.group(0))
        candidates.append((m.end(), list(stack)))
    return candidates


def _closers_for(stack):
    """按逆序为未闭合标签栈生成闭合标签串。"""
    return "".join(f"</{_opening_tag_name(t)}>" for t in reversed(stack))


def _split_long_fragment(fragment, budget):
    """把单个超长片段切成若干「各自标签平衡」的片段；续片原样重开被切断的父标签。

    返回片段列表（至少 1 个）。切不动时（budget 连一个标签都放不下）原样返回，
    由调用方决定回退策略——绝不静默丢内容。
    """
    if budget <= 0 or len(fragment) <= budget:
        return [fragment]
    pieces = []
    rest = fragment
    for _ in range(PUSHPLUS_MAX_PARTS * 8):     # 防御性上限，正常远远用不到
        if len(rest) <= budget:
            break
        picked = None
        for end, stack in reversed(_scan_open_tags(rest, budget)):
            closers = _closers_for(stack)
            if end + len(closers) <= budget and end > 0:
                picked = (end, stack, closers)
                break
        if picked is None:
            break                               # 无法在预算内找到合法切点
        end, stack, closers = picked
        reopened = "".join(stack)               # 续片要原样重开的父标签（含原始属性）
        if end <= len(reopened):
            # 切点还没跨过被重开的标签：这一刀没有实质进展（正文是一整段无标签长文本），
            # 继续切只会原地打转 → 交回调用方走截断兜底，绝不发出半截标签。
            break
        pieces.append(rest[:end] + closers)
        rest = reopened + rest[end:]
        if not rest:
            break
    pieces.append(rest)
    return [p for p in pieces if p]


def _build_part_banner(index, total, theme=None, limit=None, tail_cut=False):
    """分条推送的条序横幅：告诉读者这是第几条 / 共几条，以及为什么要分条。

    tail_cut=True 用于「条数已达 PUSHPLUS_MAX_PARTS 上限」的收尾条：
    此时后面还有内容没推完，横幅必须如实说明并指向完整日报，不能谎称已送达全文。
    """
    limit = limit or PUSHPLUS_MAX_CONTENT_CHARS
    if tail_cut:
        text = (f"📄 第 {index}/{total} 条 · 已达单次推送条数上限"
                f"（PUSHPLUS_MAX_PARTS={total}），本条之后的内容见文末完整日报链接")
    else:
        text = (f"📄 第 {index}/{total} 条 · 完整日报共 {total} 条"
                f"（单条上限 {limit // 10000 or 1} 万字，按栏目拆分，内容不缺失）")
        if index < total:
            text += f" · 接下条 {index + 1}/{total}"
    if theme == "pixel":
        return (f'<table width="100%" cellpadding="0" cellspacing="0" '
                f'style="border-collapse:collapse;margin:0 0 12px;background:{C_ACCENT};">'
                f'<tr><td style="padding:8px 10px;font-family:{FONT_MONO};font-size:11px;'
                f'font-weight:900;color:#000;line-height:1.6;">{text}</td></tr></table>')
    return (f'<table width="100%" border="0" cellpadding="0" cellspacing="0" '
            f'bgcolor="{GZ_INK}" style="width:100%!important;border-collapse:collapse;'
            f'table-layout:fixed;background:{GZ_INK};margin:0 0 8px;">'
            f'<tr><td align="left" valign="top" style="padding:10px 16px;">'
            f'<div style="font-size:{GZ_FS_META + 1}px;color:{GZ_PAPER};'
            f'font-weight:{GZ_W_BOLD};line-height:1.6;font-family:{GZ_SANS};">'
            f'{text}</div></td></tr></table>')


def _report_theme(html):
    """从日报 HTML 里读出渲染主题（供分条横幅配色）；读不出来按默认主题处理。"""
    m = re.search(r'name="octopus-theme"\s+content="([^"]+)"', html or "")
    theme = (m.group(1) if m else "").strip().lower()
    return theme if theme in PUSH_THEMES else DEFAULT_PUSH_THEME


def _split_html_for_push(html, limit=None, report_name=None, max_parts=None):
    """把超过单条上限的日报 HTML 拆成 N 条「各自完整可渲染」的消息；返回 list[str]。

    每条 = 原文档头部外壳（含刊头）+ 条序横幅 + 若干完整栏目 + 原文档页脚与闭合标签，
    因此每条都是独立、标签平衡、样式一致的 HTML，微信端排版与单条推送完全相同。
    全部内容按原文顺序送达，不做任何删减。

    返回 None 表示无法安全拆分（旧版文件没有分条标记 / 外壳本身就超上限 /
    需要的条数超过 max_parts），调用方应回退到 _truncate_html_for_push。
    """
    # 上限与条数上限都在调用时解析（而不是写进默认参数），环境变量与测试都能覆盖
    limit = limit if limit is not None else PUSHPLUS_MAX_CONTENT_CHARS
    max_parts = max_parts if max_parts is not None else PUSHPLUS_MAX_PARTS
    if limit <= 0 or len(html) <= limit:
        return [html] if html else None

    first_break = html.find(PART_BREAK_MARK)
    foot_at = html.find(DOC_FOOT_MARK)
    if first_break < 0 or foot_at < 0 or foot_at <= first_break:
        print("  ⚠️ 该 HTML 没有分条锚点（旧版日报文件？），无法按栏目拆分")
        return None

    shell = html[:first_break]                   # doctype/head/body/刊头 + 未闭合的外层容器
    tail = html[foot_at + len(DOC_FOOT_MARK):]   # 页脚 + 全部闭合标签
    body = html[first_break + len(PART_BREAK_MARK):foot_at]
    sections = [s for s in body.split(PART_BREAK_MARK) if s.strip()]
    if not sections:
        return None

    theme = _report_theme(html)
    # 每条的固定开销：外壳 + 页脚 + 横幅（按最宽的条序数字预留）+ 安全余量
    banner_w = max(len(_build_part_banner(i, max(max_parts, len(sections)), theme, limit))
                   for i in (1, max(max_parts, len(sections))))
    overhead = len(shell) + len(tail) + banner_w + 64
    budget = limit - overhead
    if budget < 2000:
        print(f"  ⚠️ 单条上限 {limit:,} 字太小：刊头+页脚+横幅已占 {overhead:,} 字，"
              f"正文只剩 {budget:,} 字，拆分没有意义")
        return None

    # 装箱：优先整栏装进一条；单栏超预算时再按标签边界细分（内容不丢）
    chunks, current, current_len = [], [], 0
    for section in sections:
        for piece in _split_long_fragment(section, budget):
            if current and current_len + len(piece) > budget:
                chunks.append("".join(current))
                current, current_len = [], 0
            current.append(piece)
            current_len += len(piece)
    if current:
        chunks.append("".join(current))
    if not chunks:
        return None

    # 条数超过安全上限（只会在把单条上限调得极小时发生）：前 max_parts-1 条完整推送，
    # 最后一条装到上限为止并附「完整日报」链接——比退回单条截断多送达十几倍内容，
    # 且如实告知未推完，绝不假装全文已送达。
    tail_cut = len(chunks) > max_parts
    if tail_cut:
        keep = max(max_parts - 1, 1)
        print(f"  ⚠️ 完整推送需要 {len(chunks)} 条，超过 PUSHPLUS_MAX_PARTS={max_parts}："
              f"前 {keep} 条完整推送，其余内容压进第 {keep + 1} 条并附完整日报链接"
              f"（如需全部送达，请调高 PUSHPLUS_MAX_PARTS 或 PUSHPLUS_MAX_CONTENT_CHARS）")
        chunks = chunks[:keep] + ["".join(chunks[keep:])]

    total = len(chunks)
    title_re = re.compile(r"(<title>)(.*?)(</title>)", re.S)
    parts = []
    for index, chunk in enumerate(chunks, 1):
        last_cut = tail_cut and index == total
        banner = _build_part_banner(index, total, theme, limit, tail_cut=last_cut)
        head = shell
        if total > 1:
            # 让每条的浏览器/微信标题也带上条序，正文横幅之外再多一层提示
            head = title_re.sub(
                lambda m: f"{m.group(1)}{m.group(2)}（第 {index}/{total} 条）{m.group(3)}",
                shell, count=1)
        part = head + banner + chunk + tail
        if len(part) > limit:
            if not last_cut:
                # 只可能是「一整段没有标签边界的超长正文」切不开：宁可回退到截断，
                # 也绝不发出超过平台上限的内容（平台自己截断会切在标签中间，整页排版崩坏）
                print(f"  ⚠️ 第 {index}/{total} 条装不进 {limit:,} 字且无法在标签边界切开"
                      f"（正文存在超长无标签文本），本次不做分条")
                return None
            part, _ = _truncate_html_for_push(part, limit, report_name)
        parts.append(part)
    return parts


def push_to_wechat(title, content_html, token=None, template="html", report_name=None,
                   topic=None):
    """通过 PushPlus 推送消息到微信；返回 True/False，调用方必须据此决定退出码。

    - 默认「一对一」推送（不携带 topic）；只有显式设置 PUSHPLUS_TOPIC
      或传入非空 topic 时才推送到群组；传空字符串可临时回退一对一；
    - 日报 HTML 超过单条上限（PUSHPLUS_MAX_CONTENT_CHARS，默认 10 万字）时**不丢内容**：
      按栏目边界拆成多条消息依次推送（标题追加 1/N、2/N…），全部内容都会送达；
      拆分不可用时（旧版文件没有分条标记）才回退到「按标签边界截断 + 完整版链接」；
    - 「发送频繁 / 稍后再试 / 服务器繁忙 / 网络异常 / HTTP 429·5xx」等可恢复错误
      按 PUSH_RETRY_BACKOFF 自动重试（最多 1+3=4 次），多条推送时每条各自享有重试；
    - token 失效、当日配额已达上限、内容违规等错误重试无意义，立即返回 False；
    - 每次失败都在日志里保留 PushPlus 返回的 code/msg，便于在 Actions 日志定位。
    """
    token = token or PUSHPLUS_TOKEN
    topic = topic if topic is not None else PUSHPLUS_TOPIC

    if not token:
        print("⚠️ 未设置 PUSHPLUS_TOKEN，跳过推送")
        print("   请设置环境变量: export PUSHPLUS_TOKEN=你的token")
        print("   （在 GitHub Actions 中请确认仓库 Settings → Secrets → PUSHPLUS_TOKEN 已配置）")
        return False

    mode = f"一对多群组 {topic}" if topic else "一对一"
    print(f"📤 正在推送到微信 (PushPlus, template={template}, {mode})...")
    if template == "html" and len(content_html) > PUSHPLUS_MAX_CONTENT_CHARS:
        parts = _split_html_for_push(content_html, PUSHPLUS_MAX_CONTENT_CHARS,
                                     report_name) if PUSHPLUS_MULTIPART else None
        if parts:
            print(f"  📚 日报 {len(content_html):,} 字 > 单条上限 "
                  f"{PUSHPLUS_MAX_CONTENT_CHARS:,} 字 → 按栏目边界拆成 {len(parts)} 条"
                  f"完整推送（微信会收到 {len(parts)} 条消息，磁盘上仍是一份完整日报）")
            return _push_html_parts(title, parts, token=token, topic=topic)
        if PUSHPLUS_MULTIPART:
            print("  ↩️ 已回退到旧的单条推送：按完整标签边界截断 + 末尾附完整日报链接")
        content_html, was_truncated = _truncate_html_for_push(
            content_html, PUSHPLUS_MAX_CONTENT_CHARS, report_name)
        if was_truncated:
            print(f"  ⚠️ 日报 HTML 超过 PushPlus 上限 {PUSHPLUS_MAX_CONTENT_CHARS} 字符，"
                  f"已按完整标签边界截断后推送（磁盘上的完整版不受影响）")
    return _push_one_message(title, content_html, token=token, template=template,
                             topic=topic)


def _push_html_parts(title, parts, token=None, topic=None):
    """按顺序推送拆分后的多条正文；全部成功才返回 True。

    - 每条标题追加「(i/N)」，微信消息列表里一眼能看出条序，也避免标题完全重复被去重；
    - 条与条之间等待 PUSHPLUS_PART_DELAY 秒，降低触发「发送频繁」的概率；
    - 任意一条最终失败即停止后续条并返回 False（调用方会发失败告警、以退出码 1 结束），
      日志里明确写出「已送达 i-1 条 / 共 N 条」，不掩盖部分送达的事实。
    """
    total = len(parts)
    for index, part in enumerate(parts, 1):
        if index > 1 and PUSHPLUS_PART_DELAY > 0:
            print(f"  ⏳ 等待 {PUSHPLUS_PART_DELAY:g}s 后推送第 {index}/{total} 条"
                  f"（避开 PushPlus 频率限制）...")
            time.sleep(PUSHPLUS_PART_DELAY)
        print(f"  📄 第 {index}/{total} 条（{len(part):,} 字）...")
        if not _push_one_message(f"{title} ({index}/{total})", part, token=token,
                                 template="html", topic=topic):
            print(f"  ❌ 第 {index}/{total} 条推送失败：已送达 {index - 1} 条，"
                  f"剩余 {total - index + 1} 条未发送（完整日报未全部送达）")
            return False
    print(f"  ✅ 完整日报已全部送达（共 {total} 条消息）")
    return True


def _push_one_message(title, content_html, token=None, template="html", topic=None):
    """发送单条 PushPlus 消息（含退避重试）；返回 True/False。"""
    token = token or PUSHPLUS_TOKEN
    topic = topic if topic is not None else PUSHPLUS_TOPIC
    payload = {
        "token": token,
        "title": title,
        "content": content_html,
        "template": template,
    }
    if topic:
        payload["topic"] = topic
    attempts = (0, *PUSH_RETRY_BACKOFF)
    last_error = "未知错误"

    for attempt, wait in enumerate(attempts, 1):
        if wait:
            print(f"  ⏳ 等待 {wait}s 后进行第 {attempt}/{len(attempts)} 次尝试...")
            time.sleep(wait)
        http_status = None
        try:
            resp = requests.post(PUSHPLUS_URL, json=payload, timeout=30)
            http_status = getattr(resp, "status_code", None)
            result = resp.json()
        except Exception as exc:
            last_error = f"网络/请求异常: {exc}"
            if http_status is not None:
                kind = _push_failure_kind(http_status, None, str(exc))
            elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
                # requests 的网络异常（含 SSL/超时/连接重置）都是 OSError 子类，可重试
                kind = "transient"
            else:
                # 编程错误等非网络异常：重试无意义，立即失败并暴露原因
                kind = "unknown"
        else:
            code = result.get("code") if isinstance(result, dict) else None
            msg = str(result.get("msg", "未知错误")) if isinstance(result, dict) else "返回数据格式错误"
            if code == 200:
                print("  ✅ 推送成功！" if attempt == 1 else f"  ✅ 推送成功！（第 {attempt} 次尝试）")
                return True
            last_error = f"PushPlus code={code} msg={msg}"
            kind = _push_failure_kind(http_status, code, msg)

        remaining = len(attempts) - attempt
        if kind == "transient" and remaining > 0:
            print(f"  ⚠️ 第 {attempt}/{len(attempts)} 次推送失败（可重试错误）: {last_error}")
            continue
        if kind == "fatal":
            print(f"  ❌ 推送失败（配额/凭证/内容类错误，重试无意义）: {last_error}")
        else:
            print(f"  ❌ 推送失败: {last_error}")
        return False

    print(f"  ❌ 推送最终失败（已重试 {len(attempts) - 1} 次）: {last_error}")
    return False


def build_no_push_alert_text(reason, data, report_path=None):
    """生成「当天检验未通过」纯文本告警正文（列出每个来源的当天/非当天/无数据状态）。"""
    items = [(k, v) for k, v in (data or {}).items() if isinstance(v, dict)]
    total = len(items)
    content_n = sum(1 for _, v in items if v.get("status") == "success")
    lines = [
        f"📅 当天内容检验未通过（{_now()} 北京时间）",
        f"原因：{reason}",
        f"数据：{content_n}/{total} 个来源抓到内容，且无来源判定为当天，"
        f"已按防旧内容规则不推送日报。",
        "",
        "各来源状态：",
    ]
    for name, s in items:
        if s.get("status") != "success":
            mark = "⚠️ 无数据"
        elif s.get("is_today"):
            mark = "✅ 当天"
        else:
            mark = "🕓 非当天"
        lines.append(f"· {name}：{mark}（数据日期 {s.get('content_date') or '—'}）")
    lines += [
        "",
        "处理建议：",
        "· 周末/休市/源站维护属预期情况，无需处理；",
        "· 确需强制推送：Actions 手动运行并勾选 force_push，"
        "或本地 ./output/manual_push.sh --force。",
        f"报告文件：{os.path.basename(report_path) if report_path else '—'}",
    ]
    return "\n".join(lines)


def push_no_push_alert(reason, data, report_path=None, token=None):
    """推送「当天检验未通过」纯文本告警。

    返回 True/False；返回 False 时调用方应以退出码 1 结束，
    确保 token 缺失 / 接口异常在 Actions 上显红而不是静默。
    """
    print("📣 正在推送「检验未通过」纯文本告警（避免彻底沉默）...")
    title = f"🐙 日报未推送提醒 {datetime.now(CST).strftime('%m/%d %H:%M')}"
    return push_to_wechat(title, build_no_push_alert_text(reason, data, report_path),
                          token=token, template="txt")


def build_push_failure_alert_text(reason, data=None, report_path=None):
    """生成「日报推送失败」兜底告警正文：日报已生成但被 PushPlus 拒绝时，
    让微信侧也能直接看到失败原因和处理建议，而不是只看到 Actions 变红。"""
    lines = [
        f"⚠️ 日报已生成，但推送到微信失败（{_now()} 北京时间）",
        f"原因：{reason}",
        "",
    ]
    if data:
        items = [v for v in data.values() if isinstance(v, dict)]
        today_n = sum(1 for v in items if v.get("is_today"))
        lines.append(f"数据状态：{today_n}/{len(items)} 个来源为当天内容，日报内容本身无问题。")
        lines.append("")
    lines += [
        "处理建议：",
        "· 若日志提示「发送频繁 / 稍后再试 / 服务器繁忙」：属 PushPlus 频率限制，"
        "稍等片刻后在 Actions 重跑一次即可；",
        "· 若提示「发送次数已达上限 / 已用完」：今日 PushPlus 额度已耗尽，次日零点恢复，"
        "或在 PushPlus 升级套餐后更新 Secrets；",
        "· 若提示 token 无效 / 已失效：到 pushplus.plus 重新获取，"
        "并更新仓库 Settings → Secrets → PUSHPLUS_TOKEN；",
        "· 若日报被拆成多条推送（标题带 1/N、2/N…）：任意一条失败就会停止后续条，"
        "微信里只有前几条；重跑一次即可重新完整推送（Actions 手动运行或 manual_push.sh）；",
        "· 手动重新推送：Actions → 🐙 章鱼AI · 手动抓取推送 → Run workflow，"
        "或本地 ./output/manual_push.sh --force。",
        f"报告文件：{os.path.basename(report_path) if report_path else '—'}",
    ]
    return "\n".join(lines)


def push_failure_alert(reason, data=None, report_path=None, token=None):
    """日报推送失败后的兜底告警（template=txt）。

    返回 True/False；本告警只负责「让微信侧感知失败」，不改变调用方的退出码——
    日报未送达，调用方仍应以退出码 1 结束（Actions 显红）。"""
    print("📣 正在发送「推送失败」兜底告警（让微信侧也能看到失败原因）...")
    title = f"🐙 日报推送失败提醒 {datetime.now(CST).strftime('%m/%d %H:%M')}"
    return push_to_wechat(title, build_push_failure_alert_text(reason, data, report_path),
                          token=token, template="txt")


# ============================================================
# 文件保存
# ============================================================
def _atomic_write(path, content):
    """原子替换文件，避免定时任务被中断后留下旧文件或半个 HTML。"""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _unique_report_path(requested_path):
    """返回不重复的 HTML 路径。

    自动和手动运行都可能在同一天执行多次；日报不能因同名而覆盖上一份。
    冲突时统一追加澳门日期（YYYYMMDD）和三位随机数，例如：
    ``daily_report_20260802_417.html``。循环检查可避免随机数碰撞。
    """
    if not os.path.exists(requested_path):
        return requested_path

    directory = os.path.dirname(os.path.abspath(requested_path))
    extension = os.path.splitext(requested_path)[1] or ".html"
    stem = os.path.splitext(os.path.basename(requested_path))[0]
    date = _today_str()
    for _ in range(1000):
        suffix = f"{random.SystemRandom().randint(0, 999):03d}"
        candidate = os.path.join(directory, f"{stem}_{date}_{suffix}{extension}")
        if not os.path.exists(candidate):
            return candidate

    raise RuntimeError(f"无法为 {requested_path} 找到不重复的日期随机文件名")


def _timestamped_report_path():
    """目标文件被锁定/不可覆盖时使用的全新日期随机文件名。"""
    directory = os.path.abspath(REPORT_DIR)
    date = _today_str()
    for _ in range(1000):
        suffix = f"{random.SystemRandom().randint(0, 999):03d}"
        candidate = os.path.join(directory, f"daily_report_{date}_{suffix}.html")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError("无法为锁定的日报找到不重复的日期随机文件名")


def newest_report_path():
    """返回实际最后更新的一份日报，不依赖可能被锁住的 latest.html。"""
    reports = glob.glob(os.path.join(REPORT_DIR, "daily_report_*.html"))
    return max(reports, key=os.path.getmtime) if reports else None


def save_report(html, output_path=None, data=None):
    """保存本次报告；同名或无法覆盖时创建日期+三位随机数的新 HTML。"""
    requested_path = output_path or os.path.join(REPORT_DIR, f"daily_report_{_today_str()}.html")
    # 先检查文件名是否已存在，避免自动/手动重复运行覆盖既有日报。
    target_path = _unique_report_path(requested_path)
    if target_path != requested_path:
        print(f"⚠️ 输出文件已存在: {requested_path}")
        print(f"   本次改用不重复文件: {target_path}")

    try:
        _atomic_write(target_path, html)
        output_path = target_path
        print(f"💾 日报已原子保存: {output_path}")
    except OSError as exc:
        # 文件在检查后被其它进程锁定或抢先创建时，再生成一个日期随机文件。
        output_path = _timestamped_report_path()
        try:
            _atomic_write(output_path, html)
        except OSError as fallback_exc:
            raise RuntimeError(f"无法保存日报（原路径: {exc}；新日期文件: {fallback_exc}）") from fallback_exc
        print(f"⚠️ 无法写入 {target_path}: {exc}")
        print(f"💾 已改存为新的日期文件: {output_path}")

    latest_path = os.path.join(REPORT_DIR, "latest.html")
    try:
        _atomic_write(latest_path, html)
        print(f"💾 最新副本已同步: {latest_path}")
    except OSError as exc:
        # 推送时始终从 output_path 重读，latest 锁定不会导致推送昨天的内容。
        print(f"⚠️ 无法更新 {latest_path}: {exc}")
        print(f"   本次推送将直接使用最新生成文件: {output_path}")

    available = sum(1 for item in (data or {}).values()
                    if isinstance(item, dict) and item.get("status") == "success")
    total = sum(1 for item in (data or {}).values() if isinstance(item, dict))
    print(f"📊 数据源状态: {available}/{total} 可用（不可用项已在报告中标注）")
    return output_path


# ============================================================
# 列出日报
# ============================================================
def list_reports():
    """列出所有已生成的日报文件"""
    pattern = os.path.join(REPORT_DIR, "daily_report_*.html")
    files = sorted(glob.glob(pattern), reverse=True)

    if not files:
        print("暂无日报文件。")
        return 0

    print(f"\n共找到 {len(files)} 份日报：\n")
    for idx, filepath in enumerate(files, 1):
        filename = os.path.basename(filepath)
        size = os.path.getsize(filepath)
        mtime = datetime.fromtimestamp(os.path.getmtime(filepath), CST)
        print(f"  {idx:2d}. {filename}  ({size:,} 字节)  [{mtime.strftime('%Y-%m-%d %H:%M')}]")
    return 0


# ============================================================
# 清理旧的 HTML 报告
# ============================================================
def clean_old_html_reports(keep_latest=False):
    """清理 output/ 目录下的所有旧 HTML 报告（daily_report_*.html + latest.html）。

    在手动/自动推送前调用，确保本次生成的日报是"最新且唯一"的内容，
    避免历史残留文件（特别是含旧版本特征的报告）被误推或被 latest.html 引用。

    参数:
        keep_latest: True 时保留 latest.html（仅清 daily_report_*.html）；
                     默认 False：两个都清。
    返回:
        (删除的 daily_report 数, 是否删了 latest.html)
    """
    deleted = 0
    latest_deleted = False

    # 1) 清理 daily_report_*.html
    pattern = os.path.join(REPORT_DIR, "daily_report_*.html")
    for filepath in glob.glob(pattern):
        try:
            os.remove(filepath)
            deleted += 1
        except OSError as exc:
            print(f"⚠️ 清理失败: {filepath} ({exc})")

    # 2) 清理 latest.html（除非显式保留）
    latest_path = os.path.join(REPORT_DIR, "latest.html")
    if not keep_latest and os.path.isfile(latest_path):
        try:
            os.remove(latest_path)
            latest_deleted = True
        except OSError as exc:
            print(f"⚠️ 清理失败: {latest_path} ({exc})")

    if deleted or latest_deleted:
        parts = []
        if deleted:
            parts.append(f"{deleted} 份 daily_report_*.html")
        if latest_deleted:
            parts.append("latest.html")
        print(f"🧹 已清理历史 HTML 报告: {', '.join(parts)}")
    return deleted, latest_deleted


# ============================================================
# 推送前的当天内容检验
# ============================================================
def check_push_eligibility(data):
    """根据采集结果判断是否允许推送。

    返回 (can_push, reason)。
    规则：
      - 没有任何来源抓到内容 → 不推送；
      - 有内容但没有任何来源属于「当天」→ 不推送（防旧内容）；
      - 否则可推送。
    """
    items = [v for v in data.values() if isinstance(v, dict)]
    content_n = sum(1 for v in items if v.get("status") == "success")
    today_n = sum(1 for v in items if v.get("is_today"))
    total = len(items)

    if content_n == 0:
        return False, f"全部数据源均未抓到内容（0/{total}）"
    if today_n == 0:
        return False, f"抓到 {content_n}/{total} 个来源，但没有一个属于当天内容（当天检验未通过）"
    snapshots = sum(1 for v in items if v.get("snapshot"))
    suffix = f"（其中 {snapshots} 个仅为今日抓取快照，非当日发布）" if snapshots else ""
    return True, f"当天检验通过：{today_n}/{total} 个来源含当天内容或今日抓取快照{suffix}"


# ============================================================
# 主函数
# ============================================================
def quant_only_report(*, enable_stocks=True):
    """只跑港股量化引擎并打印结果（研究 / 排障用，不生成日报、不推送）。"""
    print("🐙 " + "=" * 48)
    print("   章鱼 AI · 港股量化引擎（研究模式）")
    print("🐙 " + "=" * 48)
    res = _quant.run_quant(
        safe_request,
        history_path=os.path.join(REPORT_DIR, QUANT_HISTORY_FILENAME),
        enable_stocks=enable_stocks)
    if not res.get("available"):
        print(f"❌ 量化引擎不可用：{res.get('reason')}")
        return 1

    head = res.get("headline") or {}
    print(f"\n【预测概括】{head.get('text', '—')}")
    print(f"【数据基准】{res.get('as_of')} → 目标 {res.get('target_label')}")

    print("\n【指数概率】")
    print(f"  {'标的':<8}{'现价':>12}{'1日':>8}{'5日':>8}{'20日':>8}{'样本':>7}{'趋势':>10}")
    for row in res["indices"]:
        p = row["probs"]
        fmt = lambda v: f"{v*100:5.1f}%" if v is not None else "    —"
        print(f"  {row['label']:<8}{row['feat']['close']:>12,.0f}"
              f"{fmt(p[1]['p_up']):>8}{fmt(p[5]['p_up']):>8}{fmt(p[20]['p_up']):>8}"
              f"{p[5]['samples']:>7}{row['trend']['label']:>10}")

    for h, row in sorted((res.get("validation") or {}).items()):
        if not row:
            continue
        z = row.get("z")
        print(f"\n【{h}日推进式回测】样本 {row['n']} · 命中 {row['hit_rate']*100:.1f}%"
              f" · 基准 {row['base_rate']*100:.1f}%"
              f" · z={z:+.2f}" if z is not None else "")
        if row.get("brier") is not None:
            print(f"  Brier {row['brier']:.3f} · 对数损失 {row.get('log_loss') or 0:.3f}")
        for c in row.get("reliability") or []:
            print(f"  预测 {c['lo']*100:5.1f}–{c['hi']*100:5.1f}%  n={c['n']:<4}"
                  f"  实际 {c['actual']*100:5.1f}%")

    liq = res.get("liquidity") or {}
    if liq.get("available"):
        print("\n【资金流动性】")
        print(f"  综合分 {liq.get('score') or 0:.0f}/100 · {liq.get('label')}")
        print(f"  {liq.get('summary')}")
        for key, label in (("south", "南向"), ("north", "北向")):
            st = liq.get(key) or {}
            if st.get("available"):
                print(f"  {label}：最新 {st['latest']:,.0f} 亿 · 环比 "
                      f"{(st.get('chg_pct') or 0):+.1f}% · 20日均 {st['ma20']:,.0f} 亿"
                      f" · z={(st.get('z20') or 0):+.2f} · {(st.get('date') or '')}")
        for name, comp in (liq.get("components") or {}).items():
            print(f"   · {name:<9} {comp['score']:5.1f} 分（权重 "
                  f"{comp.get('weight', 0)*100:.0f}%） {comp.get('note') or ''}")

    if res.get("stocks"):
        print("\n【个股概率（按 5 日排序）】")
        for row in sorted(res["stocks"], key=lambda r: -((r["probs"][5]["p_up"] or 0))):
            print(f"  {row['label']:<12}{row['probs'][5]['p_up']*100:6.1f}%"
                  f"  综合分 {row['score']:+.2f}  样本 {row['probs'][5]['samples']}")
    jr = res.get("journal") or {}
    if jr.get("n"):
        print(f"\n【预测留痕】已结算 {jr['n']} 次 · 方向命中 "
              f"{(jr.get('hit_rate') or 0)*100:.0f}%")
    print("\n✅ 量化引擎运行完成（研究模式不推送）")
    return 0


def calendar_only_report(days=None):
    """只抓「未来 N 天影响经济时间点」并打印（研究 / 排障用：不生成日报、不推送）。

    用途：本地或 Actions 里单独验证东财财经日历接口是否可读、筛选口径是否合适，
    不必跑完整条采集链路。
    """
    print("🐙 " + "=" * 48)
    print("   章鱼 AI · 未来影响经济时间点（研究模式）")
    print("🐙 " + "=" * 48)
    res = fetch_econ_calendar(days=days)
    if res.get("status") != "success":
        print(f"❌ 财经日历暂缺：{res.get('error')}")
        return 1
    digest = _cal_digest(res)
    print(f"\n【窗口】{res.get('window')}")
    for label, value in digest.get("pairs") or []:
        print(f"【{label}】{value}")
    print(f"\n【逐日时间点】共 {len(res.get('items') or [])} 条（北京时间）")
    for _date, label, t_plus, items in digest.get("days") or []:
        when = _cal_countdown(t_plus)
        print(f"\n  {label}" + (f" · {when}" if when else ""))
        for it in items:
            city = str(it.get("city") or "")
            print(f"    {it.get('time') or '--:--'}  {'★' * int(it.get('imp') or 1):<3} "
                  f"{city:<6}{_cal_item_text(it)}")
    print("\n✅ 财经日历运行完成（研究模式不推送）")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="🐙 章鱼AI · 每日财经日报流水线（当天检验后推送）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 output/pipeline.py                        # 全流程（当天检验通过才推送）
  python3 output/pipeline.py --no-push              # 只生成，不推送
  python3 output/pipeline.py --dry-run              # 采集+预览，不推送
  python3 output/pipeline.py -o custom.html         # 指定输出路径
  python3 output/pipeline.py --manual               # 手动推送模式（重新抓取并推送）
  python3 output/pipeline.py --manual --force-push  # 手动强制推送（内容非当天也推，谨慎）
  python3 output/pipeline.py --push-only            # 推送实际最后更新的一份日报（再次当天检验）
  python3 output/pipeline.py --push-only path/to/report.html
  python3 output/pipeline.py --list                 # 列出日报
  python3 output/pipeline.py --no-quant             # 跳过港股量化引擎（运行更快）
  python3 output/pipeline.py --quant-only           # 只跑量化引擎并打印概率/流动性/回测
  python3 output/pipeline.py --calendar-only        # 只抓未来30天影响经济时间点并打印
  python3 output/pipeline.py --calendar-only 7      # 同上，窗口改成未来 7 天
  python3 output/pipeline.py --theme pixel          # 本次改用旧版像素主题（默认 guizang）
        """
    )

    parser.add_argument("--no-push", action="store_true",
                       help="只生成日报，不推送到微信")
    parser.add_argument("--dry-run", action="store_true",
                       help="采集数据并预览，不生成文件也不推送")
    parser.add_argument("-o", "--output", type=str, default=None,
                       help="指定输出文件路径")
    parser.add_argument("--manual", action="store_true",
                       help="手动推送模式：重新抓取→生成→当天检验→推送")
    parser.add_argument("--force-push", action="store_true",
                       help="当天检验未通过时仍强制推送（谨慎）")
    parser.add_argument("--push-only", nargs="?", const="__LATEST__", default=None,
                       help="推送实际最后更新的日报；也可指定带新鲜度标记的文件（再次执行当天检验）")
    parser.add_argument("--force-push-old", action="store_true",
                       help="允许 --push-only 推送未带新鲜度标记的旧版日报（不推荐）")
    parser.add_argument("--allow-incomplete-push", action="store_true",
                       help="当本次所有数据源均不可用时仍推送状态报告（默认不推送）")
    parser.add_argument("--theme", default=None, choices=list(PUSH_THEMES),
                       help="推送主题：guizang（默认 · 电子杂志×电子墨水）/ pixel（旧版复古像素）")
    parser.add_argument("--list", action="store_true",
                       help="列出已生成的日报")
    parser.add_argument("--no-quant", action="store_true",
                       help="跳过港股量化引擎（只出常规栏目，运行更快）")
    parser.add_argument("--quant-only", action="store_true",
                       help="只跑港股量化引擎并打印结果（研究模式：不生成日报、不推送）")
    parser.add_argument("--calendar-only", nargs="?", const=-1, default=None, type=int,
                       help="只抓「未来 N 天影响经济时间点」并打印（研究模式：不生成日报、不推送；"
                            "不带数字时用 OCTOPUS_CALENDAR_DAYS，默认 30 天）")

    args = parser.parse_args()

    if args.no_quant:
        global HK_QUANT_ENABLED
        HK_QUANT_ENABLED = False

    # --list 模式
    if args.list:
        return list_reports()

    # --quant-only 模式：只跑量化引擎，把概率 / 流动性 / 回测打到控制台
    if args.quant_only:
        return quant_only_report(enable_stocks=HK_QUANT_STOCKS)

    # --calendar-only 模式：只抓未来 N 天影响经济时间点，验证接口与筛选口径
    if args.calendar_only is not None:
        return calendar_only_report(days=None if args.calendar_only < 1 else args.calendar_only)

    # --push-only 模式：推送已有文件，同样执行「当天检验」
    if args.push_only:
        push_path = newest_report_path() if args.push_only == "__LATEST__" else args.push_only
        if not push_path or not os.path.isfile(push_path):
            print(f"❌ 文件不存在: {push_path or '没有可推送的日报'}")
            return 1
        print(f"📎 本次推送 HTML: {push_path}")
        with open(push_path, "r", encoding="utf-8") as f:
            html = f.read()

        meta = _report_meta(html)
        today = _today_str()
        forced = args.force_push or args.force_push_old
        if not meta.get("date") and not forced:
            # 旧版文件：没有「当天检验」元信息，无法确认是否当天 → 默认拒绝
            print("❌ 拒绝推送旧版日报：文件没有当天检验元信息（octopus-report-date）。")
            print("   请先运行 pipeline.py 重新生成，或在确认风险后添加 --force-push / --force-push-old。")
            return 1
        if meta["date"] != today and not forced:
            print(f"❌ 拒绝推送：报告日期 {meta['date']} ≠ 今天 {today}（当天检验未通过）")
            print("   请重新生成，或使用 --force-push 强制推送。")
            return 1
        if meta["today_sources"] < 1 and not forced:
            print(f"❌ 拒绝推送：该日报 {meta['today_sources']}/{meta['total_sources']} 个数据源为当天内容（当天检验未通过）")
            print("   请重新生成，或使用 --force-push 强制推送。")
            return 1

        title = f"🐙 章鱼AI日报 {datetime.now(CST).strftime('%m/%d %H:%M')}"
        if push_to_wechat(title, html, report_name=os.path.basename(push_path)):
            print("\n🎉 全部完成！")
            return 0
        push_failure_alert("通过 --push-only 推送日报被 PushPlus 拒绝（详见上方 code/msg）",
                           report_path=push_path)
        print("\n❌ 推送未成功（退出码 1；在 GitHub Actions 中将标红提醒）。")
        return 1

    # 正常流程
    mode = "🖐 手动推送模式" if args.manual else "每日自动模式"
    theme = _resolve_push_theme(args.theme)
    print("🐙 " + "=" * 48)
    print(f"   章鱼 AI · 全网多模型协同 · 每日财经日报（{mode}）")
    print("🐙 " + "=" * 48)
    print(f"   运行时间: {_now()}")
    print(f"   推送主题: {theme}（OCTOPUS_PUSH_THEME / --theme 可切换）")

    # 0. 清理历史 HTML 报告（手动/自动推送前必做）：
    #    避免历史残留文件（含旧版本特征的报告）被推送或被 latest.html 引用。
    #    --dry-run 不写文件，所以跳过清理。
    if not args.dry_run:
        clean_old_html_reports()

    # 1. 采集数据
    data = collect_all_data()

    # 1.5 情绪历史：加载跨日基线供 AI 新闻情绪因子用（只读；落盘在报告保存后，
    #     --dry-run 只读不写；缺失/损坏按冷启动处理，不中断日报）
    senti_history_path = os.path.join(REPORT_DIR, SENTIMENT_HISTORY_FILENAME)
    senti_history = _load_sentiment_history(senti_history_path)

    # 1.5b 新闻标题存档：加载并把本次抓取标题并入（多日窗口 15 日/72h 的内容基础；
    #     同日重复运行按 日期+标题 去重幂等；读取失败只告警。落盘在报告保存后；
    #     --dry-run 只读不写）
    news_history_path = os.path.join(REPORT_DIR, NEWS_HISTORY_FILENAME)
    date_str = _today_str()
    fresh_items = _collect_headline_items(data, _today_display())
    news_corpus = _merge_news_corpus(_load_news_corpus(news_history_path), fresh_items)

    # 1.6 政策因子：抓取后、推送前单独做政策冲击分析（推送页首位栏目；
    #     近 POLICY_WINDOW_DAYS=15 日窗口内无政策/宏观新闻时栏目缺席，不伪造）
    policy_result = build_policy_factor(data, date_str, news_corpus)
    if policy_result.get("available"):
        print(f"  📊 政策因子：{policy_result['summary']}")
    else:
        print(f"  📊 政策因子：近{POLICY_WINDOW_DAYS}日窗口内无显著政策新闻，首位栏目缺席")

    # 2. 生成报告
    print("\n📝 正在生成日报...")
    date_display = _date_display()
    html = generate_report(data, date_display, date_str, theme=theme,
                           sentiment_history=senti_history,
                           policy_result=policy_result,
                           news_corpus=news_corpus)
    print("  ✅ 日报生成完成")

    # 3. dry-run 模式
    if args.dry_run:
        print("\n🔍 预览模式（不推送、不保存）")
        print(f"   数据源: 港股名家频道({len(data.get('港股名家频道', {}).get('channels', []))}频道可抓取) | "
              f"全球头条({len(data.get('全球头条', {}).get('headlines', []))}条) | "
              f"A股({len(data.get('A股资讯', {}).get('headlines', []))}条) | "
              f"东财快讯({len(data.get('东财快讯', {}).get('headlines', []))}条) | "
              f"热门榜({sum(len(m.get('stocks', [])) for m in data.get('热门榜单', {}).get('markets', {}).values())}只)")
        return 0

    # 4. 保存文件
    output_path = save_report(html, args.output, data)
    # 4.5 历史落盘：把今日个股情绪计数并入跨日基线、把本次标题并入标题存档
    #     （同日多次运行按日期键/日期+标题覆盖去重，幂等；失败只告警，不影响推送）
    try:
        senti_today = build_news_sentiment(data, date_str, senti_history,
                                           news_corpus=news_corpus)
        _save_sentiment_history(
            senti_history_path,
            _update_sentiment_history(senti_history, date_str,
                                      senti_today["universe"],
                                      senti_today["today_counts"]))
    except OSError as exc:
        print(f"  ⚠️ 情绪历史保存失败（{exc}），不影响本次日报与推送")
    try:
        anchor_date = _factor_anchor_dt(date_str).strftime("%Y-%m-%d")
        _save_news_corpus(news_history_path,
                          _prune_news_corpus(news_corpus, anchor_date))
    except OSError as exc:
        print(f"  ⚠️ 新闻标题存档保存失败（{exc}），不影响本次日报与推送")
    # 必须从刚保存的路径读取，避免 latest.html 被锁定时推送到旧副本。
    with open(output_path, "r", encoding="utf-8") as f:
        push_html = f.read()

    # 5. 推送决策：先做「当天内容检验」，再决定是否推送。
    #    约定：任何「应当推送却失败」的情况都返回退出码 1（GitHub Actions 将标红），
    #    不再出现“推送失败但 workflow 显示成功”的静默问题。
    can_push, reason = check_push_eligibility(data)

    def _finish(ok, ok_msg="🎉 全部完成！",
                fail_msg="❌ 流程完成，但推送未成功（见上方原因；Actions 将标红提醒）"):
        print(f"\n{ok_msg if ok else fail_msg}")
        return 0 if ok else 1

    if args.no_push:
        print(f"\n⏭️ 已跳过推送（--no-push）。当天检验: {reason}")
        print(f"   日报已保存: {output_path}")
        return _finish(True)

    if can_push:
        print(f"\n📤 当天检验通过：{reason}")
        title = f"🐙 章鱼AI日报 {datetime.now(CST).strftime('%m/%d %H:%M')}"
        print(f"📎 正在推送本次生成的 HTML: {output_path}")
        if push_to_wechat(title, push_html, report_name=os.path.basename(output_path)):
            return _finish(True)
        # 日报推送失败：再发一条纯文本失败告警，微信侧能直接看到原因；退出码仍为 1。
        push_failure_alert("日报 HTML 多次推送均被 PushPlus 拒绝（详见上方 code/msg）",
                           data=data, report_path=output_path)
        return _finish(False)

    if args.force_push:
        print(f"\n⚠️ 当天检验未通过，但检测到 --force-push，强制推送！")
        print(f"   原因: {reason}")
        title = f"🐙 章鱼AI日报(强制) {datetime.now(CST).strftime('%m/%d %H:%M')}"
        if push_to_wechat(title, push_html, report_name=os.path.basename(output_path)):
            return _finish(True)
        push_failure_alert("强制推送的日报被 PushPlus 拒绝（详见上方 code/msg）",
                           data=data, report_path=output_path)
        return _finish(False)

    if args.allow_incomplete_push:
        print(f"\n⚠️ 全部数据源不可用，但检测到 --allow-incomplete-push，推送状态报告。")
        print(f"   原因: {reason}")
        title = f"🐙 章鱼AI日报(状态) {datetime.now(CST).strftime('%m/%d %H:%M')}"
        if push_to_wechat(title, push_html, report_name=os.path.basename(output_path)):
            return _finish(True)
        push_failure_alert("状态报告推送被 PushPlus 拒绝（详见上方 code/msg）",
                           data=data, report_path=output_path)
        return _finish(False)

    # 当天检验未通过且不强制：不推日报，但推一条纯文本告警，避免彻底沉默。
    print(f"\n⏸️ 当天检验未通过，本次不推送日报。")
    print(f"   原因: {reason}")
    print("   日报已保存（带状态标记），可在确认后使用:")
    print("     python3 output/pipeline.py --manual --force-push   # 强制手动推送")
    print("     python3 output/pipeline.py --push-only output/latest.html")
    if push_no_push_alert(reason, data, output_path):
        return _finish(True, ok_msg="🎉 全部完成（日报未推，已发出检验未通过告警）！")
    print("   ⚠️ 告警也发送失败。若是 token 未配置/失效，本次将以失败结束以便在 Actions 中发现。")
    return _finish(False)


if __name__ == "__main__":
    sys.exit(main())
