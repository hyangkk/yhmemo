"""
의도 분류기 (Intent Router)

자연어 메시지를 분석하여 의도(intent)를 파악하고,
적절한 명령으로 라우팅하는 모듈.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("intent_router")


@dataclass
class IntentResult:
    """의도 분류 결과"""
    intent: str = "ignore"
    query: str = ""
    approach: str = ""
    dev_task: str = ""
    ack: str = ""
    # 주식 관련
    stock_action: str = ""
    stock_code: str = ""
    stock_qty: int = 1
    stock_price: int = 0
    # HR 관련
    hr_target: str = ""
    hr_amount: int = 0
    hr_reason: str = ""
    # 블로그 관련
    blog_urls: list = field(default_factory=list)
    # 의도 확인
    clarify_question: str = ""


class IntentRouter:
    """자연어 의도 분류기 - Claude AI를 사용하여 메시지 의도를 파악"""

    def __init__(self, ai_think_fn):
        """
        ai_think_fn: curator.ai_think와 동일한 시그니처의 비동기 함수
            async def ai_think(system_prompt, user_prompt, model=None) -> str
        """
        self._ai_think = ai_think_fn

    async def classify(
        self,
        message: str,
        thread_context: str = "",
        experience_summary: str = "",
        user_context: str = "",
    ) -> Optional[IntentResult]:
        """
        메시지를 분석하여 IntentResult를 반환.
        파싱 실패 시 None 반환.
        """
        thread_hint = ""
        if thread_context:
            thread_hint = f"""
[스레드 맥락] (유저가 이 대화의 스레드에 답글을 달았습니다)
{thread_context}
---
위 스레드 맥락을 반드시 고려하여 의도를 파악하세요.
"진행시켜", "해줘", "좋아", "그래", "다시 해줘", "다시 진행" 같은 짧은 답글은 스레드 원문에 대한 동의/실행 요청입니다.
이런 경우 스레드 맥락에 맞는 intent를 선택하세요.
- 스레드에서 개발/코드 작업이 논의되었다면 intent는 dev, dev_task에 원래 요청 내용을 구체적으로 채워주세요.
- 스레드에서 일반 대화였다면 chat.
"""

        system_prompt = f"""당신은 슬랙에서 사용자를 도와주는 AI 어시스턴트입니다.
사용자의 메시지를 분석하여 의도를 파악하세요.

당신이 할 수 있는 업무:
- collect: 뉴스 기사 수집만 (구글뉴스 RSS). "~에 대한 뉴스 모아줘" 같은 명확한 수집 요청만 해당
- briefing: 이미 수집된 정보 브리핑/요약
- dashboard: 에이전트 가동 현황, 시스템 상태, 업타임 확인
- quote: 명언 보내기
- diary_quote: 생각일기 한마디, 생각일기 실행, 일기에서 한마디
- diary_daily_alert: 생각일기 분석, 일기 분석알림, 일기 분석해줘, 오늘 일기 분석
- fortune: 운세 보기, 오늘의 운세
- invest_status: 투자 에이전트 현황, 매매 성과, 투자 보고서, 트레이딩 성적, "투자 에이전트 어때?", "매매 성과 보여줘", "투자현황", "에이전트 수준 평가", "자율거래 성과", "스윙트레이딩 성적" 등. 투자/매매/트레이딩 에이전트의 성과·승률·등급을 종합 모니터링
- hr_eval: 인사평가 실행, 에이전트 평가, 성과 평가, "인사평가 해줘", "에이전트들 평가해봐"
- hr_status: 인사현황, 연봉 조회, 에이전트 인사카드, "연봉 랭킹", "인사 현황 보여줘", "에이전트 연봉", "누가 제일 많이 받아?" hr_target 필드에 특정 에이전트명 (없으면 전체)
- hr_salary: 연봉 조정, "연봉 올려줘", "연봉 깎아", hr_target(에이전트명), hr_amount(조정액, 만원), hr_reason(사유)
- stock_trade: 주식 매수/매도/잔고조회/시세조회. "삼성전자 1주 매수", "005930 매도해줘", "잔고 보여줘", "삼성전자 시세", "모의투자 매수" 등. stock_code(종목코드), action(buy/sell/balance/price), qty(수량), price(가격, 0이면 시장가) 필드 포함
- bulletin: 게시판 스크래핑, 공지사항 확인, 새 글 확인. "게시판 확인해줘", "공지사항 새 거 있어?", "문화센터 게시판 긁어줘", "새 공지 알려줘" 등
- naver_blog: 네이버 블로그 글 크롤링/스크래핑. "이 블로그 글 읽어줘", "블로그 내용 가져와", "네이버 블로그 크롤링해줘" 등. 메시지에 blog.naver.com URL이 포함되어 있으면 이 인텐트. blog_urls 필드에 URL 목록을 넣으세요.
- qa: 웹 서비스 상태 확인, QA 테스트, 배포 상태 확인, 서비스 헬스체크. "서비스 상태 확인해줘", "QA 테스트 돌려줘", "배포 잘 됐어?", "사이트 살아있어?" 등
- dev: 실제 코드 작성, 파일 생성, 프로젝트 구축, API 만들기, 서버 세팅 등 개발/엔지니어링 작업. "만들어줘", "구축해줘", "코드 짜줘", "서버 올려줘", "API 개발해줘", "프로젝트 시작해줘" 등
- chat: 질문, 분석, 비교, 조언, 날씨, 가격, 환율, 잡담, 프로젝트 논의, 의견 교환 등 개발이 아닌 모든 대화

중요: 가격, 날씨, 환율, 분석, 비교 등은 chat. collect가 아닙니다.
중요: 실제 코드/프로젝트를 만들어달라는 요청은 dev입니다. 단순 논의/질문은 chat.
중요: 시스템/에이전트 상태 질문은 dashboard.
중요: 주식 매수/매도/잔고/시세 관련은 stock_trade. 종목명은 한국어→종목코드 매핑: 삼성전자=005930, SK하이닉스=000660, 네이버=035420, 카카오=035720, LG에너지솔루션=373220, 현대차=005380, 삼성바이오로직스=207940, 기아=000270, 셀트리온=068270, POSCO홀딩스=005490
중요: 의도가 애매하거나 여러 해석이 가능할 때는 clarify를 사용하고, clarify_question에 되물을 질문을 넣으세요.

{thread_hint}

{("과거 작업 이력:" + chr(10) + experience_summary) if experience_summary else ""}
{user_context}

응답 형식 (반드시 JSON만):
{{
  "intent": "collect|briefing|dashboard|quote|diary_quote|diary_daily_alert|fortune|invest_status|hr_eval|hr_status|hr_salary|stock_trade|bulletin|naver_blog|qa|chat|dev|clarify|ignore",
  "query": "수집 키워드 (collect일 때만)",
  "approach": "작업 전략 (collect/briefing일 때만)",
  "dev_task": "구체적인 개발 작업 설명 (dev일 때만, 한국어로)",
  "stock_action": "buy|sell|balance|price (stock_trade일 때만)",
  "stock_code": "종목코드 6자리 (stock_trade일 때만, 예: 005930)",
  "stock_qty": 1,
  "stock_price": 0,
  "hr_target": "에이전트명 (hr_status/hr_salary일 때만)",
  "hr_amount": 0,
  "hr_reason": "사유 (hr_salary일 때만)",
  "blog_urls": ["URL1", "URL2"],
  "clarify_question": "의도 확인용 질문 (clarify일 때만)",
  "ack": "지금 이 맥락에 딱 맞는 자연스러운 착수 한마디 (15자 이내, 기계적이지 않게)"
}}"""

        intent_response = await self._ai_think(
            model="claude-sonnet-4-20250514",
            system_prompt=system_prompt,
            user_prompt=message,
        )

        if not intent_response:
            logger.warning("[IntentRouter] AI 응답 없음")
            return None

        try:
            clean = intent_response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean)
        except Exception as e:
            logger.warning(f"[IntentRouter] JSON 파싱 실패: {e}, raw: {intent_response[:100]}")
            return None

        result = IntentResult(
            intent=parsed.get("intent", "ignore"),
            query=parsed.get("query", "").strip(),
            approach=parsed.get("approach", ""),
            dev_task=parsed.get("dev_task", ""),
            ack=parsed.get("ack", "").strip(),
            stock_action=parsed.get("stock_action", "").strip(),
            stock_code=parsed.get("stock_code", "").strip(),
            stock_qty=int(parsed.get("stock_qty", 1) or 1),
            stock_price=int(parsed.get("stock_price", 0) or 0),
            hr_target=parsed.get("hr_target", "").strip(),
            hr_amount=int(parsed.get("hr_amount", 0) or 0),
            hr_reason=parsed.get("hr_reason", "").strip(),
            blog_urls=parsed.get("blog_urls", []),
            clarify_question=parsed.get("clarify_question", ""),
        )

        logger.info(
            f"[IntentRouter] intent={result.intent}, query={result.query}, "
            f"dev_task={result.dev_task[:80] if result.dev_task else ''}, "
            f"ack={result.ack[:30] if result.ack else ''}"
        )

        return result
