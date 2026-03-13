"""
네이버 블로그 스크래퍼 (Naver Blog Scraper)

역할:
- Playwright를 사용하여 네이버 블로그 글을 크롤링
- 블로그 URL을 받아 제목, 본문 텍스트, 이미지 URL 등을 추출
- 슬랙 명령어(!블로그) 및 자연어로 호출 가능

네이버 블로그는 iframe 구조로 되어 있어 일반 HTTP 요청으로는
본문을 가져올 수 없으므로 Playwright(headless 브라우저)를 사용합니다.
"""

import asyncio
import logging
import re
from typing import Optional
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


class NaverBlogScraper:
    """Playwright 기반 네이버 블로그 스크래퍼"""

    # 네이버 블로그 URL 패턴
    BLOG_PATTERNS = [
        r"blog\.naver\.com/([^/\?]+)/(\d+)",        # blog.naver.com/블로그ID/글번호
        r"blog\.naver\.com/PostView\.naver",          # blog.naver.com/PostView.naver?blogId=...
        r"m\.blog\.naver\.com/([^/\?]+)/(\d+)",       # 모바일 버전
    ]

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
            args=["--no-sandbox", "--disable-dev-shm-usage"],
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

    async def scrape(self, url: str) -> dict:
        """
        네이버 블로그 글을 스크래핑합니다.

        Args:
            url: 네이버 블로그 글 URL

        Returns:
            {
                "success": bool,
                "title": str,
                "content": str,        # 본문 텍스트
                "images": list[str],   # 이미지 URL 목록
                "date": str,           # 작성일
                "author": str,         # 작성자
                "url": str,            # 원본 URL
                "error": str           # 실패 시 에러 메시지
            }
        """
        url = self._normalize_url(url)

        if not self.is_naver_blog_url(url):
            return {"success": False, "error": "네이버 블로그 URL이 아닙니다.", "url": url}

        try:
            await self._ensure_browser()
            return await self._scrape_blog_post(url)
        except Exception as e:
            logger.error(f"[NaverBlog] 스크래핑 실패: {e}", exc_info=True)
            return {"success": False, "error": str(e), "url": url}

    async def _scrape_blog_post(self, url: str) -> dict:
        """실제 블로그 글 스크래핑"""
        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = await context.new_page()

        try:
            # 네이버 블로그는 iframe 안에 본문이 있음
            # PostView 형태의 URL로 직접 접근하면 iframe 없이 볼 수 있음
            direct_url = self._to_postview_url(url)
            logger.info(f"[NaverBlog] 접속 중: {direct_url}")

            await page.goto(direct_url, wait_until="domcontentloaded", timeout=30000)

            # iframe이 있으면 iframe 안으로 진입
            content_frame = page
            iframe = page.frame("mainFrame")
            if iframe:
                content_frame = iframe
                # iframe 로드 대기
                await content_frame.wait_for_load_state("domcontentloaded", timeout=15000)

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
                    await content_frame.wait_for_selector(sel, timeout=5000)
                    content_el = await content_frame.query_selector(sel)
                    if content_el:
                        break
                except Exception:
                    continue

            if not content_el:
                # 마지막 시도: body 전체에서 추출
                logger.warning("[NaverBlog] 알려진 본문 셀렉터를 찾지 못함, body에서 시도")
                content_el = await content_frame.query_selector("body")

            # 제목 추출
            title = await self._extract_title(content_frame)

            # 본문 텍스트 추출
            content_text = ""
            if content_el:
                content_text = await self._extract_text(content_el)

            # 이미지 URL 추출
            images = await self._extract_images(content_frame, content_el)

            # 작성일 추출
            date = await self._extract_date(content_frame)

            # 작성자 추출
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
                # " : 네이버 블로그" 제거
                return re.sub(r"\s*[:\-]\s*네이버\s*블로그.*$", "", page_title).strip()
        except Exception:
            pass

        return "(제목 없음)"

    async def _extract_text(self, element) -> str:
        """본문 텍스트 추출 — HTML 태그 제거하고 깔끔하게"""
        try:
            text = await element.inner_text()
            # 불필요한 공백/줄바꿈 정리
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
            # 본문 내 이미지 추출
            target = content_el or frame
            img_elements = await target.query_selector_all("img")

            for img in img_elements:
                src = await img.get_attribute("data-lazy-src")  # 지연 로딩 이미지
                if not src:
                    src = await img.get_attribute("src")
                if not src:
                    continue

                # 네이버 블로그 본문 이미지만 필터링 (아이콘/UI 이미지 제외)
                if any(skip in src for skip in [
                    "static.nid.naver", "ssl.pstatic.net/static",
                    "blogpfthumb", "favicon", "btn_", "ico_",
                    "widget", "banner", "ad_",
                ]):
                    continue

                # postfiles, blogfiles 등 블로그 이미지 URL
                if "pstatic.net" in src or "blogpfthumb" not in src:
                    if src.startswith("//"):
                        src = "https:" + src
                    if src.startswith("http"):
                        images.append(src)

        except Exception as e:
            logger.warning(f"[NaverBlog] 이미지 추출 실패: {e}")

        # 중복 제거 (순서 유지)
        seen = set()
        unique_images = []
        for img in images:
            if img not in seen:
                seen.add(img)
                unique_images.append(img)

        return unique_images[:20]  # 최대 20개

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
        # URL에서 블로그 ID 추출
        m = re.search(r"blog\.naver\.com/([^/\?]+)", url)
        if m:
            return m.group(1)

        # 쿼리 파라미터에서 추출
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
            await asyncio.sleep(1)  # 요청 간 1초 대기 (차단 방지)
        return results

    def format_for_slack(self, result: dict) -> str:
        """스크래핑 결과를 슬랙 메시지로 포맷팅"""
        if not result.get("success"):
            return f":x: 스크래핑 실패: {result.get('error', '알 수 없는 오류')}\nURL: {result.get('url', '')}"

        parts = []
        parts.append(f":notebook: *{result['title']}*")

        if result.get("author"):
            parts.append(f":bust_in_silhouette: 작성자: {result['author']}")
        if result.get("date"):
            parts.append(f":calendar: {result['date']}")

        parts.append(f":link: {result['url']}")
        parts.append("")

        # 본문 (최대 2000자)
        content = result.get("content", "")
        if len(content) > 2000:
            content = content[:2000] + "...\n_(본문이 길어서 일부만 표시)_"
        if content:
            parts.append(content)

        # 이미지 개수
        images = result.get("images", [])
        if images:
            parts.append(f"\n:frame_with_picture: 이미지 {len(images)}장")
            # 첫 3개 이미지 URL 표시
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
