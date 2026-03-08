"""
자기수정 엔진 (Self-Improvement Engine)

Level 4 자율 진화: 실패 패턴 감지 → 코드 분석 → 수정 → 테스트 → 커밋 → 롤백 안전장치

흐름:
  1. 반복 실패/D·F 등급 패턴 감지
  2. 관련 코드 읽기 + 실패 교훈 수집
  3. AI가 코드 수정안 생성 (diff 형태)
  4. 수정 적용 → 테스트 → 통과하면 커밋+푸시
  5. 실패하면 git checkout으로 롤백

안전장치:
  - 수정 불가 파일: orchestrator.py, executor.py, self_improver.py, security.py
  - 프로젝트 디렉토리 밖 수정 불가
  - 테스트 미통과 시 자동 롤백
  - 하루 최대 수정 횟수 제한
  - 모든 수정 이력 기록
"""

import asyncio
import base64
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("self_improver")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
BASE_DIR = Path(os.path.dirname(os.path.dirname(__file__)))  # slack-agents/

# ── 안전장치 설정 ───────────────────────────────────────

# 절대 수정 불가 파일 (자기 자신 + 핵심 인프라)
IMMUTABLE_FILES = {
    "orchestrator.py",
    "core/executor.py",
    "core/self_improver.py",
    "core/security.py",
    "core/message_bus.py",
    "run_forever.sh",
    "watchdog_cron.sh",
    "Dockerfile",
    "fly.toml",
}

# 수정 가능 디렉토리 (화이트리스트)
MUTABLE_DIRS = [
    "agents/",
    "core/goal_planner.py",
    "core/proposal_lifecycle.py",
    "core/self_memory.py",
    "core/tools.py",
    "core/config.py",
    "integrations/",
    "scripts/",
]

MAX_DAILY_IMPROVEMENTS = 5
MAX_FILE_CHANGES_PER_IMPROVEMENT = 3
MAX_CHANGE_SIZE = 5000  # bytes per file change


def _now() -> datetime:
    return datetime.now(KST)


class SelfImprover:
    """에이전트 자기수정 엔진

    실패 패턴을 감지하고, 코드를 분석하고, 수정하고, 테스트하고, 커밋한다.
    """

    def __init__(self, ai_think_fn=None):
        self._ai_think = ai_think_fn
        self._history_file = os.path.join(DATA_DIR, "self_improvements.json")
        self._history = self._load_history()
        os.makedirs(DATA_DIR, exist_ok=True)

    # ── 이력 관리 ──────────────────────────────────────

    def _load_history(self) -> dict:
        try:
            with open(self._history_file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "improvements": [],
                "daily_count": {},
                "total_success": 0,
                "total_rollback": 0,
            }

    def _save_history(self):
        # 최근 200건만 보관
        if len(self._history["improvements"]) > 200:
            self._history["improvements"] = self._history["improvements"][-200:]
        with open(self._history_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._history, ensure_ascii=False, indent=2))

    def get_today_count(self) -> int:
        today = _now().strftime("%Y-%m-%d")
        return self._history.get("daily_count", {}).get(today, 0)

    def can_improve_today(self) -> bool:
        return self.get_today_count() < MAX_DAILY_IMPROVEMENTS

    # ── 실패 패턴 감지 ────────────────────────────────

    def detect_failure_pattern(self, memory) -> dict | None:
        """SelfMemory에서 반복 실패 패턴을 감지한다.

        Returns:
            dict with {pattern, failures, related_files, suggestion} or None
        """
        evaluations = memory.get_recent_evaluations(n=20)
        failure_lessons = memory._data.get("knowledge", {}).get("failure_lessons", [])[-10:]

        if not evaluations:
            return None

        # D/F 등급 연속 3회 이상
        recent_grades = [e.get("grade", "C") for e in evaluations[-10:]]
        consecutive_fails = 0
        for g in reversed(recent_grades):
            if g in ("D", "F"):
                consecutive_fails += 1
            else:
                break

        # 같은 action에서 반복 실패
        action_fails = {}
        for e in evaluations:
            if e.get("grade") in ("D", "F"):
                action = e.get("action", "unknown")
                action_fails[action] = action_fails.get(action, 0) + 1

        repeated_action = None
        for action, count in action_fails.items():
            if count >= 3:
                repeated_action = action
                break

        # 패턴 판단
        if consecutive_fails >= 3:
            return {
                "type": "consecutive_failure",
                "count": consecutive_fails,
                "recent_evaluations": evaluations[-consecutive_fails:],
                "failure_lessons": failure_lessons[-5:],
            }
        elif repeated_action:
            related_evals = [e for e in evaluations if e.get("action") == repeated_action and e.get("grade") in ("D", "F")]
            return {
                "type": "repeated_action_failure",
                "action": repeated_action,
                "count": action_fails[repeated_action],
                "recent_evaluations": related_evals[-5:],
                "failure_lessons": failure_lessons[-5:],
            }

        return None

    # ── 파일 안전성 검증 ──────────────────────────────

    def _is_file_mutable(self, rel_path: str) -> bool:
        """파일이 수정 가능한지 검증"""
        # 절대 수정 불가
        if rel_path in IMMUTABLE_FILES:
            return False

        # .env 파일 차단
        if ".env" in rel_path:
            return False

        # 화이트리스트 디렉토리/파일 확인
        for allowed in MUTABLE_DIRS:
            if rel_path.startswith(allowed) or rel_path == allowed:
                return True

        return False

    def _validate_changes(self, changes: list[dict]) -> tuple[bool, str]:
        """변경 사항 안전성 검증"""
        if len(changes) > MAX_FILE_CHANGES_PER_IMPROVEMENT:
            return False, f"변경 파일 수 초과 (최대 {MAX_FILE_CHANGES_PER_IMPROVEMENT})"

        for change in changes:
            path = change.get("file", "")
            content = change.get("new_content", "")

            if not self._is_file_mutable(path):
                return False, f"수정 불가 파일: {path}"

            if len(content) > MAX_CHANGE_SIZE:
                return False, f"변경 크기 초과: {path} ({len(content)} > {MAX_CHANGE_SIZE})"

            # 위험 패턴 검출
            dangerous = [
                "os.system(", "subprocess.call(",
                "eval(", "exec(",
                "__import__(",
                "rm -rf", "shutil.rmtree",
                "ANTHROPIC_API_KEY", "SLACK_BOT_TOKEN",
                "SUPABASE_SERVICE_ROLE_KEY",
            ]
            for pattern in dangerous:
                # 기존 코드에 있는 건 허용, 새로 추가하는 건 차단
                if pattern in content:
                    # 원본에도 있으면 허용
                    original = change.get("original_content", "")
                    if pattern not in original:
                        return False, f"위험 패턴 감지: {pattern} in {path}"

        return True, ""

    # ── 핵심: 자기수정 실행 ───────────────────────────

    async def improve(self, failure_pattern: dict, memory) -> dict:
        """실패 패턴을 분석하고 코드를 수정한다.

        Returns:
            dict with {success, changes, commit_hash, rollback, reason}
        """
        if not self._ai_think:
            return {"success": False, "reason": "AI 함수 없음"}

        if not self.can_improve_today():
            return {"success": False, "reason": f"오늘 수정 한도 초과 ({MAX_DAILY_IMPROVEMENTS}회)"}

        result = {
            "success": False,
            "changes": [],
            "commit_hash": "",
            "rollback": False,
            "reason": "",
            "timestamp": _now().isoformat(),
            "pattern": failure_pattern.get("type", "unknown"),
        }

        try:
            # 1단계: AI가 어떤 파일을 분석해야 하는지 결정
            files_to_analyze = await self._identify_files(failure_pattern)
            if not files_to_analyze:
                result["reason"] = "분석 대상 파일 없음"
                self._record(result)
                return result

            # 2단계: 파일 내용 읽기
            file_contents = {}
            for f in files_to_analyze[:5]:  # 최대 5개 파일 분석
                full_path = BASE_DIR / f
                if full_path.exists() and full_path.is_file():
                    try:
                        content = full_path.read_text(encoding="utf-8")
                        if len(content) < 20000:
                            file_contents[f] = content
                    except Exception:
                        pass

            if not file_contents:
                result["reason"] = "읽을 수 있는 파일 없음"
                self._record(result)
                return result

            # 3단계: AI가 코드 수정안 생성
            changes = await self._generate_fix(failure_pattern, file_contents, memory)
            if not changes:
                result["reason"] = "수정안 생성 실패"
                self._record(result)
                return result

            # 4단계: 안전성 검증
            ok, reason = self._validate_changes(changes)
            if not ok:
                result["reason"] = f"안전성 검증 실패: {reason}"
                self._record(result)
                return result

            # 5단계: 원본 백업 + 수정 적용
            backups = {}
            for change in changes:
                path = BASE_DIR / change["file"]
                if path.exists():
                    backups[change["file"]] = path.read_text(encoding="utf-8")
                change["original_content"] = backups.get(change["file"], "")

            # 재검증 (원본 포함)
            ok, reason = self._validate_changes(changes)
            if not ok:
                result["reason"] = f"안전성 재검증 실패: {reason}"
                self._record(result)
                return result

            # 파일 수정 적용
            applied_files = []
            try:
                for change in changes:
                    path = BASE_DIR / change["file"]
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(change["new_content"], encoding="utf-8")
                    applied_files.append(change["file"])
                    logger.info(f"[self_improver] Applied: {change['file']}")
            except Exception as e:
                # 적용 실패 → 롤백
                self._rollback(backups)
                result["reason"] = f"파일 적용 실패: {e}"
                result["rollback"] = True
                self._record(result)
                return result

            # 6단계: 구문 검사 (Python syntax check)
            syntax_ok = await self._check_syntax(applied_files)
            if not syntax_ok:
                self._rollback(backups)
                result["reason"] = "구문 오류 — 롤백"
                result["rollback"] = True
                self._record(result)
                return result

            # 7단계: 테스트 실행
            test_ok = await self._run_tests()
            if not test_ok:
                self._rollback(backups)
                result["reason"] = "테스트 실패 — 롤백"
                result["rollback"] = True
                self._record(result)
                return result

            # 8단계: git commit + push
            commit_hash = await self._git_commit(changes, failure_pattern)

            result["success"] = True
            result["changes"] = [{"file": c["file"], "description": c.get("description", "")} for c in changes]
            result["commit_hash"] = commit_hash
            result["reason"] = "자기수정 성공"

        except Exception as e:
            result["reason"] = f"예외: {str(e)[:200]}"
            logger.error(f"[self_improver] Exception: {e}", exc_info=True)

        self._record(result)
        return result

    # ── AI 분석 단계들 ────────────────────────────────

    async def _identify_files(self, pattern: dict) -> list[str]:
        """실패 패턴에서 분석할 파일 목록 결정"""
        evaluations_text = json.dumps(pattern.get("recent_evaluations", []), ensure_ascii=False, default=str)[:2000]
        lessons_text = json.dumps(pattern.get("failure_lessons", []), ensure_ascii=False, default=str)[:1000]

        # 수정 가능한 파일 목록 생성
        mutable_files = []
        for d in MUTABLE_DIRS:
            dir_path = BASE_DIR / d
            if dir_path.is_dir():
                for f in dir_path.rglob("*.py"):
                    rel = str(f.relative_to(BASE_DIR))
                    if self._is_file_mutable(rel):
                        mutable_files.append(rel)
            elif dir_path.is_file() and dir_path.suffix == ".py":
                rel = str(dir_path.relative_to(BASE_DIR))
                if self._is_file_mutable(rel):
                    mutable_files.append(rel)

        response = await self._ai_think(
            system_prompt="""실패 패턴을 분석하고, 어떤 코드 파일을 수정하면 해결될지 판단하라.
JSON으로 답하라: {"files": ["경로1", "경로2"], "reason": "이유"}

수정 가능 파일 목록:
""" + "\n".join(f"- {f}" for f in mutable_files[:30]),
            user_prompt=f"""실패 패턴: {pattern.get('type')}
횟수: {pattern.get('count', 0)}

최근 실패 평가:
{evaluations_text}

실패 교훈:
{lessons_text}""",
        )

        try:
            parsed = json.loads(self._extract_json(response))
            files = parsed.get("files", [])
            # 수정 가능한 파일만 필터
            return [f for f in files if self._is_file_mutable(f)]
        except Exception:
            return []

    async def _generate_fix(self, pattern: dict, file_contents: dict, memory) -> list[dict] | None:
        """AI가 코드 수정안 생성"""
        files_text = ""
        for path, content in file_contents.items():
            files_text += f"\n{'='*60}\n## {path}\n{'='*60}\n{content}\n"

        evaluations_text = json.dumps(pattern.get("recent_evaluations", []), ensure_ascii=False, default=str)[:2000]
        lessons_text = json.dumps(pattern.get("failure_lessons", []), ensure_ascii=False, default=str)[:1000]

        # 메모리에서 판단 원칙 가져오기
        principles = memory.get_principles() if memory else []
        principles_text = "\n".join(f"- {p}" for p in principles[-5:])

        response = await self._ai_think(
            system_prompt=f"""당신은 자율 에이전트의 자기수정 엔진이다.
실패 패턴을 분석하고, 코드를 수정해서 문제를 해결하라.

규칙:
- 최소한의 수정만 한다 (불필요한 리팩토링 금지)
- 기존 동작을 깨뜨리지 않는다
- 하나의 문제만 고친다
- 수정할 파일은 최대 {MAX_FILE_CHANGES_PER_IMPROVEMENT}개
- 각 파일의 전체 내용을 new_content에 포함한다

판단 원칙:
{principles_text}

JSON으로 답하라:
{{"changes": [
  {{"file": "상대경로", "description": "무엇을 왜 수정하는지", "new_content": "수정된 전체 파일 내용"}}
]}}""",
            user_prompt=f"""실패 패턴: {pattern.get('type')}
횟수: {pattern.get('count', 0)}

실패 평가:
{evaluations_text}

실패 교훈:
{lessons_text}

현재 코드:
{files_text}""",
        )

        try:
            parsed = json.loads(self._extract_json(response))
            changes = parsed.get("changes", [])
            if not changes:
                return None
            return changes
        except Exception as e:
            logger.error(f"[self_improver] Parse fix failed: {e}")
            return None

    # ── 검증 & 롤백 ──────────────────────────────────

    def _rollback(self, backups: dict):
        """백업으로 파일 복원"""
        for rel_path, content in backups.items():
            try:
                path = BASE_DIR / rel_path
                path.write_text(content, encoding="utf-8")
                logger.info(f"[self_improver] Rolled back: {rel_path}")
            except Exception as e:
                logger.error(f"[self_improver] Rollback failed for {rel_path}: {e}")

    async def _check_syntax(self, files: list[str]) -> bool:
        """Python 구문 검사"""
        for f in files:
            if not f.endswith(".py"):
                continue
            full_path = BASE_DIR / f
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python3", "-m", "py_compile", str(full_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode != 0:
                    logger.error(f"[self_improver] Syntax error in {f}: {stderr.decode()[:500]}")
                    return False
            except Exception as e:
                logger.error(f"[self_improver] Syntax check failed: {e}")
                return False
        return True

    async def _run_tests(self) -> bool:
        """테스트 실행 — 테스트가 없으면 import 검사만"""
        # 테스트 디렉토리 확인
        test_dir = BASE_DIR / "tests"
        if test_dir.exists() and list(test_dir.glob("test_*.py")):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python3", "-m", "pytest", str(test_dir), "-x", "--tb=short", "-q",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(BASE_DIR),
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
                if proc.returncode != 0:
                    logger.error(f"[self_improver] Tests failed: {stdout.decode()[:500]}")
                    return False
                return True
            except asyncio.TimeoutError:
                logger.error("[self_improver] Tests timed out")
                return False
            except Exception:
                pass

        # 테스트가 없으면 핵심 모듈 import 검사
        check_modules = [
            "core.base_agent",
            "core.goal_planner",
            "core.self_memory",
            "core.tools",
        ]
        for mod in check_modules:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python3", "-c", f"import {mod}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(BASE_DIR),
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode != 0:
                    logger.error(f"[self_improver] Import failed: {mod}: {stderr.decode()[:300]}")
                    return False
            except Exception:
                pass

        return True

    async def _git_commit(self, changes: list[dict], pattern: dict) -> str:
        """GitHub API로 수정된 파일을 커밋 (컨테이너에서도 동작)"""
        descriptions = [c.get("description", "") for c in changes]
        commit_msg = f"self-improve: {pattern.get('type', 'fix')} — {descriptions[0][:60]}"

        # GitHub 토큰 가져오기
        gh_token = os.environ.get("GH_TOKEN", "")
        if not gh_token:
            # Supabase secrets_vault에서 시도
            try:
                from supabase import create_client
                sb_url = os.environ.get("SUPABASE_URL", "")
                sb_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
                if sb_url and sb_key:
                    sb = create_client(sb_url, sb_key)
                    result = sb.table("secrets_vault").select("secret_value").eq("secret_name", "GH_TOKEN").execute()
                    if result.data:
                        gh_token = result.data[0]["secret_value"]
            except Exception as e:
                logger.warning(f"[self_improver] Failed to fetch GH_TOKEN: {e}")

        if not gh_token:
            logger.warning("[self_improver] No GH_TOKEN — skipping push (local changes only)")
            return "local-only"

        repo = "hyangkk/yhmemo"
        branch = "main"
        api_base = f"https://api.github.com/repos/{repo}"
        headers = {
            "Authorization": f"token {gh_token}",
            "Accept": "application/vnd.github.v3+json",
        }

        try:
            import aiohttp
            async with aiohttp.ClientSession(headers=headers) as session:
                # 1. 현재 main의 최신 커밋 SHA 가져오기
                async with session.get(f"{api_base}/git/ref/heads/{branch}") as resp:
                    if resp.status != 200:
                        logger.error(f"[self_improver] Failed to get ref: {resp.status}")
                        return "local-only"
                    ref_data = await resp.json()
                    base_sha = ref_data["object"]["sha"]

                # 2. base tree 가져오기
                async with session.get(f"{api_base}/git/commits/{base_sha}") as resp:
                    commit_data = await resp.json()
                    base_tree_sha = commit_data["tree"]["sha"]

                # 3. 새로운 tree 생성 (변경 파일들)
                tree_items = []
                for change in changes:
                    file_path = f"slack-agents/{change['file']}"
                    content = change.get("new_content", "")
                    # blob 생성
                    async with session.post(f"{api_base}/git/blobs", json={
                        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                        "encoding": "base64",
                    }) as resp:
                        blob_data = await resp.json()
                        tree_items.append({
                            "path": file_path,
                            "mode": "100644",
                            "type": "blob",
                            "sha": blob_data["sha"],
                        })

                async with session.post(f"{api_base}/git/trees", json={
                    "base_tree": base_tree_sha,
                    "tree": tree_items,
                }) as resp:
                    tree_data = await resp.json()
                    new_tree_sha = tree_data["sha"]

                # 4. 커밋 생성
                async with session.post(f"{api_base}/git/commits", json={
                    "message": commit_msg,
                    "tree": new_tree_sha,
                    "parents": [base_sha],
                }) as resp:
                    new_commit = await resp.json()
                    new_commit_sha = new_commit["sha"]

                # 5. ref 업데이트
                async with session.patch(f"{api_base}/git/refs/heads/{branch}", json={
                    "sha": new_commit_sha,
                }) as resp:
                    if resp.status == 200:
                        short_sha = new_commit_sha[:7]
                        logger.info(f"[self_improver] Pushed via GitHub API: {short_sha} — {commit_msg}")
                        return short_sha
                    else:
                        logger.error(f"[self_improver] Failed to update ref: {resp.status}")
                        return "local-only"

        except ImportError:
            logger.warning("[self_improver] aiohttp not installed — local changes only")
            return "local-only"
        except Exception as e:
            logger.error(f"[self_improver] GitHub API commit failed: {e}")
            return "local-only"

    # ── 기록 & 유틸리티 ──────────────────────────────

    def _record(self, result: dict):
        """수정 이력 기록"""
        self._history["improvements"].append(result)
        today = _now().strftime("%Y-%m-%d")
        daily = self._history.get("daily_count", {})
        daily[today] = daily.get(today, 0) + (1 if result.get("success") else 0)
        self._history["daily_count"] = daily

        if result.get("success"):
            self._history["total_success"] = self._history.get("total_success", 0) + 1
        if result.get("rollback"):
            self._history["total_rollback"] = self._history.get("total_rollback", 0) + 1

        self._save_history()

    def get_stats(self) -> dict:
        return {
            "total_improvements": len(self._history["improvements"]),
            "total_success": self._history.get("total_success", 0),
            "total_rollback": self._history.get("total_rollback", 0),
            "today_count": self.get_today_count(),
            "daily_limit": MAX_DAILY_IMPROVEMENTS,
        }

    def get_recent_improvements(self, n: int = 5) -> list[dict]:
        return self._history["improvements"][-n:]

    @staticmethod
    def _extract_json(text: str) -> str:
        """텍스트에서 JSON 블록 추출"""
        # ```json ... ``` 패턴
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        # 그냥 { ... } 패턴
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return match.group(0)
        return text
