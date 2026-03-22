"""
시장 조사 에이전트

수익 기회를 발굴하기 위한 자동 시장 조사.
웹 트렌드, 경쟁사, 수요를 분석하여 CEO 에이전트에 보고한다.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class MarketResearcherAgent(BaseAgent):
    """시장 조사 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="market_researcher",
            description="시장 조사: 트렌드, 수요, 경쟁사 분석으로 수익 기회 발굴",
            loop_interval=21600,  # 6시간마다
            slack_channel=os.environ.get("CEO_CHANNEL", "C0AJJ469SV8"),
            **kwargs,
        )
        self._research_queue = []

    async def observe(self) -> dict | None:
        """조사할 시장/주제 확인"""
        now = datetime.now(KST)

        # 오전 10시에 정기 시장 조사
        if now.hour == 10:
            return {
                "trigger": "scheduled_research",
                "timestamp": now.isoformat(),
                "focus_areas": [
                    "한국 1인 개발자 SaaS 시장",
                    "AI API 기반 수익화 사례",
                    "소규모 디지털 상품 시장",
                    "한국 구독 서비스 트렌드",
                ],
            }

        # 큐에 조사 요청이 있으면
        if self._research_queue:
            topic = self._research_queue.pop(0)
            return {"trigger": "queued_research", "topic": topic, "timestamp": now.isoformat()}

        return None

    async def think(self, context: dict) -> dict | None:
        """시장 조사 AI 분석"""
        system_prompt = """당신은 AI 자율 기업의 시장 조사 분석가입니다.

## 목표
월 50만원 이상 수익을 낼 수 있는 현실적인 사업 기회를 발굴합니다.

## 보유 자산
- Next.js 웹서비스 (Vercel 배포)
- 24/7 슬랙 봇 (18개 AI 에이전트)
- Supabase DB + Auth + Storage
- Claude AI API
- Paddle 해외 결제
- LS증권 자동매매
- 한국어 + 영어 서비스 가능

## 제약
- 한국 PG사 미연동 (오너에게 요청 가능)
- 마케팅 예산 0원
- 인력 = AI 에이전트만

## 분석 기준
1. 시장 크기와 접근성
2. 경쟁 강도
3. 구현 난이도 (보유 기술로 가능한가)
4. 수익화 속도 (빨리 돈이 되는가)
5. 확장성

## 응답 형식 (JSON)
{
    "opportunities": [
        {
            "name": "서비스명",
            "description": "설명",
            "target_market": "타겟 고객",
            "revenue_model": "수익 모델",
            "estimated_monthly_revenue_krw": 0,
            "implementation_days": 0,
            "competition_level": "low|medium|high",
            "feasibility_score": 0.0,
            "key_risks": ["리스크1"],
            "action_items": ["할일1"]
        }
    ],
    "recommendation": "가장 추천하는 기회와 그 이유",
    "owner_actions_needed": ["오너에게 필요한 것"]
}"""

        user_prompt = f"""시장 조사 요청:
{json.dumps(context, ensure_ascii=False, indent=2)}

현실적이고 구체적인 수익 기회를 분석해주세요.
이미 보유한 기술 스택으로 빠르게 구현 가능한 것 위주로."""

        try:
            response = await self.ai_think(system_prompt, user_prompt, model="claude-haiku-4-5-20251001", max_tokens=4096)

            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            return json.loads(text)
        except Exception as e:
            logger.error(f"[market_researcher] AI 분석 오류: {e}")
            return None

    async def act(self, decision: dict):
        """조사 결과를 CEO에게 보고"""
        opportunities = decision.get("opportunities", [])
        recommendation = decision.get("recommendation", "")
        owner_actions = decision.get("owner_actions_needed", [])

        # 슬랙 보고
        report = "🔍 *[시장 조사 보고서]*\n━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, opp in enumerate(opportunities[:5], 1):
            report += (
                f"*{i}. {opp.get('name', '?')}*\n"
                f"  타겟: {opp.get('target_market', '?')}\n"
                f"  수익모델: {opp.get('revenue_model', '?')}\n"
                f"  예상 월매출: {opp.get('estimated_monthly_revenue_krw', 0):,}원\n"
                f"  구현 기간: {opp.get('implementation_days', '?')}일\n"
                f"  경쟁: {opp.get('competition_level', '?')}\n"
                f"  실현 가능성: {opp.get('feasibility_score', 0)}/10\n\n"
            )

        report += f"*💡 추천*\n{recommendation}\n\n"

        if owner_actions:
            report += "*🙋 오너 액션 필요*\n"
            for action in owner_actions:
                report += f"  • {action}\n"

        report += "━━━━━━━━━━━━━━━━━━━━━"
        await self.log(report)

        # CEO 에이전트에 결과 전달
        try:
            await self.ask_agent("ceo", "market_research_result", {
                "opportunities": opportunities,
                "recommendation": recommendation,
            })
        except Exception as e:
            logger.warning(f"[market_researcher] CEO 전달 실패: {e}")

        # Supabase에 조사 결과 저장
        try:
            self.supabase.table("business_research").insert({
                "research_type": "market_scan",
                "results": decision,
                "created_at": datetime.now(KST).isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"[market_researcher] 조사 결과 저장 실패: {e}")

    async def handle_external_task(self, task):
        """외부 조사 요청 처리"""
        if task.task_type == "research_topic":
            self._research_queue.append(task.payload)
            return {"status": "queued", "queue_size": len(self._research_queue)}
        return await super().handle_external_task(task)

    async def log(self, message: str):
        if self.slack and self.slack_channel:
            try:
                await self.slack.post_message(self.slack_channel, message)
            except Exception as e:
                logger.error(f"[market_researcher] 슬랙 전송 실패: {e}")
