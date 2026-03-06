"""
투자 리포트 에이전트 - 뉴스 기반 투자 전략 리포트 발간

매일 오전 9시, 오후 3시에 최근 뉴스를 수집/분석하여
섹터별 영향과 액셔너블한 투자 전략을 슬랙에 리포트합니다.
"""

import logging
import os
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 리포트 발간 시각 (KST)
REPORT_HOURS = [9, 15]

# 뉴스 검색 키워드 (투자 관련)
NEWS_QUERIES = [
    "미국 증시 주요 뉴스",
    "한국 증시 시장 동향",
    "AI 반도체 기술주",
    "원자재 금 유가",
    "금리 통화정책 연준 한은",
    "글로벌 경제 지정학 리스크",
]


class InvestReportAgent(BaseAgent):
    """뉴스 기반 투자 전략 리포트 에이전트"""

    CHANNEL = "ai-invest"

    def __init__(self, **kwargs):
        super().__init__(
            name="invest_report",
            description="뉴스 기반 투자 전략 리포트 발간 (매일 9시/15시)",
            loop_interval=int(os.environ.get("INVEST_REPORT_INTERVAL", 300)),
            slack_channel=self.CHANNEL,
            **kwargs,
        )
        self._last_report_key = ""  # "YYYY-MM-DD-HH" 형식으로 중복 방지

    async def observe(self) -> dict | None:
        """리포트 발간 시각인지 확인"""
        now = datetime.now(KST)
        current_hour = now.hour

        # 리포트 시각이 아니면 스킵
        if current_hour not in REPORT_HOURS:
            return None

        # 이미 이 시간대에 발간했으면 스킵
        report_key = f"{now.strftime('%Y-%m-%d')}-{current_hour}"
        if report_key == self._last_report_key:
            return None

        return {
            "report_key": report_key,
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "session": "morning" if current_hour < 12 else "afternoon",
        }

    async def think(self, context: dict) -> dict | None:
        """뉴스 수집 + AI 분석"""
        session = context["session"]
        current_time = context["current_time"]

        # 1단계: 다중 키워드로 뉴스 검색
        from core.tools import _web_search
        all_news = []
        for query in NEWS_QUERIES:
            try:
                result = await _web_search(query)
                if result and "검색 결과" in result:
                    all_news.append(result)
            except Exception as e:
                logger.debug(f"[invest_report] News search failed for '{query}': {e}")

        if not all_news:
            logger.warning("[invest_report] No news collected, skipping report")
            return None

        news_text = "\n\n---\n\n".join(all_news)

        # 2단계: AI 분석 - 뉴스 → 섹터 영향 → 투자 전략
        session_label = "오전" if session == "morning" else "오후"
        analysis = await self.ai_think(
            system_prompt=f"""당신은 월스트리트 수준의 투자 전략 애널리스트입니다.
아래 뉴스들을 분석하여 투자 리포트를 작성하세요.

현재 시각: {current_time} ({session_label} 리포트)

작성 규칙:
1. 한국어로 작성
2. 핵심 뉴스/트렌드를 3~5개 선별 (당일 또는 최근 1주일 이내)
3. 각 뉴스가 어떤 섹터/산업에 어떻게 영향을 주는지 구체적으로 분석
4. 실제 실행 가능한(actionable) 투자 전략 제안 (매수/매도/관망 등)
5. 간결하되 인사이트가 있어야 함 (투자자에게 실질적 도움)

반드시 아래 형식(슬랙 마크다운)으로 작성:

*[핵심 뉴스 & 시그널]*

1. *뉴스 제목 요약*
   - 내용: 1~2문장 핵심 요약
   - 영향 섹터: 관련 산업/섹터
   - 시장 영향: 긍정/부정/중립 + 구체적 이유

2. (반복)

*[섹터별 영향 분석]*

| 섹터 | 방향 | 근거 |
|------|------|------|
| 반도체 | 상승 | ... |
| (반복) |

*[투자 전략 제안]*

1. *전략명*
   - 대상: 구체적 종목/ETF/섹터
   - 액션: 매수/매도/비중확대/관망
   - 근거: 1~2문장
   - 리스크: 주의 사항

*[오늘의 한줄 요약]*
한 문장으로 시장 전체 분위기 요약""",
            user_prompt=f"아래는 최근 수집된 뉴스입니다. 분석해주세요.\n\n{news_text[:12000]}",
        )

        if not analysis:
            return None

        return {
            "report_key": context["report_key"],
            "session": session,
            "current_time": current_time,
            "analysis": analysis,
        }

    async def act(self, decision: dict):
        """슬랙에 리포트 발간"""
        session = decision["session"]
        current_time = decision["current_time"]
        analysis = decision["analysis"]

        session_label = "오전" if session == "morning" else "오후"
        header = f"*투자 전략 리포트* | {current_time} {session_label}"

        msg = f"{header}\n{'=' * 40}\n\n{analysis}"

        await self.say(msg)

        # 중복 발간 방지
        self._last_report_key = decision["report_key"]

        logger.info(f"[invest_report] Report published: {decision['report_key']}")
