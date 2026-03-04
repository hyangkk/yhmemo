"""
Slack 연동 클라이언트

Socket Mode를 사용하여 웹훅 서버 없이 슬랙과 실시간 양방향 통신.
에이전트가 메시지를 보내고, 사용자 명령을 수신하고, 이모지 반응을 추적.
"""

import asyncio
import logging
from typing import Callable, Coroutine, Any

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


class SlackClient:
    """슬랙 통합 클라이언트"""

    # 기본 채널 이름들
    CHANNEL_GENERAL = "ai-agents-general"
    CHANNEL_COLLECTOR = "ai-collector"
    CHANNEL_CURATOR = "ai-curator"
    CHANNEL_LOGS = "ai-agent-logs"

    def __init__(self, bot_token: str, app_token: str):
        self.app = AsyncApp(token=bot_token)
        self.client = AsyncWebClient(token=bot_token)
        self._app_token = app_token
        self._channel_cache: dict[str, str] = {}  # name → id
        self._command_handlers: dict[str, Callable] = {}
        self._reaction_handlers: list[Callable] = []
        self._mention_handlers: list[Callable] = []

        self._setup_event_handlers()

    def _setup_event_handlers(self):
        """슬랙 이벤트 핸들러 등록"""

        @self.app.event("app_mention")
        async def handle_mention(event, say):
            """에이전트에 대한 멘션 처리"""
            text = event.get("text", "")
            user = event.get("user", "")
            channel = event.get("channel", "")
            for handler in self._mention_handlers:
                try:
                    await handler(text=text, user=user, channel=channel, say=say)
                except Exception as e:
                    logger.error(f"Mention handler error: {e}")

        @self.app.event("reaction_added")
        async def handle_reaction(event):
            """이모지 반응 추적 (사용자 피드백)"""
            reaction = event.get("reaction", "")
            item = event.get("item", {})
            user = event.get("user", "")
            for handler in self._reaction_handlers:
                try:
                    await handler(reaction=reaction, item=item, user=user)
                except Exception as e:
                    logger.error(f"Reaction handler error: {e}")

        @self.app.event("message")
        async def handle_message(event):
            """DM이나 채널 메시지 처리"""
            # bot 자신의 메시지는 무시
            if event.get("bot_id"):
                return
            text = event.get("text", "")
            user = event.get("user", "")
            channel = event.get("channel", "")

            # 슬래시 커맨드 패턴 처리 (예: "!수집 AI 뉴스")
            if text.startswith("!"):
                parts = text[1:].split(maxsplit=1)
                cmd = parts[0]
                args = parts[1] if len(parts) > 1 else ""
                handler = self._command_handlers.get(cmd)
                if handler:
                    await handler(args=args, user=user, channel=channel)

    # ── 메시지 전송 ────────────────────────────────────

    async def send_message(self, channel: str, text: str, blocks: list = None) -> dict:
        """채널에 메시지 전송"""
        channel_id = await self._resolve_channel(channel)
        try:
            result = await self.client.chat_postMessage(
                channel=channel_id,
                text=text,
                blocks=blocks,
                unfurl_links=False,
            )
            return result
        except Exception as e:
            logger.error(f"Failed to send message to {channel}: {e}")
            raise

    async def send_log(self, message: str):
        """로그 채널에 메시지 전송"""
        try:
            await self.send_message(self.CHANNEL_LOGS, f"```{message}```")
        except Exception:
            logger.debug(f"Log: {message}")

    async def send_rich_message(self, channel: str, title: str, fields: dict, color: str = "#36a64f"):
        """리치 포맷 메시지 (attachment) 전송"""
        channel_id = await self._resolve_channel(channel)
        attachments = [{
            "color": color,
            "title": title,
            "fields": [
                {"title": k, "value": v, "short": len(str(v)) < 40}
                for k, v in fields.items()
            ],
        }]
        await self.client.chat_postMessage(
            channel=channel_id,
            text=title,
            attachments=attachments,
        )

    async def send_thread_reply(self, channel: str, thread_ts: str, text: str):
        """스레드에 답글"""
        channel_id = await self._resolve_channel(channel)
        await self.client.chat_postMessage(
            channel=channel_id,
            text=text,
            thread_ts=thread_ts,
        )

    # ── 핸들러 등록 ────────────────────────────────────

    def on_command(self, command: str, handler: Callable):
        """사용자 명령어 핸들러 등록 (예: "!수집")"""
        self._command_handlers[command] = handler

    def on_mention(self, handler: Callable):
        """멘션 핸들러 등록"""
        self._mention_handlers.append(handler)

    def on_reaction(self, handler: Callable):
        """이모지 반응 핸들러 등록"""
        self._reaction_handlers.append(handler)

    # ── 채널 관리 ──────────────────────────────────────

    async def _resolve_channel(self, channel_name: str) -> str:
        """채널 이름 → ID 변환 (캐시)"""
        if channel_name.startswith("C"):  # 이미 ID인 경우
            return channel_name
        if channel_name in self._channel_cache:
            return self._channel_cache[channel_name]

        try:
            result = await self.client.conversations_list(types="public_channel,private_channel")
            for ch in result["channels"]:
                self._channel_cache[ch["name"]] = ch["id"]
            if channel_name in self._channel_cache:
                return self._channel_cache[channel_name]
        except Exception as e:
            logger.error(f"Failed to resolve channel '{channel_name}': {e}")

        return channel_name  # fallback

    async def ensure_channels_exist(self):
        """필요한 채널들이 있는지 확인하고 없으면 생성"""
        required = [self.CHANNEL_GENERAL, self.CHANNEL_COLLECTOR,
                    self.CHANNEL_CURATOR, self.CHANNEL_LOGS]
        try:
            result = await self.client.conversations_list(types="public_channel")
            existing = {ch["name"] for ch in result["channels"]}
            for ch_name in required:
                if ch_name not in existing:
                    logger.info(f"Creating channel: {ch_name}")
                    await self.client.conversations_create(name=ch_name)
        except Exception as e:
            logger.warning(f"Could not ensure channels: {e}")

    # ── 시작/종료 ──────────────────────────────────────

    async def start(self):
        """Socket Mode 연결 시작"""
        await self.ensure_channels_exist()
        handler = AsyncSocketModeHandler(self.app, self._app_token)
        await handler.start_async()

    async def start_background(self):
        """백그라운드에서 Socket Mode 실행"""
        await self.ensure_channels_exist()
        handler = AsyncSocketModeHandler(self.app, self._app_token)
        await handler.connect_async()
        logger.info("Slack Socket Mode connected")
