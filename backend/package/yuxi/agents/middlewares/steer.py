"""主会话 Steer / Guided Middleware。"""

from langchain.agents.middleware import AgentMiddleware, hook_config


class SteerMiddleware(AgentMiddleware):
    """在模型调用前的安全边界处理队列干预。

    - guided：把等待注入的补充消息追加进当前 Run 的 messages，模型下一轮即看到，
      当前 Run 不终止（Claude Code 式中途修正）。
    - steer：结束当前 Run，让位给高优先级 Steer 请求。
    """

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        # 先判定让位：steer 命中时不消费 guided——take_pending_guided_messages 会把请求
        # 提交为 injected 终态，而让位会立刻结束本 Run、消息不会进入 checkpoint，
        # 结果是"既不在队列、也不在图里"的永久丢失。留在队列由下一个 Run 注入。
        steer_jump = await self._jump_if_steer_requested(runtime)
        if steer_jump is not None:
            return steer_jump
        return await self._collect_guided_update(state, runtime)

    @hook_config(can_jump_to=["end"])
    async def aafter_model(self, state, runtime):
        """兜底处理无工具模型轮次，避免 Steer 落在最后一次检查之后。"""
        if _last_message_has_tool_calls(state):
            return None
        return await self._jump_if_steer_requested(runtime)

    async def _collect_guided_update(self, state, runtime):
        from yuxi.services.agent_request_queue_service import take_pending_guided_messages

        run_id = getattr(runtime.context, "run_id", None)
        if not run_id:
            return None
        try:
            messages = await take_pending_guided_messages(
                run_id,
                applied_message_ids=_state_message_ids(state),
            )
        except Exception:  # noqa: BLE001
            return None
        if not messages:
            return None
        return {"messages": messages}

    async def _jump_if_steer_requested(self, runtime):
        from yuxi.services.agent_request_queue_service import should_end_run_for_steer

        run_id = getattr(runtime.context, "run_id", None)
        if not run_id or not await should_end_run_for_steer(run_id):
            return None
        return {"jump_to": "end"}


def _state_message_ids(state) -> set[str]:
    """取出当前 graph state 里的消息 id，作为 guided 注入"是否已生效"的判据。"""
    messages = state.get("messages") if isinstance(state, dict) else None
    ids: set[str] = set()
    for message in messages or []:
        message_id = message.get("id") if isinstance(message, dict) else getattr(message, "id", None)
        if message_id:
            ids.add(str(message_id))
    return ids


def _last_message_has_tool_calls(state) -> bool:
    """判断模型最后一条消息是否仍需执行工具，避免跳过工具批次。"""
    messages = state.get("messages") if isinstance(state, dict) else None
    if not messages:
        return False
    last_message = messages[-1]
    if isinstance(last_message, dict):
        return bool(last_message.get("tool_calls"))
    return bool(getattr(last_message, "tool_calls", None))
