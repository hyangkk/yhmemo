"""
Tests for agents/collector_agent.py
"""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.collector_agent import CollectorAgent, RSS_SOURCES, GOOGLE_NEWS_SEARCH
from core.message_bus import TaskMessage


# ── Helper: create a CollectorAgent with mocks ───────────

@pytest.fixture
def collector(agent_factory):
    """Create a CollectorAgent with all mocks injected."""
    return agent_factory(CollectorAgent)


# ── observe ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_observe_returns_context(collector):
    context = await collector.observe()
    assert context is not None
    assert "current_time" in context
    assert "pending_requests" in context
    assert "sources_available" in context
    assert "priority" in context


@pytest.mark.asyncio
async def test_observe_with_pending_requests(collector):
    collector._pending_requests.append({"query": "AI", "requester": "curator"})
    context = await collector.observe()
    assert context["priority"] == "requested_collection"
    assert len(context["pending_requests"]) == 1


@pytest.mark.asyncio
async def test_observe_routine_when_no_requests(collector):
    context = await collector.observe()
    assert context["priority"] == "routine_collection"


# ── think ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_think_with_pending_requests_returns_targeted(collector):
    collector._pending_requests.append({"query": "blockchain", "requester": "curator"})
    context = await collector.observe()
    decision = await collector.think(context)

    assert decision is not None
    assert decision["action"] == "targeted_collection"
    assert len(decision["requests"]) == 1
    assert decision["requests"][0]["query"] == "blockchain"
    # pending_requests should be cleared after think
    assert len(collector._pending_requests) == 0


@pytest.mark.asyncio
async def test_think_routine_returns_routine_collection(collector, mock_anthropic_response):
    context = {
        "current_time": "2026-03-06 10:00",
        "pending_requests": [],
        "sources_available": list(RSS_SOURCES.keys()),
        "priority": "routine_collection",
    }

    # Mock AI to decide collect_all
    ai_response = json.dumps({
        "action": "collect_all",
        "reason": "time to collect",
        "details": {"sources": ["GeekNews", "TechCrunch"]},
    })
    collector.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response(ai_response)
    )

    decision = await collector.think(context)
    assert decision is not None
    assert decision["action"] == "routine_collection"
    assert "sources" in decision


@pytest.mark.asyncio
async def test_think_routine_skip_returns_none(collector, mock_anthropic_response):
    context = {
        "current_time": "2026-03-06 03:00",
        "pending_requests": [],
        "sources_available": list(RSS_SOURCES.keys()),
        "priority": "routine_collection",
    }

    ai_response = json.dumps({
        "action": "skip",
        "reason": "too early",
        "details": {},
    })
    collector.ai.messages.create = AsyncMock(
        return_value=mock_anthropic_response(ai_response)
    )

    decision = await collector.think(context)
    assert decision is None


# ── _fetch_rss ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_rss_parses_entries(collector):
    """Mock httpx response + feedparser to test RSS parsing."""
    fake_xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <item>
          <title>Test Article 1</title>
          <link>https://example.com/1</link>
          <description>Summary of article 1</description>
          <pubDate>Mon, 06 Mar 2026 10:00:00 GMT</pubDate>
        </item>
        <item>
          <title>Test Article 2</title>
          <link>https://example.com/2</link>
          <description>Summary of article 2</description>
          <pubDate>Mon, 06 Mar 2026 11:00:00 GMT</pubDate>
        </item>
        <item>
          <title></title>
          <link>https://example.com/empty</link>
        </item>
      </channel>
    </rss>"""

    mock_response = MagicMock()
    mock_response.text = fake_xml
    collector._http.get = AsyncMock(return_value=mock_response)

    items = await collector._fetch_rss("test_source", "https://fake.rss/feed")

    # Empty-title entry should be excluded
    assert len(items) == 2
    assert items[0]["source"] == "test_source"
    assert items[0]["title"] == "Test Article 1"
    assert items[0]["url"] == "https://example.com/1"
    assert items[0]["source_type"] == "rss"
    assert "hash" in items[0]


@pytest.mark.asyncio
async def test_fetch_rss_returns_empty_on_error(collector):
    collector._http.get = AsyncMock(side_effect=Exception("network error"))
    items = await collector._fetch_rss("bad_source", "https://broken.url")
    assert items == []


# ── _save_items (deduplication) ──────────────────────────

@pytest.mark.asyncio
async def test_save_items_handles_duplicates(collector, mock_supabase):
    items = [
        {"title": "Article A", "hash": "aaa", "source": "test"},
        {"title": "Article B", "hash": "bbb", "source": "test"},
    ]

    # First item succeeds, second is a duplicate
    call_count = 0
    original_execute = mock_supabase._table_mock.execute

    def side_effect_execute():
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("duplicate key violation")
        result = MagicMock()
        result.data = [items[0]]
        return result

    mock_supabase._table_mock.execute = MagicMock(side_effect=side_effect_execute)

    saved = await collector._save_items(items)
    # At least one item should be saved
    assert len(saved) >= 1


# ── hash deduplication ───────────────────────────────────

def test_hash_deduplication():
    """Same title+link should produce same hash."""
    title = "Breaking News"
    link = "https://example.com/news"
    hash1 = hashlib.sha256(f"{title}{link}".encode()).hexdigest()[:16]
    hash2 = hashlib.sha256(f"{title}{link}".encode()).hexdigest()[:16]
    assert hash1 == hash2

    # Different content should produce different hash
    hash3 = hashlib.sha256(f"Other Title{link}".encode()).hexdigest()[:16]
    assert hash1 != hash3


# ── handle_external_task ─────────────────────────────────

@pytest.mark.asyncio
async def test_handle_external_task_collect_by_keyword(collector):
    task = TaskMessage(
        from_agent="curator",
        to_agent="collector",
        task_type="collect_by_keyword",
        payload={"query": "AI startups"},
    )

    result = await collector.handle_external_task(task)
    assert result["status"] == "queued"
    assert result["query"] == "AI startups"
    assert len(collector._pending_requests) == 1
    assert collector._pending_requests[0]["query"] == "AI startups"
    assert collector._pending_requests[0]["requester"] == "curator"


@pytest.mark.asyncio
async def test_handle_external_task_collect_from_source(collector, mock_supabase):
    """Test collect_from_source task type."""
    # Mock _fetch_rss to avoid real HTTP calls
    collector._fetch_rss = AsyncMock(return_value=[])

    task = TaskMessage(
        from_agent="master",
        to_agent="collector",
        task_type="collect_from_source",
        payload={"sources": ["GeekNews"]},
    )

    result = await collector.handle_external_task(task)
    assert result["status"] == "completed"
    assert result["sources"] == ["GeekNews"]


@pytest.mark.asyncio
async def test_handle_external_task_unhandled(collector):
    task = TaskMessage(
        from_agent="unknown",
        to_agent="collector",
        task_type="unknown_task",
        payload={},
    )

    result = await collector.handle_external_task(task)
    assert result["status"] == "unhandled"


# ── act ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_act_targeted_collection(collector):
    """Act with targeted_collection calls _collect_by_keyword."""
    collector._collect_by_keyword = AsyncMock()

    decision = {
        "action": "targeted_collection",
        "requests": [
            {"query": "fintech", "requester": "curator"},
            {"query": "blockchain", "requester": "master"},
        ],
    }

    await collector.act(decision)
    assert collector._collect_by_keyword.call_count == 2
    collector._collect_by_keyword.assert_any_call("fintech", "curator")
    collector._collect_by_keyword.assert_any_call("blockchain", "master")


@pytest.mark.asyncio
async def test_act_routine_collection(collector):
    """Act with routine_collection calls _collect_from_rss."""
    collector._collect_from_rss = AsyncMock()

    decision = {
        "action": "routine_collection",
        "sources": ["GeekNews", "TechCrunch"],
    }

    await collector.act(decision)
    collector._collect_from_rss.assert_called_once_with(["GeekNews", "TechCrunch"])
