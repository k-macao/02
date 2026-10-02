# VENDORED —— 本目录是第三方项目的本地镜像

| 项 | 值 |
|---|---|
| 上游仓库 | <https://github.com/whaleyxbt/patchright-enhanced> |
| 上游提交 | `e38ab7ab9448db6f093f72ee097c18ca9905e84c`（2026-09-20，`Delete src/leadFormConfig.ts`） |
| 拉取日期 | 2026-10-02（北京时间） |
| License | 上游仓库未附 License 文件；仅作本仓库内部工具使用，如需再分发请先与上游确认 |
| 本地改动 | 新增 `VENDORED.md`、`probe.js`、`proxies.txt.example`；另修一处上游类型报错——`src/types/config.types.ts` 把 `locale` 改为可选（上游注释掉 `locale` 后 `tsc` 报 TS2741，`npx tsc --noEmit` 无法通过），其余源码原样未改 |

## 为什么 vendor 进来

日报流水线需要读取**境外港股数据源**（香港 / 国际财经站点）。其中一部分站点
（etnet 經濟通、aastocks 阿斯達克、investing.com、HKEX 部分页面）带
Cloudflare / Kasada / DataDome 等 WAF，普通 `requests` 取回来的是挑战页或空壳 HTML。

本目录提供的能力 = 上游的 stealth Chrome 会话（patchright 内置反检测补丁），
再由 `probe.js`（本仓库新写的适配器）把「渲染后的页面文本」以 JSON 交给 Python：

```
output/hk_overseas.py  ──subprocess──▶  node probe.js  ──patchright──▶  境外站点
        ◀──────────── JSON: {results:[{name,url,text,...}]} ─────────────┘
```

## 运行前置

```bash
cd tools/patchright-enhanced
npm install                     # 或 pnpm install（仓库自带 pnpm-lock.yaml）
npx patchright install chrome   # 依赖外网下载 Chrome，沙箱里可能被出口策略挡住
```

≥ Node 18。`probe.js` 只依赖 `patchright`，不依赖 `ts-node` / `dotenv`。

## probe.js 用法

```bash
# 单页调试（输出 JSON）
node probe.js --url 'https://www.etnet.com.hk/www/tc/stocks/realtime/quote.php?code=700'

# 供 Python 调用：stdin 收 JSON，stdout 回 JSON
echo '{"targets":[{"name":"etnet","url":"https://www.etnet.com.hk/..."}]}' | node probe.js
```

支持的环境变量：`BROWSER_EXECUTABLE_PATH`、`BROWSER_TIMEZONE`、`HEADLESS=0`（有头调试）、
`PROBE_MAX_TEXT`（单页返回文本上限，默认 200000 字符）。

## 边界与诚实口径

- **默认不启用**：日报流水线只在 `OCTOPUS_HK_BROWSER=1` 且 `node` / `patchright` / Chrome
  都可用时才走浏览器取数；任一条不满足就跳过这一路，其余数据源照常，绝不用它编造数字。
- **不绕过登录**：仅读取公开页面；付费墙 / 登录墙内容一律标记「暂缺」。
- **代理**：需要代理时把 `proxies.txt`（`host:port:user:pass`，一行一条）放进本目录，
  格式与上游一致；示例见 `proxies.txt.example`。请自行确保抓取行为符合目标站点条款。
