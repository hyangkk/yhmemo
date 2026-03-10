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
from agents.invest_agent import InvestAgent
from agents.invest_report_agent import InvestReportAgent
from agents.task_board_agent import TaskBoardAgent
from agents.fortune_agent import FortuneAgent
from agents.diary_quote_agent import DiaryQuoteAgent
from agents.sentiment_agent import SentimentAgent
from integrations.ls_securities import LSSecuritiesClient, friendly_error_message
from core.conversation_memory import save_turn, build_chat_context, get_user_summary
from core.tools import TOOL_DEFINITIONS, execute_tool_calls
from core import agent_tracker
from core.agent_hr import AgentHR

# ── 로깅 설정 ──────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator")

# 파일 로깅 추가 — 오케스트레이션 가동 리포트에서 활동 내역 파싱용
_log_dir = os.path.join(os.path.dirname(__file__), "data", "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_date = datetime.now(timezone.utc).strftime("%Y%m%d")
_file_handler = logging.FileHandler(
    os.path.join(_log_dir, f"orchestrator-{_log_date}.log"),
    encoding="utf-8",
)
_file_handler.setLevel(logging.INFO)
_log_formatter = logging.Formatter(
    "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_file_handler.setFormatter(_log_formatter)
logging.getLogger().addHandler(_file_handler)


def _rotate_log_file_if_needed():
    """UTC 날짜가 바뀌면 새 로그 파일로 교체"""
    global _log_date, _file_handler
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if today != _log_date:
        root_logger = logging.getLogger()
        root_logger.removeHandler(_file_handler)
        _file_handler.close()
        _log_date = today
        _file_handler = logging.FileHandler(
            os.path.join(_log_dir, f"orchestrator-{today}.log"),
            encoding="utf-8",
        )
        _file_handler.setLevel(logging.INFO)
        _file_handler.setFormatter(_log_formatter)
        root_logger.addHandler(_file_handler)
        logger.info(f"[log] Rotated to new log file: orchestrator-{today}.log")

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
    config["NOTION_TASK_BOARD_DB_ID"] = os.environ.get("NOTION_TASK_BOARD_DB_ID", "")
    config["DIARY_NOTION_DATABASE_ID"] = os.environ.get("DIARY_NOTION_DATABASE_ID", "")

    # NOTION_API_KEY가 env에 없으면 secrets_vault에서 로드
    if not config["NOTION_API_KEY"]:
        try:
            sb_url = config.get("SUPABASE_URL", "")
            sb_key = config.get("SUPABASE_SERVICE_ROLE_KEY", "")
            if sb_url and sb_key:
                import urllib.request
                req = urllib.request.Request(
                    f"{sb_url}/rest/v1/secrets_vault?select=value&key=eq.NOTION_API_KEY",
                    headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    rows = json.loads(resp.read())
                    if rows and rows[0].get("value"):
                        config["NOTION_API_KEY"] = rows[0]["value"]
                        logger.info("Loaded NOTION_API_KEY from secrets_vault")
        except Exception as e:
            logger.warning(f"Failed to load NOTION_API_KEY from secrets_vault: {e}")

    # Supabase agent_settings에서 설정 로드 (env var 미설정 시 폴백)
    try:
        sb_url = config.get("SUPABASE_URL", "")
        sb_key = config.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if sb_url and sb_key:
            import urllib.request
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
                        logger.info(f"Loaded diary DB ID from agent_settings")
                    if not config["NOTION_TASK_BOARD_DB_ID"] and s.get("board_notion_db_id"):
                        config["NOTION_TASK_BOARD_DB_ID"] = s["board_notion_db_id"]
                        logger.info(f"Loaded task board DB ID from agent_settings")
    except Exception as e:
        logger.warning(f"Failed to load agent_settings from Supabase: {e}")

    return config


async def main():
    config = load_config()

    # ── 외부 서비스 클라이언트 초기화 ───────────────────

    budget = os.environ.get("DAILY_AI_BUDGET_USD", "10.0")
    logger.info(f"Initializing services... (AI budget: ${budget}/day)")

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

    # LS증권 (선택적, 기본값: 모의투자)
    ls_client = None
    if os.environ.get("LS_APP_KEY"):
        paper = os.environ.get("LS_PAPER_TRADING", "true").lower() == "true"
        ls_client = LSSecuritiesClient(paper_trading=paper)
        mode = "모의투자" if paper else "실전투자"
        logger.info(f"LS증권 Open API 연동 활성화 ({mode})")

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

    collector = CollectorAgent(**common_kwargs)      # 인스턴스만 생성 (루프 미시작)
    proactive = ProactiveAgent(**common_kwargs)
    curator = CuratorAgent(                          # 인스턴스만 생성 (루프 미시작)
        notion_db_id=config.get("NOTION_DATABASE_ID", ""),
        **common_kwargs,
    )
    quote = QuoteAgent(**common_kwargs)
    diary_quote = DiaryQuoteAgent(
        diary_db_id=config.get("DIARY_NOTION_DATABASE_ID", ""),
        **common_kwargs,
    )
    fortune = FortuneAgent(**common_kwargs)
    sentiment = SentimentAgent(**common_kwargs)
    # invest = InvestAgent(**common_kwargs)        # 비용 절감 위해 비활성화
    # invest_report = InvestReportAgent(**common_kwargs)  # 비용 절감 위해 비활성화
    task_board = TaskBoardAgent(
        task_board_db_id=config.get("NOTION_TASK_BOARD_DB_ID", ""),
        **common_kwargs,
    )

    # ── 인사관리 (HR) 시스템 ─────────────────────────────
    agent_hr = AgentHR(
        ai_think_fn=curator.ai_think,
        supabase_client=supabase,
    )
    # 기존 에이전트들 HR 등록
    for _agent_name in ["orchestrator", "proactive", "collector", "curator",
                        "sentiment", "task_board", "diary_quote", "quote",
                        "fortune", "message_bus"]:
        agent_hr.ensure_registered(_agent_name)

    # ── Level 5: 동적 에이전트 시작 ──────────────────────
    # ProactiveAgent의 agent_factory가 초기화된 후, 기존 동적 에이전트를 로드+시작
    async def start_dynamic_agents():
        try:
            started = await proactive.agent_factory.start_all_active()
            if started > 0:
                logger.info(f"[orchestrator] Started {started} dynamic agents")
        except Exception as e:
            logger.error(f"[orchestrator] Dynamic agent start failed: {e}")

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
        except Exception as e:
            logger.debug(f"[quote] Recent messages fetch failed: {e}")
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

    # "!생각일기" → 생각일기 한 마디 즉시 실행
    async def cmd_diary_quote(args: str, user: str, channel: str, thread_ts: str = None):
        err = await diary_quote.run_once(channel=channel, thread_ts=thread_ts)
        if err:
            await _reply(channel, err, thread_ts)

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

    # "!시세" → 투자 에이전트 즉시 브리핑
    async def cmd_market(args: str, user: str, channel: str, thread_ts: str = None):
        try:
            prices = await investment._fetch_all_prices()
            fg = await investment._fetch_fear_greed()
            await investment._send_market_briefing({
                "prices": prices,
                "fear_greed": fg,
                "hour": datetime.now(KST).hour,
            })
        except Exception as e:
            await _reply(channel, f"시세 조회 실패: {e}", thread_ts)

    # "!인사평가" → 전체 에이전트 일일 인사평가 실행
    async def cmd_hr_eval(args: str, user: str, channel: str, thread_ts: str = None):
        await _reply(channel, "📋 인사평가를 시작합니다...", thread_ts)
        try:
            result = await agent_hr.run_daily_evaluation()
            report = agent_hr.format_evaluation_result(result)
            await _reply(channel, report, thread_ts)
        except Exception as e:
            await _reply(channel, f"인사평가 실패: {e}", thread_ts)

    # "!인사현황" → 전체 에이전트 HR 현황
    async def cmd_hr_status(args: str, user: str, channel: str, thread_ts: str = None):
        if args.strip():
            # 개별 에이전트 인사카드
            report = agent_hr.get_agent_card(args.strip())
        else:
            report = agent_hr.get_hr_report()
        await _reply(channel, report, thread_ts)

    # "!연봉" → 연봉 랭킹 또는 연봉 조정
    async def cmd_salary(args: str, user: str, channel: str, thread_ts: str = None):
        parts = args.strip().split()
        if len(parts) >= 2:
            # !연봉 에이전트명 +200 → 연봉 수동 조정
            agent_name = parts[0]
            try:
                amount = int(parts[1].replace("+", "").replace(",", ""))
                reason = " ".join(parts[2:]) if len(parts) > 2 else "수동 조정"
                result = agent_hr.adjust_salary(agent_name, amount, reason)
                profile = agent_hr.get_profile(agent_name) or {}
                display = profile.get("display_name", agent_name)
                await _reply(channel,
                    f"💰 {display} 연봉 조정: {result['old_salary']:,}만원 → {result['new_salary']:,}만원",
                    thread_ts)
            except ValueError:
                await _reply(channel, "사용법: `!연봉 에이전트명 +200 [사유]`", thread_ts)
        else:
            report = agent_hr.get_salary_ranking()
            await _reply(channel, report, thread_ts)

    slack.on_command("수집", cmd_collect)
    slack.on_command("브리핑", cmd_briefing)
    slack.on_command("상태", cmd_status)
    slack.on_command("명언", cmd_quote)
    slack.on_command("생각일기", cmd_diary_quote)
    slack.on_command("로그", cmd_log)
    slack.on_command("현황", cmd_dashboard)
    slack.on_command("시세", cmd_market)
    slack.on_command("인사평가", cmd_hr_eval)
    slack.on_command("인사현황", cmd_hr_status)
    slack.on_command("연봉", cmd_salary)

    # ── 주식 매매 명령어 ──────────────────────────────────
    async def cmd_buy(args: str, user: str, channel: str, thread_ts: str = None):
        """!매수 종목코드 수량 [가격] - LS증권 매수 주문"""
        if not ls_client:
            await _reply(channel, "⚠️ LS증권 연동이 설정되지 않았습니다. (LS_APP_KEY 환경변수 필요)", thread_ts)
            return
        parts = args.strip().split()
        if len(parts) < 2:
            await _reply(channel, "사용법: `!매수 005930 1` (종목코드 수량) 또는 `!매수 005930 1 55000` (지정가)", thread_ts)
            return
        stock_code = parts[0]
        try:
            qty = int(parts[1])
        except ValueError:
            await _reply(channel, "수량은 숫자여야 합니다.", thread_ts)
            return
        price = 0
        order_type = "03"  # 시장가
        if len(parts) >= 3:
            try:
                price = int(parts[2])
                order_type = "00"  # 지정가
            except ValueError:
                pass
        mode = "모의투자" if ls_client.paper_trading else "실전투자"
        price_str = f"{price:,}원" if price else "시장가"
        await _reply(channel, f"📈 *[{mode}] 매수 주문 접수*\n종목: {stock_code} | 수량: {qty}주 | 가격: {price_str}", thread_ts)
        try:
            result = await ls_client.buy(stock_code=stock_code, qty=qty, price=price, order_type=order_type)
            if result.get("결과") == "성공":
                await _reply(channel, f"✅ *매수 주문 성공!*\n주문번호: {result.get('주문번호')}\n종목: {result.get('종목코드', stock_code)} | {qty}주 | {price_str}", thread_ts)
            else:
                err_msg = result.get("에러", "")
                if not err_msg:
                    raw = result.get("raw", {})
                    err_msg = raw.get("rsp_msg", "") or raw.get("msg1", "") or str(raw)[:300]
                await _reply(channel, f"❌ *매수 주문 실패*\n{err_msg}", thread_ts)
        except Exception as e:
            await _reply(channel, f"❌ {friendly_error_message(e)}", thread_ts)

    async def cmd_sell(args: str, user: str, channel: str, thread_ts: str = None):
        """!매도 종목코드 수량 [가격] - LS증권 매도 주문"""
        if not ls_client:
            await _reply(channel, "⚠️ LS증권 연동이 설정되지 않았습니다.", thread_ts)
            return
        parts = args.strip().split()
        if len(parts) < 2:
            await _reply(channel, "사용법: `!매도 005930 1` (종목코드 수량) 또는 `!매도 005930 1 55000` (지정가)", thread_ts)
            return
        stock_code = parts[0]
        try:
            qty = int(parts[1])
        except ValueError:
            await _reply(channel, "수량은 숫자여야 합니다.", thread_ts)
            return
        price = 0
        order_type = "03"
        if len(parts) >= 3:
            try:
                price = int(parts[2])
                order_type = "00"
            except ValueError:
                pass
        mode = "모의투자" if ls_client.paper_trading else "실전투자"
        price_str = f"{price:,}원" if price else "시장가"
        await _reply(channel, f"📉 *[{mode}] 매도 주문 접수*\n종목: {stock_code} | 수량: {qty}주 | 가격: {price_str}", thread_ts)
        try:
            result = await ls_client.sell(stock_code=stock_code, qty=qty, price=price, order_type=order_type)
            if result.get("결과") == "성공":
                await _reply(channel, f"✅ *매도 주문 성공!*\n주문번호: {result.get('주문번호')}\n종목: {result.get('종목코드', stock_code)} | {qty}주 | {price_str}", thread_ts)
            else:
                err_msg = result.get("에러", "")
                if not err_msg:
                    raw = result.get("raw", {})
                    err_msg = raw.get("rsp_msg", "") or raw.get("msg1", "") or str(raw)[:300]
                await _reply(channel, f"❌ *매도 주문 실패*\n{err_msg}", thread_ts)
        except Exception as e:
            await _reply(channel, f"❌ {friendly_error_message(e)}", thread_ts)

    async def cmd_balance(args: str, user: str, channel: str, thread_ts: str = None):
        """!잔고 - LS증권 계좌 잔고 조회"""
        if not ls_client:
            await _reply(channel, "⚠️ LS증권 연동이 설정되지 않았습니다.", thread_ts)
            return
        try:
            result = await ls_client.get_balance()

            # API 실패 + 캐시도 없는 경우
            if result.get("unavailable"):
                from integrations.ls_securities import is_market_open, market_hours_message
                if not is_market_open():
                    await _reply(channel, f"📋 표시할 잔고가 없습니다.\n{market_hours_message()}\n저장된 마지막 잔고가 없어서, 장중에 한 번 조회하면 이후 장외에서도 볼 수 있어요.", thread_ts)
                else:
                    err = result.get("error")
                    await _reply(channel, f"❌ 잔고 조회에 실패했어요.\n{friendly_error_message(err) if err else '알 수 없는 오류'}", thread_ts)
                return

            summary = result.get("summary", {})
            holdings = result.get("holdings", [])
            is_cached = result.get("cached", False)
            mode = "모의투자" if ls_client.paper_trading else "실전투자"
            if is_cached:
                cached_time = result.get("cached_time")
                time_str = cached_time.strftime("%H:%M") if cached_time else "?"
                lines = [f"💰 *[{mode}] 계좌 잔고* (📋 {time_str} 기준 캐시)"]
            else:
                lines = [f"💰 *[{mode}] 계좌 잔고*"]
            lines.append(f"추정순자산: {summary.get('추정순자산', 0):,}원")
            lines.append(f"총매입금액: {summary.get('총매입금액', 0):,}원")
            lines.append(f"추정손익: {summary.get('추정손익', 0):,}원")
            if holdings:
                lines.append("\n*보유 종목:*")
                for h in holdings:
                    pnl = h.get('평가손익', 0)
                    pnl_emoji = "🟢" if pnl >= 0 else "🔴"
                    lines.append(f"{pnl_emoji} {h['종목명']} ({h['종목코드']}) | {h['잔고수량']}주 | 수익률: {h['수익률']:.1f}%")
            else:
                lines.append("\n보유 종목이 없습니다.")
            await _reply(channel, "\n".join(lines), thread_ts)
        except Exception as e:
            await _reply(channel, f"❌ {friendly_error_message(e)}", thread_ts)

    async def cmd_price(args: str, user: str, channel: str, thread_ts: str = None):
        """!시세조회 종목코드 - LS증권 현재가 조회"""
        if not ls_client:
            await _reply(channel, "⚠️ LS증권 연동이 설정되지 않았습니다.", thread_ts)
            return
        stock_code = args.strip()
        if not stock_code:
            await _reply(channel, "사용법: `!시세조회 005930`", thread_ts)
            return
        try:
            from integrations.ls_securities import fetch_naver_volume
            result, naver_vol = await asyncio.gather(
                ls_client.get_price(stock_code),
                fetch_naver_volume(stock_code),
            )

            if result.get("unavailable"):
                from integrations.ls_securities import is_market_open, market_hours_message
                if not is_market_open():
                    await _reply(channel, f"📋 {stock_code} 시세를 조회할 수 없습니다.\n{market_hours_message()}\n장중에 한 번 조회하면 이후 장외에서도 마지막 시세를 볼 수 있어요.", thread_ts)
                else:
                    err = result.get("error")
                    await _reply(channel, f"❌ 시세 조회에 실패했어요.\n{friendly_error_message(err) if err else '알 수 없는 오류'}", thread_ts)
                return

            is_cached = result.get("cached", False)
            sign_map = {"1": "▲", "2": "▲", "3": "", "4": "▼", "5": "▼"}
            sign = sign_map.get(result.get("등락부호", ""), "")
            if is_cached:
                cached_time = result.get("cached_time")
                time_str = cached_time.strftime("%H:%M") if cached_time else "?"
                header = f"📊 *{result['종목명']}* ({stock_code}) _(📋 {time_str} 기준)_"
            else:
                header = f"📊 *{result['종목명']}* ({stock_code})"
            vol_line = f"거래량: {result['거래량']:,}"
            if naver_vol is not None:
                vol_line += f" (네이버: {naver_vol:,})"
            lines = [
                header,
                f"현재가: {result['현재가']:,}원 {sign}{abs(result['전일대비']):,}원 ({result['등락률']:+.2f}%)",
                vol_line,
                f"매수호가: {result['매수호가1']:,}원 | 매도호가: {result['매도호가1']:,}원",
                f"<https://finance.naver.com/item/main.naver?code={stock_code}|네이버 증권에서 확인>",
            ]
            await _reply(channel, "\n".join(lines), thread_ts)
        except Exception as e:
            await _reply(channel, f"❌ {friendly_error_message(e)}", thread_ts)

    slack.on_command("매수", cmd_buy)
    slack.on_command("매도", cmd_sell)
    slack.on_command("잔고", cmd_balance)
    slack.on_command("시세조회", cmd_price)

    # "!운세" → 운세 에이전트 즉시 실행
    async def cmd_fortune(args: str, user: str, channel: str, thread_ts: str = None):
        now = datetime.now(KST)
        context = {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": now.hour,
            "date_str": now.strftime("%Y년 %m월 %d일"),
            "weekday": ["월", "화", "수", "목", "금", "토", "일"][now.weekday()],
            "period": "아침" if now.hour < 11 else ("점심" if now.hour < 17 else "저녁"),
            "send_key": "manual",
            "recent_fortunes": [h.get("summary", "") for h in fortune._fortune_history[-10:]],
        }
        decision = await fortune.think(context)
        if decision:
            decision["action"] = "send_fortune"
            msg = fortune._format_message(decision)
            await _reply(channel, msg, thread_ts)
            fortune._fortune_history.append({
                "date": context["date_str"],
                "period": context["period"],
                "summary": decision["data"].get("overall", "")[:100],
            })
            fortune._save_history()
        else:
            await _reply(channel, "운세 생성에 실패했어요.", thread_ts)

    slack.on_command("운세", cmd_fortune)

    # "!센티멘트" → 소셜 센티멘트 분석 즉시 실행
    async def cmd_sentiment(args: str, user: str, channel: str, thread_ts: str = None):
        query = args.strip() if args.strip() else None
        if query:
            await _reply(channel, f"🔍 *'{query}'* 소셜 센티멘트 분석 중...", thread_ts)
        else:
            await _reply(channel, "🔍 소셜 센티멘트 종합 분석 중... (1-2분 소요)", thread_ts)
        await sentiment.run_manual(channel=channel, thread_ts=thread_ts, query=query)

    slack.on_command("센티멘트", cmd_sentiment)

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
- diary_quote: 생각일기 한마디, 생각일기 실행, 일기에서 한마디
- fortune: 운세 보기, 오늘의 운세
- hr_eval: 인사평가 실행, 에이전트 평가, 성과 평가, "인사평가 해줘", "에이전트들 평가해봐"
- hr_status: 인사현황, 연봉 조회, 에이전트 인사카드, "연봉 랭킹", "인사 현황 보여줘", "에이전트 연봉", "누가 제일 많이 받아?" hr_target 필드에 특정 에이전트명 (없으면 전체)
- hr_salary: 연봉 조정, "연봉 올려줘", "연봉 깎아", hr_target(에이전트명), hr_amount(조정액, 만원), hr_reason(사유)
- stock_trade: 주식 매수/매도/잔고조회/시세조회. "삼성전자 1주 매수", "005930 매도해줘", "잔고 보여줘", "삼성전자 시세", "모의투자 매수" 등. stock_code(종목코드), action(buy/sell/balance/price), qty(수량), price(가격, 0이면 시장가) 필드 포함
- dev: 실제 코드 작성, 파일 생성, 프로젝트 구축, API 만들기, 서버 세팅 등 개발/엔지니어링 작업. "만들어줘", "구축해줘", "코드 짜줘", "서버 올려줘", "API 개발해줘", "프로젝트 시작해줘" 등
- chat: 질문, 분석, 비교, 조언, 날씨, 가격, 환율, 잡담, 프로젝트 논의, 의견 교환 등 개발이 아닌 모든 대화

중요: 가격, 날씨, 환율, 분석, 비교 등은 chat. collect가 아닙니다.
중요: 실제 코드/프로젝트를 만들어달라는 요청은 dev입니다. 단순 논의/질문은 chat.
중요: 시스템/에이전트 상태 질문은 dashboard.
중요: 주식 매수/매도/잔고/시세 관련은 stock_trade. 종목명은 한국어→종목코드 매핑: 삼성전자=005930, SK하이닉스=000660, 네이버=035420, 카카오=035720, LG에너지솔루션=373220, 현대차=005380, 삼성바이오로직스=207940, 기아=000270, 셀트리온=068270, POSCO홀딩스=005490
중요: 의도가 애매하거나 여러 해석이 가능할 때는 clarify를 사용하고, clarify_question에 되물을 질문을 넣으세요.

{thread_hint}

{("과거 작업 이력:" + chr(10) + exp_summary) if exp_summary else ""}
{user_context}

응답 형식 (반드시 JSON만):
{{
  "intent": "collect|briefing|dashboard|quote|diary_quote|fortune|hr_eval|hr_status|hr_salary|stock_trade|chat|dev|clarify|ignore",
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
  "clarify_question": "의도 확인용 질문 (clarify일 때만)",
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

        if action == "clarify":
            question = parsed.get("clarify_question", "어떤 작업을 원하시는지 좀 더 구체적으로 말씀해주세요.")
            await _reply(channel, question, thread_ts)
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
            elif action == "diary_quote":
                await cmd_diary_quote(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "생각일기 한마디 전송 완료"
            elif action == "fortune":
                await cmd_fortune(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "운세 전송 완료"
            elif action == "hr_eval":
                await cmd_hr_eval(args="", user=user, channel=channel, thread_ts=thread_ts)
                result_text = "인사평가 완료"
            elif action == "hr_status":
                target = parsed.get("hr_target", "").strip()
                await cmd_hr_status(args=target, user=user, channel=channel, thread_ts=thread_ts)
                result_text = "인사현황 조회 완료"
            elif action == "hr_salary":
                target = parsed.get("hr_target", "").strip()
                amount = int(parsed.get("hr_amount", 0) or 0)
                reason = parsed.get("hr_reason", "").strip()
                if target and amount:
                    args_str = f"{target} {amount} {reason}".strip()
                    await cmd_salary(args=args_str, user=user, channel=channel, thread_ts=thread_ts)
                    result_text = f"{target} 연봉 조정 완료"
                else:
                    await cmd_salary(args="", user=user, channel=channel, thread_ts=thread_ts)
                    result_text = "연봉 랭킹 조회 완료"
            elif action == "stock_trade":
                stock_action = parsed.get("stock_action", "").strip()
                stock_code = parsed.get("stock_code", "").strip()
                stock_qty = int(parsed.get("stock_qty", 1) or 1)
                stock_price = int(parsed.get("stock_price", 0) or 0)
                if stock_action == "balance":
                    await cmd_balance(args="", user=user, channel=channel, thread_ts=thread_ts)
                    result_text = "잔고 조회 완료"
                elif stock_action == "price" and stock_code:
                    await cmd_price(args=stock_code, user=user, channel=channel, thread_ts=thread_ts)
                    result_text = f"시세 조회 완료: {stock_code}"
                elif stock_action == "buy" and stock_code:
                    price_arg = f" {stock_price}" if stock_price else ""
                    await cmd_buy(args=f"{stock_code} {stock_qty}{price_arg}", user=user, channel=channel, thread_ts=thread_ts)
                    result_text = f"매수 주문: {stock_code} {stock_qty}주"
                elif stock_action == "sell" and stock_code:
                    price_arg = f" {stock_price}" if stock_price else ""
                    await cmd_sell(args=f"{stock_code} {stock_qty}{price_arg}", user=user, channel=channel, thread_ts=thread_ts)
                    result_text = f"매도 주문: {stock_code} {stock_qty}주"
                else:
                    await _reply(channel, "매매 명령을 이해하지 못했어요. 예: `삼성전자 1주 시장가 매수해줘`", thread_ts)
                    result_text = "stock_trade 파싱 실패"
                    success = False
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

                    # 자율 실행 지침 추가
                    full_prompt += """

[자율 실행 지침]
- 권한 요청하지 말고 바로 실행하세요. 모든 파일 쓰기/수정 권한이 있습니다.
- 작업 완료 후 git add, git commit, git push까지 자동으로 하세요.
- 커밋 메시지는 한국어로, 변경 내용을 요약하세요.
- git push는 현재 브랜치로 하세요.
- 사용자에게 승인을 묻지 마세요. 모든 것이 사전 승인됨.
- 작업 디렉토리: /home/user/yhmemo
- 결과를 간결하게 요약하세요 (무엇을 만들었는지, 어떤 파일, 다음 단계)."""

                    await _reply(channel, "🔨 코드 작업 시작합니다. 진행 상황을 알려드릴게요.", thread_ts)

                    try:
                        from core.executor import execute_plan, format_execution_results, EXECUTOR_TOOL_SCHEMA

                        # AI가 실행 계획 생성
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

                        import re as _re2
                        try:
                            clean = plan_response.strip()
                            if "```json" in clean:
                                clean = clean.split("```json", 1)[1].rsplit("```", 1)[0].strip()
                            elif "```" in clean:
                                clean = clean.split("```", 1)[1].rsplit("```", 1)[0].strip()
                            plan = json.loads(clean)
                        except json.JSONDecodeError:
                            # 텍스트 안에서 JSON 객체 찾기
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
                            await _reply(channel, f"🔧 실행 계획 {len(steps)}단계 시작합니다.", thread_ts)
                            from core.executor import ALLOWED_BASE as _exec_base
                            exec_results = await execute_plan(
                                steps,
                                supabase_client=supabase,
                                cwd=str(_exec_base),
                            )
                            result_text_raw = format_execution_results(exec_results)
                            success_count = sum(1 for r in exec_results if r["ok"])
                            total = len(exec_results)

                            # 요약
                            summary = await curator.ai_think(
                                system_prompt="실행 결과를 슬랙 메시지로 요약. 핵심만. 최대 1500자.",
                                user_prompt=f"작업: {dev_task}\n결과:\n{result_text_raw[:2000]}",
                            )
                            icon = "✅" if success_count == total else "⚠️"
                            await _reply(
                                channel,
                                f"{icon} *[마스터]* 작업 완료! ({success_count}/{total} 성공)\n\n{summary or result_text_raw[:1500]}",
                                thread_ts,
                            )
                            result_text = f"dev 완료: {dev_task[:50]} ({success_count}/{total})"
                        elif analysis:
                            await _reply(channel, f"✅ *[마스터]* 분석 완료!\n\n{analysis[:3000]}", thread_ts)
                            result_text = f"dev 분석 완료: {dev_task[:50]}"
                        else:
                            # fallback: AI 직접 응답
                            output = await curator.ai_think(
                                system_prompt="요청된 작업을 분석하고 구체적 결과물을 만드세요.",
                                user_prompt=full_prompt,
                            )
                            if output:
                                await _reply(channel, f"✅ *[마스터]* 작업 완료!\n\n{output[:3000]}", thread_ts)
                                result_text = f"dev 완료: {dev_task[:50]}"
                            else:
                                await _reply(channel, "⚠️ *[마스터]* 작업 결과를 생성하지 못했어요.", thread_ts)
                                result_text = "dev 오류: 결과 없음"
                                success = False
                    except Exception as e:
                        await _reply(channel, f"⚠️ *[마스터]* 작업 중 오류:\n```{str(e)[:500]}```", thread_ts)
                        result_text = f"dev 오류: {str(e)[:100]}"
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
                        import re
                        improvements = re.findall(r'\[IMPROVE:(.*?)\]', chat_response)
                        # 태그는 유저에게 보여주지 않음
                        clean_response = re.sub(r'\s*\[IMPROVE:.*?\]', '', chat_response).strip()
                        await _reply(channel, clean_response, thread_ts)
                        # 개선 요청을 실제 Goal로 변환하여 실행
                        for imp in improvements:
                            await slack.send_message(SlackClient.CHANNEL_GENERAL,
                                f"🔧 *[자기개선 요청]* {imp}\n요청자: <@{user}>\n원본: {text[:100]}")
                            logger.info(f"[NL] Self-improvement request: {imp}")
                            # proactive agent의 goal planner에 목표 추가
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
                                logger.info(f"[NL] Self-improvement goal created: {goal.id}")
                            except Exception as goal_err:
                                logger.error(f"[NL] Failed to create improvement goal: {goal_err}")
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

    # 이모지 반응 → 선별 에이전트 피드백 학습 + 제안 승인/거절
    async def on_reaction(reaction: str, item: dict, user: str):
        # 1. 제안 승인/거절 처리
        message_ts = item.get("ts", "")
        if message_ts:
            result = proactive.handle_proposal_reaction(reaction, message_ts)
            if result:
                state = result["new_state"]
                title = result["title"]
                if state == "approved":
                    await _reply(
                        item.get("channel", SlackClient.CHANNEL_GENERAL),
                        f"✅ *'{title}' 승인됨!* 다음 사이클에서 실행을 시작합니다.",
                        message_ts,
                    )
                elif state == "rejected":
                    await _reply(
                        item.get("channel", SlackClient.CHANNEL_GENERAL),
                        f"❌ *'{title}' 거절됨.* 피드백이 있으면 알려주세요.",
                        message_ts,
                    )
                return  # 제안 반응이면 피드백 학습 스킵

        # 2. 선별 에이전트 피드백 학습
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
        # invest.stop()          # 비활성화됨
        # invest_report.stop()   # 비활성화됨

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    # Socket Mode 먼저 시도 → 실패 시 폴링으로 전환
    socket_mode = await slack._try_socket_mode()

    if socket_mode:
        logger.info("✓ Socket Mode 연결 성공! 실시간 이벤트 수신 중 (+ 30초 폴링 병행)")
        # Socket Mode에서도 채널/폴링 설정 필요 (봇 자신의 메시지 수신용)
        await slack.ensure_channels_exist()
        await slack._init_channel_cache()
        # 폴링 채널 초기화 (봇 자신의 !명령어/[마스터] 메시지 수신용)
        import time as _time
        slack._poll_channels = [slack.CHANNEL_GENERAL, slack.CHANNEL_INVEST]
        for ch_id in slack._poll_channels:
            slack._last_ts[ch_id] = str(_time.time())
        slack._running = True
    else:
        logger.info("Socket Mode 불가 → 폴링 모드로 운영")
        await slack.start_background()

    logger.info("Agents started silently (no startup message to Slack)")

    # 에이전트 태스크 실행 (재시작 가능하도록 팩토리 패턴)
    agent_starters = {
        "message_bus": lambda: asyncio.create_task(bus.run(), name="message_bus"),
        # "collector": lambda: asyncio.create_task(collector.start(), name="collector"),  # ai-curator 알림 중지
        # "curator": lambda: asyncio.create_task(curator.start(), name="curator"),      # ai-curator 알림 중지
        # "quote": lambda: asyncio.create_task(quote.start(), name="quote"),          # 명언 비활성화
        "diary_quote": lambda: asyncio.create_task(diary_quote.start(), name="diary_quote"),
        # "fortune": lambda: asyncio.create_task(fortune.start(), name="fortune"),  # 운영 중단
        "proactive": lambda: asyncio.create_task(proactive.start(), name="proactive"),
        # "invest": lambda: asyncio.create_task(invest.start(), name="invest"),          # 비활성화됨
        # "invest_report": lambda: asyncio.create_task(invest_report.start(), name="invest_report"),  # 비활성화됨
        "task_board": lambda: asyncio.create_task(task_board.start(), name="task_board"),
        "sentiment": lambda: asyncio.create_task(sentiment.start(), name="sentiment"),
    }
    agent_tasks = {name: starter() for name, starter in agent_starters.items()}

    # Level 5: 동적 에이전트 시작 (proactive 시작 후 약간 대기)
    async def _delayed_dynamic_start():
        await asyncio.sleep(10)  # proactive 초기화 대기
        await start_dynamic_agents()
    asyncio.create_task(_delayed_dynamic_start(), name="dynamic_agents_init")

    # ── 마스터 워치독: 4시간마다 전체 시스템 점검 (비용 절감: 1시간 → 4시간) ──
    HEALTH_CHECK_INTERVAL = 14400  # 4시간 (초) — fallback
    last_health_check_time = asyncio.get_event_loop().time()
    last_report_slot = ""  # KST 정각 슬롯 추적 (e.g. "17:00")

    async def master_health_check():
        """1시간마다 전체 시스템 점검 + 죽은 에이전트 자동 재시작 + Slack 오케스트레이션 가동 리포트"""
        nonlocal agent_tasks
        _rotate_log_file_if_needed()
        now = datetime.now(KST)
        now_str = now.strftime("%H:%M")
        issues = []
        restarts = []

        # 1. 에이전트 태스크 생존 확인 + 자동 재시작
        for name, task in list(agent_tasks.items()):
            if task.done():
                exc = task.exception() if not task.cancelled() else None
                err_msg = str(exc)[:100] if exc else "unknown"
                logger.warning(f"[watchdog] Agent '{name}' is DEAD (error: {err_msg})")
                agent_tracker.record_error(name, f"Task died: {err_msg}")

                # 재시작
                if name in agent_starters:
                    try:
                        agent_tasks[name] = agent_starters[name]()
                        agent_tracker.register_agent(name, f"자동 재시작됨 ({now_str})")
                        restarts.append(name)
                        logger.info(f"[watchdog] Restarted agent: {name}")
                    except Exception as e:
                        issues.append(f"❌ {name}: 재시작 실패 ({e})")
                        logger.error(f"[watchdog] Failed to restart {name}: {e}")
                else:
                    issues.append(f"❌ {name}: 죽음 (재시작 불가)")

        # 2. heartbeat 체크 — loop_interval의 2배 또는 최소 15분 이상 응답 없으면 경고
        #    비활성화된 에이전트(agent_starters에 없는)는 무시
        tracker_data = agent_tracker._load()
        for name, info in tracker_data.get("agents", {}).items():
            if name not in agent_starters:
                continue  # 비활성화된 에이전트는 heartbeat 체크 스킵
            last_hb = info.get("last_heartbeat", "")
            if last_hb:
                try:
                    hb_time = datetime.fromisoformat(last_hb)
                    if hb_time.tzinfo is None:
                        hb_time = hb_time.replace(tzinfo=KST)
                    elapsed = (now - hb_time).total_seconds()
                    # 에이전트 loop_interval의 2배 + 여유 5분, 최소 900초(15분)
                    loop_sec = info.get("loop_interval", 0)
                    threshold = max(900, loop_sec * 2 + 300)
                    if elapsed > threshold:
                        mins = int(elapsed / 60)
                        issues.append(f"⚠️ {name}: heartbeat {mins}분 전 (무응답)")
                except (ValueError, TypeError):
                    pass

        # 3. 지난 1시간 활동 요약 (로그 파싱)
        past_activities = _parse_recent_log_activities(now)

        # 3.5. 이전 계획 이행률 검증
        fulfillment = _check_plan_fulfillment(past_activities)

        # 4. 앞으로 1시간 실제 실행 계획
        next_activities = _get_next_1h_plan(now)

        # 4.5. 계획 저장 (다음 리포트에서 이행 검증용)
        _save_planned_tasks(now_str, next_activities)

        # 5. Slack 오케스트레이션 가동 리포트 (매 1시간마다 항상 전송)
        alive = sum(1 for t in agent_tasks.values() if not t.done())
        total = len(agent_tasks)

        report_lines = [f"*📊 오케스트레이션 가동 리포트* ({now_str} KST) — {alive}/{total} 에이전트"]

        if restarts:
            report_lines.append(f"🔄 자동 재시작: *{', '.join(restarts)}*")
        if issues:
            for issue in issues:
                report_lines.append(issue)

        # 이전 계획 이행률 (있으면)
        if fulfillment:
            report_lines.append("")
            for line in fulfillment:
                report_lines.append(line)

        report_lines.append("")
        report_lines.append("*지난 1시간:*")
        if past_activities:
            for line in past_activities:
                report_lines.append(f"• {line}")
        else:
            report_lines.append("• (활동 없음)")

        report_lines.append("")
        report_lines.append("*앞으로 1시간:*")
        for line in next_activities:
            report_lines.append(f"• {line}")

        try:
            await slack.send_message(SlackClient.CHANNEL_GENERAL, "\n".join(report_lines))
        except Exception as e:
            logger.error(f"[watchdog] Slack report failed: {e}")

        # 6. 매일 09:00 KST 자동 인사평가
        if now.strftime("%H:%M") == "09:00":
            try:
                hr_result = await agent_hr.run_daily_evaluation()
                if not hr_result.get("already_done"):
                    hr_report = agent_hr.format_evaluation_result(hr_result)
                    await slack.send_message(SlackClient.CHANNEL_GENERAL, hr_report)
                    logger.info("[HR] 일일 자동 인사평가 완료")
            except Exception as e:
                logger.error(f"[HR] 자동 인사평가 실패: {e}")

        # ai-agent-logs에도 이슈가 있을 때만 전송
        if issues or restarts:
            log_lines = [f"*🔍 마스터 점검* ({now_str} KST)"]
            if restarts:
                log_lines.append(f"🔄 자동 재시작: *{', '.join(restarts)}*")
            for issue in issues:
                log_lines.append(issue)
            try:
                await slack.send_message(SlackClient.CHANNEL_LOGS, "\n".join(log_lines))
            except Exception:
                pass

        if restarts:
            logger.info(f"[watchdog] Restarted: {restarts}")
        elif issues:
            logger.warning(f"[watchdog] Issues: {len(issues)}")
        else:
            logger.info(f"[watchdog] All {len(agent_tasks)} agents OK")

    def _parse_recent_log_activities(now: datetime) -> list[str]:
        """최근 1시간 로그에서 주요 활동 추출"""
        activities = []
        # 로그 타임스탬프는 UTC
        now_utc = now.astimezone(timezone.utc)
        log_file = os.path.join(
            os.path.dirname(__file__), "data", "logs",
            f"orchestrator-{now_utc.strftime('%Y%m%d')}.log"
        )
        if not os.path.exists(log_file):
            return activities

        one_hour_ago = now_utc - timedelta(hours=1)
        # 자정 경계 처리: 날짜+시간 문자열로 비교
        one_hour_ago_str = one_hour_ago.strftime("%Y-%m-%d %H:%M")
        now_date_str = now_utc.strftime("%Y-%m-%d %H:%M")

        # 자정 경계 시 이전 날짜 로그도 확인
        log_files = [log_file]
        if one_hour_ago.date() != now_utc.date():
            prev_log = os.path.join(
                os.path.dirname(__file__), "data", "logs",
                f"orchestrator-{one_hour_ago.strftime('%Y%m%d')}.log"
            )
            if os.path.exists(prev_log):
                log_files.insert(0, prev_log)

        # 루틴/무시할 액션 — 핵심 실행 액션은 스킵하지 않음
        _SKIP_ACTIONS = {"slot_check", "find_work"}
        # 재시작 시 1회성 에러 무시 패턴
        _IGNORE_ERRORS = {"Failed to connect", "Unclosed client session", "Task was destroyed"}

        seen = set()
        slack_msg_count = 0
        try:
          for lf in log_files:
            with open(lf, "r") as f:
                for line in f:
                    if len(line) < 20:
                        continue
                    date_time_part = line[:16]  # "YYYY-MM-DD HH:MM"
                    if date_time_part < one_hour_ago_str or date_time_part > now_date_str:
                        continue

                    # 슬랙 메시지 수 카운트
                    if "New message:" in line:
                        slack_msg_count += 1
                        continue
                    if "Poll tick" in line or "Polling" in line or "HTTP Request" in line:
                        continue

                    # 주요 이벤트 추출
                    if "Executing:" in line:
                        idx = line.index("Executing:")
                        desc = line[idx + 10:].strip()
                        # 루틴 액션은 스킵
                        if any(skip in desc for skip in _SKIP_ACTIONS):
                            continue
                        key = f"proactive: {desc}"
                        if key not in seen:
                            seen.add(key)
                            activities.append(desc)
                    elif "[executor]" in line and ("✅" in line or "❌" in line):
                        # 실행 엔진 결과
                        idx = line.index("[executor]")
                        desc = line[idx + 10:].strip()[:80]
                        key = f"exec: {desc}"
                        if key not in seen:
                            seen.add(key)
                            activities.append(f"실행: {desc}")
                    elif "Step completed:" in line or "Step failed:" in line:
                        idx = line.index("Step")
                        desc = line[idx:].strip()[:80]
                        key = f"step: {desc}"
                        if key not in seen:
                            seen.add(key)
                            activities.append(desc)
                    elif "Daily plan generated:" in line or "Fallback plan set:" in line:
                        activities.append("일일 계획 생성 완료")
                    elif "Sent quote" in line:
                        if "quote" not in seen:
                            seen.add("quote")
                            activities.append("명언 전송 완료")
                    elif "[curator] Received" in line:
                        idx = line.index("Received")
                        desc = line[idx:].strip()
                        if "curator" not in seen:
                            seen.add("curator")
                            activities.append(f"뉴스 큐레이션 — {desc}")
                    elif "Cycle" in line and "complete" in line and "invest" in line.lower():
                        if "invest_cycle" not in seen:
                            seen.add("invest_cycle")
                            activities.append("투자 분석 사이클 완료")
                    elif "[self_memory] Insight" in line:
                        idx = line.index("Insight")
                        desc = line[idx:].strip()[:60]
                        activities.append(f"메모리 저장: {desc}")
                    elif "error" in line.lower() and "ERROR" in line:
                        # 재시작 시 1회성 에러는 무시
                        if any(pat in line for pat in _IGNORE_ERRORS):
                            continue
                        short = line.split("ERROR:")[-1].strip()[:60] if "ERROR:" in line else ""
                        if short and short not in seen:
                            seen.add(short)
                            activities.append(f"⚠️ {short}")

          if slack_msg_count > 0:
              activities.append(f"슬랙 메시지 {slack_msg_count}건 수신/처리")

        except Exception as e:
            logger.debug(f"[report] Log parse error: {e}")

        return activities[:8]  # 최대 8줄

    # ── 계획 이행 추적 ────────────────────────────────────
    PLANNED_TASKS_FILE = os.path.join(os.path.dirname(__file__), "data", "planned_tasks.json")

    def _save_planned_tasks(slot: str, tasks: list[str]):
        """다음 1시간 계획을 파일에 저장 → 다음 리포트에서 이행 여부 검증"""
        try:
            data = {"slot": slot, "tasks": tasks, "saved_at": datetime.now(KST).isoformat()}
            with open(PLANNED_TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_planned_tasks() -> dict:
        """이전 1시간에 계획했던 태스크 로드"""
        try:
            if os.path.exists(PLANNED_TASKS_FILE):
                with open(PLANNED_TASKS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _check_plan_fulfillment(past_activities: list[str]) -> list[str]:
        """이전 계획 vs 실제 활동 비교 → 이행률 표시"""
        prev = _load_planned_tasks()
        if not prev or not prev.get("tasks"):
            return []

        planned = prev["tasks"]
        slot = prev.get("slot", "?")
        activity_text = " ".join(past_activities).lower()

        results = []
        done_count = 0
        for task in planned:
            # 키워드 매칭으로 이행 여부 판단
            keywords = _extract_keywords(task)
            matched = any(kw in activity_text for kw in keywords)
            if matched:
                results.append(f"  ✅ {task}")
                done_count += 1
            else:
                results.append(f"  ❌ {task}")

        total = len(planned)
        pct = int(done_count / total * 100) if total > 0 else 0
        header = f"*계획 이행률* ({slot}): {done_count}/{total} ({pct}%)"
        return [header] + results

    def _extract_keywords(task: str) -> list[str]:
        """태스크 설명에서 매칭용 키워드 추출"""
        keywords = []
        task_lower = task.lower()
        # 에이전트 이름 매칭
        agent_keywords = {
            "투자": ["invest", "투자", "cycle"],
            "뉴스": ["curator", "뉴스", "news", "received"],
            "명언": ["quote", "명언"],
            "운세": ["fortune", "운세"],
            "폴링": ["poll", "polling"],
            "slot_check": ["slot_check"],
            "시간별": ["hourly", "execute_hourly"],
            "목표": ["goal", "execute_goal"],
            "제안": ["proposal", "initiative", "propose"],
            "리서치": ["research", "business_research"],
            "트렌드": ["trend", "trend_check"],
            "모니터링": ["measure", "monitor", "성과"],
            "커뮤니케이트": ["communicate", "외부"],
            "빌드": ["build", "개발", "구축"],
        }
        for key, kws in agent_keywords.items():
            if key in task_lower or any(k in task_lower for k in kws):
                keywords.extend(kws)
        # 태스크 자체 단어도 추가
        for word in task_lower.split():
            if len(word) > 2:
                keywords.append(word)
        return keywords

    def _get_next_1h_plan(now: datetime) -> list[str]:
        """앞으로 1시간 실제 실행될 작업 — proactive 24시간 플랜 + 목표 기반"""
        plan = []
        current_hour = now.hour
        next_hour = (current_hour + 1) % 24

        # 1. proactive agent의 24시간 플랜에서 현재/다음 시간 태스크 읽기
        try:
            mem_file = os.path.join(os.path.dirname(__file__), "data", "self_memory.json")
            with open(mem_file, "r", encoding="utf-8") as f:
                mem = json.load(f)
            hourly_plan = mem.get("plans", {}).get("current_plan", {}).get("hours", {})

            # proactive state에서 마지막 실행 슬롯 확인
            state_file = os.path.join(os.path.dirname(__file__), "data", "proactive_state.json")
            with open(state_file, "r", encoding="utf-8") as f:
                pstate = json.load(f)
            last_exec_hour = pstate.get("last_executed_hour", -1)

            # 현재 시간대 태스크
            hour_key = f"{current_hour:02d}"
            hour_task = hourly_plan.get(hour_key, {})
            if hour_task:
                task_name = hour_task.get("task", "")
                method = hour_task.get("method", "")
                expected = hour_task.get("expected", "")
                if current_hour != last_exec_hour:
                    plan.append(f"[{method}] {task_name} → {expected}")
                else:
                    # 이미 실행됨 — 슬롯 결과 + 다음 시간 예고
                    slot_key = f"slot_{current_hour:02d}:{(now.minute // 10) * 10:02d}_result"
                    slot_result = pstate.get(slot_key, {})
                    if slot_result:
                        grade = slot_result.get("grade", "?")
                        result = slot_result.get("result", "")[:50]
                        plan.append(f"[완료:{grade}] {task_name} — {result}")
                    # 다음 시간 태스크 예고 (항상 표시)
                    next_hour_key = f"{(current_hour + 1) % 24:02d}"
                    next_task = hourly_plan.get(next_hour_key, {})
                    if next_task:
                        plan.append(f"[예정] {next_task.get('task','')} [{next_task.get('method','')}]")
        except Exception:
            pass

        # 2. 활성 목표의 다음 스텝
        try:
            goals_file = os.path.join(os.path.dirname(__file__), "data", "goals.json")
            with open(goals_file, "r", encoding="utf-8") as f:
                goals = json.load(f)
            if isinstance(goals, list):
                goal_list = goals
            else:
                goal_list = goals.get("goals", [])
            for g in goal_list:
                if g.get("status") != "active":
                    continue
                steps = g.get("steps", [])
                pending = [s for s in steps if s.get("status") == "pending"]
                if pending:
                    plan.append(f"[목표] {g.get('title','')[:30]} → {pending[0].get('description','')[:40]}")
                    break  # 가장 우선순위 높은 것 하나만
        except Exception:
            pass

        # 3. AI 전략실 진행보고 (30분 간격)
        plan.append("AI 전략실 진행보고 (30분 간격)")

        # 4. 재시도 대기 작업 (있으면)
        retry_queue = pstate.get("retry_queue", [])
        if retry_queue:
            for rt in retry_queue[:2]:
                plan.append(f"[재시도] {rt.get('task', '미상')[:40]}")

        # 계획이 비면 기본값
        if not plan:
            plan = ["슬랙 메시지 폴링 (12초 간격)", "활성 목표 스텝 실행"]

        return plan

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
                        channel = cmd.get("channel", SlackClient.CHANNEL_GENERAL)
                        text = cmd.get("text", "")
                        thread_ts = cmd.get("thread_ts")
                        if thread_ts:
                            await slack.send_thread_reply(channel, thread_ts, text)
                        else:
                            await slack.send_message(channel, text)

                    elif cmd_type == "dev":
                        # dev 작업 직접 실행
                        task_desc = cmd.get("task", "")
                        channel = cmd.get("channel", SlackClient.CHANNEL_GENERAL)
                        thread_ts = cmd.get("thread_ts")
                        if task_desc:
                            start_msg = f"🎯 *[마스터]* dev 작업 지시\n> {task_desc[:200]}"
                            if thread_ts:
                                await _reply(channel, start_msg, thread_ts)
                            else:
                                await slack.send_message(channel, start_msg)

                            try:
                                output = await curator.ai_think(
                                    system_prompt="소프트웨어 엔지니어로서 요청된 작업을 분석하고 구체적 결과물을 만드세요.",
                                    user_prompt=task_desc,
                                )
                                if output:
                                    result = output[:3000]
                                    done_msg = f"✅ *[마스터]* 작업 완료!\n\n{result}"
                                    if thread_ts:
                                        await _reply(channel, done_msg, thread_ts)
                                    else:
                                        await slack.send_message(channel, done_msg)
                                else:
                                    err_msg = "⚠️ *[마스터]* 작업 결과 생성 실패"
                                    if thread_ts:
                                        await _reply(channel, err_msg, thread_ts)
                                    else:
                                        await slack.send_message(channel, err_msg)
                            except Exception as e:
                                err_msg = f"⚠️ *[마스터]* 작업 오류:\n```{str(e)[:500]}```"
                                if thread_ts:
                                    await _reply(channel, err_msg, thread_ts)
                                else:
                                    await slack.send_message(channel, err_msg)
                                logger.error(f"[master] Dev command failed: {e}")

                    elif cmd_type == "collect":
                        query = cmd.get("query", "")
                        if query:
                            await cmd_collect(args=query, user="master", channel=SlackClient.CHANNEL_GENERAL)

                    elif cmd_type == "briefing":
                        await cmd_briefing(args="", user="master", channel=SlackClient.CHANNEL_GENERAL)

                    elif cmd_type == "trigger_proactive":
                        action = cmd.get("action", "find_work")
                        logger.info(f"[master] Triggering proactive: {action}")
                        handler = getattr(proactive, f"_do_{action}", None)
                        if handler:
                            ctx = await proactive.observe()
                            await handler(ctx)

                    elif cmd_type == "slack_reply":
                        # 특정 스레드에 유저처럼 메시지 (봇이 아닌 명령으로)
                        channel = cmd.get("channel", SlackClient.CHANNEL_GENERAL)
                        thread_ts = cmd.get("thread_ts")
                        text = cmd.get("text", "")
                        if text and thread_ts:
                            # NL 핸들러를 직접 호출 (봇 필터 우회)
                            await on_natural_language(
                                text=text, user="master", channel=channel, thread_ts=thread_ts
                            )

                    logger.info(f"[master] Command '{cmd_type}' completed")
                except Exception as e:
                    logger.error(f"[master] Command '{cmd_type}' failed: {e}")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        except Exception as e:
            logger.error(f"[master] Queue processing error: {e}")

    if socket_mode:
        # Socket Mode: 이벤트는 WebSocket으로 자동 수신
        # 단, 봇 자신의 메시지(마스터 명령)는 Socket으로 안 오므로 폴링 병행
        logger.info("All agents running. Socket Mode active + polling(30s) + watchdog (1시간 정각 리포트)")
        poll_tick = 0
        while not shutdown_event.is_set():
            agent_tracker.heartbeat("orchestrator")
            poll_tick += 1
            # 30초마다 폴링 (봇 자신의 !명령어/[마스터] 메시지 수신용)
            if poll_tick % 4 == 1:  # 2분마다 로그
                logger.info(f"[socket-poll] tick #{poll_tick}, channels={len(slack._poll_channels)}, running={slack._running}")
            try:
                await slack.poll_once()
                await process_command_queue()
            except Exception as e:
                logger.error(f"Poll error: {e}")
            now_kst = datetime.now(KST)
            current_slot = f"{now_kst.hour}:00"
            if now_kst.minute == 0 and now_kst.hour % 4 == 0 and current_slot != last_report_slot:
                last_report_slot = current_slot
                try:
                    await master_health_check()
                except Exception as e:
                    logger.error(f"[watchdog] Health check error: {e}")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass
    else:
        # 폴링 모드: 3초마다 메시지 확인 + 1시간마다 헬스체크
        logger.info("All agents running. Polling (3s) + watchdog (1시간 점검) 시작...")
        poll_count = 0
        while not shutdown_event.is_set():
            poll_count += 1
            agent_tracker.heartbeat("orchestrator")
            if poll_count % 20 == 1:  # 1분마다 로그
                thread_count = sum(len(v) for v in slack._active_threads.values())
                logger.info(f"[main] Poll tick #{poll_count} (alive, {thread_count} threads tracked)")
            try:
                await slack.poll_once()
                await process_command_queue()
            except Exception as e:
                logger.error(f"Poll error: {e}")

            # 4시간마다 정각(KST 0,4,8,12,16,20시)에 마스터 헬스체크
            now_kst = datetime.now(KST)
            current_slot = f"{now_kst.hour}:00"
            if now_kst.minute == 0 and now_kst.hour % 4 == 0 and current_slot != last_report_slot:
                last_report_slot = current_slot
                try:
                    await master_health_check()
                except Exception as e:
                    logger.error(f"[watchdog] Health check error: {e}")

            # shutdown 체크와 함께 3초 대기
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
