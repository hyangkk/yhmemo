"""
CommandHandler - 슬랙 ! 명령어 처리 모듈

!수집, !브리핑, !상태, !명언, !로그, !현황, !시세 등
뱅(!) 명령어 핸들러를 관리.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core import agent_tracker
from core.youtube_transcript import (
    extract_video_id,
    fetch_transcript,
    fetch_video_info,
    summarize_transcript,
)

logger = logging.getLogger("orchestrator.command_handler")

KST = timezone(timedelta(hours=9))


async def _reply(slack, channel: str, text: str, thread_ts: str = None, broadcast: bool = False):
    """스레드가 있으면 스레드로, 없으면 채널에 직접 전송. broadcast=True면 채널에도 표시"""
    if thread_ts:
        await slack.send_thread_reply(channel, thread_ts, text, also_send_to_channel=broadcast)
    else:
        await slack.send_message(channel, text)


class CommandHandler:
    """슬랙 ! 명령어 등록 및 처리"""

    def __init__(self, slack, collector, curator, quote, investment, anthropic_api_key: str = ""):
        """
        Args:
            slack: SlackClient 인스턴스
            collector: CollectorAgent 인스턴스
            curator: CuratorAgent 인스턴스
            quote: QuoteAgent 인스턴스
            investment: InvestmentAgent 인스턴스
            anthropic_api_key: Claude API 키 (영상 요약용)
        """
        self.slack = slack
        self.collector = collector
        self.curator = curator
        self.quote = quote
        self.investment = investment
        self._anthropic_api_key = anthropic_api_key

    def register(self):
        """모든 명령어를 슬랙 클라이언트에 등록"""
        self.slack.on_command("수집", self.cmd_collect)
        self.slack.on_command("브리핑", self.cmd_briefing)
        self.slack.on_command("상태", self.cmd_status)
        self.slack.on_command("명언", self.cmd_quote)
        self.slack.on_command("로그", self.cmd_log)
        self.slack.on_command("현황", self.cmd_dashboard)
        self.slack.on_command("시세", self.cmd_market)
        self.slack.on_command("영상요약", self.cmd_video_summary)

    async def cmd_collect(self, args: str, user: str, channel: str, thread_ts: str = None):
        if args.strip():
            query = args.strip()
            self.curator.set_query_context(query, thread_ts=thread_ts, channel=channel)
            await self.collector._collect_by_keyword(query, user, thread_ts=thread_ts)
        else:
            await _reply(self.slack, channel, "사용법: `!수집 키워드`", thread_ts)

    async def cmd_briefing(self, args: str, user: str, channel: str, thread_ts: str = None):
        self.curator.set_query_context("브리핑", thread_ts=thread_ts, channel=channel)
        context = await self.curator.observe()
        if context:
            decision = await self.curator.think(context)
            if decision:
                await self.curator.act(decision)
        else:
            await _reply(self.slack, channel, "새로운 정보가 없습니다.", thread_ts)

    async def cmd_status(self, args: str, user: str, channel: str, thread_ts: str = None):
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        status_msg = f"*시스템 상태* ({now})\n"
        status_msg += f"- Collector: 실행 중 (간격: {self.collector.loop_interval}초)\n"
        status_msg += f"- Curator: 실행 중 (간격: {self.curator.loop_interval}초)\n"
        status_msg += f"- Curator 대기 버퍼: {len(self.curator._new_articles_buffer)}건\n"
        await _reply(self.slack, channel, status_msg, thread_ts)

    async def cmd_quote(self, args: str, user: str, channel: str, thread_ts: str = None):
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
            await _reply(self.slack, channel, msg, thread_ts)
            self.quote._quote_history.append(f"{decision['quote_ko']} — {decision['author']}")
            self.quote._save_history()
        else:
            await _reply(self.slack, channel, "명언 생성에 실패했어요.", thread_ts)

    async def cmd_log(self, args: str, user: str, channel: str, thread_ts: str = None):
        log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "request_log.json")
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                logs = json.loads(f.read())
            if not logs:
                await _reply(self.slack, channel, "요청 이력이 없습니다.", thread_ts)
                return
            latest = logs[-1]
            lines = [f"📋 *요청사항 로그* ({latest['date']})\n"]
            for r in latest.get("requests", []):
                status = "✅" if r["status"] == "done" else "🔄"
                lines.append(f"{status} {r['request']}")
                lines.append(f"   _{r.get('changes', '')[:80]}_")
            await _reply(self.slack, channel, "\n".join(lines), thread_ts)
        except Exception as e:
            await _reply(self.slack, channel, f"로그 로드 실패: {e}", thread_ts)

    async def cmd_dashboard(self, args: str, user: str, channel: str, thread_ts: str = None):
        report = agent_tracker.get_status_report()
        await _reply(self.slack, channel, report, thread_ts)

    async def cmd_market(self, args: str, user: str, channel: str, thread_ts: str = None):
        try:
            prices = await self.investment._fetch_all_prices()
            fg = await self.investment._fetch_fear_greed()
            await self.investment._send_market_briefing({
                "prices": prices,
                "fear_greed": fg,
                "hour": datetime.now(KST).hour,
            })
        except Exception as e:
            await _reply(self.slack, channel, f"시세 조회 실패: {e}", thread_ts)

    async def cmd_video_summary(self, args: str, user: str, channel: str, thread_ts: str = None):
        """!영상요약 <YouTube URL> [모드] - YouTube 영상 자막 추출 및 요약

        모드:
            요약 (기본) - 핵심 내용 요약
            전체 - 전체 스크립트 정리
            포인트 - 핵심 포인트만 추출
        """
        if not args.strip():
            await _reply(self.slack, channel,
                "사용법: `!영상요약 <YouTube URL>` [요약|전체|포인트]\n"
                "예: `!영상요약 https://youtube.com/watch?v=xxx`\n"
                "예: `!영상요약 https://youtu.be/xxx 전체`",
                thread_ts)
            return

        # URL과 모드 파싱
        parts = args.strip().split()
        url_part = parts[0]
        mode_map = {"요약": "summary", "전체": "full", "포인트": "key_points"}
        mode = "summary"
        for p in parts[1:]:
            if p in mode_map:
                mode = mode_map[p]

        video_id = extract_video_id(url_part)
        if not video_id:
            # 전체 args에서 URL 찾기 시도
            video_id = extract_video_id(args)

        if not video_id:
            await _reply(self.slack, channel,
                "YouTube URL을 인식할 수 없습니다. 올바른 YouTube 링크를 입력해주세요.",
                thread_ts)
            return

        await _reply(self.slack, channel, "영상 자막을 가져오는 중...", thread_ts)

        # 영상 정보 + 자막 추출
        video_info = await fetch_video_info(video_id)
        transcript_result = await fetch_transcript(video_id)

        if not transcript_result["ok"]:
            await _reply(self.slack, channel,
                f"자막 추출 실패: {transcript_result['error']}",
                thread_ts)
            return

        transcript_text = transcript_result["text"]
        lang = transcript_result.get("language", "")
        auto = " (자동 생성)" if transcript_result.get("auto_generated") else ""
        title = video_info.get("title", "")
        author = video_info.get("author", "")

        header = f"*{title}*" if title else f"영상 `{video_id}`"
        if author:
            header += f" — {author}"
        header += f"\n자막 언어: {lang}{auto} | 길이: {len(transcript_text):,}자"

        await _reply(self.slack, channel, f"{header}\n\nClaude로 요약 중...", thread_ts)

        # Claude 요약
        try:
            import anthropic
            ai_client = anthropic.AsyncAnthropic(api_key=self._anthropic_api_key)
            summary = await summarize_transcript(
                ai_client, transcript_text, video_title=title, mode=mode
            )

            mode_label = {"summary": "요약", "full": "전체 정리", "key_points": "핵심 포인트"}
            await _reply(self.slack, channel,
                f"{header}\n\n📝 *[{mode_label.get(mode, '요약')}]*\n\n{summary}",
                thread_ts)
        except Exception as e:
            logger.error(f"Video summary error: {e}")
            await _reply(self.slack, channel,
                f"{header}\n\n요약 생성 실패: {str(e)[:200]}",
                thread_ts)
