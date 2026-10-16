# 进化循环按轮次落盘全历史，token 预算是 run 级软上限

- **Status**: Accepted
- **Date**: 2026-10-16

## Context

把提案器（ADR-0004）与配对评测（ADR-0003）串成多轮后，需要定：历史怎么落盘、预算怎么算、套件怎么选、提案器读哪些失败、什么时候停。这些决定会长期约束「一次进化运行」的形状，且要能离线确定测试、能事后审计每一轮。

## Decision

- **历史布局**：一次运行写到一个 run 目录，逐轮 `rounds/NN/` 存 `baseline/` 与 `candidate/` 两份快照、`edit.json`（提案的编辑 + 理由 + 尝试次数）、`summary.json`+`summary.txt`（该轮配对报告）、`decision.json`（该轮判定）；run 级存 `history.json`+`history.md`，并在 `baseline/` 落最终被采纳的快照。每轮证据都在盘上，任何一轮可事后审计/回放。
- **预算语义**：`--rounds N`（默认 10）限轮数；`--budget-tokens` 是 **run 级的 episode token 上限**——只在「已花 token + 上一轮量级」仍不超上限时才开新一轮，故不会开启一个（按上轮推算）会超标的轮次；首轮无从估计、可能一次超。它计的是**目标 episode 的 token**，不含提案器自身的调用（窄模型接口只回文本，见 ADR-0004）。它与 ADR-0003 的单次评测 `--token-budget`（拒绝成本超标的候选）是**两个独立的旋钮**，进化循环不传后者。
- **套件选择**：`--suite` 可重复，`all` 展开为该目标定义的全部套件（经适配器 `Adapter.suites()`，见 ADR-0001 的 Amendment），缺省 `combined`（5 例冒烟）；`all` 即全量（对首个目标为 6 套件 × 5 例 = 30 例，含 `combined`）。
- **提案器输入**：只喂**当轮基线臂的失败 episode**，按 `(suite, case_id)` 排序，条数由 `--max-failures` 兜帽（默认 5，`0` 不喂、负数不限），每条用适配器的 `failure_digest` 渲染——提案器仍不接触目标证据格式（ADR-0001/0004）。
- **基线臂只跑一次**：每轮先跑一次基线，既拿失败摘要喂提案器，又把结果复用进配对评测（`evaluate(..., baseline_results=...)`），不重复计费。
- **停止条件**：轮数用尽 / 预算触顶 / 连续回滚达 `--max-rollbacks`（默认 3，`0` 禁用）/ 无可用编辑（`ProposalError`）/ 无用例；每次都打印 run 摘要并 `exit 0`（运行正常结束，非错误）。
- **拒绝候选时基线不变**：回滚轮只记录、不改 `current` 快照。

## Considered Options

- **只留最终快照**：无法审计「为什么走偏」、无法回放某轮。
- **预算按「预估下轮成本」硬拦**：需要先跑一轮才知道成本，且预估不可靠；软上限更简单、可解释。
- **提案器直接读全部失败 episode**：token 随套件规模膨胀，且把目标证据格式泄进通用层（ADR-0001/0004 已否决）。
- **默认 `all`**：冒烟应廉价、快；默认 `combined`。

## Consequences

- 每轮历史自包含，`rounds/NN/` 可直接重跑或对比；run 级 `history.md` 给一屏概览。
- run 级 `--budget-tokens` 与单次 `--token-budget` 并存且语义不同，文档与 CLI help 需显式区分。
- 循环实现为纯编排（`run_evolution` 返回 `RunReport`），落盘另置于 `save_run`，故可用脚本化提案器 + `FakeAdapter` 离线确定测试完整推进/回滚/停止路径（`tests/test_evolve.py`）。
