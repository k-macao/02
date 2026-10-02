#!/usr/bin/env node
/**
 * probe.js —— 港股境外数据源 · stealth 浏览器取数适配器（章鱼 AI 日报专用）
 *
 * 作用：用上游 patchright-enhanced 同款 stealth Chrome 打开一批公开页面，
 *       把「渲染后的页面文本」以 JSON 交给 output/hk_overseas.py 解析。
 *       只读公开页面，不登录、不提交表单、不绕过付费墙。
 *
 * 输入（两种，任选其一）：
 *   A. stdin JSON：{"targets":[{name,url,selector?,wait_ms?,timeout_ms?,max_text?}], "headless":true}
 *   B. 命令行：node probe.js --url https://... [--url https://...] [--headless 0] [--wait-ms 3000]
 *
 * 输出（stdout，唯一一行 JSON；日志一律走 stderr，避免污染）：
 *   {"ok":true,"results":[{"name","url","ok","status","title","text","error"}],"elapsed_ms":1234}
 *
 * 依赖：patchright（本目录 npm install 后可用）。环境变量见 VENDORED.md。
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const DEFAULT_MAX_TEXT = parseInt(process.env.PROBE_MAX_TEXT || '200000', 10);
const DEFAULT_NAV_TIMEOUT = parseInt(process.env.PROBE_NAV_TIMEOUT_MS || '30000', 10);

function log(...args) {
  process.stderr.write('[probe] ' + args.join(' ') + '\n');
}

function readStdin() {
  return new Promise((resolve) => {
    let buf = '';
    if (process.stdin.isTTY) return resolve('');
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { buf += chunk; });
    process.stdin.on('end', () => resolve(buf));
    process.stdin.on('error', () => resolve(buf));
  });
}

function parseArgv(argv) {
  const out = { urls: [], headless: undefined, waitMs: undefined, maxText: undefined };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--url') { out.urls.push(argv[++i]); }
    else if (a === '--headless') { out.headless = argv[++i] !== '0'; }
    else if (a === '--wait-ms') { out.waitMs = parseInt(argv[++i], 10); }
    else if (a === '--max-text') { out.maxText = parseInt(argv[++i], 10); }
    else if (a === '--help' || a === '-h') { out.help = true; }
  }
  return out;
}

function loadProxies() {
  // 与上游 proxy.config.ts 同格式：host:port:username:password（一行一条，# 注释）
  const file = path.resolve(__dirname, 'proxies.txt');
  if (!fs.existsSync(file)) return [];
  try {
    return fs.readFileSync(file, 'utf-8')
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith('#') && l.includes(':'))
      .map((line) => {
        const parts = line.split(':');
        return { server: `http://${parts[0]}:${parts[1]}`, username: parts[2], password: parts[3] };
      });
  } catch (err) {
    log('读取 proxies.txt 失败：' + err.message);
    return [];
  }
}

async function main() {
  const argv = parseArgv(process.argv.slice(2));
  if (argv.help) {
    process.stdout.write(JSON.stringify({
      ok: true,
      usage: 'node probe.js --url <url> [--url <url>...]  或  echo {"targets":[...]} | node probe.js',
    }) + '\n');
    return;
  }

  let payload = {};
  const stdin = await readStdin();
  if (stdin && stdin.trim()) {
    try {
      payload = JSON.parse(stdin);
    } catch (err) {
      throw new Error('stdin 不是合法 JSON：' + err.message);
    }
  }

  const targets = Array.isArray(payload.targets) && payload.targets.length
    ? payload.targets
    : argv.urls.map((url, i) => ({ name: `url-${i + 1}`, url }));

  if (!targets.length) {
    throw new Error('没有目标：请用 stdin JSON.targets 或 --url 指定页面');
  }

  const headless = payload.headless !== undefined
    ? !!payload.headless
    : (argv.headless !== undefined ? argv.headless : process.env.HEADLESS !== '0');
  const timeout = parseInt(payload.timeout_ms || DEFAULT_NAV_TIMEOUT, 10);
  const maxText = parseInt(payload.max_text || argv.maxText || DEFAULT_MAX_TEXT, 10);

  let chromium;
  try {
    ({ chromium } = require('patchright'));
  } catch (err) {
    throw new Error('未安装 patchright：先在本目录执行 npm install（详见 VENDORED.md）');
  }

  const proxies = loadProxies();
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'octopus-probe-'));
  const launchOptions = {
    channel: 'chrome',
    headless,
    executablePath: process.env.BROWSER_EXECUTABLE_PATH || undefined,
    timezoneId: process.env.BROWSER_TIMEZONE || 'Asia/Hong_Kong',
    viewport: { width: 1366, height: 900 },
    // patchright 已内置反检测；这里只补上游同款 flag，不注入指纹脚本。
    args: ['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage'],
  };
  if (proxies.length) {
    launchOptions.proxy = proxies[0];
    log(`使用代理 ${proxies[0].server}`);
  }

  const started = Date.now();
  const results = [];
  let context;
  try {
    context = await chromium.launchPersistentContext(userDataDir, launchOptions);
    for (const t of targets) {
      const rec = { name: t.name || t.url, url: t.url, ok: false, status: null, title: '', text: '', error: null };
      let page;
      try {
        page = await context.newPage();
        const resp = await page.goto(t.url, {
          waitUntil: t.wait_until || 'domcontentloaded',
          timeout: parseInt(t.timeout_ms || timeout, 10),
        });
        rec.status = resp ? resp.status() : null;
        if (t.selector) {
          try {
            await page.waitForSelector(t.selector, { timeout: parseInt(t.selector_timeout_ms || 8000, 10) });
          } catch (err) {
            rec.error = '等待选择器超时（照常返回当前文本）';
          }
        }
        const waitMs = parseInt(t.wait_ms || argv.waitMs || 0, 10);
        if (waitMs > 0) await page.waitForTimeout(waitMs);
        rec.title = await page.title().catch(() => '');
        const text = await page.evaluate(() => (document && document.body ? document.body.innerText : ''));
        rec.text = String(text || '').slice(0, maxText);
        rec.ok = rec.text.trim().length > 0;
      } catch (err) {
        rec.error = String((err && err.message) || err);
      } finally {
        if (page) await page.close().catch(() => {});
      }
      results.push(rec);
    }
  } finally {
    if (context) await context.close().catch(() => {});
    try { fs.rmSync(userDataDir, { recursive: true, force: true }); } catch (err) { /* 忽略 */ }
  }

  process.stdout.write(JSON.stringify({ ok: true, results, elapsed_ms: Date.now() - started }) + '\n');
}

main().catch((err) => {
  process.stdout.write(JSON.stringify({ ok: false, results: [], error: String((err && err.message) || err) }) + '\n');
  process.exit(0); // 退出码恒为 0：失败信息走 JSON，Python 侧按内容判定，不因 Node 报错打断整条流水线
});
