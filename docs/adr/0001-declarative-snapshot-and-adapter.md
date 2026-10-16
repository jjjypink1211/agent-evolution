# 以声明式快照树 + 通用适配器作为 harness 进化表示

- **Status**: Accepted
- **Date**: 2026-10-15

## Context

首个目标 agent loop（`ai-agent-book/chapter2/system-hint`）用于评测的实现是 `run_experiment_2_8.py`，其 harness——**启用哪些 feature**（`features` 集合）与 **case_prompt / status_message / tools_for 的文本**——目前全部**硬编码在代码里**。进化器需要让 LLM 提案器可 diff、可回滚地编辑 harness，同时不绑定单一 loop。

## Decision

把 harness 表示为**声明式快照目录**（system prompt 文本 + 工具描述/schema + 控制参数），loop 的控制流代码保持不动；进化器通过**通用适配器接缝**接入任意 loop——适配器对上层只暴露「给定快照 + 用例 → trajectory + 门禁结果」。

快照只承载 **harness**（agent 脚手架）：system prompt、`<agent_status>` 段模板、工具描述文本，以及启用的 feature 名录。**任务文本（`case_prompt`）不属于快照**——它属于任务/输入侧，随 protocol 用例保存。

## Considered Options

- **只进化现有开关**：零改动，但退化成 32×N 的超参搜索，LLM 提案器无用武之地。
- **直接改 loop 代码**：不可回滚、不可复现，且绑定单一 loop。
- **为单一 loop 定制**：放弃通用性。

## Consequences

对该评测 loop 做一次**兼容性重构**（ticket #3，已完成）：`run_experiment_2_8.py` 从内置的 `harness_snapshot/` 读取 system prompt、`status_message` 段模板与 `tools_for` 描述文本，可用 `--snapshot` 或 `$AI_AGENT_BOOK_HARNESS_SNAPSHOT` 覆盖；启用 feature 仍取自 protocol 的 `conditions`，loop 控制流不变。

- **工具 schema 暂缓**：本期只把**描述文本**外置；工具的参数/schema（`properties` / `required` / `enum`）仍留在代码中，待通用适配器接缝（ticket #4）统一处理。
- **默认快照逐字节等价**由三重对照保证：canonical 快照 `snapshots/system-hint/` ＝ 目标内置 `harness_snapshot/`，二者均须等于重构前冻结的 golden fixture `tests/fixtures/system_hint_harness.json`。（fixture 不再由目标反向生成，以消除循环论证。）
