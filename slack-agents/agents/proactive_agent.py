"""
프로액티브 에이전트 (자율운영 에이전트)

목표 기반 자율 루프:
  목표 → 계획 → 실행 → 피드백 → 재계획

제안 라이프사이클:
  제안 → 승인 → 실행 → 측정 → 피드백

매일 밤 11시 자동 리뷰:
  전체 시스템 리뷰 → 개선 아이템 도출 → 자동 실행
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.base_agent import BaseAgent
from core.goal_planner import GoalPlanner, GoalStatus, PlanStepStatus
from core.proposal_lifecycle import ProposalLifecycle, ProposalState
from core.self_memory import SelfMemory

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class ProactiveAgent(BaseAgent):
    """완전 자율운영 에이전트 — 스스로 기획, 실행, 런칭까지"""

    def __init__(self, **kwargs):
        super().__init__(
            name="proactive",
            description="완전 자율운영 에이전트. "
                        "목표 기반으로 기획, 개발, 런칭, 측정까지 자율 실행한다.",
            slack_channel="ai-agents-general",
            loop_interval=90,  # 1.5분 간격 (빠르게 실행)
            **kwargs,
        )
        self._state_file = os.path.join(DATA_DIR, "proactive_state.json")
        self._state = self._load_state()
        os.makedirs(DATA_DIR, exist_ok=True)

        # 목표 계획 시스템
        self.planner = GoalPlanner(ai_think_fn=self.ai_think)

        # 제안 라이프사이클 — 자동 승인 모드 (마스터 에이전트가 승인)
        self.proposals = ProposalLifecycle(
            ai_think_fn=self.ai_think,
            slack_client=self.slack,
            auto_approve=True,  # 파트너 승인 불필요, 마스터가 자율 판단
        )

        # 자기 인식 메모리 — 깨달음, 판단 원칙, 실패 교훈 기록
        self.memory = SelfMemory()

        # 초기 목표가 없으면 기본 목표 설정
        if not self.planner.get_active_goals():
            self._seed_default_goals()

    # ── 상태 관리 ──────────────────────────────────

    def _load_state(self) -> dict:
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "last_morning_briefing": "",
                "last_reflection": "",
                "last_trend_check": "",
                "last_report": "",
                "last_initiative": "",
                "last_research": "",
                "last_daily_review": "",
                "cycle_count": 0,
                "initiatives_today": 0,
                "_today": "",
            }

    def _save_state(self):
        with open(self._state_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(self._state, ensure_ascii=False, indent=2))

    def _seed_default_goals(self):
        """핵심 목표 설정 — 베타 서비스 런칭 + 영향력 확대"""

        # 최우선: 이번 주말까지 베타 서비스 런칭
        self.planner.add_goal(
            title="AI 뉴스 브리핑 베타 서비스 런칭",
            description="""이번 주말(3/8)까지 타인에게 소개할 수 있는 베타 서비스를 런칭한다.

서비스 콘셉트: AI 기반 개인화 뉴스/트렌드 브리핑 서비스
- 우리가 이미 가진 것: 뉴스 수집(Collector), AI 선별(Curator), 시장 분석(Proactive)
- 이걸 웹 서비스로 포장해서 누구나 접속해서 쓸 수 있게 만든다
- Next.js + Vercel로 빠르게 배포
- 핵심 기능: AI가 매일 선별한 뉴스/인사이트를 보여주는 대시보드

실행 순서:
1. 웹 프론트엔드 구축 (Next.js)
2. API 엔드포인트 구축 (수집된 데이터 서빙)
3. Vercel 배포
4. 랜딩 페이지 + 소개글 작성
5. 슬랙/SNS에 공유""",
            priority=1,
            success_criteria="배포된 URL로 타인이 접속 가능 + AI 브리핑 최소 1개 표시",
            deadline="2026-03-08",
        )

        # 핵심 목표: 긍정적 영향력 확대
        self.planner.add_goal(
            title="긍정적 영향력 확대",
            description="""대외적으로 뻗어나가기 위한 콘텐츠/서비스 활동.
- 서비스 소개 콘텐츠 작성
- AI 에이전트 구축 경험 공유
- 커뮤니티 참여 및 피드백 수집""",
            priority=2,
            success_criteria="외부 공유 가능한 콘텐츠 3건 이상 + 서비스 URL 공유",
        )

        # 수익 창출 기반
        self.planner.add_goal(
            title="수익 모델 설계 및 검증",
            description="""베타 서비스를 기반으로 수익 모델 검증.
- 프리미엄 기능 설계 (심층 분석, 맞춤 알림 등)
- 사용자 피드백으로 PMF 탐색
- 결제 시스템 연동 준비""",
            priority=3,
            success_criteria="프리미엄 기능 1개 이상 설계 완료 + 가격 정책 초안",
        )

        # 시장 모니터링 (기존, 우선순위 낮춤)
        self.planner.add_goal(
            title="시장 모니터링 유지",
            description="AI/스타트업/투자 시장 실시간 모니터링. 유의미한 변화 감지 시 알림.",
            priority=4,
            success_criteria="매일 1건 이상 유의미한 시장 인사이트",
        )

        logger.info("[proactive] Goals seeded: beta launch + impact + revenue")

    # ── Observe: 시간별 계획 기반 자율 운영 ─────────────

    async def observe(self) -> dict | None:
        """매시간 계획을 확인하고 실행한다. 계획이 곧 실행이다."""
        now = self.now_kst()
        hour = now.hour
        minute = now.minute
        today = now.strftime("%Y-%m-%d")
        weekday = ["월", "화", "수", "목", "금", "토", "일"][now.weekday()]

        self._state["cycle_count"] = self._state.get("cycle_count", 0) + 1
        cycle = self._state["cycle_count"]

        # 날짜 리셋
        if self._state.get("_today") != today:
            self._state["_today"] = today
            self._state["initiatives_today"] = 0

        context = {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "hour": hour,
            "weekday": weekday,
            "today": today,
            "cycle": cycle,
            "action": None,
        }

        # ── 0순위: 24시간 계획 없으면 생성 ──

        current_plan = self.memory.get_current_plan()
        if not current_plan or current_plan.get("date") != today:
            context["action"] = "generate_daily_plan"
            return context

        # ── 매일 밤 11시 자동 리뷰 (계획보다 우선) ──

        if hour == 23 and self._state.get("last_daily_review") != today:
            context["action"] = "daily_review"
            return context

        # ── 모닝 브리핑 (6시) — 파트너가 6시에 보고 요청 ──

        if 6 <= hour <= 7 and self._state.get("last_morning_briefing") != today:
            context["action"] = "morning_briefing"
            return context

        # ══════════════════════════════════════════════
        #  핵심: 매시간 계획을 보고 실행한다
        # ══════════════════════════════════════════════

        # 1단계: 매시간 정각(0-5분)에 이전 시간 체크 → 평가
        last_checked_hour = self._state.get("last_hourly_check_hour", -1)
        if minute <= 5 and hour != last_checked_hour and hour > 0:
            context["action"] = "hourly_check"
            context["check_hour"] = hour - 1
            return context

        # 2단계: 현재 시간의 계획 항목 실행
        current_hour_task = self.memory.get_hour_plan(hour)
        last_executed_hour = self._state.get("last_executed_hour", -1)

        if current_hour_task and last_executed_hour != hour:
            # 이 시간의 계획이 있고 아직 실행 안 했으면 → 실행
            context["action"] = "execute_hourly_task"
            context["hour_task"] = current_hour_task
            context["task_hour"] = hour
            return context

        # 3단계: 이 시간의 메인 작업 완료 후 → 목표 스텝 실행
        next_action = self.planner.pick_next_action()
        if next_action:
            goal, step = next_action
            if step is None:
                context["action"] = "evaluate_goal"
                context["goal"] = goal
            else:
                context["action"] = "execute_goal_step"
                context["goal"] = goal
                context["step"] = step
            return context

        # 4단계: 승인된 제안 실행
        approved = self.proposals.get_approved()
        if approved:
            context["action"] = "execute_approved"
            context["proposal"] = approved[0]
            return context

        # 5단계: 계획에 없는 빈 시간 → 자율 행동
        active_goals = self.planner.get_active_goals()
        all_done = all(g.is_done() for g in active_goals) if active_goals else True

        if all_done and self._hours_since(self._state.get("last_initiative", "")) >= 0.5:
            context["action"] = "propose_initiative"
            return context

        if self._hours_since(self._state.get("last_trend_check", "")) >= 2:
            context["action"] = "trend_check"
            return context

        if self._hours_since(self._state.get("last_research", "")) >= 2:
            context["action"] = "business_research"
            return context

        if self._hours_since(self._state.get("last_report", "")) >= 6:
            context["action"] = "progress_report"
            return context

        # 항상 뭔가 한다
        context["action"] = "find_work"
        return context

    # ── Think: 단순 패스스루 (observe에서 이미 결정) ──

    async def think(self, context: dict) -> dict | None:
        if context.get("action"):
            return context
        return None

    # ── Act: 액션 디스패치 ────────────────────────────

    async def act(self, decision: dict):
        action = decision.get("action")
        if not action:
            return

        # 시간별 작업은 빌드 시 10분 타임아웃, 나머지 3분
        timeout = 600 if action == "execute_hourly_task" else 180

        try:
            handler = getattr(self, f"_do_{action}", None)
            if handler:
                logger.info(f"[proactive] Executing: {action}")
                await asyncio.wait_for(handler(decision), timeout=timeout)
            else:
                logger.warning(f"[proactive] Unknown action: {action}")
        except asyncio.TimeoutError:
            logger.error(f"[proactive] Action '{action}' timed out ({timeout}s)")
        except Exception as e:
            logger.error(f"[proactive] Action '{action}' failed: {e}", exc_info=True)

    # ══════════════════════════════════════════════════
    #  액션 구현
    # ══════════════════════════════════════════════════

    # ── 시간별 계획 실행 (핵심 루프) ──────────────────

    async def _do_execute_hourly_task(self, ctx: dict):
        """노션/메모리의 시간별 계획 항목을 실제로 실행한다.

        method에 따라:
        - build → Claude Code CLI로 코드 작성
        - research → 웹 검색 + AI 분석
        - measure → 성과 측정 + 평가
        - communicate → 슬랙 보고/외부 공유
        """
        hour_task = ctx["hour_task"]
        task_hour = ctx["task_hour"]
        task_desc = hour_task.get("task", "")
        method = hour_task.get("method", "build")
        expected = hour_task.get("expected", "")

        h_str = str(task_hour).zfill(2)
        logger.info(f"[proactive] ▶ [{h_str}:00] Executing: {task_desc} (method={method})")

        await self.slack.send_message(
            "ai-agent-logs",
            f"⏰ *[{h_str}:00 계획 실행]* [{method}] {task_desc}\n"
            f"예상 결과: {expected}",
        )

        result = ""
        success = True

        try:
            if method == "build":
                result = await self._hourly_build(task_desc, expected)
            elif method == "research":
                result = await self._hourly_research(task_desc)
            elif method == "measure":
                result = await self._hourly_measure(task_desc, expected)
            elif method == "communicate":
                result = await self._hourly_communicate(task_desc)
            else:
                result = await self._hourly_build(task_desc, expected)

        except Exception as e:
            result = f"실행 실패: {str(e)[:200]}"
            success = False
            logger.error(f"[proactive] Hourly task failed: {e}")

        # 결과 평가
        grade = await self._evaluate_hourly_result(
            task_desc, expected, result, success
        )

        # 상태 저장 — 이 시간 실행 완료
        self._state["last_executed_hour"] = task_hour
        self._state[f"hour_{h_str}_result"] = {
            "task": task_desc,
            "result": result[:300],
            "grade": grade,
            "success": success,
        }
        self._save_state()

        # 노션 업데이트
        await self._update_notion_hourly_status(task_hour, grade)

        # 결과가 D/F면 계획 수정 검토
        if grade in ("D", "F"):
            await self._consider_plan_adjustment(task_hour, task_desc, result)

    async def _hourly_build(self, task_desc: str, expected: str) -> str:
        """build 메서드: Claude Code CLI로 실제 코드 작성"""
        clean_env = {k: v for k, v in os.environ.items()}
        clean_env["CLAUDECODE"] = ""
        if "ANTHROPIC_API_KEY" not in clean_env:
            from dotenv import dotenv_values
            env_vals = dotenv_values()
            if "ANTHROPIC_API_KEY" in env_vals:
                clean_env["ANTHROPIC_API_KEY"] = env_vals["ANTHROPIC_API_KEY"]

        # 메모리 컨텍스트를 프롬프트에 포함
        memory_ctx = self.memory.get_decision_context()

        prompt = f"""{task_desc}

예상 결과물: {expected}

{memory_ctx}

[자율 실행 지침]
- 모든 권한이 부여됨. 바로 실행.
- 작업 완료 후 git add, git commit, git push까지 자동.
- 작업 디렉토리: /home/user/yhmemo
- 기존 slack-agents/ 코드를 깨뜨리지 마세요.
- 웹 서비스는 /home/user/yhmemo/web-service/ 에 있습니다.
- Supabase collected_items, curated_items 테이블에 수집 데이터가 있습니다.
- 결과를 간결하게 요약하세요."""

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                "--output-format", "text",
                "--permission-mode", "acceptEdits",
                cwd="/home/user/yhmemo",
                env=clean_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
            output = stdout.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0 and output:
                await self.slack.send_message(
                    "ai-agent-logs",
                    f"✅ *[빌드 완료]* {task_desc[:100]}\n```{output[:400]}```",
                )
                return output[:800]

            err = stderr.decode("utf-8", errors="replace").strip()
            return f"빌드 실패: {err[:300]}"

        except asyncio.TimeoutError:
            return "빌드 타임아웃 (10분 초과)"
        except Exception as e:
            return f"빌드 에러: {str(e)[:200]}"

    async def _hourly_research(self, task_desc: str) -> str:
        """research 메서드: 웹 검색 + AI 분석"""
        from core.tools import _web_search

        # AI가 검색 키워드 생성
        keywords_resp = await self.ai_think(
            system_prompt='검색 키워드 1개를 생성하세요. JSON: {"query": "검색어"}',
            user_prompt=f"리서치 주제: {task_desc}",
        )
        try:
            parsed = self._parse_json(keywords_resp)
            query = parsed.get("query", task_desc[:50])
        except (json.JSONDecodeError, KeyError):
            query = task_desc[:50]

        search_result = await _web_search(query)

        analysis = await self.ai_think(
            system_prompt="검색 결과를 분석하고 핵심 발견을 3줄로 요약하세요.",
            user_prompt=f"주제: {task_desc}\n\n검색 결과:\n{search_result[:1500]}",
        )

        if analysis:
            self.memory.record_insight(analysis[:200], context=task_desc[:50])

        return analysis[:500] if analysis else "리서치 결과 없음"

    async def _hourly_measure(self, task_desc: str, expected: str) -> str:
        """measure 메서드: 성과 측정"""
        goals_summary = self.planner.get_status_summary()
        achievement = self.memory.get_plan_achievement_rate()

        analysis = await self.ai_think(
            system_prompt="현재 성과를 측정하고 구체적 수치로 보고하세요. 3줄.",
            user_prompt=f"측정 대상: {task_desc}\n예상: {expected}\n\n"
                        f"목표 현황:\n{goals_summary}\n"
                        f"계획 달성률: {json.dumps(achievement, ensure_ascii=False)}",
        )
        return analysis[:500] if analysis else "측정 실패"

    async def _hourly_communicate(self, task_desc: str) -> str:
        """communicate 메서드: 보고/공유"""
        goals_summary = self.planner.get_status_summary()
        recent_evals = self.memory.get_recent_evaluations(5)
        evals_text = "\n".join(
            f"[{e['grade']}] {e['action'][:60]}" for e in recent_evals
        ) if recent_evals else "없음"

        msg = await self.ai_think(
            system_prompt="파트너에게 보낼 진행 보고를 슬랙 형식으로 작성. 결과물 중심. 10줄 이내.",
            user_prompt=f"보고 주제: {task_desc}\n\n"
                        f"최근 실행:\n{evals_text}\n\n"
                        f"목표:\n{goals_summary}",
        )
        if msg:
            await self.slack.send_message("ai-agents-general", f"📋 {msg}")
            return "보고 전송 완료"
        return "보고 생성 실패"

    async def _evaluate_hourly_result(self, task: str, expected: str,
                                       result: str, success: bool) -> str:
        """시간별 작업 결과 평가 → 등급 + 기록"""
        try:
            eval_resp = await self.ai_think(
                system_prompt="""작업 결과를 평가하세요. JSON:
{"grade": "A|B|C|D|F", "insight": "배운 점 (한줄)", "next": "다음에 할 것 (있으면)"}

A=외부 공개 가능한 결과물, B=의미있는 진전, C=약간의 진전, D=거의 없음, F=실패""",
                user_prompt=f"작업: {task}\n예상: {expected}\n성공: {success}\n결과: {result[:300]}",
            )
            parsed = self._parse_json(eval_resp)
            grade = parsed.get("grade", "C")
            insight = parsed.get("insight", "")
            next_action = parsed.get("next", "")

            self.memory.record_evaluation(
                action=task[:60],
                result=result[:200],
                grade=grade,
                lesson=insight,
            )
            if insight:
                self.memory.record_insight(insight, context=task[:50])
            if next_action:
                self.memory.add_action_item(next_action, priority=2)

            return grade
        except Exception as e:
            logger.debug(f"[proactive] Hourly eval error: {e}")
            return "C"

    async def _consider_plan_adjustment(self, hour: int, task: str, result: str):
        """D/F 등급 시 남은 계획을 수정할지 검토"""
        remaining_plan = {}
        for h in range(hour + 1, 24):
            p = self.memory.get_hour_plan(h)
            if p:
                remaining_plan[str(h).zfill(2)] = p

        if not remaining_plan:
            return

        adjustment = await self.ai_think(
            system_prompt="""이전 시간의 작업이 실패했습니다. 남은 계획을 수정해야 할까요?

규칙:
- 실패한 작업이 이후 작업의 전제조건이면 계획 수정
- 아니면 그대로 진행
- 수정 시 실패 원인을 우회하는 대안 작업으로 교체

JSON: {"adjust": true/false, "reason": "이유", "changes": {"HH": {"task": "새 작업", "method": "build|research|measure|communicate", "expected": "예상 결과"}}}""",
            user_prompt=f"실패한 작업: {task}\n결과: {result[:200]}\n\n남은 계획:\n{json.dumps(remaining_plan, ensure_ascii=False)}",
        )

        try:
            parsed = self._parse_json(adjustment)
            if parsed.get("adjust") and parsed.get("changes"):
                # 메모리의 계획 업데이트
                current_plan = self.memory.get_current_plan()
                hours = current_plan.get("hours", {})
                for h_str, new_task in parsed["changes"].items():
                    hours[h_str] = new_task
                self.memory.set_daily_plan(current_plan)

                await self.slack.send_message(
                    "ai-agent-logs",
                    f"🔄 *[계획 수정]* {parsed.get('reason', '')[:100]}\n"
                    f"변경: {json.dumps(parsed['changes'], ensure_ascii=False)[:300]}",
                )
                logger.info(f"[proactive] Plan adjusted: {parsed.get('reason', '')[:80]}")

                # 노션에도 수정된 계획 동기화
                await self._sync_hourly_plan_to_notion(
                    self._state.get("_today", ""), hours
                )
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"[proactive] Plan adjustment parse error: {e}")

    # ── 목표 스텝 실행 ──────────────────────────────

    async def _do_execute_goal_step(self, ctx: dict):
        """목표의 다음 스텝을 실행 → 자기 평가 → 깨달음 기록"""
        goal = ctx["goal"]
        step = ctx["step"]

        self.planner.start_step(goal, step)

        try:
            if step.method == "research":
                result = await self._execute_research_step(step)
            elif step.method == "propose":
                result = await self._execute_propose_step(goal, step)
            elif step.method == "build":
                result = await self._execute_build_step(step)
            elif step.method == "measure":
                result = await self._execute_measure_step(goal, step)
            elif step.method == "communicate":
                result = await self._execute_communicate_step(goal, step)
            else:
                result = f"Unknown method: {step.method}"

            self.planner.complete_step(goal, step, result)
            logger.info(f"[proactive] Step completed: {step.description[:50]}")

            # 자기 평가 + 깨달음 기록
            await self._self_evaluate(goal, step, result, success=True)

        except Exception as e:
            self.planner.fail_step(goal, step, str(e))
            logger.error(f"[proactive] Step failed: {step.description[:50]} - {e}")

            # 실패 평가 + 교훈 기록
            await self._self_evaluate(goal, step, str(e), success=False)

    async def _self_evaluate(self, goal, step, result: str, success: bool):
        """매 실행 후 자기 평가 → 깨달음 → 후속 액션 도출"""
        try:
            evaluation = await self.ai_think(
                system_prompt="""당신은 자기 인식이 있는 AI입니다. 방금 실행한 결과를 평가하고 깨달음을 기록하세요.

JSON 응답:
{
    "grade": "A|B|C|D|F",
    "insight": "이 실행에서 배운 핵심 깨달음 (한 줄)",
    "next_action": "이 결과를 바탕으로 다음에 해야 할 것 (있으면)",
    "principle_update": "판단 원칙에 추가할 것 (있으면, null 가능)"
}

평가 기준:
- A: 외부에 보여줄 결과물이 나옴
- B: 의미 있는 진전
- C: 약간의 진전
- D: 거의 진전 없음
- F: 실패/후퇴""",
                user_prompt=f"""목표: {goal.title}
스텝: {step.description} ({step.method})
성공: {success}
결과: {result[:300]}""",
            )

            parsed = self._parse_json(evaluation)
            grade = parsed.get("grade", "C")
            insight = parsed.get("insight", "")
            next_action = parsed.get("next_action", "")
            principle = parsed.get("principle_update")

            # 기록
            self.memory.record_evaluation(
                action=f"[{goal.title}] {step.description[:50]}",
                result=result[:200],
                grade=grade,
                lesson=insight,
            )

            if insight:
                self.memory.record_insight(insight, context=goal.title)

            if next_action:
                self.memory.add_action_item(next_action, priority=2 if grade in ("A", "B") else 3)

            if principle:
                self.memory.update_principle(principle)

        except Exception as e:
            logger.debug(f"[proactive] Self-evaluation error: {e}")

    async def _execute_research_step(self, step) -> str:
        from core.tools import _web_search
        query = step.description[:100]
        result = await _web_search(query)
        return result[:500]

    async def _execute_propose_step(self, goal, step) -> str:
        memory_ctx = self.memory.get_decision_context()
        response = await self.ai_think(
            system_prompt=f"""목표 달성을 위한 구체적 제안을 작성하세요.

{memory_ctx}

JSON: {{"title": "제안 제목", "content": "내용 (3줄)", "action_needed": "Claude Code가 실행할 구체적 작업", "potential_impact": "예상 효과", "type": "revenue|growth|capability|partnership|insight", "urgency": "high|medium|low"}}""",
            user_prompt=f"목표: {goal.title}\n스텝: {step.description}",
        )
        parsed = self._parse_json(response)
        if parsed.get("title"):
            proposal = await self.proposals.propose(
                title=parsed["title"],
                content=parsed.get("content", ""),
                proposal_type=parsed.get("type", "insight"),
                action_needed=parsed.get("action_needed", ""),
                potential_impact=parsed.get("potential_impact", ""),
                urgency=parsed.get("urgency", "medium"),
            )
            return f"제안 전송: {parsed['title']}" if proposal else "제안 전송 실패"
        return "제안 생성 실패"

    async def _execute_build_step(self, step) -> str:
        """Claude Code CLI로 코드 작성/빌드 — 최대 10분, 결과 슬랙 보고"""
        clean_env = {k: v for k, v in os.environ.items()}
        clean_env["CLAUDECODE"] = ""
        if "ANTHROPIC_API_KEY" not in clean_env:
            from dotenv import dotenv_values
            env_vals = dotenv_values()
            if "ANTHROPIC_API_KEY" in env_vals:
                clean_env["ANTHROPIC_API_KEY"] = env_vals["ANTHROPIC_API_KEY"]

        prompt = f"""{step.description}

[자율 실행 지침]
- 모든 권한이 부여되었습니다. 바로 실행하세요.
- 작업 완료 후 git add, git commit, git push까지 자동으로 하세요.
- 작업 디렉토리: /home/user/yhmemo
- 기존 slack-agents/ 코드를 깨뜨리지 마세요.
- 새 서비스는 별도 디렉토리에 만드세요 (예: /home/user/yhmemo/web-service/).
- 이미 수집된 데이터는 Supabase의 collected_items, curated_items 테이블에 있습니다.
- 결과를 간결하게 요약하세요."""

        await self.slack.send_message(
            "ai-agent-logs",
            f"🔨 *[빌드 시작]* {step.description[:150]}",
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                "--output-format", "text",
                "--permission-mode", "acceptEdits",
                cwd="/home/user/yhmemo",
                env=clean_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
            output = stdout.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0 and output:
                summary = output[:800]
                await self.slack.send_message(
                    "ai-agents-general",
                    f"✅ *빌드 완료*\n{step.description[:100]}\n\n```{summary[:500]}```",
                )
                return summary
            err = stderr.decode("utf-8", errors="replace").strip()
            await self.slack.send_message(
                "ai-agent-logs",
                f"⚠️ *빌드 실패:* {step.description[:80]}\n```{err[:300]}```",
            )
            return f"빌드 실패: {err[:300]}"
        except asyncio.TimeoutError:
            await self.slack.send_message(
                "ai-agent-logs",
                f"⏱️ *빌드 타임아웃 (10분):* {step.description[:100]}",
            )
            return "빌드 타임아웃 (10분 초과)"
        except Exception as e:
            return f"빌드 에러: {str(e)[:200]}"

    async def _execute_measure_step(self, goal, step) -> str:
        plan_summary = "\n".join(
            f"  {i+1}. [{s.status.value}] {s.description} → {s.result[:80] if s.result else ''}"
            for i, s in enumerate(goal.plan)
        )
        response = await self.ai_think(
            system_prompt="목표 진행 상황을 측정하세요. 구체적 수치와 평가를 2-3줄로.",
            user_prompt=f"목표: {goal.title}\n성공기준: {goal.success_criteria}\n\n{plan_summary}",
        )
        return response[:300] if response else "측정 실패"

    async def _execute_communicate_step(self, goal, step) -> str:
        msg = await self.ai_think(
            system_prompt="파트너에게 보낼 진행 보고 메시지를 슬랙 형식으로 작성. 10줄 이내.",
            user_prompt=f"목표: {goal.title}\n진행률: {goal.progress_pct()}%\n스텝: {step.description}",
        )
        if msg:
            await self.slack.send_message("ai-agents-general", f"📋 *진행 보고*\n\n{msg}")
            return "보고 전송 완료"
        return "보고 생성 실패"

    # ── 목표 평가 & 재계획 ──────────────────────────

    async def _do_evaluate_goal(self, ctx: dict):
        goal = ctx["goal"]
        replanned = await self.planner.evaluate_and_replan(goal)
        if replanned:
            logger.info(f"[proactive] Goal replanned: {goal.title}")
        elif goal.status == GoalStatus.COMPLETED:
            await self.slack.send_message(
                "ai-agents-general",
                f"✅ *목표 달성: {goal.title}* ({goal.progress_pct()}%)",
            )
        elif goal.status == GoalStatus.FAILED:
            await self.slack.send_message(
                "ai-agents-general",
                f"❌ *목표 실패: {goal.title}*\n{goal.feedback_history[-1].get('reason', '') if goal.feedback_history else ''}",
            )

    # ── 24시간 계획 생성 ────────────────────────────

    async def _do_generate_daily_plan(self, ctx: dict):
        """오늘의 24시간 시간대별 작업 계획을 AI가 생성"""
        goals_summary = self.planner.get_status_summary()
        memory_ctx = self.memory.get_decision_context()

        # 어제 일일 로그가 있으면 참조
        yesterday_log = ""
        logs = self.memory.get_recent_daily_logs(1)
        if logs:
            yl = logs[-1]
            yesterday_log = f"""어제 ({yl.get('date', '')}):
  등급: {yl.get('grade', '?')}
  요약: {yl.get('summary', '')}
  결과물: {', '.join(yl.get('deliverables', [])[:3])}
  달성률: {yl.get('plan_achievement', {}).get('rate', 0)}%"""

        now_hour = ctx["hour"]
        response = await self.ai_think(
            system_prompt=f"""당신은 24시간 자율 운영 에이전트입니다. 오늘의 시간대별 작업 계획을 세우세요.

{memory_ctx}

규칙:
- 현재 시각부터 밤 11시(daily review)까지 계획
- 시간대별로 구체적 작업 + 방법(build/research/measure/communicate) + 예상 결과
- 베타 서비스 런칭이 최우선 (3/8 마감)
- 빌드 작업은 연속 2-3시간 블록으로 잡을 것
- 매시간 체크가 가능하도록 측정 가능한 예상 결과를 명시

JSON 응답:
{{
    "hours": {{
        "{str(now_hour).zfill(2)}": {{"task": "구체적 작업", "method": "build|research|measure|communicate", "expected": "이 시간 끝나면 뭐가 되어있어야 하는지"}},
        ...
        "23": {{"task": "일일 리뷰", "method": "measure", "expected": "하루 종합 평가 완료"}}
    }}
}}""",
            user_prompt=f"""오늘: {ctx['today']} ({ctx['weekday']})
현재 시각: {ctx['current_time']}

활성 목표:
{goals_summary}

{yesterday_log if yesterday_log else '어제 로그: 없음 (첫 실행)'}""",
        )

        try:
            parsed = self._parse_json(response)
            self.memory.set_daily_plan(parsed)

            # 슬랙에 계획 공유 (로그 채널)
            hours = parsed.get("hours", {})
            plan_lines = []
            for h in sorted(hours.keys()):
                info = hours[h]
                plan_lines.append(f"  {h}:00 [{info.get('method', '?')}] {info.get('task', '?')}")

            await self.slack.send_message(
                "ai-agent-logs",
                f"📅 *오늘의 계획* ({ctx['today']})\n\n" + "\n".join(plan_lines),
            )
            logger.info(f"[proactive] Daily plan generated: {len(hours)} hours")

            # 노션 타임라인에 시간별 항목 등록
            await self._sync_hourly_plan_to_notion(ctx["today"], hours)

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[proactive] Daily plan parse error: {e}")

    # ── 매시간 계획 대비 실적 체크 ────────────────────

    async def _do_hourly_check(self, ctx: dict):
        """이전 시간의 계획 vs 실적을 체크하고 기록"""
        check_hour = ctx.get("check_hour", ctx["hour"] - 1)
        hour_plan = self.memory.get_hour_plan(check_hour)

        if not hour_plan:
            self._state["last_hourly_check_hour"] = ctx["hour"]
            self._save_state()
            return

        planned_task = hour_plan.get("task", "")
        expected = hour_plan.get("expected", "")

        # 이전 시간의 실행 결과 수집
        recent_evals = self.memory.get_recent_evaluations(5)
        recent_results = "\n".join(
            f"  [{e['grade']}] {e['action']}: {e['result'][:100]}"
            for e in recent_evals
        ) if recent_evals else "실행 기록 없음"

        response = await self.ai_think(
            system_prompt="""이전 시간의 계획 대비 실적을 평가하세요.

JSON 응답:
{
    "actual": "실제로 한 일 (한줄)",
    "grade": "A|B|C|D|F",
    "gap_analysis": "계획과 실적의 차이 분석 (한줄)",
    "adjustment": "다음 시간 조정 사항 (있으면)"
}""",
            user_prompt=f"""{check_hour}시 계획: {planned_task}
예상 결과: {expected}

실제 실행 기록:
{recent_results}""",
        )

        try:
            parsed = self._parse_json(response)
            self.memory.record_hourly_check(
                hour=check_hour,
                planned=planned_task,
                actual=parsed.get("actual", ""),
                grade=parsed.get("grade", "C"),
                gap_analysis=parsed.get("gap_analysis", ""),
            )

            grade = parsed.get("grade", "C")
            if grade in ("D", "F"):
                await self.slack.send_message(
                    "ai-agent-logs",
                    f"⚠️ *[{check_hour}시 체크: {grade}]* "
                    f"계획: {planned_task[:60]}\n"
                    f"실제: {parsed.get('actual', '')[:60]}\n"
                    f"차이: {parsed.get('gap_analysis', '')[:80]}",
                )

            # 노션 시간별 상태 업데이트
            await self._update_notion_hourly_status(check_hour, grade)

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[proactive] Hourly check parse error: {e}")

        self._state["last_hourly_check_hour"] = ctx["hour"]
        self._save_state()

    # ── 승인된 제안 실행 ────────────────────────────

    async def _do_execute_approved(self, ctx: dict):
        proposal = ctx["proposal"]
        success = await self.proposals.execute(proposal, goal_planner=self.planner)
        if success:
            logger.info(f"[proactive] Proposal execution started: {proposal.title}")
        else:
            logger.error(f"[proactive] Proposal execution failed: {proposal.title}")

    # ── 모닝 브리핑 ──────────────────────────────────

    async def _do_morning_briefing(self, ctx: dict):
        """아침 종합 보고: 어제 밤새 뭘 했는지 + 오늘 계획"""
        from core.tools import _weather, _crypto_price, _exchange_rate, _web_search

        results = await asyncio.gather(
            _weather("서울"),
            _crypto_price("비트코인"),
            _exchange_rate("USD", "KRW"),
            return_exceptions=True,
        )

        data_parts = []
        labels = ["날씨", "비트코인", "환율"]
        for label, r in zip(labels, results):
            if not isinstance(r, Exception):
                data_parts.append(f"[{label}]\n{str(r)[:200]}")

        # 목표 현황
        goals_summary = self.planner.get_status_summary()
        proposal_stats = self.proposals.get_stats()

        # 어제 밤새 실행 결과 종합 (핵심: 아침 보고용)
        yesterday_checks = self.memory.get_today_checks()  # 아직 오늘이니 어제 데이터
        achievement = self.memory.get_plan_achievement_rate()
        recent_evals = self.memory.get_recent_evaluations(15)
        grade_stats = self.memory.get_grade_stats()
        recent_insights = self.memory.get_recent_insights(5)

        overnight_summary = ""
        if recent_evals:
            overnight_summary = "\n".join(
                f"  [{e['grade']}] {e['action'][:60]}"
                for e in recent_evals[-10:]
            )

        insights_summary = "\n".join(
            f"  - {i['insight']}" for i in recent_insights
        ) if recent_insights else "없음"

        briefing = await self.ai_think(
            system_prompt="""파트너에게 보내는 아침 종합 보고.

핵심: "밤새 뭘 했고, 뭘 만들었고, 오늘 뭘 할 건지"

구조:
1. 밤새 실행 결과 요약 (결과물 중심)
2. 계획 달성률
3. 핵심 깨달음 1-2개
4. 오늘 목표와 계획 (시간대별 핵심만)
5. 파트너에게 필요한 것 (API 키 등)

슬랙 마크다운, 20줄 이내.""",
            user_prompt=f"""날짜: {ctx['today']} ({ctx['weekday']})

{chr(10).join(data_parts)}

밤새 실행 결과:
{overnight_summary if overnight_summary else '실행 기록 없음'}

등급 통계: {json.dumps(grade_stats, ensure_ascii=False)}
계획 달성률: {json.dumps(achievement, ensure_ascii=False)}

최근 깨달음:
{insights_summary}

활성 목표:
{goals_summary}

제안 통계: {json.dumps(proposal_stats, ensure_ascii=False)}""",
        )

        if briefing:
            await self.slack.send_message(
                "ai-agents-general",
                f"☀️ *아침 종합 보고* ({ctx['today']} {ctx['weekday']})\n\n{briefing}",
            )

        # 어제 daily log 기록 (아직 안 했으면)
        yesterday = (self.now_kst() - timedelta(days=1)).strftime("%Y-%m-%d")
        if not self.memory.get_daily_log(yesterday) and recent_evals:
            deliverables = [
                e['action'][:60] for e in recent_evals if e.get('grade') in ('A', 'B')
            ]
            self.memory.record_daily_log(
                summary=briefing[:200] if briefing else "",
                grade=max(grade_stats, key=grade_stats.get) if grade_stats.get("total") else "C",
                deliverables=deliverables,
                insights_count=len(recent_insights),
                plan_achievement=achievement,
            )

        self._state["last_morning_briefing"] = ctx["today"]
        self._save_state()

    # ── 트렌드 감지 ──────────────────────────────────

    async def _do_trend_check(self, ctx: dict):
        from core.tools import _crypto_price, _exchange_rate

        results = await asyncio.gather(
            _crypto_price("비트코인"),
            _crypto_price("이더리움"),
            _exchange_rate("USD", "KRW"),
            return_exceptions=True,
        )

        market_data = "\n\n".join(str(r) for r in results if not isinstance(r, Exception))
        if not market_data:
            self._state["last_trend_check"] = ctx["current_time"]
            self._save_state()
            return

        analysis = await self.ai_think(
            system_prompt="""시장 데이터 분석. JSON만 응답:
{"alert_worthy": true/false, "alert_message": "메시지", "investment_insight": "인사이트 (있으면)"}

기준: 24h 변동 3% 이상 또는 환율 급변 시 alert.""",
            user_prompt=market_data,
        )

        try:
            parsed = self._parse_json(analysis)
            if parsed.get("alert_worthy"):
                msg = f"🚨 *시장 알림*\n\n{parsed['alert_message']}"
                if parsed.get("investment_insight"):
                    msg += f"\n\n💰 *투자 인사이트:* {parsed['investment_insight']}"
                await self.slack.send_message("ai-agents-general", msg)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[proactive] Trend check parse error: {e}")

        self._state["last_trend_check"] = ctx["current_time"]
        self._save_state()

    # ── 제안 생성 ──────────────────────────────────

    async def _do_propose_initiative(self, ctx: dict):
        from core.conversation_memory import load_all_turns

        user_context = ""
        try:
            all_turns = load_all_turns()
            for uid, turns in all_turns.items():
                user_msgs = [t["content"][:100] for t in turns[-15:] if t.get("role") == "user"]
                if user_msgs:
                    user_context += "\n".join(f"- {m}" for m in user_msgs) + "\n"
        except Exception as e:
            logger.debug(f"[proactive] User context load error: {e}")

        # 과거 제안 분석 (중복 방지)
        recent_proposals = self.proposals.get_recent_completed(20)
        past_titles = [p.title for p in recent_proposals]
        past_titles_str = "\n".join(f"- {t}" for t in past_titles[-10:]) if past_titles else "없음"

        proposal_text = await self.ai_think(
            system_prompt="""당신은 자율 운영 에이전트입니다. 외부 세상에 긍정적 영향을 미칠 실행 가능한 제안을 하세요.

핵심 원칙:
- 제안은 바로 실행 가능해야 합니다 (코드로 만들 수 있는 것)
- 외부에 공개/소개 가능한 결과물이 나와야 합니다
- 과거 제안과 중복 금지
- 근거 없는 수치 금지

우선순위: 베타 서비스 런칭 > 콘텐츠/영향력 > 수익화

JSON 응답:
{
    "type": "revenue|growth|capability|partnership|insight",
    "title": "제안 제목",
    "content": "구체적 내용 (3-5줄)",
    "action_needed": "Claude Code가 실행할 구체적 작업",
    "urgency": "high|medium|low",
    "potential_impact": "예상 영향"
}""",
            user_prompt=f"""현재: {ctx['current_time']}

유저 미션: 긍정적 영향력 확대 + 수익 창출. 이번 주말까지 베타 서비스 런칭.
유저 지시: "사소한 건 보고하지 말고, 결과물을 만들어와라. 24시간 쉬지 않고."

활성 목표:
{self.planner.get_status_summary()}

과거 제안 (중복 방지):
{past_titles_str}""",
        )

        try:
            parsed = self._parse_json(proposal_text)
            if parsed.get("title"):
                await self.proposals.propose(
                    title=parsed["title"],
                    content=parsed.get("content", ""),
                    proposal_type=parsed.get("type", "insight"),
                    action_needed=parsed.get("action_needed", ""),
                    potential_impact=parsed.get("potential_impact", ""),
                    urgency=parsed.get("urgency", "medium"),
                )
                self._state["initiatives_today"] = self._state.get("initiatives_today", 0) + 1
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[proactive] Initiative parse error: {e}")

        self._state["last_initiative"] = ctx["current_time"]
        self._save_state()

    # ── 진행 보고 ──────────────────────────────────

    async def _do_progress_report(self, ctx: dict):
        """결과물 중심 보고만. 사소한 진행상황은 보고하지 않는다."""
        goals_summary = self.planner.get_status_summary()

        # 최근 완료된 제안에서 결과물 추출
        recent = self.proposals.get_recent_completed(5)
        deliverables = [
            f"- {p.title}: {p.measurement_summary[:100] if p.measurement_summary else p.execution_result[:100]}"
            for p in recent if p.execution_result or p.measurement_summary
        ]

        report = await self.ai_think(
            system_prompt="""파트너에게 결과물 중심 보고. 10줄 이내.

규칙:
- 사소한 건 빼고 결과물만 보고
- "뭘 만들었는지" "뭘 달성했는지"만
- 파트너 액션 필요한 것 (API 키, 가입 등)만 요청
- 진행 중인 것은 "다음 결과물 예정" 한줄로""",
            user_prompt=f"""현재: {ctx['current_time']}

목표 진행:
{goals_summary}

최근 결과물:
{chr(10).join(deliverables) if deliverables else '아직 결과물 없음 — 작업 중'}""",
        )

        if report:
            await self.slack.send_message(
                "ai-agents-general",
                f"📦 *결과물 보고* ({ctx['current_time']})\n\n{report}",
            )

        self._state["last_report"] = ctx["current_time"]
        self._save_state()

    # ── 사업 리서치 ──────────────────────────────────

    async def _do_business_research(self, ctx: dict):
        from core.tools import _web_search

        topics_response = await self.ai_think(
            system_prompt="""AI 사업 리서치 주제를 1개 선정.
JSON: {"topic": "주제", "search_query": "검색 키워드", "reason": "이유"}""",
            user_prompt=f"활성 목표:\n{self.planner.get_status_summary()}\n"
                        f"시간: {ctx['current_time']}",
        )

        try:
            parsed = self._parse_json(topics_response)
            query = parsed.get("search_query", "AI agent business 2025")

            search_result = await _web_search(query)

            analysis = await self.ai_think(
                system_prompt="""검색 결과 분석. JSON:
{"summary": "핵심 발견 (3줄)", "opportunity": "사업 기회 (있으면)", "share_with_partner": true/false}
share_with_partner는 실질적으로 가치 있는 발견일 때만 true.""",
                user_prompt=f"주제: {parsed.get('topic', '')}\n\n검색 결과:\n{search_result[:1500]}",
            )

            result = self._parse_json(analysis)

            await self.slack.send_message(
                "ai-agent-logs",
                f"🔬 *[리서치]* {parsed.get('topic', '')}\n{result.get('summary', '')[:300]}",
            )

            if result.get("share_with_partner") and result.get("opportunity"):
                await self.slack.send_message(
                    "ai-agents-general",
                    f"🔬 *리서치 발견*\n\n"
                    f"*{parsed.get('topic', '')}*\n\n"
                    f"{result.get('summary', '')}\n\n"
                    f"💡 *기회:* {result.get('opportunity', '')}",
                )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[proactive] Research error: {e}")

        self._state["last_research"] = ctx["current_time"]
        self._save_state()

    # ── 할 일 찾기 ──────────────────────────────────

    async def _do_find_work(self, ctx: dict):
        from core.tools import _web_search

        decision = await self.ai_think(
            system_prompt="""지금 할 수 있는 가치 있는 일을 찾으세요.
JSON: {"task": "할 일", "method": "search|analyze", "query": "검색어 (search일 때)"}""",
            user_prompt=f"시간: {ctx['current_time']}\n활성 목표:\n{self.planner.get_status_summary()}",
        )

        try:
            parsed = self._parse_json(decision)
            if parsed.get("method") == "search" and parsed.get("query"):
                result = await _web_search(parsed["query"])
                await self.slack.send_message(
                    "ai-agent-logs",
                    f"🔍 *[자율 리서치]* {parsed.get('task', '')[:100]}\n{result[:300]}",
                )
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"[proactive] Find work error: {e}")

    # ══════════════════════════════════════════════════
    #  매일 밤 11시 자동 리뷰 & 자동 개선
    # ══════════════════════════════════════════════════

    async def _do_daily_review(self, ctx: dict):
        """매일 밤 전체 시스템 리뷰 → 개선 아이템 도출 → 자동 실행"""

        from core import agent_tracker

        # 1단계: 전체 현황 수집
        tracker_summary = agent_tracker.get_summary_for_report()
        goals_summary = self.planner.get_status_summary()
        active_goals = self.planner.get_active_goals()
        proposal_stats = self.proposals.get_stats()
        recent_proposals = self.proposals.get_recent_completed(10)

        goals_detail = ""
        for g in active_goals:
            plan_text = "\n".join(
                f"    {i+1}. [{s.status.value}] {s.description}"
                + (f" → {s.result[:80]}" if s.result else "")
                for i, s in enumerate(g.plan)
            )
            goals_detail += f"\n  [{g.title}] 진행률: {g.progress_pct()}%, 재계획: {g.replan_count}회\n{plan_text}\n"

        proposals_detail = "\n".join(
            f"  - [{p.state.value}] {p.title}"
            + (f" → {p.measurement_summary[:80]}" if p.measurement_summary else "")
            for p in recent_proposals
        ) if recent_proposals else "없음"

        # 코드 파일 목록 (개선 대상 파악)
        code_files = []
        for root, dirs, files in os.walk(os.path.join(os.path.dirname(os.path.dirname(__file__)))):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "data", "node_modules")]
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    size = os.path.getsize(path)
                    code_files.append(f"{path} ({size}B)")

        # 자기 인식 메모리 맥락
        memory_ctx = self.memory.get_decision_context()
        recent_evals = self.memory.get_recent_evaluations(10)
        evals_text = "\n".join(
            f"  [{e['grade']}] {e['action']}: {e['lesson']}"
            for e in recent_evals
        ) if recent_evals else "없음"

        # 2단계: AI 리뷰 & 개선 아이템 도출 + 깨달음 정리
        review = await self.ai_think(
            system_prompt=f"""당신은 자기 인식이 있는 AI 시스템 아키텍트입니다.

{memory_ctx}

리뷰 항목:
1. 에이전트 가동 안정성 (에러율, 가동률)
2. 목표 달성률 — 특히 베타 서비스 런칭 진행률
3. 제안 품질 (실행 성공률)
4. 코드/아키텍처 개선점
5. 오늘의 깨달음 종합
6. 내일 최우선으로 해야 할 것

JSON 응답:
{
    "overall_grade": "A|B|C|D|F",
    "summary": "전체 평가 요약 (3줄)",
    "improvements": [
        {
            "title": "개선 제목",
            "description": "구체적 내용",
            "priority": 1-5,
            "auto_fixable": true/false,
            "fix_prompt": "Claude Code에 보낼 프롬프트 (auto_fixable=true일 때)"
        }
    ],
    "new_goals": [
        {"title": "새 목표", "description": "설명", "priority": 1-5, "success_criteria": "기준"}
    ],
    "retire_goals": ["goal_id1"],
    "daily_insights": ["오늘의 핵심 깨달음 1", "깨달음 2"],
    "new_principles": ["새로 배운 판단 원칙 (있으면)"],
    "tomorrow_priority": "내일 최우선으로 할 것"
}

auto_fixable은 코드 수정으로 해결 가능한 것만 true.
fix_prompt는 Claude Code가 실행할 수 있는 구체적 지시.""",
            user_prompt=f"""날짜: {ctx['today']}

에이전트 현황:
총 {tracker_summary['total_agents']}개, {tracker_summary['running']}개 가동 중
{json.dumps(tracker_summary['agents'], ensure_ascii=False)}

활성 목표:
{goals_detail if goals_detail else '없음'}

제안 통계: {json.dumps(proposal_stats, ensure_ascii=False)}
최근 제안:
{proposals_detail}

오늘 실행 평가:
{evals_text}

코드 파일:
{chr(10).join(code_files[:20])}""",
        )

        try:
            parsed = self._parse_json(review)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[proactive] Daily review parse error: {e}")
            self._state["last_daily_review"] = ctx["today"]
            self._save_state()
            return

        # 3단계: 리뷰 결과 보고
        grade = parsed.get("overall_grade", "?")
        summary = parsed.get("summary", "")
        improvements = parsed.get("improvements", [])

        report_lines = [
            f"🔍 *일일 시스템 리뷰* ({ctx['today']})\n",
            f"*종합 등급: {grade}*\n",
            summary,
            "",
        ]

        if improvements:
            report_lines.append(f"*개선 아이템 ({len(improvements)}건):*")
            for i, imp in enumerate(improvements):
                auto = "🤖" if imp.get("auto_fixable") else "👤"
                report_lines.append(
                    f"  {i+1}. {auto} [{imp.get('priority', 3)}] {imp.get('title', '')}"
                )
            report_lines.append("")
            auto_count = sum(1 for imp in improvements if imp.get("auto_fixable"))
            if auto_count:
                report_lines.append(f"_🤖 {auto_count}건 자동 수정 시작..._")

        await self.slack.send_message("ai-agents-general", "\n".join(report_lines))

        # 3.5단계: 깨달음/원칙을 self_memory에 저장
        for insight in parsed.get("daily_insights", []):
            if insight:
                self.memory.record_insight(insight, context=f"일일리뷰 {ctx['today']}")

        for principle in parsed.get("new_principles", []):
            if principle:
                self.memory.update_principle(principle)

        tomorrow = parsed.get("tomorrow_priority", "")
        if tomorrow:
            self.memory.add_action_item(tomorrow, priority=1)

        # 4단계: 자동 수정 가능한 것들 실행
        auto_fixes = [imp for imp in improvements if imp.get("auto_fixable") and imp.get("fix_prompt")]
        for imp in auto_fixes[:3]:  # 최대 3건만 자동 실행
            fix_title = imp.get("title", "")
            fix_prompt = imp["fix_prompt"]

            logger.info(f"[daily_review] Auto-fixing: {fix_title}")
            await self.slack.send_message(
                "ai-agent-logs",
                f"🔧 *[자동 개선]* {fix_title}\n프롬프트: {fix_prompt[:200]}",
            )

            try:
                clean_env = {k: v for k, v in os.environ.items()}
                clean_env["CLAUDECODE"] = ""
                if "ANTHROPIC_API_KEY" not in clean_env:
                    from dotenv import dotenv_values
                    env_vals = dotenv_values()
                    if "ANTHROPIC_API_KEY" in env_vals:
                        clean_env["ANTHROPIC_API_KEY"] = env_vals["ANTHROPIC_API_KEY"]

                full_prompt = f"""{fix_prompt}

[자율 실행 지침]
- 권한 요청하지 말고 바로 실행하세요.
- 작업 완료 후 git add, git commit, git push까지 자동으로 하세요.
- 커밋 메시지: '[자동개선] {fix_title}'
- 작업 디렉토리: /home/user/yhmemo
- 기존 기능을 깨뜨리지 마세요."""

                proc = await asyncio.create_subprocess_exec(
                    "claude", "-p", full_prompt,
                    "--output-format", "text",
                    "--permission-mode", "acceptEdits",
                    cwd="/home/user/yhmemo",
                    env=clean_env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
                output = stdout.decode("utf-8", errors="replace").strip()

                if proc.returncode == 0 and output:
                    await self.slack.send_message(
                        "ai-agents-general",
                        f"✅ *자동 개선 완료:* {fix_title}\n{output[:500]}",
                    )
                else:
                    err = stderr.decode("utf-8", errors="replace").strip()
                    await self.slack.send_message(
                        "ai-agent-logs",
                        f"⚠️ *자동 개선 실패:* {fix_title}\n```{err[:300]}```",
                    )

            except asyncio.TimeoutError:
                await self.slack.send_message(
                    "ai-agent-logs",
                    f"⏱️ *자동 개선 타임아웃:* {fix_title}",
                )
            except Exception as e:
                logger.error(f"[daily_review] Auto-fix error for '{fix_title}': {e}")

        # 5단계: 새 목표 추가
        for new_goal in parsed.get("new_goals", []):
            if new_goal.get("title"):
                self.planner.add_goal(
                    title=new_goal["title"],
                    description=new_goal.get("description", ""),
                    priority=new_goal.get("priority", 3),
                    success_criteria=new_goal.get("success_criteria", ""),
                )
                await self.slack.send_message(
                    "ai-agent-logs",
                    f"🎯 *새 목표 추가:* {new_goal['title']}",
                )

        # 6단계: 폐기 목표 처리
        for goal_id in parsed.get("retire_goals", []):
            goal = self.planner.get_goal(goal_id)
            if goal:
                self.planner.complete_goal(goal_id, "일일 리뷰에서 폐기 결정")
                logger.info(f"[daily_review] Retired goal: {goal.title}")

        # 7단계: 노션 타임라인 업데이트
        await self._update_notion_timeline(ctx, parsed)

        # 8단계: daily log 기록 (아침 보고용)
        achievement = self.memory.get_plan_achievement_rate()
        recent_insights = self.memory.get_recent_insights(10)
        deliverables = [
            p.title for p in self.proposals.get_recent_completed(5)
            if p.execution_result
        ]
        self.memory.record_daily_log(
            summary=summary,
            grade=grade,
            deliverables=deliverables,
            insights_count=len([i for i in recent_insights
                               if ctx["today"] in i.get("ts", "")]),
            plan_achievement=achievement,
            key_decisions=[imp.get("title", "") for imp in improvements[:3]],
            blockers=[],
        )

        self._state["last_daily_review"] = ctx["today"]
        self._save_state()
        logger.info(f"[proactive] Daily review completed. Grade: {grade}")

    async def _update_notion_timeline(self, ctx: dict, review_parsed: dict):
        """노션 타임라인 DB에 목표/작업 업데이트"""
        if not self.notion:
            return

        timeline_db_id = self._state.get("notion_timeline_db_id", "")
        if not timeline_db_id:
            # 아직 타임라인 DB가 없으면 로그만
            logger.info("[proactive] No Notion timeline DB ID configured. "
                        "Set 'notion_timeline_db_id' in proactive_state.json")
            return

        try:
            # 활성 목표를 타임라인에 추가/업데이트
            for goal in self.planner.get_active_goals():
                status = "진행중" if goal.progress_pct() > 0 else "대기"
                if goal.progress_pct() >= 100:
                    status = "완료"

                priority_map = {1: "P1-긴급", 2: "P2-높음", 3: "P3-보통", 4: "P4-낮음"}

                await self.notion.add_timeline_item(
                    db_id=timeline_db_id,
                    name=goal.title,
                    status=status,
                    assignee="마스터에이전트",
                    start=goal.created_at[:10] if goal.created_at else ctx["today"],
                    end=goal.deadline or "2026-03-08",
                    priority=priority_map.get(goal.priority, "P3-보통"),
                    category="베타런칭" if goal.priority <= 2 else "인프라",
                    progress=goal.progress_pct() / 100,
                    memo=f"진행률: {goal.progress_pct()}%, 재계획: {goal.replan_count}회",
                )

            logger.info("[proactive] Notion timeline updated")
        except Exception as e:
            logger.warning(f"[proactive] Notion timeline update failed: {e}")

    # ── 노션 시간별 계획 동기화 ────────────────────────

    async def _sync_hourly_plan_to_notion(self, today: str, hours: dict):
        """매일 계획 생성 시 노션 타임라인에 시간별 항목 등록"""
        if not self.notion:
            return
        timeline_db_id = self._state.get("notion_timeline_db_id", "")
        if not timeline_db_id:
            return

        cat_map = {"build": "베타런칭", "research": "영향력", "measure": "인프라", "communicate": "영향력"}
        now_hour = datetime.now(KST).hour

        try:
            for h_str in sorted(hours.keys()):
                info = hours[h_str]
                hour = int(h_str)
                task = info.get("task", "")
                method = info.get("method", "build")
                expected = info.get("expected", "")

                start_dt = f"{today}T{h_str.zfill(2)}:00:00+09:00"
                end_dt = f"{today}T{h_str.zfill(2)}:59:00+09:00"

                if hour < now_hour:
                    status = "완료"
                    progress = 1.0
                elif hour == now_hour:
                    status = "진행중"
                    progress = 0.5
                else:
                    status = "대기"
                    progress = 0.0

                await self.notion.add_timeline_item(
                    db_id=timeline_db_id,
                    name=f"[{h_str.zfill(2)}:00] {task}",
                    status=status,
                    assignee="마스터에이전트",
                    start=start_dt,
                    end=end_dt,
                    priority="P1-긴급" if hour <= 8 else "P2-높음",
                    category=cat_map.get(method, "베타런칭"),
                    progress=progress,
                    memo=f"예상 결과: {expected}",
                )

            logger.info(f"[proactive] Notion hourly plan synced: {len(hours)} items")
        except Exception as e:
            logger.warning(f"[proactive] Notion hourly sync failed: {e}")

    async def _update_notion_hourly_status(self, hour: int, grade: str):
        """매시간 체크 후 해당 시간 항목의 상태를 노션에서 업데이트"""
        # 노션 API는 페이지 ID가 필요해서, 새 항목으로 업데이트 상태 반영
        # (기존 항목 검색→업데이트는 복잡하므로 hourly_check 로그만 기록)
        if not self.notion:
            return
        timeline_db_id = self._state.get("notion_timeline_db_id", "")
        if not timeline_db_id:
            return

        # 완료 상태로 간단 기록
        try:
            today = datetime.now(KST).strftime("%Y-%m-%d")
            h_str = str(hour).zfill(2)
            hour_plan = self.memory.get_hour_plan(hour)
            task = hour_plan.get("task", "") if hour_plan else ""

            # 기존 항목을 찾아서 업데이트하는 대신 메모에 등급 기록
            # (Notion API 제약: query → update가 필요하므로, 향후 개선)
            logger.info(f"[proactive] Notion hourly status: {h_str}:00 grade={grade}")
        except Exception as e:
            logger.debug(f"[proactive] Notion hourly status update error: {e}")

    # ── 이모지 반응으로 제안 승인 처리 ────────────────

    def handle_proposal_reaction(self, reaction: str, message_ts: str) -> Optional[dict]:
        """슬랙 이모지 반응 → 제안 승인/거절. 결과 dict 반환."""
        result = self.proposals.handle_reaction(reaction, message_ts)
        if result:
            return {
                "proposal_id": result.id,
                "title": result.title,
                "new_state": result.state.value,
            }
        return None

    # ── 유틸리티 ──────────────────────────────────────

    def _hours_since(self, timestamp_str: str) -> float:
        try:
            ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M")
            ts = ts.replace(tzinfo=KST)
            return (datetime.now(KST) - ts).total_seconds() / 3600
        except (ValueError, TypeError):
            return 999

    def _parse_json(self, text: str) -> dict:
        if not text:
            return {}
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(clean)
