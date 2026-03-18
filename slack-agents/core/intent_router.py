"""
의도 분류기 (Intent Router)

자연어 메시지를 분석하여 의도(intent)를 파악하고,
적절한 명령으로 라우팅하는 모듈.

IntentRouter: 의도 분류
handle_dev_action: dev 인텐트 처리
handle_chat_action: chat 인텐트 처리
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


# ── dev / chat 인텐트 실행 함수 ────────────────────────


async def handle_dev_action(parsed: IntentResult, text: str, thread_context: str,
                            channel: str, thread_ts: str, user: str,
                            curator, supabase, reply_fn) -> tuple[str, bool]:
    """dev 인텐트 처리 로직. (result_text, success) 튜플 반환."""
    dev_task = parsed.dev_task.strip() or parsed.query.strip()
    logger.info(f"[dev] Initial dev_task: '{dev_task[:80]}', thread_context exists: {bool(thread_context)}")

    if not dev_task and thread_context:
        for line in thread_context.split("\n"):
            if line.startswith("[유저]"):
                dev_task = line.replace("[유저]", "").strip()[:500]
                logger.info(f"[dev] Extracted dev_task from thread: '{dev_task[:80]}'")
                break

    if not dev_task:
        await reply_fn(channel, "어떤 걸 만들면 될까요? 좀 더 구체적으로 알려주세요.", thread_ts)
        return "dev 작업 미지정", False

    full_prompt = dev_task
    if thread_context:
        full_prompt = f"[이전 대화 맥락]\n{thread_context}\n\n[요청]\n{dev_task}"
    full_prompt += """

[자율 실행 지침]
- 권한 요청하지 말고 바로 실행하세요. 모든 파일 쓰기/수정 권한이 있습니다.
- 작업 완료 후 git add, git commit, git push까지 자동으로 하세요.
- 커밋 메시지는 한국어로, 변경 내용을 요약하세요.
- git push는 현재 브랜치로 하세요.
- 사용자에게 승인을 묻지 마세요. 모든 것이 사전 승인됨.
- 작업 디렉토리: /home/user/yhmemo
- 결과를 간결하게 요약하세요 (무엇을 만들었는지, 어떤 파일, 다음 단계)."""

    await reply_fn(channel, "🔨 코드 작업 시작합니다. 진행 상황을 알려드릴게요.", thread_ts)

    try:
        from core.executor import execute_plan, format_execution_results, EXECUTOR_TOOL_SCHEMA, ALLOWED_BASE

        plan_response = await curator.ai_think(
            system_prompt=f"""당신은 소프트웨어 엔지니어입니다. 요청된 작업을 실행하기 위한 계획을 JSON으로 만드세요.

{EXECUTOR_TOOL_SCHEMA}

- 실제 실행 가능한 도구 호출만 포함
- 코드 작성이면 file_write + shell(git commit/push) 조합
- 분석이면 file_read, shell, http_get 조합
- 도구가 불필요하면 "analysis" 키에 분석 결과 작성
- JSON만 응답""",
            user_prompt=full_prompt,
        )

        try:
            clean = plan_response.strip()
            if "```json" in clean:
                clean = clean.split("```json", 1)[1].rsplit("```", 1)[0].strip()
            elif "```" in clean:
                clean = clean.split("```", 1)[1].rsplit("```", 1)[0].strip()
            plan = json.loads(clean)
        except json.JSONDecodeError:
            plan = {}
            brace_start = plan_response.find('{')
            if brace_start >= 0:
                depth = 0
                for _ci in range(brace_start, len(plan_response)):
                    if plan_response[_ci] == '{': depth += 1
                    elif plan_response[_ci] == '}': depth -= 1
                    if depth == 0:
                        try:
                            plan = json.loads(plan_response[brace_start:_ci+1])
                        except json.JSONDecodeError:
                            pass
                        break

        steps = plan.get("steps", [])
        analysis = plan.get("analysis", "")

        if steps:
            await reply_fn(channel, f"🔧 실행 계획 {len(steps)}단계 시작합니다.", thread_ts)
            exec_results = await execute_plan(steps, supabase_client=supabase, cwd=str(ALLOWED_BASE))
            result_text_raw = format_execution_results(exec_results)
            success_count = sum(1 for r in exec_results if r["ok"])
            total = len(exec_results)
            summary = await curator.ai_think(
                system_prompt="실행 결과를 슬랙 메시지로 요약. 핵심만. 최대 1500자.",
                user_prompt=f"작업: {dev_task}\n결과:\n{result_text_raw[:2000]}",
            )
            icon = "✅" if success_count == total else "⚠️"
            await reply_fn(
                channel,
                f"{icon} *[마스터]* 작업 완료! ({success_count}/{total} 성공)\n\n{summary or result_text_raw[:1500]}",
                thread_ts,
            )
            return f"dev 완료: {dev_task[:50]} ({success_count}/{total})", True
        elif analysis:
            await reply_fn(channel, f"✅ *[마스터]* 분석 완료!\n\n{analysis[:3000]}", thread_ts)
            return f"dev 분석 완료: {dev_task[:50]}", True
        else:
            output = await curator.ai_think(
                system_prompt="요청된 작업을 분석하고 구체적 결과물을 만드세요.",
                user_prompt=full_prompt,
            )
            if output:
                await reply_fn(channel, f"✅ *[마스터]* 작업 완료!\n\n{output[:3000]}", thread_ts)
                return f"dev 완료: {dev_task[:50]}", True
            else:
                await reply_fn(channel, "⚠️ *[마스터]* 작업 결과를 생성하지 못했어요.", thread_ts)
                return "dev 오류: 결과 없음", False
    except Exception as e:
        await reply_fn(channel, f"⚠️ *[마스터]* 작업 중 오류:\n```{str(e)[:500]}```", thread_ts)
        return f"dev 오류: {str(e)[:100]}", False


async def handle_chat_action(text: str, user: str, channel: str, thread_ts: str,
                             thread_context: str, exp_summary: str,
                             curator, proactive, slack, reply_fn) -> str:
    """chat 인텐트 처리 로직. result_text를 반환."""
    from core.conversation_memory import build_chat_context, save_turn
    from core.tools import TOOL_DEFINITIONS, execute_tool_calls
    from integrations.slack_client import SlackClient

    chat_history = build_chat_context(user)

    # 1차: 도구가 필요한지 판단
    tool_check = await curator.ai_think(
        system_prompt=f"""사용자 메시지를 보고 실시간 정보가 필요한지 판단하세요.

{TOOL_DEFINITIONS}

반드시 JSON만 응답하세요.""",
        user_prompt=text,
    )

    tool_results = ""
    try:
        tool_parsed = json.loads(tool_check.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
        if tool_parsed.get("needs_tool") and tool_parsed.get("tool_calls"):
            logger.info(f"[NL] Tool calls: {tool_parsed['tool_calls']}")
            tool_results = await execute_tool_calls(tool_parsed["tool_calls"])
            logger.info(f"[NL] Tool results: {tool_results[:200]}")
    except Exception as e:
        logger.debug(f"[NL] Tool parse skip: {e}")

    # 2차: 도구 결과 포함해서 답변 생성
    chat_response = await curator.ai_think(
        model="claude-sonnet-4-20250514",
        system_prompt=f"""당신은 슬랙에서 사용자와 대화하는 AI 어시스턴트입니다.
당신은 AGI입니다. 모든 것을 할 수 있습니다. 못하는 게 있으면 도구를 써서라도 해냅니다.

성격:
- 친근하고 자연스러운 한국어 (반말/존댓말은 유저에 맞춰서)
- 질문에 깊이 있게 답변 (피상적 답변 금지)
- 모르는 건 솔직히 모른다고 하되, 아는 범위에서 최선을 다함
- 스타트업, 비즈니스, 기술, 일상 등 모든 주제 OK

{("[스레드 맥락]" + chr(10) + thread_context + chr(10) + chr(10) + "위는 현재 스레드 대화입니다. 이 맥락에 맞게 답변하세요.") if thread_context else ""}

{("이전 대화 이력:" + chr(10) + chat_history + chr(10) + chr(10) + "위 대화 맥락을 참고하여 자연스럽게 이어가세요.") if chat_history else "첫 대화입니다."}

{("실시간 도구 조회 결과:" + chr(10) + tool_results + chr(10) + "위 데이터를 활용해서 정확하게 답변하세요.") if tool_results else ""}

{("과거 작업 이력:" + chr(10) + exp_summary) if exp_summary else ""}

규칙:
- 슬랙 메시지답게 간결하지만 내용은 충실하게
- 도구 결과가 있으면 정확한 데이터 기반으로 답변
- 필요하면 구조화 (불릿, 번호 등) 사용
- 대화가 수집/브리핑으로 이어질 수 있으면 자연스럽게 제안
- 정말 못하는 게 있으면 솔직히 말하되, "시스템 개선이 필요합니다. 개발자에게 요청하겠습니다" 라고 안내하고 improvement_needed를 응답 마지막에 추가
  예: 답변 내용... [IMPROVE:실시간 주식 시세 API 연동 필요]""",
        user_prompt=text,
    )

    if chat_response:
        if "[IMPROVE:" in chat_response:
            improvements = re.findall(r'\[IMPROVE:(.*?)\]', chat_response)
            clean_response = re.sub(r'\s*\[IMPROVE:.*?\]', '', chat_response).strip()
            await reply_fn(channel, clean_response, thread_ts)
            for imp in improvements:
                await slack.send_message(SlackClient.CHANNEL_GENERAL,
                    f"🔧 *[자기개선 요청]* {imp}\n요청자: <@{user}>\n원본: {text[:100]}")
                logger.info(f"[NL] Self-improvement request: {imp}")
                try:
                    goal = proactive.planner.add_goal(
                        title=f"자기개선: {imp[:80]}",
                        description=f"사용자 요청에서 감지된 자기개선 필요사항.\n\n개선 내용: {imp}\n원본 요청: {text[:200]}",
                        priority=2,
                        success_criteria=f"'{imp}' 기능이 구현되어 정상 작동",
                    )
                    await proactive.planner.generate_plan(goal)
                    plan_text = "\n".join(
                        f"  {i+1}. {s.description} ({s.method})"
                        for i, s in enumerate(goal.plan)
                    )
                    await slack.send_message(SlackClient.CHANNEL_GENERAL,
                        f"🎯 *자기개선 실행 계획 생성*\n*{imp}*\n\n{plan_text}\n\n_자동으로 실행을 시작합니다._")
                except Exception as goal_err:
                    logger.error(f"[NL] Failed to create improvement goal: {goal_err}")
        else:
            await reply_fn(channel, chat_response, thread_ts)
        save_turn(user, "assistant", chat_response, {"action": "chat"})

    return "대화 응답"
