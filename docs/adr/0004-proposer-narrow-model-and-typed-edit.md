# 提案器用窄模型接口 + 类型化单编辑，端到端可离线确定测试

- **Status**: Accepted
- **Date**: 2026-10-16

## Context

进化循环每轮需要一个 LLM 读「当前快照 + 失败 episode 的轨迹与门禁明细」，提出**一处**编辑。要满足的约束：编辑可 diff/可回滚、通用层不绑定单一 loop、可离线确定测试、且提案器端点与被测 agent 的 provider 相互独立。

失败 episode 的轨迹（消息、工具事件、门禁明细）是**目标特有**的证据格式，只有适配器读得懂；若让提案器直接读证据文件，就把它变成了目标专有代码。

## Decision

- **窄模型接口**：提案器只依赖 `ProposerModel.complete(system, user) -> str`；`OpenAIChatModel` 是唯一的 SDK 实现，端点用 `EVOLVER_BASE_URL` / `EVOLVER_API_KEY` / `EVOLVER_MODEL` 独立配置，`Proposer.from_env()` 是入口。测试用脚本化模型，零网络。
- **类型化单编辑**：一处编辑用 `Edit(kind, key, value, reason)` 表示，`kind ∈ {feature, system_prompt, status_section, tool_description}`；`Edit.apply(snapshot)` 保证恰好改动一个字段，并把「已经是该状态」的编辑当作错误——no-op 不是候选。
- **失败摘要走接缝**：轨迹由适配器的 `failure_digest(snapshot, case, result)` 渲染成文本（ADR-0001），提案器只读文本。
- **严格 JSON + 一次修复重试**：模型回复须为一个 JSON 对象 `{"edit": { ... }}`（也接受裸的 edit 对象，并容忍一层 ``` 围栏）；解析或应用失败时用一条「上次回复被拒」的修复提示重试，次数可配（默认 1）；仍失败则抛 `ProposalError`，由调用方回滚（ADR-0003）。

## Considered Options

- **直接改 loop 源码**：不可回滚、不可复现（ADR-0001 已否决）。
- **自由文本补丁**：解析不可靠、难以断言「只有一处改动」。
- **提案器直接持有 OpenAI SDK 客户端**：测试要 monkeypatch SDK，并把 SDK 形状泄进通用层。
- **提案器直接读证据文件**：把目标证据格式泄进通用层。

## Consequences

- 提案器可用脚本化模型离线确定测试（`tests/test_proposer.py`：解析、围栏、包装对象、修复重试、`max_repairs=0`、端点配置）。
- `max_repairs=0` 即「一次失败就放弃」；默认 1 兼顾稳健与成本。
- 重试会重复计费 token，故端与修复上限都在提案器侧显式可配；候选是否采纳仍由配对评测决定，提案器不参与判定。
- **理由必填**：规格要求「一处编辑 **+ 理由**」，故提案器路径要求 `reason` 非空，缺失即按不可用回复走修复重试（`Edit` 本身仍允许空 `reason`，便于程序化构造）。

## Known limitation: a feature flip is inert against the current target（已由 ADR-0006 解除）

`EditKind.FEATURE` 是合法、可应用、可 diff 的快照编辑，但对首个目标**不改变 episode 行为**：目标从 protocol 的 condition 推导启用 feature（`run_experiment_2_8.py` 的 `features = set(protocol["conditions"][condition])`），其 `HarnessSnapshot` 不含 `features` 字段，快照里的 `features` 目前只是「已知 feature 名录」（见 ADR-0001 的 Consequences 与 `snapshot.py`）。因此该编辑会被配对评测一律回滚。

让 feature 翻转生效需要重开 ADR-0001 中「启用哪些 feature 归 protocol 决定」这一条（或由适配器把快照的 feature 集合桥接进 condition），已另开 follow-up issue（#8）跟踪，不在本 ADR 范围。

**后续（ticket #8，见 ADR-0006）**：`HarnessSnapshot` 已长出 `features`，一次 run 的启用集合改为「快照 features ∩ 臂的 condition 列表」，`FEATURE` 编辑因此对首个目标真正生效。本节保留为历史记录。
