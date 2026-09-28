"""行业轮动数据源在线探测（GitHub Actions 中运行，结果落盘 + 打印）。

用途：日报栏目「每日量化策略（行业轮动）」缺席时，在真实外网环境复现
``sector_rotation.run()`` 的每一步，定位是「板块日 K 接口（三主机）」「申万官方备用源」
还是「覆盖 / 锚点 / 存档门槛」把整栏判死；clist 列表接口只作记录（2026-09-29 起主流程
改用 31 个申万一级行业固定表，不再依赖它）。只做只读探测，不写任何策略状态文件，不推送。

用法：
    python3 output/probe_sector_rotation.py
    python3 output/probe_sector_rotation.py -o output/diag/probe.json

探测结果写入 JSON：HTTP 状态、响应结构、样本行、耗时、以及 run() 的最终判定。
失败信息一律如实记录，不做任何兜底或伪装。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"          # 兼容旧引用
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"  # 兼容旧引用


def _http_json(url, params, timeout=15, extra_headers=None, label=""):
    """单次 GET：记录状态、耗时与响应片段，异常也如实返回。"""
    out = {"label": label, "url": url, "params": dict(params), "timeout": timeout}
    query = urllib.parse.urlencode(params)
    full = f"{url}?{query}"
    out["request_url"] = full
    headers = {"User-Agent": UA,
               "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
               "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if extra_headers:
        headers.update(extra_headers)
    started = time.time()
    try:
        req = urllib.request.Request(full, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out["http_status"] = resp.status
            raw = resp.read()
        out["elapsed_ms"] = int((time.time() - started) * 1000)
        out["bytes"] = len(raw)
        out["body_head"] = raw[:600].decode("utf-8", "replace")
        try:
            out["json"] = json.loads(raw.decode("utf-8", "replace"))
            out["json_ok"] = True
        except (ValueError, UnicodeDecodeError) as exc:
            out["json_ok"] = False
            out["json_error"] = f"{type(exc).__name__}: {exc}"
    except urllib.error.HTTPError as exc:
        out["elapsed_ms"] = int((time.time() - started) * 1000)
        out["http_status"] = exc.code
        out["error"] = f"HTTPError {exc.code}"
        out["body_head"] = (exc.read()[:400].decode("utf-8", "replace")
                            if hasattr(exc, "read") else "")
    except Exception as exc:                                  # 网络层失败
        out["elapsed_ms"] = int((time.time() - started) * 1000)
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def _summarize_list(probe):
    """把行业列表响应压缩成可快速判读的摘要。"""
    data = probe.get("json") or {}
    root = data.get("data") if isinstance(data, dict) else None
    if not isinstance(root, dict):
        return {"note": "data 缺失或不是对象", "rc": data.get("rc") if isinstance(data, dict) else None}
    diff = root.get("diff")
    sample = ""
    if isinstance(diff, list) and diff:
        sample = str(diff[0])[:200]
    elif isinstance(diff, dict) and diff:
        key = sorted(diff)[0]
        sample = f"{key}: {str(diff[key])[:160]}"
    return {"total": root.get("total"), "diff_type": type(diff).__name__,
            "diff_len": len(diff) if hasattr(diff, "__len__") else None,
            "sample": sample, "keys": sorted(root)[:12]}


def _summarize_kline(probe):
    data = probe.get("json") or {}
    root = data.get("data") if isinstance(data, dict) else None
    if not isinstance(root, dict):
        return {"note": "data 缺失或不是对象", "rc": data.get("rc") if isinstance(data, dict) else None}
    klines = root.get("klines")
    return {"name": root.get("name"), "code": root.get("code"),
            "klines_type": type(klines).__name__,
            "klines_len": len(klines) if hasattr(klines, "__len__") else None,
            "first": str(klines[0])[:120] if klines else None,
            "last": str(klines[-1])[:120] if klines else None,
            "keys": sorted(root)[:12]}


def probe_universe():
    """行业板块列表（clist）：只作记录，主流程自 2026-09-29 起不再依赖它。

    先小页（pz=5，与全景「板块热力」同口径，通常 200），再现行大页（pz=100，境外出口常 502），
    主源与一个镜像各试一次；``total`` 用来记录东财三级混排后的板块总数（2026-09 为 496）。
    """
    import sector_rotation as sr
    base = {"pn": "1", "po": "1", "np": "1", "fltt": "2", "invt": "2",
            "fid": "f3", "fs": "m:90+t:2", "fields": "f12,f14,f3"}
    probes = []
    for url in sr.LIST_URLS[:2]:
        host = urllib.parse.urlsplit(url).netloc
        for pz, label in (("5", "小页 pz=5"), ("100", "大页 pz=100")):
            probe = _http_json(url, dict(base, pz=pz), extra_headers=sr.EM_HEADERS,
                               label=f"{host} {label}")
            probe["summary"] = _summarize_list(probe)
            probes.append(probe)
    return probes


def probe_klines(codes):
    """申万一级板块日 K：每个样本代码依次试主源与两个镜像；都异常时再试 fqt 变体。"""
    import sector_rotation as sr
    base = {"klt": "101", "fqt": "1", "lmt": "180", "end": "20500101",
            "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56"}
    out = []
    for code in codes:
        got = False
        for url in sr.KLINE_URLS:
            host = urllib.parse.urlsplit(url).netloc
            probe = _http_json(url, dict(base, secid=f"90.{code}"), extra_headers=sr.EM_HEADERS,
                               label=f"90.{code} @ {host}")
            probe["summary"] = _summarize_kline(probe)
            out.append(probe)
            if probe.get("json_ok") and (probe["summary"].get("klines_len") or 0) > 0:
                got = True
                break                                  # 该代码已取到日线，不再试镜像
        if not got:
            for fqt in ("0", "2"):
                probe = _http_json(sr.KLINE_URLS[0], dict(base, secid=f"90.{code}", fqt=fqt),
                                   extra_headers=sr.EM_HEADERS, label=f"90.{code} fqt={fqt}")
                probe["summary"] = _summarize_kline(probe)
                out.append(probe)
    return out


def probe_sw_official(sw_code):
    """申万宏源研究所官方指数发布接口（独立备用源）：只探测一个行业，记录最新日期。"""
    import sector_rotation as sr
    probe = _http_json(sr.SW_TREND_URL, {"swindexcode": sw_code, "period": "DAY"},
                       timeout=20, extra_headers=sr.SW_HEADERS, label=f"申万官方 {sw_code}")
    data = probe.get("json") or {}
    rows = data.get("data") if isinstance(data, dict) else None
    probe["summary"] = {"code": data.get("code") if isinstance(data, dict) else None,
                        "rows": len(rows) if isinstance(rows, list) else None,
                        "last": (rows[-1] if isinstance(rows, list) and rows else None)}
    probe.pop("json", None)                            # 整段历史太大，不留原文
    return probe


def run_module():
    """用与 pipeline.safe_request 等价的取数函数跑一遍真实算法（固定 31 个申万一级行业）。"""
    def fetch_json(url, params=None, timeout=15, headers=None):
        probe = _http_json(url, params or {}, timeout=timeout, extra_headers=headers, label="run()")
        return probe.get("json")

    import sector_rotation as sr
    result = {"universe_kind": "sw_l1_fixed", "universe_count": len(sr.SW_L1_SECTORS)}
    started = time.time()
    try:
        res = sr.run(fetch_json, state_path=os.path.join(HERE, "diag_no_state.json"))
        keep = {k: v for k, v in res.items() if k != "scores"}
        keep["scores_top5"] = (res.get("scores") or [])[:5] if res.get("available") else []
        result["run"] = keep
    except Exception as exc:
        result["run_error"] = f"{type(exc).__name__}: {exc}"
    result["elapsed_ms"] = int((time.time() - started) * 1000)
    # 探测不得留下任何策略状态文件
    stale = os.path.join(HERE, "diag_no_state.json")
    for path in (stale, stale + ".tmp"):
        if os.path.exists(path):
            os.unlink(path)
    return result


def build_report(verbose=True, keep_payloads=True):
    """执行三步探测并返回结果字典（供 CLI 与日报内自动诊断共用）。

    keep_payloads=False 时只保留摘要与响应片段，避免把整包行情 JSON 写进存档。
    """
    import sector_rotation as sr
    report = {"probe_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "probe_at_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
              "runner": os.environ.get("GITHUB_RUN_ID", "local"),
              "universe_kind": "sw_l1_fixed", "universe_count": len(sr.SW_L1_SECTORS)}
    log = (lambda *a: print(*a)) if verbose else (lambda *a: None)

    log("=" * 60)
    log(f"🔎 行业轮动数据源探测 · {report['probe_at_cst']} (UTC+8)")
    log("=" * 60)

    # 样本：银行 / 电子 / 农林牧渔（后者也是 run() 用来探测复权口径的第一个行业）
    codes = ["BK1283", "BK1201", "BK0433"]
    log(f"\n[1/3] 申万一级板块日 K（kline · 主源 + 两个镜像）· 样本 {codes}")
    report["klines"] = probe_klines(codes)
    for probe in report["klines"]:
        log(f"  · {probe['label']}: status={probe.get('http_status')} "
            f"err={probe.get('error')} summary={probe['summary']}")

    log("\n[2/3] 行业列表（clist，仅记录；主流程已改用固定表）")
    report["universe"] = probe_universe()
    for probe in report["universe"]:
        log(f"  · {probe['label']}: status={probe.get('http_status')} "
            f"err={probe.get('error')} summary={probe['summary']}")

    log("\n[3/3] 申万官方源（独立备用）+ sector_rotation.run() 端到端")
    report["sw_official"] = probe_sw_official(sr.SW_L1_SECTORS[0][2])
    log(f"  · {report['sw_official']['label']}: status={report['sw_official'].get('http_status')} "
        f"err={report['sw_official'].get('error')} summary={report['sw_official']['summary']}")
    report["module"] = run_module()
    log(f"  · 固定股票池 {report['module'].get('universe_count')} 个 · run="
        + str({k: v for k, v in (report['module'].get('run') or {}).items()
               if k not in ('scores_top5', 'state', 'tracking')}))

    if not keep_payloads:
        for probe in report["universe"] + report["klines"]:
            probe.pop("json", None)
            probe["body_head"] = (probe.get("body_head") or "")[:300]
    return report


def main():
    parser = argparse.ArgumentParser(description="行业轮动数据源在线探测")
    parser.add_argument("-o", "--output", default=None, help="探测结果 JSON 路径")
    args = parser.parse_args()

    report = build_report(verbose=True)
    path = args.output or os.path.join(HERE, "diag", "sector_rotation_probe.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n💾 探测结果已写入: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
