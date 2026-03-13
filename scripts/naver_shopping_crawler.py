#!/usr/bin/env python3
"""
네이버 쇼핑 프로모션 페이지 크롤러
- https://shopping.naver.com/promotion 페이지의 상품 정보를 크롤링
- 상품 이미지, 이름, 가격, 할인률 추출
- 결과를 노션 "에이전트 결과물 DB"에 자동 저장

사용법:
    pip install playwright requests
    python -m playwright install chromium
    python scripts/naver_shopping_crawler.py

환경변수:
    NOTION_API_KEY: 노션 API 키 (없으면 JSON 파일로만 저장)
"""

import asyncio
import json
import re
import sys
import os
from datetime import datetime

# ============================================================
# 1단계: 네이버 쇼핑 프로모션 페이지 크롤링
# ============================================================

async def crawl_naver_promotion():
    """Playwright로 네이버 쇼핑 프로모션 페이지를 크롤링합니다."""
    from playwright.async_api import async_playwright

    products = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )
        page = await context.new_page()

        print("[1/4] 네이버 쇼핑 프로모션 페이지 접속 중...")
        await page.goto(
            "https://shopping.naver.com/promotion",
            wait_until="networkidle",
            timeout=30000,
        )

        # 페이지 로딩 대기 (동적 렌더링)
        await page.wait_for_timeout(3000)

        # 스크롤해서 lazy-load 상품들 로드
        print("[2/4] 페이지 스크롤하여 상품 로딩 중...")
        for _ in range(5):
            await page.evaluate("window.scrollBy(0, 1000)")
            await page.wait_for_timeout(1000)

        print("[3/4] 상품 정보 추출 중...")

        # 방법 1: 일반적인 상품 카드 셀렉터들 시도
        selectors = [
            # 네이버 쇼핑 공통 상품 카드 패턴
            "[class*='product']",
            "[class*='Product']",
            "[class*='item']",
            "[class*='Item']",
            "[class*='goods']",
            "[class*='card']",
            "[class*='deal']",
            "[class*='promotion']",
        ]

        # 페이지 전체 HTML에서 상품 정보 추출
        content = await page.content()

        # __NEXT_DATA__ 또는 JSON 데이터 추출 시도
        next_data_match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            content,
            re.DOTALL,
        )
        if next_data_match:
            try:
                data = json.loads(next_data_match.group(1))
                products = extract_from_next_data(data)
                if products:
                    print(f"  → __NEXT_DATA__에서 {len(products)}개 상품 추출 완료")
            except json.JSONDecodeError:
                pass

        # __NEXT_DATA__에서 못 찾으면 DOM에서 직접 추출
        if not products:
            products = await extract_from_dom(page)

        # DOM에서도 못 찾으면 네트워크 요청에서 API 응답 캡처 시도
        if not products:
            print("  → DOM 추출 실패, API 응답 캡처 시도...")
            products = await extract_from_api(page, context)

        await browser.close()

    print(f"[4/4] 총 {len(products)}개 상품 정보 추출 완료")
    return products


def extract_from_next_data(data):
    """Next.js __NEXT_DATA__에서 상품 정보를 추출합니다."""
    products = []

    def search_products(obj, depth=0):
        if depth > 10:
            return
        if isinstance(obj, dict):
            # 상품 정보가 있을 수 있는 키 패턴
            has_name = any(
                k in obj
                for k in [
                    "productName", "name", "title", "itemName",
                    "goodsName", "productTitle",
                ]
            )
            has_price = any(
                k in obj
                for k in [
                    "price", "salePrice", "discountPrice",
                    "finalPrice", "sellingPrice",
                ]
            )
            if has_name and has_price:
                product = parse_product_dict(obj)
                if product:
                    products.append(product)
            else:
                for v in obj.values():
                    search_products(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                search_products(item, depth + 1)

    search_products(data)
    return products


def parse_product_dict(obj):
    """딕셔너리에서 상품 정보를 파싱합니다."""
    # 이름 추출
    name = None
    for key in [
        "productName", "name", "title", "itemName",
        "goodsName", "productTitle",
    ]:
        if key in obj and isinstance(obj[key], str) and len(obj[key]) > 1:
            name = obj[key]
            break

    if not name:
        return None

    # 가격 추출
    price = None
    original_price = None
    for key in [
        "salePrice", "discountPrice", "finalPrice",
        "sellingPrice", "price",
    ]:
        if key in obj:
            val = obj[key]
            if isinstance(val, (int, float)) and val > 0:
                price = int(val)
                break
            elif isinstance(val, str) and val.isdigit():
                price = int(val)
                break

    for key in [
        "originalPrice", "normalPrice", "listPrice",
        "basePrice", "price",
    ]:
        if key in obj and key not in [
            "salePrice", "discountPrice", "finalPrice", "sellingPrice",
        ]:
            val = obj[key]
            if isinstance(val, (int, float)) and val > 0:
                original_price = int(val)
                break

    if not price:
        return None

    # 할인률 추출
    discount_rate = None
    for key in [
        "discountRate", "discountPercent", "discountRatio",
        "saleRate", "benefitRate",
    ]:
        if key in obj:
            val = obj[key]
            if isinstance(val, (int, float)):
                discount_rate = int(val)
                break
            elif isinstance(val, str):
                nums = re.findall(r"\d+", val)
                if nums:
                    discount_rate = int(nums[0])
                    break

    # 할인률이 없으면 계산
    if discount_rate is None and original_price and price < original_price:
        discount_rate = round((1 - price / original_price) * 100)

    # 이미지 URL 추출
    image_url = None
    for key in [
        "imageUrl", "image", "thumbnailUrl", "thumbnail",
        "imgUrl", "productImage", "mainImage", "representImage",
    ]:
        if key in obj:
            val = obj[key]
            if isinstance(val, str) and (
                val.startswith("http") or val.startswith("//")
            ):
                image_url = val if val.startswith("http") else f"https:{val}"
                break
            elif isinstance(val, dict):
                for sub_key in ["url", "src", "path"]:
                    if sub_key in val and isinstance(val[sub_key], str):
                        url = val[sub_key]
                        image_url = url if url.startswith("http") else f"https:{url}"
                        break

    return {
        "name": name,
        "price": price,
        "original_price": original_price,
        "discount_rate": discount_rate,
        "image_url": image_url,
    }


async def extract_from_dom(page):
    """페이지 DOM에서 상품 정보를 직접 추출합니다."""
    products = []

    # 다양한 셀렉터 조합 시도
    items = await page.evaluate("""() => {
        const results = [];

        // 이미지 + 가격 정보가 함께 있는 요소 찾기
        const allElements = document.querySelectorAll(
            '[class*="product"], [class*="Product"], [class*="item"], ' +
            '[class*="Item"], [class*="deal"], [class*="Deal"], ' +
            '[class*="goods"], [class*="card"], [class*="Card"]'
        );

        for (const el of allElements) {
            const img = el.querySelector('img');
            const priceEls = el.querySelectorAll(
                '[class*="price"], [class*="Price"], [class*="cost"], [class*="won"]'
            );
            const nameEl = el.querySelector(
                '[class*="name"], [class*="Name"], [class*="title"], ' +
                '[class*="Title"], [class*="text"], [class*="desc"]'
            );
            const discountEl = el.querySelector(
                '[class*="discount"], [class*="Discount"], [class*="rate"], ' +
                '[class*="Rate"], [class*="percent"], [class*="sale"]'
            );

            if (img && (priceEls.length > 0 || nameEl)) {
                const name = nameEl ? nameEl.textContent.trim() : '';
                const imgSrc = img.src || img.dataset.src || img.getAttribute('data-lazy-src') || '';

                let priceText = '';
                for (const p of priceEls) {
                    priceText += ' ' + p.textContent.trim();
                }

                const discountText = discountEl ? discountEl.textContent.trim() : '';

                if (name && name.length > 1) {
                    results.push({
                        name: name.substring(0, 200),
                        image_url: imgSrc,
                        price_text: priceText.trim(),
                        discount_text: discountText,
                    });
                }
            }
        }

        return results;
    }""")

    for item in items:
        # 가격 파싱
        price_nums = re.findall(r"[\d,]+", item.get("price_text", ""))
        prices = [int(n.replace(",", "")) for n in price_nums if len(n.replace(",", "")) >= 3]

        price = min(prices) if prices else None
        original_price = max(prices) if len(prices) > 1 else None

        # 할인률 파싱
        discount_rate = None
        disc_text = item.get("discount_text", "")
        disc_nums = re.findall(r"(\d+)\s*%", disc_text)
        if disc_nums:
            discount_rate = int(disc_nums[0])
        elif original_price and price and price < original_price:
            discount_rate = round((1 - price / original_price) * 100)

        if item.get("name") and price:
            products.append({
                "name": item["name"],
                "price": price,
                "original_price": original_price,
                "discount_rate": discount_rate,
                "image_url": item.get("image_url"),
            })

    # 중복 제거
    seen = set()
    unique = []
    for p in products:
        key = (p["name"], p["price"])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return unique


async def extract_from_api(page, context):
    """페이지 리로드 시 API 응답을 캡처하여 상품 정보를 추출합니다."""
    products = []
    api_responses = []

    async def handle_response(response):
        url = response.url
        if any(
            kw in url
            for kw in ["product", "item", "promotion", "deal", "goods", "api"]
        ):
            try:
                body = await response.json()
                api_responses.append({"url": url, "data": body})
            except Exception:
                pass

    page.on("response", handle_response)

    await page.reload(wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(3000)

    for resp in api_responses:
        found = extract_from_next_data(resp["data"])
        products.extend(found)

    # 중복 제거
    seen = set()
    unique = []
    for p in products:
        key = (p["name"], p["price"])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return unique


# ============================================================
# 2단계: 노션에 결과 저장
# ============================================================

def save_to_notion(products, api_key):
    """크롤링 결과를 노션 에이전트 결과물 DB에 저장합니다."""
    import requests

    # 에이전트 결과물 DB의 data_source_id
    data_source_id = "1e21114e-6491-814f-9771-000b489f49c7"

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 상품 테이블 마크다운 생성
    content_lines = [
        f"크롤링 일시: {now}",
        f"총 {len(products)}개 상품",
        "",
        "---",
        "",
    ]

    for i, p in enumerate(products, 1):
        name = p["name"]
        price = f'{p["price"]:,}원' if p["price"] else "가격 미확인"
        original = f'{p["original_price"]:,}원' if p.get("original_price") else "-"
        discount = f'{p["discount_rate"]}%' if p.get("discount_rate") else "-"
        img_url = p.get("image_url", "")

        content_lines.append(f"### {i}. {name}")
        content_lines.append("")
        if img_url:
            content_lines.append(f"![상품 이미지]({img_url})")
            content_lines.append("")
        content_lines.append(f"- **할인가**: {price}")
        content_lines.append(f"- **원래 가격**: {original}")
        content_lines.append(f"- **할인률**: {discount}")
        content_lines.append("")
        content_lines.append("---")
        content_lines.append("")

    content = "\n".join(content_lines)

    # 노션 페이지 생성 (Notion API 직접 호출)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

    # 데이터베이스에 페이지 추가
    page_data = {
        "parent": {"database_id": "1e21114e6491810189b67ca52d78a8fb0"},
        "properties": {
            "이름": {
                "title": [
                    {
                        "text": {
                            "content": f"네이버 쇼핑 프로모션 크롤링 ({now})"
                        }
                    }
                ]
            },
            "상태": {
                "status": {"name": "AI 정리 완료"}
            },
        },
    }

    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=headers,
        json=page_data,
        timeout=15,
    )

    if resp.status_code != 200:
        print(f"노션 페이지 생성 실패: {resp.status_code} {resp.text}")
        return None

    page_id = resp.json()["id"]
    print(f"노션 페이지 생성 완료: {page_id}")

    # 페이지 콘텐츠 추가 (블록 단위)
    blocks = build_notion_blocks(products, now)

    # 100개씩 나눠서 추가 (API 제한)
    for i in range(0, len(blocks), 100):
        chunk = blocks[i : i + 100]
        resp = requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            json={"children": chunk},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"블록 추가 실패 ({i}~): {resp.status_code}")

    return page_id


def build_notion_blocks(products, now):
    """상품 정보를 노션 블록으로 변환합니다."""
    blocks = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"크롤링 일시: {now} | 총 {len(products)}개 상품"
                        },
                    }
                ],
                "icon": {"type": "emoji", "emoji": "🛒"},
            },
        },
        {"object": "block", "type": "divider", "divider": {}},
    ]

    # 테이블 블록 생성
    table_rows = []

    # 헤더 행
    header_row = {
        "object": "block",
        "type": "table_row",
        "table_row": {
            "cells": [
                [{"type": "text", "text": {"content": "번호"}}],
                [{"type": "text", "text": {"content": "상품 이미지"}}],
                [{"type": "text", "text": {"content": "상품명"}}],
                [{"type": "text", "text": {"content": "가격"}}],
                [{"type": "text", "text": {"content": "할인률"}}],
            ]
        },
    }
    table_rows.append(header_row)

    # 상품 행
    for i, p in enumerate(products, 1):
        price_text = f'{p["price"]:,}원' if p["price"] else "-"
        if p.get("original_price"):
            price_text = f'{p["price"]:,}원 (정가 {p["original_price"]:,}원)'

        discount_text = f'{p["discount_rate"]}%' if p.get("discount_rate") else "-"

        row = {
            "object": "block",
            "type": "table_row",
            "table_row": {
                "cells": [
                    [{"type": "text", "text": {"content": str(i)}}],
                    [{"type": "text", "text": {"content": p.get("image_url", "-") or "-"}}],
                    [{"type": "text", "text": {"content": p["name"][:100]}}],
                    [{"type": "text", "text": {"content": price_text}}],
                    [{"type": "text", "text": {"content": discount_text}}],
                ]
            },
        }
        table_rows.append(row)

    # 테이블 블록 (최대 100행까지 한 테이블에)
    if table_rows:
        table_block = {
            "object": "block",
            "type": "table",
            "table": {
                "table_width": 5,
                "has_column_header": True,
                "has_row_header": False,
                "children": table_rows[:100],  # 노션 API 제한
            },
        }
        blocks.append(table_block)

    # 100개 초과 시 추가 테이블
    if len(table_rows) > 100:
        remaining = table_rows[100:]
        extra_table = {
            "object": "block",
            "type": "table",
            "table": {
                "table_width": 5,
                "has_column_header": False,
                "has_row_header": False,
                "children": remaining,
            },
        }
        blocks.append(extra_table)

    # 상품별 이미지 섹션 (테이블 아래)
    blocks.append({"object": "block", "type": "divider", "divider": {}})
    blocks.append(
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [
                    {"type": "text", "text": {"content": "상품 이미지 모음"}}
                ]
            },
        }
    )

    for i, p in enumerate(products[:50], 1):  # 이미지는 최대 50개
        img_url = p.get("image_url")
        if img_url:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": f"{i}. {p['name'][:50]}"},
                                "annotations": {"bold": True},
                            }
                        ]
                    },
                }
            )
            blocks.append(
                {
                    "object": "block",
                    "type": "image",
                    "image": {
                        "type": "external",
                        "external": {"url": img_url},
                    },
                }
            )

    return blocks


# ============================================================
# 3단계: 메인 실행
# ============================================================

def save_to_json(products, filepath="naver_promotion_products.json"):
    """크롤링 결과를 JSON 파일로 저장합니다."""
    output = {
        "crawled_at": datetime.now().isoformat(),
        "source": "https://shopping.naver.com/promotion",
        "total_count": len(products),
        "products": products,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"JSON 저장 완료: {filepath}")
    return filepath


async def main():
    print("=" * 60)
    print("네이버 쇼핑 프로모션 크롤러")
    print("=" * 60)

    # 크롤링 실행
    products = await crawl_naver_promotion()

    if not products:
        print("\n⚠️ 상품을 찾지 못했습니다.")
        print("네이버 쇼핑 프로모션 페이지 구조가 변경되었을 수 있습니다.")
        print("브라우저에서 직접 확인 후 셀렉터를 조정해주세요.")
        return

    # JSON 저장
    json_path = save_to_json(products)

    # 상품 요약 출력
    print("\n📋 크롤링 결과 요약:")
    print("-" * 50)
    for i, p in enumerate(products[:10], 1):
        price = f'{p["price"]:,}원' if p["price"] else "?"
        discount = f'({p["discount_rate"]}% 할인)' if p.get("discount_rate") else ""
        print(f"  {i}. {p['name'][:40]} - {price} {discount}")
    if len(products) > 10:
        print(f"  ... 외 {len(products) - 10}개")

    # 노션 저장
    notion_key = os.environ.get("NOTION_API_KEY", "")
    if notion_key:
        print("\n노션에 결과 저장 중...")
        page_id = save_to_notion(products, notion_key)
        if page_id:
            print(f"✅ 노션 저장 완료!")
    else:
        print("\n💡 NOTION_API_KEY 환경변수가 없어 노션 저장을 건너뜁니다.")
        print("   JSON 파일을 참고해주세요.")


if __name__ == "__main__":
    asyncio.run(main())
