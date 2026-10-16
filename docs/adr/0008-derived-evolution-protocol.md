# 进化专用 protocol：同型扩用例，冻结件不动

- **Status**: Accepted
- **Date**: 2026-10-16

## Context

真实 `evolve` 三跑全部回滚，净胜 +2 / +1 / +2，bootstrap 95% 置信下界恒为 **+0.000**。放宽到 n≈10 后（一轮半、约 28 episodes / 350k tokens ≈ ¥12，中途叫停）结论不变：净胜 +2/10，下界仍是 **+0.000**。两轮实测合起来说明**加宽样本是错误杠杆**——二元客观门禁下，判据要求下界 > 0，所需净胜随 n 一起涨（n=5 需 +4，n=10 需 +8），而提案器实际能拿到的效应只有 ~20%。要过线必须**先让效应变大**，而不是把样本变多。

于是先试「加大效应」，分两处下手：**换更便宜的被测**与**把用例做难**（难度是纯数据：`todo_list` 的客观门禁对 case 完全通用，`run_experiment_2_8.py:496` 只校验产物齐备、内容恰为 token、提交集合恰等于 `case["artifacts"]`——加难不需要碰目标一行代码）。两者都被实测否掉：

- **换被测**：DeepSeek `deepseek-v4-flash` 在 6 套件 **30/30 全过**（`runs/baseline-probe`）、`todo_list` **15/15**（`runs/evolve-try-todo`）——零失败，harness 无任何可改进余地，换过去只得到「基线全过」的零空间。（成本优势是真的：峰值价约 **¥0.03/episode**，比 kimi 的 ~¥0.45 低一个数量级。）
- **加难用例**：10 例难用例（6–8 个产物、混大小写与易混字符的 token、混入近似命名）交给 DeepSeek，仍是 **10/10 全过**（`runs/baseline-hard`，101k tokens，36 秒）——DeepSeek 极致批处理（`hard-03` 仅 3 turn：一 turn 写 7 个动作、一 turn 更 8 条状态、一 turn 提交），加产物数与混淆程度都压不动它。

根因随后在别处找到（**另见 ADR-0009**）：循环 0 accept 是因为 `failure_digest` 丢掉了 `tool_calls` 的 arguments，提案器看不到产物内容、也不知道门禁要求什么，只能瞎猜。修好 digest 后**无需换被测、无需加难用例**，真实 `evolve` 第 1 轮即 accept（`runs/evolve-kimi-digest-fix`）。

但目标的 `experiment_protocol.json` **不能就地改**。它是冻结件：

- 它的 `protocol_sha256` 被写进已发布战役的 `manifest.json`，run 目录里还留有一份逐字节副本；
- `design.matched_cases_per_contrast: 5`，README 明确写「five real Moonshot kimi-k3 cases for every preregistered contrast」；
- `main()` 会把「run 目录里的 protocol 副本」与「当前 protocol」比对，不一致直接 `RuntimeError: run protocol copy differs from frozen protocol`（`run_experiment_2_8.py:966`）。

改它等于让既有战役证据与 README 声明同时失效——这正是 ticket #8 当初刻意做成「冻结战役逐字节复现」（ADR-0006）所要避免的。而**扩用例集**确实还有价值：n=5 时 net +4-of-5 恰好卡在下界 > 0 的边界（空间验证 `runs/eval-exactness-hint` 就是 +4、下界 +0.400），把同型用例加宽能让 accept 取决于编辑本身而非抽样运气。

## Decision

- 新增 `tools/build_evolution_protocol.py`：以**冻结件为唯一输入**，派生 `protocols/system-hint-evolution.json`。派生规则是「源逐字段照抄，只覆盖 `cases.todo_list` 并追加 `evolution_extension` 块」；`evolution_extension` 记录来源文件名、来源 `protocol_sha256`、追加用例的套件与 id。工具带 `--check`，检测派生件相对冻结件是否过期。
- **只做同型扩用例**：`todo_list` 在冻结 5 例之后**追加** 5 例（`todo-06`…`todo-10`），形状与冻结用例完全一致——一个纯 token + 4 个 `.txt` 产物，产物名全协议唯一。**保留冻结 5 例在前**，因此派生件的用例集是冻结用例集的严格超集，与 `matched_cases_per_contrast` 同构的对照部分逐字节保持。
- **不换被测、不加难用例**：`provider` / `pricing` 逐字节照抄冻结件（仍是 `kimi-k3`）；难度不作为杠杆——「造难用例」已被实测否掉，且它会让派生化用例与冻结用例不再同构，失去对照意义。
- `SystemHintAdapter` 新增 `protocol_path` 参数并新增 `resolve_protocol_path()`：显式路径 > `AGENT_EVOLUTION_PROTOCOL` > 目标自带的 `experiment_protocol.json`。`cli.py` 的 `evaluate` / `evolve` 增加 `--protocol`，并把解析后的路径既用于选 provider，也传给 adapter，保证「读哪个 protocol」只有一处判定。
- **默认行为逐字节不变**：不传 `--protocol`、不设环境变量时，仍读目标的冻结 protocol（`kimi-k3`，`todo_list` 5 例）。真实 `evolve` 因此**默认就走冻结件**，不需要派生件。
- 冻结件与已发布战役**一字不改**。

## Considered Options

- **直接改冻结 `experiment_protocol.json`**：最省事，但会改 `protocol_sha256`、让战役副本比对失败、并使 README 的「five cases」与 `matched_cases_per_contrast` 变成假话。弃。
- **继续加宽样本（n=10、n=20…）**：已实测为错误杠杆——下界不动而成本线性上升。弃。
- **派生件换成 DeepSeek + 10 例难用例**：实测双否——DeepSeek 零空间，且难用例对它仍 10/10。这个方向曾一度落地（本 ADR 的上一版），依据实测整体回滚。弃。
- **派生件整体替换掉冻结 5 例**：每轮能省 5 个必然通过的 episode，但会丢掉与 `matched_cases_per_contrast` 同构的对照，且继承前面「难用例」方向已被否的结论。改为保留 + 追加。
- **把派生件放进目标仓**：数据离目标更近，但会往书籍仓塞非书籍产物，且两个同名同构文件极易被误用。改为放在本仓 `protocols/`。
- **干脆不要派生件**（默认跑冻结 5 例已能 accept）：可行——这正是当前默认路径。但仍保留机制，因为当基线失败率下降到接近边界时，扩用例集是让 accept 稳健的唯一手段。

## Consequences

- **成本量级改善**：真实 `evolve` 在冻结 protocol 上第 1 轮即 accept，总耗 **157,577 tokens ≈ ¥5.77**（`runs/evolve-kimi-digest-fix`），不再需要 n=10 那种 ¥10+ 的探索。
- **证据可区分**：派生 protocol 有自己的 `protocol_sha256`，会写进它产出的每份 evidence，因此进化实验的证据不会被误认为已发布战役的一部分。派生件产出 usage 时仍按冻结 `pricing`（kimi）计价——因为被测没换。
- **漂移有守护**：单测断言「派生件 == 从冻结件现场重建的结果」，并逐字段核对「除 `cases`/`evolution_extension` 外与冻结件完全相同」「非 todo_list 套件逐字节相同」「冻结 5 例在派生件中居前且逐字节相同」；另有测试断言追加用例 id/token 唯一、形状不高于冻结用例（防「加难」回潮）。冻结件一旦改动，`--check` 与测试同时报警，派生件必须重建。
- **记录在案的偏差**：派生件的 `todo_list` 例数（10）> 冻结 `design`；`evolution_extension.purpose` 明确这是**仅供进化**的扩样例，既不构成对已发布主张的复现，也不对其做任何修正。
- **未来触发重评**：若进化需要在更多套件上扩用例，或需要让 `run_experiment_2_8.py` 原生的 `main()` 也能跑重定向 protocol，则应改为「协议来源外置」而非继续派生副本。
