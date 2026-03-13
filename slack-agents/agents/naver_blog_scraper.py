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
from urllib.parse import urlparse, parse_qs

import aiohttp

logger = logging.getLogger(__name__)

# 불필요한 리소스 타입 (차단하여 로딩 속도 개선)
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}
# 차단할 URL 패턴 (광고/트래커)
_BLOCKED_URL_PATTERNS = [
    "google-analytics", "googletagmanager", "doubleclick",
    "adservice", "googlesyndication", "facebook.net",
    "connect.facebook", "analytics", "ad.naver", "adimg",
]


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
    PAGE_TIMEOUT = 60000
    IFRAME_TIMEOUT = 30000
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
        """모바일 URL을 PC 버전으로 변환"""
        url = url.replace("m.blog.naver.com", "blog.naver.com")
        if not url.startswith("http"):
            url = "https://" + url
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

    async def _create_context(self, block_resources: bool = False):
        """브라우저 컨텍스트 생성 (리소스 차단 옵션)"""
        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = await context.new_page()

        if block_resources:
            await page.route("**/*", self._route_handler)

        return context, page

    @staticmethod
    async def _route_handler(route):
        """불필요한 리소스 차단 핸들러"""
        req = route.request
        if req.resource_type in _BLOCKED_RESOURCE_TYPES:
            await route.abort()
            return
        url_lower = req.url.lower()
        if any(p in url_lower for p in _BLOCKED_URL_PATTERNS):
            await route.abort()
            return
        await route.continue_()

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
                return await self._scrape_blog_post(url)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"[NaverBlog] 스크래핑 실패 (시도 {attempt + 1}/{max_retries}), {wait}초 후 재시도: {e}")
                    await asyncio.sleep(wait)
        raise last_error

    async def _scrape_blog_post(self, url: str) -> dict:
        """실제 블로그 글 스크래핑"""
        context, page = await self._create_context(block_resources=False)

        try:
            direct_url = self._to_postview_url(url)
            logger.info(f"[NaverBlog] 접속 중: {direct_url}")

            await page.goto(direct_url, wait_until="domcontentloaded", timeout=self.PAGE_TIMEOUT)

            # iframe이 있으면 iframe 안으로 진입
            content_frame = page
            iframe = page.frame("mainFrame")
            if iframe:
                content_frame = iframe
                await content_frame.wait_for_load_state("domcontentloaded", timeout=self.IFRAME_TIMEOUT)

            # 본문 영역 로드 대기 (여러 셀렉터 시도)
            content_selectors = [
                "div.se-main-container",       # 스마트에디터 3 (최신)
                "div.__se_component_area",      # 스마트에디터 2
                "div#postViewArea",             # 구버전
                "div.post-view",                # 또 다른 구버전
                "div#post-view",
            ]

            content_el = None
            for sel in content_selectors:
                try:
                    await content_frame.wait_for_selector(sel, timeout=self.SELECTOR_TIMEOUT)
                    content_el = await content_frame.query_selector(sel)
                    if content_el:
                        break
                except Exception:
                    continue

            if not content_el:
                logger.warning("[NaverBlog] 알려진 본문 셀렉터를 찾지 못함, body에서 시도")
                content_el = await content_frame.query_selector("body")

            title = await self._extract_title(content_frame)
            content_text = ""
            if content_el:
                content_text = await self._extract_text(content_el)
            images = await self._extract_images(content_frame, content_el)
            date = await self._extract_date(content_frame)
            author = await self._extract_author(content_frame, url)

            return {
                "success": True,
                "title": title,
                "content": content_text,
                "images": images,
                "date": date,
                "author": author,
                "url": url,
            }

        finally:
            await page.close()
            await context.close()

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
            # RSS 2.0 형식: channel > item
            channel = root.find("channel")
            if channel is None:
                return []

            posts = []
            for item in channel.findall("item")[:max_posts]:
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                pub_date = item.findtext("pubDate", "").strip()
                if title and link:
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
        context, page = await self._create_context(block_resources=True)

        try:
            # PostList 페이지로 접속
            list_url = f"https://blog.naver.com/PostList.naver?blogId={blog_id}&categoryNo=0&from=postList"
            logger.info(f"[NaverBlog] 블로그 홈 접속: {list_url}")

            try:
                await page.goto(list_url, wait_until="domcontentloaded", timeout=self.PAGE_TIMEOUT)
            except Exception as e:
                logger.warning(f"[NaverBlog] PostList 로딩 실패, 블로그 홈으로 재시도: {e}")
                # PostList 실패 시 블로그 홈으로 직접 접속
                home_url = f"https://blog.naver.com/{blog_id}"
                await page.goto(home_url, wait_until="domcontentloaded", timeout=self.PAGE_TIMEOUT)

            # iframe 진입
            content_frame = page
            iframe = page.frame("mainFrame")
            if iframe:
                content_frame = iframe
                try:
                    await content_frame.wait_for_load_state("domcontentloaded", timeout=self.IFRAME_TIMEOUT)
                except Exception as e:
                    logger.warning(f"[NaverBlog] iframe 로드 대기 타임아웃, 계속 진행: {e}")

            # 글 목록에서 포스트 링크 추출
            posts = []

            # 방법 1: CSS 셀렉터로 추출
            post_selectors = [
                "a.pcol2",                          # 제목 링크 (리스트뷰)
                "span.ell a",                        # 제목 링크 (간략뷰)
                "a.link__iGhdOl",                    # 최신 스킨
                "div.post-item a",                   # 카드형
                "table.board-list a",                # 테이블형
                ".blog2_post a.sp_blog2",            # 블로그2 스킨
                "div.area_list_title a",             # 리스트 타이틀
                "div.wrap_postlist a.url",            # 포스트리스트
                "div.blog2_series a",                # 시리즈형
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
                    # blog.naver.com/블로그ID/글번호 패턴
                    matches = re.findall(
                        r'href="(https?://blog\.naver\.com/' + re.escape(blog_id) + r'/(\d+))"',
                        html
                    )
                    seen = set()
                    for full_url, post_no in matches:
                        if full_url not in seen:
                            seen.add(full_url)
                            posts.append({"title": f"글 #{post_no}", "url": full_url})
                    # PostView.naver 패턴도 시도
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
                        return text
            except Exception:
                continue

        # 페이지 타이틀에서 추출 시도
        try:
            page_title = await frame.title() if hasattr(frame, 'title') else ""
            if page_title:
                return re.sub(r"\s*[:\-]\s*네이버\s*블로그.*$", "", page_title).strip()
        except Exception:
            pass

        return "(제목 없음)"

    async def _extract_text(self, element) -> str:
        """본문 텍스트 추출 — HTML 태그 제거하고 깔끔하게"""
        try:
            text = await element.inner_text()
            lines = [line.strip() for line in text.split("\n")]
            lines = [line for line in lines if line]
            return "\n".join(lines)
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
                src = await img.get_attribute("data-lazy-src")
                if not src:
                    src = await img.get_attribute("src")
                if not src:
                    continue

                if any(skip in src for skip in [
                    "static.nid.naver", "ssl.pstatic.net/static",
                    "blogpfthumb", "favicon", "btn_", "ico_",
                    "widget", "banner", "ad_",
                ]):
                    continue

                if "pstatic.net" in src or "blogpfthumb" not in src:
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

    async def _extract_date(self, frame) -> str:
        """작성일 추출"""
        date_selectors = [
            "span.se_publishDate",
            "span.date",
            "p.date",
            "span.blog_date",
            "span.se_date",
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

    def format_for_slack(self, result: dict) -> str:
        """스크래핑 결과를 슬랙 메시지로 포맷팅"""
        if not result.get("success"):
            error = result.get("error", "알 수 없는 오류")
            # 사용자 친화적 에러 메시지
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
