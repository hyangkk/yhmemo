import logging
import re
from datetime import date
from typing import List, Optional
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup

from models import Grant

logger = logging.getLogger(__name__)

KSTARTUP_BASE_URL = "https://www.k-startup.go.kr"
KSTARTUP_LIST_URL = f"{KSTARTUP_BASE_URL}/web/contents/bizpbanc-ongoing.do"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

STAGE_KEYWORDS = {
    "예비창업": ["예비창업", "예비"],
    "초기창업": ["초기창업", "초기", "창업 3년", "창업3년"],
    "도약기": ["도약", "창업 7년", "창업7년"],
    "성장기": ["성장", "스케일업", "scale-up"],
}

INDUSTRY_KEYWORDS = [
    "IT", "소프트웨어", "바이오", "헬스케어", "제조", "유통", "물류",
    "농업", "식품", "문화", "콘텐츠", "교육", "환경", "에너지", "핀테크",
    "AI", "인공지능", "빅데이터", "블록체인", "IoT", "로봇",
]


def _parse_amount(text: str) -> Optional[int]:
    text = text.replace(",", "").replace(" ", "")
    match = re.search(r"(\d+)억", text)
    if match:
        return int(match.group(1)) * 10000
    match = re.search(r"(\d+)만", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def _parse_date(text: str) -> Optional[date]:
    text = text.strip()
    match = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    return None


def _extract_stages(text: str) -> List[str]:
    stages = []
    for stage, keywords in STAGE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            stages.append(stage)
    return stages or ["전체"]


def _extract_industries(text: str) -> List[str]:
    return [kw for kw in INDUSTRY_KEYWORDS if kw in text]


def _parse_grant_item(item: BeautifulSoup, base_url: str) -> Optional[Grant]:
    try:
        title_el = item.select_one(".biz-name, .tit, h3, h4, .subject")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)

        org_el = item.select_one(".agency, .org, .organization, .dept")
        organization = org_el.get_text(strip=True) if org_el else "K-Startup"

        desc_el = item.select_one(".biz-desc, .desc, .summary, p")
        description = desc_el.get_text(strip=True) if desc_el else title

        amount_el = item.select_one(".amount, .fund, .money")
        max_amount = _parse_amount(amount_el.get_text()) if amount_el else None

        deadline_el = item.select_one(".deadline, .end-date, .period")
        deadline = _parse_date(deadline_el.get_text()) if deadline_el else None

        link_el = item.select_one("a[href]")
        url = None
        if link_el:
            href = link_el.get("href", "")
            url = href if href.startswith("http") else f"{base_url}{href}"

        full_text = item.get_text()
        target_stage = _extract_stages(full_text)
        target_industry = _extract_industries(full_text)

        return Grant(
            id=str(uuid4()),
            title=title,
            organization=organization,
            category="창업지원",
            description=description,
            max_amount=max_amount,
            deadline=deadline,
            target_stage=target_stage,
            target_industry=target_industry,
            url=url,
        )
    except Exception as e:
        logger.warning(f"항목 파싱 실패: {e}")
        return None


def crawl_kstartup(pages: int = 3) -> List[Grant]:
    grants: List[Grant] = []

    with httpx.Client(headers=HEADERS, timeout=30, follow_redirects=True) as client:
        for page in range(1, pages + 1):
            try:
                params = {"pageIndex": page, "pbancSttus": "ing"}
                resp = client.get(KSTARTUP_LIST_URL, params=params)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                logger.error(f"페이지 {page} 요청 실패: {e}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select(
                ".biz-list li, .list-type li, .business-list .item, "
                "table tbody tr, .card-list .card"
            )

            if not items:
                logger.warning(f"페이지 {page}: 항목을 찾지 못했습니다.")
                break

            for item in items:
                grant = _parse_grant_item(item, KSTARTUP_BASE_URL)
                if grant:
                    grants.append(grant)

            logger.info(f"페이지 {page} 완료: {len(grants)}건 누적")

    logger.info(f"크롤링 완료: 총 {len(grants)}건")
    return grants


def get_sample_grants() -> List[Grant]:
    """Supabase 미연결 시 또는 테스트용 샘플 데이터"""
    return [
        Grant(
            id="sample-1",
            title="2024년 초기창업패키지",
            organization="중소벤처기업부",
            category="창업지원",
            description="창업 3년 이내 초기창업자를 위한 사업화 자금 지원",
            max_amount=10000,
            deadline=date(2024, 12, 31),
            target_stage=["초기창업"],
            target_industry=["IT", "소프트웨어", "AI"],
            url="https://www.k-startup.go.kr",
        ),
        Grant(
            id="sample-2",
            title="청년창업사관학교",
            organization="중소벤처기업진흥공단",
            category="교육/보육",
            description="만 39세 이하 청년창업자 대상 창업 교육 및 사업화 지원",
            max_amount=5000,
            deadline=date(2024, 11, 30),
            target_stage=["예비창업", "초기창업"],
            target_industry=["전체"],
            url="https://www.k-startup.go.kr",
        ),
        Grant(
            id="sample-3",
            title="스마트제조혁신 바우처",
            organization="중소벤처기업부",
            category="기술개발",
            description="제조업 중소기업 스마트공장 구축 및 고도화 지원",
            max_amount=30000,
            deadline=date(2024, 10, 31),
            target_stage=["성장기", "도약기"],
            target_industry=["제조", "IoT", "AI"],
            url="https://www.k-startup.go.kr",
        ),
        Grant(
            id="sample-4",
            title="K-바이오 헬스케어 펀드",
            organization="한국벤처투자",
            category="투자",
            description="바이오·헬스케어 분야 유망 스타트업 투자 지원",
            max_amount=100000,
            deadline=date(2024, 9, 30),
            target_stage=["도약기", "성장기"],
            target_industry=["바이오", "헬스케어"],
            url="https://www.k-startup.go.kr",
        ),
        Grant(
            id="sample-5",
            title="예비창업패키지",
            organization="창업진흥원",
            category="창업지원",
            description="혁신적인 아이디어를 보유한 예비창업자의 창업 사업화 지원",
            max_amount=5000,
            deadline=date(2024, 8, 31),
            target_stage=["예비창업"],
            target_industry=["전체"],
            url="https://www.k-startup.go.kr",
        ),
    ]
