# agent-evolution

离线**进化**一个 agent loop 的 **harness(脚手架)**:把模型权重当作固定,只让 system prompt、工具描述与特性开关(Feature)变。

每一轮,LLM 提案器提出**恰好一处**快照编辑,系统跑**配对 episode**(候选快照 vs 基线快照,同模型同初始状态),用**目标自身的客观门禁**打分,达标则保留该编辑、否则回滚。

> 术语与措辞以 `GLOSSARY.md` 为准;每条关键设计决策记录在 `docs/adr/`。

## 项目目标

- 提供一个**目标无关**的进化闭环:提案 → 配对打分 → 保留/回滚,通过 Adapter 接缝接入任意 agent loop。
- 让 harness 变成**声明式、可 diff、可回滚、可复现**的快照——于是被改造对象是「文件」而不是「代码」。
- 用**零新增模型调用**的确定性打分:直接复用目标 loop 已有的客观门禁(tool-event + 沙箱状态),不引入 LLM 裁判。
- 首个目标(由 `SystemHintAdapter` 接入):`ai-agent-book` 的 `chapter2/system-hint/run_experiment_2_8.py`。

## 约束

1. **只改 harness**:system prompt 文本、`<agent_status>` 状态段模板、工具描述/schema、特性开关。**不含 loop 的控制流代码**,也不改模型权重。
2. **先评测后应用**:任何编辑在成为新基线前,必须先跑配对 episode 并达标;否则回滚。
3. **确定性打分**:门禁只由工具动作、沙箱状态与固定 ground truth 判定,**不采信模型自述**。
4. **一次一处编辑**:提案器每轮只产出一个 `Edit`,保证「一次改动」可核对。
5. **启用集合 = 快照 features ∩ 臂的 protocol condition 列表**:快照与 protocol 共同决定一次 run 启用哪些 feature。`disabled` 臂列表为空,故交集恒空、控制臂始终干净;臂未列出的 feature 翻转是 no-op。
6. **闭集**:快照只能开关目标已认识的 feature;引入全新 feature 仍需改目标代码。
7. **接缝唯一**:只有 `system_hint_adapter.py` 耦合具体目标;上层只依赖 `adapter.py` 定义的 `Adapter` 接缝。
8. **预算与健壮**:token 预算是 run 级软上限;每次运行都以退出码 0 结束,单轮失败不使整个运行崩溃。
9. **两端点独立配置**:被测 agent 沿用目标自己的 provider;提案器走独立的 `EVOLVER_*` 端点。

## 工作原理(一轮)

```
基线快照 ──▶ 跑基线 episode ──▶ 提案器读失败摘要,提出一处 Edit
                                        │
                                        ▼
                              应用 Edit 得候选快照
                                        │
                                        ▼
                        候选 vs 基线 配对 episode + 门禁打分
                                        │
                             ┌──────────┴──────────┐
                          达标保留                不达标回滚
```

停止条件(`StopReason`):轮次耗尽 / token 预算触顶 / 回滚过多 / 提案器失败 / 无可用用例。

## 目录结构

```
src/agent_evolution/
  adapter.py            # Adapter 接缝 + CaseRef / EpisodeResult
  snapshot.py           # Snapshot:声明式 harness 快照(diff/save/load/fingerprint)
  edit.py               # Edit:一处编辑 + 如何应用到快照
  paired.py             # 配对评测 + 接受/回滚判据
  parallel.py           # 同一快照的 episode 批处理(默认顺序,可并发保序)
  proposer.py           # LLM 提案器(仅依赖 ProposerModel 协议,测试可脚本化)
  evolve.py             # 多轮进化循环、run 目录、history、预算
  cli.py                # 命令行:snapshot / evaluate / evolve
  system_hint_adapter.py# 唯一耦合目标的模块:驱动 run_experiment_2_8.py
  target_harness.py     # 从目标抽回 harness 文本(黄金等价性校验)
  text.py
snapshots/system-hint/  # 规范的 golden 快照(canonical)
protocols/              # 进化专用 protocol(从目标冻结件派生,不改冻结件)
tests/                  # pytest;目标或录制缺失时自动 skip
tools/sync_harness.py   # 把 canonical 快照同步/校验进目标仓
tools/build_evolution_protocol.py  # 派生 protocols/system-hint-evolution.json
docs/adr/               # 架构决策记录
docs/agents/            # 给 agent 的仓库约定(issue tracker / 标签 / 领域文档)
runs/                   # 产物目录(进化运行与评测证据)
```

## 如何运行

### 要求

- Python **>= 3.11**。运行时无第三方依赖;开发测试需要 `pytest`。
- 一个可用且能调用 **OpenAI 兼容** chat 端点的环境(被测 agent 与提案器各一个)。
- 目标仓默认位于 `C:\agent\ai-agent-book\chapter2\system-hint`。

### 安装

```powershell
pip install -e ".[dev]"
```

安装后提供命令 `agent-evolution`(等价于 `python -m agent_evolution`)。

### 配置环境变量

被测 agent 的 provider 与 Key **取自目标的 `experiment_protocol.json`** 里的 `provider.name`(不会抓「第一个存在的 Key」):

- `moonshot` / `kimi` → `MOONSHOT_API_KEY`(或 `KIMI_API_KEY`)
- `deepseek` → `DEEPSEEK_API_KEY`
- 其余见 `src/agent_evolution/system_hint_adapter.py` 的 `PROVIDER_KEY_VARS`

提案器(独立端点):

- `EVOLVER_API_KEY`(必填)、`EVOLVER_BASE_URL`(默认 `https://api.moonshot.cn/v1`)、`EVOLVER_MODEL`(默认 `kimi-k3`)

目标定位:

- `AI_AGENT_BOOK_TARGET`(或 `--target-dir`)可覆盖默认目标目录。

### 准备目标

目标从它旁边的 `harness_snapshot/` 读取默认 harness。首次运行前,确保它与本仓的 canonical 快照一致:

```powershell
python tools/sync_harness.py --check      # 只校验
python tools/sync_harness.py              # 不一致时写入
```

### 跑测试

```powershell
python -m pytest
```

- 纯离线:用回放/fake client,不访问网络。
- 涉及目标的测试在目标缺失时 `skip`;回放测试依赖录制轨迹 `runs/exp2-8-kimi-k3-20260730-v1/cases/*.json`。

### 用法

```powershell
# 查看 / 比较快照(不需要网络)
agent-evolution snapshot show snapshots/system-hint
agent-evolution snapshot diff snapshots/system-hint <candidate-dir>

# 对一份候选快照做配对评测(退出码 0=接受,1=回滚)
agent-evolution evaluate --suite combined `
  --baseline snapshots/system-hint --candidate <candidate-dir>

# 从基线出发跑多轮进化
agent-evolution evolve --baseline snapshots/system-hint `
  --suite all --rounds 10 --out runs/evolve/my-run
```

`evolve` 关键参数(默认值):`--suite combined`(可重复;`all` 展开为全部套件)、`--rounds 10`、`--max-failures 5`、`--max-rollbacks 3`、`--budget-tokens`(可选)、`--resamples 10000`、`--seed 20261015`、`--workers`(默认读 `AGENT_EVOLUTION_WORKERS`,否则 1)、`--protocol`(默认读 `AGENT_EVOLUTION_PROTOCOL`,否则目标自带)。

### 用例集与 protocol

目标是 `kimi-k3`,在 `todo_list` 上有真实空间,**默认跑冻结件即可**(`eval-exactness-hint`、`evolve-kimi-digest-fix` 都接受)。但目标的 `experiment_protocol.json` 是**冻结件**:它的 `protocol_sha256` 已写入已发布战役证据,README 也写死每对照 5 例;就地改会让那些声明失效。

当基线失败率接近判据边界时(n=5 时 net +4-of-5 恰好压线),用派生件**同型扩用例**让 accept 稳健:

```powershell
python tools/build_evolution_protocol.py          # 生成 protocols/system-hint-evolution.json
python tools/build_evolution_protocol.py --check  # 校验派生件是否仍与冻结件同步

agent-evolution evolve --baseline snapshots/system-hint --suite todo_list --workers 4 `
  --protocol protocols/system-hint-evolution.json --out runs/evolve/my-run
```

- 派生件**只覆盖 `cases.todo_list`**:冻结 5 例居前逐字节保留,再追加 5 例**同型**用例(一个纯 token + 4 个 `.txt` 产物,产物名全协议唯一);并多一个 `evolution_extension` 记录来源 `protocol_sha256` 与追加明细。`provider`/`pricing` 等其余字段与冻结件逐字节等价。
- **不换被测、不加难用例**:两者都实测否掉——`deepseek-v4-flash` 在 6 套件 30/30、在 10 例难用例上仍 10/10(零空间);循环真正卡住的是提案器看不到失败原因(见下)。
- 选择顺序:`--protocol` > `AGENT_EVOLUTION_PROTOCOL` > 目标自带的 `experiment_protocol.json`。
- 冻结件一字不改;持久化证据带派生件自己的 `protocol_sha256`,不会与已发布战役混淆。详见 `docs/adr/0008`。

### 失败摘要

提案器每轮读到的**失败摘要**会渲染:门禁正文(`gate {suite}: ...`,即这条门禁到底要求什么)、以及每条消息里工具调用的**名称与 arguments**(产物内容就在 arguments 里)。丢掉 arguments 会让提案器看到「文件都写了、提交也齐」而无从判断失败原因——这是 0 accept 的真正根因。详见 `docs/adr/0009`。

### 提速

- **并发**：`--workers N`(或环境变量 `AGENT_EVOLUTION_WORKERS=N`)并行跑同一快照的一批 episode(保序,上限为用例数)。默认 1 = 旧的顺序行为。`.env` 无此变量时行为逐字节不变。
- **基线复用**：回滚后基线快照不变,其 episode 与提案器失败摘要跨轮复用,不再每轮重跑。
- 二者只改「谁在跑 / 跑几次」,**不改变**接受/回滚判据与随机种子。详见 `docs/adr/0007`。

### 产物

- `evolve`:run 目录下每轮 `rounds/NN/`(`edit.json`、`baseline/`、`candidate/`、`summary.json/txt`、`decision.json`),run 级 `history.json` / `history.md`。
- `evaluate`:输出目录下 `summary.json` 与配对报告。

## 文档索引

- `GLOSSARY.md` —— 领域术语(唯一权威措辞)。
- `docs/adr/0001`–`0009` —— 关键设计决策与取舍。
- `docs/agents/` —— issue tracker、triage 标签、领域文档布局等仓库约定。
- `AGENTS.md` —— 给 agent 的入口。
