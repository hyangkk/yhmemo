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

    # 채널 ID (이름 변경에도 영향 없음)
    CHANNEL_GENERAL = "C0AJJ469SV8"    # ai-agents-general
    CHANNEL_COLLECTOR = "C0AJBN0PDQB"  # ai-collector
    CHANNEL_CURATOR = "C0AJEM4J5KP"    # ai-curator
    CHANNEL_LOGS = "C0AJJ464VJN"       # ai-agent-logs
    CHANNEL_QUOTE = "C0AJUJTHJGL"      # 명언-한마디
    CHANNEL_INVEST = "C0AKRJZ395W"    # ai-invest

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
        # 활성 스레드 추적: {channel_id: {thread_ts: last_reply_ts}}
        self._active_threads: dict[str, dict[str, str]] = {}
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
                # 봇이 보낸 메시지를 자동으로 스레드 추적에 등록
                # (유저가 답글 달면 감지하기 위해)
                # 로그 채널은 제외
                msg_ts = result.get("ts")
                if msg_ts and channel_id and channel_id != self.CHANNEL_LOGS:
                    if channel_id not in self._active_threads:
                        self._active_threads[channel_id] = {}
                    self._active_threads[channel_id][msg_ts] = msg_ts
                    # 채널당 최근 20개 스레드만 추적
                    threads = self._active_threads[channel_id]
                    if len(threads) > 20:
                        oldest_keys = sorted(threads.keys())[:len(threads) - 20]
                        for k in oldest_keys:
                            threads.pop(k, None)
                    self._save_active_threads()
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
        result = await self.client.chat_postMessage(
            channel=channel_id,
            text=text,
            thread_ts=thread_ts,
            reply_broadcast=also_send_to_channel,
        )
        # 봇이 답글 단 스레드를 활성 스레드로 추적 → 유저 답글 감지
        if channel_id not in self._active_threads:
            self._active_threads[channel_id] = {}
        reply_ts = result.get("ts", str(time.time()))
        self._active_threads[channel_id][thread_ts] = reply_ts
        self._save_active_threads()

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
        """필요한 채널에 봇을 join (채널 ID 기반)"""
        required = [self.CHANNEL_GENERAL, self.CHANNEL_COLLECTOR,
                    self.CHANNEL_CURATOR, self.CHANNEL_LOGS, self.CHANNEL_QUOTE,
                    self.CHANNEL_INVEST]
        for ch_id in required:
            try:
                await self.client.conversations_join(channel=ch_id)
                logger.info(f"Joined channel: {ch_id}")
            except Exception as e:
                if "already_in_channel" not in str(e):
                    logger.warning(f"Failed to join {ch_id}: {e}")

    # ── 폴링 타임스탬프 영속 저장 ──────────────────────

    _TS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "poll_last_ts.json")
    _THREADS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "active_threads.json")

    def _load_last_ts(self) -> dict:
        """저장된 채널별 마지막 ts 로드"""
        try:
            with open(self._TS_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _load_active_threads(self) -> dict:
        """저장된 활성 스레드 로드"""
        try:
            with open(self._THREADS_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_active_threads(self):
        """활성 스레드 디스크에 저장"""
        os.makedirs(os.path.dirname(self._THREADS_FILE), exist_ok=True)
        # 채널당 최근 20개 스레드만 유지
        trimmed = {}
        for ch, threads in self._active_threads.items():
            sorted_threads = sorted(threads.items(), key=lambda x: x[1], reverse=True)[:20]
            trimmed[ch] = dict(sorted_threads)
        with open(self._THREADS_FILE, "w") as f:
            json.dump(trimmed, f)

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

    async def _poll_threads(self, channel_id: str, bot_id: str):
        """활성 스레드의 답글을 백그라운드에서 폴링 (메인 폴링 루프를 블로킹하지 않음)"""
        try:
            active = self._active_threads.get(channel_id, {})
            if not active:
                return
            stale_threads = []
            # 최근 활동 기준 10개 폴링 (last_reply_ts가 큰 = 최근 활동한 스레드 우선)
            thread_items = sorted(active.items(), key=lambda x: max(x[0], x[1]), reverse=True)[:10]
            logger.info(f"[threads] Polling {len(thread_items)}/{len(active)} threads for {channel_id}")
            for thread_ts, last_reply_ts in thread_items:
                try:
                    reply_result = await asyncio.wait_for(
                        self.client.conversations_replies(
                            channel=channel_id, ts=thread_ts, oldest=last_reply_ts, limit=5,
                        ),
                        timeout=5.0,
                    )
                    replies = reply_result.get("messages", [])
                    new_reply_found = False
                    for reply in replies:
                        if reply["ts"] == last_reply_ts or reply["ts"] == thread_ts:
                            continue
                        if reply.get("bot_id") or reply.get("user") == bot_id:
                            active[thread_ts] = reply["ts"]
                            continue
                        reply_text = reply.get("text", "")
                        reply_user = reply.get("user", "")
                        if reply_text.strip() and self._natural_language_handler:
                            new_reply_found = True
                            logger.info(f"[poll] Thread reply detected: '{reply_text[:80]}' from {reply_user} in thread {thread_ts}")
                            asyncio.create_task(self._safe_nl_handler(
                                text=reply_text, user=reply_user, channel=channel_id,
                                thread_ts=thread_ts,
                            ))
                        active[thread_ts] = reply["ts"]
                    if new_reply_found:
                        self._save_active_threads()
                    await asyncio.sleep(0.5)  # API 레이트 리밋 방지
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    err = str(e)
                    if "thread_not_found" in err:
                        stale_threads.append(thread_ts)
                    elif "ratelimited" in err:
                        logger.warning(f"[threads] Rate limited, backing off")
                        await asyncio.sleep(5)
                        break
                    else:
                        logger.warning(f"Thread poll error: {type(e).__name__}: {err[:120]}")
            for t in stale_threads:
                active.pop(t, None)
            if stale_threads:
                self._save_active_threads()
        except Exception as e:
            logger.warning(f"Thread polling error: {e}")

    async def _safe_nl_handler(self, text: str, user: str, channel: str, thread_ts: str = None):
        """NL 핸들러를 안전하게 실행 (에러 로깅)"""
        try:
            await self._natural_language_handler(
                text=text, user=user, channel=channel, thread_ts=thread_ts,
            )
        except Exception as e:
            logger.error(f"NL handler error: {e}")

    async def _poll_channel(self, channel_name: str):
        """한 채널의 새 메시지를 폴링 (채널 ID 또는 이름)"""
        channel_id = await self._resolve_channel(channel_name)
        if not channel_id:
            return

        try:
            kwargs = {"channel": channel_id, "limit": 10}
            if channel_id in self._last_ts:
                kwargs["oldest"] = self._last_ts[channel_id]

            logger.debug(f"[poll] Checking {channel_id} (oldest={kwargs.get('oldest', 'none')})")
            result = await asyncio.wait_for(
                self.client.conversations_history(**kwargs), timeout=10.0
            )
            messages = result.get("messages", [])

            bot_id = await self._get_bot_user_id()

            # ── 1. 새 채널 메시지 처리 ──
            if messages:
                logger.info(f"[poll] {channel_id}: {len(messages)} new messages")

                # 가장 최신 타임스탬프 저장 (디스크에도 영속)
                newest_ts = messages[0]["ts"]
                self._last_ts[channel_id] = newest_ts
                self._save_last_ts()

                # 오래된 것부터 처리 (역순)
                for msg in reversed(messages):
                    # 봇 자신의 메시지 무시 (단, !명령어 또는 [마스터] 접두사는 허용)
                    text_peek = msg.get("text", "")
                    is_master = text_peek.startswith("!") or text_peek.startswith("[마스터]")
                    if (msg.get("bot_id") or msg.get("user") == bot_id) and not is_master:
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

                    # 자연어 메시지 처리 (논블로킹 - LLM 호출이 폴링을 막지 않도록)
                    elif self._natural_language_handler and text.strip():
                        logger.info(f"[poll] Natural language: '{text[:50]}'")
                        asyncio.create_task(self._safe_nl_handler(
                            text=text, user=user, channel=channel,
                            thread_ts=msg.get("ts"),
                        ))

                # 스레드 자동 발견
                for msg in messages:
                    if msg.get("reply_count", 0) > 0 and msg.get("ts"):
                        if channel_id not in self._active_threads:
                            self._active_threads[channel_id] = {}
                        if msg["ts"] not in self._active_threads[channel_id]:
                            self._active_threads[channel_id][msg["ts"]] = msg.get("latest_reply", msg["ts"])
                            logger.info(f"[poll] Auto-tracked thread: {msg['ts']} ({msg.get('reply_count')} replies)")

        except asyncio.TimeoutError:
            pass  # conversations_history 타임아웃은 다음 사이클에 재시도
        except Exception as e:
            err_str = str(e)
            if "not_in_channel" in err_str:
                try:
                    await self.client.conversations_join(channel=channel_id)
                    logger.info(f"Auto-joined channel: {channel_name}")
                except Exception:
                    pass
            elif "ratelimited" in err_str:
                await asyncio.sleep(30)
            else:
                logger.warning(f"Poll error for {channel_name}: {type(e).__name__}: {e}")

        # ── 2. 스레드 답글 폴링 (10초마다, 레이트 리밋 방지) ──
        try:
            active = self._active_threads.get(channel_id, {})
            if active:
                now = time.time()
                last_thread_poll = getattr(self, '_last_thread_poll', {}).get(channel_id, 0)
                if now - last_thread_poll >= 10:  # 10초 간격
                    if not hasattr(self, '_last_thread_poll'):
                        self._last_thread_poll = {}
                    self._last_thread_poll[channel_id] = now
                    bot_id = await self._get_bot_user_id()
                    asyncio.create_task(self._poll_threads(channel_id, bot_id))
        except Exception as e:
            logger.debug(f"Thread poll dispatch error: {e}")

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

        # 명령어 수신 채널 (GENERAL + INVEST)
        channels = [self.CHANNEL_GENERAL, self.CHANNEL_INVEST]

        for ch_id in channels:
            self._last_ts[ch_id] = str(time.time())

        logger.info(f"Polling channels: {channels}")

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

        async def _process_message(event):
            """Socket Mode 메시지 공통 처리"""
            text = event.get("text", "")
            user = event.get("user", "")
            channel = event.get("channel", "")
            thread_ts = event.get("thread_ts") or event.get("ts")

            if not text.strip():
                return

            if text.startswith("!"):
                parts = text[1:].split(maxsplit=1)
                cmd = parts[0]
                args = parts[1] if len(parts) > 1 else ""
                handler = self._command_handlers.get(cmd)
                if handler:
                    logger.info(f"[socket] Executing command: !{cmd}")
                    await handler(args=args, user=user, channel=channel, thread_ts=thread_ts)
            elif text.startswith("[마스터]"):
                if self._natural_language_handler:
                    logger.info(f"[socket] Master command: '{text[:50]}'")
                    await self._natural_language_handler(
                        text=text, user=user, channel=channel, thread_ts=thread_ts,
                    )
            elif not event.get("bot_id"):
                # 일반 유저 메시지만 자연어 처리
                if self._natural_language_handler:
                    logger.info(f"[socket] Natural language: '{text[:50]}'")
                    try:
                        await self._natural_language_handler(
                            text=text, user=user, channel=channel,
                            thread_ts=thread_ts,
                        )
                    except Exception as e:
                        logger.error(f"[socket] Natural language handler error: {e}")

        @self._app.event("message")
        async def handle_message(event):
            if event.get("bot_id") or event.get("subtype"):
                return
            await _process_message(event)

        # 봇 자신의 메시지 (bot_message subtype) → !명령어/[마스터] 셀프 테스트용
        @self._app.event({"type": "message", "subtype": "bot_message"})
        async def handle_bot_message(event):
            text = event.get("text", "")
            if text.startswith("!") or text.startswith("[마스터]"):
                logger.info(f"[socket] Bot self-command: '{text[:50]}'")
                await _process_message(event)

    # ── 시작/종료 ──────────────────────────────────────

    async def start_background(self):
        """백그라운드에서 Slack 연결 (폴링 모드 초기화)"""
        await self.ensure_channels_exist()
        self._running = True
        # 폴링 채널 초기화
        await self._init_channel_cache()

        # 봇이 참여할 채널 (필수 채널만)
        for ch_id in [self.CHANNEL_GENERAL, self.CHANNEL_LOGS, self.CHANNEL_INVEST]:
            try:
                await self.client.conversations_join(channel=ch_id)
            except Exception:
                pass

        # 메시지 수신 채널 (명령어 + 자연어) — 채널 ID 직접 사용
        poll_channels = [self.CHANNEL_GENERAL, self.CHANNEL_QUOTE, self.CHANNEL_INVEST]
        saved_ts = self._load_last_ts()
        for ch_id in poll_channels:
            if ch_id in saved_ts:
                self._last_ts[ch_id] = saved_ts[ch_id]
            else:
                self._last_ts[ch_id] = f"{time.time() - 60:.6f}"  # 1분 전
        self._poll_channels = poll_channels

        # 활성 스레드 복원
        self._active_threads = self._load_active_threads()

        # 주요 채널의 최근 스레드 자동 발견 (시작 시 1회)
        main_ch_id = self.CHANNEL_GENERAL
        if main_ch_id:
            try:
                result = await self.client.conversations_history(channel=main_ch_id, limit=20)
                for msg in result.get("messages", []):
                    if msg.get("reply_count", 0) > 0:
                        if main_ch_id not in self._active_threads:
                            self._active_threads[main_ch_id] = {}
                        if msg["ts"] not in self._active_threads[main_ch_id]:
                            self._active_threads[main_ch_id][msg["ts"]] = msg.get("latest_reply", msg["ts"])
                self._save_active_threads()
            except Exception as e:
                logger.debug(f"Thread scan error: {e}")

        thread_count = sum(len(v) for v in self._active_threads.values())
        logger.info(f"Polling mode ready (interval: {self._poll_interval}s)")
        logger.info(f"Polling channels: {poll_channels}")
        if thread_count:
            logger.info(f"Tracking {thread_count} active threads for reply detection")

    async def poll_once(self):
        """한 번 폴링 (외부에서 주기적으로 호출)"""
        if not self._running:
            logger.debug("[poll_once] not running, skip")
            return
        if not self._poll_channels:
            logger.warning("[poll_once] _poll_channels is empty!")
            return
        for ch_name in self._poll_channels:
            await self._poll_channel(ch_name)

    def stop(self):
        """폴링 중지"""
        self._running = False
