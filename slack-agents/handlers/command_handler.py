"""
CommandHandler - 슬랙 ! 명령어 처리 모듈

!수집, !브리핑, !상태, !명언, !로그, !현황, !시세 명령어를 처리한다.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core import agent_tracker

logger = logging.getLogger("orchestrator.command_handler")

KST = timezone(timedelta(hours=9))


async def _reply(slack, channel: str, text: str, thread_ts: str = None, broadcast: bool = False):
    """스레드가 있으면 스레드로, 없으면 채널에 직접 전송. broadcast=True면 채널에도 표시"""
    if thread_ts:
        await slack.send_thread_reply(channel, thread_ts, text, also_send_to_channel=broadcast)
    else:
        await slack.send_message(channel, text)


class CommandHandler:
    """슬랙 ! 명령어를 처리하는 핸들러"""

    def __init__(self, slack, collector, curator, quote, investment):
        """
        Args:
            slack: SlackClient 인스턴스
            collector: CollectorAgent 인스턴스
            curator: CuratorAgent 인스턴스
            quote: QuoteAgent 인스턴스
            investment: InvestmentAgent 인스턴스
        """
        self.slack = slack
        self.collector = collector
        self.curator = curator
        self.quote = quote
        self.investment = investment

    async def reply(self, channel: str, text: str, thread_ts: str = None, broadcast: bool = False):
        """_reply 래퍼"""
        await _reply(self.slack, channel, text, thread_ts, broadcast)

    async def cmd_collect(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!수집 키워드 → 수집 에이전트에 키워드 수집 즉시 실행"""
        if args.strip():
            query = args.strip()
            self.curator.set_query_context(query, thread_ts=thread_ts, channel=channel)
            await self.collector._collect_by_keyword(query, user, thread_ts=thread_ts)
        else:
            await self.reply(channel, "사용법: `!수집 키워드`", thread_ts)

    async def cmd_briefing(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!브리핑 → 선별 에이전트에 즉시 브리핑 요청"""
        self.curator.set_query_context("브리핑", thread_ts=thread_ts, channel=channel)
        context = await self.curator.observe()
        if context:
            decision = await self.curator.think(context)
            if decision:
                await self.curator.act(decision)
        else:
            await self.reply(channel, "새로운 정보가 없습니다.", thread_ts)

    async def cmd_status(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!상태 → 전체 시스템 상태 확인"""
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        status_msg = f"*시스템 상태* ({now})\n"
        status_msg += f"- Collector: 실행 중 (간격: {self.collector.loop_interval}초)\n"
        status_msg += f"- Curator: 실행 중 (간격: {self.curator.loop_interval}초)\n"
        status_msg += f"- Curator 대기 버퍼: {len(self.curator._new_articles_buffer)}건\n"
        await self.reply(channel, status_msg, thread_ts)

    async def cmd_quote(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!명언 → 명언 에이전트 즉시 실행"""
        context = {
            "current_time": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
            "current_hour": datetime.now(KST).hour,
            "recent_conversations": [],
            "sent_history": self.quote._quote_history[-30:],
        }
        try:
            recent = await self.quote._fetch_recent_messages()
            context["recent_conversations"] = recent[:20]
        except Exception as e:
            logger.debug(f"[quote] Recent messages fetch failed: {e}")
        decision = await self.quote.think(context)
        if decision:
            decision["action"] = "send_quote"
            msg = self.quote._format_message(decision)
            await self.reply(channel, msg, thread_ts)
            self.quote._quote_history.append(f"{decision['quote_ko']} — {decision['author']}")
            self.quote._save_history()
        else:
            await self.reply(channel, "명언 생성에 실패했어요.", thread_ts)

    async def cmd_log(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!로그 → 요청사항 이력 보기"""
        log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "request_log.json")
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.loads(f.read())
            if not logs:
                await self.reply(channel, "요청 이력이 없습니다.", thread_ts)
                return
            latest = logs[-1]
            lines = [f"📋 *요청사항 로그* ({latest['date']})\n"]
            for r in latest.get("requests", []):
                status = "✅" if r["status"] == "done" else "🔄"
                lines.append(f"{status} {r['request']}")
                lines.append(f"   _{r.get('changes', '')[:80]}_")
            await self.reply(channel, "\n".join(lines), thread_ts)
        except Exception as e:
            await self.reply(channel, f"로그 로드 실패: {e}", thread_ts)

    async def cmd_dashboard(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!현황 → 에이전트 가동 현황 보기"""
        report = agent_tracker.get_status_report()
        await self.reply(channel, report, thread_ts)

    async def cmd_market(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!시세 → 투자 에이전트 즉시 브리핑"""
        try:
            prices = await self.investment._fetch_all_prices()
            fg = await self.investment._fetch_fear_greed()
            await self.investment._send_market_briefing({
                "prices": prices,
                "fear_greed": fg,
                "hour": datetime.now(KST).hour,
            })
        except Exception as e:
            await self.reply(channel, f"시세 조회 실패: {e}", thread_ts)

    def register(self):
        """슬랙 클라이언트에 명령어 핸들러를 등록한다."""
        self.slack.on_command("수집", self.cmd_collect)
        self.slack.on_command("브리핑", self.cmd_briefing)
        self.slack.on_command("상태", self.cmd_status)
        self.slack.on_command("명언", self.cmd_quote)
        self.slack.on_command("로그", self.cmd_log)
        self.slack.on_command("현황", self.cmd_dashboard)
        self.slack.on_command("시세", self.cmd_market)
