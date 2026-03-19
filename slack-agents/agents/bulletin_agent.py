"""
게시판 스크래퍼 에이전트 (Bulletin Board Scraper Agent)

역할:
- 학교, 문화센터, 공공기관 등 다양한 웹 게시판을 주기적으로 스크래핑
- 새 게시글 감지 시 슬랙으로 알림
- Supabase에 모니터링할 게시판 목록과 수집된 게시글 저장
- Playwright(headless 브라우저)를 사용하여 해외 IP 차단/JS 렌더링 사이트도 크롤링 가능

자율 행동:
- Observe: bulletin_boards 테이블에서 모니터링 대상 확인, 스크래핑 시간 판단
- Think: 새 게시글이 있는지 판단
- Act: 새 게시글을 저장하고 슬랙 알림 전송
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import http.cookiejar
import ssl
import urllib.request

from core.base_agent import BaseAgent
from core.message_bus import TaskMessage
from integrations.slack_client import SlackClient

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 한국 사이트 공통 User-Agent
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}

# Playwright 리소스 차단 패턴 (불필요한 리소스 로딩 방지)
_PW_BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}
_PW_BLOCKED_URL_PATTERNS = [
    "google-analytics", "googletagmanager", "doubleclick",
    "adservice", "googlesyndication", "facebook.net",
    "analytics",
]


class BulletinAgent(BaseAgent):
    """게시판 스크래퍼 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="bulletin",
            description="학교/문화센터/공공기관 게시판을 모니터링하여 새 게시글을 알려주는 에이전트",
            slack_channel=SlackClient.CHANNEL_GENERAL,
            loop_interval=3600,  # 1시간마다 루프 (게시판별 check_interval로 실제 주기 제어)
            **kwargs,
        )
        # SSL 검증 비활성화 + 구형 사이트 호환 (보안 레벨 낮춤)
        self._ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE
        try:
            self._ssl_ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        except ssl.SSLError:
            pass
        self._ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1
        self._ssl_ctx.maximum_version = ssl.TLSVersion.TLSv1_3

        # 한국 프록시 설정 (해외 IP 차단 사이트 우회)
        # 형식: http://user:pass@host:port 또는 socks5://host:port
        self._proxy_url = os.environ.get("KOREAN_PROXY_URL", "")

        # Vercel 프록시 (서울 리전) — 한국 전용 사이트 우회용
        self._vercel_proxy_url = os.environ.get(
            "VERCEL_PROXY_URL",
            "https://web-service-ruby.vercel.app/api/proxy",
        )
        # Supabase Edge Function 프록시 (글로벌 CDN) — 대안
        self._supabase_proxy_url = os.environ.get(
            "SUPABASE_PROXY_URL",
            "https://unuvbdqjgiypxfvlplpd.supabase.co/functions/v1/kr-proxy",
        )
        # Cloudflare Worker 프록시 (서울 POP) — 한국 IP 우회용 최우선
        self._cf_proxy_url = os.environ.get(
            "CF_PROXY_URL",
            "https://kr-proxy.yhmemo-kr.workers.dev",
        )
        self._vercel_proxy_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

        # Notion API 설정
        self._notion_api_key = os.environ.get("NOTION_API_KEY", "")
        self._notion_db_id = os.environ.get(
            "BULLETIN_NOTION_DB_ID",
            "1e21114e-6491-8101-8b67-ca52d78a8fb0",  # AI 에이전트 결과물 DB
        )
        # Supabase Storage 설정
        self._supabase_url = os.environ.get(
            "SUPABASE_URL",
            "https://unuvbdqjgiypxfvlplpd.supabase.co",
        )
        self._storage_bucket = "bulletin-images"

        # Playwright 브라우저 인스턴스 (싱글턴, 필요 시 생성)
        self._pw = None
        self._pw_browser = None

        # 일일 보고 추적 (KST 22시 보고, 하루 1회)
        self._last_daily_report_date: str | None = None

    async def start(self):
        """에이전트 시작 — 테이블 확인 후 자동 루프 실행 (1시간 간격)"""
        await self._ensure_tables()
        # BaseAgent의 자동 루프 실행 (observe → think → act, loop_interval=3600초)
        await super().start()

    async def _ensure_tables(self):
        """bulletin_boards, bulletin_posts 테이블이 없으면 생성"""
        def _sync_ensure():
            try:
                # 테이블 존재 확인 (조회 시도)
                self.supabase.table("bulletin_boards").select("id").limit(1).execute()
            except Exception:
                logger.info("[bulletin] 테이블 없음 — 자동 생성 시도")
                try:
                    # psycopg2로 직접 DDL 실행
                    import os
                    db_url = os.environ.get("DATABASE_URL", "")
                    if db_url:
                        import psycopg2
                        conn = psycopg2.connect(db_url)
                        conn.autocommit = True
                        with conn.cursor() as cur:
                            cur.execute("""
                                CREATE TABLE IF NOT EXISTS bulletin_boards (
                                    id BIGSERIAL PRIMARY KEY,
                                    name TEXT NOT NULL,
                                    url TEXT NOT NULL,
                                    parser_type TEXT DEFAULT 'auto',
                                    css_selector TEXT DEFAULT '',
                                    use_playwright BOOLEAN DEFAULT FALSE,
                                    active BOOLEAN DEFAULT TRUE,
                                    created_at TIMESTAMPTZ DEFAULT NOW(),
                                    updated_at TIMESTAMPTZ DEFAULT NOW()
                                );
                                CREATE TABLE IF NOT EXISTS bulletin_posts (
                                    id BIGSERIAL PRIMARY KEY,
                                    board_id BIGINT REFERENCES bulletin_boards(id) ON DELETE CASCADE,
                                    title TEXT NOT NULL,
                                    url TEXT DEFAULT '',
                                    content TEXT DEFAULT '',
                                    post_date TEXT DEFAULT '',
                                    hash TEXT NOT NULL UNIQUE,
                                    created_at TIMESTAMPTZ DEFAULT NOW()
                                );
                                CREATE INDEX IF NOT EXISTS idx_bulletin_posts_hash ON bulletin_posts(hash);
                                CREATE INDEX IF NOT EXISTS idx_bulletin_posts_board_id ON bulletin_posts(board_id);
                            """)
                        # 기존 테이블에 새 컬럼 추가 (이미 있으면 무시)
                        for col_sql in [
                            "ALTER TABLE bulletin_boards ADD COLUMN IF NOT EXISTS use_playwright BOOLEAN DEFAULT FALSE",
                            "ALTER TABLE bulletin_posts ADD COLUMN IF NOT EXISTS content TEXT DEFAULT ''",
                            "ALTER TABLE bulletin_boards ADD COLUMN IF NOT EXISTS check_interval INTEGER DEFAULT 86400",
                            "ALTER TABLE bulletin_boards ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ",
                        ]:
                            try:
                                cur.execute(col_sql)
                            except Exception:
                                pass
                        conn.close()
                        logger.info("[bulletin] 테이블 생성 완료")
                    else:
                        logger.warning("[bulletin] DATABASE_URL 없음 — Supabase Dashboard에서 수동 생성 필요")
                except Exception as e2:
                    logger.error(f"[bulletin] 테이블 자동 생성 실패: {e2}")

        await asyncio.to_thread(_sync_ensure)

    # ── Observe ─────────────────────────────────────────

    async def observe(self) -> dict | None:
        """모니터링 대상 게시판 목록 로드 + KST 22시 일일 보고 체크"""
        now_kst = datetime.now(KST)
        today_str = now_kst.strftime("%Y-%m-%d")
        is_daily_report_time = (
            now_kst.hour == 22
            and self._last_daily_report_date != today_str
        )

        if is_daily_report_time:
            # 일일 보고 모드: check_interval 무시, 모든 활성 게시판 강제 로드
            boards = await self._load_all_boards()
            if not boards:
                return None
            return {
                "current_time": self.now_str(),
                "boards": boards,
                "daily_report": True,
            }

        # 일반 모드: check_interval 기반 필터링
        boards = await self._load_boards()
        if not boards:
            return None

        return {
            "current_time": self.now_str(),
            "boards": boards,
        }

    # ── Think ──────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        """각 게시판을 스크래핑하고 새 글이 있는지 확인"""
        boards = context["boards"]
        all_new_posts = []

        for board in boards:
            try:
                posts, _debug_info = await self._scrape_board(board)
                # 스크래핑 시도했으면 last_checked_at 갱신 (성공 여부 무관)
                await self._update_last_checked(board)

                if not posts:
                    logger.info(f"[bulletin] {board['name']}: 게시글을 가져오지 못함")
                    continue

                new_posts = await self._filter_new_posts(board, posts)
                if new_posts:
                    logger.info(f"[bulletin] {board['name']}: 새 글 {len(new_posts)}개 발견")
                    all_new_posts.append({
                        "board": board,
                        "posts": new_posts,
                    })
                else:
                    logger.info(f"[bulletin] {board['name']}: 새 글 없음")
            except Exception as e:
                logger.error(f"[bulletin] {board['name']} 스크래핑 오류: {e}")

        if not all_new_posts:
            # 일일 보고 모드면 새 글 없어도 보고
            if context.get("daily_report"):
                return {"action": "daily_report", "results": [], "board_count": len(boards)}
            return None

        action = "daily_report" if context.get("daily_report") else "notify_new_posts"
        return {"action": action, "results": all_new_posts}

    # ── Act ────────────────────────────────────────────

    async def act(self, decision: dict):
        """새 게시글을 저장하고 슬랙에 알림"""
        action = decision.get("action", "notify_new_posts")
        results = decision.get("results", [])

        for result in results:
            board = result["board"]
            posts = result["posts"]

            # Supabase에 저장
            saved_count = await self._save_posts(board, posts)

            # 노션에 저장 (각 게시글에 notion_url 필드 추가)
            for post in posts:
                try:
                    notion_url = await self._save_to_notion(post, board)
                    post["notion_url"] = notion_url
                except Exception as e:
                    logger.error(f"[bulletin] 노션 저장 실패 ({post['title'][:30]}): {e}")
                    post["notion_url"] = ""

            # 일반 모드: 개별 알림
            if action != "daily_report":
                await self._send_slack_notification(board, posts)

            logger.info(f"[bulletin] {board['name']}: {saved_count}건 저장, 알림 발송")

        # 일일 보고 모드: 요약 보고 발송
        if action == "daily_report":
            await self._send_daily_report(results, decision.get("board_count", 0))
            self._last_daily_report_date = datetime.now(KST).strftime("%Y-%m-%d")

    # ── 게시판 목록 로드 ─────────────────────────────────

    async def _load_boards(self) -> list[dict]:
        """Supabase bulletin_boards 테이블에서 활성 게시판 목록 로드 (check_interval 기반 필터)"""
        def _sync_load():
            try:
                result = self.supabase.table("bulletin_boards").select("*").eq(
                    "active", True
                ).execute()
                all_boards = result.data or []

                # check_interval 기준으로 체크할 게시판만 필터
                now = datetime.now(timezone.utc)
                due_boards = []
                for board in all_boards:
                    interval = board.get("check_interval") or 86400  # 기본 24시간
                    last_checked = board.get("last_checked_at")
                    if last_checked:
                        # ISO-8601 파싱 (표준 라이브러리)
                        last_dt = datetime.fromisoformat(last_checked.replace("Z", "+00:00"))
                        if (now - last_dt).total_seconds() < interval:
                            logger.info(f"[bulletin] {board['name']}: 아직 체크 주기 안 됨, 건너뜀")
                            continue
                    due_boards.append(board)

                return due_boards
            except Exception as e:
                logger.error(f"[bulletin] 게시판 목록 로드 실패: {e}")
                return []

        return await asyncio.to_thread(_sync_load)

    async def _load_all_boards(self) -> list[dict]:
        """모든 활성 게시판 로드 (check_interval 무시, 일일 보고용)"""
        def _sync_load():
            try:
                result = self.supabase.table("bulletin_boards").select("*").eq(
                    "active", True
                ).execute()
                return result.data or []
            except Exception as e:
                logger.error(f"[bulletin] 게시판 목록 로드 실패: {e}")
                return []

        return await asyncio.to_thread(_sync_load)

    async def _update_last_checked(self, board: dict):
        """게시판의 last_checked_at을 현재 시각으로 갱신"""
        def _sync_update():
            try:
                self.supabase.table("bulletin_boards").update({
                    "last_checked_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", board["id"]).execute()
            except Exception as e:
                logger.error(f"[bulletin] last_checked_at 갱신 실패: {e}")

        await asyncio.to_thread(_sync_update)

    # ── HTTP 요청 (urllib + 쿠키 대응) ─────────────────

    def _build_opener(self) -> tuple[urllib.request.OpenerDirector, http.cookiejar.CookieJar]:
        """프록시 설정을 포함한 opener 생성"""
        cj = http.cookiejar.CookieJar()
        handlers = [
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(context=self._ssl_ctx),
        ]

        if self._proxy_url:
            proxy_handler = urllib.request.ProxyHandler({
                "http": self._proxy_url,
                "https": self._proxy_url,
            })
            handlers.append(proxy_handler)
            logger.info(f"[bulletin] 한국 프록시 사용: {self._proxy_url[:30]}...")

        opener = urllib.request.build_opener(*handlers)
        return opener, cj

    def _fetch_url(self, url: str) -> tuple[bytes, dict]:
        """urllib로 URL 가져오기. 세션 쿠키 자동 처리. (content, headers) 반환"""
        parsed = urlparse(url)
        root_url = f"{parsed.scheme}://{parsed.netloc}/"
        errors = []

        # 쿠키 자동 관리 + 프록시 opener
        opener, cj = self._build_opener()

        def _make_request(target_url: str, referer: str = "") -> urllib.request.Request:
            req = urllib.request.Request(target_url)
            for k, v in HEADERS.items():
                req.add_header(k, v)
            # 추가 헤더 (구린 사이트 호환)
            req.add_header("Connection", "keep-alive")
            req.add_header("Upgrade-Insecure-Requests", "1")
            if referer:
                req.add_header("Referer", referer)
            return req

        # 1차: 직접 요청
        try:
            req = _make_request(url)
            with opener.open(req, timeout=20) as resp:
                content = resp.read()
                headers = dict(resp.headers)
                logger.info(f"[bulletin] 직접 접근 성공: {resp.status} ({len(content)}B)")
                return content, headers
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            errors.append(f"1차(직접): HTTP {e.code} {e.reason} body={body}")
            logger.info(f"[bulletin] 직접 접근 HTTP {e.code}: {body[:100]}")
        except Exception as e:
            errors.append(f"1차(직접): {type(e).__name__}: {e}")
            logger.info(f"[bulletin] 직접 접근 실패: {e}")

        # 2차: 메인 페이지로 세션 쿠키 획득 후 재시도
        try:
            req = _make_request(root_url)
            with opener.open(req, timeout=10) as resp:
                resp.read()
                logger.info(f"[bulletin] 메인 페이지 접근 성공: {resp.status}, cookies={len(cj)}")
        except Exception as e:
            errors.append(f"2차(메인): {type(e).__name__}: {e}")

        try:
            req = _make_request(url, referer=root_url)
            with opener.open(req, timeout=20) as resp:
                content = resp.read()
                headers = dict(resp.headers)
                logger.info(f"[bulletin] 쿠키+Referer 재시도 성공: {resp.status} ({len(content)}B)")
                return content, headers
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            errors.append(f"2차(쿠키+Referer): HTTP {e.code} body={body}")
        except Exception as e:
            errors.append(f"2차(쿠키+Referer): {type(e).__name__}: {e}")

        # 3차: HTTP 폴백
        if parsed.scheme == "https":
            http_url = url.replace("https://", "http://", 1)
            http_root = root_url.replace("https://", "http://", 1)
            try:
                opener.open(_make_request(http_root), timeout=10).read()
            except Exception:
                pass
            try:
                req = _make_request(http_url, referer=http_root)
                with opener.open(req, timeout=20) as resp:
                    content = resp.read()
                    headers = dict(resp.headers)
                    logger.info(f"[bulletin] HTTP 폴백 성공: {resp.status} ({len(content)}B)")
                    return content, headers
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="replace")[:200]
                except Exception:
                    pass
                errors.append(f"3차(HTTP): HTTP {e.code} body={body}")
            except Exception as e:
                errors.append(f"3차(HTTP): {type(e).__name__}: {e}")

        detail = "\n".join(errors)
        raise RuntimeError(f"모든 접근 방법 실패:\n{detail}")

    # ── 게시판 스크래핑 ──────────────────────────────────

    async def scrape_and_show(self, channel: str, thread_ts: str = None, max_posts: int = 5):
        """게시판 스크래핑 후 결과를 바로 슬랙에 표시 (새 글 필터 없이)"""
        # 수동 명령어이므로 check_interval 무시하고 모든 활성 게시판 로드
        boards = await self._load_all_boards()
        if not boards:
            await self._reply(channel, "등록된 게시판이 없습니다. `!게시판 등록 이름 URL`로 추가하세요.", thread_ts)
            return

        for board in boards:
            try:
                posts, debug_info = await self._scrape_board(board)
                if posts:
                    # 최근 N개만 표시
                    display = posts[:max_posts]
                    pw_label = " :globe_with_meridians:" if board.get("use_playwright") else ""
                    lines = [f"*:pushpin: [{board['name']}]{pw_label} 최근 게시글 (총 {len(posts)}건 중 {len(display)}건)*\n"]
                    for p in display:
                        title = p["title"]
                        url = p.get("url", "")
                        date = p.get("date", "")
                        content = p.get("content", "")
                        if url:
                            lines.append(f"• <{url}|{title}>")
                        else:
                            lines.append(f"• {title}")
                        if date:
                            lines[-1] += f"  ({date})"
                        if content:
                            preview = content.replace("\n", " ").strip()[:100]
                            if preview:
                                lines.append(f"  _{preview}{'...' if len(content) > 100 else ''}_")
                    lines.append(f"\n<{board['url']}|게시판 바로가기>")
                    await self._reply(channel, "\n".join(lines), thread_ts)

                    # 새 글만 저장
                    new_posts = await self._filter_new_posts(board, posts)
                    if new_posts:
                        await self._save_posts(board, new_posts)
                else:
                    # 파싱 실패 — 디버그 정보 표시
                    msg = f"*:warning: [{board['name']}] 게시글을 파싱하지 못했습니다.*\n"
                    msg += f"URL: {board['url']}\n"
                    if debug_info:
                        msg += f"```{debug_info[:500]}```"
                    await self._reply(channel, msg, thread_ts)
            except Exception as e:
                logger.error(f"[bulletin] {board['name']} 스크래핑 오류: {e}", exc_info=True)
                error_msg = str(e)
                if "400" in error_msg or "403" in error_msg or "503" in error_msg:
                    await self._reply(
                        channel,
                        f":x: [{board['name']}] 사이트 접근 차단됨 (HTTP {error_msg[:80]})\n"
                        f"해외 IP 차단이 원인일 수 있습니다. 한국 서버에서 실행하거나 프록시 설정이 필요합니다.",
                        thread_ts,
                    )
                else:
                    await self._reply(channel, f":x: [{board['name']}] 오류: {e}", thread_ts)

    # ── Vercel 프록시 (서울 리전) ────────────────────────

    async def _fetch_via_proxy(self, url: str) -> str:
        """프록시를 통해 한국 전용 사이트 HTML 가져오기.
        Cloudflare Worker (X-Forwarded-For 스푸핑) → Vercel → Supabase 순으로 시도.
        """
        import json
        key = self._vercel_proxy_key

        if not key:
            raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY 없음 — 프록시 인증 불가")

        # 시도할 프록시 URL 목록 (Cloudflare Worker 최우선 — X-Forwarded-For 한국 IP 스푸핑)
        proxy_urls = [
            ("Cloudflare", self._cf_proxy_url),
            ("Vercel", self._vercel_proxy_url),
            ("Supabase", self._supabase_proxy_url),
        ]

        # 한국 통신사 IP (KT 대역) — WAF X-Forwarded-For 우회용
        KOREAN_SPOOF_IP = "211.234.120.50"

        import ssl as _ssl
        ctx = _ssl.create_default_context()

        last_error = None
        for proxy_name, proxy_url in proxy_urls:
            if not proxy_url:
                continue
            try:
                logger.info(f"[bulletin/{proxy_name}] 프록시 요청: {url}")

                payload = {"url": url}
                # Cloudflare Worker에는 X-Forwarded-For 스푸핑 파라미터 추가
                if proxy_name == "Cloudflare":
                    payload["spoof_ip"] = KOREAN_SPOOF_IP

                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    proxy_url,
                    data=data,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "User-Agent": "YhmemoBot/1.0",
                    },
                    method="POST",
                )

                resp_body = await asyncio.to_thread(
                    lambda: urllib.request.urlopen(req, context=ctx, timeout=25).read()
                )
                result = json.loads(resp_body)

                if "error" in result:
                    raise RuntimeError(f"{proxy_name} 프록시 오류: {result['error']}")

                html = result.get("html", "")
                status = result.get("status", 0)
                logger.info(f"[bulletin/{proxy_name}] 응답: HTTP {status}, {len(html)}자")

                if status >= 400:
                    raise RuntimeError(f"{proxy_name} 프록시: 원본 HTTP {status}")

                return html
            except Exception as e:
                logger.warning(f"[bulletin/{proxy_name}] 프록시 실패: {e}")
                last_error = e

        raise RuntimeError(f"모든 프록시 실패: {last_error}")

    # ── Playwright 브라우저 관리 ────────────────────────

    async def _ensure_playwright(self):
        """Playwright 브라우저 싱글턴 보장"""
        if self._pw_browser and self._pw_browser.is_connected():
            return
        from playwright.async_api import async_playwright
        self._pw = await async_playwright().start()

        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
        ]

        # 한국 프록시 설정 (해외 IP 차단 사이트 우회)
        proxy_config = None
        if self._proxy_url:
            proxy_config = {"server": self._proxy_url}
            logger.info(f"[bulletin/pw] 한국 프록시 사용: {self._proxy_url[:30]}...")

        self._pw_browser = await self._pw.chromium.launch(
            headless=True,
            args=launch_args,
            proxy=proxy_config,
        )
        logger.info("[bulletin] Playwright 브라우저 시작됨")

    async def _close_playwright(self):
        """Playwright 브라우저 정리"""
        if self._pw_browser:
            await self._pw_browser.close()
            self._pw_browser = None
        if self._pw:
            await self._pw.stop()
            self._pw = None

    async def _pw_fetch_html(self, url: str, wait_selector: str = None) -> str:
        """Playwright로 URL에 접근하여 렌더링된 HTML 반환.
        iframe이 감지되면 iframe 내부 HTML을 반환."""
        await self._ensure_playwright()

        context = await self._pw_browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ko-KR",
        )
        page = await context.new_page()

        # 불필요한 리소스 차단 (빠른 로딩)
        async def _route_handler(route):
            req = route.request
            if req.resource_type in _PW_BLOCKED_RESOURCE_TYPES:
                await route.abort()
                return
            url_lower = req.url.lower()
            if any(p in url_lower for p in _PW_BLOCKED_URL_PATTERNS):
                await route.abort()
                return
            await route.continue_()
        await page.route("**/*", _route_handler)

        try:
            logger.info(f"[bulletin/pw] 접속 중: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # form auto-submit 페이지: 네비게이션(form.submit) 완료 대기
            # (eminwon.yongin.go.kr 고시공고: init() → search() → form.submit())
            if "eminwon" in url or "OfrNotAncmt" in url:
                try:
                    logger.info("[bulletin/pw] form auto-submit 네비게이션 대기 중...")
                    await page.wait_for_navigation(wait_until="domcontentloaded", timeout=15000)
                    logger.info("[bulletin/pw] form submit 네비게이션 완료")
                except Exception:
                    logger.info("[bulletin/pw] 네비게이션 타임아웃, 계속 진행")

            # 추가 대기: 특정 셀렉터가 나타날 때까지 또는 고정 대기
            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=10000)
                except Exception:
                    logger.info(f"[bulletin/pw] 셀렉터 '{wait_selector}' 대기 타임아웃, 계속 진행")
            else:
                await asyncio.sleep(3)  # JS 렌더링 대기

            # iframe 감지 — 게시판 콘텐츠가 iframe에 있는 경우 (용인시 고시공고 등)
            html = await page.content()
            frames = page.frames
            if len(frames) > 1:
                for frame in frames[1:]:  # 메인 프레임 제외
                    frame_url = frame.url or ""
                    # 게시판 iframe 패턴 감지
                    if any(kw in frame_url for kw in ["eminwon", "boardList", "OfrNotAncmt", "emwp"]):
                        try:
                            await frame.wait_for_load_state("domcontentloaded", timeout=10000)
                            await asyncio.sleep(2)  # AJAX 렌더링 대기
                            frame_html = await frame.content()
                            if len(frame_html) > len(html) * 0.1 and "boardDefalut" in frame_html:
                                logger.info(f"[bulletin/pw] iframe 감지: {frame_url[:80]} ({len(frame_html)}자)")
                                html = frame_html
                                break
                        except Exception as e:
                            logger.warning(f"[bulletin/pw] iframe 접근 실패: {e}")

            logger.info(f"[bulletin/pw] HTML 수신: {len(html)}자")
            return html
        finally:
            await page.close()
            await context.close()

    async def _pw_scrape_post_content(self, url: str) -> str:
        """Playwright로 개별 게시글 본문을 추출"""
        await self._ensure_playwright()

        context = await self._pw_browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="ko-KR",
        )
        page = await context.new_page()

        # 본문 크롤링 시 이미지는 허용하되 광고만 차단
        async def _route_handler(route):
            req = route.request
            if req.resource_type in {"media", "font"}:
                await route.abort()
                return
            url_lower = req.url.lower()
            if any(p in url_lower for p in _PW_BLOCKED_URL_PATTERNS):
                await route.abort()
                return
            await route.continue_()
        await page.route("**/*", _route_handler)

        try:
            logger.info(f"[bulletin/pw] 게시글 접속: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # 본문 컨텐츠 추출 시도 (다양한 패턴)
            content_selectors = [
                "div.board_view_content",  # 공공기관 게시판 일반
                "div.view_content",
                "div.bbs_content",
                "div.board-content",
                "div.content_view",
                "td.board_content",
                "div#content",
                "div.detail_content",
                "div.sub_content",
                "article",
                "div.view_cont",
                "div.bbsV_cont",
            ]

            content_text = ""
            for sel in content_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        text = await el.inner_text()
                        if text and len(text.strip()) > 10:
                            content_text = text.strip()
                            logger.info(f"[bulletin/pw] 본문 추출 성공: {sel} ({len(content_text)}자)")
                            break
                except Exception:
                    continue

            if not content_text:
                # 폴백: body 전체에서 추출
                try:
                    body = await page.query_selector("body")
                    if body:
                        content_text = (await body.inner_text()).strip()
                        # 불필요한 네비게이션/메뉴 텍스트 제거 (앞뒤 500자 이상이면 중간만)
                        if len(content_text) > 1000:
                            content_text = content_text[:3000]
                except Exception:
                    pass

            return content_text[:5000]  # 최대 5000자
        finally:
            await page.close()
            await context.close()

    # ── 게시판 스크래핑 ──────────────────────────────────

    async def _scrape_board(self, board: dict) -> tuple[list[dict], str]:
        """게시판 HTML을 파싱하여 게시글 목록 추출. (posts, debug_info) 반환
        use_playwright=True인 게시판은 Playwright를 사용하여 렌더링된 HTML을 가져옴.
        """
        url = board["url"]
        parser_type = board.get("parser_type", "auto")
        use_playwright = board.get("use_playwright", False)
        debug_info = ""

        # 용인시 고시공고: form POST action URL로 직접 목록 조회
        YONGIN_GOSI_ACTION_URL = (
            "https://eminwon.yongin.go.kr/emwp/gov/mogaha/ntis/web/ofr/action/OfrAction.do"
        )
        YONGIN_GOSI_IFRAME_URL = (
            "https://eminwon.yongin.go.kr/emwp/jsp/ofr/OfrNotAncmtLSub.jsp"
            "?not_ancmt_se_code=01,04&homepage_pbs_yn=Y&subCheck=Y"
            "&ofr_pageSize=10&jndinm=OfrNotAncmtEJB&context=NTIS&list_gubun=&epcCheck=Y"
        )
        if parser_type == "yongin_gosi" or (
            "yiNwStable02_01" in url and "yongin.go.kr" in url
        ):
            parser_type = "yongin_gosi"
            # 1순위: form POST로 직접 목록 조회 (Playwright 불필요)
            try:
                html = await self._fetch_yongin_gosi_list()
                if html and "boardDefalut" in html:
                    logger.info(f"[bulletin] 용인시 고시공고: form POST 성공 ({len(html)}자)")
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, "html.parser")
                    posts = self._parse_yongin_gosi(soup, "https://eminwon.yongin.go.kr", board)
                    if posts:
                        await self._enrich_posts_with_content(posts, use_vercel=True)
                    return posts, ""
            except Exception as e:
                logger.warning(f"[bulletin] 고시공고 form POST 실패: {e}")
            # 2순위: Playwright로 iframe URL 접근
            url = YONGIN_GOSI_IFRAME_URL
            use_playwright = True
            logger.info(f"[bulletin] 용인시 고시공고: Playwright 폴백")

        _error_patterns = ["bad request", "403 forbidden", "access denied",
                           "502 bad gateway", "서버 오류", "접근이 거부"]

        def _is_error_page(h: str) -> bool:
            if not h or len(h.strip()) < 100:
                return True
            h_lower = h.lower()
            return any(ep in h_lower for ep in _error_patterns)

        html = ""
        used_vercel_proxy = False

        # 1단계: urllib 직접 접근 (use_playwright가 아닌 경우만)
        if not use_playwright:
            try:
                content, headers = await asyncio.to_thread(self._fetch_url, url)
                html = self._decode_html(content, headers)
                if _is_error_page(html):
                    raise RuntimeError(f"에러 페이지 감지 ({len(html)}자)")
            except Exception as e:
                logger.warning(f"[bulletin] 1단계(urllib) 실패: {e}")
                html = ""

        # 2단계: 프록시 체인 (Cloudflare → Vercel → Supabase)
        # use_playwright가 명시적으로 설정된 경우(yongin_gosi 등) 프록시 건너뜀
        # — 프록시는 raw HTML만 반환하므로 JS 렌더링이 필요한 게시판에는 무의미
        if (not html or _is_error_page(html)) and not use_playwright:
            try:
                html = await self._fetch_via_proxy(url)
                if _is_error_page(html):
                    raise RuntimeError(f"에러 페이지 감지 ({len(html)}자)")
                used_vercel_proxy = True
                logger.info(f"[bulletin] 2단계(프록시) 성공: {len(html)}자")
            except Exception as e:
                logger.warning(f"[bulletin] 2단계(프록시) 실패: {e}")

        # 3단계: Playwright 폴백
        if not html or _is_error_page(html):
            try:
                css_sel = board.get("css_selector", "")
                wait_sel = css_sel if css_sel else None
                # 고시공고: form auto-submit 결과의 테이블 row를 기다림
                if parser_type == "yongin_gosi":
                    wait_sel = "table.boardDefalut tbody tr td a"
                html = await self._pw_fetch_html(url, wait_selector=wait_sel)
                if _is_error_page(html):
                    raise RuntimeError(f"에러 페이지 감지 ({len(html)}자)")
                use_playwright = True
                logger.info(f"[bulletin] 3단계(Playwright) 성공: {len(html)}자")
            except Exception as e2:
                logger.error(f"[bulletin] 모든 접근 방법 실패 ({url})")
                return [], f"모든 접근 실패:\n1. urllib\n2. 프록시 체인\n3. Playwright"

        logger.info(f"[bulletin] {board['name']}: HTML {len(html)}자 수신 (playwright={use_playwright})")

        # BeautifulSoup 파싱
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        # 특수 게시판 파서 분기
        if parser_type == "yongin_gosi":
            posts = self._parse_yongin_gosi(soup, base_url, board)
        elif parser_type == "yongin_event":
            posts = self._parse_yongin_event(soup, base_url, board)
        elif parser_type == "imweb":
            posts = self._parse_imweb_board(soup, base_url, board)
        elif parser_type == "ggcf":
            posts = self._parse_ggcf_board(soup, base_url, board)
        elif parser_type == "table":
            posts = self._parse_table_board(soup, base_url, board)
        elif parser_type == "list":
            posts = self._parse_list_board(soup, base_url, board)
        else:
            # auto: 특수 패턴 감지 → 테이블 → 리스트 → 링크 폴백
            if soup.select_one("table.boardDefalut"):
                posts = self._parse_yongin_gosi(soup, base_url, board)
            elif soup.select_one("div.gallery_bbs_list4") or soup.select_one("div.gallery_bbs_list"):
                posts = self._parse_yongin_event(soup, base_url, board)
            elif soup.select_one("div.li_board ul.li_body"):
                posts = self._parse_imweb_board(soup, base_url, board)
            elif soup.select_one("div.list-type1"):
                posts = self._parse_ggcf_board(soup, base_url, board)
            else:
                posts = self._parse_table_board(soup, base_url, board)
            if not posts:
                posts = self._parse_list_board(soup, base_url, board)
            if not posts:
                posts = self._parse_any_links(soup, base_url, board)

        # urllib로 파싱했는데 게시글이 없고, Playwright 아직 안 써봤으면 폴백 시도
        if not posts and not use_playwright:
            logger.info(f"[bulletin] {board['name']}: urllib 파싱 결과 없음, Playwright 폴백 시도")
            try:
                css_sel = board.get("css_selector", "")
                wait_sel = css_sel if css_sel else None
                pw_html = await self._pw_fetch_html(url, wait_selector=wait_sel)
                pw_soup = BeautifulSoup(pw_html, "html.parser")

                if parser_type == "yongin_gosi":
                    posts = self._parse_yongin_gosi(pw_soup, base_url, board)
                elif parser_type == "yongin_event":
                    posts = self._parse_yongin_event(pw_soup, base_url, board)
                elif parser_type == "imweb":
                    posts = self._parse_imweb_board(pw_soup, base_url, board)
                elif parser_type == "ggcf":
                    posts = self._parse_ggcf_board(pw_soup, base_url, board)
                elif parser_type == "table":
                    posts = self._parse_table_board(pw_soup, base_url, board)
                elif parser_type == "list":
                    posts = self._parse_list_board(pw_soup, base_url, board)
                else:
                    # auto: 초기 파싱과 동일한 자동 감지 로직 적용
                    if pw_soup.select_one("table.boardDefalut"):
                        posts = self._parse_yongin_gosi(pw_soup, base_url, board)
                    elif pw_soup.select_one("div.gallery_bbs_list4") or pw_soup.select_one("div.gallery_bbs_list"):
                        posts = self._parse_yongin_event(pw_soup, base_url, board)
                    elif pw_soup.select_one("div.li_board ul.li_body"):
                        posts = self._parse_imweb_board(pw_soup, base_url, board)
                    elif pw_soup.select_one("div.list-type1"):
                        posts = self._parse_ggcf_board(pw_soup, base_url, board)
                    else:
                        posts = self._parse_table_board(pw_soup, base_url, board)
                    if not posts:
                        posts = self._parse_list_board(pw_soup, base_url, board)
                    if not posts:
                        posts = self._parse_any_links(pw_soup, base_url, board)

                if posts:
                    use_playwright = True
                    soup = pw_soup  # 디버그 정보도 업데이트
                    html = pw_html
                    logger.info(f"[bulletin] {board['name']}: Playwright 폴백 성공 ({len(posts)}건)")
            except Exception as e:
                logger.warning(f"[bulletin] {board['name']}: Playwright 폴백 실패: {e}")

        # 게시글 본문 추출 (Vercel 프록시 또는 Playwright)
        if posts and (use_playwright or used_vercel_proxy):
            await self._enrich_posts_with_content(posts, use_vercel=used_vercel_proxy)

        if not posts:
            # 디버그: HTML 구조 힌트
            tables = soup.find_all("table")
            all_links = soup.find_all("a", href=True)
            title_tag = soup.find("title")
            page_title = title_tag.get_text(strip=True) if title_tag else "(제목 없음)"
            debug_info = (
                f"페이지 제목: {page_title}\n"
                f"테이블: {len(tables)}개, 링크: {len(all_links)}개\n"
                f"HTML 크기: {len(html)}자\n"
            )
            # 링크 샘플
            link_samples = []
            for a in all_links[:10]:
                href = a.get("href", "")
                text = a.get_text(strip=True)[:40]
                if text:
                    link_samples.append(f"  {text} → {href[:60]}")
            if link_samples:
                debug_info += "링크 샘플:\n" + "\n".join(link_samples)

        return posts, debug_info

    async def _enrich_posts_with_content(self, posts: list[dict], max_posts: int = 5,
                                         use_vercel: bool = False):
        """게시글 목록의 각 항목에 본문 내용을 추가 (최대 max_posts개)"""
        from bs4 import BeautifulSoup as BS4

        # 본문 추출용 셀렉터 목록 (우선순위순)
        _content_sels = [
            "table.boardView1 td",  # yicare.or.kr 등 한국 공공기관 게시판
            "div.board_txt_area",  # imweb 플랫폼 (JTBC 마라톤 등)
            "div.board_view_content", "div.view_content", "div.bbs_content",
            "div.board-content", "div.content_view", "td.board_content",
            "div#content", "div.detail_content", "article", "div.view_cont",
        ]

        def _extract_content(soup_obj):
            """BeautifulSoup 객체에서 본문 텍스트 추출"""
            content_text = ""

            # boardView1 테이블의 "내용" th에 대응하는 td 찾기 (yicare.or.kr 패턴)
            view_table = soup_obj.select_one("table.boardView1")
            if view_table:
                for th in view_table.find_all("th"):
                    if "내용" in th.get_text(strip=True):
                        td = th.find_next_sibling("td")
                        if td:
                            # 이미지 URL 추출
                            imgs = td.find_all("img")
                            text = td.get_text(separator="\n", strip=True)
                            # script 태그 내용 제거
                            text = re.sub(r'imageMapResize\(\);?', '', text).strip()
                            if text and len(text) > 5:
                                content_text = text
                            elif imgs:
                                content_text = f"[이미지 {len(imgs)}장]"
                            break
                if content_text:
                    return content_text

            # 일반 셀렉터로 시도
            for sel in _content_sels:
                el = soup_obj.select_one(sel)
                if el and len(el.get_text(strip=True)) > 10:
                    content_text = el.get_text(separator="\n", strip=True)
                    break

            return content_text

        for post in posts[:max_posts]:
            post_url = post.get("url", "")
            if not post_url:
                continue
            try:
                # 용인시 고시공고: form POST로 상세 조회
                if post_url.startswith("yongin_gosi:"):
                    notice_no = post_url.split(":", 1)[1]
                    content_text = await self._fetch_yongin_gosi_detail(notice_no)
                    post["content"] = content_text[:5000]
                    logger.info(f"[bulletin] 고시공고 상세 추출: {post['title'][:30]}... ({len(content_text)}자)")
                    await asyncio.sleep(1)
                    continue

                if use_vercel:
                    # 프록시로 HTML 가져와서 BeautifulSoup 파싱
                    html = await self._fetch_via_proxy(post_url)
                    soup = BS4(html, "html.parser")
                    content_text = _extract_content(soup)
                    if not content_text:
                        body = soup.find("body")
                        if body:
                            content_text = body.get_text(separator="\n", strip=True)[:3000]
                    post["content"] = content_text[:5000]
                else:
                    # Playwright로 본문 추출
                    post["content"] = await self._pw_scrape_post_content(post_url)

                logger.info(f"[bulletin] 본문 추출: {post['title'][:30]}... ({len(post.get('content',''))}자)")
                await asyncio.sleep(1)  # 서버 부하 방지
            except Exception as e:
                logger.warning(f"[bulletin] 본문 추출 실패 ({post_url}): {e}")
                post["content"] = ""

    def _decode_html(self, raw: bytes, headers: dict) -> str:
        """응답 인코딩 자동 감지 (EUC-KR 사이트 대응)"""
        content_type = headers.get("Content-Type", headers.get("content-type", ""))

        # Content-Type 헤더에서 charset 추출
        charset_match = re.search(r"charset=([^\s;]+)", content_type, re.I)
        if charset_match:
            charset = charset_match.group(1).strip()
            try:
                return raw.decode(charset)
            except (UnicodeDecodeError, LookupError):
                pass

        # HTML meta 태그에서 charset 추출
        meta_match = re.search(
            rb'<meta[^>]+charset=["\']?([^"\'\s;>]+)', raw, re.I
        )
        if meta_match:
            charset = meta_match.group(1).decode("ascii", errors="ignore")
            try:
                return raw.decode(charset)
            except (UnicodeDecodeError, LookupError):
                pass

        # UTF-8 시도 → EUC-KR 시도 → 강제 UTF-8
        for enc in ["utf-8", "euc-kr", "cp949"]:
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue

        return raw.decode("utf-8", errors="replace")

    def _parse_table_board(self, soup, base_url: str, board: dict) -> list[dict]:
        """테이블 기반 게시판 파싱 (한국 공공기관 대다수)"""
        posts = []

        # 게시판 테이블 찾기: CSS 선택자가 설정되어 있으면 우선 사용
        css_selector = board.get("css_selector", "")
        if css_selector:
            container = soup.select_one(css_selector)
            if container:
                tables = container.find_all("table") or [container]
            else:
                tables = []
        else:
            # 일반적인 게시판 테이블 패턴 탐색
            tables = soup.find_all("table")

        for table in tables:
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # 헤더 행 분석 (번호, 제목, 작성자, 날짜 등)
            header = rows[0]
            header_cells = header.find_all(["th", "td"])
            header_texts = [c.get_text(strip=True) for c in header_cells]

            # 게시판 테이블인지 판별 (제목/글제목 컬럼이 있어야 함)
            title_keywords = ["제목", "글제목", "사업명", "공지사항", "프로그램", "내용", "과정명"]
            is_board = any(
                any(kw in ht for kw in title_keywords)
                for ht in header_texts
            )
            if not is_board and not css_selector:
                continue

            # 제목 컬럼 인덱스 찾기
            title_idx = None
            date_idx = None
            for i, ht in enumerate(header_texts):
                if any(kw in ht for kw in title_keywords):
                    title_idx = i
                if any(kw in ht for kw in ["날짜", "등록일", "작성일", "게시일", "일자", "접수기간"]):
                    date_idx = i

            # 데이터 행 파싱
            for row in rows[1:]:
                cells = row.find_all("td")
                if not cells:
                    continue

                # 제목과 링크 추출
                title = ""
                link = ""

                if title_idx is not None and title_idx < len(cells):
                    title_cell = cells[title_idx]
                else:
                    # 제목 인덱스를 못 찾으면, 링크가 있는 셀을 제목으로
                    title_cell = None
                    for cell in cells:
                        a_tag = cell.find("a")
                        if a_tag and len(a_tag.get_text(strip=True)) > 3:
                            title_cell = cell
                            break
                    if not title_cell:
                        continue

                a_tag = title_cell.find("a")
                if a_tag:
                    title = a_tag.get_text(strip=True)
                    href = a_tag.get("href", "")
                    onclick = a_tag.get("onclick", "")

                    # onclick에서 URL 또는 게시글 번호 추출
                    if href.startswith("javascript") or href in ("#", "./", ""):
                        # boardView('16730') 패턴 처리
                        board_view_match = re.search(r"boardView\s*\(\s*['\"](\d+)['\"]\s*\)", onclick)
                        if board_view_match:
                            post_no = board_view_match.group(1)
                            # 현재 게시판 URL에 no=... &board=view 추가
                            board_url_parsed = urlparse(board["url"])
                            base_params = board_url_parsed.query
                            href = f"{board_url_parsed.scheme}://{board_url_parsed.netloc}{board_url_parsed.path}?{base_params}&no={post_no}&board=view"
                        else:
                            # 일반 onclick URL 추출
                            url_match = re.search(r"['\"]([^'\"]*(?:\.php|\.do|\.asp|view)[^'\"]*)['\"]", onclick)
                            if url_match:
                                href = url_match.group(1)
                            else:
                                href = ""
                    if href and not href.startswith("http"):
                        href = urljoin(base_url, href)
                    link = href
                else:
                    title = title_cell.get_text(strip=True)

                if not title or len(title) < 2:
                    continue

                # 날짜 추출
                date_str = ""
                if date_idx is not None and date_idx < len(cells):
                    date_str = cells[date_idx].get_text(strip=True)
                else:
                    # 날짜 패턴 검색
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        if re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", text):
                            date_str = text
                            break

                content_hash = hashlib.sha256(
                    f"{board['id']}:{title}:{link or date_str}".encode()
                ).hexdigest()[:16]

                posts.append({
                    "title": title[:200],
                    "url": link,
                    "date": date_str[:30],
                    "hash": content_hash,
                })

            if posts:
                break  # 게시판 테이블을 찾았으면 종료

        return posts

    def _parse_list_board(self, soup, base_url: str, board: dict) -> list[dict]:
        """리스트/div 기반 게시판 파싱"""
        posts = []

        # 일반적인 게시판 리스트 패턴
        list_selectors = [
            "ul.board-list li",
            "ul.bbs-list li",
            "div.board-list div.item",
            "div.list-wrap div.list-item",
            ".board_list li",
            ".bbs_list li",
            ".notice_list li",
        ]

        items = []
        css_selector = board.get("css_selector", "")
        if css_selector:
            items = soup.select(css_selector)

        if not items:
            for selector in list_selectors:
                items = soup.select(selector)
                if items:
                    break

        # 리스트 선택자로 못 찾으면 모든 링크에서 게시글 패턴 추출
        if not items:
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"]
                text = a_tag.get_text(strip=True)
                # 게시글 링크 패턴 (view, read, detail 등 포함)
                if (re.search(r"(view|read|detail|content)", href, re.I)
                        and len(text) > 5):
                    if not href.startswith("http"):
                        href = urljoin(base_url, href)
                    content_hash = hashlib.sha256(
                        f"{board['id']}:{text}:{href}".encode()
                    ).hexdigest()[:16]
                    posts.append({
                        "title": text[:200],
                        "url": href,
                        "date": "",
                        "hash": content_hash,
                    })
            return posts[:20]

        for item in items:
            a_tag = item.find("a")
            if not a_tag:
                continue

            title = a_tag.get_text(strip=True)
            href = a_tag.get("href", "")
            if href and not href.startswith("http"):
                href = urljoin(base_url, href)

            # 날짜 추출
            date_str = ""
            date_el = item.find(class_=re.compile(r"date|time|day", re.I))
            if date_el:
                date_str = date_el.get_text(strip=True)
            else:
                text = item.get_text()
                date_match = re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", text)
                if date_match:
                    date_str = date_match.group()

            if title and len(title) > 2:
                content_hash = hashlib.sha256(
                    f"{board['id']}:{title}:{href or date_str}".encode()
                ).hexdigest()[:16]
                posts.append({
                    "title": title[:200],
                    "url": href,
                    "date": date_str[:30],
                    "hash": content_hash,
                })

        return posts[:20]

    def _parse_any_links(self, soup, base_url: str, board: dict) -> list[dict]:
        """최후 폴백: 페이지 내 모든 링크에서 게시글 패턴 추출"""
        posts = []
        seen_titles = set()

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            text = a_tag.get_text(strip=True)

            # 너무 짧거나 네비게이션 링크 제외
            if len(text) < 4 or len(text) > 200:
                continue
            nav_keywords = ["홈", "로그인", "회원가입", "사이트맵", "메뉴", "이전", "다음",
                            "처음", "마지막", "top", "home", "login", "prev", "next",
                            "first", "last", "more", "목록", "닫기", "검색"]
            if text.lower() in nav_keywords or text in seen_titles:
                continue

            # 게시글 링크 패턴: view, read, detail, content, idx, seq, no= 등
            is_post_link = bool(re.search(
                r"(view|read|detail|content|idx=|seq=|no=|num=|boardseq|articleseq|menuid.*groupid)",
                href, re.I
            ))
            # 또는 같은 도메인의 .php/.do/.asp 링크
            if not is_post_link:
                is_post_link = bool(re.search(r"\.(php|do|asp|jsp)\?", href, re.I))

            if not is_post_link:
                continue

            if not href.startswith("http"):
                href = urljoin(base_url, href)

            # 중복 제거
            if text in seen_titles:
                continue
            seen_titles.add(text)

            # 인접 요소에서 날짜 추출 시도
            date_str = ""
            parent = a_tag.parent
            if parent:
                parent_text = parent.get_text()
                date_match = re.search(r"(\d{4}[-./]\d{1,2}[-./]\d{1,2})", parent_text)
                if date_match:
                    date_str = date_match.group(1)

            content_hash = hashlib.sha256(
                f"{board['id']}:{text}:{href}".encode()
            ).hexdigest()[:16]

            posts.append({
                "title": text[:200],
                "url": href,
                "date": date_str,
                "hash": content_hash,
            })

        return posts[:20]

    # ── 용인시 고시공고 form POST 직접 조회 ─────────────

    async def _fetch_yongin_gosi_list(self) -> str:
        """용인시 고시공고 action URL에 form POST로 목록 HTML 가져오기"""
        from urllib.parse import urlencode

        action_url = "https://eminwon.yongin.go.kr/emwp/gov/mogaha/ntis/web/ofr/action/OfrAction.do"
        form_data = {
            "method": "selectListOfrNotAncmt",
            "methodnm": "selectListOfrNotAncmtHomepage",
            "not_ancmt_se_code": "01,04",
            "homepage_pbs_yn": "Y",
            "subCheck": "Y",
            "jndinm": "OfrNotAncmtEJB",
            "context": "NTIS",
            "epcCheck": "Y",
            "pageIndex": "",
            "ofr_pageSize": "10",
            "jspPageName": "OfrNotAncmtLSub.jsp",
            "list_gubun": "",
        }

        def _sync_fetch():
            data = urlencode(form_data).encode("utf-8")
            req = urllib.request.Request(action_url, data=data, method="POST", headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://eminwon.yongin.go.kr/emwp/jsp/ofr/OfrNotAncmtLSub.jsp",
                "Origin": "https://eminwon.yongin.go.kr",
            })
            resp = urllib.request.urlopen(req, context=self._ssl_ctx, timeout=20)
            raw = resp.read()
            # 인코딩 감지
            ct = resp.headers.get("Content-Type", "")
            if "euc-kr" in ct.lower() or "cp949" in ct.lower():
                return raw.decode("euc-kr", errors="replace")
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("euc-kr", errors="replace")

        return await asyncio.to_thread(_sync_fetch)

    async def _fetch_yongin_gosi_detail(self, notice_no: str) -> str:
        """용인시 고시공고 상세 페이지를 form POST로 가져와서 본문 텍스트 반환"""
        from urllib.parse import urlencode
        from bs4 import BeautifulSoup as BS4

        action_url = "https://eminwon.yongin.go.kr/emwp/gov/mogaha/ntis/web/ofr/action/OfrAction.do"
        form_data = {
            "method": "selectOfrNotAncmt",
            "methodnm": "selectOfrNotAncmtRegst",
            "not_ancmt_mgt_no": notice_no,
            "not_ancmt_se_code": "01,04",
            "homepage_pbs_yn": "Y",
            "subCheck": "Y",
            "jndinm": "OfrNotAncmtEJB",
            "context": "NTIS",
            "epcCheck": "Y",
            "jspPageName": "OfrNotAncmtLSub.jsp",
        }

        def _sync_fetch():
            data = urlencode(form_data).encode("utf-8")
            req = urllib.request.Request(action_url, data=data, method="POST", headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://eminwon.yongin.go.kr/emwp/jsp/ofr/OfrNotAncmtLSub.jsp",
                "Origin": "https://eminwon.yongin.go.kr",
            })
            resp = urllib.request.urlopen(req, context=self._ssl_ctx, timeout=20)
            raw = resp.read()
            ct = resp.headers.get("Content-Type", "")
            if "euc-kr" in ct.lower():
                html = raw.decode("euc-kr", errors="replace")
            else:
                try:
                    html = raw.decode("utf-8")
                except UnicodeDecodeError:
                    html = raw.decode("euc-kr", errors="replace")

            soup = BS4(html, "html.parser")

            parts = []

            # boardDefalutView 구조: h4(제목), dl(메타), .viewTxt(본문)
            view = soup.select_one(".boardDefalutView")
            if view:
                # 메타 정보
                for dl in view.find_all("dl"):
                    dt = dl.find("dt")
                    dds = dl.find_all("dd")
                    if dt and dds:
                        key = dt.get_text(strip=True)
                        val = " / ".join(dd.get_text(strip=True) for dd in dds if dd.get_text(strip=True))
                        if key and val and "첨부" not in key:
                            parts.append(f"{key}: {val}")

                # 본문 (.viewTxt)
                vt = view.select_one(".viewTxt")
                if vt:
                    text = vt.get_text(separator="\n", strip=True)
                    if text:
                        parts.append("")
                        parts.append(text)

                # 첨부파일
                for dl in view.find_all("dl"):
                    dt = dl.find("dt")
                    if dt and "첨부" in dt.get_text(strip=True):
                        for dd in dl.find_all("dd"):
                            a = dd.find("a")
                            if a:
                                parts.append(f"\n첨부: {a.get_text(strip=True)}")

            if parts:
                return "\n".join(parts)

            # 폴백: "내용" th → td 패턴
            for th in soup.find_all("th"):
                if "내용" in th.get_text(strip=True):
                    td = th.find_next_sibling("td")
                    if td:
                        text = td.get_text(separator="\n", strip=True)
                        if text and len(text) > 5:
                            return text

            body = soup.find("body")
            if body:
                return body.get_text(separator="\n", strip=True)[:3000]
            return ""

        return await asyncio.to_thread(_sync_fetch)

    # ── 용인시 고시공고 파서 (eminwon.yongin.go.kr) ──────

    def _parse_yongin_gosi(self, soup, base_url: str, board: dict) -> list[dict]:
        """용인시 고시공고 전용 파서 (table.boardDefalut 구조)
        컬럼: 번호 | 고시공고번호 | 제목 | 담당부서 | 등록일 | 게재기간 | 조회수
        onclick이 <td>에 직접 있음: <td onclick="searchDetail('142120')">
        """
        posts = []
        table = soup.select_one("table.boardDefalut")
        if not table:
            return self._parse_table_board(soup, base_url, board)

        rows = table.select("tbody tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 5:
                continue

            # 제목 (3번째 컬럼, index=2)
            title_cell = cells[2]
            title = title_cell.get_text(strip=True)
            if not title or len(title) < 2:
                continue

            # onclick은 <td>에 있거나 <a>에 있을 수 있음
            onclick = title_cell.get("onclick", "")
            a_tag = title_cell.find("a")
            if not onclick and a_tag:
                onclick = a_tag.get("onclick", "")
                title = a_tag.get_text(strip=True)

            # searchDetail('관리번호') 추출
            notice_no = ""
            m = re.search(r"searchDetail\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", onclick)
            if m:
                notice_no = m.group(1)

            # 고시공고번호 (2번째 컬럼)
            gosi_no = cells[1].get_text(strip=True)
            # 날짜 (5번째 컬럼, index=4)
            date_str = cells[4].get_text(strip=True)
            # 담당부서 (4번째 컬럼)
            dept = cells[3].get_text(strip=True)

            # 상세 페이지: form POST이므로 URL을 직접 구성할 수 없음
            # notice_no를 url 필드에 메타데이터로 저장 (추후 상세 조회 시 사용)
            detail_url = f"yongin_gosi:{notice_no}" if notice_no else ""

            content_hash = hashlib.sha256(
                f"{board['id']}:{title}:{notice_no or date_str}".encode()
            ).hexdigest()[:16]

            post = {
                "title": f"[{gosi_no}] {title}" if gosi_no else title[:200],
                "url": detail_url,
                "date": date_str[:30],
                "hash": content_hash,
                "notice_no": notice_no,
            }
            if dept:
                post["content"] = f"담당부서: {dept}"
            posts.append(post)

        logger.info(f"[bulletin] 용인시 고시공고 파서: {len(posts)}건")
        return posts

    # ── 용인시 문화행사 파서 ───────────────────────────────

    def _parse_yongin_event(self, soup, base_url: str, board: dict) -> list[dict]:
        """용인시 문화행사 전용 파서.
        구조: div.gallery_bbs_list4 > ul > li (갤러리 카드형)
        각 li 안에: .gallery_bbs_img img, .gallery_bbs_txt p.tit,
        a[href*="BD_selectClturEventPfmcyt.do"] 상세 링크
        """
        posts = []

        # 1차: 정확한 셀렉터 (gallery_bbs_list4)
        items = soup.select("div.gallery_bbs_list4 > ul > li")

        # 2차: 일반 갤러리 패턴 폴백
        if not items:
            for sel in ["div.gallery_bbs_list4 li", "div.gallery_bbs_list li",
                        "div.gallery_list li", "ul.gallery_list > li",
                        "div.event_list li", "div.culture_list li"]:
                items = soup.select(sel)
                if items:
                    break

        # 3차: BD_selectClturEventPfmcyt 링크 패턴 폴백
        if not items:
            seen = set()
            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href", "")
                if "BD_selectClturEventPfmcyt.do" in href and href != "#":
                    text = a_tag.get_text(strip=True)
                    if len(text) > 2 and text not in seen:
                        seen.add(text)
                        full_url = urljoin(base_url, href) if not href.startswith("http") else href
                        # 부모에서 날짜 추출
                        parent = a_tag.parent
                        date_str = ""
                        if parent:
                            dm = re.search(r"(\d{4}\.\d{2}\.\d{2})", parent.get_text())
                            if dm:
                                date_str = dm.group(1)
                        content_hash = hashlib.sha256(
                            f"{board['id']}:{text}:{full_url}".encode()
                        ).hexdigest()[:16]
                        posts.append({"title": text[:200], "url": full_url, "date": date_str, "hash": content_hash})

            if posts:
                logger.info(f"[bulletin] 문화행사 링크 패턴: {len(posts)}건")
                return posts[:20]

            # 4차: 테이블 폴백
            return self._parse_table_board(soup, base_url, board)

        # 카드 아이템 파싱
        for item in items:
            # 제목: p.tit
            title = ""
            title_el = item.select_one(".gallery_bbs_txt p.tit")
            if title_el:
                title = title_el.get_text(strip=True)
            else:
                title_el = item.select_one(".tit, .title, h3, h4, strong")
                if title_el:
                    title = title_el.get_text(strip=True)

            if not title or len(title) < 2:
                continue

            # 상세 링크: BD_selectClturEventPfmcyt.do 포함하는 a 태그 (href="#" 제외)
            link = ""
            for a in item.find_all("a", href=True):
                href = a.get("href", "")
                if "BD_selectClturEventPfmcyt.do" in href and href != "#":
                    link = urljoin(base_url, href) if not href.startswith("http") else href
                    break
            if not link:
                # 일반 링크 폴백
                for a in item.find_all("a", href=True):
                    href = a.get("href", "")
                    if href and href != "#" and not href.startswith("javascript"):
                        link = urljoin(base_url, href) if not href.startswith("http") else href
                        break

            # 카테고리 (bbs_label)
            category = ""
            label_el = item.select_one(".bbs_label")
            if label_el:
                category = label_el.get_text(strip=True)

            # 행사기간 (첫번째 li의 마지막 span)
            date_str = ""
            meta_items = item.select(".gallery_bbs_txt ul li")
            for mi in meta_items:
                text = mi.get_text(strip=True)
                if "행사기간" in text or "기간" in text:
                    spans = mi.find_all("span")
                    if len(spans) >= 2:
                        date_str = spans[-1].get_text(strip=True)
                    else:
                        dm = re.search(r"(\d{4}\.\d{2}\.\d{2}\s*~\s*\d{4}\.\d{2}\.\d{2})", text)
                        if dm:
                            date_str = dm.group(1)
                    break
            if not date_str:
                dm = re.search(r"(\d{4}\.\d{2}\.\d{2})", item.get_text())
                if dm:
                    date_str = dm.group(1)

            # 장소
            venue = ""
            for mi in meta_items:
                text = mi.get_text(strip=True)
                if "장소" in text:
                    el = mi.select_one(".ellipsis, span:last-child")
                    if el:
                        venue = el.get_text(strip=True)
                    break

            # 이미지 URL
            img_url = ""
            img = item.select_one(".gallery_bbs_img img")
            if not img:
                img = item.find("img")
            if img:
                img_src = img.get("src", "")
                if img_src and not img_src.startswith("data:"):
                    img_url = urljoin(base_url, img_src) if not img_src.startswith("http") else img_src

            content_hash = hashlib.sha256(
                f"{board['id']}:{title}:{link or date_str}".encode()
            ).hexdigest()[:16]

            post = {
                "title": f"[{category}] {title}" if category else title[:200],
                "url": link,
                "date": date_str[:50],
                "hash": content_hash,
            }
            if venue:
                post["content"] = f"장소: {venue}"
            if img_url:
                post["thumbnail"] = img_url
            posts.append(post)

        logger.info(f"[bulletin] 문화행사 카드 파서: {len(posts)}건")
        return posts[:20]

    # ── ggcf 게시판 파서 (경기도어린이박물관 등) ──────────

    def _parse_ggcf_board(self, soup, base_url: str, board: dict) -> list[dict]:
        """경기문화재단(ggcf.kr) 게시판 파서.
        구조: div.list-type1 반복, 각 div 안에:
        - div.part-list-title > a (제목 + URL)
        - strong (카테고리: 공지사항, 채용공고 등)
        - p.part-date (날짜)
        """
        posts = []

        items = soup.select("div.list-type1")
        for item in items:
            # 제목 + URL
            title_div = item.select_one("div.part-list-title")
            a_tag = title_div.find("a", href=True) if title_div else None
            if not a_tag:
                continue

            # 제목 텍스트 (이미지 태그 제외)
            title_p = a_tag.find("p")
            if title_p:
                # span(아이콘) 제거 후 텍스트만
                for span in title_p.find_all("span"):
                    span.decompose()
                title = title_p.get_text(strip=True)
            else:
                title = a_tag.get_text(strip=True)

            if not title or len(title) < 2:
                continue

            href = a_tag.get("href", "")
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = f"{base_url}{href}"
            else:
                full_url = f"{base_url}/{href}"

            # 날짜 (p.part-date)
            date_p = item.select_one("p.part-date")
            date_str = date_p.get_text(strip=True) if date_p else ""

            # 카테고리 (strong 태그)
            cat_el = item.find("strong")
            category = cat_el.get_text(strip=True) if cat_el else ""

            post_hash = hashlib.md5(f"{board.get('id', '')}{title}{href}".encode()).hexdigest()

            post = {
                "title": f"[{category}] {title}" if category else title,
                "url": full_url,
                "date": date_str,
                "hash": post_hash,
                "content": "",
            }
            posts.append(post)

        logger.info(f"[bulletin] ggcf 게시판 파서: {len(posts)}건")
        return posts

    # ── imweb 게시판 파서 (JTBC 마라톤 등) ────────────────

    def _parse_imweb_board(self, soup, base_url: str, board: dict) -> list[dict]:
        """imweb 플랫폼 게시판 파서.
        구조: div.li_board > ul.li_body 반복, 각 ul 안에:
        - a.list_text_title (제목 + href에 idx 포함)
        - li.time (날짜)
        - li.category (카테고리)
        - li.count (번호)
        """
        posts = []
        board_url = board.get("url", base_url)

        # li_body ul 항목들 = 각 게시글
        items = soup.select("ul.li_body.holder")
        if not items:
            items = soup.select("div.li_board ul.li_body")

        for item in items:
            # 제목 + URL
            title_a = item.select_one("a.list_text_title")
            if not title_a:
                continue

            title_span = title_a.select_one("span")
            title = title_span.get_text(strip=True) if title_span else title_a.get_text(strip=True)
            if not title:
                continue

            href = title_a.get("href", "")
            # idx 추출
            idx_match = re.search(r'idx=(\d+)', href)
            if href.startswith("/"):
                full_url = f"{base_url}{href}"
            elif href.startswith("http"):
                full_url = href
            else:
                full_url = f"{board_url}{'&' if '?' in board_url else '?'}{href}"

            # 날짜
            time_li = item.select_one("li.time")
            date_str = time_li.get("title", "").strip() if time_li else ""
            if not date_str and time_li:
                date_str = time_li.get_text(strip=True)

            # 카테고리
            cat_li = item.select_one("li.category em")
            category = cat_li.get_text(strip=True).strip("[]") if cat_li else ""

            # 번호
            count_li = item.select_one("li.count")
            post_no = count_li.get_text(strip=True) if count_li else ""

            post_hash = hashlib.md5(f"{board.get('id', '')}{title}{date_str}".encode()).hexdigest()

            post = {
                "title": f"[{category}] {title}" if category else title,
                "url": full_url,
                "date": date_str.split(" ")[0] if date_str else "",
                "hash": post_hash,
                "content": "",
            }
            posts.append(post)

        logger.info(f"[bulletin] imweb 게시판 파서: {len(posts)}건")
        return posts

    async def _fetch_imweb_detail(self, url: str) -> str:
        """imweb 게시글 상세 페이지에서 본문 추출"""
        try:
            content, headers = await asyncio.to_thread(self._fetch_url, url)
            html = self._decode_html(content, headers)
        except Exception:
            try:
                html = await self._fetch_via_proxy(url)
            except Exception as e:
                logger.warning(f"[bulletin] imweb 상세 페이지 접근 실패: {e}")
                return ""

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # board_txt_area에서 본문 추출
        txt_area = soup.select_one("div.board_txt_area")
        if txt_area:
            # 이미지 URL 수집
            imgs = txt_area.find_all("img", src=True)
            img_urls = [img["src"] for img in imgs if img["src"].startswith("http")]

            text = txt_area.get_text(separator="\n", strip=True)
            if img_urls:
                text += "\n\n[이미지]\n" + "\n".join(img_urls[:5])
            return text[:5000]

        return ""

    # ── 새 글 필터링 ─────────────────────────────────────

    @staticmethod
    def _parse_post_date(date_str: str) -> Optional[datetime]:
        """게시글 날짜 문자열을 datetime으로 파싱 (다양한 한국 날짜 형식 지원)"""
        if not date_str:
            return None
        # 숫자만 추출하여 날짜 파싱 시도
        cleaned = date_str.strip()
        for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d.",
                     "%y.%m.%d", "%y-%m-%d", "%y/%m/%d"):
            try:
                return datetime.strptime(cleaned[:10], fmt).replace(tzinfo=KST)
            except ValueError:
                continue
        # "2026년 03월 19일" 형식
        m = re.search(r"(\d{4})\s*[년.]\s*(\d{1,2})\s*[월.]\s*(\d{1,2})", cleaned)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=KST)
            except ValueError:
                pass
        return None

    async def _filter_new_posts(self, board: dict, posts: list[dict]) -> list[dict]:
        """이미 저장된 게시글 제외 + 최근 24시간 이내 글만 포함"""
        # 1) 24시간 이내 글만 필터링
        cutoff = datetime.now(KST) - timedelta(hours=24)
        recent_posts = []
        for p in posts:
            post_date = self._parse_post_date(p.get("date", ""))
            if post_date is None:
                # 날짜를 파싱할 수 없으면 포함 (안전하게)
                recent_posts.append(p)
            elif post_date >= cutoff:
                recent_posts.append(p)

        if len(recent_posts) < len(posts):
            logger.info(
                f"[bulletin] 24시간 필터: {len(posts)}건 → {len(recent_posts)}건"
            )

        if not recent_posts:
            return []

        # 2) 이미 저장된 게시글 제외
        hashes = [p["hash"] for p in recent_posts]

        def _sync_check():
            try:
                result = self.supabase.table("bulletin_posts").select("hash").in_(
                    "hash", hashes
                ).execute()
                return {r["hash"] for r in (result.data or [])}
            except Exception as e:
                logger.error(f"[bulletin] 기존 게시글 조회 실패: {e}")
                return set()

        seen_hashes = await asyncio.to_thread(_sync_check)
        return [p for p in recent_posts if p["hash"] not in seen_hashes]

    # ── 게시글 저장 ──────────────────────────────────────

    async def _save_posts(self, board: dict, posts: list[dict]) -> int:
        """새 게시글을 Supabase에 저장"""
        def _sync_save():
            saved = 0
            for post in posts:
                try:
                    self.supabase.table("bulletin_posts").insert({
                        "board_id": board["id"],
                        "title": post["title"],
                        "url": post.get("url", ""),
                        "content": post.get("content", "")[:5000],
                        "post_date": post.get("date", ""),
                        "hash": post["hash"],
                        "created_at": datetime.now(KST).isoformat(),
                    }).execute()
                    saved += 1
                except Exception as e:
                    if "duplicate" not in str(e).lower():
                        logger.error(f"[bulletin] 게시글 저장 실패: {e}")
            return saved

        return await asyncio.to_thread(_sync_save)

    # ── 노션 저장 ──────────────────────────────────────────

    async def _save_to_notion(self, post: dict, board: dict) -> str:
        """게시글을 노션 DB에 저장하고 페이지 URL 반환"""
        if not self._notion_api_key:
            logger.warning("[bulletin] NOTION_API_KEY 없음 — 노션 저장 건너뜀")
            return ""

        # 게시글 HTML에서 이미지 URL 추출 및 Supabase Storage 업로드
        image_urls = await self._upload_post_images(post, board)

        # 노션 페이지 본문 구성
        board_name = board["name"]
        title = post["title"]
        post_url = post.get("url", "")
        content_text = post.get("content", "")
        date_str = post.get("date", "")

        # Notion 페이지 content (마크다운)
        lines = [
            "## 게시글 정보\n",
            f"- **출처**: {board_name}",
            f"- **작성일**: {date_str}" if date_str else "",
            f"- **원본 링크**: {post_url}" if post_url else "",
            "",
        ]
        lines = [l for l in lines if l is not None]

        if content_text:
            lines.append("## 본문\n")
            lines.append(content_text[:3000])
            lines.append("")

        if image_urls:
            lines.append("## 첨부 이미지\n")
            for i, img_url in enumerate(image_urls, 1):
                lines.append(f"![이미지 {i}]({img_url})\n")

        if not content_text and not image_urls:
            lines.append("> 본문 내용을 가져오지 못했습니다.\n")

        lines.append("---")
        lines.append(f"*수집일: {datetime.now(KST).strftime('%Y-%m-%d %H:%M')} | 에이전트: bulletin_agent*")

        content = "\n".join(lines)

        # Notion API 호출
        page_data = {
            "parent": {"database_id": self._notion_db_id},
            "properties": {
                "이름": {"title": [{"text": {"content": f"{title} - {board_name}"}}]},
                "상태": {"status": {"name": "AI 초안 완료"}},
            },
            "children": self._markdown_to_notion_blocks(content),
        }
        if image_urls:
            page_data["icon"] = {"type": "emoji", "emoji": "📋"}

        def _sync_create():
            req = urllib.request.Request(
                "https://api.notion.com/v1/pages",
                data=json.dumps(page_data).encode("utf-8"),
                method="POST",
                headers={
                    "Authorization": f"Bearer {self._notion_api_key}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28",
                },
            )
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(req, timeout=30, context=ctx)
            result = json.loads(resp.read())
            return result.get("url", "")

        notion_url = await asyncio.to_thread(_sync_create)
        logger.info(f"[bulletin] 노션 저장 완료: {title[:30]}... → {notion_url}")
        return notion_url

    def _markdown_to_notion_blocks(self, md: str) -> list[dict]:
        """간단한 마크다운을 Notion 블록으로 변환"""
        blocks = []
        for line in md.split("\n"):
            if not line.strip():
                continue

            # 헤딩
            if line.startswith("## "):
                blocks.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": [{"type": "text", "text": {"content": line[3:].strip()}}]},
                })
            elif line.startswith("---"):
                blocks.append({"object": "block", "type": "divider", "divider": {}})
            # 이미지
            elif line.startswith("!["):
                m = re.match(r"!\[.*?\]\((.+?)\)", line)
                if m:
                    blocks.append({
                        "object": "block",
                        "type": "image",
                        "image": {"type": "external", "external": {"url": m.group(1)}},
                    })
            # 인용
            elif line.startswith("> "):
                blocks.append({
                    "object": "block",
                    "type": "quote",
                    "quote": {"rich_text": [{"type": "text", "text": {"content": line[2:].strip()}}]},
                })
            # 리스트
            elif line.startswith("- "):
                text = line[2:]
                # 볼드 처리
                rich_text = self._parse_inline_markdown(text)
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": rich_text},
                })
            # 이탤릭 (전체 줄)
            elif line.startswith("*") and line.endswith("*"):
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line.strip("*")}, "annotations": {"italic": True}}]},
                })
            # 일반 텍스트
            else:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]},
                })

        return blocks[:100]  # Notion API 블록 제한

    def _parse_inline_markdown(self, text: str) -> list[dict]:
        """인라인 마크다운(볼드/링크)을 Notion rich_text로 변환"""
        parts = []
        remaining = text
        while remaining:
            # 볼드
            m = re.search(r"\*\*(.+?)\*\*", remaining)
            if m:
                if m.start() > 0:
                    parts.append({"type": "text", "text": {"content": remaining[:m.start()]}})
                parts.append({"type": "text", "text": {"content": m.group(1)}, "annotations": {"bold": True}})
                remaining = remaining[m.end():]
            else:
                parts.append({"type": "text", "text": {"content": remaining}})
                break
        return parts

    async def _upload_post_images(self, post: dict, board: dict) -> list[str]:
        """게시글의 이미지를 프록시로 다운로드 → Supabase Storage 업로드 → 공개 URL 반환"""
        post_url = post.get("url", "")
        if not post_url or not self._vercel_proxy_key:
            return []

        # 게시글 HTML 가져오기 (이미지 URL 추출용)
        try:
            html = await self._fetch_via_proxy(post_url)
        except Exception as e:
            logger.warning(f"[bulletin] 이미지 추출용 HTML 가져오기 실패: {e}")
            return []

        # boardView 영역에서 이미지 URL 추출
        img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html)
        # 게시판 도메인의 이미지만 필터 (외부 광고/트래커 제외)
        board_domain = urlparse(board["url"]).netloc
        filtered = []
        for img in img_urls:
            full_url = urljoin(post_url, img)
            if board_domain in full_url and "/upload/" in full_url:
                filtered.append(full_url)

        if not filtered:
            return []

        logger.info(f"[bulletin] 이미지 {len(filtered)}개 발견: {post['title'][:30]}...")

        # 각 이미지 다운로드 & 업로드 (최대 5개)
        public_urls = []
        for img_url in filtered[:5]:
            try:
                public_url = await self._download_and_upload_image(img_url, board)
                if public_url:
                    public_urls.append(public_url)
            except Exception as e:
                logger.warning(f"[bulletin] 이미지 업로드 실패 ({img_url}): {e}")

        return public_urls

    async def _download_and_upload_image(self, img_url: str, board: dict) -> str:
        """프록시로 이미지 다운로드 → Supabase Storage 업로드 → 공개 URL 반환"""
        key = self._vercel_proxy_key
        proxy_url = self._supabase_proxy_url  # base64 지원하는 Supabase Edge Function 사용

        def _sync_download_upload():
            # 1. 프록시로 이미지 다운로드 (base64)
            payload = json.dumps({"url": img_url, "spoof_ip": "211.234.120.50"}).encode("utf-8")
            ctx = ssl.create_default_context()
            req = urllib.request.Request(proxy_url, data=payload, method="POST", headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "YhmemoBot/1.0",
            })
            resp = urllib.request.urlopen(req, timeout=60, context=ctx)
            result = json.loads(resp.read())

            if "base64" not in result:
                logger.warning(f"[bulletin] 이미지 base64 없음 (status={result.get('status')})")
                return ""

            img_data = base64.b64decode(result["base64"])
            if len(img_data) < 100:
                return ""

            # 2. Supabase Storage에 업로드
            # 파일명: 게시판별 디렉토리 / 원본 파일명
            parsed = urlparse(img_url)
            filename = os.path.basename(parsed.path)
            board_slug = re.sub(r"[^a-z0-9]", "-", board["name"].lower())[:30]
            storage_path = f"{board_slug}/{filename}"

            upload_url = f"{self._supabase_url}/storage/v1/object/{self._storage_bucket}/{storage_path}"
            req2 = urllib.request.Request(upload_url, data=img_data, method="POST", headers={
                "Authorization": f"Bearer {key}",
                "apikey": key,
                "Content-Type": result.get("content_type", "image/jpeg"),
                "x-upsert": "true",
            })
            urllib.request.urlopen(req2, timeout=60, context=ctx)

            public_url = f"{self._supabase_url}/storage/v1/object/public/{self._storage_bucket}/{storage_path}"
            logger.info(f"[bulletin] 이미지 업로드 완료: {storage_path}")
            return public_url

        return await asyncio.to_thread(_sync_download_upload)

    # ── 슬랙 알림 ────────────────────────────────────────

    async def _send_slack_notification(self, board: dict, posts: list[dict]):
        """새 게시글 슬랙 알림"""
        board_name = board["name"]
        board_url = board["url"]

        # 최대 5개까지만 개별 표시
        display_posts = posts[:5]
        remaining = len(posts) - len(display_posts)

        lines = [f"*:pushpin: [{board_name}] 새 게시글 {len(posts)}건*\n"]

        for post in display_posts:
            title = post["title"]
            url = post.get("url", "")
            date = post.get("date", "")
            content = post.get("content", "")
            notion_url = post.get("notion_url", "")

            if url:
                lines.append(f"• <{url}|{title}>")
            else:
                lines.append(f"• {title}")
            if date:
                lines[-1] += f"  ({date})"
            # 노션 링크
            if notion_url:
                lines.append(f"  :memo: <{notion_url}|노션에서 보기>")
            # 본문 미리보기 (100자)
            if content:
                preview = content.replace("\n", " ").strip()[:100]
                if preview:
                    lines.append(f"  _{preview}{'...' if len(content) > 100 else ''}_")

        if remaining > 0:
            lines.append(f"\n_...외 {remaining}건 더_")

        lines.append(f"\n<{board_url}|게시판 바로가기>")

        message = "\n".join(lines)
        await self.slack.send_message(self.slack_channel, message)

    async def _send_daily_report(self, results: list[dict], board_count: int):
        """KST 22시 일일 보고: 오늘 발견된 새 게시글 요약"""
        now_kst = datetime.now(KST)
        date_str = now_kst.strftime("%Y년 %m월 %d일")

        total_new = sum(len(r["posts"]) for r in results)
        boards_with_new = len(results)

        lines = [f"*:newspaper: [{date_str}] 게시판 일일 보고*\n"]
        lines.append(f"모니터링 게시판: {board_count}개 | 새 글 발견: {total_new}건 ({boards_with_new}개 게시판)\n")

        if not results:
            lines.append("_오늘 새 게시글이 없습니다._")
        else:
            for result in results:
                board = result["board"]
                posts = result["posts"]
                lines.append(f"*:pushpin: {board['name']}* — 새 글 {len(posts)}건")
                for post in posts[:3]:
                    title = post["title"]
                    url = post.get("url", "")
                    date = post.get("date", "")
                    notion_url = post.get("notion_url", "")
                    if url:
                        line = f"  • <{url}|{title}>"
                    else:
                        line = f"  • {title}"
                    if date:
                        line += f"  ({date})"
                    if notion_url:
                        line += f"  :memo: <{notion_url}|노션>"
                    lines.append(line)
                if len(posts) > 3:
                    lines.append(f"  _...외 {len(posts) - 3}건_")
                lines.append("")

        message = "\n".join(lines)
        await self.slack.send_message(self.slack_channel, message)
        logger.info(f"[bulletin] 일일 보고 발송: {total_new}건 새 글")

    # ── 외부 작업 수신 ───────────────────────────────────

    async def handle_external_task(self, task: TaskMessage) -> Any:
        """다른 에이전트/명령어에서 즉시 스크래핑 요청"""
        if task.task_type == "scrape_now":
            # 즉시 모든 게시판 스크래핑
            context = await self.observe()
            if context:
                decision = await self.think(context)
                if decision:
                    await self.act(decision)
                    return {"status": "completed", "results": len(decision.get("results", []))}
            return {"status": "no_new_posts"}

        elif task.task_type == "add_board":
            # 새 게시판 등록
            payload = task.payload
            return await self._add_board(
                name=payload.get("name", ""),
                url=payload.get("url", ""),
                parser_type=payload.get("parser_type", "auto"),
                css_selector=payload.get("css_selector", ""),
                use_playwright=payload.get("use_playwright", False),
            )

        return await super().handle_external_task(task)

    async def _add_board(self, name: str, url: str, parser_type: str = "auto",
                         css_selector: str = "", use_playwright: bool = False) -> dict:
        """새 게시판을 Supabase에 등록"""
        def _sync_add():
            try:
                result = self.supabase.table("bulletin_boards").insert({
                    "name": name,
                    "url": url,
                    "parser_type": parser_type,
                    "css_selector": css_selector,
                    "use_playwright": use_playwright,
                    "active": True,
                    "created_at": datetime.now(KST).isoformat(),
                }).execute()
                return {"status": "added", "data": result.data}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return await asyncio.to_thread(_sync_add)
