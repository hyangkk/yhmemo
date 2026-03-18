"""
Agent Orchestrator - 24/7 에이전트 실행기

모든 에이전트를 생성하고, 메시지 버스를 시작하고,
슬랙 연결을 관리하는 메인 진입점.

실행: python orchestrator.py

핵심 로직은 다음 모듈에 위임:
- core/intent_router.py: 자연어 의도 분류 + dev/chat 처리
- core/command_handler.py: 슬랙 !명령어 처리
- core/agent_manager.py: 에이전트 생명주기 관리
- core/watchdog.py: 워치독 헬스체크 + 로그 파싱
"""

import asyncio
import json
import logging
import os
import re
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
from core.agent_manager import AgentManager
from core.command_handler import CommandHandler
from core.intent_router import IntentRouter, handle_dev_action, handle_chat_action
from core.conversation_memory import save_turn, get_user_summary
from core import agent_tracker
from core import watchdog
from integrations.slack_client import SlackClient
from integrations.notion_client import NotionClient
from integrations.ls_securities import LSSecuritiesClient

# ── 로깅 설정 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")

_log_dir = os.path.join(os.path.dirname(__file__), "data", "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_date = datetime.now(timezone.utc).strftime("%Y%m%d")
_file_handler = logging.FileHandler(
    os.path.join(_log_dir, f"orchestrator-{_log_date}.log"), encoding="utf-8",
)
_file_handler.setLevel(logging.INFO)
_log_formatter = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_file_handler.setFormatter(_log_formatter)
logging.getLogger().addHandler(_file_handler)

def _rotate_log_file_if_needed():
    """UTC 날짜가 바뀌면 새 로그 파일로 교체"""
    global _log_date, _file_handler
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if today != _log_date:
        root = logging.getLogger()
        root.removeHandler(_file_handler)
        _file_handler.close()
        _log_date = today
        _file_handler = logging.FileHandler(os.path.join(_log_dir, f"orchestrator-{today}.log"), encoding="utf-8")
        _file_handler.setLevel(logging.INFO)
        _file_handler.setFormatter(_log_formatter)
        root.addHandler(_file_handler)

KST = timezone(timedelta(hours=9))

# ── 경험 저장소 ────────────────────────────────────────
_experience_file = os.path.join(os.path.dirname(__file__), "data", "experience.json")
os.makedirs(os.path.dirname(_experience_file), exist_ok=True)

def load_experience() -> list[dict]:
    try:
        with open(_experience_file, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_experience(entry: dict):
    data = load_experience()
    data.append(entry)
    data = data[-500:]
    with open(_experience_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))


def load_config() -> dict:
    """환경변수에서 설정 로드"""
    required = ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    config = {}
    missing = []
    for key in required:
        val = os.environ.get(key)
        if not val:
            missing.append(key)
        config[key] = val
    if missing:
        logger.error(f"Missing required env vars: {', '.join(missing)}")
        sys.exit(1)

    config["NOTION_API_KEY"] = os.environ.get("NOTION_API_KEY", "")
    config["NOTION_DATABASE_ID"] = os.environ.get("NOTION_DATABASE_ID", "")
    config["NOTION_TASK_BOARD_DB_ID"] = os.environ.get("NOTION_TASK_BOARD_DB_ID", "")
    config["DIARY_NOTION_DATABASE_ID"] = os.environ.get("DIARY_NOTION_DATABASE_ID", "")

    # secrets_vault / agent_settings 에서 보조 설정 로드
    sb_url = config.get("SUPABASE_URL", "")
    sb_key = config.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if sb_url and sb_key:
        import urllib.request
        if not config["NOTION_API_KEY"]:
            try:
                req = urllib.request.Request(
                    f"{sb_url}/rest/v1/secrets_vault?select=value&key=eq.NOTION_API_KEY",
                    headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    rows = json.loads(resp.read())
                    if rows and rows[0].get("value"):
                        config["NOTION_API_KEY"] = rows[0]["value"]
            except Exception as e:
                logger.warning(f"Failed to load NOTION_API_KEY: {e}")
        try:
            req = urllib.request.Request(
                f"{sb_url}/rest/v1/agent_settings?select=diary_notion_database_id,board_notion_db_id",
                headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                settings = json.loads(resp.read())
                if settings:
                    s = settings[0]
                    if not config["DIARY_NOTION_DATABASE_ID"] and s.get("diary_notion_database_id"):
                        config["DIARY_NOTION_DATABASE_ID"] = s["diary_notion_database_id"]
                    if not config["NOTION_TASK_BOARD_DB_ID"] and s.get("board_notion_db_id"):
                        config["NOTION_TASK_BOARD_DB_ID"] = s["board_notion_db_id"]
        except Exception as e:
            logger.warning(f"Failed to load agent_settings: {e}")
    return config


async def main():
    config = load_config()

    # ── 외부 서비스 초기화 ──────────────────────────────
    budget = os.environ.get("DAILY_AI_BUDGET_USD", "10.0")
    logger.info(f"Initializing services... (AI budget: ${budget}/day)")

    try:
        from studio_api import start_studio_server
        import time as _time
        studio_thread = start_studio_server(port=8000)
        _time.sleep(2)
        logger.info(f"Studio API: thread_alive={studio_thread.is_alive()}")
    except Exception as e:
        logger.warning(f"Studio API 서버 시작 실패 (무시): {e}")

    supabase = create_client(config["SUPABASE_URL"], config["SUPABASE_SERVICE_ROLE_KEY"])
    slack = SlackClient(bot_token=config["SLACK_BOT_TOKEN"], app_token=config["SLACK_APP_TOKEN"])
    notion = NotionClient(api_key=config["NOTION_API_KEY"]) if config["NOTION_API_KEY"] else None
    ls_client = None
    if os.environ.get("LS_APP_KEY"):
        paper = os.environ.get("LS_PAPER_TRADING", "true").lower() == "true"
        ls_client = LSSecuritiesClient(paper_trading=paper)
    bus = MessageBus(supabase_client=supabase)

    # ── 에이전트 매니저 ─────────────────────────────────
    agent_mgr = AgentManager()
    agent_mgr.create_all_from_config(config, supabase, slack, notion, ls_client, bus)
    curator = agent_mgr.get("curator")
    proactive = agent_mgr.get("proactive")

    # ── 명령어 핸들러 ──────────────────────────────────
    cmd = CommandHandler(
        slack=slack, supabase=supabase, notion=notion, ls_client=ls_client,
        collector=agent_mgr.get("collector"), curator=curator,
        quote=agent_mgr.get("quote"), diary_quote=agent_mgr.get("diary_quote"),
        diary_daily_alert=agent_mgr.get("diary_daily_alert"), fortune=agent_mgr.get("fortune"),
        sentiment=agent_mgr.get("sentiment"), bulletin=agent_mgr.get("bulletin"),
        qa=agent_mgr.get("qa"), proactive=proactive,
        auto_trader=agent_mgr.get("auto_trader"), market_info=agent_mgr.get("market_info"),
        swing_trader=agent_mgr.get("swing_trader"), invest_research=agent_mgr.get("invest_research"),
        task_board=agent_mgr.get("task_board"),
        agent_hr=agent_mgr.agent_hr, invest_monitor=agent_mgr.invest_monitor,
    )
    cmd.register_all()

    # ── 의도 분류기 ────────────────────────────────────
    intent_router = IntentRouter(ai_think_fn=curator.ai_think)

    # ── 자연어 메시지 처리 ──────────────────────────────
    async def on_natural_language(text: str, user: str, channel: str, thread_ts: str = None):
        save_turn(user, "user", text)

        # 스레드 맥락 수집
        thread_context = ""
        if thread_ts:
            try:
                ch_id = await slack._resolve_channel(channel) if not channel.startswith("C") else channel
                resp = await slack.client.conversations_replies(channel=ch_id, ts=thread_ts, limit=10)
                msgs = resp.get("messages", [])
                lines = [f"[{'봇' if m.get('bot_id') else '유저'}] {m.get('text', '')[:300]}"
                         for m in msgs if m.get("ts") == thread_ts or m.get("text") != text]
                thread_context = "\n".join(lines[-8:]) if lines else ""
            except Exception:
                pass

        # 경험/유저 맥락
        past_exp = load_experience()
        exp_summary = "\n".join(f"- {e['task_type']}: \"{e.get('query','')}\" → {e.get('result','')}" for e in past_exp[-15:]) if past_exp else ""
        user_context = get_user_summary(user)

        # 의도 분류
        parsed = await intent_router.classify(text, thread_context, exp_summary, user_context)
        if not parsed or parsed.intent == "ignore":
            return

        if parsed.intent == "clarify":
            await cmd._reply(channel, parsed.clarify_question or "좀 더 구체적으로 말씀해주세요.", thread_ts)
            return

        if thread_ts and parsed.ack:
            await slack.add_reaction(channel, thread_ts, "eyes")
            await cmd._reply(channel, parsed.ack, thread_ts)

        # 의도별 디스패치
        action = parsed.intent
        result_text, success = "", True
        try:
            dispatch = {
                "collect": lambda: cmd.cmd_collect(parsed.query or "", user, channel, thread_ts),
                "briefing": lambda: cmd.cmd_briefing("", user, channel, thread_ts),
                "dashboard": lambda: cmd.cmd_dashboard("", user, channel, thread_ts),
                "status": lambda: cmd.cmd_dashboard("", user, channel, thread_ts),
                "quote": lambda: cmd.cmd_quote("", user, channel, thread_ts),
                "diary_quote": lambda: cmd.cmd_diary_quote("", user, channel, thread_ts),
                "diary_daily_alert": lambda: cmd.cmd_diary_daily_alert("", user, channel, thread_ts),
                "fortune": lambda: cmd.cmd_fortune("", user, channel, thread_ts),
                "invest_status": lambda: cmd.cmd_invest_status("", user, channel, thread_ts),
                "hr_eval": lambda: cmd.cmd_hr_eval("", user, channel, thread_ts),
                "qa": lambda: cmd.cmd_qa("", user, channel, thread_ts),
                "bulletin": lambda: cmd.cmd_bulletin("", user, channel, thread_ts),
            }
            if action in dispatch:
                await dispatch[action]()
                result_text = f"{action} 완료"
            elif action == "hr_status":
                await cmd.cmd_hr_status(parsed.hr_target, user, channel, thread_ts)
                result_text = "인사현황 조회 완료"
            elif action == "hr_salary":
                if parsed.hr_target and parsed.hr_amount:
                    await cmd.cmd_salary(f"{parsed.hr_target} {parsed.hr_amount} {parsed.hr_reason}".strip(), user, channel, thread_ts)
                else:
                    await cmd.cmd_salary("", user, channel, thread_ts)
                result_text = "연봉 조회/조정 완료"
            elif action == "stock_trade":
                result_text, success = await _dispatch_stock(parsed, cmd, user, channel, thread_ts)
            elif action == "naver_blog":
                result_text, success = await _dispatch_blog(parsed, text, cmd, user, channel, thread_ts)
            elif action == "dev":
                result_text, success = await handle_dev_action(parsed, text, thread_context, channel, thread_ts, user, curator, supabase, cmd._reply)
            elif action == "chat":
                result_text = await handle_chat_action(text, user, channel, thread_ts, thread_context, exp_summary, curator, proactive, slack, cmd._reply)
        except Exception as e:
            result_text, success = f"오류: {str(e)[:100]}", False
            logger.error(f"[NL] Execution error: {e}")

        if action != "chat":
            save_experience({"task_type": action, "query": parsed.query, "user_message": text[:200],
                             "approach": parsed.approach, "result": result_text, "success": success,
                             "timestamp": datetime.now(KST).isoformat()})
            save_turn(user, "assistant", f"[{action}] {result_text}", {"action": action})

    slack.on_natural_language(on_natural_language)

    # ── 이모지 반응 / 멘션 ──────────────────────────────
    async def on_reaction(reaction: str, item: dict, user: str):
        ts = item.get("ts", "")
        if ts:
            result = proactive.handle_proposal_reaction(reaction, ts)
            if result:
                ch = item.get("channel", SlackClient.CHANNEL_GENERAL)
                msg = f"✅ *'{result['title']}' 승인됨!*" if result["new_state"] == "approved" else f"❌ *'{result['title']}' 거절됨.*"
                await cmd._reply(ch, msg, ts)
                return
        await curator.handle_reaction_feedback(reaction, item)
    slack.on_reaction(on_reaction)

    async def on_mention(text: str, user: str, channel: str, say):
        clean = text.split(">", 1)[-1].strip() if ">" in text else text
        if clean:
            await say(await curator.ai_think(system_prompt="정보 관리 AI. 간결하게 답하세요.", user_prompt=clean))
    slack.on_mention(on_mention)

    # ── 에이전트 시작 + shutdown ────────────────────────
    logger.info("Starting all agents...")
    agent_mgr.start_all_tasks()
    asyncio.create_task(agent_mgr.delayed_dynamic_start(), name="dynamic_agents_init")
    shutdown_event = asyncio.Event()
    agent_mgr.setup_shutdown(shutdown_event)

    # ── Socket Mode 또는 폴링 ──────────────────────────
    socket_mode = await slack._try_socket_mode()
    if socket_mode:
        logger.info("Socket Mode 연결 성공")
        await slack.ensure_channels_exist()
        await slack._init_channel_cache()
        import time as _t
        slack._poll_channels = [slack.CHANNEL_GENERAL, slack.CHANNEL_INVEST]
        for ch_id in slack._poll_channels:
            slack._last_ts[ch_id] = str(_t.time())
        slack._running = True
    else:
        logger.info("Socket Mode 불가 → 폴링 모드")
        await slack.start_background()

    # ── 메인 루프 (폴링 + 워치독) ──────────────────────
    last_report_slot = ""
    CMD_Q = os.path.join(os.path.dirname(__file__), "data", "command_queue.json")
    poll_interval = 30 if socket_mode else 3

    async def _process_cmd_queue():
        try:
            if not os.path.exists(CMD_Q): return
            with open(CMD_Q, "r", encoding="utf-8") as f: cmds = json.loads(f.read())
            if not cmds: return
            with open(CMD_Q, "w") as f: f.write("[]")
            for c in cmds:
                t = c.get("type", "")
                try:
                    if t == "send_message":
                        await cmd._reply(c.get("channel", SlackClient.CHANNEL_GENERAL), c.get("text",""), c.get("thread_ts"))
                    elif t == "collect" and c.get("query"):
                        await cmd.cmd_collect(c["query"], "master", SlackClient.CHANNEL_GENERAL)
                    elif t == "briefing":
                        await cmd.cmd_briefing("", "master", SlackClient.CHANNEL_GENERAL)
                    elif t == "slack_reply" and c.get("text") and c.get("thread_ts"):
                        await on_natural_language(c["text"], "master", c.get("channel", SlackClient.CHANNEL_GENERAL), c["thread_ts"])
                except Exception as e:
                    logger.error(f"[master] Command '{t}' failed: {e}")
        except Exception:
            pass

    async def _health_check():
        _rotate_log_file_if_needed()
        now = datetime.now(KST)
        issues, restarts = await agent_mgr.watchdog_health_check()
        past = watchdog.parse_recent_log_activities(now)
        watchdog.check_plan_fulfillment(past)
        nxt = watchdog.get_next_1h_plan(now)
        watchdog.save_planned_tasks(now.strftime("%H:%M"), nxt)
        if now.strftime("%H:%M") == "09:00":
            try:
                r = await agent_mgr.agent_hr.run_daily_evaluation()
                if not r.get("already_done"):
                    await slack.send_message(SlackClient.CHANNEL_GENERAL, agent_mgr.agent_hr.format_evaluation_result(r))
            except Exception as e: logger.error(f"[HR] 자동 인사평가 실패: {e}")
        if now.strftime("%H:%M") == "16:00":
            try:
                ev = await agent_mgr.invest_monitor.evaluate_invest_agents(days=7)
                await slack.send_message(SlackClient.CHANNEL_INVEST, agent_mgr.invest_monitor.format_report(ev))
            except Exception as e: logger.error(f"[invest_monitor] 정기 모니터링 실패: {e}")
        if issues or restarts:
            lines = [f"*🔍 마스터 점검* ({now.strftime('%H:%M')} KST)"]
            if restarts: lines.append(f"🔄 자동 재시작: *{', '.join(restarts)}*")
            lines.extend(issues)
            try: await slack.send_message(SlackClient.CHANNEL_LOGS, "\n".join(lines))
            except Exception: pass

    tick = 0
    while not shutdown_event.is_set():
        agent_tracker.heartbeat("orchestrator")
        tick += 1
        try:
            await slack.poll_once()
            await _process_cmd_queue()
        except Exception as e:
            logger.error(f"Poll error: {e}")
        now_kst = datetime.now(KST)
        slot = f"{now_kst.hour}:00"
        if now_kst.minute == 0 and now_kst.hour % 4 == 0 and slot != last_report_slot:
            last_report_slot = slot
            try: await _health_check()
            except Exception as e: logger.error(f"[watchdog] error: {e}")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass

    await agent_mgr.cleanup_tasks()
    logger.info("Orchestrator shut down cleanly")


async def _dispatch_stock(parsed, cmd, user, channel, thread_ts):
    """stock_trade 인텐트 디스패치"""
    if parsed.stock_action == "balance":
        await cmd.cmd_balance("", user, channel, thread_ts)
        return "잔고 조회 완료", True
    elif parsed.stock_action == "price" and parsed.stock_code:
        await cmd.cmd_price(parsed.stock_code, user, channel, thread_ts)
        return f"시세 조회: {parsed.stock_code}", True
    elif parsed.stock_action == "buy" and parsed.stock_code:
        p = f" {parsed.stock_price}" if parsed.stock_price else ""
        await cmd.cmd_buy(f"{parsed.stock_code} {parsed.stock_qty}{p}", user, channel, thread_ts)
        return f"매수: {parsed.stock_code} {parsed.stock_qty}주", True
    elif parsed.stock_action == "sell" and parsed.stock_code:
        p = f" {parsed.stock_price}" if parsed.stock_price else ""
        await cmd.cmd_sell(f"{parsed.stock_code} {parsed.stock_qty}{p}", user, channel, thread_ts)
        return f"매도: {parsed.stock_code} {parsed.stock_qty}주", True
    else:
        await cmd._reply(channel, "매매 명령을 이해하지 못했어요.", thread_ts)
        return "stock_trade 파싱 실패", False


async def _dispatch_blog(parsed, text, cmd, user, channel, thread_ts):
    """naver_blog 인텐트 디스패치"""
    urls = parsed.blog_urls or re.findall(r'https?://(?:m\.)?blog\.naver\.com/\S+', text)
    want = any(kw in text for kw in ["최신글", "최신 글", "가져와", "크롤링", "읽어", "본문"])
    if urls:
        args = urls[0] + (" 5" if want else "")
        await cmd.cmd_blog(args, user, channel, thread_ts, fetch_posts=want)
        return f"블로그 스크래핑 {len(urls)}건", True
    else:
        await cmd._reply(channel, "블로그 URL을 찾지 못했어요. URL을 함께 보내주세요.", thread_ts)
        return "naver_blog URL 없음", False


if __name__ == "__main__":
    max_restarts = 50
    restart_count = 0
    while restart_count < max_restarts:
        try:
            asyncio.run(main())
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            restart_count += 1
            logger.error(f"Orchestrator crashed ({restart_count}/{max_restarts}): {e}")
            if restart_count < max_restarts:
                import time; time.sleep(10)
            else:
                logger.critical("Max restarts reached. Exiting.")
