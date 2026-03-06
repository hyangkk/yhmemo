"""
Shared test fixtures for the slack-agents multi-agent system.
"""

import asyncio
import json
import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the slack-agents package root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Dummy API key ───────────────────────────────────────

@pytest.fixture
def anthropic_api_key():
    return "sk-ant-test-dummy-key-for-testing"


# ── Mock Supabase client ────────────────────────────────

@pytest.fixture
def mock_supabase():
    """Mock Supabase client that chains .table().insert/upsert/select/update/eq().execute()"""
    client = MagicMock()

    # Build a chainable mock for table operations
    table_mock = MagicMock()
    execute_result = MagicMock()
    execute_result.data = []

    # Every method returns a chainable mock with .execute()
    for method_name in ("insert", "upsert", "update", "select", "delete"):
        method = MagicMock(return_value=table_mock)
        setattr(table_mock, method_name, method)

    table_mock.eq = MagicMock(return_value=table_mock)
    table_mock.order = MagicMock(return_value=table_mock)
    table_mock.limit = MagicMock(return_value=table_mock)
    table_mock.execute = MagicMock(return_value=execute_result)
    table_mock.on_conflict = MagicMock(return_value=table_mock)

    # Make .upsert().execute() and similar work
    for method_name in ("insert", "upsert", "update", "select", "delete"):
        getattr(table_mock, method_name).return_value = table_mock

    client.table = MagicMock(return_value=table_mock)
    client._table_mock = table_mock
    client._execute_result = execute_result
    return client


# ── Mock Slack client ───────────────────────────────────

@pytest.fixture
def mock_slack():
    """Mock Slack client with async methods."""
    slack = MagicMock()
    slack.send_message = AsyncMock(return_value={"ok": True, "ts": "1234567890.123456"})
    slack.send_thread_reply = AsyncMock(return_value={"ok": True})
    slack.add_reaction = AsyncMock(return_value={"ok": True})
    slack.send_log = AsyncMock(return_value=None)
    slack.send_rich_message = AsyncMock(return_value={"ok": True})
    return slack


# ── Mock Notion client ──────────────────────────────────

@pytest.fixture
def mock_notion():
    """Mock Notion client with async methods."""
    notion = MagicMock()
    notion.create_page = AsyncMock(return_value={"url": "https://notion.so/test-page"})
    notion.query_database = AsyncMock(return_value=[])
    notion.get_action_items = AsyncMock(return_value=[])
    return notion


# ── Mock Anthropic API ──────────────────────────────────

@pytest.fixture
def mock_anthropic_response():
    """Factory fixture: returns a function that creates a mock Anthropic response."""
    def _make_response(text: str):
        response = MagicMock()
        content_block = MagicMock()
        content_block.text = text
        response.content = [content_block]
        return response
    return _make_response


# ── Mock MessageBus ─────────────────────────────────────

@pytest.fixture
def mock_message_bus():
    """Mock MessageBus with common methods."""
    bus = MagicMock()
    bus.register_agent = MagicMock()
    bus.subscribe = MagicMock()
    bus.send_task = AsyncMock(return_value="task-id-123")
    bus.broadcast = AsyncMock()
    bus._handlers = {}
    bus._event_listeners = {}
    return bus


# ── Agent factory ───────────────────────────────────────

@pytest.fixture
def agent_factory(mock_message_bus, mock_slack, mock_notion, mock_supabase, anthropic_api_key):
    """Factory function that creates agents with all mocks injected.

    Usage:
        agent = agent_factory(CollectorAgent, extra_kwarg="value")
    """
    def _create(agent_class, **extra_kwargs):
        # Patch agent_tracker so it doesn't touch disk
        with patch("core.agent_tracker.register_agent"), \
             patch("core.agent_tracker.heartbeat"), \
             patch("core.agent_tracker.record_error"), \
             patch("core.agent_tracker.mark_stopped"):
            agent = agent_class(
                message_bus=mock_message_bus,
                slack_client=mock_slack,
                notion_client=mock_notion,
                supabase_client=mock_supabase,
                anthropic_api_key=anthropic_api_key,
                **extra_kwargs,
            )
        return agent
    return _create
