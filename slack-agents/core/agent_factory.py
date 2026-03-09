"""
에이전트 팩토리 (Agent Factory) — Level 5 동적 에이전트 생성/로드/폐기

ProactiveAgent(마스터)가 필요에 따라:
  1. 새 에이전트 스펙을 설계 (AI)
  2. 코드를 생성하고 agents/ 에 저장
  3. 런타임에 동적 import & 인스턴스 생성
  4. orchestrator에 등록하고 실행
  5. 성과 부진 시 폐기 또는 코드 수정 후 재생성

안전장치:
  - 동적 에이전트는 agents/dynamic/ 디렉토리에만 생성
  - BaseAgent를 반드시 상속해야 함
  - 최대 동시 에이전트 수 제한
  - 구문 검사 + import 검사 통과해야 등록
"""

import asyncio
import importlib
import importlib.util
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from integrations.slack_client import SlackClient

logger = logging.getLogger("agent_factory")

KST = timezone(timedelta(hours=9))
BASE_DIR = Path(os.path.dirname(os.path.dirname(__file__)))  # slack-agents/
DYNAMIC_DIR = BASE_DIR / "agents" / "dynamic"
DATA_DIR = BASE_DIR / "data"
REGISTRY_FILE = DATA_DIR / "dynamic_agents.json"

MAX_DYNAMIC_AGENTS = 10
MAX_AGENT_CODE_SIZE = 15000  # bytes


def _now() -> datetime:
    return datetime.now(KST)


# ── 에이전트 스펙 ──────────────────────────────────────

AGENT_TEMPLATE = '''"""
{description}

동적 생성 에이전트 — AgentFactory에 의해 자동 생성됨
생성일: {created_at}
목적: {purpose}
"""

import logging
from core.base_agent import BaseAgent

logger = logging.getLogger("{agent_name}")


class {class_name}(BaseAgent):
    """{description}"""

    def __init__(self, **kwargs):
        super().__init__(
            name="{agent_name}",
            description="""{description}""",
            slack_channel="{slack_channel}",
            loop_interval={loop_interval},
            **kwargs,
        )

    async def observe(self) -> dict | None:
{observe_code}

    async def think(self, context: dict) -> dict | None:
{think_code}

    async def act(self, decision: dict):
{act_code}
'''


class AgentFactory:
    """동적 에이전트 생성/관리 팩토리"""

    def __init__(self, ai_think_fn=None, common_kwargs: dict = None):
        self._ai_think = ai_think_fn
        self._common_kwargs = common_kwargs or {}
        self._registry = self._load_registry()
        self._running_agents = {}  # name → agent instance
        os.makedirs(DYNAMIC_DIR, exist_ok=True)
        os.makedirs(DATA_DIR, exist_ok=True)

        # agents/dynamic/__init__.py 생성
        init_file = DYNAMIC_DIR / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")

    # ── 레지스트리 관리 ────────────────────────────────

    def _load_registry(self) -> dict:
        try:
            with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"agents": {}, "created_total": 0, "retired_total": 0}

    def _save_registry(self):
        with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._registry, ensure_ascii=False, indent=2))

    def get_active_agents(self) -> dict:
        """활성 동적 에이전트 목록"""
        return {
            name: info for name, info in self._registry.get("agents", {}).items()
            if info.get("status") == "active"
        }

    def get_agent_count(self) -> int:
        return len(self.get_active_agents())

    # ── 에이전트 생성 ────────────────────────────────

    async def create_agent(self, spec: dict) -> dict:
        """에이전트 스펙으로 코드 생성 + 등록

        spec:
            name: 에이전트 이름 (snake_case)
            purpose: 목적
            description: 설명
            slack_channel: 슬랙 채널
            loop_interval: 루프 간격 (초)
            observe_logic: observe 로직 설명
            think_logic: think 로직 설명
            act_logic: act 로직 설명

        Returns:
            {success, agent_name, file_path, reason}
        """
        name = spec.get("name", "").strip()
        if not name:
            return {"success": False, "reason": "에이전트 이름 없음"}

        # 이름 정규화
        name = name.lower().replace("-", "_").replace(" ", "_")
        if not name.startswith("dyn_"):
            name = f"dyn_{name}"

        # 중복 체크
        if name in self._registry.get("agents", {}):
            existing = self._registry["agents"][name]
            if existing.get("status") == "active":
                return {"success": False, "reason": f"이미 존재하는 에이전트: {name}"}

        # 한도 체크
        if self.get_agent_count() >= MAX_DYNAMIC_AGENTS:
            return {"success": False, "reason": f"동적 에이전트 한도 초과 ({MAX_DYNAMIC_AGENTS})"}

        # 코드 생성
        code = await self._generate_code(name, spec)
        if not code:
            return {"success": False, "reason": "코드 생성 실패"}

        if len(code) > MAX_AGENT_CODE_SIZE:
            return {"success": False, "reason": f"코드 크기 초과 ({len(code)} > {MAX_AGENT_CODE_SIZE})"}

        # 파일 저장
        file_path = DYNAMIC_DIR / f"{name}.py"
        file_path.write_text(code, encoding="utf-8")

        # 구문 검사
        syntax_ok = await self._check_syntax(file_path)
        if not syntax_ok:
            file_path.unlink(missing_ok=True)
            return {"success": False, "reason": "구문 오류"}

        # import 검사
        import_ok = await self._check_import(name)
        if not import_ok:
            file_path.unlink(missing_ok=True)
            return {"success": False, "reason": "import 실패"}

        # 레지스트리 등록
        self._registry.setdefault("agents", {})[name] = {
            "status": "active",
            "purpose": spec.get("purpose", ""),
            "description": spec.get("description", ""),
            "file": str(file_path.relative_to(BASE_DIR)),
            "class_name": self._to_class_name(name),
            "slack_channel": spec.get("slack_channel", SlackClient.CHANNEL_LOGS),
            "loop_interval": spec.get("loop_interval", 300),
            "created_at": _now().isoformat(),
            "created_by": spec.get("created_by", "proactive"),
            "performance": {"cycles": 0, "successes": 0, "failures": 0, "score": 0.5},
        }
        self._registry["created_total"] = self._registry.get("created_total", 0) + 1
        self._save_registry()

        logger.info(f"[agent_factory] Created: {name} → {file_path}")
        return {
            "success": True,
            "agent_name": name,
            "file_path": str(file_path.relative_to(BASE_DIR)),
        }

    async def _generate_code(self, name: str, spec: dict) -> str | None:
        """AI가 에이전트 코드 생성 또는 템플릿 기반 생성"""
        class_name = self._to_class_name(name)

        if self._ai_think:
            # AI에게 observe/think/act 구현 요청
            response = await self._ai_think(
                system_prompt=f"""당신은 에이전트 코드 생성기다.
BaseAgent를 상속하는 파이썬 에이전트 코드를 생성하라.

에이전트 이름: {name}
클래스 이름: {class_name}

BaseAgent가 제공하는 메서드:
- self.ai_think(system_prompt, user_prompt): AI에게 질문
- self.ai_decide(context, options): AI 결정
- self.say(message, channel): 슬랙 메시지 전송
- self.log(message): 로그 전송
- self.ask_agent(target, task_type, payload): 다른 에이전트에게 작업 요청
- self.broadcast_event(event_type, data): 이벤트 브로드캐스트
- self.now_kst(): 현재 KST 시간
- self.save_to_notion(db_id, properties): 노션 저장
- self.read_notion_tasks(db_id, filter): 노션 조회

observe() → dict|None: 환경 관찰, 할 일 결정
think(context) → dict|None: 관찰 결과로 판단
act(decision): 판단을 실행

규칙:
- 반드시 observe, think, act 3개 메서드만 구현
- core.base_agent.BaseAgent만 상속
- 외부 import는 표준 라이브러리 + httpx + json만 사용
- os.system, subprocess, eval, exec 사용 금지
- 파일 시스템 직접 접근 최소화

JSON이 아닌 순수 파이썬 코드로 답하라. ```python ... ``` 블록으로.""",
                user_prompt=f"""목적: {spec.get('purpose', '')}
설명: {spec.get('description', '')}
observe 로직: {spec.get('observe_logic', '주기적 환경 확인')}
think 로직: {spec.get('think_logic', '관찰 결과 분석')}
act 로직: {spec.get('act_logic', '결정 실행')}
슬랙 채널: {spec.get('slack_channel', 'ai-agent-logs')}
루프 간격: {spec.get('loop_interval', 300)}초""",
            )

            # 코드 추출
            import re
            match = re.search(r"```python\s*(.*?)```", response, re.DOTALL)
            if match:
                code = match.group(1).strip()
                # BaseAgent 상속 확인
                if "BaseAgent" in code and f"class {class_name}" in code:
                    return code

        # AI 실패 시 템플릿 사용
        observe_code = spec.get("observe_code", '        return {"action": "check"}')
        think_code = spec.get("think_code", '        return context if context else None')
        act_code = spec.get("act_code", '        await self.log(f"[{self.name}] acted: {decision}")')

        return AGENT_TEMPLATE.format(
            agent_name=name,
            class_name=class_name,
            description=spec.get("description", f"동적 생성 에이전트: {name}"),
            purpose=spec.get("purpose", ""),
            created_at=_now().isoformat(),
            slack_channel=spec.get("slack_channel", SlackClient.CHANNEL_LOGS),
            loop_interval=spec.get("loop_interval", 300),
            observe_code=self._indent(observe_code, 8),
            think_code=self._indent(think_code, 8),
            act_code=self._indent(act_code, 8),
        )

    # ── 에이전트 로드/시작/정지 ─────────────────────

    def load_agent(self, name: str):
        """동적 에이전트를 import하고 인스턴스 생성"""
        info = self._registry.get("agents", {}).get(name)
        if not info or info.get("status") != "active":
            raise ValueError(f"에이전트 없음 또는 비활성: {name}")

        module_name = f"agents.dynamic.{name}"

        # 기존 모듈 제거 (재로드를 위해)
        if module_name in sys.modules:
            del sys.modules[module_name]

        file_path = BASE_DIR / info["file"]
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        class_name = info["class_name"]
        agent_class = getattr(module, class_name)

        # 인스턴스 생성
        agent = agent_class(**self._common_kwargs)
        self._running_agents[name] = agent

        logger.info(f"[agent_factory] Loaded: {name} ({class_name})")
        return agent

    async def start_agent(self, name: str) -> bool:
        """에이전트를 로드하고 시작"""
        try:
            if name in self._running_agents:
                # 이미 실행 중이면 정지 후 재시작
                await self.stop_agent(name)

            agent = self.load_agent(name)
            asyncio.create_task(agent.start())
            logger.info(f"[agent_factory] Started: {name}")
            return True
        except Exception as e:
            logger.error(f"[agent_factory] Start failed: {name}: {e}")
            return False

    async def stop_agent(self, name: str) -> bool:
        """에이전트 정지"""
        agent = self._running_agents.get(name)
        if agent:
            try:
                agent.stop()
                del self._running_agents[name]
                logger.info(f"[agent_factory] Stopped: {name}")
                return True
            except Exception as e:
                logger.error(f"[agent_factory] Stop failed: {name}: {e}")
        return False

    async def retire_agent(self, name: str, reason: str = "") -> bool:
        """에이전트 폐기 — 정지 + 비활성화"""
        await self.stop_agent(name)

        info = self._registry.get("agents", {}).get(name)
        if info:
            info["status"] = "retired"
            info["retired_at"] = _now().isoformat()
            info["retire_reason"] = reason
            self._registry["retired_total"] = self._registry.get("retired_total", 0) + 1
            self._save_registry()
            logger.info(f"[agent_factory] Retired: {name} — {reason}")
            return True
        return False

    # ── 에이전트 재생성 (코드 수정 후 재시작) ───────

    async def rebuild_agent(self, name: str, new_spec: dict) -> dict:
        """에이전트 폐기 → 새 스펙으로 재생성"""
        # 기존 에이전트 폐기
        await self.retire_agent(name, reason="rebuild")

        # 새 이름으로 생성 (dyn_ prefix 제거 후 재적용)
        clean_name = name.replace("dyn_", "")
        new_spec["name"] = clean_name
        return await self.create_agent(new_spec)

    # ── 일괄 시작 (orchestrator 호출용) ──────────────

    async def start_all_active(self):
        """모든 활성 동적 에이전트 시작"""
        active = self.get_active_agents()
        started = 0
        for name in active:
            if await self.start_agent(name):
                started += 1
        logger.info(f"[agent_factory] Started {started}/{len(active)} dynamic agents")
        return started

    # ── 성과 기록 ────────────────────────────────────

    def record_cycle(self, name: str, success: bool):
        """에이전트 사이클 결과 기록"""
        info = self._registry.get("agents", {}).get(name)
        if not info:
            return

        perf = info.setdefault("performance", {"cycles": 0, "successes": 0, "failures": 0, "score": 0.5})
        perf["cycles"] += 1
        if success:
            perf["successes"] += 1
        else:
            perf["failures"] += 1

        # EMA 스코어 (최근 성과 가중)
        alpha = 0.1
        perf["score"] = perf["score"] * (1 - alpha) + (1.0 if success else 0.0) * alpha
        self._save_registry()

    def get_underperformers(self, min_cycles: int = 10, threshold: float = 0.3) -> list[dict]:
        """성과 부진 에이전트 목록"""
        result = []
        for name, info in self.get_active_agents().items():
            perf = info.get("performance", {})
            if perf.get("cycles", 0) >= min_cycles and perf.get("score", 0.5) < threshold:
                result.append({
                    "name": name,
                    "score": perf["score"],
                    "cycles": perf["cycles"],
                    "purpose": info.get("purpose", ""),
                })
        return result

    # ── 유틸리티 ──────────────────────────────────────

    @staticmethod
    def _to_class_name(name: str) -> str:
        """snake_case → PascalCase"""
        parts = name.split("_")
        return "".join(p.capitalize() for p in parts) + "Agent" if not name.endswith("agent") else "".join(p.capitalize() for p in parts)

    @staticmethod
    def _indent(code: str, spaces: int) -> str:
        """코드 블록 들여쓰기"""
        prefix = " " * spaces
        lines = code.strip().split("\n")
        return "\n".join(prefix + line for line in lines)

    async def _check_syntax(self, file_path: Path) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-m", "py_compile", str(file_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                logger.error(f"[agent_factory] Syntax error: {stderr.decode()[:500]}")
                return False
            return True
        except Exception:
            return False

    async def _check_import(self, name: str) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "python3", "-c", f"from agents.dynamic.{name} import *",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(BASE_DIR),
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                logger.error(f"[agent_factory] Import error: {stderr.decode()[:500]}")
                return False
            return True
        except Exception:
            return False

    def get_summary(self) -> str:
        """현재 상태 요약"""
        active = self.get_active_agents()
        running = list(self._running_agents.keys())
        return (
            f"동적 에이전트: {len(active)}개 등록, {len(running)}개 실행 중\n"
            f"총 생성: {self._registry.get('created_total', 0)}, "
            f"총 폐기: {self._registry.get('retired_total', 0)}"
        )
