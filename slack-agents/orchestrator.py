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
from agents.invest_agent import InvestAgent
from agents.investment_agent import InvestmentAgent
from core import agent_tracker

from handlers.command_handler import CommandHandler, _reply
from handlers.nl_router import NLRouter
from handlers.dev_runner import DevRunner
from handlers.watchdog import MasterWatchdog

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

    supabase = create_client(config["SUPABASE_URL"], config["SUPABASE_SERVICE_ROLE_KEY"])

    slack = SlackClient(
        bot_token=config["SLACK_BOT_TOKEN"],
        app_token=config["SLACK_APP_TOKEN"],
    )

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
    invest = InvestAgent(**common_kwargs)
    investment = InvestmentAgent(**common_kwargs)

    # ── 핸들러 인스턴스 생성 ───────────────────────────
    dev_runner = DevRunner(summarizer=curator)
    cmd_handler = CommandHandler(slack, collector, curator, quote, investment)
    nl_router = NLRouter(slack, curator, cmd_handler, dev_runner)

    # ── 슬랙 명령어 & 이벤트 핸들러 등록 ──────────────
    cmd_handler.register()
    slack.on_natural_language(nl_router.handle)

    # 이모지 반응 → 선별 에이전트 피드백 학습 + 제안 승인/거절
    async def on_reaction(reaction: str, item: dict, user: str):
        message_ts = item.get("ts", "")
        if message_ts:
            result = proactive.handle_proposal_reaction(reaction, message_ts)
            if result:
                state = result["new_state"]
                title = result["title"]
                if state == "approved":
                    await _reply(
                        slack,
                        item.get("channel", "ai-agents-general"),
                        f"✅ *'{title}' 승인됨!* 다음 사이클에서 실행을 시작합니다.",
                        message_ts,
                    )
                elif state == "rejected":
                    await _reply(
                        slack,
                        item.get("channel", "ai-agents-general"),
                        f"❌ *'{title}' 거절됨.* 피드백이 있으면 알려주세요.",
                        message_ts,
                    )
                return

        await curator.handle_reaction_feedback(reaction, item)

    slack.on_reaction(on_reaction)

    # 멘션 → AI가 자유롭게 응답
    async def on_mention(text: str, user: str, channel: str, say):
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
        invest.stop()
        investment.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Socket Mode 먼저 시도 → 실패 시 폴링으로 전환
    socket_mode = await slack._try_socket_mode()

    if socket_mode:
        logger.info("✓ Socket Mode 연결 성공! 실시간 이벤트 수신 중 (폴링 불필요)")
        await slack.ensure_channels_exist()
        await slack._init_channel_cache()
    else:
        logger.info("Socket Mode 불가 → 폴링 모드로 운영")
        await slack.start_background()

    logger.info("Agents started silently (no startup message to Slack)")

    # 에이전트 태스크 실행 (재시작 가능하도록 팩토리 패턴)
    agent_starters = {
        "message_bus": lambda: asyncio.create_task(bus.run(), name="message_bus"),
        "collector": lambda: asyncio.create_task(collector.start(), name="collector"),
        "curator": lambda: asyncio.create_task(curator.start(), name="curator"),
        "quote": lambda: asyncio.create_task(quote.start(), name="quote"),
        "proactive": lambda: asyncio.create_task(proactive.start(), name="proactive"),
        "invest": lambda: asyncio.create_task(invest.start(), name="invest"),
        "investment": lambda: asyncio.create_task(investment.start(), name="investment"),
    }
    agent_tasks = {name: starter() for name, starter in agent_starters.items()}

    # ── 마스터 워치독 ─────────────────────────────────
    HEALTH_CHECK_INTERVAL = 600  # 10분 (초)
    last_health_check_time = asyncio.get_event_loop().time()
    watchdog = MasterWatchdog(slack, agent_tasks, agent_starters)

    # ── 마스터 명령 큐 처리 ───────────────────────────────
    COMMAND_QUEUE_FILE = os.path.join(os.path.dirname(__file__), "data", "command_queue.json")

    async def process_command_queue():
        """마스터 오케스트레이터(Claude Code)가 보낸 명령을 처리"""
        try:
            if not os.path.exists(COMMAND_QUEUE_FILE):
                return
            with open(COMMAND_QUEUE_FILE, "r", encoding="utf-8") as f:
                commands = json.loads(f.read())
            if not commands:
                return
            # 큐 즉시 비움 (중복 실행 방지)
            with open(COMMAND_QUEUE_FILE, "w") as f:
                f.write("[]")

            for cmd in commands:
                cmd_type = cmd.get("type", "")
                logger.info(f"[master] Executing command: {cmd_type}")
                try:
                    if cmd_type == "send_message":
                        channel = cmd.get("channel", "ai-agents-general")
                        text = cmd.get("text", "")
                        thread_ts = cmd.get("thread_ts")
                        if thread_ts:
                            await slack.send_thread_reply(channel, thread_ts, text)
                        else:
                            await slack.send_message(channel, text)

                    elif cmd_type == "dev":
                        task_desc = cmd.get("task", "")
                        channel = cmd.get("channel", "ai-agents-general")
                        thread_ts = cmd.get("thread_ts")
                        if task_desc:
                            full_prompt = dev_runner.build_prompt(task_desc)
                            start_msg = f"🎯 *[마스터]* dev 작업 지시\n> {task_desc[:200]}"
                            if thread_ts:
                                await _reply(slack, channel, start_msg, thread_ts)
                            else:
                                await slack.send_message(channel, start_msg)

                            result = await dev_runner.run(full_prompt)
                            if result["success"]:
                                done_msg = f"✅ *[마스터]* 작업 완료!\n\n{result['output'][:3000]}"
                            else:
                                done_msg = f"⚠️ *[마스터]* 작업 오류:\n```{result['error'][:500]}```"
                                logger.error(f"[master] Dev command failed: {result['error'][:200]}")

                            if thread_ts:
                                await _reply(slack, channel, done_msg, thread_ts)
                            else:
                                await slack.send_message(channel, done_msg)

                    elif cmd_type == "collect":
                        query = cmd.get("query", "")
                        if query:
                            await cmd_handler.cmd_collect(args=query, user="master", channel="ai-agents-general")

                    elif cmd_type == "briefing":
                        await cmd_handler.cmd_briefing(args="", user="master", channel="ai-agents-general")

                    elif cmd_type == "trigger_proactive":
                        action = cmd.get("action", "find_work")
                        logger.info(f"[master] Triggering proactive: {action}")
                        handler = getattr(proactive, f"_do_{action}", None)
                        if handler:
                            ctx = await proactive.observe()
                            await handler(ctx)

                    elif cmd_type == "slack_reply":
                        channel = cmd.get("channel", "ai-agents-general")
                        thread_ts = cmd.get("thread_ts")
                        text = cmd.get("text", "")
                        if text and thread_ts:
                            await nl_router.handle(
                                text=text, user="master", channel=channel, thread_ts=thread_ts
                            )

                    logger.info(f"[master] Command '{cmd_type}' completed")
                except Exception as e:
                    logger.error(f"[master] Command '{cmd_type}' failed: {e}")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        except Exception as e:
            logger.error(f"[master] Queue processing error: {e}")

    # ── 메인 이벤트 루프 ─────────────────────────────────
    if socket_mode:
        logger.info("All agents running. Socket Mode active + watchdog enabled (10분 점검)")
        while not shutdown_event.is_set():
            loop_time = asyncio.get_event_loop().time()
            if loop_time - last_health_check_time >= HEALTH_CHECK_INTERVAL:
                last_health_check_time = loop_time
                try:
                    await watchdog.check()
                except Exception as e:
                    logger.error(f"[watchdog] Health check error: {e}")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
    else:
        logger.info("All agents running. Polling (3s) + watchdog (10분 점검) 시작...")
        poll_count = 0
        while not shutdown_event.is_set():
            poll_count += 1
            agent_tracker.heartbeat("orchestrator")
            if poll_count % 20 == 1:
                thread_count = sum(len(v) for v in slack._active_threads.values())
                logger.info(f"[main] Poll tick #{poll_count} (alive, {thread_count} threads tracked)")
            try:
                await slack.poll_once()
                await process_command_queue()
            except Exception as e:
                logger.error(f"Poll error: {e}")

            loop_time = asyncio.get_event_loop().time()
            if loop_time - last_health_check_time >= HEALTH_CHECK_INTERVAL:
                last_health_check_time = loop_time
                try:
                    await watchdog.check()
                except Exception as e:
                    logger.error(f"[watchdog] Health check error: {e}")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass

    # 태스크 정리
    for task in agent_tasks.values():
        task.cancel()
    await asyncio.gather(*agent_tasks.values(), return_exceptions=True)

    if notion:
        await notion.close()

    logger.info("Orchestrator shut down cleanly")


if __name__ == "__main__":
    # 자동 재시작 래퍼: 예기치 않은 크래시 시 재기동
    max_restarts = 50  # 밤새 안정 운영을 위해 충분한 재시작 횟수
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
