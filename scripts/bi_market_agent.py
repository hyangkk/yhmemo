#!/usr/bin/env python3
"""
AI 비즈니스 인텔리전스 시장 모니터링 에이전트 (P1)

- 매일 오전 8시(KST) GitHub Actions에 의해 자동 실행
- 한국 스타트업 투자/시장 뉴스 수집 (RSS 기반)
- Claude AI가 경쟁사 동향·시장 기회·위협 요인 분석
- 핵심 인사이트를 Supabase 저장 + 텔레그램 발송
- 주간 누적 트렌드 요약 자동 생성

Supabase 필요 테이블: bi_market_reports
"""

import os
import re
import sys
import json
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree

import anthropic

KST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# 뉴스 소스 (RSS)
# ---------------------------------------------------------------------------

RSS_SOURCES = [
    {
        "name": "벤처스퀘어",
        "url": "https://www.venturesquare.net/feed",
        "category": "startup",
    },
    {
        "name": "더벨",
        "url": "https://www.thebell.co.kr/free/content/NewsRSSList.asp",
        "category": "investment",
    },
    {
        "name": "IT조선",
        "url": "https://it.chosun.com/site/data/rss/rss.xml",
        "category": "tech",
    },
    {
        "name": "연합뉴스 IT과학",
        "url": "https://www.yna.co.kr/rss/it.xml",
        "category": "tech",
    },
    {
        "name": "전자신문",
        "url": "https://www.etnews.com/rss/allArticle.xml",
        "category": "tech",
    },
]

# 시장 인텔리전스 관심 키워드
BI_KEYWORDS = [
    "AI", "인공지능", "SaaS", "B2B", "투자", "시리즈", "유치",
    "스타트업", "창업", "경쟁", "신규", "출시", "서비스", "데이터",
    "클라우드", "자동화", "분석", "플랫폼", "솔루션",
]


# ---------------------------------------------------------------------------
# Supabase 공통
# ---------------------------------------------------------------------------

def _supabase_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _supabase_get(path: str) -> list:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return []
    req = urllib.request.Request(f"{url}{path}", headers=_supabase_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Supabase GET 실패 ({path}): {e}", file=sys.stderr)
        return []


def _supabase_post(path: str, data: dict) -> bool:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return False
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{url}{path}",
        data=payload,
        headers={**_supabase_headers(), "Prefer": "return=minimal"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as e:
        print(f"Supabase POST 실패 ({e.code}): {e.read().decode()}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 1. RSS 뉴스 수집
# ---------------------------------------------------------------------------

def _fetch_rss(source: dict, max_items: int = 10) -> list:
    """RSS 피드에서 최신 뉴스 수집."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    items = []
    try:
        req = urllib.request.Request(source["url"], headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()

        root = ElementTree.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS 2.0
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            pub_date = item.findtext("pubDate", "").strip()

            if title and link:
                items.append({
                    "title": title,
                    "url": link,
                    "summary": re.sub(r"<[^>]+>", "", desc)[:300],
                    "published": pub_date,
                    "source": source["name"],
                    "category": source["category"],
                })

    except Exception as e:
        print(f"  RSS 수집 실패 ({source['name']}): {e}", file=sys.stderr)

    return items


def collect_news(max_per_source: int = 8) -> list:
    """전체 소스에서 뉴스 수집 후 BI 키워드 필터링."""
    all_news = []
    for source in RSS_SOURCES:
        items = _fetch_rss(source, max_items=max_per_source)
        print(f"  {source['name']}: {len(items)}건 수집")
        all_news.extend(items)

    # 키워드 관련도 점수 계산
    def relevance(item: dict) -> int:
        text = (item["title"] + " " + item["summary"]).lower()
        return sum(1 for kw in BI_KEYWORDS if kw.lower() in text)

    all_news.sort(key=relevance, reverse=True)

    # 상위 30개만 분석 대상
    filtered = [n for n in all_news if relevance(n) > 0][:30]
    print(f"  BI 관련 뉴스: {len(filtered)}건 (전체 {len(all_news)}건 중)")
    return filtered


# ---------------------------------------------------------------------------
# 2. 중복 제거 (오늘 이미 처리된 뉴스)
# ---------------------------------------------------------------------------

def get_today_hashes() -> set:
    """오늘 날짜로 저장된 뉴스 해시 목록 조회."""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    rows = _supabase_get(
        f"/rest/v1/bi_market_reports"
        f"?select=news_hash"
        f"&report_date=eq.{today}"
        f"&report_type=eq.item"
    )
    return {r["news_hash"] for r in rows if r.get("news_hash")}


def _news_hash(item: dict) -> str:
    return hashlib.md5((item["title"] + item["url"]).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 3. Claude AI 시장 분석
# ---------------------------------------------------------------------------

def analyze_market_intelligence(news_items: list, user_context: str = "") -> dict:
    """Claude로 뉴스 묶음을 시장 인텔리전스 관점에서 분석."""
    client = anthropic.Anthropic()

    news_block = "\n\n".join([
        f"[{i+1}] {item['source']} | {item['title']}\n{item['summary']}"
        for i, item in enumerate(news_items[:20])
    ])

    context_section = f"\n\n## 분석 맥락\n{user_context}" if user_context else ""

    prompt = f"""당신은 AI/SaaS B2B 분야 시장 인텔리전스 전문가입니다.
아래 오늘 수집된 뉴스들을 분석하여 비즈니스 인사이트를 도출하세요.{context_section}

## 오늘의 시장 뉴스
{news_block}

## 분석 요청
다음 4가지 관점에서 핵심 인사이트를 추출하세요:

1. **시장 기회** (Market Opportunities): 새로운 비즈니스 기회나 수요
2. **경쟁사 동향** (Competitive Intelligence): 경쟁사/업계 주요 움직임
3. **투자/자금 트렌드** (Funding Trends): 투자 흐름과 주목 분야
4. **위협 및 리스크** (Threats & Risks): 시장 위협 요인이나 주의할 변화

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "opportunities": [
    {{"title": "기회 제목", "detail": "구체적 설명 2-3문장", "action": "권장 액션"}}
  ],
  "competitive": [
    {{"company": "회사/분야명", "movement": "동향 설명", "implication": "우리에게 의미"}}
  ],
  "funding": [
    {{"area": "투자 분야", "trend": "트렌드 설명", "signal": "시장 신호"}}
  ],
  "threats": [
    {{"factor": "위협 요인", "detail": "설명", "response": "대응 방향"}}
  ],
  "headline": "오늘의 핵심 시장 메시지 한 줄",
  "top_action": "오늘 당장 검토해야 할 최우선 액션 아이템"
}}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group())
        return {"headline": text[:200], "opportunities": [], "competitive": [], "funding": [], "threats": [], "top_action": ""}
    except Exception as e:
        print(f"  Claude 분석 오류: {e}", file=sys.stderr)
        return {"headline": f"분석 오류: {e}", "opportunities": [], "competitive": [], "funding": [], "threats": [], "top_action": ""}


# ---------------------------------------------------------------------------
# 4. Supabase 저장
# ---------------------------------------------------------------------------

def save_daily_report(analysis: dict, news_count: int) -> bool:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    return _supabase_post(
        "/rest/v1/bi_market_reports",
        {
            "report_date": today,
            "report_type": "daily_summary",
            "headline": analysis.get("headline", ""),
            "top_action": analysis.get("top_action", ""),
            "opportunities": json.dumps(analysis.get("opportunities", []), ensure_ascii=False),
            "competitive": json.dumps(analysis.get("competitive", []), ensure_ascii=False),
            "funding": json.dumps(analysis.get("funding", []), ensure_ascii=False),
            "threats": json.dumps(analysis.get("threats", []), ensure_ascii=False),
            "news_count": news_count,
            "created_at": datetime.now(KST).isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# 5. 텔레그램 리포트 발송
# ---------------------------------------------------------------------------

def send_telegram_report(token: str, chat_id: str, analysis: dict, news_count: int) -> bool:
    today = datetime.now(KST).strftime("%m월 %d일")
    headline = analysis.get("headline", "시장 분석 완료")
    top_action = analysis.get("top_action", "")

    opportunities = analysis.get("opportunities", [])[:3]
    competitive = analysis.get("competitive", [])[:2]
    funding = analysis.get("funding", [])[:2]
    threats = analysis.get("threats", [])[:2]

    opp_text = ""
    for o in opportunities:
        opp_text += f"  • <b>{o.get('title', '')}</b>\n    {o.get('detail', '')[:100]}\n    → {o.get('action', '')[:80]}\n"

    comp_text = ""
    for c in competitive:
        comp_text += f"  • <b>{c.get('company', '')}</b>: {c.get('movement', '')[:100]}\n"

    fund_text = ""
    for f in funding:
        fund_text += f"  • <b>{f.get('area', '')}</b>: {f.get('trend', '')[:100]}\n"

    threat_text = ""
    for t in threats:
        threat_text += f"  • {t.get('factor', '')}: {t.get('detail', '')[:80]}\n"

    msg = (
        f"<b>📊 AI BI 시장 인텔리전스 리포트</b> — {today}\n"
        f"분석 뉴스: {news_count}건\n\n"
        f"<b>💡 오늘의 핵심</b>\n{headline}\n\n"
    )

    if opp_text:
        msg += f"<b>🚀 시장 기회</b>\n{opp_text}\n"

    if comp_text:
        msg += f"<b>🔍 경쟁사 동향</b>\n{comp_text}\n"

    if fund_text:
        msg += f"<b>💰 투자 트렌드</b>\n{fund_text}\n"

    if threat_text:
        msg += f"<b>⚠️ 위협 요인</b>\n{threat_text}\n"

    if top_action:
        msg += f"<b>✅ 오늘의 액션</b>\n{top_action}"

    payload = json.dumps({
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                print("  텔레그램 리포트 발송 완료")
                return True
            print(f"  텔레그램 실패: {result}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"  텔레그램 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 6. 주간 트렌드 요약 (월요일 실행)
# ---------------------------------------------------------------------------

def generate_weekly_trend_summary(token: str, chat_id: str) -> None:
    """지난 7일 리포트를 취합하여 주간 트렌드 요약 생성."""
    today = datetime.now(KST)
    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    rows = _supabase_get(
        f"/rest/v1/bi_market_reports"
        f"?select=headline,top_action,opportunities,created_at"
        f"&report_type=eq.daily_summary"
        f"&report_date=gte.{week_ago}"
        f"&order=created_at.desc"
    )

    if len(rows) < 3:
        print("  주간 요약: 데이터 부족 (3일 미만)")
        return

    client = anthropic.Anthropic()
    summaries = "\n".join([
        f"- {r.get('headline', '')} | 액션: {r.get('top_action', '')[:60]}"
        for r in rows
    ])

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{
                "role": "user",
                "content": (
                    f"다음은 지난 {len(rows)}일간의 AI/SaaS 시장 일일 헤드라인입니다.\n\n"
                    f"{summaries}\n\n"
                    f"이 트렌드를 종합하여 이번 주 시장의 핵심 패턴 3가지와 "
                    f"다음 주 주목해야 할 포인트 2가지를 간결하게 정리하세요."
                ),
            }],
        )
        weekly_insight = message.content[0].text

        msg = (
            f"<b>📈 주간 시장 트렌드 요약</b>\n\n"
            f"{weekly_insight[:1500]}"
        )

        if token and chat_id:
            payload = json.dumps({
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15):
                print("  주간 트렌드 요약 발송 완료")

    except Exception as e:
        print(f"  주간 요약 생성 오류: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    print("=== AI BI 시장 인텔리전스 에이전트 시작 ===\n")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    user_context = os.environ.get("BI_USER_CONTEXT", "")  # 선택적: 분석 맥락 커스터마이즈

    # 월요일이면 주간 요약 추가 실행
    is_monday = datetime.now(KST).weekday() == 0
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

    # 1. 뉴스 수집
    print("[1/4] 시장 뉴스 수집 중...")
    news = collect_news(max_per_source=8)

    if not news:
        print("  수집된 뉴스 없음. 종료합니다.")
        if token and chat_id:
            payload = json.dumps({
                "chat_id": chat_id,
                "text": "📊 AI BI 에이전트: 오늘 뉴스 수집에 실패했습니다. RSS 소스를 확인해주세요.",
                "parse_mode": "HTML",
            }).encode("utf-8")
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=15)
            except Exception:
                pass
        return

    # 2. Claude AI 분석
    print(f"\n[2/4] Claude AI 시장 분석 중... ({len(news)}건)")
    analysis = analyze_market_intelligence(news, user_context)
    print(f"  핵심 메시지: {analysis.get('headline', '')[:80]}")

    # 3. Supabase 저장
    print("\n[3/4] Supabase 저장 중...")
    saved = save_daily_report(analysis, len(news))
    print(f"  저장: {'성공' if saved else '실패'}")

    # 4. 텔레그램 발송
    print("\n[4/4] 텔레그램 리포트 발송 중...")
    if token and chat_id:
        send_telegram_report(token, chat_id, analysis, len(news))

        if is_monday or is_manual:
            print("  월요일/수동 실행 — 주간 트렌드 요약 생성 중...")
            generate_weekly_trend_summary(token, chat_id)
    else:
        print("  텔레그램 설정 없음 — 발송 건너뜀")

    print(f"\n=== 완료: 뉴스 {len(news)}건 분석, 기회 {len(analysis.get('opportunities', []))}개 도출 ===")


if __name__ == "__main__":
    main()
