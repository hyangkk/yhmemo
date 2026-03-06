"""
Tests for core/self_memory.py
"""

import json
import os
from unittest.mock import patch

import pytest

from core.self_memory import SelfMemory, _default_data, LIMITS


# ── Fixture: SelfMemory using tmp_path ───────────────────

@pytest.fixture
def memory(tmp_path):
    """Create a SelfMemory that uses a temporary directory."""
    data_dir = str(tmp_path)
    file_path = os.path.join(data_dir, "self_memory.json")
    with patch("core.self_memory.DATA_DIR", data_dir):
        mem = SelfMemory.__new__(SelfMemory)
        mem._file = file_path
        os.makedirs(data_dir, exist_ok=True)
        mem._data = _default_data()
        mem._migrate_if_needed()
    return mem


# ── Initial data structure ───────────────────────────────

def test_default_data_structure():
    data = _default_data()
    assert "identity" in data
    assert "knowledge" in data
    assert "plans" in data
    assert "action_items" in data
    assert "daily_logs" in data
    assert "core_mission" in data["identity"]
    assert "partner_directives" in data["identity"]
    assert "decision_principles" in data["identity"]
    assert "insights" in data["knowledge"]
    assert "evaluations" in data["knowledge"]
    assert "failure_lessons" in data["knowledge"]


# ── Directives ───────────────────────────────────────────

def test_add_directive(memory):
    initial_count = len(memory.get_directives())
    memory.add_directive("New test directive")
    directives = memory.get_directives()
    assert len(directives) == initial_count + 1
    assert "New test directive" in directives


def test_add_duplicate_directive(memory):
    memory.add_directive("Unique directive")
    count_after_first = len(memory.get_directives())
    memory.add_directive("Unique directive")
    assert len(memory.get_directives()) == count_after_first


def test_get_directives(memory):
    directives = memory.get_directives()
    assert isinstance(directives, list)
    assert len(directives) > 0  # Default data has directives


# ── Insights ─────────────────────────────────────────────

def test_record_insight(memory):
    memory.record_insight("Test insight", context="test context", category="technical")
    insights = memory.get_recent_insights(n=5)
    assert len(insights) == 1
    assert insights[0]["insight"] == "Test insight"
    assert insights[0]["context"] == "test context"
    assert insights[0]["category"] == "technical"
    assert "ts" in insights[0]


def test_get_recent_insights_with_category_filter(memory):
    memory.record_insight("General insight", category="general")
    memory.record_insight("Tech insight", category="technical")
    memory.record_insight("Business insight", category="business")

    tech = memory.get_recent_insights(n=10, category="technical")
    assert len(tech) == 1
    assert tech[0]["category"] == "technical"

    all_insights = memory.get_recent_insights(n=10)
    assert len(all_insights) == 3


def test_get_recent_insights_limit(memory):
    for i in range(15):
        memory.record_insight(f"Insight {i}")

    recent = memory.get_recent_insights(n=5)
    assert len(recent) == 5
    # Should be the most recent 5
    assert recent[-1]["insight"] == "Insight 14"


# ── Evaluations ──────────────────────────────────────────

def test_record_evaluation(memory):
    memory.record_evaluation(
        action="Deploy service",
        result="Successfully deployed",
        grade="A",
        lesson="Quick deployment works"
    )
    evals = memory.get_recent_evaluations(n=5)
    assert len(evals) == 1
    assert evals[0]["grade"] == "A"
    assert evals[0]["action"] == "Deploy service"


def test_record_evaluation_grade_stats(memory):
    memory.record_evaluation("a1", "r1", "A", "l1")
    memory.record_evaluation("a2", "r2", "B", "l2")
    memory.record_evaluation("a3", "r3", "A", "l3")
    memory.record_evaluation("a4", "r4", "D", "l4")

    stats = memory.get_grade_stats()
    assert stats["A"] == 2
    assert stats["B"] == 1
    assert stats["D"] == 1
    assert stats["total"] == 4


def test_failure_lesson_auto_recording_on_d_grade(memory):
    memory.record_evaluation("bad action", "failed result", "D", "lesson from failure")

    failures = memory._data["knowledge"]["failure_lessons"]
    assert len(failures) == 1
    assert failures[0]["action"] == "bad action"
    assert failures[0]["lesson"] == "lesson from failure"


def test_failure_lesson_auto_recording_on_f_grade(memory):
    memory.record_evaluation("terrible action", "total failure", "F", "never do this")

    failures = memory._data["knowledge"]["failure_lessons"]
    assert len(failures) == 1
    assert failures[0]["lesson"] == "never do this"


def test_no_failure_lesson_on_good_grade(memory):
    memory.record_evaluation("good action", "success", "A", "keep it up")
    memory.record_evaluation("ok action", "ok", "C", "could be better")

    failures = memory._data["knowledge"]["failure_lessons"]
    assert len(failures) == 0


# ── Plans ────────────────────────────────────────────────

def test_set_daily_plan(memory):
    plan = {
        "hours": {
            "09": {"task": "Morning standup", "method": "communicate", "expected": "Alignment"},
            "10": {"task": "Build feature", "method": "build", "expected": "MVP v1"},
        }
    }
    memory.set_daily_plan(plan)

    current = memory.get_current_plan()
    assert "date" in current
    assert "generated_at" in current
    assert len(current["hours"]) == 2
    assert current["hours"]["09"]["task"] == "Morning standup"


def test_get_hour_plan(memory):
    plan = {
        "hours": {
            "14": {"task": "Afternoon work", "method": "build", "expected": "Feature done"},
        }
    }
    memory.set_daily_plan(plan)

    hour_plan = memory.get_hour_plan(14)
    assert hour_plan["task"] == "Afternoon work"

    # Non-existent hour returns empty dict
    empty = memory.get_hour_plan(3)
    assert empty == {}


def test_record_hourly_check(memory):
    memory.record_hourly_check(
        hour=10,
        planned="Build feature",
        actual="Built 80% of feature",
        grade="B",
        gap_analysis="Minor delay"
    )

    checks = memory._data["plans"]["hourly_checks"]
    assert len(checks) == 1
    assert checks[0]["hour"] == 10
    assert checks[0]["grade"] == "B"


def test_get_plan_achievement_rate(memory):
    # Mock _now to return a fixed date
    with patch("core.self_memory._now") as mock_now:
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))
        fixed = datetime(2026, 3, 6, 15, 0, tzinfo=KST)
        mock_now.return_value = fixed

        memory.record_hourly_check(10, "Plan A", "Did A", "A", "on track")
        memory.record_hourly_check(11, "Plan B", "Did B", "B", "close")
        memory.record_hourly_check(12, "Plan C", "Did nothing", "D", "off track")

        rate = memory.get_plan_achievement_rate()
        assert rate["total"] == 3
        assert rate["achieved"] == 2  # A and B count
        assert rate["rate"] == pytest.approx(66.7, abs=0.1)


def test_get_plan_achievement_rate_empty(memory):
    # Patch to ensure no checks match today
    with patch("core.self_memory._now") as mock_now:
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))
        mock_now.return_value = datetime(2099, 1, 1, 0, 0, tzinfo=KST)

        rate = memory.get_plan_achievement_rate()
        assert rate["total"] == 0
        assert rate["achieved"] == 0
        assert rate["rate"] == 0


# ── Action Items ─────────────────────────────────────────

def test_add_action_item(memory):
    memory.add_action_item("Write tests", priority=1, category="dev")
    items = memory.get_pending_actions()
    assert len(items) == 1
    assert items[0]["item"] == "Write tests"
    assert items[0]["priority"] == 1
    assert items[0]["status"] == "pending"


def test_complete_action_item(memory):
    memory.add_action_item("Task to complete", priority=2)
    memory.complete_action_item(0)

    items = memory._data["action_items"]
    assert items[0]["status"] == "completed"
    assert items[0]["completed_at"] != ""

    pending = memory.get_pending_actions()
    assert len(pending) == 0


def test_get_pending_sorted_by_priority(memory):
    memory.add_action_item("Low priority", priority=5)
    memory.add_action_item("High priority", priority=1)
    memory.add_action_item("Medium priority", priority=3)

    pending = memory.get_pending_actions()
    assert len(pending) == 3
    assert pending[0]["priority"] == 1
    assert pending[1]["priority"] == 3
    assert pending[2]["priority"] == 5


def test_get_pending_actions_with_category(memory):
    memory.add_action_item("Dev task", priority=1, category="dev")
    memory.add_action_item("Biz task", priority=2, category="business")

    dev = memory.get_pending_actions(category="dev")
    assert len(dev) == 1
    assert dev[0]["category"] == "dev"


# ── Size limits ──────────────────────────────────────────

def test_save_truncates_insights(memory):
    for i in range(LIMITS["insights"] + 50):
        memory.record_insight(f"Insight {i}")

    insights = memory._data["knowledge"]["insights"]
    assert len(insights) <= LIMITS["insights"]


def test_save_truncates_hourly_checks(memory):
    for i in range(LIMITS["hourly_checks"] + 10):
        memory._data["plans"]["hourly_checks"].append({
            "date": "2026-03-06", "hour": i % 24, "planned": "p",
            "actual": "a", "grade": "B", "gap_analysis": "g",
            "ts": "2026-03-06T00:00:00",
        })
    memory._save()

    checks = memory._data["plans"]["hourly_checks"]
    assert len(checks) <= LIMITS["hourly_checks"]


def test_save_truncates_daily_logs(memory):
    for i in range(LIMITS["daily_logs"] + 5):
        memory._data["daily_logs"].append({
            "date": f"2026-01-{str(i+1).zfill(2)}",
            "summary": "test", "grade": "B",
        })
    memory._save()

    logs = memory._data["daily_logs"]
    assert len(logs) <= LIMITS["daily_logs"]


# ── get_decision_context ─────────────────────────────────

def test_get_decision_context_returns_formatted_string(memory):
    memory.add_directive("Test directive")
    memory.record_insight("Test insight", category="technical")
    memory.add_action_item("Test action", priority=1)

    context = memory.get_decision_context()
    assert isinstance(context, str)
    assert "Test directive" in context
    assert "Test insight" in context
    assert "Test action" in context
    assert "core_mission" not in context or "mission" in context.lower()  # Some form of mission reference


# ── Migration from old flat structure ────────────────────

def test_migration_from_old_flat_structure(tmp_path):
    """Old data format (flat) should be migrated to new structured format."""
    data_dir = str(tmp_path)
    file_path = os.path.join(data_dir, "self_memory.json")
    os.makedirs(data_dir, exist_ok=True)

    old_data = {
        "core_mission": "Old mission",
        "partner_directives": ["old directive 1"],
        "decision_principles": ["old principle 1"],
        "insights": [{"insight": "old insight", "ts": "2026-01-01"}],
        "evaluations": [{"action": "a", "grade": "B", "ts": "2026-01-01"}],
        "failure_lessons": [{"action": "f", "lesson": "l", "ts": "2026-01-01"}],
        "action_items": [{"item": "old action", "status": "pending"}],
    }
    with open(file_path, "w") as f:
        json.dump(old_data, f)

    with patch("core.self_memory.DATA_DIR", data_dir):
        mem = SelfMemory.__new__(SelfMemory)
        mem._file = file_path
        mem._data = mem._load()
        mem._migrate_if_needed()

    # Should have new structure
    assert "identity" in mem._data
    assert "knowledge" in mem._data

    # Old data should be preserved
    assert mem._data["identity"]["core_mission"] == "Old mission"
    assert "old directive 1" in mem._data["identity"]["partner_directives"]
    assert "old principle 1" in mem._data["identity"]["decision_principles"]
    assert len(mem._data["knowledge"]["insights"]) == 1
    assert len(mem._data["knowledge"]["evaluations"]) == 1
    assert len(mem._data["knowledge"]["failure_lessons"]) == 1
    assert len(mem._data["action_items"]) == 1
