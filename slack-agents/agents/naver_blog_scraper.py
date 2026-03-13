"""
네이버 블로그 스크래퍼 (Naver Blog Scraper)

역할:
- Playwright를 사용하여 네이버 블로그 글을 크롤링
- 블로그 URL을 받아 제목, 본문 텍스트, 이미지 URL 등을 추출
- 슬랙 명령어(!블로그) 및 자연어로 호출 가능

네이버 블로그는 iframe 구조로 되어 있어 일반 HTTP 요청으로는
본문을 가져올 수 없으므로 Playwright(headless 브라우저)를 사용합니다.
글 목록은 RSS 피드를 우선 시도하고, 실패 시 Playwright로 폴백합니다.
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode

import aiohttp

logger = logging.getLogger(__name__)

# 글 목록 조회 시만 차단 (본문 크롤링은 이미지 필요하므로 차단 안 함)
_BLOCKED_RESOURCE_TYPES_LIST = {"image", "media", "font", "stylesheet"}
_BLOCKED_URL_PATTERNS = [
    "google-analytics", "googletagmanager", "doubleclick",
    "adservice", "googlesyndication", "facebook.net",
    "connect.facebook", "analytics", "ad.naver", "adimg",
]
# 본문 크롤링 시 차단할 리소스 (광고/트래커만, 이미지는 허용)
_BLOCKED_RESOURCE_TYPES_POST = {"media", "font"}


class NaverBlogScraper:
    """Playwright 기반 네이버 블로그 스크래퍼"""

    # 네이버 블로그 URL 패턴
    BLOG_PATTERNS = [
        r"blog\.naver\.com/([^/\?]+)/(\d+)",        # blog.naver.com/블로그ID/글번호
        r"blog\.naver\.com/PostView\.naver",          # blog.naver.com/PostView.naver?blogId=...
        r"m\.blog\.naver\.com/([^/\?]+)/(\d+)",       # 모바일 버전
        r"blog\.naver\.com/([^/\?\s]+)$",             # blog.naver.com/블로그ID (블로그 홈)
        r"blog\.naver\.com/([^/\?\s]+)\?",            # blog.naver.com/블로그ID?... (쿼리 포함)
    ]

    # 개별 글 URL 패턴 (홈과 구분용)
    POST_PATTERNS = [
        r"blog\.naver\.com/([^/\?]+)/(\d+)",
        r"blog\.naver\.com/PostView\.naver",
        r"m\.blog\.naver\.com/([^/\?]+)/(\d+)",
    ]

    # 페이지 로딩 타임아웃 (ms)
    PAGE_TIMEOUT = 30000
    IFRAME_TIMEOUT = 15000
    SELECTOR_TIMEOUT = 8000

    def __init__(self):
        self._browser = None
        self._playwright = None

    async def _ensure_browser(self):
        """브라우저가 없으면 시작"""
        if self._browser and self._browser.is_connected():
            return

        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
            ],
        )
        logger.info("[NaverBlog] Playwright 브라우저 시작됨")

    async def close(self):
        """브라우저 정리"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    @staticmethod
    def is_naver_blog_url(url: str) -> bool:
        """네이버 블로그 URL인지 확인"""
        return any(re.search(p, url) for p in NaverBlogScraper.BLOG_PATTERNS)

    @staticmethod
    def _normalize_url(url: str) -> str:
        """모바일 URL을 PC 버전으로 변환, 불필요한 쿼리 파라미터 제거"""
        # 슬랙이 URL을 <https://...> 또는 <https://...|표시텍스트>로 감싸는 경우 처리
        url = url.strip()
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1]
        # 슬랙 링크 형식: <URL|표시텍스트> → URL만 추출
        if "|" in url:
            url = url.split("|")[0]
        # 이중 래핑 제거: https://<https://...> 또는 <https://blog...>
        url = re.sub(r"^https?://<(https?://)", r"\1", url)
        url = url.strip("<>")
        url = url.replace("m.blog.naver.com", "blog.naver.com")
        if not url.startswith("http"):
            url = "https://" + url
        # fromRss, trackingCode 등 불필요한 쿼리 파라미터 제거
        parsed = urlparse(url)
        if parsed.query:
            qs = parse_qs(parsed.query)
            # 제거할 파라미터
            for remove_key in ["fromRss", "trackingCode"]:
                qs.pop(remove_key, None)
            if qs:
                clean_query = urlencode(qs, doseq=True)
                url = parsed._replace(query=clean_query).geturl()
            else:
                url = parsed._replace(query="").geturl()
        return url

    @staticmethod
    def _is_post_url(url: str) -> bool:
        """개별 글 URL인지 확인 (블로그 홈이 아닌)"""
        return any(re.search(p, url) for p in NaverBlogScraper.POST_PATTERNS)

    @staticmethod
    def _extract_blog_id(url: str) -> str:
        """URL에서 블로그 ID 추출"""
        m = re.search(r"blog\.naver\.com/([^/\?\s]+)", url)
        return m.group(1) if m else ""

    async def _create_context(self, block_mode: str = "none"):
        """
        브라우저 컨텍스트 생성
        block_mode: "none" (차단 없음), "list" (목록용 - 이미지/CSS 차단), "post" (글용 - 광고만 차단)
        """
        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = await context.new_page()

        if block_mode == "list":
            async def list_handler(route):
                req = route.request
                if req.resource_type in _BLOCKED_RESOURCE_TYPES_LIST:
                    await route.abort()
                    return
                url_lower = req.url.lower()
                if any(p in url_lower for p in _BLOCKED_URL_PATTERNS):
                    await route.abort()
                    return
                await route.continue_()
            await page.route("**/*", list_handler)
        elif block_mode == "post":
            async def post_handler(route):
                req = route.request
                if req.resource_type in _BLOCKED_RESOURCE_TYPES_POST:
                    await route.abort()
                    return
                url_lower = req.url.lower()
                if any(p in url_lower for p in _BLOCKED_URL_PATTERNS):
                    await route.abort()
                    return
                await route.continue_()
            await page.route("**/*", post_handler)

        return context, page

    async def scrape(self, url: str, max_posts: int = 5) -> dict:
        """
        네이버 블로그 글을 스크래핑합니다.
        블로그 홈 URL이면 최신 글 목록을 가져옵니다.

        Args:
            url: 네이버 블로그 글 URL 또는 블로그 홈 URL
            max_posts: 블로그 홈일 때 가져올 최신 글 수 (기본 5)

        Returns:
            개별 글: {"success", "title", "content", "images", "date", "author", "url"}
            블로그 홈: {"success", "is_home", "blog_id", "posts": [{"title", "url", "date"}...]}
        """
        url = self._normalize_url(url)

        if not self.is_naver_blog_url(url):
            return {"success": False, "error": "네이버 블로그 URL이 아닙니다.", "url": url}

        try:
            await self._ensure_browser()
            if self._is_post_url(url):
                return await self._scrape_blog_post_with_retry(url)
            else:
                return await self._scrape_blog_home(url, max_posts)
        except Exception as e:
            logger.error(f"[NaverBlog] 스크래핑 실패: {e}", exc_info=True)
            return {"success": False, "error": str(e), "url": url}

    async def _scrape_blog_post_with_retry(self, url: str, max_retries: int = 2) -> dict:
        """재시도 로직이 포함된 블로그 글 스크래핑"""
        last_error = None
        for attempt in range(max_retries):
            try:
                result = await self._scrape_blog_post(url)
                # 본문이 비어있으면 PostView.naver 직접 접근으로 재시도
                if result.get("success") and not result.get("content") and attempt < max_retries - 1:
                    logger.warning(f"[NaverBlog] 본문 비어있음, PostView.naver로 재시도 (시도 {attempt + 1})")
                    result = await self._scrape_blog_post_direct(url)
                return result
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"[NaverBlog] 스크래핑 실패 (시도 {attempt + 1}/{max_retries}), {wait}초 후 재시도: {e}")
                    await asyncio.sleep(wait)
        raise last_error

    def _to_postview_naver_url(self, url: str) -> Optional[str]:
        """blog.naver.com/ID/글번호 → PostView.naver?blogId=ID&logNo=글번호 변환"""
        m = re.search(r"blog\.naver\.com/([^/\?]+)/(\d+)", url)
        if m:
            blog_id, log_no = m.group(1), m.group(2)
            return f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"
        return None

    async def _get_content_frame(self, page):
        """페이지에서 콘텐츠 프레임 찾기 (iframe 또는 메인 페이지)"""
        content_frame = page

        # mainFrame iframe 찾기
        iframe = page.frame("mainFrame")
        if not iframe:
            # iframe이 JS로 동적 생성될 수 있으므로 잠시 대기 후 재시도
            logger.info("[NaverBlog] mainFrame 없음, 2초 대기 후 재시도")
            await asyncio.sleep(2)
            iframe = page.frame("mainFrame")

        if iframe:
            content_frame = iframe
            try:
                await content_frame.wait_for_load_state("domcontentloaded", timeout=self.IFRAME_TIMEOUT)
            except Exception as e:
                logger.warning(f"[NaverBlog] iframe domcontentloaded 대기 타임아웃, 계속 진행: {e}")

        return content_frame

    async def _find_content_element(self, content_frame):
        """본문 컨텐츠 요소 찾기"""
        content_selectors = [
            "div.se-main-container",       # 스마트에디터 3 (최신)
            "div.__se_component_area",      # 스마트에디터 2
            "div#postViewArea",             # 구버전
            "div.post-view",                # 또 다른 구버전
            "div#post-view",
            "div.post_ct",                  # 일부 테마
            "div#content-area",             # 콘텐츠 영역
        ]

        # 먼저 셀렉터 중 하나가 나타날 때까지 대기
        combined_selector = ", ".join(content_selectors)
        try:
            await content_frame.wait_for_selector(combined_selector, timeout=self.SELECTOR_TIMEOUT)
        except Exception:
            logger.debug("[NaverBlog] 복합 셀렉터 대기 타임아웃")

        # 개별적으로 찾기
        for sel in content_selectors:
            try:
                el = await content_frame.query_selector(sel)
                if el:
                    # 텍스트가 있는지 빠르게 확인
                    text = await el.inner_text()
                    if text and len(text.strip()) > 10:
                        logger.info(f"[NaverBlog] 본문 셀렉터 발견: {sel} (텍스트 {len(text)}자)")
                        return el
            except Exception:
                continue

        logger.warning("[NaverBlog] 알려진 본문 셀렉터를 찾지 못함, body에서 시도")
        return await content_frame.query_selector("body")

    async def _scrape_blog_post(self, url: str) -> dict:
        """블로그 글 스크래핑 (기본 방식: 원래 URL로 접속)"""
        context, page = await self._create_context(block_mode="post")

        try:
            logger.info(f"[NaverBlog] 접속 중: {url}")
            await page.goto(url, wait_until="domcontentloaded", timeout=self.PAGE_TIMEOUT)

            # 고정 대기 (네이버 JS 렌더링 시간 확보, networkidle 대신)
            await asyncio.sleep(3)

            content_frame = await self._get_content_frame(page)
            content_el = await self._find_content_element(content_frame)

            result = await self._extract_all(content_frame, content_el, url)
            return result

        finally:
            await page.close()
            await context.close()

    async def _scrape_blog_post_direct(self, url: str) -> dict:
        """PostView.naver URL로 직접 접근하여 스크래핑 (폴백)"""
        postview_url = self._to_postview_naver_url(url)
        if not postview_url:
            logger.warning("[NaverBlog] PostView URL 변환 실패, 원래 URL 사용")
            postview_url = url

        context, page = await self._create_context(block_mode="post")

        try:
            logger.info(f"[NaverBlog] PostView 직접 접속: {postview_url}")
            await page.goto(postview_url, wait_until="domcontentloaded", timeout=self.PAGE_TIMEOUT)

            await asyncio.sleep(3)

            content_frame = await self._get_content_frame(page)
            content_el = await self._find_content_element(content_frame)

            result = await self._extract_all(content_frame, content_el, url)
            return result

        finally:
            await page.close()
            await context.close()

    async def _extract_all(self, content_frame, content_el, url: str) -> dict:
        """제목/본문/이미지/날짜/작성자를 한번에 추출 (순서 보존)"""
        title = await self._extract_title(content_frame)
        content_text = ""
        if content_el:
            content_text = await self._extract_text(content_el)
        images = await self._extract_images(content_frame, content_el)
        date = await self._extract_date(content_frame)
        author = await self._extract_author(content_frame, url)

        # 텍스트/이미지 순서 보존 추출
        ordered_blocks = []
        if content_el:
            ordered_blocks = await self._extract_ordered_blocks(content_el)

        logger.info(f"[NaverBlog] 추출 결과: 제목={title[:30]}, 본문={len(content_text)}자, 이미지={len(images)}장, 블록={len(ordered_blocks)}개")

        return {
            "success": True,
            "title": title,
            "content": content_text,
            "images": images,
            "ordered_blocks": ordered_blocks,
            "date": date,
            "author": author,
            "url": url,
        }

    async def _scrape_blog_home(self, url: str, max_posts: int = 5) -> dict:
        """블로그 홈 URL에서 최신 글 목록 추출 (RSS 우선, Playwright 폴백)"""
        blog_id = self._extract_blog_id(url)

        # 1차: RSS 피드로 빠르게 글 목록 가져오기
        posts = await self._fetch_posts_via_rss(blog_id, max_posts)
        if posts:
            logger.info(f"[NaverBlog] RSS로 {len(posts)}개 글 목록 가져옴")
            return {
                "success": True,
                "is_home": True,
                "blog_id": blog_id,
                "url": url,
                "posts": posts,
            }

        # 2차: Playwright로 폴백
        logger.info("[NaverBlog] RSS 실패, Playwright로 글 목록 가져오기 시도")
        return await self._scrape_blog_home_playwright(url, blog_id, max_posts)

    async def _fetch_posts_via_rss(self, blog_id: str, max_posts: int) -> list[dict]:
        """RSS 피드로 글 목록 가져오기 (Playwright 없이 빠름)"""
        if not blog_id:
            return []

        rss_url = f"https://rss.blog.naver.com/{blog_id}.xml"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.warning(f"[NaverBlog] RSS 응답 실패: {resp.status}")
                        return []
                    xml_text = await resp.text()

            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                return []

            posts = []
            for item in channel.findall("item")[:max_posts]:
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                pub_date = item.findtext("pubDate", "").strip()
                if title and link:
                    # RSS 링크에서 불필요한 파라미터 제거
                    link = self._normalize_url(link)
                    posts.append({"title": title, "url": link, "date": pub_date})

            return posts

        except asyncio.TimeoutError:
            logger.warning("[NaverBlog] RSS 요청 타임아웃")
            return []
        except ET.ParseError as e:
            logger.warning(f"[NaverBlog] RSS XML 파싱 실패: {e}")
            return []
        except Exception as e:
            logger.warning(f"[NaverBlog] RSS 가져오기 실패: {e}")
            return []

    async def _scrape_blog_home_playwright(self, url: str, blog_id: str, max_posts: int = 5) -> dict:
        """Playwright로 블로그 홈에서 최신 글 목록 추출"""
        context, page = await self._create_context(block_mode="list")

        try:
            list_url = f"https://blog.naver.com/PostList.naver?blogId={blog_id}&categoryNo=0&from=postList"
            logger.info(f"[NaverBlog] 블로그 홈 접속: {list_url}")

            try:
                await page.goto(list_url, wait_until="domcontentloaded", timeout=self.PAGE_TIMEOUT)
            except Exception as e:
                logger.warning(f"[NaverBlog] PostList 로딩 실패, 블로그 홈으로 재시도: {e}")
                home_url = f"https://blog.naver.com/{blog_id}"
                await page.goto(home_url, wait_until="domcontentloaded", timeout=self.PAGE_TIMEOUT)

            content_frame = await self._get_content_frame(page)

            posts = []

            # 방법 1: CSS 셀렉터로 추출
            post_selectors = [
                "a.pcol2",
                "span.ell a",
                "a.link__iGhdOl",
                "div.post-item a",
                "table.board-list a",
                ".blog2_post a.sp_blog2",
                "div.area_list_title a",
                "div.wrap_postlist a.url",
                "div.blog2_series a",
            ]

            for sel in post_selectors:
                try:
                    links = await content_frame.query_selector_all(sel)
                    for link in links[:max_posts * 2]:
                        href = await link.get_attribute("href")
                        title = (await link.inner_text()).strip()
                        if href and title and len(title) > 1:
                            if href.startswith("/"):
                                href = "https://blog.naver.com" + href
                            elif not href.startswith("http"):
                                continue
                            if "blog.naver.com" in href:
                                posts.append({"title": title, "url": href})
                    if posts:
                        break
                except Exception as e:
                    logger.debug(f"[NaverBlog] 셀렉터 {sel} 실패: {e}")
                    continue

            # 방법 2: 모든 링크에서 글 URL 패턴 필터링
            if not posts:
                try:
                    all_links = await content_frame.query_selector_all("a[href]")
                    seen_urls = set()
                    for link in all_links:
                        href = await link.get_attribute("href")
                        if not href:
                            continue
                        if href.startswith("/"):
                            href = "https://blog.naver.com" + href
                        post_match = re.search(r"blog\.naver\.com/[^/]+/(\d+)", href)
                        if post_match and href not in seen_urls:
                            seen_urls.add(href)
                            title = (await link.inner_text()).strip()
                            if not title or len(title) < 2:
                                title = f"글 #{post_match.group(1)}"
                            posts.append({"title": title, "url": href})
                except Exception as e:
                    logger.warning(f"[NaverBlog] 링크 추출 실패: {e}")

            # 방법 3: 페이지 HTML에서 직접 정규식으로 추출
            if not posts:
                try:
                    html = await content_frame.content()
                    matches = re.findall(
                        r'href="(https?://blog\.naver\.com/' + re.escape(blog_id) + r'/(\d+))"',
                        html
                    )
                    seen = set()
                    for full_url, post_no in matches:
                        if full_url not in seen:
                            seen.add(full_url)
                            posts.append({"title": f"글 #{post_no}", "url": full_url})
                    if not posts:
                        pv_matches = re.findall(
                            r'href="(/PostView\.naver\?blogId=' + re.escape(blog_id) + r'[^"]*logNo=(\d+)[^"]*)"',
                            html
                        )
                        for rel_url, post_no in pv_matches:
                            full_url = "https://blog.naver.com" + rel_url
                            if full_url not in seen:
                                seen.add(full_url)
                                posts.append({"title": f"글 #{post_no}", "url": full_url})
                except Exception as e:
                    logger.warning(f"[NaverBlog] HTML 정규식 추출 실패: {e}")

            # 중복 제거 및 제한
            seen = set()
            unique_posts = []
            for p in posts:
                if p["url"] not in seen:
                    seen.add(p["url"])
                    unique_posts.append(p)
            posts = unique_posts[:max_posts]

            return {
                "success": True,
                "is_home": True,
                "blog_id": blog_id,
                "url": url,
                "posts": posts,
            }

        finally:
            await page.close()
            await context.close()

    def _to_postview_url(self, url: str) -> str:
        """블로그 URL을 그대로 반환 (iframe 접근은 Playwright가 처리)"""
        return url

    async def _extract_title(self, frame) -> str:
        """제목 추출"""
        title_selectors = [
            "div.se-module-text.se-title-text",   # SE3
            "span.se-fs-",                          # SE3 텍스트
            "h3.se_textarea",                       # SE2
            "div.htitle span",                      # 구버전
            "h3.tit_h3",
            "title",
        ]
        for sel in title_selectors:
            try:
                el = await frame.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        # " : 네이버블로그" / " : 네이버 블로그" 접미사 제거
                        text = self._clean_title(text)
                        if text:
                            return text
            except Exception:
                continue

        # 페이지 타이틀에서 추출 시도
        try:
            page_title = await frame.title() if hasattr(frame, 'title') else ""
            if page_title:
                return self._clean_title(page_title)
        except Exception:
            pass

        return "(제목 없음)"

    @staticmethod
    def _clean_title(title: str) -> str:
        """제목에서 네이버 블로그 접미사 제거"""
        # "제목 : 네이버 블로그", "제목 : 네이버블로그" 등 제거
        title = re.sub(r"\s*[:\-]\s*네이버\s*블로그.*$", "", title).strip()
        # "제목 .. : 네이버블로그" 패턴도 처리
        title = re.sub(r"\s*\.{2,}\s*$", "", title).strip()
        return title

    async def _extract_text(self, element) -> str:
        """본문 텍스트 추출 — HTML 태그 제거하고 깔끔하게"""
        try:
            text = await element.inner_text()
            lines = [line.strip() for line in text.split("\n")]
            lines = [line for line in lines if line]
            result = "\n".join(lines)
            # 네이버 블로그 공통 불필요 텍스트 제거
            noise_patterns = [
                r"^공감\d*$",
                r"^댓글\d*$",
                r"^이 블로그.*검색$",
                r"^맨 위로$",
                r"^블로그 메뉴$",
                r"^프롤로그$",
            ]
            cleaned_lines = []
            for line in result.split("\n"):
                if not any(re.match(p, line) for p in noise_patterns):
                    cleaned_lines.append(line)
            return "\n".join(cleaned_lines)
        except Exception as e:
            logger.warning(f"[NaverBlog] 텍스트 추출 실패: {e}")
            return ""

    async def _extract_images(self, frame, content_el) -> list[str]:
        """이미지 URL 추출"""
        images = []
        try:
            target = content_el or frame
            img_elements = await target.query_selector_all("img")

            for img in img_elements:
                # 여러 이미지 속성 시도 (지연 로딩 대응)
                src = None
                for attr in ["data-lazy-src", "data-src", "src"]:
                    src = await img.get_attribute(attr)
                    if src and src.startswith("http"):
                        break
                    if src and src.startswith("//"):
                        src = "https:" + src
                        break

                if not src:
                    continue

                # 아이콘/UI 이미지 제외
                if any(skip in src for skip in [
                    "static.nid.naver", "ssl.pstatic.net/static",
                    "blogpfthumb", "favicon", "btn_", "ico_",
                    "widget", "banner", "ad_", "blank.gif",
                    "transparent", "spacer",
                ]):
                    continue

                # 크기가 너무 작은 이미지 제외 (아이콘일 가능성)
                width = await img.get_attribute("width")
                height = await img.get_attribute("height")
                if width and height:
                    try:
                        if int(width) < 50 or int(height) < 50:
                            continue
                    except ValueError:
                        pass

                if src.startswith("//"):
                    src = "https:" + src
                if src.startswith("http"):
                    images.append(src)

        except Exception as e:
            logger.warning(f"[NaverBlog] 이미지 추출 실패: {e}")

        seen = set()
        unique_images = []
        for img in images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)

        return unique_images[:20]

    # 이미지 필터링에 사용할 패턴 (클래스 상수)
    _SKIP_IMG_PATTERNS = [
        "static.nid.naver", "ssl.pstatic.net/static",
        "blogpfthumb", "favicon", "btn_", "ico_",
        "widget", "banner", "ad_", "blank.gif",
        "transparent", "spacer",
    ]

    async def _extract_ordered_blocks(self, content_el) -> list[dict]:
        """본문 내 텍스트와 이미지를 원래 순서대로 추출.
        반환: [{"type": "text", "value": "...", "rich_text": [...]}, {"type": "image", "value": "url"}, ...]
        """
        blocks = []
        try:
            # SE3: se-component 단위로 순회
            components = await content_el.query_selector_all(
                "div.se-component"
            )
            if components:
                for comp in components:
                    comp_type = await comp.get_attribute("class") or ""
                    # 이미지 컴포넌트
                    if "se-image" in comp_type or "se-sticker" in comp_type:
                        img = await comp.query_selector("img")
                        if img:
                            src = await self._get_img_src(img)
                            if src:
                                blocks.append({"type": "image", "value": src})
                    # 텍스트 컴포넌트
                    elif "se-text" in comp_type:
                        rich = await self._extract_rich_text(comp)
                        text = (await comp.inner_text()).strip()
                        if text:
                            blocks.append({"type": "text", "value": text, "rich_text": rich})
                    # 인용구
                    elif "se-quotation" in comp_type:
                        rich = await self._extract_rich_text(comp)
                        text = (await comp.inner_text()).strip()
                        if text:
                            blocks.append({"type": "quote", "value": text, "rich_text": rich})
                    # 구분선
                    elif "se-horizontalLine" in comp_type:
                        blocks.append({"type": "divider", "value": ""})
                    # 기타: 텍스트가 있으면 추출
                    else:
                        imgs = await comp.query_selector_all("img")
                        for img in imgs:
                            src = await self._get_img_src(img)
                            if src:
                                blocks.append({"type": "image", "value": src})
                        text = (await comp.inner_text()).strip()
                        if text:
                            rich = await self._extract_rich_text(comp)
                            blocks.append({"type": "text", "value": text, "rich_text": rich})
                if blocks:
                    return blocks

            # SE2 / 구버전: 자식 요소를 순회
            children = await content_el.query_selector_all(":scope > *")
            for child in children:
                tag = await child.evaluate("el => el.tagName.toLowerCase()")
                if tag == "img":
                    src = await self._get_img_src(child)
                    if src:
                        blocks.append({"type": "image", "value": src})
                    continue
                imgs = await child.query_selector_all("img")
                for img in imgs:
                    src = await self._get_img_src(img)
                    if src:
                        blocks.append({"type": "image", "value": src})
                text = (await child.inner_text()).strip()
                if text:
                    rich = await self._extract_rich_text(child)
                    blocks.append({"type": "text", "value": text, "rich_text": rich})

        except Exception as e:
            logger.warning(f"[NaverBlog] ordered_blocks 추출 실패: {e}")

        return blocks

    async def _extract_rich_text(self, element) -> list[dict]:
        """요소에서 텍스트와 하이퍼링크를 rich_text 배열로 추출.
        반환: [{"text": "일반텍스트"}, {"text": "링크텍스트", "url": "https://..."}]
        """
        try:
            # JS로 직접 텍스트 노드와 링크를 순서대로 추출
            rich_text = await element.evaluate("""el => {
                const result = [];
                function walk(node) {
                    if (node.nodeType === 3) { // TEXT_NODE
                        const t = node.textContent;
                        if (t) result.push({text: t});
                    } else if (node.tagName === 'A') {
                        const href = node.href || node.getAttribute('href') || '';
                        const t = node.innerText || node.textContent || '';
                        if (t && href && href.startsWith('http')) {
                            result.push({text: t, url: href});
                        } else if (t) {
                            result.push({text: t});
                        }
                    } else if (node.tagName === 'BR') {
                        result.push({text: '\\n'});
                    } else {
                        for (const child of node.childNodes) {
                            walk(child);
                        }
                    }
                }
                walk(el);
                return result;
            }""")
            return rich_text if rich_text else []
        except Exception:
            # 폴백: 순수 텍스트
            try:
                text = (await element.inner_text()).strip()
                return [{"text": text}] if text else []
            except Exception:
                return []

    async def _get_img_src(self, img) -> Optional[str]:
        """img 요소에서 유효한 src URL 추출 (필터링 포함)"""
        src = None
        for attr in ["data-lazy-src", "data-src", "src"]:
            s = await img.get_attribute(attr)
            if s and (s.startswith("http") or s.startswith("//")):
                src = s
                break
        if not src:
            return None
        if src.startswith("//"):
            src = "https:" + src
        if any(skip in src for skip in self._SKIP_IMG_PATTERNS):
            return None
        # 크기 필터
        width = await img.get_attribute("width")
        height = await img.get_attribute("height")
        if width and height:
            try:
                if int(width) < 50 or int(height) < 50:
                    return None
            except ValueError:
                pass
        return src if src.startswith("http") else None

    async def _extract_date(self, frame) -> str:
        """작성일 추출"""
        date_selectors = [
            "span.se_publishDate",
            "span.date",
            "p.date",
            "span.blog_date",
            "span.se_date",
            "span.se-date",                # SE3 최신
            "div.blog_date",
        ]
        for sel in date_selectors:
            try:
                el = await frame.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    async def _extract_author(self, frame, url: str) -> str:
        """작성자(블로그 ID) 추출"""
        m = re.search(r"blog\.naver\.com/([^/\?]+)", url)
        if m:
            return m.group(1)

        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if "blogId" in qs:
            return qs["blogId"][0]

        return ""

    async def scrape_multiple(self, urls: list[str]) -> list[dict]:
        """여러 블로그 글을 순차적으로 스크래핑"""
        results = []
        for url in urls:
            result = await self.scrape(url)
            results.append(result)
            await asyncio.sleep(1)
        return results

    @staticmethod
    def to_notion_blocks(result: dict) -> list[dict]:
        """스크래핑 결과를 노션 콘텐츠 블록으로 변환 (원문 순서 보존).
        NotionClient의 블록 헬퍼를 사용합니다.
        """
        from integrations.notion_client import NotionClient

        blocks = []

        # 원문 링크
        if result.get("url"):
            blocks.append(NotionClient.block_bookmark(result["url"]))
            blocks.append(NotionClient.block_divider())

        # ordered_blocks가 있으면 원래 순서대로 변환
        # 연속 텍스트 블록은 \n으로 합쳐서 하나의 paragraph로 (이중 줄바꿈 방지)
        ordered = result.get("ordered_blocks", [])
        if ordered:
            # 연속 텍스트 블록을 그룹으로 묶기
            i = 0
            while i < len(ordered):
                ob = ordered[i]
                if ob["type"] == "text":
                    # 연속된 text 블록들의 rich_text를 합치기
                    merged_rich: list[dict] = []
                    while i < len(ordered) and ordered[i]["type"] == "text":
                        cur = ordered[i]
                        if merged_rich:
                            # 이전 텍스트와 구분을 위해 줄바꿈 추가
                            merged_rich.append({"text": "\n"})
                        rich = cur.get("rich_text", [])
                        if rich:
                            merged_rich.extend(rich)
                        else:
                            merged_rich.append({"text": cur["value"]})
                        i += 1
                    # rich_text 전체 길이 체크 후 블록 생성
                    blocks.append(NotionClient.block_paragraph_rich(merged_rich))
                elif ob["type"] == "image":
                    blocks.append(NotionClient.block_image(ob["value"]))
                    i += 1
                elif ob["type"] == "quote":
                    rich = ob.get("rich_text", [])
                    if rich:
                        blocks.append(NotionClient.block_quote_rich(rich))
                    else:
                        blocks.append(NotionClient.block_quote(ob["value"][:2000]))
                    i += 1
                elif ob["type"] == "divider":
                    blocks.append(NotionClient.block_divider())
                    i += 1
                else:
                    i += 1
        else:
            # ordered_blocks가 없으면 content + images 순서로 폴백
            content = result.get("content", "")
            if content:
                for para in content.split("\n\n"):
                    para = para.strip()
                    if para:
                        while para:
                            blocks.append(NotionClient.block_paragraph(para[:2000]))
                            para = para[2000:]

            images = result.get("images", [])
            if images:
                blocks.append(NotionClient.block_divider())
                for img_url in images:
                    blocks.append(NotionClient.block_image(img_url))

        # 노션 API는 한 번에 최대 100개 블록
        return blocks[:100]

    def format_for_slack(self, result: dict) -> str:
        """스크래핑 결과를 슬랙 메시지로 포맷팅"""
        if not result.get("success"):
            error = result.get("error", "알 수 없는 오류")
            if "Timeout" in error:
                friendly = "페이지 로딩이 너무 오래 걸려요. 잠시 후 다시 시도해주세요."
            elif "net::" in error.lower():
                friendly = "네트워크 연결에 문제가 있어요. 잠시 후 다시 시도해주세요."
            else:
                friendly = error
            return f":x: 스크래핑 실패: {friendly}\nURL: {result.get('url', '')}"

        # 블로그 홈 결과
        if result.get("is_home"):
            parts = []
            parts.append(f":house: *{result.get('blog_id', '')}* 블로그 최신 글 목록")
            parts.append(f":link: {result['url']}")
            parts.append("")
            posts = result.get("posts", [])
            if posts:
                for i, p in enumerate(posts, 1):
                    date_str = f" ({p['date']})" if p.get("date") else ""
                    parts.append(f"{i}. <{p['url']}|{p['title']}>{date_str}")
                parts.append(f"\n_총 {len(posts)}건 — 개별 글을 크롤링하려면 URL을 보내주세요_")
            else:
                parts.append("_글 목록을 가져오지 못했습니다._")
            return "\n".join(parts)

        parts = []
        parts.append(f":notebook: *{result['title']}*")

        if result.get("author"):
            parts.append(f":bust_in_silhouette: 작성자: {result['author']}")
        if result.get("date"):
            parts.append(f":calendar: {result['date']}")

        parts.append(f":link: {result['url']}")
        parts.append("")

        content = result.get("content", "")
        if len(content) > 2000:
            content = content[:2000] + "...\n_(본문이 길어서 일부만 표시)_"
        if content:
            parts.append(content)
        else:
            parts.append("_(본문을 가져오지 못했습니다)_")

        images = result.get("images", [])
        if images:
            parts.append(f"\n:frame_with_picture: 이미지 {len(images)}장")
            for img_url in images[:3]:
                parts.append(img_url)
            if len(images) > 3:
                parts.append(f"_... 외 {len(images) - 3}장_")

        return "\n".join(parts)


# 모듈 레벨 싱글턴
_scraper: Optional[NaverBlogScraper] = None


async def get_scraper() -> NaverBlogScraper:
    """싱글턴 스크래퍼 인스턴스 반환"""
    global _scraper
    if _scraper is None:
        _scraper = NaverBlogScraper()
    return _scraper


async def scrape_naver_blog(url: str) -> dict:
    """편의 함수: URL 하나 스크래핑"""
    scraper = await get_scraper()
    return await scraper.scrape(url)
