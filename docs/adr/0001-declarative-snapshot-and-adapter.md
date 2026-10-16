# 以声明式快照树 + 通用适配器作为 harness 进化表示

- **Status**: Accepted
- **Date**: 2026-10-15

## Context

首个目标 agent loop（`ai-agent-book/chapter2/system-hint`）用于评测的实现是 `run_experiment_2_8.py`，其 harness——**启用哪些 feature**（`features` 集合）与 **case_prompt / status_message / tools_for 的文本**——目前全部**硬编码在代码里**。进化器需要让 LLM 提案器可 diff、可回滚地编辑 harness，同时不绑定单一 loop。

## Decision

把 harness 表示为**声明式快照目录**（system prompt 文本 + 工具描述/schema + 控制参数），loop 的控制流代码保持不动；进化器通过**通用适配器接缝**接入任意 loop——适配器对上层只暴露「给定快照 + 用例 → trajectory + 门禁结果」。

## Considered Options

- **只进化现有开关**：零改动，但退化成 32×N 的超参搜索，LLM 提案器无用武之地。
- **直接改 loop 代码**：不可回滚、不可复现，且绑定单一 loop。
- **为单一 loop 定制**：放弃通用性。

## Consequences

需对该评测 loop 做一次**兼容性重构**：把 `features` 与 `case_prompt` / `status_message` / `tools_for` 的文本外置成快照文件，`run_one` 从快照读取而非硬编码。默认快照必须与原行为逐字节等价（golden 对照）。
