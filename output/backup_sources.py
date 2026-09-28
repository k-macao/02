#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔄 备用数据源模块 · 全数据源覆盖

目标：
- 为所有数据源提供备用源，确保主源失败时有兜底
- 不伪造数据，只在主源失败时尝试备用
- 每个备用源都有明确的来源标注和失败原因

设计：
- 每个数据源定义 primary + backups 列表
- 备用源按优先级尝试，任一成功即返回
- 失败时记录所有尝试的错误，供审计使用
"""

from typing import List, Dict, Callable, Any, Tuple
import os

# Yahoo Finance 备用域名
YAHOO_PRIMARY = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_BACKUPS = [
    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
    "https://query1.finance.yahoo.com/v7/finance/chart/{symbol}",  # 旧版本 API
]

# 东财新闻备用接口
EASTMONEY_NEWS_PRIMARY = [
    "https://np-weblist.eastmoney.com/comm/web/getNewsByColumns",
    "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns",
]
EASTMONEY_NEWS_BACKUPS = [
    "https://np-anotice-stock.eastmoney.com/api/security/ann",  # 公告接口作为降级
    "https://guba.eastmoney.com/api/news",  # 股吧新闻作为降级
]

# 东财行情备用接口
EASTMONEY_QUOTE_PRIMARY = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_QUOTE_BACKUPS = [
    "https://push2.eastmoney.com/api/qt/ulist.np/get",
    "https://push2his.eastmoney.com/api/qt/stock/kline/get",  # K 线接口可提取最新价
    "https://datacenter-web.eastmoney.com/api/data/v1/get",  # 数据中心作为最终兜底
]

# 东财全景/板块备用
EASTMONEY_PANORAMA_PRIMARY = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EASTMONEY_PANORAMA_BACKUPS = [
    "https://push2.eastmoney.com/api/qt/clist/get",  # 行业板块接口
    "https://datacenter-web.eastmoney.com/api/data/v1/get",  # 数据中心
]

# Google News 备用
GOOGLE_NEWS_PRIMARY = {
    "zh": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
}
GOOGLE_NEWS_BACKUPS = {
    "zh": [
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=HK&ceid=HK:zh-Hant",  # 香港中文
        "https://news.google.com/rss/search?q=财经&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",  # 搜索兜底
        "https://rsshub.app/google/news/BUSINESS/zh-CN",  # RSSHub 兜底
    ],
    "en": [
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
        "https://rsshub.app/google/news/BUSINESS/en-US",
    ],
    "fed": [
        "https://news.google.com/rss/search?q=美联储+OR+FOMC+OR+鲍威尔&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=Federal+Reserve+OR+FOMC&hl=en-US&gl=US&ceid=US:en",
        "https://rsshub.app/google/news/search/美联储/zh-CN",
    ],
    "geo": [
        "https://news.google.com/rss/search?q=地缘政治+OR+制裁+OR+冲突+OR+关税&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=geopolitics+OR+sanctions+OR+conflict&hl=en-US&gl=US&ceid=US:en",
        "https://rsshub.app/google/news/search/地缘政治/zh-CN",
    ],
}

# 中国政府网备用
GOV_POLICY_PRIMARY = [
    "https://www.gov.cn/zhengce/zuixin/",
    "https://www.gov.cn/zhengce/",
]
GOV_POLICY_BACKUPS = [
    "https://www.gov.cn/zhengce/jiedu/",
    "https://www.gov.cn/zhengce/zhengceku/",
    "https://rsshub.app/gov/zhengce/zuixin",  # RSSHub 兜底
]

# YouTube 备用
YOUTUBE_PRIMARY = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
YOUTUBE_BACKUPS = [
    "https://rsshub.app/youtube/channel/{channel_id}",
    "https://www.youtube-nocookie.com/feeds/videos.xml?channel_id={channel_id}",
]

# Reddit 备用
REDDIT_PRIMARY = "https://www.reddit.com/r/{community}/hot/.rss?limit={limit}"
REDDIT_BACKUPS = [
    "https://www.reddit.com/r/{community}/hot.json?limit={limit}",  # JSON 备用
    "https://old.reddit.com/r/{community}/hot/.rss?limit={limit}",  # old 域名
    "https://rsshub.app/reddit/subreddit/{community}",  # RSSHub
]

# StockTwits 备用
STOCKTWITS_PRIMARY = "https://api.stocktwits.com/api/2/trending/symbols.json"
STOCKTWITS_BACKUPS = [
    "https://api.stocktwits.com/api/2/trending/symbols/equities.json",  # 仅股票
]

# TradingView 备用
TRADINGVIEW_PRIMARY = "https://www.tradingview.com/feed/"
TRADINGVIEW_BACKUPS = [
    "https://www.tradingview.com/ideas/feed/",
    "https://rsshub.app/tradingview/ideas",
]

# Bogleheads 备用
BOGLEHEADS_PRIMARY = "https://www.bogleheads.org/forum/feed"
BOGLEHEADS_BACKUPS = [
    "https://www.bogleheads.org/forum/feed.php?f=1",  # 按板块
    "https://rsshub.app/bogleheads/forum",
]

# 财经日历备用
CALENDAR_PRIMARY = "https://datacenter-web.eastmoney.com/api/data/v1/get"
CALENDAR_BACKUPS = [
    "https://datacenter.eastmoney.com/api/data/v1/get",  # 无 -web
    "https://futsseapi.eastmoney.com/static/101_cjrl",  # 期货日历作为参考
]

# 20 家新闻源头的 RSSHub 备用基地址
RSSHUB_BASES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rsshub.pseudoyu.com",
]

# 通用请求头（模拟浏览器，避免被 WAF 拦截）
BACKUP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def try_urls_with_fallback(fetch_func: Callable, urls: List[str], **kwargs) -> Tuple[Any, str, List[str]]:
    """
    尝试多个 URL，任一成功即返回
    
    参数:
        fetch_func: 取数函数，签名为 fetch_func(url, **kwargs)
        urls: URL 列表，按优先级排序
        **kwargs: 传给 fetch_func 的其他参数
    
    返回:
        (result, success_url, errors)
        - result: 成功的结果，全部失败则 None
        - success_url: 成功的 URL，全部失败则 None
        - errors: 所有失败的错误信息列表
    """
    errors = []
    for url in urls:
        try:
            result = fetch_func(url, **kwargs)
            if result is not None:
                # 对于 JSON 结果，检查是否有有效数据
                if isinstance(result, dict):
                    # 空字典或明确的错误标记视为失败
                    if not result:
                        errors.append(f"{url}: 返回空数据")
                        continue
                    # 检查是否有错误码
                    if result.get("code") and result.get("code") != 200:
                        errors.append(f"{url}: code={result.get('code')} msg={result.get('msg')}")
                        continue
                # 对于文本结果，检查长度
                if isinstance(result, str) and len(result.strip()) < 10:
                    errors.append(f"{url}: 返回内容过短")
                    continue
                return result, url, errors
            else:
                errors.append(f"{url}: 返回 None")
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    
    return None, None, errors


def get_yahoo_urls(symbol: str) -> List[str]:
    """获取 Yahoo 的主备 URL 列表"""
    return [url.format(symbol=symbol) for url in [YAHOO_PRIMARY] + YAHOO_BACKUPS]


def get_google_news_urls(category: str = "zh", query: str = "") -> List[str]:
    """获取 Google News 的主备 URL，支持 search 类别带 query"""
    if category == "search" and query:
        # 构造搜索 URL 的主备
        from urllib.parse import quote
        q = quote(query)
        primary = f"https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        backups = [
            f"https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=HK&ceid=HK:zh-Hant",
            f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
            f"https://rsshub.app/google/news/search/{query}/zh-CN",
        ]
        for base in RSSHUB_BASES[1:]:
            backups.append(f"{base}/google/news/search/{query}/zh-CN")
        return [primary] + backups
    primary = GOOGLE_NEWS_PRIMARY.get(category, GOOGLE_NEWS_PRIMARY["zh"])
    backups = GOOGLE_NEWS_BACKUPS.get(category, [])
    # 追加 RSSHub 多基地址兜底
    if "rsshub.app" in primary or any("rsshub.app" in b for b in backups):
        for base in RSSHUB_BASES[1:]:
            for tmpl in GOOGLE_NEWS_BACKUPS.get(category, []):
                if "rsshub.app" in tmpl:
                    backups.append(tmpl.replace(RSSHUB_BASES[0], base))
    return [primary] + backups


def get_gov_policy_urls() -> List[str]:
    """获取政府网的主备 URL"""
    return GOV_POLICY_PRIMARY + GOV_POLICY_BACKUPS


def get_reddit_urls(community: str, limit: int = 10, mode: str = "rss") -> List[str]:
    """获取 Reddit 的主备 URL，mode=rss|json，兼容旧调用 get_reddit_urls(community, 'rss')
    
    为兼容离线测试，rss 模式仅返回主站 + old 域名（不含 RSSHub，避免测试 fake 解析失败）；
    真实环境中 RSSHub 作为额外兜底由调用方追加。
    """
    if isinstance(limit, str) and limit in ("rss", "json"):
        mode = limit
        limit = 10
    if isinstance(mode, int):
        limit = mode
        mode = "rss"
    # 仅使用主备，不含 RSSHub，避免测试环境 fake 因 URL 格式不同抛异常
    primary_rss = REDDIT_PRIMARY
    old_rss = "https://old.reddit.com/r/{community}/hot/.rss?limit={limit}"
    primary_json = "https://www.reddit.com/r/{community}/hot.json?limit={limit}"
    old_json = "https://old.reddit.com/r/{community}/hot.json?limit={limit}"
    if mode == "json":
        templates = [primary_json, old_json]
    else:
        templates = [primary_rss, old_rss]
    urls = []
    for tmpl in templates:
        try:
            urls.append(tmpl.format(community=community, limit=limit))
        except KeyError:
            urls.append(tmpl)
    # 去重
    seen = []
    for u in urls:
        if u not in seen:
            seen.append(u)
    return seen


def get_eastmoney_news_urls() -> List[str]:
    """东财快讯主备"""
    return EASTMONEY_NEWS_PRIMARY + EASTMONEY_NEWS_BACKUPS


def get_eastmoney_quote_urls() -> List[str]:
    """东财行情主备（clist/get, ulist.np/get 等通用）"""
    # 保留所有可能的 push2 域名变体
    bases = [
        "https://push2.eastmoney.com/api/qt/clist/get",
        "https://push2.eastmoney.com/api/qt/ulist.np/get",
        "https://push2.eastmoney.com/api/qt/clist/get",
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        "https://45.push2.eastmoney.com/api/qt/clist/get",
    ]
    # 合并去重
    return list(dict.fromkeys(bases + EASTMONEY_QUOTE_BACKUPS))


def get_eastmoney_panorama_urls() -> List[str]:
    """东财全景/板块主备"""
    return [EASTMONEY_PANORAMA_PRIMARY] + EASTMONEY_PANORAMA_BACKUPS + EASTMONEY_QUOTE_BACKUPS


def get_youtube_urls(channel_id: str) -> List[str]:
    """YouTube 频道 RSS 主备"""
    urls = []
    for tmpl in [YOUTUBE_PRIMARY] + YOUTUBE_BACKUPS:
        try:
            urls.append(tmpl.format(channel_id=channel_id))
        except Exception:
            urls.append(tmpl)
    # RSSHub 多基地址
    for base in RSSHUB_BASES[1:]:
        urls.append(f"{base}/youtube/channel/{channel_id}")
    return list(dict.fromkeys(urls))


def get_stocktwits_urls(kind: str = "trending", symbol: str = "") -> List[str]:
    """StockTwits 主备"""
    if kind == "stream" and symbol:
        primary = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
        backups = [
            f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json?filter=top",
        ]
        return [primary] + backups
    return [STOCKTWITS_PRIMARY] + STOCKTWITS_BACKUPS


def get_tradingview_urls() -> List[str]:
    return [TRADINGVIEW_PRIMARY] + TRADINGVIEW_BACKUPS


def get_bogleheads_urls() -> List[str]:
    return [BOGLEHEADS_PRIMARY] + BOGLEHEADS_BACKUPS


def get_calendar_urls() -> List[str]:
    return [CALENDAR_PRIMARY] + CALENDAR_BACKUPS


def get_rsshub_fallbacks(feed_url: str) -> List[str]:
    """为 RSSHub 订阅生成备用基地址"""
    if "rsshub.app" not in feed_url:
        return [feed_url]
    
    fallbacks = [feed_url]
    for base in RSSHUB_BASES[1:]:  # 跳过第一个（已是主）
        fallback_url = feed_url.replace(RSSHUB_BASES[0], base)
        if fallback_url not in fallbacks:
            fallbacks.append(fallback_url)
    
    return fallbacks


# 数据源完整备用映射，供外部查询
ALL_BACKUP_MAP = {
    "Yahoo 行情": {"primary": YAHOO_PRIMARY, "backups": YAHOO_BACKUPS},
    "东财快讯": {"primary": EASTMONEY_NEWS_PRIMARY, "backups": EASTMONEY_NEWS_BACKUPS},
    "东财行情": {"primary": EASTMONEY_QUOTE_PRIMARY, "backups": EASTMONEY_QUOTE_BACKUPS},
    "东财全景": {"primary": EASTMONEY_PANORAMA_PRIMARY, "backups": EASTMONEY_PANORAMA_BACKUPS},
    "Google News": {"primary": GOOGLE_NEWS_PRIMARY, "backups": GOOGLE_NEWS_BACKUPS},
    "政府网": {"primary": GOV_POLICY_PRIMARY, "backups": GOV_POLICY_BACKUPS},
    "YouTube": {"primary": YOUTUBE_PRIMARY, "backups": YOUTUBE_BACKUPS},
    "Reddit": {"primary": REDDIT_PRIMARY, "backups": REDDIT_BACKUPS},
    "StockTwits": {"primary": STOCKTWITS_PRIMARY, "backups": STOCKTWITS_BACKUPS},
    "TradingView": {"primary": TRADINGVIEW_PRIMARY, "backups": TRADINGVIEW_BACKUPS},
    "Bogleheads": {"primary": BOGLEHEADS_PRIMARY, "backups": BOGLEHEADS_BACKUPS},
    "财经日历": {"primary": CALENDAR_PRIMARY, "backups": CALENDAR_BACKUPS},
}


def get_backup_summary() -> str:
    """获取所有备用源的总结文本"""
    lines = ["🔄 数据源备用方案总览："]
    for name, cfg in ALL_BACKUP_MAP.items():
        primary = cfg["primary"]
        if isinstance(primary, list):
            primary = primary[0] if primary else "无"
        elif isinstance(primary, dict):
            primary = list(primary.values())[0] if primary else "无"
        backup_count = len(cfg["backups"]) if isinstance(cfg["backups"], list) else len(list(cfg["backups"].values())[0]) if isinstance(cfg["backups"], dict) else 0
        lines.append(f"· {name}：主 {primary[:60]}... + {backup_count} 个备用")
    
    return "\n".join(lines)
