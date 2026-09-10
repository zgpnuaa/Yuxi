# guided 队列的投递保证：让位不消费、注入以 checkpoint 为准

状态：implemented
类型：bug-fix
Owner：backend/package/yuxi/agents/middlewares/steer.py

## 问题

guided（运行中消息注入）在两条路径上会丢用户输入：

1. **让位即丢失**：`SteerMiddleware.abefore_model` 先调 `take_pending_guided_messages`（其中已把请求提交为 `injected` 终态），再判定 steer；命中 steer 时只返回 `{"jump_to": "end"}`，guided 消息既不进 checkpoint 也不回队列——`injected` 意味着不再参与派发，消息永久消失。
2. **提交早于 checkpoint**：`take_pending_guided_messages` 在把 `HumanMessage` 交给 middleware **之前**就提交 `injected`。此时 graph 尚未应用并保存该更新；worker 若在 commit 与 checkpoint 落盘之间退出，恢复时 `list_pending_guided` 只读 `queued`，消息既不会被注入也不会被派发。

worker lease 只解决执行 ownership，无法让这两个持久化点原子提交。

## 决策

**让位不消费**：`abefore_model` 先判定 steer；命中即返回 `{"jump_to": "end"}` 且完全不触碰 guided，请求保持 `queued`，由下一个 Run 正常注入或派发。

**以 checkpoint 为已生效判据**：`injected` 语义收窄为「已提交注入，待 checkpoint 确认」。收割函数接受当前 graph state 的消息 id 集合：

- 请求为 `injected` 且其消息 id 已出现在 state 中 → 已生效，跳过（不重复注入）；
- 请求为 `injected` 但不在 state 中（提交后崩溃）→ 重新注入，实现幂等重放；
- 请求为 `queued` → 正常注入；
- 请求没有可用于对账的消息 id → 不跳过，宁可重放也不丢消息。

仓储层 `list_pending_guided` 增加 `statuses` 参数（默认 `("queued",)`），收割路径传 `("queued", "injected")`。

判据使用 `Message.extra_metadata.raw_message.id`——它是请求入库时生成的稳定 LangChain 消息 id，注入时被原样恢复，因此与 checkpoint 中的消息 id 可对账。

## 替代方案

- 在 commit 前先注入、成功后再提交：middleware 没有「checkpoint 已写入」的回调点，无法确认；拒绝。
- 让两个持久化点原子提交：checkpoint 由 LangGraph 写 PostgreSQL，与业务事务不在同一连接/事务边界；拒绝。
- 仅靠 `injected` 状态重放：无法区分「已生效」与「提交后崩溃」，会重复注入；拒绝。

## 后果

guided 的投递语义变为「恰好一次」：崩溃后恢复要么跳过（已生效）要么重放（未生效）。代价是每次 `before_model` 多读一次 `injected` 行（有 `(uid, agent_slug, conversation_thread_id)` 过滤，量级为线程内少量行），并且在消息 id 缺失时可能重复注入一次——这是有意选择的偏保守方向。

`injected` 不再是「绝对终态」：它在语义上是「已提交，待确认」，仓储默认查询仍只返回 `queued`，只有收割路径显式包含它。

## 验证

- 单元（`test/unit/agents/test_steer_middleware.py`）：
  - `test_before_model_prefers_steer_jump_when_both_pending` 断言让位时**不调用**收割函数（原测试把丢失行为写成了预期，已纠正）；
  - `test_before_model_passes_state_message_ids_for_replay` 断言 state 中的消息 id 被传给收割函数；
  - `test_guided_replay_decision_uses_checkpoint_state` 覆盖已生效跳过、未落盘重放、queued 正常注入、无 id 不跳过四种判定。
- 集成（真实 PostgreSQL，`test/integration/services/test_agent_request_queue_concurrency.py::test_guided_injected_request_remains_replayable_until_checkpoint_confirms`）：落一条 `queued` guided 请求并提交 `injected`（模拟提交后崩溃）后，默认查询返回空（复现丢失路径），带 `statuses=("queued","injected")` 的恢复查询返回该请求。
- 未验证范围：未做「提交 injected → 杀 worker → 重启后续跑」的真实进程级故障注入 E2E。
