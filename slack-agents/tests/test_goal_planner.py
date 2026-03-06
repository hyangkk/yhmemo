"""
Tests for core/goal_planner.py
"""

import json
import os
from unittest.mock import patch

import pytest

from core.goal_planner import (
    GoalPlanner, Goal, PlanStep,
    GoalStatus, PlanStepStatus,
)


# ── Fixture: GoalPlanner using tmp_path ──────────────────

@pytest.fixture
def planner(tmp_path):
    """Create a GoalPlanner that uses a temporary directory."""
    data_dir = str(tmp_path)
    goals_file = os.path.join(data_dir, "goals.json")
    with patch("core.goal_planner.DATA_DIR", data_dir):
        p = GoalPlanner.__new__(GoalPlanner)
        p._goals_file = goals_file
        p._goals = []
        p._ai_think = None
        os.makedirs(data_dir, exist_ok=True)
    return p


# ── add_goal ─────────────────────────────────────────────

def test_add_goal_creates_correct_fields(planner):
    goal = planner.add_goal(
        title="Launch MVP",
        description="Build and launch the MVP",
        priority=1,
        success_criteria="Users can sign up",
        deadline="2026-03-08",
    )

    assert goal.title == "Launch MVP"
    assert goal.description == "Build and launch the MVP"
    assert goal.priority == 1
    assert goal.status == GoalStatus.ACTIVE
    assert goal.success_criteria == "Users can sign up"
    assert goal.deadline == "2026-03-08"
    assert goal.id.startswith("goal_")
    assert goal.created_at != ""
    assert goal.updated_at != ""
    assert goal.replan_count == 0
    assert goal.plan == []


def test_add_goal_persists(planner):
    planner.add_goal("Test Goal", "desc", priority=2)
    assert os.path.exists(planner._goals_file)
    with open(planner._goals_file) as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["title"] == "Test Goal"


# ── get_active_goals sorted by priority ──────────────────

def test_get_active_goals_sorted_by_priority(planner):
    planner.add_goal("Low", "desc", priority=5)
    planner.add_goal("High", "desc", priority=1)
    planner.add_goal("Medium", "desc", priority=3)

    active = planner.get_active_goals()
    assert len(active) == 3
    assert active[0].priority == 1
    assert active[0].title == "High"
    assert active[1].priority == 3
    assert active[2].priority == 5


def test_get_active_goals_excludes_completed(planner):
    g1 = planner.add_goal("Active", "desc", priority=1)
    g2 = planner.add_goal("Done", "desc", priority=2)
    planner.complete_goal(g2.id, "finished")

    active = planner.get_active_goals()
    assert len(active) == 1
    assert active[0].title == "Active"


# ── complete_goal / fail_goal ────────────────────────────

def test_complete_goal(planner):
    goal = planner.add_goal("Goal to complete", "desc", priority=1)
    planner.complete_goal(goal.id, "All done")

    updated = planner.get_goal(goal.id)
    assert updated.status == GoalStatus.COMPLETED
    assert updated.updated_at != ""
    assert len(updated.feedback_history) == 1
    assert updated.feedback_history[0]["type"] == "completed"
    assert updated.feedback_history[0]["result"] == "All done"


def test_fail_goal(planner):
    goal = planner.add_goal("Goal to fail", "desc", priority=2)
    planner.fail_goal(goal.id, "Not feasible")

    updated = planner.get_goal(goal.id)
    assert updated.status == GoalStatus.FAILED
    assert len(updated.feedback_history) == 1
    assert updated.feedback_history[0]["type"] == "failed"
    assert updated.feedback_history[0]["reason"] == "Not feasible"


def test_complete_nonexistent_goal(planner):
    """Completing a nonexistent goal should not raise."""
    planner.complete_goal("nonexistent_id", "result")  # Should not raise


# ── PlanStep status transitions ──────────────────────────

def test_plan_step_default_status():
    step = PlanStep(description="Research", method="research")
    assert step.status == PlanStepStatus.PENDING


def test_plan_step_to_dict_from_dict():
    step = PlanStep(description="Build API", method="build")
    step.status = PlanStepStatus.IN_PROGRESS
    step.started_at = "2026-03-06T10:00:00"

    d = step.to_dict()
    assert d["status"] == "in_progress"
    assert d["description"] == "Build API"

    restored = PlanStep.from_dict(d)
    assert restored.status == PlanStepStatus.IN_PROGRESS
    assert restored.description == "Build API"


def test_start_step(planner):
    goal = planner.add_goal("G", "d", priority=1)
    step = PlanStep(description="Step 1", method="build")
    goal.plan = [step]
    planner._save_goals()

    planner.start_step(goal, step)
    assert step.status == PlanStepStatus.IN_PROGRESS
    assert step.started_at != ""


def test_complete_step(planner):
    goal = planner.add_goal("G", "d", priority=1)
    step = PlanStep(description="Step 1", method="build")
    goal.plan = [step]

    planner.complete_step(goal, step, "Done successfully")
    assert step.status == PlanStepStatus.COMPLETED
    assert step.result == "Done successfully"
    assert step.completed_at != ""


def test_fail_step(planner):
    goal = planner.add_goal("G", "d", priority=1)
    step = PlanStep(description="Step 1", method="build")
    goal.plan = [step]

    planner.fail_step(goal, step, "API limit exceeded")
    assert step.status == PlanStepStatus.FAILED
    assert "FAILED:" in step.result
    assert "API limit exceeded" in step.result


# ── Goal.next_pending_step ───────────────────────────────

def test_next_pending_step():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    s1 = PlanStep(description="S1", method="research")
    s1.status = PlanStepStatus.COMPLETED
    s2 = PlanStep(description="S2", method="build")
    s3 = PlanStep(description="S3", method="measure")
    goal.plan = [s1, s2, s3]

    nxt = goal.next_pending_step()
    assert nxt is s2
    assert goal.current_step_index == 1


def test_next_pending_step_all_done():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    s1 = PlanStep(description="S1", method="research")
    s1.status = PlanStepStatus.COMPLETED
    goal.plan = [s1]

    nxt = goal.next_pending_step()
    assert nxt is None


def test_next_pending_step_empty_plan():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    nxt = goal.next_pending_step()
    assert nxt is None


# ── Goal.progress_pct ────────────────────────────────────

def test_progress_pct_no_plan():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    assert goal.progress_pct() == 0.0


def test_progress_pct_partial():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    s1 = PlanStep(description="S1", method="r")
    s1.status = PlanStepStatus.COMPLETED
    s2 = PlanStep(description="S2", method="b")
    s3 = PlanStep(description="S3", method="m")
    s3.status = PlanStepStatus.SKIPPED
    goal.plan = [s1, s2, s3]

    # 2 out of 3 done (completed + skipped)
    assert goal.progress_pct() == pytest.approx(66.7, abs=0.1)


def test_progress_pct_all_complete():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    s1 = PlanStep(description="S1", method="r")
    s1.status = PlanStepStatus.COMPLETED
    goal.plan = [s1]
    assert goal.progress_pct() == 100.0


# ── Goal.is_done ─────────────────────────────────────────

def test_is_done_all_completed():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    s1 = PlanStep(description="S1", method="r")
    s1.status = PlanStepStatus.COMPLETED
    s2 = PlanStep(description="S2", method="b")
    s2.status = PlanStepStatus.SKIPPED
    goal.plan = [s1, s2]
    assert goal.is_done() is True


def test_is_done_with_pending():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    s1 = PlanStep(description="S1", method="r")
    s1.status = PlanStepStatus.COMPLETED
    s2 = PlanStep(description="S2", method="b")
    goal.plan = [s1, s2]
    assert goal.is_done() is False


def test_is_done_empty_plan():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    assert goal.is_done() is False


def test_is_done_all_failed():
    goal = Goal(id="g1", title="T", description="D", priority=1)
    s1 = PlanStep(description="S1", method="r")
    s1.status = PlanStepStatus.FAILED
    goal.plan = [s1]
    assert goal.is_done() is True


# ── pick_next_action ─────────────────────────────────────

def test_pick_next_action_returns_highest_priority(planner):
    g1 = planner.add_goal("Low", "d", priority=5)
    g2 = planner.add_goal("High", "d", priority=1)

    s1 = PlanStep(description="G1 step", method="research")
    g1.plan = [s1]
    s2 = PlanStep(description="G2 step", method="build")
    g2.plan = [s2]
    planner._save_goals()

    result = planner.pick_next_action()
    assert result is not None
    goal, step = result
    assert goal.title == "High"
    assert step.description == "G2 step"


def test_pick_next_action_returns_none_when_no_goals(planner):
    result = planner.pick_next_action()
    assert result is None


def test_pick_next_action_returns_goal_with_none_step_when_done(planner):
    g = planner.add_goal("Done goal", "d", priority=1)
    s = PlanStep(description="S", method="r")
    s.status = PlanStepStatus.COMPLETED
    g.plan = [s]
    planner._save_goals()

    result = planner.pick_next_action()
    assert result is not None
    goal, step = result
    assert goal.title == "Done goal"
    assert step is None  # None step means evaluation needed


def test_pick_next_action_skips_completed_goals(planner):
    g1 = planner.add_goal("Completed", "d", priority=1)
    planner.complete_goal(g1.id, "done")
    g2 = planner.add_goal("Active", "d", priority=2)
    s = PlanStep(description="S", method="build")
    g2.plan = [s]
    planner._save_goals()

    result = planner.pick_next_action()
    assert result is not None
    goal, step = result
    assert goal.title == "Active"


# ── Goal serialization round-trip ────────────────────────

def test_goal_to_dict_from_dict():
    goal = Goal(
        id="goal_123",
        title="Test",
        description="Test goal",
        priority=2,
        status=GoalStatus.ACTIVE,
        plan=[PlanStep(description="Step 1", method="build")],
        created_at="2026-03-06T10:00:00",
        updated_at="2026-03-06T10:00:00",
        deadline="2026-03-08",
        success_criteria="Criteria met",
    )

    d = goal.to_dict()
    restored = Goal.from_dict(d)

    assert restored.id == "goal_123"
    assert restored.title == "Test"
    assert restored.priority == 2
    assert restored.status == GoalStatus.ACTIVE
    assert len(restored.plan) == 1
    assert restored.plan[0].description == "Step 1"
    assert restored.deadline == "2026-03-08"
