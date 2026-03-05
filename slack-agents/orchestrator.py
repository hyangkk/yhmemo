"""
Agent Orchestrator - 24/7 에이전트 실행기

모든 에이전트를 생성하고, 메시지 버스를 시작하고,
슬랙 연결을 관리하는 메인 진입점.

실행: python orchestrator.py
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

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
    async def cmd_collect(args: str, user: str, channel: str):
        if args.strip():
            query = args.strip()
            await slack.send_message(channel, f":satellite: `{query}` 수집을 시작합니다...")
            # curator에 검색 키워드 컨텍스트 전달
            curator.set_query_context(query)
            await collector._collect_by_keyword(query, user)
        else:
            await slack.send_message(channel, "사용법: `!수집 키워드`")

    # "!브리핑" → 선별 에이전트에 즉시 브리핑 요청
    async def cmd_briefing(args: str, user: str, channel: str):
        await slack.send_message(channel, "브리핑을 준비합니다...")
        # 강제로 observe → think → act 실행
        context = await curator.observe()
        if context:
            decision = await curator.think(context)
            if decision:
                await curator.act(decision)
        else:
            await slack.send_message(channel, "현재 새로운 정보가 없습니다.")

    # "!상태" → 전체 시스템 상태 확인
    async def cmd_status(args: str, user: str, channel: str):
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        status_msg = f"*시스템 상태* ({now})\n"
        status_msg += f"- Collector: 실행 중 (간격: {collector.loop_interval}초)\n"
        status_msg += f"- Curator: 실행 중 (간격: {curator.loop_interval}초)\n"
        status_msg += f"- Curator 대기 버퍼: {len(curator._new_articles_buffer)}건\n"
        await slack.send_message(channel, status_msg)

    slack.on_command("수집", cmd_collect)
    slack.on_command("브리핑", cmd_briefing)
    slack.on_command("상태", cmd_status)

    # 자연어 메시지 → LLM 의도 파악 후 명령 실행
    async def on_natural_language(text: str, user: str, channel: str, thread_ts: str = None):
        """자연어 메시지를 LLM으로 분석해 적절한 명령 실행"""
        intent = await curator.ai_think(
            system_prompt="""당신은 슬랙 메시지의 의도를 파악하는 분류기입니다.
사용자 메시지를 보고 아래 중 하나로 분류하세요.

의도 목록:
- collect: 정보/뉴스/기사 수집 요청 (예: "봄 페스티벌 행사 찾아줘", "AI 관련 소식 모아줘", "스타트업 뉴스 수집해줘")
- briefing: 브리핑/요약 요청 (예: "오늘 뉴스 요약해줘", "브리핑 해줘", "모은거 정리해줘")
- status: 시스템 상태 확인 (예: "지금 어떤 상태야?", "잘 돌아가고 있어?")
- chat: 일반 대화/질문 (예: "안녕", "뭐 할 수 있어?")
- ignore: 봇과 관련없는 메시지

반드시 아래 JSON 형식으로만 응답하세요:
{"intent": "collect|briefing|status|chat|ignore", "query": "수집 키워드 (collect일 때만)", "reply": "사용자에게 보낼 간단한 답변 (chat일 때만)"}""",
            user_prompt=text,
        )

        try:
            import json
            # JSON 파싱 (마크다운 코드블록 제거)
            clean = intent.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed = json.loads(clean)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[NL] Failed to parse intent: {e}, raw: {intent[:100]}")
            return

        action = parsed.get("intent", "ignore")
        logger.info(f"[NL] Intent: {action}, query: {parsed.get('query', '')}")

        if action == "collect":
            query = parsed.get("query", "").strip()
            if query:
                await cmd_collect(args=query, user=user, channel=channel)
            else:
                await slack.send_message(channel, "무엇을 수집할까요? 키워드를 알려주세요.")
        elif action == "briefing":
            await cmd_briefing(args="", user=user, channel=channel)
        elif action == "status":
            await cmd_status(args="", user=user, channel=channel)
        elif action == "chat":
            reply = parsed.get("reply", "")
            if reply:
                if thread_ts:
                    await slack.send_thread_reply(channel, thread_ts, reply)
                else:
                    await slack.send_message(channel, reply)

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

    # 시작 알림
    await slack.start_background()
    await slack.send_message(
        SlackClient.CHANNEL_GENERAL,
        f"*AI 에이전트 시스템 시작* ({datetime.now(KST).strftime('%Y-%m-%d %H:%M')})\n"
        f"- Collector: {collector.loop_interval}초 간격 자율 수집\n"
        f"- Curator: {curator.loop_interval}초 간격 자율 선별\n"
        f"명령어: `!수집 키워드`, `!브리핑`, `!상태`\n"
        f"자연어도 OK: \"봄 페스티벌 행사 찾아줘\" 처럼 편하게 말씀하세요!",
    )

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
    asyncio.run(main())
