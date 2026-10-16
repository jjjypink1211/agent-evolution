# 失败摘要必须带上工具调用参数与门禁定义

- **Status**: Accepted
- **Date**: 2026-10-16

## Context

真实 `evolve` 连续三轮全部回滚（净胜 +2 / +1 / +2，下界恒 +0.000），n≈10 也一样。按 ADR-0008 的推理，第一反应是「效应太小 → 换被测 / 加难用例」，但两处都被实测否掉（DeepSeek 在 6 套件 30/30、在 10 例难用例上仍 10/10）。

回头看**提案器到底看到了什么**，才找到真正的根因。免费取证（复用已有的失败 episode 证据，不花任何模型调用）显示 kimi 的 `todo_list` 失败**不是能力不足**：

- 4 个产物都写了、token 都在文件里、提交也齐、`complete=True`；
- 但内容是**散文**——`Delivery inputs\nIdentifier: BRAVO-528\n...`；
- 而门禁是逐字节相等：`(root/"artifacts"/f).read_text().strip() == case["token"]`（`run_experiment_2_8.py:499`）。

即一个**遵循性失败**（没听「exactly the token」），正是提示词/工具描述能救的那类。可提案器看不到这一点，因为 `failure_digest` 是瞎的：

1. **丢掉了 `tool_calls` 的 arguments**。`failure_digest` 只渲染 assistant 消息的 `content` 与工具事件的返回值（`Wrote artifacts/inputs.txt`），而**产物内容恰恰在 arguments 里**。提案器看到「文件都写了、提交齐了、complete=True」，无从判断失败在「内容必须恰好是 token」。
2. **不说明门禁要求什么**。摘要里只有 `failed_gates=['todo_list']` 这个**标签**，没有 `objective_gates["todo_list"]` 的**正文**（「all four required sandbox artifacts exist with exact case token and submission lists every artifact」）。

结果提案器只能瞎猜「加个验证步骤」，三轮只挪 ±2。

## Decision

- 新增 `_render_message(message)`（`system_hint_adapter.py:76`）：除 `role: content` 外，把每个工具调用的**名称与 arguments** 渲染成 `call {name}({arguments})`，与既有的工具事件行并列。arguments 是模型自己写进文件的内容所在，必须可见。
- `failure_digest`（`:189`）在 transcript 前加一行 `gate {suite}: {gate}`，取 `self._protocol["objective_gates"][case.suite]`，把「失败的门禁到底要求什么」写进摘要。
- 摘要的既有截断不变：`DIGEST_TURN_LIMIT=24`（最后 24 条消息）、`DIGEST_CHARS=400`（单字段截断）。

## Considered Options

- **换被测模型 / 加难用例**：实测双否（ADR-0008 记录了完整数据）。它们在**错误的层次**上使劲——失败不在能力，而在提案器看不见失败的原因。
- **把整份 evidence JSON 塞给提案器**：信息最全，但体积失控、且大量无关的 usage/时间戳会稀释信号，还需处理截断。只把「模型写了什么 + 门禁要什么」提出来足够。
- **只加门禁正文、不加 arguments**：能提示「要恰好是 token」，但看不到模型当前写成什么样，提案器仍难以形成「把它包在散文里了」的因果判断。两者要一起给。
- **让目标侧改证据格式**：会碰冻结战役的产物与代码。摘要在**本仓 adapter** 里修，目标与既有证据一字不动。

## Consequences

- **一次修复、立竿见影**：修好后真实 `evolve` **第 1 轮即 accept**（`runs/evolve-kimi-digest-fix`）：`tools[write_artifact]` 的描述改为「…pass only that exact, case-sensitive token…」，net **+5**，bootstrap 95% 下界 **+1.000**。提案器给出的 `reason` 正是这条诊断本身（「token appears once in each file … the agent currently wraps the token in prose」）——证明它现在**真的看得见**失败原因。
- **比人工手写更强**：人工候选（`runs/candidates/exactness-hint`，改 system_prompt）是 net **+4**；循环自己找到的工具描述编辑是 **+5**，且落在更贴近失效点的地方。
- **零额外 API 成本**：摘要只是**渲染**已有 evidence，不新增模型调用；诊断本身可离线复现。
- **依赖目标内部结构**：`_render_message` 与 `gate` 行都读目标 evidence 的字段形状（`messages[].tool_calls[].function.arguments`）。目标改证据格式时该处需同步；`failure_digest` 是 adapter 接缝的一部分（`adapter.py:71`），语义上本就允许随目标演进。
- **未来触发重评**：若引入多臂/新套件，需确认新套件的门禁在 `objective_gates` 中都有正文；缺正文时会退化为只有标签（不报错、只是信息变少）。
