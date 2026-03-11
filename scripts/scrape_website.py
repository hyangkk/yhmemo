#!/usr/bin/env python3
"""
웹사이트 게시판 스크래핑 스크립트 (Playwright 기반)

WAF/봇 차단이 강한 사이트도 실제 브라우저를 제어하여 접근합니다.
로컬 환경에서 실행해야 합니다.

사용법:
    # 설치 (최초 1회)
    pip install playwright
    playwright install chromium

    # 실행
    python scripts/scrape_website.py "https://www.yicare.or.kr/main/main.php?categoryid=25&menuid=01&groupid=00"

    # 최신 게시물 N개 가져오기
    python scripts/scrape_website.py "URL" --count 3

    # 상세 내용까지 가져오기
    python scripts/scrape_website.py "URL" --detail
"""

import asyncio
import argparse
import json
import re
import sys
from datetime import datetime
from playwright.async_api import async_playwright


async def scrape_board(url: str, count: int = 1, detail: bool = True, headless: bool = True):
    """게시판 페이지에서 게시물 목록과 내용을 스크래핑합니다."""

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Sec-CH-UA": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                "Sec-CH-UA-Mobile": "?0",
                "Sec-CH-UA-Platform": '"macOS"',
            },
        )

        # webdriver 감지 우회
        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = {runtime: {}};
        """)

        # 1단계: 메인 도메인 먼저 방문 (쿠키 획득)
        from urllib.parse import urlparse
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        print(f"[1/4] 메인 페이지 방문: {base_url}")
        try:
            await page.goto(base_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(1000)
        except Exception as e:
            print(f"  메인 페이지 접근 실패 (무시하고 계속): {e}")

        # 2단계: 게시판 목록 페이지 접근
        print(f"[2/4] 게시판 목록 접근: {url}")
        response = await page.goto(url, wait_until="networkidle", timeout=30000)
        print(f"  응답 코드: {response.status if response else 'N/A'}")

        title = await page.title()
        print(f"  페이지 제목: {title}")

        if response and response.status >= 400:
            body = await page.inner_text("body")
            print(f"  오류: {body[:200]}")
            await browser.close()
            return results

        # 3단계: 게시물 링크 수집
        print(f"[3/4] 게시물 목록 파싱...")
        board_links = await _find_board_links(page)

        if not board_links:
            # 테이블 기반 게시판 시도
            board_links = await _find_table_board_links(page)

        if not board_links:
            # onclick 기반 게시판 시도
            board_links = await _find_onclick_board_links(page)

        if not board_links:
            print("  게시물 링크를 찾을 수 없습니다.")
            body_text = await page.inner_text("body")
            print(f"\n  === 페이지 전체 텍스트 ===\n{body_text[:3000]}")
            await browser.close()
            return results

        print(f"  발견된 게시물: {len(board_links)}개")
        for i, item in enumerate(board_links[:count + 2]):
            print(f"    {i+1}. {item['title'][:60]} ({item.get('date', 'N/A')})")

        # 4단계: 상세 내용 가져오기
        target_links = board_links[:count]
        print(f"[4/4] 상세 내용 가져오기 ({len(target_links)}개)...")

        for i, item in enumerate(target_links):
            print(f"\n  --- [{i+1}/{len(target_links)}] {item['title'][:60]} ---")

            if detail and item.get("href"):
                try:
                    detail_content = await _get_detail(page, item, base_url)
                    item["content"] = detail_content
                    print(f"  내용 길이: {len(detail_content)}자")

                    # 목록 페이지로 복귀
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await page.wait_for_timeout(500)
                except Exception as e:
                    print(f"  상세 내용 가져오기 실패: {e}")
                    item["content"] = ""

            results.append(item)

        await browser.close()

    return results


async def _find_board_links(page) -> list:
    """a[href] 패턴으로 게시물 링크를 찾습니다."""
    links = await page.query_selector_all("a[href]")
    board_links = []

    # 게시판 URL 패턴
    patterns = ["view", "read", "idx=", "no=", "seq=", "num=", "sno=", "bbs_id=",
                "board_view", "articleView", "bbsView"]

    for link in links:
        href = await link.get_attribute("href") or ""
        text = (await link.inner_text()).strip()

        if not text or len(text) < 2:
            continue

        href_lower = href.lower()
        if any(p in href_lower for p in patterns):
            # 날짜 추출 시도 (부모 tr에서)
            date = ""
            try:
                row = await link.evaluate_handle("el => el.closest('tr') || el.closest('li') || el.parentElement")
                row_text = await row.evaluate("el => el.textContent")
                date_match = re.search(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})', row_text)
                if date_match:
                    date = date_match.group(1)
            except:
                pass

            board_links.append({
                "title": text,
                "href": href,
                "date": date,
            })

    return board_links


async def _find_table_board_links(page) -> list:
    """테이블 기반 게시판에서 게시물을 찾습니다."""
    board_links = []
    rows = await page.query_selector_all("table tbody tr, table tr")

    for row in rows:
        cells = await row.query_selector_all("td")
        if len(cells) < 2:
            continue

        # 제목 셀 찾기 (보통 2번째~3번째 td에 링크)
        for cell in cells:
            link = await cell.query_selector("a")
            if link:
                text = (await link.inner_text()).strip()
                href = await link.get_attribute("href") or ""

                if text and len(text) > 2:
                    # 날짜 추출
                    row_text = await row.inner_text()
                    date = ""
                    date_match = re.search(r'(\d{4}[-./]\d{1,2}[-./]\d{1,2})', row_text)
                    if date_match:
                        date = date_match.group(1)

                    board_links.append({
                        "title": text,
                        "href": href,
                        "date": date,
                    })
                    break

    return board_links


async def _find_onclick_board_links(page) -> list:
    """onclick 이벤트 기반 게시판에서 게시물을 찾습니다."""
    board_links = []
    elements = await page.query_selector_all("[onclick]")

    for el in elements:
        onclick = await el.get_attribute("onclick") or ""
        text = (await el.inner_text()).strip()

        if text and len(text) > 2 and ("view" in onclick.lower() or "read" in onclick.lower()):
            board_links.append({
                "title": text,
                "href": "",
                "onclick": onclick,
                "date": "",
            })

    return board_links


async def _get_detail(page, item: dict, base_url: str) -> str:
    """게시물 상세 페이지의 내용을 가져옵니다."""
    href = item["href"]

    if not href.startswith("http"):
        if href.startswith("/"):
            href = base_url + href
        elif href.startswith("./"):
            current_url = page.url
            href = current_url.rsplit("/", 1)[0] + "/" + href[2:]
        else:
            current_url = page.url
            href = current_url.rsplit("/", 1)[0] + "/" + href

    await page.goto(href, wait_until="networkidle", timeout=30000)

    # 본문 영역 찾기 (일반적인 게시판 패턴)
    content_selectors = [
        ".board_view_content", ".view_content", ".board_content",
        ".bbs_content", ".view_cont", ".article_content",
        ".content_view", "#board_content", "#content",
        ".board-view-content", ".post-content", ".entry-content",
        "article", ".view_area", ".board_view",
    ]

    for selector in content_selectors:
        el = await page.query_selector(selector)
        if el:
            content = await el.inner_text()
            if content.strip():
                return content.strip()

    # 본문 영역을 못 찾으면 body 전체 텍스트
    body_text = await page.inner_text("body")
    return body_text.strip()


def print_results(results: list):
    """결과를 보기 좋게 출력합니다."""
    print("\n" + "=" * 70)
    print(f" 스크래핑 결과 ({len(results)}건)")
    print("=" * 70)

    for i, item in enumerate(results):
        print(f"\n{'─' * 70}")
        print(f"  제목: {item['title']}")
        print(f"  날짜: {item.get('date', 'N/A')}")
        print(f"  URL:  {item.get('href', 'N/A')}")
        if item.get("content"):
            print(f"{'─' * 70}")
            print(item["content"][:5000])

    print(f"\n{'=' * 70}")


async def main():
    parser = argparse.ArgumentParser(description="웹사이트 게시판 스크래핑")
    parser.add_argument("url", help="게시판 목록 페이지 URL")
    parser.add_argument("--count", "-c", type=int, default=1, help="가져올 게시물 수 (기본: 1)")
    parser.add_argument("--detail", "-d", action="store_true", default=True, help="상세 내용 가져오기 (기본: True)")
    parser.add_argument("--no-detail", action="store_true", help="상세 내용 생략 (목록만)")
    parser.add_argument("--visible", "-v", action="store_true", help="브라우저 창 표시 (디버깅용)")
    parser.add_argument("--json", "-j", action="store_true", help="JSON 형식으로 출력")

    args = parser.parse_args()

    detail = not args.no_detail
    headless = not args.visible

    results = await scrape_board(args.url, count=args.count, detail=detail, headless=headless)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
