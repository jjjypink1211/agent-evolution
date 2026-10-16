# Harness Evolve

一个离线进化系统：通过配对 episode 打分，搜索并保留/回滚某个 agent loop 的 harness。它把「模型权重」当作固定，只让脚手架变。

## Language

**Harness（脚手架）**:
固定模型端点外围、可变的 agent 层：system prompt 文本、工具描述/schema、控制参数。不含 loop 的控制流代码。
_Avoid_: agent, 提示词, 配置

**Harness 快照 (Snapshot)**:
harness 的一份声明式、可 diff 表示，落在快照目录里。
_Avoid_: 版本, 配置包

**Feature（特性开关）**:
harness 上一个可开关的干预：开启后 loop 会改变它写给模型的状态段、工具结果或工具集。一次 run 实际启用的是「快照的 features ∩ 该臂 protocol condition 列表」的交集，故快照与 protocol 共同决定——臂未列出的 feature 翻转是 no-op。
_Avoid_: 开关, flag, 选项

**进化 (Evolution)**:
离线过程：提案器提出快照编辑，跑配对 episode 打分，据此保留或回滚。不是运行时自适应。
_Avoid_: 训练, 微调, 学习

**进化运行 (Run)**:
一次进化的完整过程，跑到停止条件为止，全部历史落在一个 run 目录。含若干轮次。
_Avoid_: job, campaign

**轮次 (Round)**:
进化运行的一步：跑基线 → 提案一处编辑 → 跑候选配对评测 → 保留或回滚。
_Avoid_: iteration, step

**token 预算 (Token Budget)**:
一次进化运行的 **episode** token 上限，是 run 级软上限：下一轮（按上轮量级推算）会超即停。不含提案器自身调用；区别于单次评测的候选成本上限。
_Avoid_: 成本, 配额

**Episode**:
一个任务用例在某份快照下跑一次；主结果是该用例客观门禁的布尔值。
_Avoid_: run, 样本, rollout

**配对 Episode (Paired Episode)**:
同一用例在「候选快照 vs 基线快照」下、同模型同初始状态下各跑一次，供成对比较。
_Avoid_: A/B 测试, 对照组

**客观门禁 (Objective Gate)**:
一个用例的通过条件，仅由工具动作、沙箱状态与固定 ground truth 判定，不采信模型自述。
_Avoid_: 评分标准, 断言

**提案器 (Proposer)**:
读取失败 episode 的失败摘要与当前快照，提出恰好一处编辑的 LLM。
_Avoid_: 优化器, mutator

**失败摘要 (Failure Digest)**:
适配器把一次失败 episode 的门禁明细与轨迹渲染成的一段人读文本，供提案器阅读；提案器不直接读目标的证据格式。
_Avoid_: 日志, trace

**基线 (Baseline)**:
当前已被采纳、作为配对比较参照的快照。
_Avoid_: 原始版本, 主分支

**保留 / 回滚 (Accept / Rollback)**:
配对打分达标则采纳候选快照为新基线，否则弃用。
_Avoid_: 合并, 提交

**适配器 (Adapter)**:
把某个具体 agent loop 接入进化系统的接缝：列出目标定义的套件、枚举某套件的用例、给定「快照 + 用例」跑一次并返回门禁结果，并把一次失败渲染成人读摘要供提案器阅读。
_Avoid_: 插件, 驱动

**任务套件 (Suite)**:
同主题、共享门禁语义的一组任务用例。
_Avoid_: 数据集, benchmark

**门禁通过率 (Pass Rate)**:
一份快照在一组用例上门禁通过的占比，是成对比较的主指标。
_Avoid_: 分数, accuracy
