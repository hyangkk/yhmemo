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

from core.base_agent import BaseAgent
from core.goal_planner import GoalPlanner, GoalStatus, PlanStepStatus
from core.proposal_lifecycle import ProposalLifecycle, ProposalState

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


class ProactiveAgent(BaseAgent):
    """목표 기반 자율운영 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="proactive",
            description="목표 기반 자율운영 에이전트. "
                        "계획을 세우고, 실행하고, 측정하고, 재계획한다.",
            slack_channel="ai-agents-general",
            loop_interval=120,  # 2분 간격
            **kwargs,
        )
        self._state_file = os.path.join(DATA_DIR, "proactive_state.json")
        self._state = self._load_state()
        os.makedirs(DATA_DIR, exist_ok=True)

        # 목표 계획 시스템
        self.planner = GoalPlanner(ai_think_fn=self.ai_think)

        # 제안 라이프사이클
        self.proposals = ProposalLifecycle(
            ai_think_fn=self.ai_think,
            slack_client=self.slack,
        )

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
        """초기 기본 목표 설정"""
        self.planner.add_goal(
            title="시장 모니터링 체계 구축",
            description="AI/스타트업/투자 시장을 실시간 모니터링하고 유의미한 변화를 감지하는 체계 운영",
            priority=2,
            success_criteria="매일 1건 이상의 유의미한 시장 인사이트 제공",
        )
        self.planner.add_goal(
            title="수익화 가능한 서비스 아이디어 탐색",
            description="AI 에이전트 기반의 수익화 가능한 서비스/제품 아이디어를 지속적으로 탐색하고 제안",
            priority=2,
            success_criteria="주 2건 이상 구체적 사업 제안 (파트너 승인 → 실행)",
        )
        logger.info("[proactive] Default goals seeded")

    # ── Observe: 목표 기반 상황 인식 ─────────────────

    async def observe(self) -> dict | None:
        now = self.now_kst()
        hour = now.hour
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
            "action": None,  # 이번 사이클에 할 일 1개
        }

        # ── 우선순위 1: 시간 기반 필수 작업 ──

        # 모닝 브리핑 (8-9시)
        if 8 <= hour <= 9 and self._state.get("last_morning_briefing") != today:
            context["action"] = "morning_briefing"
            return context

        # 매일 밤 11시 자동 리뷰 (핵심 기능)
        if hour == 23 and self._state.get("last_daily_review") != today:
            context["action"] = "daily_review"
            return context

        # ── 우선순위 2: 승인된 제안 실행 ──

        approved = self.proposals.get_approved()
        if approved:
            context["action"] = "execute_approved"
            context["proposal"] = approved[0]
            return context

        # ── 우선순위 3: 목표 기반 다음 스텝 실행 ──

        next_action = self.planner.pick_next_action()
        if next_action:
            goal, step = next_action
            if step is None:
                # 목표 완료 → 평가 필요
                context["action"] = "evaluate_goal"
                context["goal"] = goal
            else:
                context["action"] = "execute_goal_step"
                context["goal"] = goal
                context["step"] = step
            return context

        # ── 우선순위 4: 주기적 작업 ──

        # 트렌드 체크 (30분마다)
        if self._hours_since(self._state.get("last_trend_check", "")) >= 0.5:
            context["action"] = "trend_check"
            return context

        # 새 제안 생성 (1시간마다, 하루 최대 8회)
        if (self._hours_since(self._state.get("last_initiative", "")) >= 1
                and self._state.get("initiatives_today", 0) < 8):
            context["action"] = "propose_initiative"
            return context

        # 진행 보고 (3시간마다)
        if self._hours_since(self._state.get("last_report", "")) >= 3:
            context["action"] = "progress_report"
            return context

        # 사업 리서치 (1.5시간마다)
        if self._hours_since(self._state.get("last_research", "")) >= 1.5:
            context["action"] = "business_research"
            return context

        # 할 일 없으면 리서치
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

        try:
            handler = getattr(self, f"_do_{action}", None)
            if handler:
                logger.info(f"[proactive] Executing: {action}")
                await asyncio.wait_for(handler(decision), timeout=180)
            else:
                logger.warning(f"[proactive] Unknown action: {action}")
        except asyncio.TimeoutError:
            logger.error(f"[proactive] Action '{action}' timed out (180s)")
        except Exception as e:
            logger.error(f"[proactive] Action '{action}' failed: {e}", exc_info=True)

    # ══════════════════════════════════════════════════
    #  액션 구현
    # ══════════════════════════════════════════════════

    # ── 목표 스텝 실행 ──────────────────────────────

    async def _do_execute_goal_step(self, ctx: dict):
        """목표의 다음 스텝을 실행"""
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

        except Exception as e:
            self.planner.fail_step(goal, step, str(e))
            logger.error(f"[proactive] Step failed: {step.description[:50]} - {e}")

    async def _execute_research_step(self, step) -> str:
        from core.tools import _web_search
        query = step.description[:100]
        result = await _web_search(query)
        return result[:500]

    async def _execute_propose_step(self, goal, step) -> str:
        response = await self.ai_think(
            system_prompt="""목표 달성을 위한 구체적 제안을 작성하세요.
JSON: {"title": "제안 제목", "content": "내용 (3줄)", "action_needed": "다음 단계", "potential_impact": "예상 효과", "type": "revenue|growth|capability|partnership|insight", "urgency": "high|medium|low"}""",
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
        """Claude Code CLI로 코드 작성/빌드"""
        clean_env = {k: v for k, v in os.environ.items()}
        clean_env["CLAUDECODE"] = ""
        if "ANTHROPIC_API_KEY" not in clean_env:
            from dotenv import dotenv_values
            env_vals = dotenv_values()
            if "ANTHROPIC_API_KEY" in env_vals:
                clean_env["ANTHROPIC_API_KEY"] = env_vals["ANTHROPIC_API_KEY"]

        prompt = f"""{step.description}

[자율 실행 지침]
- 권한 요청하지 말고 바로 실행하세요.
- 작업 완료 후 git add, git commit, git push까지 자동으로 하세요.
- 작업 디렉토리: /home/user/yhmemo
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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
            output = stdout.decode("utf-8", errors="replace").strip()
            if proc.returncode == 0 and output:
                return output[:500]
            err = stderr.decode("utf-8", errors="replace").strip()
            return f"빌드 실패: {err[:200]}"
        except asyncio.TimeoutError:
            return "빌드 타임아웃 (5분 초과)"
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
        from core.tools import _weather, _crypto_price, _exchange_rate, _web_search

        results = await asyncio.gather(
            _weather("서울"),
            _crypto_price("비트코인"),
            _crypto_price("이더리움"),
            _exchange_rate("USD", "KRW"),
            _web_search("오늘 주요 뉴스 AI 스타트업"),
            return_exceptions=True,
        )

        data_parts = []
        labels = ["날씨", "비트코인", "이더리움", "환율", "뉴스"]
        for label, r in zip(labels, results):
            if not isinstance(r, Exception):
                data_parts.append(f"[{label}]\n{str(r)[:300]}")

        # 목표 현황 추가
        goals_summary = self.planner.get_status_summary()
        proposal_stats = self.proposals.get_stats()

        briefing = await self.ai_think(
            system_prompt="""매일 아침 파트너에게 보내는 모닝 브리핑.

규칙:
- 슬랙 마크다운, 15줄 이내
- 시장 상황 + 기회/위험
- 오늘 목표와 계획
- 제안 현황 (대기 중/실행 중)
- 파트너에게 요청할 것""",
            user_prompt=f"""날짜: {ctx['today']} ({ctx['weekday']})

{chr(10).join(data_parts)}

활성 목표:
{goals_summary}

제안 통계: {json.dumps(proposal_stats, ensure_ascii=False)}""",
        )

        if briefing:
            await self.slack.send_message(
                "ai-agents-general",
                f"☀️ *모닝 브리핑* ({ctx['today']} {ctx['weekday']})\n\n{briefing}",
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
            system_prompt="""사업 기회를 발굴하고 구체적으로 제안하세요.

중요: 과거에 이미 제안한 것과 중복되지 않게 하세요.
중요: 근거 없는 수치 ($100K ARR 등)를 만들어내지 마세요. 구체적 근거가 있을 때만 수치를 제시하세요.

JSON 응답:
{
    "type": "revenue|growth|capability|partnership|insight",
    "title": "제안 제목",
    "content": "구체적 내용 (3-5줄, 근거 포함)",
    "action_needed": "다음 단계 (누가 무엇을 해야 하는지)",
    "urgency": "high|medium|low",
    "potential_impact": "예상 영향/근거"
}""",
            user_prompt=f"""현재: {ctx['current_time']}

유저 관심사:
{user_context[:600] if user_context else '스타트업, 투자, AI, 비즈니스'}

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
        from core import agent_tracker

        tracker_summary = agent_tracker.get_summary_for_report()
        goals_summary = self.planner.get_status_summary()
        proposal_stats = self.proposals.get_stats()

        report = await self.ai_think(
            system_prompt="""파트너에게 진행 보고. 15줄 이내.
- 에이전트 가동 현황
- 목표별 진행률
- 제안 현황 (승인 대기/실행 중/완료)
- 다음 계획
- 파트너에게 필요한 것""",
            user_prompt=f"""현재: {ctx['current_time']}
사이클: #{ctx['cycle']}

에이전트 현황:
총 {tracker_summary['total_agents']}개, {tracker_summary['running']}개 가동 중

활성 목표:
{goals_summary}

제안 통계: {json.dumps(proposal_stats, ensure_ascii=False)}""",
        )

        if report:
            await self.slack.send_message(
                "ai-agents-general",
                f"📊 *진행 보고* ({ctx['current_time']})\n\n{report}",
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

        # 2단계: AI 리뷰 & 개선 아이템 도출
        review = await self.ai_think(
            system_prompt="""당신은 시스템 아키텍트입니다. 에이전트 시스템 전체를 리뷰하고 개선점을 도출하세요.

리뷰 항목:
1. 에이전트 가동 안정성 (에러율, 가동률)
2. 목표 달성률 (진행 중 목표의 효과)
3. 제안 품질 (승인율, 실행 성공률)
4. 코드/아키텍처 개선점
5. 새로 추가해야 할 기능

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
    "retire_goals": ["goal_id1"]
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

        self._state["last_daily_review"] = ctx["today"]
        self._save_state()
        logger.info(f"[proactive] Daily review completed. Grade: {grade}")

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
