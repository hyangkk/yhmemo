"""
게시판 스크래퍼 에이전트 (Bulletin Board Scraper Agent)

역할:
- 학교, 문화센터, 공공기관 등 다양한 웹 게시판을 주기적으로 스크래핑
- 새 게시글 감지 시 슬랙으로 알림
- Supabase에 모니터링할 게시판 목록과 수집된 게시글 저장

자율 행동:
- Observe: bulletin_boards 테이블에서 모니터링 대상 확인, 스크래핑 시간 판단
- Think: 새 게시글이 있는지 판단
- Act: 새 게시글을 저장하고 슬랙 알림 전송
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

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


class BulletinAgent(BaseAgent):
    """게시판 스크래퍼 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="bulletin",
            description="학교/문화센터/공공기관 게시판을 모니터링하여 새 게시글을 알려주는 에이전트",
            slack_channel=SlackClient.CHANNEL_GENERAL,
            loop_interval=21600,  # 6시간마다 실행
            **kwargs,
        )
        self._http = httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=HEADERS,
            verify=False,  # 구린 사이트 SSL 인증서 문제 대응
        )

    async def start(self):
        """에이전트 시작 — 테이블 확인만 하고 자동 루프는 실행하지 않음 (수동 전용)"""
        await self._ensure_tables()
        self._running = True
        logger.info(f"[{self.name}] Agent registered (manual-only mode, no auto loop)")
        # 자동 루프 실행하지 않음 — !게시판 명령어로만 실행

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
                                    active BOOLEAN DEFAULT TRUE,
                                    created_at TIMESTAMPTZ DEFAULT NOW(),
                                    updated_at TIMESTAMPTZ DEFAULT NOW()
                                );
                                CREATE TABLE IF NOT EXISTS bulletin_posts (
                                    id BIGSERIAL PRIMARY KEY,
                                    board_id BIGINT REFERENCES bulletin_boards(id) ON DELETE CASCADE,
                                    title TEXT NOT NULL,
                                    url TEXT DEFAULT '',
                                    post_date TEXT DEFAULT '',
                                    hash TEXT NOT NULL UNIQUE,
                                    created_at TIMESTAMPTZ DEFAULT NOW()
                                );
                                CREATE INDEX IF NOT EXISTS idx_bulletin_posts_hash ON bulletin_posts(hash);
                                CREATE INDEX IF NOT EXISTS idx_bulletin_posts_board_id ON bulletin_posts(board_id);
                            """)
                        conn.close()
                        logger.info("[bulletin] 테이블 생성 완료")
                    else:
                        logger.warning("[bulletin] DATABASE_URL 없음 — Supabase Dashboard에서 수동 생성 필요")
                except Exception as e2:
                    logger.error(f"[bulletin] 테이블 자동 생성 실패: {e2}")

        await asyncio.to_thread(_sync_ensure)

    # ── Observe ─────────────────────────────────────────

    async def observe(self) -> dict | None:
        """모니터링 대상 게시판 목록 로드"""
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
                posts = await self._scrape_board(board)
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
            return None

        return {"action": "notify_new_posts", "results": all_new_posts}

    # ── Act ────────────────────────────────────────────

    async def act(self, decision: dict):
        """새 게시글을 저장하고 슬랙에 알림"""
        results = decision.get("results", [])

        for result in results:
            board = result["board"]
            posts = result["posts"]

            # Supabase에 저장
            saved_count = await self._save_posts(board, posts)

            # 슬랙 알림
            await self._send_slack_notification(board, posts)

            logger.info(f"[bulletin] {board['name']}: {saved_count}건 저장, 알림 발송")

    # ── 게시판 목록 로드 ─────────────────────────────────

    async def _load_boards(self) -> list[dict]:
        """Supabase bulletin_boards 테이블에서 활성 게시판 목록 로드"""
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

    # ── 게시판 스크래핑 ──────────────────────────────────

    async def scrape_and_show(self, channel: str, thread_ts: str = None, max_posts: int = 5):
        """게시판 스크래핑 후 결과를 바로 슬랙에 표시 (새 글 필터 없이)"""
        boards = await self._load_boards()
        if not boards:
            await self._reply(channel, "등록된 게시판이 없습니다. `!게시판 등록 이름 URL`로 추가하세요.", thread_ts)
            return

        for board in boards:
            try:
                posts, debug_info = await self._scrape_board(board)
                if posts:
                    # 최근 N개만 표시
                    display = posts[:max_posts]
                    lines = [f"*:pushpin: [{board['name']}] 최근 게시글 (총 {len(posts)}건 중 {len(display)}건)*\n"]
                    for p in display:
                        title = p["title"]
                        url = p.get("url", "")
                        date = p.get("date", "")
                        if url:
                            lines.append(f"• <{url}|{title}>")
                        else:
                            lines.append(f"• {title}")
                        if date:
                            lines[-1] += f"  ({date})"
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
                await self._reply(channel, f":x: [{board['name']}] 오류: {e}", thread_ts)

    async def _scrape_board(self, board: dict) -> tuple[list[dict], str]:
        """게시판 HTML을 파싱하여 게시글 목록 추출. (posts, debug_info) 반환"""
        url = board["url"]
        parser_type = board.get("parser_type", "auto")
        debug_info = ""

        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"[bulletin] HTTP 요청 실패 ({url}): {e}")
            return [], f"HTTP 오류: {e}"

        # 인코딩 감지 및 처리
        html = self._decode_html(resp)
        logger.info(f"[bulletin] {board['name']}: HTML {len(html)}자 수신")

        # BeautifulSoup 파싱
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        # 파서 타입에 따라 분기
        if parser_type == "table":
            posts = self._parse_table_board(soup, base_url, board)
        elif parser_type == "list":
            posts = self._parse_list_board(soup, base_url, board)
        else:
            # auto: 테이블 → 리스트 → 링크 폴백
            posts = self._parse_table_board(soup, base_url, board)
            if not posts:
                posts = self._parse_list_board(soup, base_url, board)
            if not posts:
                posts = self._parse_any_links(soup, base_url, board)

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

    def _decode_html(self, resp: httpx.Response) -> str:
        """응답 인코딩 자동 감지 (EUC-KR 사이트 대응)"""
        content_type = resp.headers.get("content-type", "")

        # Content-Type 헤더에서 charset 추출
        charset_match = re.search(r"charset=([^\s;]+)", content_type, re.I)
        if charset_match:
            charset = charset_match.group(1).strip()
            try:
                return resp.content.decode(charset)
            except (UnicodeDecodeError, LookupError):
                pass

        # HTML meta 태그에서 charset 추출
        raw = resp.content
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
                    if href:
                        # javascript:void(0) 등 무시, onclick에서 URL 추출 시도
                        if href.startswith("javascript") or href == "#":
                            onclick = a_tag.get("onclick", "")
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

    # ── 새 글 필터링 ─────────────────────────────────────

    async def _filter_new_posts(self, board: dict, posts: list[dict]) -> list[dict]:
        """이미 저장된 게시글 제외"""
        hashes = [p["hash"] for p in posts]

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
        return [p for p in posts if p["hash"] not in seen_hashes]

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

            if url:
                lines.append(f"• <{url}|{title}>")
            else:
                lines.append(f"• {title}")
            if date:
                lines[-1] += f"  ({date})"

        if remaining > 0:
            lines.append(f"\n_...외 {remaining}건 더_")

        lines.append(f"\n<{board_url}|게시판 바로가기>")

        message = "\n".join(lines)
        await self.slack.send_message(self.slack_channel, message)

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
            )

        return await super().handle_external_task(task)

    async def _add_board(self, name: str, url: str, parser_type: str = "auto",
                         css_selector: str = "") -> dict:
        """새 게시판을 Supabase에 등록"""
        def _sync_add():
            try:
                result = self.supabase.table("bulletin_boards").insert({
                    "name": name,
                    "url": url,
                    "parser_type": parser_type,
                    "css_selector": css_selector,
                    "active": True,
                    "created_at": datetime.now(KST).isoformat(),
                }).execute()
                return {"status": "added", "data": result.data}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        return await asyncio.to_thread(_sync_add)
