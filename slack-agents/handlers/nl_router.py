"""
NLRouter - 자연어 메시지 라우팅 모듈

사용자의 자연어 메시지를 LLM으로 분석하여 의도를 파악하고
적절한 액션(collect, briefing, dashboard, quote, dev, chat)으로 디스패치한다.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta

from core.conversation_memory import save_turn, build_chat_context, get_user_summary
from core.tools import TOOL_DEFINITIONS, execute_tool_calls
from handlers.command_handler import _reply

logger = logging.getLogger("orchestrator.nl_router")

KST = timezone(timedelta(hours=9))

# ── 경험 저장소 ────────────────────────────────────
_experience_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "experience.json")
os.makedirs(os.path.dirname(_experience_file), exist_ok=True)


def load_experience() -> list[dict]:
    """누적된 작업 경험 로드"""
    try:
        with open(_experience_file, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_experience(entry: dict):
    """작업 경험 저장"""
    data = load_experience()
    data.append(entry)
    data = data[-500:]
    with open(_experience_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))


def find_similar_experience(task_type: str, query: str = "") -> list[dict]:
    """유사한 과거 경험 검색"""
    data = load_experience()
    relevant = []
    for exp in data:
        if exp.get("task_type") == task_type:
            relevant.append(exp)
        elif query and query in exp.get("query", ""):
            relevant.append(exp)
    return relevant[-3:]


class NLRouter:
    """자연어 메시지를 분석하고 적절한 액션으로 라우팅하는 핸들러"""

    def __init__(self, slack, curator, command_handler, dev_runner):
        """
        Args:
            slack: SlackClient 인스턴스
            curator: CuratorAgent 인스턴스 (ai_think 메서드 사용)
            command_handler: CommandHandler 인스턴스 (cmd_* 메서드 재사용)
            dev_runner: DevRunner 인스턴스
        """
        self.slack = slack
        self.curator = curator
        self.cmd = command_handler
        self.dev_runner = dev_runner

    async def _reply(self, channel: str, text: str, thread_ts: str = None, broadcast: bool = False):
        """_reply 래퍼"""
        await _reply(self.slack, channel, text, thread_ts, broadcast)

    async def handle(self, text: str, user: str, channel: str, thread_ts: str = None):
        """자연어 메시지를 분석하고 대화형으로 소통한 뒤 실행"""

        # 0단계: 유저 메시지 메모리에 저장
        save_turn(user, "user", text)

        # 0.5단계: 스레드 답글이면 원문 맥락 가져오기
        thread_context = ""
        if thread_ts:
            try:
                ch_id = await self.slack._resolve_channel(channel) if not channel.startswith("C") else channel
                resp = await self.slack.client.conversations_replies(
                    channel=ch_id, ts=thread_ts, limit=10
                )
                msgs = resp.get("messages", [])
                thread_lines = []
                for m in msgs:
                    if m.get("ts") == thread_ts or m.get("text") != text:
                        who = "봇" if m.get("bot_id") else "유저"
                        thread_lines.append(f"[{who}] {m.get('text', '')[:300]}")
                if thread_lines:
                    thread_context = "\n".join(thread_lines[-8:])
            except Exception as e:
                logger.debug(f"[NL] Thread context fetch error: {e}")

        # 1단계: 과거 경험 + 대화 맥락 로드
        past_exp = load_experience()
        exp_summary = ""
        if past_exp:
            recent = past_exp[-15:]
            exp_lines = [f"- {e['task_type']}: \"{e.get('query','')}\" → {e.get('result','')}" for e in recent]
            exp_summary = "\n".join(exp_lines)

        user_context = get_user_summary(user)

        # 2단계: LLM으로 의도 파악
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

        intent_response = await self.curator.ai_think(
            system_prompt=f"""당신은 슬랙에서 사용자를 도와주는 AI 어시스턴트입니다.
사용자의 메시지를 분석하여 의도를 파악하세요.

당신이 할 수 있는 업무:
- collect: 뉴스 기사 수집만 (구글뉴스 RSS). "~에 대한 뉴스 모아줘" 같은 명확한 수집 요청만 해당
- briefing: 이미 수집된 정보 브리핑/요약
- dashboard: 에이전트 가동 현황, 시스템 상태, 업타임 확인
- quote: 명언 보내기
- dev: 실제 코드 작성, 파일 생성, 프로젝트 구축, API 만들기, 서버 세팅 등 개발/엔지니어링 작업. "만들어줘", "구축해줘", "코드 짜줘", "서버 올려줘", "API 개발해줘", "프로젝트 시작해줘" 등
- chat: 질문, 분석, 비교, 조언, 날씨, 가격, 환율, 잡담, 프로젝트 논의, 의견 교환 등 개발이 아닌 모든 대화

중요: 가격, 날씨, 환율, 분석, 비교 등은 chat. collect가 아닙니다.
중요: 실제 코드/프로젝트를 만들어달라는 요청은 dev입니다. 단순 논의/질문은 chat.
중요: 시스템/에이전트 상태 질문은 dashboard.

{thread_hint}

{("과거 작업 이력:" + chr(10) + exp_summary) if exp_summary else ""}
{user_context}

응답 형식 (반드시 JSON만):
{{
  "intent": "collect|briefing|dashboard|quote|chat|dev|ignore",
  "query": "수집 키워드 (collect일 때만)",
  "approach": "작업 전략 (collect/briefing일 때만)",
  "dev_task": "구체적인 개발 작업 설명 (dev일 때만, 한국어로)",
  "ack": "지금 이 맥락에 딱 맞는 자연스러운 착수 한마디 (15자 이내, 기계적이지 않게)"
}}""",
            user_prompt=text,
        )

        if not intent_response:
            logger.warning("[NL] Empty intent response from AI")
            return

        try:
            clean = intent_response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean)
        except Exception as e:
            logger.warning(f"[NL] Parse error: {e}, raw: {intent_response[:100]}")
            return

        action = parsed.get("intent", "ignore")
        approach = parsed.get("approach", "")
        query = parsed.get("query", "").strip()
        dev_task_raw = parsed.get("dev_task", "")
        ack_msg = parsed.get("ack", "").strip()

        logger.info(f"[NL] Intent: {action}, query: {query}, dev_task: {dev_task_raw[:80] if dev_task_raw else ''}, ack: {ack_msg[:30] if ack_msg else ''}, thread_ts: {thread_ts}")

        if action == "ignore":
            return

        # 3단계: 접수 표시 (눈 리액션 + LLM이 맥락에 맞게 생성한 착수 멘트)
        if thread_ts and action != "ignore" and ack_msg:
            await self.slack.add_reaction(channel, thread_ts, "eyes")
            await self._reply(channel, ack_msg, thread_ts)

        # 4단계: 실제 업무 실행
        result_text = ""
        success = True
        try:
            if action == "collect":
                if query:
                    await self.cmd.cmd_collect(args=query, user=user, channel=channel, thread_ts=thread_ts)
                    result_text = f"'{query}' 수집 완료"
                else:
                    await self._reply(channel, "무엇을 수집할까요? 키워드를 알려주세요.", thread_ts)
                    result_text = "키워드 미지정"
                    success = False
            elif action == "briefing":
                await self.cmd.cmd_briefing(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "브리핑 완료"
            elif action in ("status", "dashboard"):
                await self.cmd.cmd_dashboard(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "현황 확인 완료"
            elif action == "quote":
                await self.cmd.cmd_quote(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "명언 전송 완료"
            elif action == "dev":
                result_text, success = await self._handle_dev(
                    parsed, text, thread_context, channel, thread_ts
                )
            elif action == "chat":
                result_text = await self._handle_chat(
                    text, user, channel, thread_ts, thread_context, exp_summary
                )
        except Exception as e:
            result_text = f"오류: {str(e)[:100]}"
            success = False
            logger.error(f"[NL] Execution error: {e}")

        # 5단계: 경험 저장 + 대화 메모리 (chat 외 액션)
        if action != "chat":
            save_experience({
                "task_type": action,
                "query": query,
                "user_message": text[:200],
                "approach": approach,
                "result": result_text,
                "success": success,
                "timestamp": datetime.now(KST).isoformat(),
            })
            save_turn(user, "assistant", f"[{action}] {result_text}", {"action": action})

    async def _handle_dev(self, parsed: dict, text: str, thread_context: str,
                          channel: str, thread_ts: str = None) -> tuple[str, bool]:
        """dev 액션 처리: Claude Code CLI 호출"""
        dev_task = parsed.get("dev_task", "").strip() or parsed.get("query", "").strip()
        logger.info(f"[dev] Initial dev_task: '{dev_task[:80]}', thread_context exists: {bool(thread_context)}")

        if not dev_task and thread_context:
            for line in thread_context.split("\n"):
                if line.startswith("[유저]"):
                    dev_task = line.replace("[유저]", "").strip()[:500]
                    logger.info(f"[dev] Extracted dev_task from thread: '{dev_task[:80]}'")
                    break

        if not dev_task:
            logger.info(f"[dev] No dev_task found, asking user")
            await self._reply(channel, "어떤 걸 만들면 될까요? 좀 더 구체적으로 알려주세요.", thread_ts)
            return "dev 작업 미지정", False

        full_prompt = self.dev_runner.build_prompt(dev_task, thread_context)
        await self._reply(channel, "🔨 코드 작업 시작합니다. 진행 상황을 알려드릴게요.", thread_ts)

        result = await self.dev_runner.run(full_prompt)

        if result["timed_out"]:
            await self._reply(channel, "⏱️ 작업이 5분을 초과했어요. 좀 더 작은 단위로 나눠서 요청해주세요.", thread_ts)
            return "dev 타임아웃", False
        elif result["success"]:
            output = await self.dev_runner.summarize_output(result["output"])
            await self._reply(channel, f"✅ *[마스터]* 작업 완료!\n\n{output}", thread_ts)
            return f"dev 완료: {dev_task[:50]}", True
        else:
            await self._reply(
                channel,
                f"⚠️ *[마스터]* 작업 중 문제가 생겼어요:\n```\n{result['error'][:1000]}\n```\n다시 시도하거나 작업을 수정해서 알려주세요.",
                thread_ts,
            )
            return f"dev 오류: {result['error'][:100]}", False

    async def _handle_chat(self, text: str, user: str, channel: str,
                           thread_ts: str, thread_context: str, exp_summary: str) -> str:
        """chat 액션 처리: 도구 사용 가능한 대화"""
        chat_history = build_chat_context(user)

        # 1차: 도구가 필요한지 판단
        tool_check = await self.curator.ai_think(
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
        chat_response = await self.curator.ai_think(
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
            # 자기개선 태그 감지
            if "[IMPROVE:" in chat_response:
                improvements = re.findall(r'\[IMPROVE:(.*?)\]', chat_response)
                clean_response = re.sub(r'\s*\[IMPROVE:.*?\]', '', chat_response).strip()
                await self._reply(channel, clean_response, thread_ts)
                for imp in improvements:
                    await self.slack.send_message("ai-agent-logs",
                        f"🔧 *[자기개선 요청]* {imp}\n요청자: <@{user}>\n원본: {text[:100]}")
                    logger.info(f"[NL] Self-improvement request: {imp}")
            else:
                await self._reply(channel, chat_response, thread_ts)
            save_turn(user, "assistant", chat_response, {"action": "chat"})

        return "대화 응답"
