"""【散户群体情绪因子·量化策略分析】日报栏目（策略部分，2026-10-10 新增）。

内容来源：仓库根目录 `散户情绪因子-量化策略分析.md` 的「2/策略如下」部分（原文逐条保留，
仅把公式改写为可在微信里直接阅读的纯文字）。纯静态文本：不抓取、不计算、不调用外部服务，
因此不进入数据审计 / 当天源统计，也不影响推送门禁。

栏目位置：由 pipeline._collect_report_parts 固定插在「AI 全篇速览（导读）」之后、
正文第一栏之前，四套主题（pixel / guizang / forum / dossier）共用同一份数据。

渲染只使用 kit 提供的原语（kv / sub / esc），因此同一份内容自动适配各主题的配色与字号；
入门版（PLAIN）下不会被「说明文字」开关删除——这是栏目本身的正文。
"""

SECTION_KICKER = "RETAIL SENTIMENT"
SECTION_TITLE = "散户群体情绪因子·量化策略分析"
SECTION_CAPTION = "策略框架 · 非投资建议"

INTRO = (
    "散户群体情绪因子（Retail Sentiment Factors）是量化投资与行为金融学中非常关键的非结构化 alpha 因子。"
    "由于散户行为具有显著的羊群效应（Herd Behavior）、过度反应与反应不足、高频换手以及对舆论热点高度敏感等特征，"
    "对散户情绪进行因子化提取，在反向指标预测（反向 Alpha）、波动率预测、流动性溢价评估及小盘股选股中具有极高价值。"
)

# 一、数据源与构建路线：每组为 (小标题, [(项目, 说明), ...])
SOURCES_INTRO = (
    "构建散户情绪因子主要依赖两类数据：文本/社交媒体数据（显式情绪）和市场交易微观结构数据（隐式情绪）。"
)
SOURCES_EXPLICIT = [
    ("显式 · 数据来源",
     "国内：东方财富股吧、雪球社区、新浪财经微博、淘股吧、贴吧。"
     "国外：Reddit (r/wallstreetbets)、StockTwits、Twitter/X。"),
    ("显式 · 词频/字典法",
     "基于金融情感词典（如 Loughran-McDonald 词典或中文金融专属字典），统计看多/看空词汇频率。"),
    ("显式 · 深度学习/大模型",
     "使用 FinBERT、RoBERTa 或微调的大语言模型（LLM），对帖子/评论进行多标签分类（看涨、看跌、焦虑、追涨等），"
     "计算每日或每小时的净看涨情绪指数（Net Bullishness Index）。"
     "若模型仅输出看多/看空二分类，或剔除了中性帖子：NBI = (Pos − Neg) ÷ (Pos + Neg)；"
     "或使用对数形式（降低极端爆流量带来的扰动）：NBI-Log = ln((1 + Pos) ÷ (1 + Neg))。"
     "Pos、Neg 分别为股票 i 在第 t 日（或小时）的看多、看空帖子数。"),
    ("显式 · 热度/讨论量",
     "统计某只股票在特定时间窗口内的发帖量、发帖增量增速（Spike Detector），即 Attention Factor。"),
]
SOURCES_IMPLICIT = [
    ("隐式 · 小单净买入占比",
     "基于逐笔成交数据（Tick Data），按单笔成交金额划分（如 4 万元以下为小单/散户单），"
     "计算小单净买入金额占总成交额的比率（Small Order Net Flow）。"),
    ("隐式 · 开户数与保证金",
     "新增开户数、证券结算资金净流入（宏观/行业层面的散户情绪）。"),
    ("隐式 · 融资买入比例",
     "散户为主导的融资买入额占总成交额比重（Margin Trading Intensity）。"),
    ("隐式 · 挂单偏离度",
     "散户倾向于挂不理性的深买/深卖单（Limit Order Disparity）。"),
]

# 二、常用散户情绪因子定义与逻辑：每个因子 (名称, 构造原理, 行为金融学解释, 常见应用/作用机制)
FACTORS = [
    ("散户注意力爆发因子 (Attention Spike)",
     "发帖量(t) ÷ 近 20 日发帖量均值（t-20 至 t-1）",
     "散户对突发新闻/热点的过度反应（Overreaction）",
     "短期促使股价剧烈波动，中长期往往面临均值回归（Mean Reversion）。"),
    ("社区净看涨倾向 (Net Sentiment Score)",
     "(看多帖子数 − 看空帖子数) ÷ 总帖子数",
     "散户群体的乐观/悲观共识度",
     "高看涨情绪配合低成交量往往是顶部反向信号。"),
    ("小单资金持续净流入 (Small-Order Flow Continuity)",
     "连续 N 日小单净买入占比的加权均值",
     "散户盲目追涨或“抄底陷阱”",
     "连续高额小单买入往往对应机构出货，通常为负向选股因子。"),
    ("论坛讨论分歧度 (Sentiment Dispersion)",
     "论坛帖子情绪看涨/看跌的标准差/熵",
     "市场对该股存在严重分歧（Divergence of Opinion）",
     "高分歧通常伴随高波动率和更高的换手率。"),
]

# 三、特征与反向指标特性
CHARACTER_INTRO = "散户情绪因子在实际量化应用中，最核心的规律在于“时间粒度决定方向”："
CHARACTER = [
    ("超短期（1~3 日）· 顺向动量效应（Momentum）",
     "在情绪刚被点燃的初期（例如突然爆出热点或涨停），散户情绪具有强烈的追涨效应，"
     "推动股价在 1~3 天内继续上涨（羊群效应驱动的自我实现）。"),
    ("中长期（1~4 周）· 显著的反向均值回归（Reversal / Contrarian Signal）",
     "当散户情绪达到极值（绝对看多或散户资金高度集中流入）时，通常意味着潜在买方枯竭或机构主力正在趁高出货。"),
    ("实践结论",
     "在日频或周频策略中，高散户看涨情绪因子往往与未来收益率呈显著负相关（即散户指标用作反向指标）。"),
]

# 四、构建与使用的注意事项
CAUTIONS = [
    ("噪声过滤与水军/机器人识别（Bot Detection）",
     "社交媒体上存在大量配资广告、水军刷屏、自动发帖机器人。构建文本因子前，必须经过严格的去重、垃圾过滤和用户权重赋予"
     "（如按注册时长、粉丝数、历史准确率赋权）。"),
    ("结合机构情绪与资金流向交叉验证",
     "散户情绪因子在与机构资金流向（如大单/特大单净买入）或 smart money 因子结合使用时效果最佳。"
     "典型多空信号：散户极度看多 + 机构资金大额净卖出 = 极强卖出信号。"),
    ("市值敏感性（Market Cap Bias）",
     "散户情绪因子在小盘股、高换手率股、散户持股比例高的股票中 IC（信息系数）显著较高；"
     "在机构重仓的大盘股中，散户情绪对股价的影响力被大幅稀释。"),
    ("衰减速度极快（High Decay Rate）",
     "舆论热点和散户情绪的变化极快，因子换手率非常高。在扣除交易费率和冲击成本后，需评估其纯 Alpha 收益。"),
]

# 五、总结与典型量化应用
APPLICATIONS = [
    ("应用场景 1（选股/Alpha）",
     "作为反向因子，剔除散户情绪过于狂热（小单净买入占比处于前 5% 且论坛讨论度爆表）的标的。"),
    ("应用场景 2（择时/Timing）",
     "当全市场散户情绪指标（如全市场融资买入占比、论坛全盘情绪）达到历史 95% 分位数时，降低策略总体仓位。"),
    ("应用场景 3（风险/波动率预测）",
     "散户高分歧度（Sentiment Dispersion）可作为预测未来 5-10 日股票日内波动率上升的有效前瞻指标。"),
]


def _line(kit, label, text):
    """一条条目：加粗小标题 + 说明文字，转义后用 <br> 连接（同一行表格内换行）。"""
    return f"<b>{kit.esc(label)}</b>：{kit.esc(text)}"


def _lines(kit, pairs):
    return "<br>".join(_line(kit, label, text) for label, text in pairs)


def _body(kit, html):
    """键值表的值列统一左对齐（像素主题默认右对齐，长段落需要左对齐）。"""
    return f'<div style="text-align:left;">{html}</div>'


def _rows(kit, pairs):
    """多条说明压成一张键值表（每行一个 kit 行，减少重复的表格样式）。"""
    return kit.kv([(kit.esc(label), _body(kit, kit.esc(text))) for label, text in pairs])


def build_section(kit):
    """返回与 pipeline 栏目元组同构的 (kicker, title, content, badge, caption)。"""
    esc = kit.esc
    parts = [
        kit.kv([(esc("总述"), _body(kit, esc(INTRO)))]),
        kit.sub(esc("一、散户情绪因子的数据源与构建路线")),
        kit.kv([
            (esc("概述"), _body(kit, esc(SOURCES_INTRO))),
            (esc("显式情绪"), _body(kit, _lines(kit, SOURCES_EXPLICIT))),
            (esc("隐式情绪"), _body(kit, _lines(kit, SOURCES_IMPLICIT))),
        ]),
        kit.sub(esc("二、常用散户情绪因子定义与逻辑")),
    ]
    parts.append(kit.kv([
        (esc(name), _body(kit, esc("构造：" + build) + "<br>" + esc("解释：" + meaning)
                          + "<br>" + esc("作用：" + usage)))
        for name, build, meaning, usage in FACTORS
    ]))
    parts.append(kit.sub(esc("三、散户情绪因子的特征与反向指标特性")))
    parts.append(kit.kv([(esc("核心规律"), _body(kit, esc(CHARACTER_INTRO)))]
                        + [(esc(label), _body(kit, esc(text))) for label, text in CHARACTER]))
    parts.append(kit.sub(esc("四、构建与使用散户情绪因子的注意事项")))
    parts.append(_rows(kit, CAUTIONS))
    parts.append(kit.sub(esc("五、总结与典型量化应用")))
    parts.append(_rows(kit, APPLICATIONS))
    content = "".join(p for p in parts if p)
    return (SECTION_KICKER, SECTION_TITLE, content, "", SECTION_CAPTION)
