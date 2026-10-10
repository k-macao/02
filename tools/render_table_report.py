#!/usr/bin/env python3
"""Render 整理.md as a self-contained, zebra-striped HTML report with inline data bars."""
from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "整理.md"
OUTPUT = ROOT / "整理-表格可视化.html"

SECTION_TONES = {
    1: "blue",
    2: "teal",
    3: "indigo",
    4: "violet",
    5: "amber",
    6: "rose",
    7: "green",
}

INLINE_TOKEN = re.compile(r"(`[^`]+`|\*\*.*?\*\*|\[[^\]]+\]\([^)]+\))")
RATIO = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$")
PERCENT = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*%\s*$")
NUMBER = re.compile(r"^\s*([+-]?[\d,]+(?:\.\d+)?)\s*([kKmM])?\s*(ms|s|秒)?\s*$")


def split_table_row(line: str) -> list[str]:
    """Split a Markdown pipe-table row, respecting escaped literal pipes."""
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]

    cells: list[str] = []
    cell: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value) and value[i + 1] == "|":
            cell.append("|")
            i += 2
            continue
        if value[i] == "|":
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(value[i])
        i += 1
    cells.append("".join(cell).strip())
    return cells


def is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def plain_text(markdown: str) -> str:
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", markdown)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    return value.replace(r"\|", "|").strip()


def render_inline(markdown: str) -> str:
    """Render the small inline-Markdown subset used by 整理.md safely."""
    output: list[str] = []
    position = 0
    for match in INLINE_TOKEN.finditer(markdown):
        output.append(html.escape(markdown[position:match.start()], quote=False).replace(r"\|", "|"))
        token = match.group(0)
        if token.startswith("`"):
            code_value = html.escape(token[1:-1], quote=False).replace("\\|", "|")
            output.append(f"<code>{code_value}</code>")
        elif token.startswith("**"):
            output.append(f"<strong>{render_inline(token[2:-2])}</strong>")
        else:
            link = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", token)
            if link:
                label, href = link.groups()
                safe_href = href if href.startswith(("https://", "http://", "./", "../", "#")) else "#"
                output.append(f'<a href="{html.escape(safe_href, quote=True)}">{render_inline(label)}</a>')
        position = match.end()
    output.append(html.escape(markdown[position:], quote=False).replace(r"\|", "|"))
    return "".join(output)


def metric_header(header: str) -> str | None:
    """Return a visualization kind for columns that contain comparable data."""
    label = plain_text(header).lower().replace(" ", "")
    if label == "维度":
        return "share-in-label"
    if any(term in label for term in ("保留", "削幅", "≥±", "出现率", "近10次出现", "稳定出现", "当天源")):
        return "share"
    if label in {"原始值", "显示值"} or "raw" in label or "p95" in label:
        return "relative"
    if "★" in label or "单题延迟" in label or "耗时" in label or "时间" == label:
        return "relative"
    return None


def parse_metric(value: str, kind: str) -> tuple[float, str] | None:
    text = plain_text(value)
    ratio = RATIO.fullmatch(text)
    if ratio and kind == "share":
        numerator, denominator = map(float, ratio.groups())
        return (abs(numerator) / denominator if denominator else 0.0), "share"

    percent = PERCENT.fullmatch(text)
    if percent and kind == "share":
        return abs(float(percent.group(1))) / 100.0, "share"

    if kind == "share-in-label":
        matches = re.findall(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", text)
        if len(matches) == 1:
            return float(matches[0]) / 100.0, "share"

    if kind != "relative":
        return None
    number = NUMBER.fullmatch(text)
    if not number:
        return None
    raw, multiplier, unit = number.groups()
    amount = float(raw.replace(",", ""))
    if multiplier:
        amount *= 1_000 if multiplier.lower() == "k" else 1_000_000
    # Units are intentionally compared within their own table column.
    return abs(amount), "relative"


def meter_widths(rows: list[list[str]], headers: list[str]) -> dict[tuple[int, int], tuple[float, str]]:
    """Compute in-cell bar widths; source values remain visible verbatim."""
    result: dict[tuple[int, int], tuple[float, str]] = {}
    for column, header in enumerate(headers):
        kind = metric_header(header)
        if not kind:
            continue
        parsed = [(row_index, parse_metric(row[column], kind)) for row_index, row in enumerate(rows)]
        valid = [(index, metric) for index, metric in parsed if metric is not None]
        if len(valid) < 2:
            continue
        modes = {metric[1] for _, metric in valid}
        if modes == {"share"}:
            for row_index, (amount, mode) in valid:
                result[(row_index, column)] = (max(0.0, min(1.0, amount)) * 100.0, mode)
        else:
            maximum = max(amount for _, (amount, _) in valid) or 1.0
            for row_index, (amount, mode) in valid:
                result[(row_index, column)] = (max(0.0, min(1.0, amount / maximum)) * 100.0, mode)
    return result


def render_cell_content(value: str) -> str:
    text = plain_text(value)
    normalized = text.strip()
    badges = {
        "开": "badge-on",
        "关": "badge-off",
        "failed": "badge-fail",
        "P": "badge-pass",
        ".": "badge-missing",
        "—": "badge-neutral",
        "无冲突": "badge-pass",
        "保持开放": "badge-warn",
    }
    if normalized in badges:
        return f'<span class="badge {badges[normalized]}">{render_inline(value)}</span>'
    for symbol, class_name in (("✅", "badge-pass"), ("❌", "badge-fail"), ("⚠️", "badge-warn"), ("⛔", "badge-fail")):
        if normalized.startswith(symbol):
            rest = value[value.find(symbol) + len(symbol):].strip()
            return f'<span class="badge {class_name}">{symbol}</span>{(" " + render_inline(rest)) if rest else ""}'
    return render_inline(value)


def render_meter(cell: str, metric: tuple[float, str]) -> str:
    """Inline mini-bar: keeps the number on the same line (no extra row)."""
    width, mode = metric
    explanation = "按实际比例" if mode == "share" else "按同组最大值归一"
    tooltip = html.escape(f"原值：{plain_text(cell)}；条形{explanation}", quote=True)
    return (f'<span class="meter" title="{tooltip}" aria-hidden="true">'
            f'<span class="meter-fill" style="width:{width:.1f}%"></span></span>')


def render_records(rows: list[list[str]], tone: str, block_number: int) -> str:
    """Render a Markdown table as a single-column list: one compact entry per row.

    不分列：每行拆成「字段：内容」逐行堆叠，窄屏不需要左右滑动；
    压缩行：空单元格直接不出行，数值条形改为行内迷你条，不额外占一行。
    """
    if len(rows) < 2:
        return ""
    headers = rows[0]
    body = rows[1:]
    widths = meter_widths(body, headers)

    out = [f'<ol class="record-list tone-{tone}" id="list-{block_number}" '
           f'aria-label="条目组 {block_number}">']
    for row_index, row in enumerate(body):
        out.append('<li class="record">')
        head_cell = row[0] if row else ""
        head_label = plain_text(headers[0]) if headers else ""
        head_metric = widths.get((row_index, 0))
        out.append('<p class="record-head">')
        out.append(f'<span class="record-no">{row_index + 1:02d}</span>')
        if head_label and row_index == 0:
            # 首列表头只在该组第一条出现一次，重复出现只会拉长行数。
            out.append(f'<span class="record-kicker">{render_inline(headers[0])}</span>')
        out.append(f'<span class="record-title">{render_cell_content(head_cell)}</span>')
        if head_metric is not None:
            out.append(render_meter(head_cell, head_metric))
        out.append('</p>')

        for column in range(1, len(headers)):
            cell = row[column] if column < len(row) else ""
            if not plain_text(cell):
                continue                      # 空值不占行
            label = plain_text(headers[column])
            metric = widths.get((row_index, column))
            out.append('<p class="field">')
            if label:
                out.append(f'<span class="field-label">{render_inline(headers[column])}</span>')
            out.append(f'<span class="field-value">{render_cell_content(cell)}</span>')
            if metric is not None:
                out.append(render_meter(cell, metric))
            out.append('</p>')
        out.append('</li>')
    out.append('</ol>')
    return "".join(out)


def heading_slug(index: int) -> str:
    return f"chapter-{index}"


def build_report(markdown: str) -> tuple[str, int, list[tuple[str, str]], str]:
    lines = markdown.splitlines()
    chapter_titles: list[tuple[str, str]] = []
    seen_h1 = False
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match and len(match.group(1)) == 1:
            if not seen_h1:
                seen_h1 = True
                continue
            chapter_titles.append((heading_slug(len(chapter_titles) + 1), match.group(2)))

    rendered: list[str] = []
    current_tone = "blue"
    chapter_index = 0
    h1_seen = False
    section_open = False
    subheading_index = 0
    table_count = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            if level == 1 and not h1_seen:
                h1_seen = True
                index += 1
                continue
            if level == 1:
                if section_open:
                    rendered.append("</section>")
                chapter_index += 1
                current_tone = SECTION_TONES.get(chapter_index, "blue")
                subheading_index = 0
                section_open = True
                rendered.append(f'<section class="report-section tone-{current_tone}" id="{heading_slug(chapter_index)}">')
                rendered.append(f'<div class="chapter-label">SECTION {chapter_index:02d}</div>')
                rendered.append(f'<h2 class="chapter-title">{render_inline(title)}</h2>')
            else:
                h_level = min(level + 1, 6)
                if level == 2:
                    subheading_index += 1
                    anchor = f"sub-{chapter_index}-{subheading_index}"
                    rendered.append(f'<h{h_level} id="{anchor}" class="subheading">{render_inline(title)}</h{h_level}>')
                else:
                    rendered.append(f'<h{h_level} class="minor-heading">{render_inline(title)}</h{h_level}>')
            index += 1
            continue

        if line.startswith("> "):
            rendered.append(f'<aside class="source-note">{render_inline(line[2:].strip())}</aside>')
            index += 1
            continue

        if line.strip() in {"---", "***", "___"}:
            rendered.append('<hr class="soft-rule">')
            index += 1
            continue

        if is_table_line(line):
            raw_rows: list[list[str]] = []
            while index < len(lines) and is_table_line(lines[index]):
                raw_rows.append(split_table_row(lines[index]))
                index += 1
            if len(raw_rows) >= 2 and is_separator_row(raw_rows[1]):
                headers = raw_rows[0]
                data_rows = raw_rows[2:]
                if any(len(row) != len(headers) for row in data_rows):
                    raise ValueError(f"Table has inconsistent columns near line {index - len(raw_rows) + 1}")
                table_count += 1
                rendered.append(render_records([headers, *data_rows], current_tone, table_count))
            else:
                for row in raw_rows:
                    rendered.append(f'<p class="plain-text">{render_inline(" | ".join(row))}</p>')
            continue

        # Paragraph fallback keeps future non-table notes readable.
        paragraph = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip() and not re.match(r"^#{1,6}\s+", lines[index]) and not is_table_line(lines[index]) and lines[index].strip() not in {"---", "***", "___"}:
            paragraph.append(lines[index].strip())
            index += 1
        rendered.append(f'<p class="plain-text">{render_inline(" ".join(paragraph))}</p>')

    if section_open:
        rendered.append("</section>")

    body = "\n".join(rendered)
    toc = "\n".join(
        f'<a class="toc-link tone-{SECTION_TONES.get(i, "blue")}" href="#{slug}"><span>{i:02d}</span>{render_inline(title)}</a>'
        for i, (slug, title) in enumerate(chapter_titles, start=1)
    )
    return body, table_count, [(slug, title) for slug, title in chapter_titles], toc


CSS = r"""
:root{color-scheme:light;--ink:#111111;--muted:#8a8a8e;--paper:#ffffff;--card:#f5f5f6;--white:#fff;--line:#e4e4e7;--lime:#c8f03c;--lime-deep:#7a9a00;--shadow:none}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:84px}
body{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;line-height:1.6;-webkit-font-smoothing:antialiased}
.page{max-width:1000px;margin:0 auto;padding:44px 28px 80px}
.hero{position:relative;padding:8px 6px 26px}
.eyebrow{color:var(--muted);font-size:12px;font-weight:600;letter-spacing:.12em;text-transform:uppercase}
.hero h1{margin:8px 0 12px;font-size:clamp(34px,5.4vw,58px);font-weight:900;line-height:1.12;letter-spacing:-.04em;color:var(--ink)}
.hero p{max-width:720px;margin:0;color:#5b5b60;font-size:15px}
.hero-meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}
.pill{padding:5px 12px;border-radius:999px;background:var(--card);color:#222;font-size:12px;font-weight:600}
.legend{display:flex;flex-wrap:wrap;gap:10px 22px;align-items:center;margin:18px 0 22px;padding:14px 18px;border-radius:18px;background:var(--card);color:#5b5b60;font-size:12px}
.legend-item{display:inline-flex;gap:8px;align-items:center}
.swatch{width:26px;height:12px;border-radius:3px;background:#e2e2e5}
.bar-swatch{width:48px;height:6px;border-radius:99px;background:linear-gradient(90deg,var(--lime) 64%,#e4e4e7 64%)}
.toc{position:sticky;z-index:10;top:10px;display:flex;flex-wrap:wrap;gap:6px;margin:0 0 28px;padding:10px;border-radius:18px;background:rgba(255,255,255,.94);backdrop-filter:blur(12px);border:1px solid var(--line)}
.toc-link{display:inline-flex;align-items:center;gap:7px;padding:6px 11px;border-radius:999px;color:#555;text-decoration:none;font-size:12px;font-weight:600;transition:background .15s ease,color .15s ease}
.toc-link:hover{background:var(--card);color:var(--ink)}
.toc-link span{display:grid;place-items:center;min-width:22px;height:22px;padding:0 5px;border-radius:999px;background:#ececef;color:#333;font-size:10px;font-weight:800}
.toc-link:hover span{background:var(--lime)}
/* 统一为荧绿强调色 */
.tone-blue,.tone-teal,.tone-indigo,.tone-violet,.tone-amber,.tone-rose,.tone-green{--accent:var(--lime-deep);--accent-dark:var(--ink);--accent-soft:#f0f9c4;--row-a:#fafafa;--row-hover:#f0f0f2;--bar-rgb:200,240,60}
.report-section{margin:0 0 22px;padding:30px 30px 26px;border-radius:26px;background:var(--card);border:0;box-shadow:none}
.chapter-label{display:inline-flex;align-items:center;gap:8px;margin-bottom:6px;color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase}
.chapter-label:before{content:"";width:8px;height:8px;border-radius:2px;background:var(--lime)}
.chapter-title{margin:0 0 20px;padding:0 0 14px;border-bottom:1px solid #e0e0e4;color:var(--ink);font-size:clamp(24px,3.2vw,34px);font-weight:900;line-height:1.2;letter-spacing:-.03em}
.subheading{display:flex;align-items:center;gap:10px;margin:26px 0 12px;color:var(--ink);font-size:18px;font-weight:800;line-height:1.35;letter-spacing:-.01em}
.subheading:before{content:"";width:14px;height:14px;border-radius:3px;background:var(--lime);flex:0 0 auto}
.minor-heading{margin:20px 0 10px;color:var(--ink);font-size:15px;font-weight:800}
.record-list{list-style:none;margin:0 0 14px;padding:0;border-radius:16px;background:#fff;overflow:hidden}
.record{padding:9px 16px 10px;border-top:1px solid #f0f0f2}
.record:first-child{border-top:0}
.record:nth-child(odd){background:#fff}
.record:nth-child(even){background:#fbfbfc}
.record:hover{background:#f3f7e0}
.record-head{margin:0;color:var(--ink);font-size:14px;font-weight:700;line-height:1.5;overflow-wrap:anywhere}
.record-no{display:inline-block;min-width:22px;margin-right:8px;padding:0 6px;border-radius:999px;background:var(--lime);color:var(--ink);font-size:10px;font-weight:900;line-height:18px;text-align:center;vertical-align:1px}
.record-kicker{margin-right:6px;color:var(--muted);font-size:11px;font-weight:700;letter-spacing:.04em}
.record-kicker:after{content:"·";margin-left:6px;color:#c4c4c9}
.record-title{color:var(--ink)}
.field{margin:2px 0 0;padding-left:30px;color:#4a4a50;font-size:13px;line-height:1.55;overflow-wrap:anywhere}
.field-label{margin-right:6px;color:var(--ink);font-size:11px;font-weight:800}
.field-label:after{content:"：";color:var(--muted)}
.field-value{font-variant-numeric:tabular-nums}
.meter{display:inline-block;width:64px;height:6px;margin-left:8px;border-radius:99px;background:#e4e4e7;vertical-align:middle;overflow:hidden}
.meter-fill{display:block;height:100%;border-radius:99px;background:var(--lime)}
code{padding:.1em .4em;border-radius:6px;background:#fff;border:1px solid #e4e4e7;color:#222;font-size:.9em;overflow-wrap:anywhere}
.badge{display:inline-flex;align-items:center;justify-content:center;padding:2px 9px;border-radius:999px;font-size:11px;font-weight:800;line-height:1.5;white-space:nowrap;border:0}
.badge-on,.badge-pass{background:var(--lime);color:var(--ink)}
.badge-off,.badge-neutral{background:#e4e4e7;color:#6b6b70}
.badge-fail{background:#111;color:#fff}
.source-note{margin:0 0 18px;padding:14px 18px;border-radius:16px;background:#fff;color:#4a4a50;font-size:13px}
.source-note a{color:var(--ink);font-weight:800;text-decoration:underline;text-decoration-color:var(--lime);text-decoration-thickness:3px;text-underline-offset:3px}
.plain-text{margin:10px 0;color:#4a4a50}
.soft-rule{margin:24px 0;border:0;border-top:1px solid #e0e0e4}
.footer{margin-top:28px;padding:0 4px;color:var(--muted);font-size:11px;line-height:1.6}
.footer code{background:transparent;border:0;padding:0}
@media(max-width:760px){.page{padding:22px 12px 44px}.hero{padding:4px 4px 18px}.legend{padding:12px}.toc{top:6px;gap:4px;padding:8px}.toc-link{padding:5px 9px;font-size:11px}.report-section{padding:20px 14px 16px;border-radius:20px}.record{padding:9px 12px}.record-head{font-size:13px}.field{padding-left:0;font-size:12.5px}.subheading{font-size:16px}}
@media print{body{background:#fff}.page{max-width:none;padding:0}.toc{position:static;backdrop-filter:none}.report-section{break-inside:avoid}.record{break-inside:avoid}.record-no,.meter-fill,.bar-swatch{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
"""


def main() -> None:
    markdown = SOURCE.read_text(encoding="utf-8")
    body, table_count, chapters, toc = build_report(markdown)
    page = f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="description" content="章鱼 AI 内容分类整理：单列条目排版，数据源、量化、页面推送与问题诊断">
<title>章鱼 AI · 内容分类整理（单列条目版）</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <div class="eyebrow">OCTOPUS AI · FIELD GUIDE</div>
    <h1>章鱼 AI · 内容分类整理</h1>
    <p>同一份内容，全部改成单列条目：不分列、不横滑，每行拆成「字段：内容」逐行堆叠，行距压紧，空字段不占行。</p>
    <div class="hero-meta">
      <span class="pill">{len(chapters)} 个内容分区</span>
      <span class="pill">{table_count} 组条目</span>
      <span class="pill">独立 HTML · 离线可读</span>
      <span class="pill">单列 · 不分列 · 紧凑行距</span>
    </div>
  </header>
  <div class="legend" aria-label="阅读说明">
    <span class="legend-item"><span class="swatch"></span>条目底色交替，悬停高亮</span>
    <span class="legend-item"><span class="bar-swatch"></span>行内迷你条：比例类按实际比例，其他指标按同组最大值归一</span>
    <span class="legend-item">显示的数字始终保留原值；单列排版，窄屏无需左右滑动</span>
  </div>
  <nav class="toc" aria-label="章节导航">{toc}</nav>
  <main>
{body}
  </main>
  <footer class="footer">由 <code>整理.md</code> 生成 · 内嵌样式，无外部字体、脚本或网络依赖</footer>
</div>
</body>
</html>
'''
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"Rendered {SOURCE.name} → {OUTPUT.name} ({table_count} record lists)")


if __name__ == "__main__":
    main()
