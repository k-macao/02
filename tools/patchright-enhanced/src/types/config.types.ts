export interface BrowserConfig {
  headless: boolean;
  executablePath: string;
  // 本地补丁（2026-10-02）：上游把 locale 注释掉后类型仍要求必填，`tsc` 报 TS2741；
  // 这里改为可选，语义不变（ctx-factory 里 locale 本就未启用）。详见 VENDORED.md。
  locale?: string;
  timezoneId: string;
}

export interface ProxyConfig {
  server: string;
  username: string;
  password: string;
}

export interface AppConfig {
  browser: BrowserConfig;
  proxy: ProxyConfig;
  maxParallel: number;
  sessionsDir: string;
}
