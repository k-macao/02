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


def render_table(rows: list[list[str]], tone: str, table_number: int) -> str:
    if len(rows) < 2:
        return ""
    headers = rows[0]
    body = rows[1:]
    widths = meter_widths(body, headers)
    table_id = f"table-{table_number}"

    out = [f'<div class="table-wrap tone-{tone}" role="region" aria-label="表格 {table_number}" tabindex="0">']
    out.append(f'<table class="report-table" id="{table_id}"><thead><tr>')
    for header in headers:
        out.append(f"<th scope=\"col\">{render_inline(header)}</th>")
    out.append("</tr></thead><tbody>")

    for row_index, row in enumerate(body):
        out.append("<tr>")
        for column, cell in enumerate(row):
            cell_tag = "th scope=\"row\"" if column == 0 else "td"
            metric = widths.get((row_index, column))
            content = render_cell_content(cell)
            if metric is not None:
                width, mode = metric
                width_text = f"{width:.1f}%"
                explanation = "按实际比例" if mode == "share" else "按同列最大值归一"
                tooltip = html.escape(f"原值：{plain_text(cell)}；条形{explanation}", quote=True)
                out.append(
                    f'<{cell_tag} class="metric-cell" title="{tooltip}">'
                    f'<span class="bar-fill" style="width:{width_text}" aria-hidden="true"></span>'
                    f'<span class="cell-content">{content}</span></{cell_tag.split()[0]}>'
                )
            else:
                out.append(f"<{cell_tag}>{content}</{cell_tag.split()[0]}>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
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
                rendered.append(render_table([headers, *data_rows], current_tone, table_count))
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
:root{color-scheme:light;--ink:#162536;--muted:#66788a;--paper:#f3f7fa;--white:#fff;--line:#dce6ee;--navy:#10253b;--shadow:0 14px 38px rgba(25,52,77,.08)}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:84px}
body{margin:0;background:radial-gradient(ellipse at 8% 0%,#deeff4 0,transparent 34%),radial-gradient(ellipse at 100% 18%,#e9e7fa 0,transparent 32%),var(--paper);color:var(--ink);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;line-height:1.65}
.page{max-width:1240px;margin:0 auto;padding:34px 28px 72px}
.hero{position:relative;overflow:hidden;padding:34px 38px 30px;border:1px solid rgba(255,255,255,.68);border-radius:26px;background:linear-gradient(128deg,#12283f 0%,#173f5a 54%,#167c79 100%);color:#fff;box-shadow:0 24px 55px rgba(13,49,73,.2)}
.hero:after{content:"";position:absolute;width:330px;height:330px;border:1px solid rgba(255,255,255,.14);border-radius:50%;right:-90px;top:-170px;box-shadow:0 0 0 34px rgba(255,255,255,.035),0 0 0 72px rgba(255,255,255,.025)}
.eyebrow{position:relative;z-index:1;color:#8ce0d0;font-size:11px;font-weight:800;letter-spacing:.22em;text-transform:uppercase}
.hero h1{position:relative;z-index:1;margin:6px 0 8px;font-size:clamp(30px,5vw,48px);line-height:1.18;letter-spacing:-.035em;color:#fff}
.hero p{position:relative;z-index:1;max-width:780px;margin:0;color:#d8e7ef;font-size:15px}
.hero-meta{position:relative;z-index:1;display:flex;flex-wrap:wrap;gap:9px;margin-top:22px}
.pill{padding:5px 11px;border:1px solid rgba(255,255,255,.22);border-radius:999px;background:rgba(255,255,255,.09);color:#eefaff;font-size:12px}
.legend{display:flex;flex-wrap:wrap;gap:12px 20px;align-items:center;margin:16px 0 22px;padding:12px 16px;border:1px solid #dce8ee;border-radius:14px;background:rgba(255,255,255,.78);color:#53687a;font-size:12px;box-shadow:0 4px 16px rgba(25,52,77,.035)}
.legend-item{display:inline-flex;gap:8px;align-items:center}.swatch{width:26px;height:12px;border:1px solid #dae6ed;border-radius:4px;background:linear-gradient(180deg,#f0f7fb 0 50%,#fff 50% 100%)}.bar-swatch{width:48px;height:10px;border:1px solid #d7e2e9;border-radius:99px;background:linear-gradient(90deg,#55a8a0 64%,#edf3f6 64%)}
.toc{position:sticky;z-index:10;top:10px;display:flex;flex-wrap:wrap;gap:7px;margin:0 0 26px;padding:11px;border:1px solid rgba(210,223,232,.9);border-radius:16px;background:rgba(255,255,255,.9);backdrop-filter:blur(14px);box-shadow:0 7px 22px rgba(25,52,77,.07)}
.toc-link{display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border-radius:10px;color:#24374a;text-decoration:none;font-size:12px;font-weight:700;transition:transform .16s ease,background .16s ease}.toc-link:hover{transform:translateY(-1px);background:#eef5f8}.toc-link span{display:grid;place-items:center;width:23px;height:23px;border-radius:7px;background:var(--accent-soft);color:var(--accent);font-size:10px}
.report-section{--accent:#1769aa;--accent-dark:#0d4779;--accent-soft:#e6f2fb;--row-a:#f0f7fc;--row-hover:#e0f0fa;--bar-rgb:23,105,170;margin:0 0 24px;padding:28px 28px 26px;border:1px solid rgba(215,226,234,.95);border-radius:22px;background:rgba(255,255,255,.92);box-shadow:var(--shadow)}
.tone-blue{--accent:#1769aa;--accent-dark:#0d4779;--accent-soft:#e6f2fb;--row-a:#f0f7fc;--row-hover:#deeffa;--bar-rgb:23,105,170}
.tone-teal{--accent:#0c8178;--accent-dark:#075b57;--accent-soft:#e1f5f2;--row-a:#eff9f7;--row-hover:#d9f1ed;--bar-rgb:12,129,120}
.tone-indigo{--accent:#5864c7;--accent-dark:#3e489a;--accent-soft:#eaecff;--row-a:#f4f4ff;--row-hover:#e6e9ff;--bar-rgb:88,100,199}
.tone-violet{--accent:#8053b8;--accent-dark:#5f3991;--accent-soft:#f2eafa;--row-a:#faf5fd;--row-hover:#f0e5fa;--bar-rgb:128,83,184}
.tone-amber{--accent:#b66a21;--accent-dark:#824411;--accent-soft:#fff0d9;--row-a:#fff9ef;--row-hover:#fff0d8;--bar-rgb:182,106,33}
.tone-rose{--accent:#b74f70;--accent-dark:#84334e;--accent-soft:#fdebf0;--row-a:#fff5f7;--row-hover:#fbe6ed;--bar-rgb:183,79,112}
.tone-green{--accent:#318254;--accent-dark:#205b39;--accent-soft:#e5f4e9;--row-a:#f1f9f3;--row-hover:#e2f3e6;--bar-rgb:49,130,84}
.chapter-label{display:inline-flex;align-items:center;gap:8px;margin-bottom:6px;color:var(--accent);font-size:10px;font-weight:900;letter-spacing:.2em;text-transform:uppercase}.chapter-label:before{content:"";width:22px;height:2px;background:var(--accent)}
.chapter-title{margin:0 0 22px;padding:0 0 13px;border-bottom:1px solid var(--line);color:#14273b;font-size:clamp(22px,3vw,30px);line-height:1.25;letter-spacing:-.02em}
.subheading{display:flex;align-items:center;gap:10px;margin:29px 0 13px;color:#253c50;font-size:18px;line-height:1.35}.subheading:before{content:"";width:5px;height:21px;border-radius:5px;background:var(--accent)}
.minor-heading{margin:21px 0 10px;color:var(--accent-dark);font-size:15px}
.table-wrap{position:relative;margin:0 0 18px;overflow:auto;border:1px solid #dce6ed;border-radius:14px;background:#fff;box-shadow:0 5px 15px rgba(26,52,74,.045);scrollbar-color:#b6cbd6 #f4f8fa;scrollbar-width:thin}
.report-table{width:100%;min-width:560px;border-collapse:separate;border-spacing:0;color:#23384a;font-size:13px;line-height:1.55}
.report-table th,.report-table td{position:relative;padding:10px 12px;border-bottom:1px solid rgba(215,226,234,.78);vertical-align:top;text-align:left;overflow-wrap:anywhere}
.report-table thead th{position:sticky;top:0;z-index:2;background:linear-gradient(120deg,var(--accent-dark),var(--accent));color:#fff;font-weight:750;letter-spacing:.015em;border-bottom:0}
.report-table thead th:first-child{border-radius:12px 0 0 0}.report-table thead th:last-child{border-radius:0 12px 0 0}
.report-table tbody tr:nth-child(odd){background:var(--row-a)}.report-table tbody tr:nth-child(even){background:#fff}.report-table tbody tr:hover{background:var(--row-hover)}
.report-table tbody tr:last-child th,.report-table tbody tr:last-child td{border-bottom:0}
.report-table tbody th[scope=row]{width:1%;min-width:135px;color:var(--accent-dark);font-weight:700}
.metric-cell{font-variant-numeric:tabular-nums;white-space:nowrap}.metric-cell .bar-fill{position:absolute;z-index:0;left:0;top:0;bottom:0;max-width:100%;background:linear-gradient(90deg,rgba(var(--bar-rgb),.17),rgba(var(--bar-rgb),.07));border-right:2px solid rgba(var(--bar-rgb),.36);pointer-events:none}.metric-cell .cell-content{position:relative;z-index:1}
code{padding:.12em .38em;border:1px solid #dfe8ed;border-radius:5px;background:#f2f6f8;color:#22506a;font-size:.91em;overflow-wrap:anywhere}
.badge{display:inline-flex;align-items:center;justify-content:center;padding:2px 8px;border:1px solid transparent;border-radius:999px;font-size:11px;font-weight:800;line-height:1.5;white-space:nowrap}.badge-on,.badge-pass{background:#e5f5eb;color:#267142;border-color:#c8e9d3}.badge-off,.badge-neutral{background:#edf1f4;color:#677887;border-color:#dce4e9}.badge-fail{background:#fde8e6;color:#a63d36;border-color:#f4c8c3}.badge-warn{background:#fff2d8;color:#8a5a12;border-color:#f1dcae}.badge-missing{background:#fff1dc;color:#95590b;border-color:#f1ddba}
.source-note{margin:0 0 18px;padding:12px 15px;border-left:4px solid #0c8178;border-radius:0 11px 11px 0;background:linear-gradient(100deg,#e9f7f4,#f4fbfa);color:#31524f;font-size:13px}.source-note a{color:#086b66;font-weight:800}
.plain-text{margin:10px 0;color:#465a6c}.soft-rule{margin:27px 0;border:0;border-top:1px solid var(--line)}
.footer{padding:16px 5px 0;color:#718192;text-align:center;font-size:11px}
@media(max-width:760px){.page{padding:16px 12px 42px}.hero{padding:25px 21px 22px;border-radius:20px}.hero p{font-size:14px}.legend{padding:11px 12px}.toc{top:6px;gap:4px;padding:8px}.toc-link{padding:5px 7px;font-size:11px}.report-section{padding:21px 14px 18px;border-radius:17px}.report-table{min-width:520px;font-size:12px}.report-table th,.report-table td{padding:9px 10px}.subheading{font-size:16px}}
@media print{body{background:#fff}.page{max-width:none;padding:0}.hero{background:#163c54!important;print-color-adjust:exact;-webkit-print-color-adjust:exact;box-shadow:none}.toc{position:static;box-shadow:none}.report-section{box-shadow:none;break-inside:avoid}.table-wrap{overflow:visible;box-shadow:none}.report-table thead th,.report-table tbody tr:nth-child(odd),.metric-cell .bar-fill{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
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
<meta name="description" content="章鱼 AI 内容分类整理：数据源、量化、页面推送与问题诊断">
<title>章鱼 AI · 内容分类整理（表格可视化）</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <div class="eyebrow">OCTOPUS AI · FIELD GUIDE</div>
    <h1>章鱼 AI · 内容分类整理</h1>
    <p>同一份内容，改用更直观的表格呈现。章节以不同色系区分，表格行交替着色，关键数字附带同列比例条。</p>
    <div class="hero-meta">
      <span class="pill">{len(chapters)} 个内容分区</span>
      <span class="pill">{table_count} 张数据表</span>
      <span class="pill">独立 HTML · 离线可读</span>
      <span class="pill">响应式布局</span>
    </div>
  </header>
  <div class="legend" aria-label="可视化说明">
    <span class="legend-item"><span class="swatch"></span>表格行底色交替，悬停高亮</span>
    <span class="legend-item"><span class="bar-swatch"></span>数值条：比例类按实际比例，其他指标按同列最大值归一</span>
    <span class="legend-item">显示的数字始终保留原值；横向可滚动查看更多列</span>
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
    print(f"Rendered {SOURCE.name} → {OUTPUT.name} ({table_count} tables)")


if __name__ == "__main__":
    main()
