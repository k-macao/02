# Jev 开源模型 · 接入可行性验证

> 问题：**测试能否接入 GitHub 开源的 Jev 类似模型策略。**
> 结论：**能接，而且已经接上了接入层并跑通离线全链路；但"预测力"和"真权重"两件事还没被验证完**——前者只能靠留痕结算慢慢验，后者卡在本沙箱出不了 Hugging Face 的网（CI 探针已备好，一键可跑）。
> 日期：2026-10-03 · 关联文件：`output/jev_bridge.py`、`tools/jev_mock_server.py`、`tests/test_jev_bridge.py`、`.github/workflows/jev-integration-probe.yml`

## 0. 结论速览

| 问题 | 结论 | 证据 |
|---|---|---|
| Jev 是什么？有没有开源可用？ | **有**，且不止一个；全是"只判断不生成"的类型化决策模型 | laya（30.4k★，Apache-2.0）、kev（8.4k★）、NanoJev（2.5k★，MIT）、OpenJev-Kit、EdgeJev |
| 我们的机器/CI 跑得动吗？ | **跑得动**：运行时只要 `onnxruntime + tokenizers + numpy`，**不需要 torch、不需要 GPU、不需要 API Key** | 本沙箱实装 `edgejev 0.3.2` 成功，`edgejev info` 打印 CPU provider 与三个已注册后端 |
| 协议能不能对上我们的栏目？ | **能**：官方 `POST /v1/systemone` 的三个原语正好覆盖日报要的三类判断 | 方向=choice、涨跌概率=noul、风险等级=score |
| 护栏够不够？ | **够，且能复用现有口径**：收敛阈值、概率夹边、留痕结算全部复用 `hk_seven_day` 同一份常量 | 35 项离线回归全绿（7.0s） |
| 真权重跑起来了吗？ | **没跑起来**，唯一卡点是 **Hugging Face 出网被拦**（本沙箱）；代码链路已用协议回声服务等价验证 | `snapshot_download` 实测报 `ConnectError: TLS/SSL connection has been closed (EOF)` |
| 值得接吗？ | **值得试，但要当研究信号**：它恰好能填上现在这块空缺（见 §5），且零 API 成本 | 生产上 `hk7_forecast.json` **0 条留痕**，2026-10-03 日报正文写着「暂缺：AI 七日港股」 |

## 1. 验证环境与复现命令

本轮所有结论都跑过一遍，命令如下（Python 3.11.2，2 vCPU，无 GPU）：

```bash
# ① 装开源本地运行时（小时级零依赖，不装 torch）
python3 -m venv /tmp/jevtest && /tmp/jevtest/bin/pip install edgejev
/tmp/jevtest/bin/edgejev info

# ② 接入层离线全链路（无权重 / 无 Key / 无外网，只用 127.0.0.1 回环）
python3 tests/test_jev_bridge.py                        # 35 项回归
python3 tools/jev_mock_server.py --port 8811 &          # 协议兼容回声服务
python3 output/jev_bridge.py --check --base http://127.0.0.1:8811
python3 output/jev_bridge.py --demo  --base http://127.0.0.1:8811

# ③ 真权重（需要 Hugging Face 出网，本沙箱做不到；在 GitHub Actions 上可跑）
#   工作流已在 main 上：2026-10-04 由 k-macao 提交（.github/workflows/jev-integration-probe.yml）
#   手动 Run workflow 勾 build_model，或在提交信息里带 [jev-model]
```

## 2. Jev 是什么，开源生态长什么样

Jev（TypeSafe 的 System One）走的是一条和大模型相反的路线：**砍掉文本生成，只输出类型化的判断和已校准的概率**。三个原语：

| 原语 | 语义 | 返回 | 对应日报里的判断 |
|---|---|---|---|
| `choice` | 在候选里选一个 | `choice` + 各选项概率 + 置信度 | 未来 7 日方向（上行 / 震荡 / 下行） |
| `score` | 按档位打分 | 期望分 + 各档概率 | 不确定性 / 风险等级 |
| `noul` | 命题是否成立 | P(真) | P(未来 7 日收涨) |

一次前向答完多题（多题打包进一条序列，用 block-causal 掩码隔离），**没有生成、没有 JSON 解析、没有重试**——这也带来一个今天被验证到的副作用，见 §4。

### 开源可选（GitHub，2026-10-03 实测数据）

| 项目 | ★ | 许可证 | 骨干 / 体积 | 单题延迟 | 备注 |
|---|---:|---|---|---:|---|
| [laya](https://github.com/NandhaKishorM/laya) | 30.4k | Apache-2.0 | mmBERT-base 322M · int8 **324 MB** | **15.6 ms** | 精度最好（AG News 91.2%），EdgeJev 与其 PyTorch 逐位一致 |
| [kev](https://github.com/jaredpalmer/kev) | 8.4k | Apache-2.0 | Qwen2.5-0.5B + LoRA · fp32 1978 MB | 44 ms | 量化后精度塌得厉害（emotion 44%→21%），只能用 fp32 |
| [NanoJev](https://github.com/TianyuCodings/NanoJev) | 2.5k | MIT | Qwen3-0.6B + 标量头 · 2389 MB | 155 ms | **只在游戏决策上训练**，通用分类接近随机（AG News 20%） |
| [EdgeJev](https://github.com/yzfly/edgejev) | 15 | Apache-2.0（README 标注） | 统一 laya/kev/nanojev/playjev 的转换+量化+部署 | — | 我们实际用的落地工具：`edgejev build` / `serve` |
| [OpenJev-Kit](https://github.com/meijustory123/OpenJev-Kit) | 0 | **无许可证** | Qwen3.5-0.8B 全量微调 752M | — | 训练流程完整，但无许可证 → 只能看思路，别抄代码 |
| [jev-trading](https://github.com/EthanAlgoX/jev-trading) | 3 | **无许可证** | Bun + TS 的选股服务 | — | 有"数据护栏 + 动作校验 + 留痕"的工程范式可借鉴 |

**官方托管 API 的对照**：Jev 1.13 实测中位 314 ms（含网络往返），AG News 85.5% / emotion 61.5%——也就是说 laya 在分类任务上打平或更好，且本地跑没有网络往返、没有按 token 计费。对我们这种"每天跑几次、每次几十题"的日报场景，**本地 ONNX 是明显更合适的一档**。

## 3. 实测记录（原始输出）

### 3.1 运行时装得动，CPU 就能跑

```text
onnxruntime 1.30.0 | 选用 CPU（linux x86_64） | 可用 AzureExecutionProvider, CPUExecutionProvider
已注册后端: kev, laya, playjev
```

Python 3.11 + 2 vCPU 环境，装的是 PyPI 上的 `edgejev 0.3.2`，依赖只有 `onnxruntime 1.30.0 / tokenizers 0.23.2 / numpy 2.4.6 / huggingface_hub 1.33.0`——**没有 torch**（约 324 MB 的 int8 模型，跑分见上表）。

### 3.2 构建路径的依赖解析（一次性，用来转 ONNX）

`pip install "edgejev[build]"` 的 dry-run 结果：会拉 `torch-2.14.1`、`transformers-5.18.0`、`laya-0.3.25`、`onnx-1.23.1`、`onnxconverter-common-1.16.0`、`peft-0.21.2`，**并连带整套 `nvidia-cu13` 轮子（数 GB，构建根本用不上 GPU）**。

> 结论：CI 上必须先 `pip install torch --index-url https://download.pytorch.org/whl/cpu` 再装 `edgejev[build]`，否则 runner 磁盘和下载时间都要翻好几倍。探针工作流已经这么写了。

### 3.3 唯一卡点：Hugging Face 出网

```text
FAILED: LocalEntryNotFoundError
Got: ConnectError: TLS/SSL connection has been closed (EOF)
（域名能解析到 3.165.160.12，TCP/TLS 被出口策略拦掉）
```

本沙箱放行了 GitHub 与 PyPI，**没有放行 Hugging Face / hf-mirror / ModelScope**，因此 1.3 GB 的 laya 权重下不来。这不是代码问题：GitHub Actions 的 runner 默认可以出网，探针工作流第 ③ 步就是为它准备的；跑完还会把 324 MB 的 ONNX 目录作为 artifact 上传，**拉一次就能拷进内网离线用**。

### 3.4 接入层离线全链路（35 项回归 + 回环自检）

```text
Ran 35 tests in 7.048s
OK

$ python3 output/jev_bridge.py --check --base http://127.0.0.1:8811
✅ 就绪：mock-jev-echo（echo/n/a）

$ python3 output/jev_bridge.py --demo --base http://127.0.0.1:8811
◈ 恒生指数（^HSI）
  闭合自检：闭合：只含当次快照字段（t 及之前）
  [choice] dir → up {'up': 0.431, 'flat': 0.328, 'down': 0.240}
  [noul]   p_up → P=0.1804（置信 0.8196）
  [score]  risk → 2.7236（置信 0.5237）
  合并：P(7日涨)=0.3600 | 量化基准=0.5600 | 来源=noul | 收敛=True
  说明：模型概率 0.180 偏离基准 0.560 超过 20%，已收敛
```

这段是**回声服务**（`tools/jev_mock_server.py`，标准库实现同一套协议）跑出来的，概率本身没有预测力——它验证的是协议、结构校验、收敛护栏、缺席降级、留痕结算这五层。**权重只影响"概率准不准"，不影响这五层**，所以这五层可以在这里被钉死。

### 3.5 CI 探针预演（把工作流里的 shell 原样在本地跑一遍）

```text
=== [protocol-offline] 🧪 跑接入层回归（纯标准库） ===        → Ran 35 tests OK
=== [protocol-offline] 🌀 协议回环自检 ===                     → ✅ 就绪：mock-jev-echo
  [choice] dir → up {'up': 0.99, 'flat': 0.005, 'down': 0.005}
  [noul]   p_up → P=0.9950（置信 0.995）
  合并：P(7日涨)=0.7600 | 量化基准=0.5600 | 来源=noul | 收敛=True
=== [protocol-offline] 🛡️ 断言护栏生效 ===                     → ✅ 收敛护栏成立
=== [edgejev-runtime] 🌐 探测 Hugging Face 可达性 ===          → ⚠️ 不可达（脚本按预期降级）
```

也就是说：**探针工作流的第 ①② 步现在就能跑通**（本地已按步骤逐个复现），只有第 ③ 步（真权重）和 `edgejev` 命令本身需要外网/runner 环境。

### 3.6 CI 真机结果（2026-10-04，PR #111 合并后自动触发）

PR #111 合并（`3b2a280`）触发了探针工作流，这是**第一次在真 GitHub runner 上跑**：

| 作业 | 结果 | 说明 |
|---|---|---|
| ① 接入层离线回归 | ✅ **success** | 35 项回归 + 协议回环 + 收敛断言，干净 runner 上全绿 |
| ② 开源本地运行时 | ✅ **success** | `pip install edgejev` 可装、ONNX Runtime 正常、PyPI 出网正常 |
| ③ 真权重端到端 | ❌ **failure** | 卡在「🏗️ 构建本地 ONNX 模型」步骤，**28 秒失败**（job 总时长 1 分 41 秒） |

**两个发现**（都属于工作流缺陷，不是接入层的问题）：

1. **触发条件太宽**：③ 本不该在合并时启动。`contains(head_commit.message, '[jev-model]')` 把**提交正文里顺带提到这个标记**的合并提交也算上了（我的合并提交正文写了一句「或在提交信息里带 `[jev-model]`」）→ 改为 `startsWith(...)`，标记必须在提交信息第一行行首。
2. **③ 秒级失败的合理怀疑是依赖跨大版本**：`laya` 与 `edgejev` 都只声明下界（`transformers>=4.48.0`、`huggingface_hub>=0.20.0`），pip 会解析出 `transformers 5.18.0` / `huggingface_hub 1.33.0` 这种**跨大版本**组合（本地 dry-run 实测解析结果），而 `edgejev build` 是按 4.x / 0.x 写的。

> ⚠️ 证据边界：GitHub 的**日志下载主机在开发沙箱被拦截**（`pipelines.actions.githubusercontent.com` / `results-receiver` 均不通），job 页面又要求登录，所以**原始报错我读不到**。上面第 2 条是**推断**（有版本解析证据支撑，但未经日志确认），不是结论。

**已按此修好工作流（待提交）**：钉住 `transformers>=4.48,<5` / `huggingface_hub>=0.20,<1` / `numpy<2.3` / `tokenizers<0.23`（本机 dry-run 可满足），并做**失败自证**——打印全部关键依赖版本、`edgejev build` 输出 `tee` 到文件，失败时把尾部 40 行写进 job summary 并 `::error::` 点名。这样下一跑无论成败都会给出确切原因，不再依赖我读得到日志。

### 3.7 全仓回归（确认没有踩到既有功能）

```text
$ python3 -m unittest discover -s tests
Ran 715 tests in 116.643s
FAILED (failures=5, skipped=1)
```

5 项失败全部落在 `tests/test_public_sites.py`（Reddit / StockTwits / TradingView / 新闻窗口的时间敏感用例）。为避免误判，我把基线提交 `2141e7a` 单独解包到别处跑了同一组用例——**同样的 5 项失败**，说明是既有问题（与时间/公开站点有关），**与本轮新增文件无关**。本轮新增的 35 项全绿。

## 4. 接入设计：三块，全部复用现有口径

```
state（闭合快照，只含 t 及之前）  ──►  POST /v1/systemone
   · 白名单 21 个标量字段（symbol/close/ret5..60/ma20_dev/rsi14/vol_pct/…）
   · 黑名单 actual_ret / hit / settle_date / target_close …（出现即拒）
        │
        ├─ choice  dir   ：未来 7 日方向（上行 / 震荡 / 下行）
        ├─ noul    p_up  ：P(7 日后收盘更高)
        └─ score   risk  ：不确定性等级（5 档）
        ▼
结构校验（概率和 1±0.05、choice 与最大概率一致、noul∈[0,1]）
        ▼
概率对账（复用 hk_seven_day 的 MAX_PROB_DEVIATION=0.20 / PROB_FLOOR-CAP=5%~95%）
        ▼
留痕（output/jev_forecast.json，settled=False，满 7 个交易日后按真实收盘结算）
```

护栏与原「大模型研判层」的对照——**能共用的全部共用，不另立一套**：

| 护栏 | 原大模型层（hk_seven_day） | Jev 接入层（jev_bridge） |
|---|---|---|
| 概率夹边 | 5%~95% | **同一份常量**（`import` 自 hk_seven_day） |
| 偏离收敛 | >20pp 收敛到基准 ±20pp | **同一份常量**，同一算法 |
| 数字溯源 | 文案里每个数字都要能溯源（正则逐条比对） | **天然不需要**：不产文本，没有编数字的入口；改成"概率对账 + 来源标注" |
| 绝对化措辞 | 命中即退回 | 不适用（不产文本） |
| 缺席口径 | 无 Key → 整栏缺席 | 无端点 → 整栏缺席；调用失败 → 逐标的记因并回退量化基准 |
| 防未来函数 | 输入闭合 + 目标日严格在后 | 白名单裁字段 + 黑名单拒标签 + 目标日检查 |
| 留痕结算 | `hk7_forecast.json` | `jev_forecast.json`，**同一套 `_load/_save/_settle/_journal_stats`** |

### 一个协议级的坑（已固化成护栏）

Jev 的多个问题是**各自独立作答**的（兄弟题互相看不到，这是 block-causal 掩码的设计，好处是问题顺序不影响结果）。所以同一份 state 下，"方向题"和"命题题"给出的信号**不保证自洽**——上面的演示就是例子：`dir` 给了 up 0.431，而 `p_up` 给了 0.18。

处理：① 以命题题（noul）为准，方向题（choice）只用于展示与兜底；② 差异 >0.25 时在结果里加 `coherence` 提示位并在文案里说明"各题独立作答"，**不做硬校验**（硬校验会把合法输出当错误丢掉）。

## 5. 为什么这块值得接（而不是"已有大模型就够"）

生产上 **AI 七日港股这一栏其实长期是缺的**：`output/hk7_forecast.json` 现在 **0 条**留痕，2026-10-03 的日报正文里写着「**暂缺：AI 七日港股**」——因为没配 `OCTOPUS_LLM_API_KEY`，该子块按设计整体缺席。

Jev 这类本地模型恰好补这个空：

| | 云端大模型（现有可选层） | Jev 本地模型（本轮验证） |
|---|---|---|
| 成本 | 按 token 计费，没 Key 就缺席 | **零 API 成本**，模型拉一次就离线可用 |
| 出网 | 必须出网 | 推理**完全不出网**（数据不出本机） |
| 输出 | 文本 + 数字，需三道护栏 | 只有值 + 概率，**没有幻觉数字的入口** |
| 可解释性 | 有解释（这也是它贵的原因） | **没有解释**，需要文案时仍走量化模板 |
| 稳定性 | 受供应商/限流/JSON 截断影响 | 固定权重 + 本地前向，可复现 |

**定位建议：Jev 当"概率裁判"（方向 / 概率 / 风险等级），文案继续用现有量化模板；不要用它替代解释性文本层。** 三者可以并列存在：LLM 有 Key 就用 LLM，没 Key 就用 Jev（本地），两者都没有就按现在的口径缺席。

## 6. 还没验证完的两件事（不要当成已验证）

1. **真权重端到端**：还没跑通，且已有一条真机证据——2026-10-04 的 CI 里 ③ 在「构建模型」步骤 **28 秒失败**（① 接入层回归、② 运行时安装均已通过）。原始报错读不到（日志主机被沙箱拦），合理怀疑是依赖跨大版本（见 §3.6），修好的工作流已加入钉版本 + 失败自证。→ **在下一跑拿到确切原因前，不要对外说"已经接上真模型"**。
2. **预测力**：即便真模型跑起来，laya/kev 都是通用文本决策模型，**没有任何证据表明它在"恒指未来 7 日方向"上有边际**。上游实测里 laya 在 AG News 强、在情感细分类上弱于官方 API，说明"选对模型"依赖任务本身。→ 建议按仓库既有口径先当研究信号：**先留痕、后结算**，`jev_forecast.json` 满 10 个样本前只报样本量、不下命中率结论（`MIN_JOURNAL_FOR_HITRATE` 同一口径），进了推送门禁再说。

其他需要盯的限制：模型体积（int8 324 MB，仓库不适合直接入库，走 artifact/缓存）；协议生态很新（各复现项目的接口细节仍在变，所以接入层做了严格结构校验 + 逐项记因）；**许可证**：laya/kev/MIT 的 NanoJev 可放心用，OpenJev-Kit 与 jev-trading 无许可证，别直接抄代码。

## 7. 落地清单（都是小改动）

| 优先级 | 动作 | 说明 |
|---|---|---|
| P0 | 跑 CI 探针第 ③ 步 | ✅ ①② 已在真 runner 上通过（2026-10-04）；③ 需先提交修好的工作流（钉大版本 + 失败自证，见 §3.6），再 Run workflow 勾 `build_model`（或提交信息**第一行**以 `[jev-model]` 开头）|
| P0 | 把 Jev 接进 `fetch_hk_seven_day` 作为第三条引擎 | 复用 `_hk_seven_day_block`：`engine` 加一档 `"jev"`、文案标注「Jev 本地模型 · laya int8 · 概率已按基准收敛」；缺席时行为与现在完全一致 |
| P1 | 在日报「数据覆盖」里点名 Jev | 与「AI 七日港股暂缺」并列，标明是端点没配还是调用失败 |
| P1 | 把 35 项回归纳入 CI | 目前仓库没有测试工作流；`tests/test_jev_bridge.py` 纯标准库，30 秒可跑完 |
| P2 | 真权重跑通后做 A/B | 同一批 history 分别用「量化基准 / Jev / LLM」留痕，按 Brier 分数比较（结算口径已经统一） |

## 8. 本轮新增文件

| 文件 | 作用 |
|---|---|
| `output/jev_bridge.py` | 接入层：闭合快照、三原语提问、结构校验、概率对账、留痕结算、`--check` / `--demo` CLI |
| `tools/jev_mock_server.py` | 协议兼容回声服务（标准库）：无权重 / 无 Key / 无外网也能验证接入层 |
| `tests/test_jev_bridge.py` | 35 项离线回归：配置、闭合自检、协议、结构校验、收敛护栏、跨题独立性、401/500/超时/断连降级、留痕结算 |
| `.github/workflows/jev-integration-probe.yml` | CI 探针（2026-10-04 已上 main）：①离线回归 ②运行时 + HF 可达性 ③真权重端到端 |

> 免责：本文与新增代码均为研究/工程验证，概率不是保证，不构成投资建议。
