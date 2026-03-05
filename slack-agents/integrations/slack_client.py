"""
Slack 연동 클라이언트

두 가지 모드 지원:
1. Socket Mode (WebSocket) - 실시간 양방향 통신 (기본)
2. Polling Mode (HTTP) - WebSocket 불가 환경용 폴백

에이전트가 메시지를 보내고, 사용자 명령을 수신하고, 이모지 반응을 추적.
"""

import asyncio
import json
import logging
import os
import time
from typing import Callable, Coroutine, Any

from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


class SlackClient:
    """슬랙 통합 클라이언트"""

    # 기본 채널 이름들
    CHANNEL_GENERAL = "ai-agents-general"
    CHANNEL_COLLECTOR = "ai-collector"
    CHANNEL_CURATOR = "ai-curator"
    CHANNEL_LOGS = "ai-agent-logs"

    def __init__(self, bot_token: str, app_token: str = "", poll_interval: float = 30.0):
        self.client = AsyncWebClient(token=bot_token)
        self._bot_token = bot_token
        self._app_token = app_token
        self._poll_interval = poll_interval
        self._channel_cache: dict[str, str] = {}  # name → id
        self._command_handlers: dict[str, Callable] = {}
        self._reaction_handlers: list[Callable] = []
        self._mention_handlers: list[Callable] = []
        self._natural_language_handler: Callable | None = None
        self._running = False
        self._bot_user_id: str = ""

        # 폴링용 타임스탬프 (채널별 마지막 확인 시각)
        self._last_ts: dict[str, str] = {}
        # Socket Mode 객체 (사용 가능할 때만)
        self._socket_handler = None
        self._app = None

    # ── 메시지 전송 ────────────────────────────────────

    async def send_message(self, channel: str, text: str, blocks: list = None) -> dict:
        """채널에 메시지 전송 (rate limit 시 재시도)"""
        channel_id = await self._resolve_channel(channel)
        for attempt in range(3):
            try:
                result = await self.client.chat_postMessage(
                    channel=channel_id,
                    text=text,
                    blocks=blocks,
                    unfurl_links=False,
                )
                return result
            except Exception as e:
                if "ratelimited" in str(e) and attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
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

    async def add_reaction(self, channel: str, timestamp: str, emoji: str = "eyes"):
        """메시지에 이모지 리액션 추가"""
        channel_id = await self._resolve_channel(channel)
        try:
            await self.client.reactions_add(channel=channel_id, timestamp=timestamp, name=emoji)
        except Exception:
            pass  # 이미 리액션이 있거나 실패해도 무시

    async def send_thread_reply(self, channel: str, thread_ts: str, text: str, also_send_to_channel: bool = False):
        """스레드에 답글 (also_send_to_channel=True면 채널에도 표시)"""
        channel_id = await self._resolve_channel(channel)
        await self.client.chat_postMessage(
            channel=channel_id,
            text=text,
            thread_ts=thread_ts,
            reply_broadcast=also_send_to_channel,
        )

    # ── 핸들러 등록 ────────────────────────────────────

    def on_command(self, command: str, handler: Callable):
        """사용자 명령어 핸들러 등록 (예: "!수집")"""
        self._command_handlers[command] = handler

    def on_mention(self, handler: Callable):
        """멘션 핸들러 등록"""
        self._mention_handlers.append(handler)

    def on_natural_language(self, handler: Callable):
        """자연어 메시지 핸들러 등록 (명령어가 아닌 일반 메시지)"""
        self._natural_language_handler = handler

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
            result = await self.client.conversations_list(types="public_channel")
            for ch in result["channels"]:
                self._channel_cache[ch["name"]] = ch["id"]
            if channel_name in self._channel_cache:
                return self._channel_cache[channel_name]
        except Exception as e:
            logger.error(f"Failed to resolve channel '{channel_name}': {e}")

        return channel_name  # fallback

    async def ensure_channels_exist(self):
        """필요한 채널들이 있는지 확인하고 없으면 생성, 봇을 join"""
        required = [self.CHANNEL_GENERAL, self.CHANNEL_COLLECTOR,
                    self.CHANNEL_CURATOR, self.CHANNEL_LOGS]
        try:
            result = await self.client.conversations_list(types="public_channel")
            existing = {}
            for ch in result["channels"]:
                existing[ch["name"]] = ch["id"]

            for ch_name in required:
                if ch_name not in existing:
                    logger.info(f"Creating channel: {ch_name}")
                    resp = await self.client.conversations_create(name=ch_name)
                    existing[ch_name] = resp["channel"]["id"]

            # 봇을 모든 필수 채널에 join
            for ch_name in required:
                ch_id = existing.get(ch_name)
                if ch_id:
                    try:
                        await self.client.conversations_join(channel=ch_id)
                        logger.info(f"Joined channel: {ch_name} ({ch_id})")
                    except Exception as e:
                        logger.warning(f"Failed to join {ch_name}: {e}")
        except Exception as e:
            logger.warning(f"Could not ensure channels: {e}")

    # ── 폴링 타임스탬프 영속 저장 ──────────────────────

    _TS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "poll_last_ts.json")

    def _load_last_ts(self) -> dict:
        """저장된 채널별 마지막 ts 로드"""
        try:
            with open(self._TS_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_last_ts(self):
        """현재 채널별 마지막 ts 저장"""
        os.makedirs(os.path.dirname(self._TS_FILE), exist_ok=True)
        with open(self._TS_FILE, "w") as f:
            json.dump(self._last_ts, f)

    # ── 폴링 모드 ───────────────────────────────────────

    async def _get_bot_user_id(self):
        """봇 자신의 user ID 조회"""
        if not self._bot_user_id:
            result = await self.client.auth_test()
            self._bot_user_id = result["user_id"]
        return self._bot_user_id

    async def _poll_channel(self, channel_name: str):
        """한 채널의 새 메시지를 폴링"""
        channel_id = await self._resolve_channel(channel_name)
        if not channel_id or channel_id == channel_name:
            return

        try:
            kwargs = {"channel": channel_id, "limit": 10}
            if channel_id in self._last_ts:
                kwargs["oldest"] = self._last_ts[channel_id]

            result = await self.client.conversations_history(**kwargs)
            messages = result.get("messages", [])

            if not messages:
                return

            logger.info(f"[poll] {channel_name}: {len(messages)} new messages")

            # 가장 최신 타임스탬프 저장 (디스크에도 영속)
            newest_ts = messages[0]["ts"]
            self._last_ts[channel_id] = newest_ts
            self._save_last_ts()

            bot_id = await self._get_bot_user_id()

            # 오래된 것부터 처리 (역순)
            for msg in reversed(messages):
                # 봇 자신의 메시지 무시
                if msg.get("bot_id") or msg.get("user") == bot_id:
                    logger.debug(f"[poll] Skipping bot message: '{msg.get('text', '')[:30]}'")
                    continue

                text = msg.get("text", "")
                user = msg.get("user", "")
                channel = channel_id
                logger.info(f"[poll] New message: '{text[:50]}' from {user}")

                # 멘션 처리
                if f"<@{bot_id}>" in text:
                    for handler in self._mention_handlers:
                        try:
                            async def say(reply_text, ch=channel, ts=msg["ts"]):
                                await self.send_thread_reply(ch, ts, reply_text)
                            await handler(text=text, user=user, channel=channel, say=say)
                        except Exception as e:
                            logger.error(f"Mention handler error: {e}")

                # 명령어 처리
                elif text.startswith("!"):
                    parts = text[1:].split(maxsplit=1)
                    cmd = parts[0]
                    args = parts[1] if len(parts) > 1 else ""
                    handler = self._command_handlers.get(cmd)
                    if handler:
                        logger.info(f"[poll] Executing command: !{cmd}")
                        try:
                            await handler(args=args, user=user, channel=channel)
                        except Exception as e:
                            logger.error(f"Command handler error: {e}")

                # 자연어 메시지 처리
                elif self._natural_language_handler and text.strip():
                    logger.info(f"[poll] Natural language: '{text[:50]}'")
                    try:
                        await self._natural_language_handler(
                            text=text, user=user, channel=channel,
                            thread_ts=msg.get("ts"),
                        )
                    except Exception as e:
                        logger.error(f"Natural language handler error: {e}")

        except Exception as e:
            err_str = str(e)
            if "not_in_channel" in err_str:
                # 자동 join 시도
                try:
                    await self.client.conversations_join(channel=channel_id)
                    logger.info(f"Auto-joined channel: {channel_name}")
                except Exception:
                    pass
            elif "ratelimited" in err_str:
                await asyncio.sleep(30)
            else:
                logger.warning(f"Poll error for {channel_name}: {e}")

    async def _init_channel_cache(self):
        """채널 캐시 초기화 (재시도 포함)"""
        for attempt in range(5):
            try:
                result = await self.client.conversations_list(types="public_channel")
                for ch in result["channels"]:
                    self._channel_cache[ch["name"]] = ch["id"]
                logger.info(f"Channel cache loaded: {len(self._channel_cache)} channels")
                return True
            except Exception as e:
                logger.warning(f"Channel cache init attempt {attempt+1}/5 failed: {e}")
                await asyncio.sleep(2 ** attempt)
        return False

    async def _poll_loop(self):
        """모든 채널을 주기적으로 폴링"""
        logger.info(f"Polling mode started (interval: {self._poll_interval}s)")

        # 채널 캐시 초기화
        await self._init_channel_cache()

        # 명령어는 GENERAL 채널에서만 수신 (rate limit 방지)
        channels = [self.CHANNEL_GENERAL]

        for ch_name in channels:
            ch_id = self._channel_cache.get(ch_name)
            if ch_id:
                self._last_ts[ch_id] = str(time.time())

        logger.info(f"Polling channels: {[self._channel_cache.get(ch, '?') for ch in channels]}")

        while self._running:
            try:
                for ch_name in channels:
                    await self._poll_channel(ch_name)
            except Exception as e:
                logger.error(f"Poll loop error: {e}")
            await asyncio.sleep(self._poll_interval)

    # ── Socket Mode 시도 → 실패 시 폴링 ─────────────────

    async def _try_socket_mode(self) -> bool:
        """Socket Mode 연결 시도. 성공하면 True."""
        if not self._app_token or not self._app_token.startswith("xapp-"):
            return False
        try:
            from slack_bolt.async_app import AsyncApp
            from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

            self._app = AsyncApp(token=self._bot_token)
            self._setup_socket_event_handlers()
            handler = AsyncSocketModeHandler(self._app, self._app_token)
            await asyncio.wait_for(handler.connect_async(), timeout=5)
            self._socket_handler = handler
            logger.info("Slack Socket Mode connected")
            return True
        except Exception as e:
            logger.warning(f"Socket Mode 연결 실패, 폴링 모드로 전환: {e}")
            # 내부 재시도 태스크 정리
            try:
                if hasattr(self, '_app') and self._app:
                    await self._app.async_stop()
            except Exception:
                pass
            self._app = None
            return False

    def _setup_socket_event_handlers(self):
        """Socket Mode용 이벤트 핸들러 등록"""
        @self._app.event("app_mention")
        async def handle_mention(event, say):
            text = event.get("text", "")
            user = event.get("user", "")
            channel = event.get("channel", "")
            for handler in self._mention_handlers:
                try:
                    await handler(text=text, user=user, channel=channel, say=say)
                except Exception as e:
                    logger.error(f"Mention handler error: {e}")

        @self._app.event("reaction_added")
        async def handle_reaction(event):
            reaction = event.get("reaction", "")
            item = event.get("item", {})
            user = event.get("user", "")
            for handler in self._reaction_handlers:
                try:
                    await handler(reaction=reaction, item=item, user=user)
                except Exception as e:
                    logger.error(f"Reaction handler error: {e}")

        @self._app.event("message")
        async def handle_message(event):
            if event.get("bot_id") or event.get("subtype"):
                return
            text = event.get("text", "")
            user = event.get("user", "")
            channel = event.get("channel", "")
            thread_ts = event.get("ts")

            if not text.strip():
                return

            if text.startswith("!"):
                parts = text[1:].split(maxsplit=1)
                cmd = parts[0]
                args = parts[1] if len(parts) > 1 else ""
                handler = self._command_handlers.get(cmd)
                if handler:
                    await handler(args=args, user=user, channel=channel, thread_ts=thread_ts)
            elif self._natural_language_handler:
                logger.info(f"[socket] Natural language: '{text[:50]}'")
                try:
                    await self._natural_language_handler(
                        text=text, user=user, channel=channel,
                        thread_ts=thread_ts,
                    )
                except Exception as e:
                    logger.error(f"[socket] Natural language handler error: {e}")

    # ── 시작/종료 ──────────────────────────────────────

    async def start_background(self):
        """백그라운드에서 Slack 연결 (폴링 모드 초기화)"""
        await self.ensure_channels_exist()
        self._running = True
        # 폴링 채널 초기화
        await self._init_channel_cache()

        # 모든 public 채널에 봇 join
        for ch_name, ch_id in self._channel_cache.items():
            try:
                await self.client.conversations_join(channel=ch_id)
                logger.info(f"Joined channel: {ch_name} ({ch_id})")
            except Exception:
                pass  # 이미 참여 중이면 무시

        # 모든 채널 폴링 — 저장된 ts 복원 또는 기동 시점 사용
        channels = list(self._channel_cache.keys())
        saved_ts = self._load_last_ts()
        for ch_name in channels:
            ch_id = self._channel_cache.get(ch_name)
            if ch_id:
                if ch_id in saved_ts:
                    self._last_ts[ch_id] = saved_ts[ch_id]
                else:
                    self._last_ts[ch_id] = str(time.time() - 60)  # 1분 전
        self._poll_channels = channels
        logger.info(f"Polling mode ready (interval: {self._poll_interval}s)")
        logger.info(f"Polling channels: {channels}")

    async def poll_once(self):
        """한 번 폴링 (외부에서 주기적으로 호출)"""
        if not self._running:
            return
        for ch_name in self._poll_channels:
            await self._poll_channel(ch_name)

    def stop(self):
        """폴링 중지"""
        self._running = False
