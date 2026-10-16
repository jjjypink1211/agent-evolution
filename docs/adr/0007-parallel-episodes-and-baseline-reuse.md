# 提速：同一快照的 episode 可并行，且基线 episode 跨轮回滚复用

- **Status**: Accepted
- **Date**: 2026-10-16

## Context

一次 `evolve` 的每轮要跑**两批** episode：基线 n 个、候选 n 个。而

1. **基线在回滚后逐字节不变，却每轮重跑**：一次全回滚的 3 轮运行把「基线 n + 候选 n」重复 3 次，基线那 n 个 episode 花了两遍的预算。
2. **episode 之间彼此独立**：每个 episode 有自己的证据目录、自己的模型调用，互不依赖，墙钟是大头。

但并发不能随便加。目标把**已加载的 harness 放在模块全局** `_HARNESS`(`run_experiment_2_8.py:95`)，`set_harness` **就地改写**它(`:105`)，而随后的 `run_one` 通过 `harness()` 读这个全局。于是：

- **两个不同快照绝不能同时在途**——否则一个 episode 会读到另一个快照的 harness。
- **同一个快照的一批 episode 可以并发**——它们指向的 harness 内容完全相同（快照 fingerprint 决定内容，落点只是 episode 目录），对 `_HARNESS` 的竞争无害。

目标侧其余部分无共享可变状态（无 `os.chdir`、无 `os.environ` 写入），已核实。

## Decision

- 新增 `parallel.py`：`resolve_workers(count, max_workers)` 与 `run_batch(adapter, snapshot, cases, *, max_workers)`，**保序**返回。默认 **1** 个 worker（= 旧顺序行为）；经 `--workers` 或 `AGENT_EVOLUTION_WORKERS` 提高，上限为批内用例数。
- `paired.evaluate` / `paired_outcomes` / `candidate_outcomes` 透传 `max_workers`，并**每臂整批跑完再跑另一臂**（基线批 → 候选批），**绝不交错**——任一时刻只有一个快照在途。
- `evolve.run_evolution` 按 `snapshot.fingerprint()` **缓存基线 episode 并跨轮回滚复用**（基线未变，其 episode 与提案器失败摘要仍有效），经 `evaluate(..., baseline_results=...)` 传入，避免一轮内把基线跑两遍。

## Considered Options

- **每个 episode 起子进程隔离**：彻底避开全局竞争，但解释器启动开销大，且放弃目标已有的 episode 级 resume（`run_one` 按 fingerprint 复用证据）。
- **两臂交错并发**：会在途两种快照，踩 `_HARNESS` 竞争，禁。
- **默认即并发**：破坏 `FakeAdapter.calls` 的**顺序**断言与离线可复现性；改为 opt-in（默认 1）。
- **只并发、不缓存基线**：回滚轮次仍为基线重复付费（基线占一半 episode），故一并做缓存。

## Consequences

- **判据语义不变**：并发只改「谁在跑」，缓存只改「跑几次」；配对 delta、bootstrap 区间、accept/rollback 完全一致（有测试逐项断言）。
- **默认不变**：未设 workers 时逐字节等同旧的顺序行为。
- **加速**：并发把每批墙钟约降为 ÷workers（上限=用例数）；基线复用把全回滚的 3 轮由 `3n(基)+3n(候)` 降到 `1n(基)+3n(候)`。两者叠加是本次提速的主杠杆。
- **约束显式化**：`run_batch` 只接受**单个**快照，「一个快照一批」成为类型层面的约定；`paired` 的两臂两批顺序执行是唯一安全的并发形状，且由 `test_arms_are_batched_not_interleaved` 钉住。
- **未来触发重评**：若目标将来在 episode 之间引入其它全局可变状态（缓存、注册表、环境变量），须重新评估并发上限。
