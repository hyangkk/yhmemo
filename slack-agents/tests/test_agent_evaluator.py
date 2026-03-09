"""
Tests for core/agent_evaluator.py — 에이전트 평가 + 인사조치 테스트
"""

import json
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 모듈을 먼저 import하여 로드
import core.agent_evaluator as evaluator_module
from core.agent_evaluator import AgentEvaluator


# ── agent_tracker mock data ────────────────────────────

MOCK_TRACKER_DATA = {
    "agents": {
        "collector": {
            "status": "running",
            "cycles": 100,
            "uptime_pct": 95.0,
            "errors": 2,
        },
        "curator": {
            "status": "running",
            "cycles": 80,
            "uptime_pct": 90.0,
            "errors": 5,
        },
        "dyn_bad_agent": {
            "status": "error",
            "cycles": 50,
            "uptime_pct": 20.0,
            "errors": 40,
        },
        "dyn_good_agent": {
            "status": "running",
            "cycles": 60,
            "uptime_pct": 98.0,
            "errors": 1,
        },
    }
}


@pytest.fixture
def tmp_data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def mock_factory():
    factory = MagicMock()
    factory._registry = {
        "agents": {
            "dyn_bad_agent": {
                "status": "active",
                "purpose": "테스트용 부진 에이전트",
                "description": "부진 테스트",
                "slack_channel": "test",
                "loop_interval": 300,
                "performance": {"cycles": 50, "successes": 10, "failures": 40, "score": 0.15},
            },
            "dyn_good_agent": {
                "status": "active",
                "purpose": "테스트용 우수 에이전트",
                "description": "우수 테스트",
                "performance": {"cycles": 60, "successes": 58, "failures": 2, "score": 0.92},
            },
        }
    }
    factory.get_active_agents.return_value = {
        "dyn_bad_agent": factory._registry["agents"]["dyn_bad_agent"],
        "dyn_good_agent": factory._registry["agents"]["dyn_good_agent"],
    }
    factory.retire_agent = AsyncMock(return_value=True)
    factory.rebuild_agent = AsyncMock(return_value={"success": True, "agent_name": "dyn_bad_agent"})
    factory.create_agent = AsyncMock(return_value={"success": True, "agent_name": "dyn_new"})
    factory.start_agent = AsyncMock(return_value=True)
    factory.get_agent_count.return_value = 2
    return factory


@pytest.fixture
def mock_delegation():
    delegation = MagicMock()
    delegation.get_agent_reliability.return_value = 0.7
    delegation._bus = MagicMock()
    delegation._bus._handlers = {"collector": None, "curator": None}
    return delegation


@pytest.fixture
def mock_tracker():
    tracker = MagicMock()
    tracker.get_summary_for_report.return_value = MOCK_TRACKER_DATA
    return tracker


@pytest.fixture
def evaluator(tmp_data_dir, mock_factory, mock_delegation, mock_tracker):
    original_tracker = evaluator_module.agent_tracker
    evaluator_module.agent_tracker = mock_tracker

    ev = AgentEvaluator(
        agent_factory=mock_factory,
        task_delegation=mock_delegation,
        ai_think_fn=None,
    )
    ev._eval_file = os.path.join(tmp_data_dir, "agent_evaluations.json")

    yield ev

    evaluator_module.agent_tracker = original_tracker


# ── 개별 에이전트 평가 테스트 ────────────────────────

def test_evaluate_static_agent_uses_tracker_data(evaluator):
    """정적 에이전트 평가 시 agent_tracker 실데이터를 사용하는지 확인"""
    ev = evaluator.evaluate_agent("collector")

    assert ev["grade"] in ("A", "B", "C", "D", "F")
    metrics = ev["metrics"]
    assert metrics["uptime_pct"] == 95.0
    assert metrics["cycle_count"] == 100
    assert metrics["error_count"] == 2


def test_evaluate_dynamic_agent_combines_factory_and_tracker(evaluator):
    """동적 에이전트 평가 시 팩토리+트래커 데이터를 합산하는지 확인"""
    ev = evaluator.evaluate_agent("dyn_bad_agent")

    metrics = ev["metrics"]
    assert metrics["is_dynamic"] is True
    assert metrics["composite_score"] < 0.4
    assert ev["grade"] in ("D", "F")


def test_evaluate_good_dynamic_agent(evaluator):
    """우수 동적 에이전트는 높은 등급을 받는지 확인"""
    ev = evaluator.evaluate_agent("dyn_good_agent")

    metrics = ev["metrics"]
    assert metrics["is_dynamic"] is True
    assert metrics["composite_score"] > 0.7
    assert ev["grade"] in ("A", "B")


# ── 전체 평가 + 인사조치 테스트 ─────────────────────

@pytest.mark.asyncio
async def test_evaluate_all_includes_tracker_agents(evaluator):
    """evaluate_all이 tracker에 등록된 모든 에이전트를 평가하는지 확인"""
    review = await evaluator.evaluate_all()

    assert review["agent_count"] >= 4
    assert "collector" in review["grades"]
    assert "dyn_bad_agent" in review["grades"]
    assert "dyn_good_agent" in review["grades"]


@pytest.mark.asyncio
async def test_enforce_actions_retires_f_grade(evaluator, mock_factory):
    """F등급 동적 에이전트가 폐기되는지 확인"""
    review = {
        "underperformers": [
            {"name": "dyn_bad_agent", "grade": "F", "score": 0.1},
        ],
        "top_performers": [],
        "should_create": [],
        "should_retire": [],
    }

    actions = await evaluator.enforce_actions(review)
    assert any(a["action"] == "retire" and a["agent"] == "dyn_bad_agent" for a in actions)
    mock_factory.retire_agent.assert_called_once()


@pytest.mark.asyncio
async def test_enforce_actions_rebuilds_d_grade(evaluator, mock_factory):
    """D등급 동적 에이전트가 재생성되는지 확인"""
    review = {
        "underperformers": [
            {"name": "dyn_bad_agent", "grade": "D", "score": 0.25},
        ],
        "top_performers": [],
        "should_create": [],
        "should_retire": [],
    }

    actions = await evaluator.enforce_actions(review)
    assert any(a["action"] == "rebuild" for a in actions)
    mock_factory.rebuild_agent.assert_called_once()


@pytest.mark.asyncio
async def test_enforce_creates_recommended_agents(evaluator, mock_factory):
    """AI 추천 에이전트를 생성하는지 확인"""
    review = {
        "underperformers": [],
        "top_performers": [],
        "should_create": [
            {"name": "market_watcher", "purpose": "시장 감시"},
        ],
        "should_retire": [],
    }

    actions = await evaluator.enforce_actions(review)
    assert any(a["action"] == "create" for a in actions)
    mock_factory.create_agent.assert_called_once()
    mock_factory.start_agent.assert_called_once()


# ── 등급 계산 테스트 ────────────────────────────────

def test_grade_computation(evaluator):
    assert evaluator._compute_grade({"composite_score": 0.95}) == "A"
    assert evaluator._compute_grade({"composite_score": 0.75}) == "B"
    assert evaluator._compute_grade({"composite_score": 0.55}) == "C"
    assert evaluator._compute_grade({"composite_score": 0.35}) == "D"
    assert evaluator._compute_grade({"composite_score": 0.15}) == "F"


# ── 조직 건강도 테스트 ──────────────────────────────

def test_org_health_report(evaluator):
    health = evaluator.get_org_health()
    assert "health" in health
    assert "avg_score" in health

    summary = evaluator.get_summary()
    assert "조직 건강도" in summary
