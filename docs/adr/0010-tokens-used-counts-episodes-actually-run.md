# `tokens_used` 只计真正跑过的 episode

- **Status**: Accepted
- **Date**: 2026-10-16

## Context

ADR-0007 让基线 episode 跨轮复用（回滚后基线不变），但循环的记账没跟着改：`run_evolution` 每轮无条件 `tokens_used += record.tokens`，而 `record.tokens = baseline_tokens + candidate_tokens`。被复用的基线臂于是**每轮再记一遍**——同一批 episode 的 token 被重复计入。

在真实运行 `runs/evolve-kimi-digest-fix` 上，这个偏差是 87%（上报 244,525 vs 真实 157,577）：

| 轮 | 基线臂 | 候选臂 | 真实花费 |
|---|---|---|---|
| 1 | 42,848（新跑） | 43,474 | 86,322 |
| 2 | 43,474（复用） | 37,281 | 37,281 |
| 3 | 43,474（复用） | 33,974 | 33,974 |

`episodes/` 下只有 **4** 个快照目录（`d3ab…` 基线、`7af2…`、`c145…`、`038a…` 候选），即 20 个 episode；而 `tokens_used` 却按 5 个臂记账。多出的 86,948 = 第 2、3 轮各重记了一遍 43,474。

还有一处**同源的空跑**：候选 episode 跑完就丢了，第 1 轮 accept 后的新基线（就是那个候选）在第 2 轮又被当成「没见过的基线」重跑一遍。它既浪费钱，又是上面重复计入的来源。

## Decision

- `RoundRecord` 新增 `baseline_reused: bool`，并新增 `spent_tokens`：
  - `spent_tokens = candidate_tokens`（候选臂总会跑）；
  - 基线臂未复用时 `+ baseline_tokens`，复用时不计。
  - 原 `tokens` 保留，含义明确为「**测量**这轮两臂的代价」，用于逐轮报表。
- `run_evolution` 用 `record.spent_tokens` 累加 `tokens_used` 与预算投影 `last_round_tokens`。
- **accept 时把候选 episode 存进基线缓存**：`baseline_cache.setdefault(candidate.fingerprint(), [(case, outcome.candidate) …])`。于是「候选 → 下一轮基线」是缓存命中，既不重跑也不重记；回滚路径照旧复用旧基线。
- `round_payload` 补 `spent_tokens` 与 `baseline_reused`，让 `history.json` 能自证这个数。

## Considered Options

- **只修「复用不重记」，不补候选缓存**：记账口径立刻自洽（第 3 轮不再重记），但第 2 轮的基线仍会真跑一遍、也就仍会记一笔；`tokens_used` 会变成 201,051 而非实测的 157,577。两处是同一个「谁在跑 / 跑几次」的问题，拆开修等于留一半。
- **改判据或降低预算口径**：判据（net > 0 且下界 > 0）与花钱无关，不该动；预算本来就是「跑多少」的软上限，把记账修对才是它该有的语义。
- **在 adapter 里做 episode 缓存**：会把「谁在跑」的知识泄漏进接缝实现，也不再是逐轮可读的；复用属于 loop 的调度，留在 `evolve.py`。

## Consequences

- `tokens_used` 现在等于实测（`runs/evolve-kimi-digest-fix` → **157,577**），与 `episodes/` 的 20 个 episode 对得上，也与 README 的 ¥5.77 对得上。
- **预算更经花也更准**：复用轮的边际成本只有候选臂，`budget_tokens` 现在按真实边际成本推进。副作用是同一预算能跑更多轮——`tests/test_evolve.py` 的「预算 100」用例从 2 轮变 3 轮（判据与停止条件不变，只是不再虚报花销）。
- **省掉一次真实重跑**：accept 后不再重跑新基线，直接省下一整臂的 token 与时间。
- **不改变判据、种子与接受/回滚结果**：只改「跑几次 / 记多少」。
