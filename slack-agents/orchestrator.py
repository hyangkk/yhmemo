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
import signal
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# ── 단일 인스턴스 보장 (PID 파일) ─────────────────────
PID_FILE = os.path.join(os.path.dirname(__file__), "data", ".orchestrator.pid")
os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)

def _kill_existing():
    """기존 orchestrator 프로세스 종료"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE) as f:
                old_pid = int(f.read().strip())
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
    curator = CuratorAgent(
        notion_db_id=config.get("NOTION_DATABASE_ID", ""),
        **common_kwargs,
    )

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

    slack.on_command("수집", cmd_collect)
    slack.on_command("브리핑", cmd_briefing)
    slack.on_command("상태", cmd_status)

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
        # 최근 100건만 유지
        data = data[-100:]
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

        # 1단계: 과거 경험 로드
        past_exp = load_experience()
        exp_summary = ""
        if past_exp:
            recent = past_exp[-5:]
            exp_lines = [f"- {e['task_type']}: \"{e.get('query','')}\" → {e.get('result','')}" for e in recent]
            exp_summary = "\n".join(exp_lines)

        # 2단계: LLM으로 의도 파악 + 대화형 응답 생성
        intent_response = await curator.ai_think(
            system_prompt=f"""당신은 슬랙에서 사용자를 도와주는 AI 어시스턴트입니다.
사용자의 메시지를 분석하여 의도를 파악하고, 자연스러운 한국어로 응답하세요.

당신이 할 수 있는 업무:
- collect: 뉴스/정보 수집 (구글뉴스 RSS 기반)
- briefing: 수집된 정보 브리핑/요약
- status: 시스템 상태 확인
- chat: 일반 대화

{("과거 작업 이력:" + chr(10) + exp_summary + chr(10) + "이 경험을 참고하여 더 나은 방법을 제안하세요.") if exp_summary else "아직 작업 경험이 없습니다. 처음 하는 업무라면 솔직하게 말하세요."}

응답 형식 (반드시 JSON):
{{
  "intent": "collect|briefing|status|chat|ignore",
  "query": "수집 키워드 (collect일 때만)",
  "ack_message": "사용자에게 먼저 보낼 확인 메시지. 자연스럽고 친근하게. 어떤 업무인지 설명하고 어떻게 진행할지 간단히 안내. 과거에 비슷한 경험이 있으면 언급. 처음이면 '처음 해보는 유형이라 최선을 다해볼게요' 같이.",
  "approach": "이번 작업에서 사용할 방법/전략 (나중에 경험으로 저장됨)"
}}""",
            user_prompt=text,
        )

        try:
            clean = intent_response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = _json.loads(clean)
        except (Exception,) as e:
            logger.warning(f"[NL] Parse error: {e}, raw: {intent_response[:100]}")
            return

        action = parsed.get("intent", "ignore")
        ack = parsed.get("ack_message", "")
        approach = parsed.get("approach", "")
        query = parsed.get("query", "").strip()

        logger.info(f"[NL] Intent: {action}, query: {query}")

        if action == "ignore":
            return

        # 3단계: 접수 표시 (눈 리액션 + 한줄 접수 메시지)
        ACK_MESSAGES = {
            "collect": "👀 수집 시작합니다! 잠시만요~",
            "briefing": "👀 브리핑 준비 중! 금방 가져올게요~",
            "status": "👀 상태 확인 중! 잠깐만요~",
        }
        if thread_ts and action in ACK_MESSAGES:
            await slack.add_reaction(channel, thread_ts, "eyes")
            await _reply(channel, ACK_MESSAGES[action], thread_ts)

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
            elif action == "status":
                await cmd_status(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "상태 확인 완료"
            elif action == "chat":
                # 대화는 ack 메시지가 곧 응답
                if ack:
                    await _reply(channel, ack, thread_ts)
                result_text = "대화 응답"
        except Exception as e:
            result_text = f"오류: {str(e)[:100]}"
            success = False
            logger.error(f"[NL] Execution error: {e}")

        # 5단계: 경험 저장
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

    logger.info("Starting all agents...")

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received")
        shutdown_event.set()
        bus.stop()
        collector.stop()
        curator.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # 시작 (알림 없이 조용히)
    await slack.start_background()
    logger.info("Agents started silently (no startup message to Slack)")

    # 에이전트 태스크 실행
    tasks = [
        asyncio.create_task(bus.run(), name="message_bus"),
        asyncio.create_task(collector.start(), name="collector"),
        asyncio.create_task(curator.start(), name="curator"),
    ]

    logger.info("All agents running. Starting polling loop...")

    # 메인 루프: 폴링 + shutdown 대기
    poll_count = 0
    while not shutdown_event.is_set():
        poll_count += 1
        logger.info(f"[main] Poll tick #{poll_count}")
        try:
            await slack.poll_once()
        except Exception as e:
            logger.error(f"Poll error: {e}")
        logger.info(f"[main] Poll tick #{poll_count} done, sleeping 30s")
        # shutdown 체크와 함께 30초 대기
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass  # 30초 지남, 다시 폴링

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
