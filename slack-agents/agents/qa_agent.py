"""
QA 에이전트 - 웹 서비스 배포 후 자동 테스트 및 모니터링

역할:
- 10분마다 웹 서비스 헬스체크 (핵심 엔드포인트 검증)
- GitHub Actions 배포 상태 모니터링
- 배포 실패/서비스 다운 감지 시 즉시 슬랙 알림
- 핵심 API 엔드포인트 동작 검증

자율 행동:
- Observe: 웹 서비스 상태 + 최근 배포 결과 수집
- Think: 이상 여부 판단
- Act: 이상 시 슬랙 알림, 정상 시 침묵
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 검증 대상 엔드포인트
WEB_SERVICE_URL = "https://web-service-ruby.vercel.app"
HEALTH_ENDPOINTS = [
    {"path": "/", "expect_status": 200, "name": "메인 페이지"},
    {"path": "/login", "expect_status": 200, "name": "로그인 페이지"},
    {"path": "/projects", "expect_status": 200, "name": "프로젝트 페이지"},
    {"path": "/api/projects", "expect_status": 401, "name": "프로젝트 API (인증 필요)"},
]

GITHUB_API = "https://api.github.com/repos/hyangkk/yhmemo"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
QA_STATE_FILE = os.path.join(DATA_DIR, "qa_state.json")


class QAAgent(BaseAgent):
    """웹 서비스 자동 QA 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="qa",
            description="웹 서비스 배포 후 자동 테스트 및 모니터링 에이전트",
            slack_channel="C0AJJ469SV8",  # ai-agents-general
            loop_interval=600,  # 10분마다 체크
            **kwargs,
        )
        self._state = self._load_state()
        self._consecutive_failures = 0

    def _load_state(self) -> dict:
        try:
            with open(QA_STATE_FILE, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "last_known_deploy_sha": "",
                "last_deploy_check": "",
                "last_full_test": "",
                "failure_count": 0,
            }

    def _save_state(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(QA_STATE_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._state, ensure_ascii=False, indent=2))

    # ── Observe ──────────────────────────────────────────

    async def observe(self) -> dict | None:
        now = datetime.now(KST)
        context = {
            "timestamp": now.strftime("%Y-%m-%d %H:%M KST"),
            "health_results": [],
            "deploy_status": None,
            "new_deploy": False,
        }

        # 1. 웹 서비스 헬스체크
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for ep in HEALTH_ENDPOINTS:
                url = f"{WEB_SERVICE_URL}{ep['path']}"
                try:
                    resp = await client.get(url)
                    context["health_results"].append({
                        "name": ep["name"],
                        "path": ep["path"],
                        "status": resp.status_code,
                        "expected": ep["expect_status"],
                        "ok": resp.status_code == ep["expect_status"],
                        "latency_ms": int(resp.elapsed.total_seconds() * 1000),
                    })
                except Exception as e:
                    context["health_results"].append({
                        "name": ep["name"],
                        "path": ep["path"],
                        "status": 0,
                        "expected": ep["expect_status"],
                        "ok": False,
                        "error": str(e)[:100],
                    })

        # 2. 최근 배포 상태 확인 (GitHub Actions)
        try:
            gh_token = os.environ.get("GH_TOKEN", "")
            headers = {"Accept": "application/vnd.github+json"}
            if gh_token:
                headers["Authorization"] = f"token {gh_token}"

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{GITHUB_API}/actions/runs?per_page=5",
                    headers=headers,
                )
                if resp.status_code == 200:
                    runs = resp.json().get("workflow_runs", [])
                    # 웹 서비스 배포만 필터
                    web_deploys = [r for r in runs if "Web Service" in r.get("name", "")]
                    if web_deploys:
                        latest = web_deploys[0]
                        context["deploy_status"] = {
                            "name": latest["name"],
                            "status": latest["status"],
                            "conclusion": latest.get("conclusion"),
                            "sha": latest["head_sha"][:7],
                            "created_at": latest["created_at"],
                        }
                        # 새 배포 감지
                        if latest["head_sha"][:7] != self._state.get("last_known_deploy_sha"):
                            context["new_deploy"] = True
        except Exception as e:
            logger.warning(f"[qa] GitHub API 조회 실패: {e}")

        # 3. Studio API 헬스체크 (같은 Fly.io 인스턴스)
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get("http://localhost:8000/health")
                context["studio_health"] = resp.json() if resp.status_code == 200 else {"error": resp.status_code}
        except Exception:
            context["studio_health"] = {"error": "unreachable"}

        return context

    # ── Think ────────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        health = context.get("health_results", [])
        deploy = context.get("deploy_status")

        failures = [h for h in health if not h.get("ok")]
        slow_endpoints = [h for h in health if h.get("ok") and h.get("latency_ms", 0) > 5000]

        action = {
            "type": "report",
            "failures": failures,
            "slow": slow_endpoints,
            "all_ok": len(failures) == 0,
            "deploy": deploy,
            "new_deploy": context.get("new_deploy", False),
            "timestamp": context["timestamp"],
        }

        # 배포 실패 감지
        if deploy and deploy.get("conclusion") == "failure":
            action["deploy_failed"] = True

        # 모든 게 정상이고 새 배포도 아니면 → 침묵
        if action["all_ok"] and not action.get("deploy_failed") and not action["new_deploy"]:
            self._consecutive_failures = 0
            return None

        return action

    # ── Act ──────────────────────────────────────────────

    async def act(self, decision: dict):
        lines = []
        now_str = decision["timestamp"]

        # 새 배포 감지
        if decision.get("new_deploy") and decision.get("deploy"):
            deploy = decision["deploy"]
            sha = deploy["sha"]

            if deploy.get("conclusion") == "success" and decision["all_ok"]:
                lines.append(f"*[QA] 배포 검증 완료* ({now_str})")
                lines.append(f"> 커밋 `{sha}` 배포 성공, 모든 엔드포인트 정상")
                self._state["last_known_deploy_sha"] = sha
                self._save_state()
            elif deploy.get("status") == "in_progress":
                # 배포 중이면 다음 사이클에서 확인
                return
            elif deploy.get("conclusion") == "failure":
                lines.append(f"*[QA] 배포 실패 감지!* ({now_str})")
                lines.append(f"> 커밋 `{sha}` 배포 실패 — GitHub Actions 확인 필요")

        # 헬스체크 실패
        if decision.get("failures"):
            self._consecutive_failures += 1
            lines.append(f"*[QA] 서비스 이상 감지* ({now_str})")
            for f in decision["failures"]:
                error = f.get("error", f"HTTP {f.get('status')}")
                lines.append(f"> {f['name']} ({f['path']}): {error}")

            if self._consecutive_failures >= 3:
                lines.append(f"\n연속 {self._consecutive_failures}회 실패 — 긴급 점검 필요!")

        # 느린 엔드포인트
        if decision.get("slow"):
            lines.append(f"*[QA] 느린 응답 감지* ({now_str})")
            for s in decision["slow"]:
                lines.append(f"> {s['name']}: {s['latency_ms']}ms")

        if lines:
            msg = "\n".join(lines)
            await self.slack.send_message(self.slack_channel, msg)
            await self.log(msg)

        # 상태 업데이트
        if decision.get("new_deploy") and decision.get("deploy"):
            self._state["last_known_deploy_sha"] = decision["deploy"]["sha"]
        self._state["last_deploy_check"] = now_str
        self._state["failure_count"] = self._consecutive_failures
        self._save_state()

    # ── 수동 실행 지원 ───────────────────────────────────

    async def run_once(self, channel: str = None, thread_ts: str = None) -> str | None:
        """!qa 명령어로 즉시 테스트 실행"""
        context = await self.observe()
        if not context:
            return "QA 데이터 수집 실패"

        health = context.get("health_results", [])
        failures = [h for h in health if not h.get("ok")]
        deploy = context.get("deploy_status")

        lines = [f"*[QA 수동 테스트]* ({context['timestamp']})\n"]

        # 헬스체크 결과
        for h in health:
            icon = "OK" if h["ok"] else "FAIL"
            latency = f" ({h.get('latency_ms', '?')}ms)" if h.get("ok") else ""
            error = f" — {h.get('error', f'HTTP {h.get(\"status\")}')}" if not h["ok"] else ""
            lines.append(f"{'  ' if h['ok'] else '  '}{icon} {h['name']}{latency}{error}")

        # 배포 상태
        if deploy:
            status = deploy.get("conclusion") or deploy.get("status")
            lines.append(f"\n*배포*: {deploy['name']} — {status} (sha: `{deploy['sha']}`)")

        # Studio API
        studio = context.get("studio_health", {})
        if studio.get("status") == "ok":
            lines.append(f"*Studio API*: 정상 (빌드 #{studio.get('build_num', '?')})")
        else:
            lines.append(f"*Studio API*: {studio.get('error', '알 수 없음')}")

        result = "\n".join(lines)
        target_channel = channel or self.slack_channel
        if thread_ts:
            await self.slack.send_thread_reply(target_channel, thread_ts, result)
        else:
            await self.slack.send_message(target_channel, result)
        return None
