"""
유튜브 분석 에이전트 - YouTube 영상 자막 추출 및 AI 분석 서비스

슬랙에서 YouTube 링크를 감지하면 자동으로 자막을 추출하고
Claude로 요약/분석하여 응답하는 독립 에이전트.

실행: python agent.py
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv()

# ── 로깅 설정 ──────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("youtube-agent")

_log_dir = os.path.join(os.path.dirname(__file__), "data", "logs")
os.makedirs(_log_dir, exist_ok=True)
_log_date = datetime.now(timezone.utc).strftime("%Y%m%d")
_file_handler = logging.FileHandler(
    os.path.join(_log_dir, f"youtube-agent-{_log_date}.log"),
    encoding="utf-8",
)
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logging.getLogger().addHandler(_file_handler)

KST = timezone(timedelta(hours=9))

# ── 단일 인스턴스 보장 ──────────────────────────────────
PID_FILE = os.path.join(os.path.dirname(__file__), "data", ".youtube-agent.pid")
os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)


def _kill_existing():
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

# ── 설정 로드 ──────────────────────────────────────────

import anthropic
from slack_sdk.web.async_client import AsyncWebClient

from transcript import (
    extract_video_id,
    has_youtube_url,
    fetch_transcript,
    fetch_video_info,
    summarize_transcript,
    answer_about_video,
)


def load_config() -> dict:
    """환경변수에서 설정 로드"""
    required = ["SLACK_BOT_TOKEN", "ANTHROPIC_API_KEY"]
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

    config["SLACK_APP_TOKEN"] = os.environ.get("SLACK_APP_TOKEN", "")
    config["SUPABASE_URL"] = os.environ.get("SUPABASE_URL", "")
    config["SUPABASE_SERVICE_ROLE_KEY"] = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return config


# ── 트랜스크립트 캐시 ──────────────────────────────────

class TranscriptCache:
    """최근 처리한 영상 자막 캐시 (메모리 + 디스크)"""

    CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "transcript_cache.json")

    def __init__(self, max_items: int = 50):
        self._cache: dict[str, dict] = {}
        self._max_items = max_items
        self._load()

    def _load(self):
        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._cache = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
        # 최근 N개만 유지
        if len(self._cache) > self._max_items:
            sorted_items = sorted(self._cache.items(), key=lambda x: x[1].get("cached_at", ""))
            self._cache = dict(sorted_items[-self._max_items:])
        with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False)

    def get(self, video_id: str) -> dict | None:
        return self._cache.get(video_id)

    def put(self, video_id: str, data: dict):
        data["cached_at"] = datetime.now(KST).isoformat()
        self._cache[video_id] = data
        self._save()


# ── 메인 에이전트 ──────────────────────────────────────

class YouTubeAnalysisAgent:
    """YouTube 분석 에이전트"""

    # 수신 채널 목록
    CHANNEL_GENERAL = "C0AJJ469SV8"   # ai-agents-general
    CHANNEL_INVEST = "C0AKRJZ395W"    # ai-invest

    def __init__(self, config: dict):
        self.config = config
        self.slack = AsyncWebClient(token=config["SLACK_BOT_TOKEN"])
        self.ai = anthropic.AsyncAnthropic(api_key=config["ANTHROPIC_API_KEY"])
        self.cache = TranscriptCache()
        self._bot_user_id = ""
        self._running = False
        self._poll_interval = 5.0
        self._last_ts: dict[str, str] = {}
        # 활성 분석 세션: {thread_ts: {"video_id": ..., "transcript": ..., "title": ...}}
        self._active_sessions: dict[str, dict] = {}
        self._load_state()

    # ── 상태 영속 ──

    _STATE_FILE = os.path.join(os.path.dirname(__file__), "data", "agent_state.json")

    def _load_state(self):
        try:
            with open(self._STATE_FILE, "r") as f:
                state = json.load(f)
                self._last_ts = state.get("last_ts", {})
                self._active_sessions = state.get("active_sessions", {})
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_state(self):
        os.makedirs(os.path.dirname(self._STATE_FILE), exist_ok=True)
        # 최근 30개 세션만 유지
        if len(self._active_sessions) > 30:
            sorted_sessions = sorted(
                self._active_sessions.items(),
                key=lambda x: x[1].get("created_at", ""),
            )
            self._active_sessions = dict(sorted_sessions[-30:])
        with open(self._STATE_FILE, "w") as f:
            json.dump({
                "last_ts": self._last_ts,
                "active_sessions": {
                    k: {key: val for key, val in v.items() if key != "transcript"}
                    for k, v in self._active_sessions.items()
                },
            }, f, ensure_ascii=False)

    # ── 메시지 전송 ──

    async def send_message(self, channel: str, text: str, thread_ts: str = None):
        """채널 또는 스레드에 메시지 전송"""
        kwargs = {"channel": channel, "text": text, "unfurl_links": False}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        for attempt in range(3):
            try:
                return await self.slack.chat_postMessage(**kwargs)
            except Exception as e:
                if "ratelimited" in str(e) and attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                logger.error(f"Send message error: {e}")
                raise

    async def add_reaction(self, channel: str, timestamp: str, emoji: str):
        try:
            await self.slack.reactions_add(channel=channel, timestamp=timestamp, name=emoji)
        except Exception:
            pass

    # ── 핵심 로직: 영상 분석 ──

    async def analyze_video(self, video_id: str, mode: str, channel: str, thread_ts: str = None) -> str:
        """영상 자막 추출 → 분석 → 결과 반환"""

        # 캐시 확인
        cached = self.cache.get(video_id)
        if cached and cached.get("transcript"):
            transcript_text = cached["transcript"]
            video_title = cached.get("title", "")
            video_author = cached.get("author", "")
            lang = cached.get("language", "")
            auto = cached.get("auto_generated", False)
            logger.info(f"[cache hit] {video_id}: {video_title[:50]}")
        else:
            # 영상 정보 + 자막 추출
            video_info = await fetch_video_info(video_id)
            transcript_result = await fetch_transcript(video_id)

            if not transcript_result["ok"]:
                return f"자막 추출 실패: {transcript_result['error']}"

            transcript_text = transcript_result["text"]
            video_title = video_info.get("title", "")
            video_author = video_info.get("author", "")
            lang = transcript_result.get("language", "")
            auto = transcript_result.get("auto_generated", False)

            # 캐시 저장
            self.cache.put(video_id, {
                "transcript": transcript_text,
                "title": video_title,
                "author": video_author,
                "language": lang,
                "auto_generated": auto,
            })

        # 헤더 구성
        header = f"*{video_title}*" if video_title else f"영상 `{video_id}`"
        if video_author:
            header += f" — {video_author}"
        auto_label = " (자동 생성)" if auto else ""
        header += f"\n자막 언어: {lang}{auto_label} | 길이: {len(transcript_text):,}자"

        await self.send_message(channel, f"{header}\n\nClaude로 분석 중...", thread_ts)

        # Claude 요약
        summary = await summarize_transcript(
            self.ai, transcript_text, video_title=video_title, mode=mode
        )

        mode_label = {"summary": "요약", "full": "전체 정리", "key_points": "핵심 포인트"}
        result = f"{header}\n\n*[{mode_label.get(mode, '요약')}]*\n\n{summary}"

        # 대화 세션 등록 (후속 질문 지원)
        session_key = thread_ts or str(time.time())
        self._active_sessions[session_key] = {
            "video_id": video_id,
            "transcript": transcript_text,
            "title": video_title,
            "created_at": datetime.now(KST).isoformat(),
        }
        self._save_state()

        return result

    async def handle_followup(self, question: str, session: dict, channel: str, thread_ts: str):
        """영상에 대한 후속 질문 처리"""
        transcript = session.get("transcript", "")
        if not transcript:
            # 캐시에서 복구
            cached = self.cache.get(session.get("video_id", ""))
            if cached:
                transcript = cached.get("transcript", "")
            else:
                await self.send_message(channel, "이전 영상 자막을 찾을 수 없습니다. 링크를 다시 보내주세요.", thread_ts)
                return

        title = session.get("title", "")
        await self.send_message(channel, "영상 내용을 바탕으로 답변 중...", thread_ts)

        answer = await answer_about_video(self.ai, transcript, question, video_title=title)
        await self.send_message(channel, answer, thread_ts)

    # ── 메시지 처리 ──

    async def process_message(self, text: str, user: str, channel: str, msg_ts: str, thread_ts: str = None):
        """수신 메시지 처리"""
        # 1. YouTube URL이 있으면 분석
        video_id = extract_video_id(text)
        if video_id:
            # 모드 감지
            mode = "summary"
            text_lower = text.lower()
            if "전체" in text or "스크립트" in text or "full" in text_lower:
                mode = "full"
            elif "포인트" in text or "핵심" in text or "key" in text_lower:
                mode = "key_points"

            await self.add_reaction(channel, msg_ts, "eyes")

            try:
                result = await self.analyze_video(video_id, mode, channel, thread_ts or msg_ts)
                await self.send_message(channel, result, thread_ts or msg_ts)
            except Exception as e:
                logger.error(f"Analyze error: {e}")
                await self.send_message(channel, f"분석 중 오류: {str(e)[:200]}", thread_ts or msg_ts)
            return

        # 2. 스레드 답글이면 후속 질문인지 확인
        if thread_ts and thread_ts in self._active_sessions:
            session = self._active_sessions[thread_ts]
            await self.add_reaction(channel, msg_ts, "eyes")
            try:
                await self.handle_followup(text, session, channel, thread_ts)
            except Exception as e:
                logger.error(f"Followup error: {e}")
                await self.send_message(channel, f"답변 중 오류: {str(e)[:200]}", thread_ts)
            return

        # 3. !영상요약 명령어
        if text.startswith("!영상요약"):
            args = text[len("!영상요약"):].strip()
            if not args:
                await self.send_message(channel,
                    "사용법: `!영상요약 <YouTube URL>` [요약|전체|포인트]\n"
                    "예: `!영상요약 https://youtu.be/xxx`\n"
                    "예: `!영상요약 https://youtu.be/xxx 전체`",
                    thread_ts or msg_ts)
                return

            vid = extract_video_id(args)
            if not vid:
                await self.send_message(channel, "YouTube URL을 인식할 수 없습니다.", thread_ts or msg_ts)
                return

            mode = "summary"
            if "전체" in args:
                mode = "full"
            elif "포인트" in args:
                mode = "key_points"

            await self.add_reaction(channel, msg_ts, "eyes")
            try:
                result = await self.analyze_video(vid, mode, channel, thread_ts or msg_ts)
                await self.send_message(channel, result, thread_ts or msg_ts)
            except Exception as e:
                logger.error(f"Command analyze error: {e}")
                await self.send_message(channel, f"분석 중 오류: {str(e)[:200]}", thread_ts or msg_ts)

    # ── 폴링 ──

    async def _get_bot_user_id(self):
        if not self._bot_user_id:
            result = await self.slack.auth_test()
            self._bot_user_id = result["user_id"]
        return self._bot_user_id

    async def poll_channel(self, channel_id: str):
        """채널 새 메시지 폴링"""
        try:
            kwargs = {"channel": channel_id, "limit": 10}
            if channel_id in self._last_ts:
                kwargs["oldest"] = self._last_ts[channel_id]

            result = await asyncio.wait_for(
                self.slack.conversations_history(**kwargs), timeout=10.0
            )
            messages = result.get("messages", [])
            bot_id = await self._get_bot_user_id()

            if messages:
                self._last_ts[channel_id] = messages[0]["ts"]
                self._save_state()

                for msg in reversed(messages):
                    text = msg.get("text", "")
                    user = msg.get("user", "")
                    msg_ts = msg.get("ts", "")

                    # 봇 자신 무시 (테스트 명령 제외)
                    is_command = text.startswith("!영상요약")
                    if (msg.get("bot_id") or user == bot_id) and not is_command:
                        continue

                    # YouTube URL 포함 메시지 또는 !영상요약 명령만 처리
                    if has_youtube_url(text) or text.startswith("!영상요약"):
                        logger.info(f"[poll] YouTube message: '{text[:80]}' from {user}")
                        asyncio.create_task(
                            self._safe_process(text, user, channel_id, msg_ts)
                        )

            # 활성 세션의 스레드 답글 폴링
            await self._poll_session_threads(channel_id, bot_id)

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            err = str(e)
            if "not_in_channel" in err:
                try:
                    await self.slack.conversations_join(channel=channel_id)
                except Exception:
                    pass
            elif "ratelimited" in err:
                await asyncio.sleep(30)
            else:
                logger.warning(f"Poll error for {channel_id}: {e}")

    async def _poll_session_threads(self, channel_id: str, bot_id: str):
        """활성 분석 세션의 스레드에서 후속 질문 감지"""
        for thread_ts, session in list(self._active_sessions.items()):
            try:
                result = await asyncio.wait_for(
                    self.slack.conversations_replies(
                        channel=channel_id, ts=thread_ts, limit=5,
                    ),
                    timeout=5.0,
                )
                replies = result.get("messages", [])
                last_checked = session.get("_last_reply_ts", thread_ts)

                for reply in replies:
                    if reply["ts"] <= last_checked or reply["ts"] == thread_ts:
                        continue
                    if reply.get("bot_id") or reply.get("user") == bot_id:
                        session["_last_reply_ts"] = reply["ts"]
                        continue

                    reply_text = reply.get("text", "").strip()
                    if reply_text and not has_youtube_url(reply_text):
                        # 후속 질문으로 처리
                        logger.info(f"[thread] Followup: '{reply_text[:80]}'")
                        session["_last_reply_ts"] = reply["ts"]
                        asyncio.create_task(
                            self._safe_followup(reply_text, session, channel_id, thread_ts)
                        )
                    elif has_youtube_url(reply_text):
                        # 새 영상 분석
                        session["_last_reply_ts"] = reply["ts"]
                        asyncio.create_task(
                            self._safe_process(reply_text, reply.get("user", ""), channel_id, reply["ts"], thread_ts)
                        )

                await asyncio.sleep(0.3)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                if "thread_not_found" in str(e):
                    self._active_sessions.pop(thread_ts, None)
                else:
                    logger.debug(f"Thread poll error: {e}")

    async def _safe_process(self, text, user, channel, msg_ts, thread_ts=None):
        try:
            await self.process_message(text, user, channel, msg_ts, thread_ts)
        except Exception as e:
            logger.error(f"Process error: {e}")

    async def _safe_followup(self, text, session, channel, thread_ts):
        try:
            await self.handle_followup(text, session, channel, thread_ts)
        except Exception as e:
            logger.error(f"Followup error: {e}")

    # ── 시작/종료 ──

    async def start(self):
        """에이전트 시작"""
        self._running = True

        # 채널 조인
        channels = [self.CHANNEL_GENERAL, self.CHANNEL_INVEST]
        for ch_id in channels:
            try:
                await self.slack.conversations_join(channel=ch_id)
            except Exception:
                pass

        # 초기 타임스탬프 설정
        for ch_id in channels:
            if ch_id not in self._last_ts:
                self._last_ts[ch_id] = str(time.time() - 60)
        self._save_state()

        bot_id = await self._get_bot_user_id()
        logger.info(f"YouTube Analysis Agent started (bot_id={bot_id})")
        logger.info(f"Polling channels: {channels}")
        logger.info(f"Active sessions: {len(self._active_sessions)}")

        await self.send_message(self.CHANNEL_GENERAL,
            "🎬 *유튜브 분석 에이전트* 가동됨\n"
            "YouTube 링크를 보내면 자동으로 자막 추출 + AI 요약합니다.\n"
            "명령어: `!영상요약 <URL>` [요약|전체|포인트]\n"
            "요약 후 스레드에서 영상 내용에 대해 질문할 수 있습니다.")

        poll_count = 0
        while self._running:
            poll_count += 1
            if poll_count % 60 == 1:
                logger.info(f"[main] Poll #{poll_count} (alive, {len(self._active_sessions)} sessions)")

            for ch_id in channels:
                await self.poll_channel(ch_id)

            await asyncio.sleep(self._poll_interval)

    def stop(self):
        self._running = False


# ── 엔트리포인트 ──────────────────────────────────────

async def main():
    config = load_config()
    agent = YouTubeAnalysisAgent(config)

    shutdown_event = asyncio.Event()

    def _signal_handler(sig, frame):
        logger.info(f"Signal {sig} received, shutting down...")
        agent.stop()
        shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    await agent.start()
    logger.info("YouTube Analysis Agent shut down cleanly")


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
            logger.error(f"Agent crashed ({restart_count}/{max_restarts}): {e}")
            if restart_count < max_restarts:
                logger.info("Restarting in 10 seconds...")
                time.sleep(10)
            else:
                logger.critical("Max restarts reached. Exiting.")
