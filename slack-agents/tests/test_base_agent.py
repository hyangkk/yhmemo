"""
Tests for core/base_agent.py
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from core.base_agent import BaseAgent
from core.message_bus import MessageBus, TaskMessage


# ── Concrete test agent (since BaseAgent is abstract) ───

class DummyAgent(BaseAgent):
    """Minimal concrete implementation for testing."""

    def __init__(self, **kwargs):
        self.observe_returns = None
        self.think_returns = None
        self.act_called_with = []
        self.observe_raises = None
        super().__init__(
            name="dummy",
            description="A dummy test agent",
            loop_interval=1,
            **kwargs,
        )

    async def observe(self):
        if self.observe_raises:
            raise self.observe_raises
        return self.observe_returns

    async def think(self, context):
        return self.think_returns

    async def act(self, decision):
        self.act_called_with.append(decision)


# ── Lifecycle tests ─────────────────────────────────────

@pytest.mark.asyncio
async def test_start_stop_lifecycle(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    assert agent._running is False
    # Start the agent in background and stop after a brief run
    task = asyncio.create_task(agent.start())
    await asyncio.sleep(0.1)
    assert agent._running is True
    agent.stop()
    await asyncio.sleep(0.1)
    assert agent._running is False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ── Observe -> Think -> Act loop ────────────────────────

@pytest.mark.asyncio
async def test_observe_think_act_loop(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    agent.observe_returns = {"info": "test context"}
    agent.think_returns = {"action": "do_something"}

    task = asyncio.create_task(agent.start())
    await asyncio.sleep(0.15)
    agent.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(agent.act_called_with) >= 1
    assert agent.act_called_with[0] == {"action": "do_something"}


@pytest.mark.asyncio
async def test_loop_skips_act_when_think_returns_none(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    agent.observe_returns = {"data": True}
    agent.think_returns = None  # No action needed

    task = asyncio.create_task(agent.start())
    await asyncio.sleep(0.15)
    agent.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(agent.act_called_with) == 0


@pytest.mark.asyncio
async def test_loop_skips_when_observe_returns_none(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    agent.observe_returns = None

    task = asyncio.create_task(agent.start())
    await asyncio.sleep(0.15)
    agent.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(agent.act_called_with) == 0


# ── Error handling in loop ──────────────────────────────

@pytest.mark.asyncio
async def test_agent_continues_after_error(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    agent.observe_raises = ValueError("test error")

    task = asyncio.create_task(agent.start())
    # Let it run a couple cycles with errors
    await asyncio.sleep(0.3)
    # Agent should still be running despite errors
    assert agent._running is True
    agent.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Log method should have been called with error messages
    mock_slack.send_log.assert_called()


# ── ai_think ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_think_calls_anthropic(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key, mock_anthropic_response):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    # Mock the anthropic client's messages.create
    agent.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response("Hello from AI")
    )

    result = await agent.ai_think("system prompt", "user prompt")
    assert result == "Hello from AI"

    agent.ai.messages.create.assert_called_once_with(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system="system prompt",
        messages=[{"role": "user", "content": "user prompt"}],
    )


@pytest.mark.asyncio
async def test_ai_think_custom_model(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key, mock_anthropic_response):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    agent.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response("response")
    )

    await agent.ai_think("sys", "user", model="claude-haiku-4-20250414")
    call_kwargs = agent.ai.messages.create.call_args[1]
    assert call_kwargs["model"] == "claude-haiku-4-20250414"


# ── ai_decide ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_ai_decide_parses_json(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key, mock_anthropic_response):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    response_json = json.dumps({"action": "collect", "reason": "test", "details": {"target": "news"}})
    agent.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response(response_json)
    )

    result = await agent.ai_decide({"situation": "test"}, ["collect", "skip"])
    assert result["action"] == "collect"
    assert result["details"]["target"] == "news"


@pytest.mark.asyncio
async def test_ai_decide_parses_json_code_block(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key, mock_anthropic_response):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    response_text = '```json\n{"action": "skip", "reason": "nothing to do", "details": {}}\n```'
    agent.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response(response_text)
    )

    result = await agent.ai_decide({"test": True})
    assert result["action"] == "skip"


@pytest.mark.asyncio
async def test_ai_decide_handles_invalid_json(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key, mock_anthropic_response):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    agent.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response("This is not JSON at all")
    )

    result = await agent.ai_decide({"test": True})
    assert result["action"] == "raw_response"
    assert "This is not JSON at all" in result["reason"]


# ── say / log ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_say_sends_to_correct_channel(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    await agent.say("test message")
    # DummyAgent doesn't set slack_channel, so nothing should be sent
    mock_slack.send_message.assert_not_called()

    # With explicit channel
    await agent.say("hello", channel="test-channel")
    mock_slack.send_message.assert_called_once()
    call_args = mock_slack.send_message.call_args
    assert call_args[0][0] == "test-channel"
    assert "*[dummy]*" in call_args[0][1]


@pytest.mark.asyncio
async def test_log_sends_to_log_channel(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    await agent.log("something happened")
    mock_slack.send_log.assert_called_once()
    call_args = mock_slack.send_log.call_args[0][0]
    assert "[dummy]" in call_args
    assert "something happened" in call_args


# ── Registration on bus ─────────────────────────────────

def test_agent_registers_on_bus(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key):
    with patch("core.agent_tracker.register_agent"), \
         patch("core.agent_tracker.heartbeat"), \
         patch("core.agent_tracker.record_error"), \
         patch("core.agent_tracker.mark_stopped"):
        agent = DummyAgent(
            message_bus=mock_message_bus,
            slack_client=mock_slack,
            notion_client=mock_notion,
            supabase_client=mock_supabase,
            anthropic_api_key=anthropic_api_key,
        )

    mock_message_bus.register_agent.assert_called_once_with("dummy", agent._handle_task)
