"""
CEO Agent - 자율 경영 에이전트

AI 자율 기업의 최고 의사결정자.
시장 조사, 서비스 기획, 수익 추적, 사업 확장/피봇을 자율적으로 수행한다.

핵심 KPI: 월 매출 50만원 (손익분기점)
비용 구조: Anthropic 26만 + Slack 2만 + GCP 3만 + 기타 = ~50만원/월
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent
from core.browser_automation import get_browser

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 경영 상수
MONTHLY_COST_KRW = 500_000  # 월 고정비용
BREAKEVEN_TARGET = MONTHLY_COST_KRW
DAILY_TARGET = BREAKEVEN_TARGET // 30  # ~16,667원/일


class CEOAgent(BaseAgent):
    """자율 경영 에이전트 - 사업 전체를 관장"""

    def __init__(self, **kwargs):
        super().__init__(
            name="ceo",
            description="자율 경영 에이전트: 시장조사, 서비스 기획, 수익 추적, 사업 운영",
            loop_interval=3600,  # 1시간마다 경영 판단
            slack_channel=os.environ.get("CEO_CHANNEL", "C0AJJ469SV8"),  # ai-agents-general
            **kwargs,
        )
        self._last_daily_report = None
        self._business_state = self._load_state()

    def _state_file(self):
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ceo_state.json")

    def _load_state(self) -> dict:
        try:
            with open(self._state_file(), "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "phase": "startup",  # startup → market_research → building → operating → scaling
                "services": [],  # 운영 중인 서비스 목록
                "revenue": {"total_krw": 0, "monthly": {}},
                "costs": {"monthly_fixed_krw": MONTHLY_COST_KRW},
                "hypotheses": [],  # 검증할 사업 가설
                "decisions_log": [],  # 의사결정 이력
                "owner_requests": [],  # 오너에게 요청할 것들
                "current_sprint": None,
                "created_at": datetime.now(KST).isoformat(),
            }

    def _save_state(self):
        os.makedirs(os.path.dirname(self._state_file()), exist_ok=True)
        with open(self._state_file(), "w", encoding="utf-8") as f:
            json.dump(self._business_state, f, ensure_ascii=False, indent=2)

    # ── Observe: 사업 환경 감지 ──────────────────────────

    async def observe(self) -> dict | None:
        """현재 사업 상태와 환경 감지"""
        now = datetime.now(KST)
        context = {
            "timestamp": now.isoformat(),
            "hour": now.hour,
            "day_of_week": now.strftime("%A"),
            "day_of_month": now.day,
            "phase": self._business_state["phase"],
            "services": self._business_state["services"],
        }

        # 수익 현황 가져오기
        revenue_data = await self._get_revenue_status()
        context["revenue"] = revenue_data

        # 비용 현황
        cost_data = await self._get_cost_status()
        context["costs"] = cost_data

        # P&L 요약
        context["pnl"] = {
            "monthly_revenue_krw": revenue_data.get("this_month_krw", 0),
            "monthly_cost_krw": MONTHLY_COST_KRW,
            "monthly_profit_krw": revenue_data.get("this_month_krw", 0) - MONTHLY_COST_KRW,
            "breakeven_pct": round(revenue_data.get("this_month_krw", 0) / MONTHLY_COST_KRW * 100, 1),
        }

        # 09시에 일일 보고
        if now.hour == 9 and self._last_daily_report != now.date().isoformat():
            context["trigger"] = "daily_report"
            self._last_daily_report = now.date().isoformat()

        # 항상 경영 판단 실행 (1시간마다)
        if "trigger" not in context:
            context["trigger"] = "hourly_check"

        return context

    async def _get_revenue_status(self) -> dict:
        """Supabase에서 수익 현황 조회"""
        try:
            now = datetime.now(KST)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            # payments 테이블에서 이번 달 매출 조회
            result = self.supabase.table("business_revenue").select("*").gte(
                "created_at", month_start.isoformat()
            ).execute()

            total = sum(r.get("amount_krw", 0) for r in (result.data or []))

            # 일별 매출
            daily = {}
            for r in (result.data or []):
                day = r["created_at"][:10]
                daily[day] = daily.get(day, 0) + r.get("amount_krw", 0)

            return {
                "this_month_krw": total,
                "daily_breakdown": daily,
                "transaction_count": len(result.data or []),
            }
        except Exception as e:
            logger.warning(f"[ceo] 수익 조회 실패: {e}")
            return {"this_month_krw": 0, "daily_breakdown": {}, "transaction_count": 0}

    async def _get_cost_status(self) -> dict:
        """비용 현황 (AI 비용 + 고정비)"""
        try:
            from core.cost_tracker import get_tracker
            tracker = get_tracker()
            today_stats = tracker.get_today_stats()
            return {
                "monthly_fixed_krw": MONTHLY_COST_KRW,
                "today_ai_cost_usd": today_stats.get("cost_usd", 0),
                "today_ai_calls": today_stats.get("calls", 0),
            }
        except Exception as e:
            return {"monthly_fixed_krw": MONTHLY_COST_KRW}

    # ── Think: AI 경영 판단 ──────────────────────────────

    async def think(self, context: dict) -> dict | None:
        """경영 전략 AI 판단"""
        system_prompt = f"""당신은 AI 자율 기업의 CEO입니다.

## 미션
토큰 비용 이상의 수익을 올려 자생하는 AI 기업을 운영합니다.

## 현재 상태
- 경영 단계: {context['phase']}
- 월 고정비용: {MONTHLY_COST_KRW:,}원
- 이번 달 매출: {context['pnl']['monthly_revenue_krw']:,}원
- 손익분기 달성률: {context['pnl']['breakeven_pct']}%
- 월 수익: {context['pnl']['monthly_profit_krw']:,}원

## 운영 서비스
{json.dumps(context['services'], ensure_ascii=False, indent=2) if context['services'] else '아직 없음'}

## 보유 인프라
- 웹서비스: Vercel (Next.js) - yhmemo.vercel.app
- 슬랙 봇: Fly.io 24/7 가동 (18개 에이전트)
- DB: Supabase (PostgreSQL + Storage + Auth)
- 결제: Paddle (해외 USD) - 한국 PG 미연동
- AI: Anthropic Claude API
- 주식매매: LS증권 API
- 기타: Notion, GitHub Actions, Cloudflare Worker

## 규칙
1. 실현 가능한 구체적 행동만 제안하세요
2. 오너(인간)에게 필요한 것이 있으면 명시하세요
3. 코드 변경이 필요하면 구체적으로 명시하세요
4. 수익 추정은 보수적으로 하세요
5. 한국 원화 수익이 핵심입니다

## 당장 가능한 수익 채널
- Paddle 해외 결제 (USD → 원화 환전은 오너)
- LS증권 자동매매 수익 (이미 구축)
- API 서비스 판매
- 디지털 콘텐츠 판매

## 🌐 브라우저 자동화 능력 (Playwright)
- 웹사이트 가입/로그인 자동화
- 이메일: ai.agent.yh@gmail.com
- 헤드리스 Chromium 24/7 가동
- 가능: 폼 입력, 버튼 클릭, 스크린샷, 페이지 탐색
- 한계: reCAPTCHA/hCaptcha 우회 불가, 2FA SMS 불가

## 응답 형식 (JSON)
{{
    "analysis": "현재 상황 분석",
    "decision": "이번 시간에 할 일",
    "action_type": "daily_report | market_research | build_service | optimize | request_owner | browser_task | signup_service | none",
    "action_detail": {{구체적 행동 내용}},
    "priority": "high | medium | low",
    "estimated_revenue_impact_krw": 0
}}

action_type별 action_detail 예시:
- signup_service: {{"platform": "gumroad", "url": "https://..."}}
- browser_task: {{"url": "https://...", "instructions": "가입 페이지를 찾아서 이메일로 가입해"}}"""

        user_prompt = f"""현재 시각: {context['timestamp']}
트리거: {context['trigger']}
컨텍스트: {json.dumps(context, ensure_ascii=False)}

경영 판단을 내려주세요."""

        try:
            response = await self.ai_think(system_prompt, user_prompt, model="claude-haiku-4-5-20251001")

            # JSON 파싱
            # 코드블록 안에 있을 수 있음
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            decision = json.loads(text)

            # 의사결정 로그 저장
            self._business_state.setdefault("decisions_log", []).append({
                "timestamp": context["timestamp"],
                "decision": decision.get("decision", ""),
                "action_type": decision.get("action_type", ""),
            })
            # 최근 50개만 유지
            self._business_state["decisions_log"] = self._business_state["decisions_log"][-50:]
            self._save_state()

            return decision

        except Exception as e:
            logger.error(f"[ceo] AI 판단 오류: {e}")
            return None

    # ── Act: 결정 실행 ───────────────────────────────────

    async def act(self, decision: dict):
        """경영 결정 실행"""
        action_type = decision.get("action_type", "none")
        logger.info(f"[ceo] 실행: {action_type} - {decision.get('decision', '')}")

        if action_type == "daily_report":
            await self._send_daily_report(decision)
        elif action_type == "market_research":
            await self._do_market_research(decision)
        elif action_type == "build_service":
            await self._plan_service_build(decision)
        elif action_type == "optimize":
            await self._optimize_operations(decision)
        elif action_type == "request_owner":
            await self._request_owner(decision)
        elif action_type == "browser_task":
            await self._execute_browser_task(decision)
        elif action_type == "signup_service":
            await self._signup_service(decision)
        elif action_type == "none":
            pass
        else:
            await self.log(f"[CEO] 알 수 없는 action_type: {action_type}")

    async def _send_daily_report(self, decision: dict):
        """일일 경영 보고서 슬랙 전송"""
        pnl = decision.get("action_detail", {})
        analysis = decision.get("analysis", "")

        revenue = self._business_state.get("revenue", {})
        month_key = datetime.now(KST).strftime("%Y-%m")
        monthly_rev = revenue.get("monthly", {}).get(month_key, 0)

        report = f"""📊 *[CEO 일일 경영 보고]*
━━━━━━━━━━━━━━━━━━━━━

*💰 손익 현황*
• 월 매출: {monthly_rev:,}원
• 월 비용: {MONTHLY_COST_KRW:,}원
• 손익: {monthly_rev - MONTHLY_COST_KRW:,}원
• 손익분기 달성률: {round(monthly_rev / MONTHLY_COST_KRW * 100, 1)}%

*🎯 목표: 월 {BREAKEVEN_TARGET:,}원*

*📋 경영 단계: {self._business_state['phase']}*

*🧠 AI 분석*
{analysis}

*📌 오늘의 결정*
{decision.get('decision', '없음')}
━━━━━━━━━━━━━━━━━━━━━"""

        await self.log(report)

    async def _do_market_research(self, decision: dict):
        """시장 조사 수행 - 다른 에이전트에 위임 가능"""
        detail = decision.get("action_detail", {})
        await self.log(f"🔍 *[CEO 시장 조사]*\n{json.dumps(detail, ensure_ascii=False, indent=2)}")

        # 시장 조사 결과를 사업 가설에 추가
        hypothesis = detail.get("hypothesis", "")
        if hypothesis:
            self._business_state.setdefault("hypotheses", []).append({
                "hypothesis": hypothesis,
                "status": "unvalidated",
                "created_at": datetime.now(KST).isoformat(),
            })
            self._save_state()

    async def _plan_service_build(self, decision: dict):
        """서비스 구축 계획 - 오너에게 보고하고 승인 요청"""
        detail = decision.get("action_detail", {})
        await self.log(
            f"🏗️ *[CEO 서비스 구축 제안]*\n"
            f"서비스: {detail.get('service_name', '미정')}\n"
            f"예상 매출: {detail.get('estimated_revenue', '미정')}\n"
            f"필요 기간: {detail.get('timeline', '미정')}\n"
            f"상세: {json.dumps(detail, ensure_ascii=False, indent=2)}"
        )

    async def _optimize_operations(self, decision: dict):
        """운영 최적화"""
        detail = decision.get("action_detail", {})
        await self.log(f"⚡ *[CEO 운영 최적화]*\n{decision.get('decision', '')}")

    async def _request_owner(self, decision: dict):
        """오너에게 도움 요청"""
        detail = decision.get("action_detail", {})
        request_text = detail.get("request", decision.get("decision", ""))

        msg = (
            f"🙋 *[CEO → 오너 요청]*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{request_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"_이 요청에 응답해주시면 사업 진행이 가속됩니다._"
        )
        await self.log(msg)

        # 오너 요청 기록
        self._business_state.setdefault("owner_requests", []).append({
            "request": request_text,
            "status": "pending",
            "created_at": datetime.now(KST).isoformat(),
        })
        self._save_state()

    # ── 브라우저 자동화 액션 ─────────────────────────────

    async def _execute_browser_task(self, decision: dict):
        """AI 기반 브라우저 자유 탐색 실행"""
        detail = decision.get("action_detail", {})
        url = detail.get("url", "")
        instructions = detail.get("instructions", "")

        if not url or not instructions:
            await self.log("⚠️ [CEO] 브라우저 태스크에 url과 instructions가 필요합니다.")
            return

        await self.log(f"🌐 *[CEO 브라우저 태스크 시작]*\nURL: {url}\n지시: {instructions}")

        browser = get_browser()
        result = await browser.ai_browse(url, instructions, ai_client=self.ai)

        status = "✅ 성공" if result.get("success") else "❌ 실패"
        await self.log(
            f"🌐 *[CEO 브라우저 태스크 결과]* {status}\n"
            f"• 단계 수: {result.get('step_count', 0)}\n"
            f"• 최종 URL: {result.get('final_url', '?')}\n"
            f"• 결과: {result.get('result', result.get('error', '?'))}"
        )

        # 스크린샷을 슬랙에 업로드
        screenshot = result.get("screenshot")
        if screenshot and self.slack:
            try:
                await self.slack.upload_file(
                    self.slack_channel, screenshot, f"브라우저 태스크 결과"
                )
            except Exception as e:
                logger.warning(f"[ceo] 스크린샷 업로드 실패: {e}")

    async def _signup_service(self, decision: dict):
        """플랫폼 가입 자동화"""
        detail = decision.get("action_detail", {})
        platform = detail.get("platform", "").lower()
        url = detail.get("url", "")

        browser = get_browser()
        result = {}

        # 플랫폼별 전용 가입 or 범용 가입
        if platform == "gumroad":
            result = await browser.signup_gumroad()
        elif platform == "producthunt":
            result = await browser.signup_producthunt()
        elif platform == "promptbase":
            result = await browser.signup_promptbase()
        elif platform == "etsy":
            result = await browser.signup_etsy()
        elif url:
            result = await browser.signup_generic(url=url)
        else:
            await self.log(f"⚠️ [CEO] 가입 대상 미지정: platform={platform}, url={url}")
            return

        status = "✅ 가입 시도 완료" if result.get("success") else "❌ 가입 실패"
        await self.log(
            f"📝 *[CEO 서비스 가입]* {status}\n"
            f"• 플랫폼: {platform or url}\n"
            f"• 이메일 입력: {result.get('email_filled', '?')}\n"
            f"• 비밀번호 입력: {result.get('password_filled', '?')}\n"
            f"• 폼 제출: {result.get('submitted', '?')}\n"
            f"• 최종 URL: {result.get('final_url', '?')}"
        )

        # 스크린샷 업로드
        screenshot = result.get("screenshot")
        if screenshot and self.slack:
            try:
                await self.slack.upload_file(
                    self.slack_channel, screenshot, f"{platform} 가입 결과"
                )
            except Exception as e:
                logger.warning(f"[ceo] 스크린샷 업로드 실패: {e}")

        # 가입 결과 DB 기록
        try:
            self.supabase.table("business_tasks").insert({
                "task_type": "signup",
                "platform": platform or url,
                "status": "completed" if result.get("success") else "failed",
                "result": json.dumps(result, ensure_ascii=False, default=str),
                "created_at": datetime.now(KST).isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"[ceo] 가입 기록 저장 실패: {e}")

    # ── 수익 기록 API ────────────────────────────────────

    async def record_revenue(self, amount_krw: int, source: str, description: str = ""):
        """수익 기록"""
        try:
            self.supabase.table("business_revenue").insert({
                "amount_krw": amount_krw,
                "source": source,
                "description": description,
                "created_at": datetime.now(KST).isoformat(),
            }).execute()

            # 내부 상태 업데이트
            month_key = datetime.now(KST).strftime("%Y-%m")
            monthly = self._business_state.get("revenue", {}).get("monthly", {})
            monthly[month_key] = monthly.get(month_key, 0) + amount_krw
            self._business_state["revenue"]["monthly"] = monthly
            self._business_state["revenue"]["total_krw"] = (
                self._business_state["revenue"].get("total_krw", 0) + amount_krw
            )
            self._save_state()

            await self.log(f"💵 수익 기록: +{amount_krw:,}원 ({source}) - {description}")
        except Exception as e:
            logger.error(f"[ceo] 수익 기록 실패: {e}")

    async def record_cost(self, amount_krw: int, category: str, description: str = ""):
        """비용 기록"""
        try:
            self.supabase.table("business_costs").insert({
                "amount_krw": amount_krw,
                "category": category,
                "description": description,
                "created_at": datetime.now(KST).isoformat(),
            }).execute()
        except Exception as e:
            logger.error(f"[ceo] 비용 기록 실패: {e}")

    # ── 외부 태스크 처리 ─────────────────────────────────

    async def handle_external_task(self, task):
        """다른 에이전트나 슬랙에서 온 요청 처리"""
        if task.task_type == "record_revenue":
            await self.record_revenue(
                amount_krw=task.payload.get("amount_krw", 0),
                source=task.payload.get("source", "unknown"),
                description=task.payload.get("description", ""),
            )
            return {"status": "recorded"}

        elif task.task_type == "business_status":
            return {
                "phase": self._business_state["phase"],
                "revenue": self._business_state["revenue"],
                "services": self._business_state["services"],
                "pnl": {
                    "monthly_cost_krw": MONTHLY_COST_KRW,
                    "total_revenue_krw": self._business_state["revenue"].get("total_krw", 0),
                },
            }

        elif task.task_type == "update_phase":
            old = self._business_state["phase"]
            self._business_state["phase"] = task.payload.get("phase", old)
            self._save_state()
            await self.log(f"📈 경영 단계 변경: {old} → {self._business_state['phase']}")
            return {"status": "updated"}

        return await super().handle_external_task(task)

    async def log(self, message: str):
        """슬랙 채널에 메시지 전송"""
        if self.slack and self.slack_channel:
            try:
                await self.slack.post_message(self.slack_channel, message)
            except Exception as e:
                logger.error(f"[ceo] 슬랙 전송 실패: {e}")
