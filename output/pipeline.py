def generate_report(data, date_display, date_str):
    wsb = data.get("Reddit WSB热议", {})
    wsb_stocks = wsb.get("stocks", [])
    yahoo = data.get("Yahoo头条", {})
    yh_headlines = yahoo.get("headlines", [])
    sina = data.get("A股资讯", {})
    sina_headlines = sina.get("headlines", [])
    kospi = data.get("韩股半导体", {})
    kospi_headlines = kospi.get("headlines", [])

    # WSB 榜单
    medals = ["🥇","🥈","🥉","④","⑤","⑥","⑦","⑧","⑨","⑩"]
    wsb_rows = []
    for i, s in enumerate(wsb_stocks[:10]):
        label = f"{medals[i]} {s.get('symbol','?')} {s.get('name','')}"
        wsb_rows.append((label, f"{s.get('mentions','?')} 次提及"))

    # 话题标签
    topics = [
        "Fed利率决议", "微软财报", "Meta财报",
        "30年期国债", "中东局势", "原油大涨",
        "存储半导体", "滞胀预期", "核心PCE",
        "AI资本开支", "苹果财报", "亚马逊财报",
    ]

    # Yahoo 头条列表
    yh_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">📰 {_esc(h[:120])}</div>'
        for h in yh_headlines[:8]
    ) if yh_headlines else '<div style="font-size:13px;color:#888;">暂无实时数据</div>'

    # 韩股资讯列表
    kospi_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">🇰🇷 {_esc(h[:120])}</div>'
        for h in kospi_headlines[:5]
    ) if kospi_headlines else '<div style="font-size:13px;color:#888;">暂无实时数据</div>'

    # A股资讯列表
    sina_items = "".join(
        f'<div style="font-size:13px;padding:3px 0;border-bottom:1px dashed {C_DASH};color:{C_BLUE};">🇨🇳 {_esc(h[:120])}</div>'
        for h in sina_headlines[:5]
    ) if sina_headlines else '<div style="font-size:13px;color:#888;">暂无实时数据</div>'

    # ========== 逐个拼接卡片内容，避免f-string嵌套 ==========
    # 1. 行情速览卡片
    card_market = _card("⚡", "行情速览", 
        _alert("Fed维持利率 · 长债收益率新高 · 地缘局势紧张") +
        _data_table([
            ("道琼斯指数", '<span style="color:#d93025;">51,618 -2.19%</span>', C_RED),
            ("标普500", '<span style="color:#d93025;">7,317 -1.52%</span>', C_RED),
            ("纳斯达克", '<span style="color:#d93025;">24,460 -1.74%</span>', C_RED),
            ("30年期国债", '<span style="color:#d93025;">5.24% 2007年新高</span>', C_RED),
            ("WTI原油", '<span style="color:#d93025;">$84.9 +7.2%</span>', C_RED),
            ("核心PCE同比", '<span style="color:#188038;">3.3% 低于预期</span>', C_GREEN),
        ]) +
        _vs_box("微软 MSFT", "+11%", "Azure营收破千亿<br>AI业务增长123%", "Meta META", "-9%", "EPS不及预期<br>自由现金流暴跌91%") +
        _note("<b>市场共识</b>：AI行情分化加剧，有盈利兑现的标的走强，纯烧钱模式承压。关注晚间苹果、亚马逊财报。")
    )

    # 2. 全球头条卡片
    card_yahoo = _card("📰", "全球头条", yh_items)

    # 3. 半导体&韩股卡片
    card_semi = _card("🔌", "半导体&韩股",
        _alert("存储周期分歧加剧，三星盈利创新高", C_GREEN, C_ALERT_G) +
        _mini_table([
            ("KOSPI指数", '<span style="color:#d93025;">5,594 -1.23%</span>'),
            ("三星电子", '<span style="color:#188038;">+0.7% 利润+1814%</span>'),
            ("SK海力士", '<span style="color:#d93025;">-5.6% 三日跌27%</span>'),
            ("费城半导体SOX", '<span style="color:#d93025;">-20% 进入熊市</span>'),
        ]) +
        kospi_items +
        _note("韩国收紧杠杆ETF监管，防范市场过度波动；存储板块估值处于历史低位，需关注需求复苏节奏。")
    )

    # 4. WSB热议卡片
    card_wsb = _card("🐂", "Reddit WSB热议",
        f'<div style="font-size:13px;color:#888;padding-bottom:4px;">过去24小时美股散户讨论热度</div>' +
        _section_title("Top 10 提及榜", 15) +
        _mini_table(wsb_rows) +
        _section_title("热门话题") +
        f'<div style="margin:4px 0;line-height:28px;">{_tags_html(topics)}</div>' +
        _note("<b>散户情绪</b>：资金从高位AI标的分流，转向周期复苏和防御板块，做空情绪有所上升。")
    )

    # 5. A股卡片
    card_astock = _card("🇨🇳", "A股市场",
        _data_table([
            ("上证指数", '<span style="color:#188038;">3,813 +0.40%</span>', C_GREEN),
            ("深证成指", '<span style="color:#188038;">+1.10%</span>', C_GREEN),
            ("创业板指", '<span style="color:#188038;">+1.55%</span>', C_GREEN),
            ("科创50", '<span style="color:#d93025;">-0.87%</span>', C_RED),
            ("两市成交额", "2.31万亿元"),
        ]) +
        sina_items +
        _note("大消费板块领涨，乳业、食品饮料表现强势；半导体板块承压，科创50逆势下跌。")
    )

    # 6. 今日关注卡片
    card_focus = _card("🎯", "今日关注",
        _mini_table([
            ("重点财报", "苹果 AAPL · 亚马逊 AMZN（盘后）"),
            ("经济数据", "美国非农就业数据 · 初请失业金"),
            ("地缘事件", "中东局势进展 · 原油供应变化"),
            ("央行动态", "美联储官员讲话 · 降息预期变化"),
            ("技术关口", "纳指关键支撑位 · 美债收益率走势"),
        ]) +
        _note("<b>操作建议</b>：财报季波动加大，控制仓位，关注业绩兑现能力，规避纯题材炒作标的。")
    )

    # ========== 最终组装HTML ==========
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>章鱼AI·全景日报</title>
</head>
<body style="margin:0;padding:0;background:#f0f0f0;font-family:{FONT};color:#002FA7;font-size:15px;line-height:1.75;-webkit-text-size-adjust:100%;">

<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;max-width:600px;margin:0 auto;background:#f0f0f0;">
<tr><td style="padding:10px;">

<!-- 头部 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#002FA7;">
<tr><td style="padding:16px 14px 4px;text-align:center;color:#fff;font-size:13px;">🐙 Octopus AI · 全景分析</td></tr>
<tr><td style="padding:0 14px 4px;text-align:center;color:#fff;font-size:20px;font-weight:700;">每日财经日报</td></tr>
<tr><td style="padding:0 14px 12px;text-align:center;color:#fff;font-size:12px;">{_esc(date_display)} · 自动生成</td></tr>
<tr><td style="padding:0 14px 14px;text-align:center;">
<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">全球市场</span>
<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">AI科技</span>
<span style="display:inline-block;background:rgba(255,255,255,.2);padding:2px 8px;margin:2px;font-size:11px;color:#fff;">{_esc(_now())}</span>
</td></tr>
</table>

{card_market}
{card_yahoo}
{card_semi}
{card_wsb}
{card_astock}
{card_focus}

<!-- 页脚 -->
<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;background:#fff;">
<tr><td style="padding:12px 10px;text-align:center;">
<div style="font-size:11px;color:#8899c0;line-height:1.8;">
🐙 章鱼AI · 仅供参考，不构成投资建议<br>
数据来源：Reddit · Yahoo · 新浪财经 · TradingKey
</div>
<div style="font-size:10px;color:#99aacc;margin-top:4px;line-height:1.6;">
生成时间：{_now()}
</div>
</td></tr>
</table>

</td></tr>
</table>
</body>
</html>'''

    return html
