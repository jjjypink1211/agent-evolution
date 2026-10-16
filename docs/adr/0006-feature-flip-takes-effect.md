# feature 翻转经快照生效：启用集合 = 快照 features ∩ 臂的 condition 列表

- **Status**: Accepted
- **Date**: 2026-10-16

## Context

ADR-0004 记下一条已知限制：`EditKind.FEATURE` 是合法、可应用、可 diff 的快照编辑，但对首个目标**不改变 episode 行为**——`run_experiment_2_8.py` 的 `features` 完全取自 `protocol["conditions"][condition]`，其 `HarnessSnapshot` 不含 `features` 字段，快照里的 `features` 只是「已知 feature 名录」。于是提案器最自然的一类编辑（翻一个 feature）会被配对评测一律回滚，进化循环退化成只能改文本。

同时，ADR-0001 的 Decision 已经写明快照承载「启用的 feature 名录」，与目标实际忽略它的实现相矛盾。

## Decision

让快照的 `features` 真正参与决定一次 run 启用哪些 feature：

- 目标 `HarnessSnapshot` 增加 `features: frozenset[str]`，由 `load_harness` 从 `snapshot.json` 的 `features` 读取；缺失或非字符串列表按 `HarnessError` **严格失败**（与 `Snapshot.load` 一致，不静默降级）。
- 新增 `enabled_features(condition, protocol) = set(protocol["conditions"][condition]) & set(harness().features)`；`run_one` 用它取代原来只读 protocol 的写法。
- 证据同时记录两个集合：`features`（实际生效）与 `condition_features`（该臂 preregister 的列表），使「快照裁掉了什么」在证据里可见。

于是「启用集合 = 快照 features ∩ 臂的 condition 列表」：快照的加减与 protocol 的臂定义**共同**决定，两者都不可单独推翻对方。

## Considered Options

- **快照取代 condition 列表**（run 只看快照）：最直接，但会废掉 protocol 的臂矩阵——`disabled` 对照组将不再恒为空，冻结的对比设计失效。
- **适配器桥接**（把快照 feature 写进 condition 再交给目标）：快照与 `protocol_sha256` 记录的实际 protocol 不一致，破坏冻结证据。
- **只允许 protocol 已表达的组合**：等于没修，提案器仍无法引入新组合。

## Consequences

- **对首个目标生效，且不破坏臂矩阵**：`disabled` 臂的 condition 列表为空，交集恒为空（对照臂依旧干净）；`combined` 臂列出全部 6 个 feature，故把快照里任一 feature 翻 off 会真的少一个；其余单 feature 臂照旧。
- **冻结战役逐字节复现**：golden 快照 `snapshots/system-hint/snapshot.json` 列全 6 个 feature，故 `features` 与旧行为一致，历史证据依旧成立。
- **臂未列出的 feature 翻转是 no-op**：把快照里的某 feature 翻 on，若当前臂的 condition 列表不含它，交集不变、episode 不变、配对评测回滚。这是设计使然（臂决定评测什么），不是 bug；提案器若反复提这类编辑会被回滚。
- **闭集**：快照只能开关目标已认识的 feature；引入全新 feature 仍需改目标代码，不在进化范围。
- **回滚语义不变**：启用集合变了但门禁没变时，配对评测照样回滚——进步仍由客观门禁判定（ADR-0002/0003）。
- **判定「翻转真的到达门禁」需要模型行为**：该目标的门禁只读**任务工具**（`read_record`/`probe_resource`/`write_artifact`/`read_document`/`install_package`），而这些工具的可用性由 **suite** 而非 feature 决定；feature 只改动写给模型的**文本/状态段/额外工具**（`todo_list`）。因此回放冻结轨迹**永远**推不动门禁，门禁只能经模型行为改变。故 AC1 的回归证明用一个「只依据它收到的消息作答」的策略替身（`tests/policy_client.py`：`timestamps` 在则能从工具结果里比出较晚记录并提交，不在则无据可依、提交空值）——离线、确定、且**在 #8 之前必然失败**（旧实现的翻转被忽略，`timestamps` 照常出现，门禁照常通过）。真实模型的佐证是一次性 live smoke，不进 CI。
- **后续同步**：`edit.py`/`proposer.py` 里「catalogue / 惰性」的措辞据此更新；ADR-0004 的 Known limitation 标记为 resolved；GLOSSARY 增 `Feature` 词条。
