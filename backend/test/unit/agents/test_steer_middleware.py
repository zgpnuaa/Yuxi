"""Steer/Guided Middleware 单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yuxi.agents.middlewares.steer as steer_module
from langchain_core.messages import AIMessage
from yuxi.agents.middlewares.steer import SteerMiddleware
from yuxi.services import agent_request_queue_service

pytestmark = [pytest.mark.unit]


def _runtime(run_id="run-1"):
    return SimpleNamespace(context=SimpleNamespace(run_id=run_id))


@pytest.mark.asyncio
async def test_before_model_injects_pending_guided_messages(monkeypatch):
    from langchain.messages import HumanMessage

    middleware = SteerMiddleware()
    messages = [HumanMessage(content="补充：只看 2024 年后的数据", id="m-1")]

    async def fake_take(run_id, *, applied_message_ids=None):
        assert run_id == "run-1"
        return messages

    async def fake_steer(run_id):
        return False

    monkeypatch.setattr(steer_module, "take_pending_guided_messages", fake_take, raising=False)
    monkeypatch.setattr("yuxi.services.agent_request_queue_service.take_pending_guided_messages", fake_take)
    monkeypatch.setattr("yuxi.services.agent_request_queue_service.should_end_run_for_steer", fake_steer)

    result = await middleware.abefore_model({}, _runtime())

    assert result == {"messages": messages}


@pytest.mark.asyncio
async def test_before_model_returns_none_without_interventions(monkeypatch):
    middleware = SteerMiddleware()

    async def fake_take(run_id, *, applied_message_ids=None):
        return []

    async def fake_steer(run_id):
        return False

    monkeypatch.setattr("yuxi.services.agent_request_queue_service.take_pending_guided_messages", fake_take)
    monkeypatch.setattr("yuxi.services.agent_request_queue_service.should_end_run_for_steer", fake_steer)

    assert await middleware.abefore_model({}, _runtime()) is None


@pytest.mark.asyncio
async def test_before_model_prefers_steer_jump_when_both_pending(monkeypatch):
    """steer 与 guided 同时等待时让位，且不得消费 guided。

    take_pending_guided_messages 会把请求提交为 injected 终态，而让位会立刻结束本 Run、
    消息不会进入 checkpoint——消费即永久丢失。留在队列由下一个 Run 注入。
    """
    middleware = SteerMiddleware()
    taken: list[dict] = []

    async def fake_take(run_id, *, applied_message_ids=None):
        taken.append({"run_id": run_id, "applied": applied_message_ids})
        raise AssertionError("让位时不得消费 guided")

    async def fake_steer(run_id):
        return True

    monkeypatch.setattr("yuxi.services.agent_request_queue_service.take_pending_guided_messages", fake_take)
    monkeypatch.setattr("yuxi.services.agent_request_queue_service.should_end_run_for_steer", fake_steer)

    result = await middleware.abefore_model({}, _runtime())

    assert result == {"jump_to": "end"}
    assert taken == []


@pytest.mark.asyncio
async def test_before_model_guided_failure_does_not_break_run(monkeypatch):
    middleware = SteerMiddleware()

    async def fake_take(run_id, *, applied_message_ids=None):
        raise RuntimeError("db down")

    async def fake_steer(run_id):
        return False

    monkeypatch.setattr("yuxi.services.agent_request_queue_service.take_pending_guided_messages", fake_take)
    monkeypatch.setattr("yuxi.services.agent_request_queue_service.should_end_run_for_steer", fake_steer)

    assert await middleware.abefore_model({}, _runtime()) is None


@pytest.mark.asyncio
async def test_before_model_without_run_id_skips_queries(monkeypatch):
    middleware = SteerMiddleware()

    async def fail_take(run_id, *, applied_message_ids=None):
        raise AssertionError("无 run_id 不应查询 guided")

    async def fail_steer(run_id):
        raise AssertionError("无 run_id 不应查询 steer")

    monkeypatch.setattr("yuxi.services.agent_request_queue_service.take_pending_guided_messages", fail_take)
    monkeypatch.setattr("yuxi.services.agent_request_queue_service.should_end_run_for_steer", fail_steer)

    assert await middleware.abefore_model({}, SimpleNamespace(context=SimpleNamespace())) is None


@pytest.mark.asyncio
async def test_before_model_ends_run_when_steer_is_waiting(monkeypatch: pytest.MonkeyPatch):
    """存在待处理 Steer 时，在下一次模型调用前结束当前 Graph。"""

    async def should_end(run_id: str) -> bool:
        return run_id == "run-1"

    monkeypatch.setattr(agent_request_queue_service, "should_end_run_for_steer", should_end)
    runtime = SimpleNamespace(context=SimpleNamespace(run_id="run-1"))

    result = await SteerMiddleware().abefore_model({}, runtime)

    assert result == {"jump_to": "end"}


@pytest.mark.asyncio
async def test_before_model_continues_without_steer(monkeypatch: pytest.MonkeyPatch):
    """没有 Steer 时继续正常模型调用。"""

    async def should_end(run_id: str) -> bool:
        return False

    monkeypatch.setattr(agent_request_queue_service, "should_end_run_for_steer", should_end)
    runtime = SimpleNamespace(context=SimpleNamespace(run_id="run-1"))

    assert await SteerMiddleware().abefore_model({}, runtime) is None


@pytest.mark.asyncio
async def test_before_model_ignores_context_without_run_id(monkeypatch: pytest.MonkeyPatch):
    """缺少 Run 上下文时不查询队列。"""
    called = False

    async def should_end(run_id: str) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(agent_request_queue_service, "should_end_run_for_steer", should_end)
    runtime = SimpleNamespace(context=SimpleNamespace())

    assert await SteerMiddleware().abefore_model({}, runtime) is None
    assert called is False


@pytest.mark.asyncio
async def test_after_model_ends_tool_free_turn_when_steer_arrives(monkeypatch: pytest.MonkeyPatch):
    """模型轮次结束后才到达的 Steer 仍会让旧 Run 让位。"""

    async def should_end(run_id: str) -> bool:
        return run_id == "run-1"

    monkeypatch.setattr(agent_request_queue_service, "should_end_run_for_steer", should_end)
    runtime = SimpleNamespace(context=SimpleNamespace(run_id="run-1"))

    result = await SteerMiddleware().aafter_model(
        {"messages": [AIMessage(content="已完成当前回答")]},
        runtime,
    )

    assert result == {"jump_to": "end"}


@pytest.mark.asyncio
async def test_after_model_does_not_skip_tool_batch(monkeypatch: pytest.MonkeyPatch):
    """模型生成工具调用时，Steer 不能跳过尚未执行的工具批次。"""
    called = False

    async def should_end(run_id: str) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(agent_request_queue_service, "should_end_run_for_steer", should_end)
    runtime = SimpleNamespace(context=SimpleNamespace(run_id="run-1"))

    result = await SteerMiddleware().aafter_model(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call-1", "name": "tool", "args": {}}],
                )
            ]
        },
        runtime,
    )

    assert result is None
    assert called is False


@pytest.mark.asyncio
async def test_before_model_passes_state_message_ids_for_replay(monkeypatch):
    """注入判据来自当前 state：middleware 必须把 state 里的消息 id 传给收割函数。"""
    from langchain.messages import AIMessage, HumanMessage

    middleware = SteerMiddleware()
    captured: dict = {}

    async def fake_take(run_id, *, applied_message_ids=None):
        captured["applied"] = applied_message_ids
        return []

    async def fake_steer(run_id):
        return False

    monkeypatch.setattr("yuxi.services.agent_request_queue_service.take_pending_guided_messages", fake_take)
    monkeypatch.setattr("yuxi.services.agent_request_queue_service.should_end_run_for_steer", fake_steer)

    state = {
        "messages": [
            HumanMessage(content="hi", id="m-1"),
            AIMessage(content="ok", id="m-2"),
            HumanMessage(content="no-id"),
        ]
    }
    await middleware.abefore_model(state, _runtime())

    assert captured["applied"] == {"m-1", "m-2"}


@pytest.mark.asyncio
async def test_guided_replay_decision_uses_checkpoint_state():
    """崩溃重放判定：injected 且消息已在 checkpoint 中 → 视为已生效；否则重新注入。"""
    from yuxi.services.agent_request_queue_service import is_guided_request_applied

    applied = {"msg-applied"}

    # 已注入且已落盘 → 已生效，跳过，保证不重复注入。
    assert is_guided_request_applied("injected", "msg-applied", applied) is True
    # 已注入但提交后崩溃、消息未进 checkpoint → 必须重放。
    assert is_guided_request_applied("injected", "msg-unapplied", applied) is False
    # 未注入（仍 queued）→ 正常注入路径。
    assert is_guided_request_applied("queued", "msg-applied", applied) is False
    # 没有可用于对账的消息 id 时不跳过，宁可重放也不丢消息。
    assert is_guided_request_applied("injected", None, applied) is False
