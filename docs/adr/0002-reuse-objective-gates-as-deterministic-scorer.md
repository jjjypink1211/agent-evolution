# 复用目标 loop 的客观门禁作确定性子分，不引入 LLM 裁判

- **Status**: Accepted
- **Date**: 2026-10-15

## Context

首个目标 system-hint 已自带 `experiment_protocol.json` 的 `objective_gates`（`objective_scoring_only: true`）：通过条件仅由工具动作、沙箱状态与固定 ground truth 判定，不采信模型自述。已存在 `run_experiment_2_8.py` 实现配对对照。

## Decision

直接复用这些客观门禁作为 episode 的确定性子分；**不引入 LLM 裁判**。LLM 裁判推迟到将来接入无客观门禁的开放式任务时再评估。

## Considered Options

- **LLM 成对裁判**：适用于开放式任务，但有噪声、额外成本、可复现性差——对已有确定性判据的任务是纯粹退步。
