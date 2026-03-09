"""
Tests for core/agent_factory.py — 동적 에이전트 생성/폐기/재생성 테스트
"""

import json
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def tmp_dirs():
    """테스트용 임시 디렉토리 (BASE_DIR, DATA_DIR, DYNAMIC_DIR)"""
    with tempfile.TemporaryDirectory() as base:
        dynamic_dir = os.path.join(base, "agents", "dynamic")
        data_dir = os.path.join(base, "data")
        os.makedirs(dynamic_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        # __init__.py 생성
        with open(os.path.join(dynamic_dir, "__init__.py"), "w") as f:
            f.write("")
        yield base, data_dir, dynamic_dir


@pytest.fixture
def factory(tmp_dirs):
    """테스트용 AgentFactory"""
    base, data_dir, dynamic_dir = tmp_dirs
    from pathlib import Path

    with patch("core.agent_factory.BASE_DIR", Path(base)), \
         patch("core.agent_factory.DYNAMIC_DIR", Path(dynamic_dir)), \
         patch("core.agent_factory.DATA_DIR", Path(data_dir)), \
         patch("core.agent_factory.REGISTRY_FILE", Path(data_dir) / "dynamic_agents.json"):
        from core.agent_factory import AgentFactory
        f = AgentFactory(ai_think_fn=None, common_kwargs={})
    return f


# ── 레지스트리 테스트 ──────────────────────────────

def test_initial_registry_empty(factory):
    assert factory.get_agent_count() == 0
    assert factory.get_active_agents() == {}


def test_registry_persists(factory, tmp_dirs):
    """레지스트리에 에이전트 등록 후 저장/로드 확인"""
    factory._registry["agents"]["dyn_test"] = {
        "status": "active",
        "purpose": "테스트",
        "performance": {"cycles": 0, "successes": 0, "failures": 0, "score": 0.5},
    }
    factory._save_registry()

    loaded = factory._load_registry()
    assert "dyn_test" in loaded["agents"]
    assert loaded["agents"]["dyn_test"]["status"] == "active"


# ── 에이전트 생성 테스트 ──────────────────────────

@pytest.mark.asyncio
async def test_create_agent_with_template(factory, tmp_dirs):
    """템플릿 기반 에이전트 생성 테스트 (AI 없이)"""
    base, data_dir, dynamic_dir = tmp_dirs
    from pathlib import Path

    with patch("core.agent_factory.BASE_DIR", Path(base)), \
         patch("core.agent_factory.DYNAMIC_DIR", Path(dynamic_dir)), \
         patch("core.agent_factory.DATA_DIR", Path(data_dir)), \
         patch("core.agent_factory.REGISTRY_FILE", Path(data_dir) / "dynamic_agents.json"):

        # 구문/import 체크 우회 (실제 파일이 import될 수 없으므로)
        factory._check_syntax = AsyncMock(return_value=True)
        factory._check_import = AsyncMock(return_value=True)

        result = await factory.create_agent({
            "name": "test_monitor",
            "purpose": "시스템 모니터링 테스트",
            "description": "테스트용 모니터 에이전트",
            "slack_channel": "test",
            "loop_interval": 60,
        })

    assert result["success"] is True
    assert result["agent_name"] == "dyn_test_monitor"
    assert factory.get_agent_count() == 1

    # 파일이 생성되었는지 확인
    agent_file = os.path.join(dynamic_dir, "dyn_test_monitor.py")
    assert os.path.exists(agent_file)
    code = open(agent_file).read()
    assert "BaseAgent" in code
    assert "DynTestMonitorAgent" in code or "DynTestMonitor" in code


@pytest.mark.asyncio
async def test_create_duplicate_rejected(factory, tmp_dirs):
    """중복 에이전트 이름 거부"""
    base, data_dir, dynamic_dir = tmp_dirs
    from pathlib import Path

    with patch("core.agent_factory.BASE_DIR", Path(base)), \
         patch("core.agent_factory.DYNAMIC_DIR", Path(dynamic_dir)), \
         patch("core.agent_factory.DATA_DIR", Path(data_dir)), \
         patch("core.agent_factory.REGISTRY_FILE", Path(data_dir) / "dynamic_agents.json"):

        factory._check_syntax = AsyncMock(return_value=True)
        factory._check_import = AsyncMock(return_value=True)

        await factory.create_agent({"name": "dup_test", "purpose": "first"})
        result = await factory.create_agent({"name": "dup_test", "purpose": "second"})

    assert result["success"] is False
    assert "이미 존재" in result["reason"]


@pytest.mark.asyncio
async def test_create_exceeds_limit(factory, tmp_dirs):
    """최대 한도 초과 시 거부"""
    base, data_dir, dynamic_dir = tmp_dirs
    from pathlib import Path

    with patch("core.agent_factory.BASE_DIR", Path(base)), \
         patch("core.agent_factory.DYNAMIC_DIR", Path(dynamic_dir)), \
         patch("core.agent_factory.DATA_DIR", Path(data_dir)), \
         patch("core.agent_factory.REGISTRY_FILE", Path(data_dir) / "dynamic_agents.json"), \
         patch("core.agent_factory.MAX_DYNAMIC_AGENTS", 1):

        factory._check_syntax = AsyncMock(return_value=True)
        factory._check_import = AsyncMock(return_value=True)

        await factory.create_agent({"name": "first", "purpose": "1"})
        result = await factory.create_agent({"name": "second", "purpose": "2"})

    assert result["success"] is False
    assert "한도" in result["reason"]


# ── 폐기 테스트 ─────────────────────────────────

@pytest.mark.asyncio
async def test_retire_agent(factory, tmp_dirs):
    """에이전트 폐기 테스트"""
    base, data_dir, dynamic_dir = tmp_dirs
    from pathlib import Path

    with patch("core.agent_factory.BASE_DIR", Path(base)), \
         patch("core.agent_factory.DYNAMIC_DIR", Path(dynamic_dir)), \
         patch("core.agent_factory.DATA_DIR", Path(data_dir)), \
         patch("core.agent_factory.REGISTRY_FILE", Path(data_dir) / "dynamic_agents.json"):

        factory._check_syntax = AsyncMock(return_value=True)
        factory._check_import = AsyncMock(return_value=True)

        await factory.create_agent({"name": "retiring", "purpose": "곧 폐기"})
        assert factory.get_agent_count() == 1

        retired = await factory.retire_agent("dyn_retiring", reason="성과 부진")
        assert retired is True
        assert factory.get_agent_count() == 0

        info = factory._registry["agents"]["dyn_retiring"]
        assert info["status"] == "retired"
        assert info["retire_reason"] == "성과 부진"
        assert factory._registry["retired_total"] == 1


# ── 성과 기록 테스트 ─────────────────────────────

def test_record_cycle_updates_score(factory):
    """사이클 기록이 EMA 스코어를 업데이트하는지 확인"""
    factory._registry["agents"] = {
        "dyn_test": {
            "status": "active",
            "performance": {"cycles": 0, "successes": 0, "failures": 0, "score": 0.5},
        }
    }

    # 성공 10회
    for _ in range(10):
        factory.record_cycle("dyn_test", success=True)

    perf = factory._registry["agents"]["dyn_test"]["performance"]
    assert perf["cycles"] == 10
    assert perf["successes"] == 10
    assert perf["score"] > 0.5  # EMA가 올라감

    # 실패 10회
    for _ in range(10):
        factory.record_cycle("dyn_test", success=False)

    perf = factory._registry["agents"]["dyn_test"]["performance"]
    assert perf["failures"] == 10
    assert perf["score"] < 0.8  # 실패 반영되어 내려감


def test_get_underperformers(factory):
    """부진 에이전트 감지"""
    factory._registry["agents"] = {
        "dyn_bad": {
            "status": "active",
            "purpose": "부진",
            "performance": {"cycles": 20, "successes": 3, "failures": 17, "score": 0.1},
        },
        "dyn_ok": {
            "status": "active",
            "purpose": "보통",
            "performance": {"cycles": 20, "successes": 15, "failures": 5, "score": 0.7},
        },
    }

    result = factory.get_underperformers(min_cycles=10, threshold=0.3)
    assert len(result) == 1
    assert result[0]["name"] == "dyn_bad"


# ── 유틸리티 테스트 ──────────────────────────────

def test_to_class_name(factory):
    assert factory._to_class_name("dyn_market_watcher") == "DynMarketWatcherAgent"
    assert factory._to_class_name("dyn_test_agent") == "DynTestAgent"  # agent로 끝나면 Agent 안 붙임


def test_summary(factory):
    summary = factory.get_summary()
    assert "동적 에이전트" in summary
    assert "총 생성" in summary
