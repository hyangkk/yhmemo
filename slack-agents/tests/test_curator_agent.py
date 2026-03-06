"""
Tests for agents/curator_agent.py
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.curator_agent import CuratorAgent
from core.message_bus import TaskMessage


# ── Helper: create a CuratorAgent with mocks ─────────────

@pytest.fixture
def curator(agent_factory):
    """Create a CuratorAgent with all mocks injected."""
    return agent_factory(CuratorAgent, notion_db_id="test-db-id")


# ── observe ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_observe_with_empty_buffer_and_no_actions(curator, mock_supabase):
    """When buffer is empty and no action items, observe returns None."""
    # Supabase returns no preferences
    mock_supabase._execute_result.data = []

    context = await curator.observe()
    assert context is None


@pytest.mark.asyncio
async def test_observe_with_articles_in_buffer(curator, mock_supabase):
    """When articles exist in buffer, observe returns context."""
    curator._new_articles_buffer = [
        {"title": "Test Article", "source": "test", "url": "https://example.com"},
    ]
    mock_supabase._execute_result.data = []

    context = await curator.observe()
    assert context is not None
    assert context["new_articles_count"] == 1
    assert len(context["new_articles"]) == 1


# ── think ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_think_parses_ai_selection(curator, mock_anthropic_response):
    """Think correctly parses AI JSON selection response."""
    context = {
        "current_time": "2026-03-06 10:00",
        "new_articles_count": 3,
        "new_articles": [
            {"title": "AI Breakthrough", "source": "TechCrunch", "url": "https://tc.com/1"},
            {"title": "Startup Funding", "source": "GeekNews", "url": "https://gn.com/2"},
            {"title": "Weather Update", "source": "News", "url": "https://news.com/3"},
        ],
        "user_preferences": {},
    }

    ai_response = json.dumps({
        "selected": [
            {"index": 0, "score": 0.9, "reason": "AI related", "summary": "AI breakthrough summary"},
        ],
        "rejected_reason": "Not relevant",
        "briefing": "AI news today",
    })
    curator.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response(ai_response)
    )

    decision = await curator.think(context)
    assert decision is not None
    assert decision["action"] == "curate_and_brief"
    assert len(decision["selected"]) == 1
    assert decision["selected"][0]["score"] == 0.9
    assert decision["briefing"] == "AI news today"


@pytest.mark.asyncio
async def test_think_with_no_articles_but_action_items(curator):
    """When no new articles but action items exist, return process_action_items."""
    context = {
        "current_time": "2026-03-06 10:00",
        "new_articles_count": 0,
        "new_articles": [],
        "user_preferences": {},
        "action_items": ["Research AI tools"],
    }

    decision = await curator.think(context)
    assert decision is not None
    assert decision["action"] == "process_action_items"
    assert decision["items"] == ["Research AI tools"]


@pytest.mark.asyncio
async def test_think_returns_none_with_nothing(curator):
    """No articles, no action items -> None."""
    context = {
        "current_time": "2026-03-06 10:00",
        "new_articles_count": 0,
        "new_articles": [],
        "user_preferences": {},
    }

    decision = await curator.think(context)
    assert decision is None


@pytest.mark.asyncio
async def test_think_handles_json_in_code_block(curator, mock_anthropic_response):
    """Think handles AI response wrapped in ```json code block."""
    context = {
        "current_time": "2026-03-06 10:00",
        "new_articles_count": 1,
        "new_articles": [
            {"title": "Test", "source": "src", "url": "https://example.com"},
        ],
        "user_preferences": {},
    }

    ai_response = '```json\n{"selected": [{"index": 0, "score": 0.8, "reason": "good", "summary": "test"}], "rejected_reason": "n/a", "briefing": "briefing"}\n```'
    curator.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response(ai_response)
    )

    decision = await curator.think(context)
    assert decision is not None
    assert decision["action"] == "curate_and_brief"


@pytest.mark.asyncio
async def test_think_returns_none_on_invalid_json(curator, mock_anthropic_response):
    """Think returns None if AI gives invalid JSON."""
    context = {
        "current_time": "2026-03-06 10:00",
        "new_articles_count": 1,
        "new_articles": [{"title": "T", "source": "s", "url": "u"}],
        "user_preferences": {},
    }

    curator.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response("This is not valid JSON at all.")
    )

    decision = await curator.think(context)
    assert decision is None


# ── act (briefing to correct channel) ────────────────────

@pytest.mark.asyncio
async def test_act_sends_briefing_to_default_channel(curator, mock_slack, mock_supabase):
    """Without thread context, briefing goes to ai-curator channel."""
    decision = {
        "action": "curate_and_brief",
        "selected": [
            {"index": 0, "score": 0.85, "reason": "relevant", "summary": "AI news summary"},
        ],
        "articles": [
            {"title": "AI News", "source": "TechCrunch", "url": "https://tc.com/1"},
        ],
        "briefing": "Today's AI news",
        "rejected_reason": "n/a",
        "query": "",
    }

    await curator.act(decision)

    # Should send to ai-curator (default, no thread context)
    mock_slack.send_message.assert_called()
    call_args = mock_slack.send_message.call_args
    assert call_args[0][0] == "ai-curator"


@pytest.mark.asyncio
async def test_act_sends_briefing_to_thread(curator, mock_slack, mock_supabase):
    """With thread context, briefing goes to specified channel/thread."""
    decision = {
        "action": "curate_and_brief",
        "selected": [
            {"index": 0, "score": 0.85, "reason": "relevant", "summary": "summary"},
        ],
        "articles": [
            {"title": "Article", "source": "src", "url": "https://example.com"},
        ],
        "briefing": "briefing text",
        "rejected_reason": "n/a",
        "query": "AI",
        "thread_ts": "1234567890.123",
        "channel": "ai-agents-general",
    }

    await curator.act(decision)

    # Should send thread reply
    mock_slack.send_thread_reply.assert_called()
    call_args = mock_slack.send_thread_reply.call_args
    assert call_args[0][0] == "ai-agents-general"  # channel
    assert call_args[0][1] == "1234567890.123"  # thread_ts
    assert isinstance(call_args[0][2], str)  # text (briefing message)


# ── handle_reaction_feedback ─────────────────────────────

@pytest.mark.asyncio
async def test_handle_reaction_feedback_positive(curator, mock_supabase):
    """Positive reactions are saved as positive feedback."""
    item = {"ts": "123456.789"}
    await curator.handle_reaction_feedback("thumbsup", item)

    mock_supabase.table.assert_called_with("feedback_log")
    insert_call = mock_supabase._table_mock.insert.call_args[0][0]
    assert insert_call["feedback_type"] == "positive"
    assert insert_call["reaction"] == "thumbsup"


@pytest.mark.asyncio
async def test_handle_reaction_feedback_negative(curator, mock_supabase):
    """Negative reactions are saved as negative feedback."""
    item = {"ts": "123456.789"}
    await curator.handle_reaction_feedback("thumbsdown", item)

    insert_call = mock_supabase._table_mock.insert.call_args[0][0]
    assert insert_call["feedback_type"] == "negative"


@pytest.mark.asyncio
async def test_handle_reaction_feedback_unknown_ignored(curator, mock_supabase):
    """Unknown reactions are ignored (no database call)."""
    item = {"ts": "123456.789"}

    # Reset call count
    mock_supabase.table.reset_mock()

    await curator.handle_reaction_feedback("smile", item)
    # Should not call supabase for unknown reactions
    mock_supabase.table.assert_not_called()


# ── _on_new_articles (buffering) ─────────────────────────

@pytest.mark.asyncio
async def test_on_new_articles_buffers_correctly(curator):
    """New articles event adds items to buffer."""
    task = TaskMessage(
        from_agent="collector",
        to_agent="broadcast",
        task_type="new_articles",
        payload={
            "items": [
                {"title": "A1", "source": "s1"},
                {"title": "A2", "source": "s2"},
            ],
        },
    )

    # Patch _do_curate to prevent actual curation
    curator._do_curate = AsyncMock()

    await curator._on_new_articles(task)
    assert len(curator._new_articles_buffer) == 2
    assert curator._new_articles_buffer[0]["title"] == "A1"


@pytest.mark.asyncio
async def test_on_new_articles_triggers_curate_for_user_request(curator):
    """User-requested articles (with query) trigger immediate curation."""
    task = TaskMessage(
        from_agent="collector",
        to_agent="broadcast",
        task_type="new_articles",
        payload={
            "items": [{"title": "Result", "source": "search"}],
            "query": "AI startups",
        },
    )

    curator._do_curate = AsyncMock()
    await curator._on_new_articles(task)

    # _do_curate should be called for user requests
    curator._do_curate.assert_called_once()


@pytest.mark.asyncio
async def test_on_new_articles_does_not_trigger_for_routine(curator):
    """Routine articles (without query) don't trigger immediate curation."""
    task = TaskMessage(
        from_agent="collector",
        to_agent="broadcast",
        task_type="new_articles",
        payload={
            "items": [{"title": "Routine", "source": "rss"}],
        },
    )

    curator._do_curate = AsyncMock()
    await curator._on_new_articles(task)

    # _do_curate should NOT be called for routine collection
    curator._do_curate.assert_not_called()


# ── set_query_context ────────────────────────────────────

def test_set_query_context(curator):
    """set_query_context stores query, thread_ts, and channel."""
    curator.set_query_context("blockchain", thread_ts="1111.222", channel="test-ch")
    assert curator._current_query == "blockchain"
    assert curator._request_thread_ts == "1111.222"
    assert curator._request_channel == "test-ch"


# ── _consume_buffer / _clear_context ─────────────────────

def test_consume_buffer(curator):
    curator._new_articles_buffer = [{"a": 1}, {"b": 2}, {"c": 3}]
    curator._consume_buffer(2)
    assert len(curator._new_articles_buffer) == 1
    assert curator._new_articles_buffer[0] == {"c": 3}


def test_clear_context(curator):
    curator._current_query = "test"
    curator._request_thread_ts = "123.456"
    curator._request_channel = "ch"
    curator._clear_context()
    assert curator._current_query == ""
    assert curator._request_thread_ts is None
    assert curator._request_channel is None
