"""
Agent Orchestrator - 24/7 에이전트 실행기

모든 에이전트를 생성하고, 메시지 버스를 시작하고,
슬랙 연결을 관리하는 메인 진입점.

실행: python orchestrator.py
"""

import asyncio
import json
import logging
import os
import random
import signal
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── 단일 인스턴스 보장 (PID 파일) ─────────────────────
PID_FILE = os.path.join(os.path.dirname(__file__), "data", ".orchestrator.pid")
os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)

def _kill_existing():
    """기존 orchestrator 프로세스 종료 (자기 자신 제외)"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
                os.kill(old_pid, signal.SIGKILL)
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

_kill_existing()

from supabase import create_client

from core.message_bus import MessageBus
from integrations.slack_client import SlackClient
from integrations.notion_client import NotionClient
from agents.collector_agent import CollectorAgent
from agents.curator_agent import CuratorAgent
from agents.quote_agent import QuoteAgent
from agents.proactive_agent import ProactiveAgent
from core.conversation_memory import save_turn, build_chat_context, get_user_summary
from core.tools import TOOL_DEFINITIONS, execute_tool_calls
from core import agent_tracker

# ── 로깅 설정 ──────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")

KST = timezone(timedelta(hours=9))


def load_config() -> dict:
    """환경변수에서 설정 로드"""
    required = [
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "ANTHROPIC_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
    ]
    config = {}
    missing = []
    for key in required:
        val = os.environ.get(key)
        if not val:
            missing.append(key)
        config[key] = val

    if missing:
        logger.error(f"Missing required env vars: {', '.join(missing)}")
        logger.error("Please set them in .env or environment")
        sys.exit(1)

    # 선택적 설정
    config["NOTION_API_KEY"] = os.environ.get("NOTION_API_KEY", "")
    config["NOTION_DATABASE_ID"] = os.environ.get("NOTION_DATABASE_ID", "")

    return config


async def main():
    config = load_config()

    # ── 외부 서비스 클라이언트 초기화 ───────────────────

    logger.info("Initializing services...")

    # Supabase
    supabase = create_client(config["SUPABASE_URL"], config["SUPABASE_SERVICE_ROLE_KEY"])

    # Slack
    slack = SlackClient(
        bot_token=config["SLACK_BOT_TOKEN"],
        app_token=config["SLACK_APP_TOKEN"],
    )

    # Notion (선택적)
    notion = None
    if config["NOTION_API_KEY"]:
        notion = NotionClient(api_key=config["NOTION_API_KEY"])
        logger.info("Notion integration enabled")

    # ── 메시지 버스 ─────────────────────────────────────

    bus = MessageBus(supabase_client=supabase)

    # ── 에이전트 생성 ───────────────────────────────────

    common_kwargs = {
        "message_bus": bus,
        "slack_client": slack,
        "notion_client": notion,
        "supabase_client": supabase,
        "anthropic_api_key": config["ANTHROPIC_API_KEY"],
    }

    collector = CollectorAgent(**common_kwargs)
    proactive = ProactiveAgent(**common_kwargs)
    curator = CuratorAgent(
        notion_db_id=config.get("NOTION_DATABASE_ID", ""),
        **common_kwargs,
    )
    quote = QuoteAgent(**common_kwargs)

    # ── 슬랙 명령어 등록 ───────────────────────────────

    # "!수집 AI뉴스" → 수집 에이전트에 키워드 수집 즉시 실행
    async def cmd_collect(args: str, user: str, channel: str, thread_ts: str = None):
        if args.strip():
            query = args.strip()
            curator.set_query_context(query, thread_ts=thread_ts, channel=channel)
            await collector._collect_by_keyword(query, user, thread_ts=thread_ts)
        else:
            await _reply(channel, "사용법: `!수집 키워드`", thread_ts)

    # "!브리핑" → 선별 에이전트에 즉시 브리핑 요청
    async def cmd_briefing(args: str, user: str, channel: str, thread_ts: str = None):
        curator.set_query_context("브리핑", thread_ts=thread_ts, channel=channel)
        context = await curator.observe()
        if context:
            decision = await curator.think(context)
            if decision:
                await curator.act(decision)
        else:
            await _reply(channel, "새로운 정보가 없습니다.", thread_ts)

    # "!상태" → 전체 시스템 상태 확인
    async def cmd_status(args: str, user: str, channel: str, thread_ts: str = None):
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        status_msg = f"*시스템 상태* ({now})\n"
        status_msg += f"- Collector: 실행 중 (간격: {collector.loop_interval}초)\n"
        status_msg += f"- Curator: 실행 중 (간격: {curator.loop_interval}초)\n"
        status_msg += f"- Curator 대기 버퍼: {len(curator._new_articles_buffer)}건\n"
        await _reply(channel, status_msg, thread_ts)

    async def _reply(channel: str, text: str, thread_ts: str = None, broadcast: bool = False):
        """스레드가 있으면 스레드로, 없으면 채널에 직접 전송. broadcast=True면 채널에도 표시"""
        if thread_ts:
            await slack.send_thread_reply(channel, thread_ts, text, also_send_to_channel=broadcast)
        else:
            await slack.send_message(channel, text)

    # "!명언" → 명언 에이전트 즉시 실행
    async def cmd_quote(args: str, user: str, channel: str, thread_ts: str = None):
        context = {
            "current_time": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "current_hour": datetime.now(KST).hour,
            "recent_conversations": [],
            "sent_history": quote._quote_history[-30:],
        }
        # 최근 대화 수집
        try:
            recent = await quote._fetch_recent_messages()
            context["recent_conversations"] = recent[:20]
        except Exception:
            pass
        decision = await quote.think(context)
        if decision:
            decision["action"] = "send_quote"
            # 요청한 채널/스레드로 전송
            msg = quote._format_message(decision)
            await _reply(channel, msg, thread_ts)
            quote._quote_history.append(f"{decision['quote_ko']} — {decision['author']}")
            quote._save_history()
        else:
            await _reply(channel, "명언 생성에 실패했어요.", thread_ts)

    # "!로그" → 요청사항 이력 보기
    async def cmd_log(args: str, user: str, channel: str, thread_ts: str = None):
        log_file = os.path.join(os.path.dirname(__file__), "data", "request_log.json")
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.loads(f.read())
            if not logs:
                await _reply(channel, "요청 이력이 없습니다.", thread_ts)
                return
            latest = logs[-1]
            lines = [f"📋 *요청사항 로그* ({latest['date']})\n"]
            for r in latest.get("requests", []):
                status = "✅" if r["status"] == "done" else "🔄"
                lines.append(f"{status} {r['request']}")
                lines.append(f"   _{r.get('changes', '')[:80]}_")
            await _reply(channel, "\n".join(lines), thread_ts)
        except Exception as e:
            await _reply(channel, f"로그 로드 실패: {e}", thread_ts)

    # "!현황" → 에이전트 가동 현황 보기
    async def cmd_dashboard(args: str, user: str, channel: str, thread_ts: str = None):
        report = agent_tracker.get_status_report()
        await _reply(channel, report, thread_ts)

    slack.on_command("수집", cmd_collect)
    slack.on_command("브리핑", cmd_briefing)
    slack.on_command("상태", cmd_status)
    slack.on_command("명언", cmd_quote)
    slack.on_command("로그", cmd_log)
    slack.on_command("현황", cmd_dashboard)

    # ── 경험 저장소 ────────────────────────────────────
    experience_file = os.path.join(os.path.dirname(__file__), "data", "experience.json")
    os.makedirs(os.path.dirname(experience_file), exist_ok=True)

    def load_experience() -> list[dict]:
        """누적된 작업 경험 로드"""
        try:
            with open(experience_file, "r", encoding="utf-8") as f:
                return json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_experience(entry: dict):
        """작업 경험 저장"""
        data = load_experience()
        data.append(entry)
        # 최근 500건 유지
        data = data[-500:]
        with open(experience_file, "w", encoding="utf-8") as f:
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
        return relevant[-3:]  # 최근 3건

    # ── 자연어 메시지 처리 (대화형 소통) ─────────────
    async def on_natural_language(text: str, user: str, channel: str, thread_ts: str = None):
        """자연어 메시지를 분석하고 대화형으로 소통한 뒤 실행"""
        import json as _json

        # 0단계: 유저 메시지 메모리에 저장
        save_turn(user, "user", text)

        # 0.5단계: 스레드 답글이면 원문 맥락 가져오기
        thread_context = ""
        if thread_ts:
            try:
                ch_id = await slack._resolve_channel(channel) if not channel.startswith("C") else channel
                resp = await slack.client.conversations_replies(
                    channel=ch_id, ts=thread_ts, limit=10
                )
                msgs = resp.get("messages", [])
                thread_lines = []
                for m in msgs:
                    if m.get("ts") == thread_ts or m.get("text") != text:
                        who = "봇" if m.get("bot_id") else "유저"
                        thread_lines.append(f"[{who}] {m.get('text', '')[:300]}")
                if thread_lines:
                    thread_context = "\n".join(thread_lines[-8:])  # 최근 8개 메시지
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

        intent_response = await curator.ai_think(
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
            parsed = _json.loads(clean)
        except (Exception,) as e:
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
            await slack.add_reaction(channel, thread_ts, "eyes")
            await _reply(channel, ack_msg, thread_ts)

        # 4단계: 실제 업무 실행
        result_text = ""
        success = True
        try:
            if action == "collect":
                if query:
                    await cmd_collect(args=query, user=user, channel=channel, thread_ts=thread_ts)
                    result_text = f"'{query}' 수집 완료"
                else:
                    await _reply(channel, "무엇을 수집할까요? 키워드를 알려주세요.", thread_ts)
                    result_text = "키워드 미지정"
                    success = False
            elif action == "briefing":
                await cmd_briefing(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "브리핑 완료"
            elif action in ("status", "dashboard"):
                await cmd_dashboard(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "현황 확인 완료"
            elif action == "quote":
                await cmd_quote(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "명언 전송 완료"
            elif action == "dev":
                # 실제 개발 실행: Claude Code CLI 호출
                dev_task = parsed.get("dev_task", "").strip() or (query or "").strip()
                logger.info(f"[dev] Initial dev_task: '{dev_task[:80]}', thread_context exists: {bool(thread_context)}")
                # dev_task가 비어있고 스레드 맥락이 있으면, 원래 요청(첫 유저 메시지)을 사용
                if not dev_task and thread_context:
                    for line in thread_context.split("\n"):
                        if line.startswith("[유저]"):
                            dev_task = line.replace("[유저]", "").strip()[:500]
                            logger.info(f"[dev] Extracted dev_task from thread: '{dev_task[:80]}'")
                            break
                if not dev_task:
                    logger.info(f"[dev] No dev_task found, asking user")
                    await _reply(channel, "어떤 걸 만들면 될까요? 좀 더 구체적으로 알려주세요.", thread_ts)
                    result_text = "dev 작업 미지정"
                    success = False
                else:
                    # 스레드 맥락이 있으면 프롬프트에 포함
                    full_prompt = dev_task
                    if thread_context:
                        full_prompt = f"[이전 대화 맥락]\n{thread_context}\n\n[요청]\n{dev_task}"

                    await _reply(channel, "🔨 코드 작업 시작합니다. 진행 상황을 알려드릴게요.", thread_ts)

                    try:
                        # CLAUDECODE 환경변수 제거 (중첩 세션 방지)
                        clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
                        proc = await asyncio.create_subprocess_exec(
                            "claude", "-p", full_prompt,
                            "--output-format", "text",
                            cwd="/home/user/yhmemo",
                            env=clean_env,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        stdout, stderr = await asyncio.wait_for(
                            proc.communicate(), timeout=300  # 5분 타임아웃
                        )
                        output = stdout.decode("utf-8", errors="replace").strip()
                        err_output = stderr.decode("utf-8", errors="replace").strip()

                        if proc.returncode == 0 and output:
                            # 결과가 길면 요약
                            if len(output) > 3000:
                                summary = await curator.ai_think(
                                    system_prompt="아래 Claude Code 실행 결과를 슬랙 메시지로 요약하세요. 무엇을 만들었는지, 어떤 파일을 생성/수정했는지, 다음 단계는 무엇인지 핵심만. 최대 1500자.",
                                    user_prompt=output,
                                )
                                await _reply(channel, f"✅ 작업 완료!\n\n{summary or output[:1500]}", thread_ts)
                            else:
                                await _reply(channel, f"✅ 작업 완료!\n\n{output}", thread_ts)
                            result_text = f"dev 완료: {dev_task[:50]}"
                        else:
                            error_msg = err_output or output or "알 수 없는 오류"
                            await _reply(channel, f"⚠️ 작업 중 문제가 생겼어요:\n```\n{error_msg[:1000]}\n```\n다시 시도하거나 작업을 수정해서 알려주세요.", thread_ts)
                            result_text = f"dev 오류: {error_msg[:100]}"
                            success = False
                    except asyncio.TimeoutError:
                        await _reply(channel, "⏱️ 작업이 5분을 초과했어요. 좀 더 작은 단위로 나눠서 요청해주세요.", thread_ts)
                        result_text = "dev 타임아웃"
                        success = False

            elif action == "chat":
                # 대화 이력을 포함한 깊은 대화 (도구 사용 가능)
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
                    tool_parsed = _json.loads(tool_check.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
                    if tool_parsed.get("needs_tool") and tool_parsed.get("tool_calls"):
                        logger.info(f"[NL] Tool calls: {tool_parsed['tool_calls']}")
                        tool_results = await execute_tool_calls(tool_parsed["tool_calls"])
                        logger.info(f"[NL] Tool results: {tool_results[:200]}")
                except Exception as e:
                    logger.debug(f"[NL] Tool parse skip: {e}")

                # 2차: 도구 결과 포함해서 답변 생성
                chat_response = await curator.ai_think(
                    system_prompt=f"""당신은 슬랙에서 사용자와 대화하는 AI 어시스턴트 'Agent 01'입니다.
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
                        import re
                        improvements = re.findall(r'\[IMPROVE:(.*?)\]', chat_response)
                        # 태그는 유저에게 보여주지 않음
                        clean_response = re.sub(r'\s*\[IMPROVE:.*?\]', '', chat_response).strip()
                        await _reply(channel, clean_response, thread_ts)
                        # 개선 요청을 로그 채널에 기록
                        for imp in improvements:
                            await slack.send_message("ai-agent-logs",
                                f"🔧 *[자기개선 요청]* {imp}\n요청자: <@{user}>\n원본: {text[:100]}")
                            logger.info(f"[NL] Self-improvement request: {imp}")
                    else:
                        await _reply(channel, chat_response, thread_ts)
                    save_turn(user, "assistant", chat_response, {"action": "chat"})
                result_text = "대화 응답"
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
            # 작업 결과도 대화 메모리에 기록
            save_turn(user, "assistant", f"[{action}] {result_text}", {"action": action})

    slack.on_natural_language(on_natural_language)

    # 이모지 반응 → 선별 에이전트 피드백 학습
    async def on_reaction(reaction: str, item: dict, user: str):
        await curator.handle_reaction_feedback(reaction, item)

    slack.on_reaction(on_reaction)

    # 멘션 → AI가 자유롭게 응답
    async def on_mention(text: str, user: str, channel: str, say):
        # 멘션에서 봇 ID 부분 제거
        clean_text = text.split(">", 1)[-1].strip() if ">" in text else text
        if not clean_text:
            return
        response = await curator.ai_think(
            system_prompt="당신은 정보 관리 AI 어시스턴트입니다. 사용자의 질문에 간결하게 답하세요.",
            user_prompt=clean_text,
        )
        await say(response)

    slack.on_mention(on_mention)

    # ── 모든 비동기 태스크 시작 ─────────────────────────

    # 오케스트레이터 자체를 추적 대상으로 등록
    agent_tracker.register_agent("orchestrator", "메인 폴링 루프 + 메시지 라우터", 3)
    agent_tracker.register_agent("message_bus", "에이전트 간 메시지 버스", 0)

    logger.info("Starting all agents...")

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()
        bus.stop()
        collector.stop()
        curator.stop()
        quote.stop()
        proactive.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Socket Mode 먼저 시도 → 실패 시 폴링으로 전환
    socket_mode = await slack._try_socket_mode()

    if socket_mode:
        logger.info("✓ Socket Mode 연결 성공! 실시간 이벤트 수신 중 (폴링 불필요)")
        # Socket Mode에서도 채널 캐시와 기본 설정은 필요
        await slack.ensure_channels_exist()
        await slack._init_channel_cache()
    else:
        logger.info("Socket Mode 불가 → 폴링 모드로 운영")
        await slack.start_background()

    logger.info("Agents started silently (no startup message to Slack)")

    # 에이전트 태스크 실행
    tasks = [
        asyncio.create_task(bus.run(), name="message_bus"),
        asyncio.create_task(collector.start(), name="collector"),
        asyncio.create_task(curator.start(), name="curator"),
        asyncio.create_task(quote.start(), name="quote"),
        asyncio.create_task(proactive.start(), name="proactive"),
    ]

    if socket_mode:
        # Socket Mode: 이벤트는 WebSocket으로 자동 수신, 폴링 불필요
        logger.info("All agents running. Socket Mode active (no polling needed)")
        await shutdown_event.wait()
    else:
        # 폴링 모드: 3초마다 메시지 확인 (실시간성 향상)
        logger.info("All agents running. Starting polling loop (3s interval)...")
        poll_count = 0
        while not shutdown_event.is_set():
            poll_count += 1
            agent_tracker.heartbeat("orchestrator")
            if poll_count % 20 == 1:  # 1분마다 로그
                thread_count = sum(len(v) for v in slack._active_threads.values())
                logger.info(f"[main] Poll tick #{poll_count} (alive, {thread_count} threads tracked)")
            try:
                await slack.poll_once()
            except Exception as e:
                logger.error(f"Poll error: {e}")
            # shutdown 체크와 함께 3초 대기
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass

    # 태스크 정리
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    if notion:
        await notion.close()

    logger.info("Orchestrator shut down cleanly")


if __name__ == "__main__":
    # 자동 재시작 래퍼: 예기치 않은 크래시 시 재기동
    max_restarts = 5
    restart_count = 0
    while restart_count < max_restarts:
        try:
            asyncio.run(main())
            break  # 정상 종료 (shutdown signal)
        except KeyboardInterrupt:
            break
        except Exception as e:
            restart_count += 1
            logger.error(f"Orchestrator crashed ({restart_count}/{max_restarts}): {e}")
            if restart_count < max_restarts:
                import time
                logger.info(f"Restarting in 10 seconds...")
                time.sleep(10)
            else:
                logger.critical("Max restarts reached. Exiting.")
