"""
Tests for core/message_bus.py
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.message_bus import MessageBus, TaskMessage, TaskStatus


# ── Agent registration ──────────────────────────────────

def test_register_agent():
    bus = MessageBus()
    handler = AsyncMock()
    bus.register_agent("test_agent", handler)
    assert "test_agent" in bus._handlers
    assert bus._handlers["test_agent"] is handler


def test_register_multiple_agents():
    bus = MessageBus()
    h1 = AsyncMock()
    h2 = AsyncMock()
    bus.register_agent("agent_a", h1)
    bus.register_agent("agent_b", h2)
    assert len(bus._handlers) == 2


# ── Task sending and routing ────────────────────────────

@pytest.mark.asyncio
async def test_send_task_puts_on_queue():
    bus = MessageBus()
    task = TaskMessage(from_agent="a", to_agent="b", task_type="do_work")
    task_id = await bus.send_task(task)
    assert task_id == task.id
    assert bus._queue.qsize() == 1


@pytest.mark.asyncio
async def test_send_task_persists_with_supabase():
    mock_sb = MagicMock()
    table_mock = MagicMock()
    table_mock.insert.return_value = table_mock
    table_mock.execute.return_value = MagicMock()
    mock_sb.table.return_value = table_mock

    bus = MessageBus(supabase_client=mock_sb)
    task = TaskMessage(from_agent="a", to_agent="b", task_type="test")
    await bus.send_task(task)
    # Queue should have the task
    assert bus._queue.qsize() == 1


@pytest.mark.asyncio
async def test_task_routed_to_correct_handler():
    bus = MessageBus()
    handler_a = AsyncMock(return_value="result_a")
    handler_b = AsyncMock(return_value="result_b")
    bus.register_agent("agent_a", handler_a)
    bus.register_agent("agent_b", handler_b)

    task = TaskMessage(from_agent="agent_a", to_agent="agent_b", task_type="work")
    await bus.send_task(task)

    # Run the bus briefly to process the task
    run_task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.1)
    bus.stop()
    await asyncio.sleep(0.1)
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass

    handler_b.assert_called_once()
    handler_a.assert_not_called()


# ── Task status transitions ────────────────────────────

@pytest.mark.asyncio
async def test_task_status_transitions_on_success():
    bus = MessageBus()
    handler = AsyncMock(return_value={"ok": True})
    bus.register_agent("worker", handler)

    task = TaskMessage(from_agent="boss", to_agent="worker", task_type="job")
    assert task.status == TaskStatus.PENDING

    await bus.send_task(task)

    run_task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.1)
    bus.stop()
    await asyncio.sleep(0.1)
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass

    assert task.status == TaskStatus.COMPLETED
    assert task.result == {"ok": True}


@pytest.mark.asyncio
async def test_task_status_transitions_on_failure():
    bus = MessageBus()
    handler = AsyncMock(side_effect=RuntimeError("something broke"))
    bus.register_agent("worker", handler)

    task = TaskMessage(from_agent="boss", to_agent="worker", task_type="job")
    await bus.send_task(task)

    run_task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.1)
    bus.stop()
    await asyncio.sleep(0.1)
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass

    assert task.status == TaskStatus.FAILED
    assert "something broke" in task.result["error"]


# ── Broadcast ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_broadcast_to_multiple_subscribers():
    bus = MessageBus()
    listener_1 = AsyncMock()
    listener_2 = AsyncMock()
    bus.subscribe("event_x", listener_1)
    bus.subscribe("event_x", listener_2)

    await bus.broadcast("sender", "event_x", {"key": "value"})

    listener_1.assert_called_once()
    listener_2.assert_called_once()
    # Verify the task passed to listeners has correct fields
    call_task = listener_1.call_args[0][0]
    assert call_task.from_agent == "sender"
    assert call_task.task_type == "event_x"
    assert call_task.payload == {"key": "value"}


@pytest.mark.asyncio
async def test_broadcast_no_subscribers():
    bus = MessageBus()
    # Should not raise
    await bus.broadcast("sender", "nobody_listens", {"data": 1})


@pytest.mark.asyncio
async def test_broadcast_listener_error_does_not_crash():
    bus = MessageBus()
    bad_listener = AsyncMock(side_effect=ValueError("oops"))
    good_listener = AsyncMock()
    bus.subscribe("event", bad_listener)
    bus.subscribe("event", good_listener)

    await bus.broadcast("sender", "event", {})
    # Good listener should still be called despite bad listener error
    good_listener.assert_called_once()


# ── Unregistered agent ──────────────────────────────────

@pytest.mark.asyncio
async def test_unregistered_agent_task_dropped():
    bus = MessageBus()
    # No handler registered for "ghost_agent"
    task = TaskMessage(from_agent="sender", to_agent="ghost_agent", task_type="work")
    await bus.send_task(task)

    run_task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.1)
    bus.stop()
    await asyncio.sleep(0.1)
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass

    # Task should remain PENDING since no handler processed it
    assert task.status == TaskStatus.PENDING


# ── TaskMessage defaults ────────────────────────────────

def test_task_message_defaults():
    task = TaskMessage(from_agent="a", to_agent="b", task_type="test")
    assert task.status == TaskStatus.PENDING
    assert task.result is None
    assert task.payload == {}
    assert task.id  # Should have a UUID
    assert task.created_at is not None
