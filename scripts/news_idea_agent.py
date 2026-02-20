#!/usr/bin/env python3
"""
뉴스 아이디어 에이전트
- 매 시간 정각 GitHub Actions에 의해 자동 실행
- Supabase agent_settings 테이블에서 설정 로드
- 활성화된 한국 뉴스 RSS 피드에서 뉴스 3개 수집
- Claude AI로 3개 뉴스를 결합하여 새로운 아이디어 도출
- Supabase에 저장 + 텔레그램으로 발송
"""

import os
import re
import sys
import json
import feedparser
import anthropic
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta


ALL_SOURCES = {
    "KBS":   "https://news.kbs.co.kr/rss/rss.do",
    "MBC":   "https://imnews.imbc.com/rss/news/news_00.xml",
    "SBS":   "https://news.sbs.co.kr/news/headlineRssFeed.do?plink=RSSREADER",
    "JTBC":  "https://news.jtbc.co.kr/RSS/NewsFlash.xml",
    "연합뉴스": "https://www.yna.co.kr/RSS/news.xml",
}

DEFAULT_PROMPT_TEMPLATE = """당신은 창의적인 아이디어 기획자입니다.
아래 오늘의 주요 뉴스 3개를 깊이 분석하고, 이 3가지 흐름을 창의적으로 결합하여 혁신적인 새로운 아이디어를 하나 도출해주세요.

{news_block}

다음 형식으로 아이디어를 제시해주세요:

## 아이디어 이름
(간결하고 인상적인 이름)

## 핵심 통찰
(세 뉴스가 어떤 공통된 흐름이나 기회를 가리키는지 설명)

## 아이디어 설명
(구체적인 서비스/제품/정책/캠페인 아이디어)

## 실현 방안
(단계별 접근법 또는 주요 실행 포인트 3가지)

## 기대 효과
(이 아이디어가 가져올 변화와 가치)"""

KST = timezone(timedelta(hours=9))


def _supabase_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# 0. 설정 로드
# ---------------------------------------------------------------------------

def fetch_settings() -> dict:
    """Supabase agent_settings 테이블에서 설정 로드. 실패 시 기본값 반환."""
    default = {
        "enabled": True,
        "run_every_hours": 1,
        "active_sources": list(ALL_SOURCES.keys()),
        "prompt_template": "",
    }

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        return default

    req = urllib.request.Request(
        f"{url}/rest/v1/agent_settings?id=eq.1",
        headers=_supabase_headers(),
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            if data:
                return {**default, **data[0]}
    except Exception as e:
        print(f"설정 로드 실패 (기본값 사용): {e}", file=sys.stderr)

    return default


# ---------------------------------------------------------------------------
# 1. 뉴스 수집
# ---------------------------------------------------------------------------

def fetch_top_news(active_sources: list, count: int = 3) -> list:
    """활성화된 RSS 피드에서 최신 24시간 이내 뉴스 1개씩 수집."""
    import time as _time
    news_items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)

    feeds = [(name, url) for name, url in ALL_SOURCES.items() if name in active_sources]

    for source_name, feed_url in feeds:
        if len(news_items) >= count:
            break
        try:
            print(f"  [{source_name}] 수집 중...")
            feed = feedparser.parse(feed_url)

            if not feed.entries:
                print(f"  [{source_name}] 항목 없음, 건너뜀")
                continue

            found = None
            for entry in feed.entries:
                # published_parsed 또는 updated_parsed로 날짜 확인
                parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
                if parsed_time:
                    pub_dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
                    if pub_dt >= cutoff:
                        found = entry
                        break
                else:
                    # 날짜 정보 없으면 첫 번째 항목 사용
                    found = entry
                    break

            if not found:
                # 24시간 이내 뉴스 없으면 최신 기사로 fallback
                print(f"  [{source_name}] 24시간 이내 뉴스 없음 → 최신 기사 사용")
                found = feed.entries[0]

            title = found.get("title", "").strip()
            summary = found.get("summary", found.get("description", title)).strip()
            link = found.get("link", "")

            summary = re.sub(r"<[^>]+>", "", summary).strip()
            if len(summary) > 500:
                summary = summary[:497] + "..."

            news_items.append(
                {"source": source_name, "title": title, "summary": summary, "link": link}
            )
            print(f"  [{source_name}] OK: {title[:60]}...")

        except Exception as e:
            print(f"  [{source_name}] 실패: {e}", file=sys.stderr)

    if len(news_items) < count:
        print(f"경고: {count}개 중 {len(news_items)}개만 수집됨", file=sys.stderr)

    return news_items[:count]


# ---------------------------------------------------------------------------
# 2. AI 아이디어 생성
# ---------------------------------------------------------------------------

def generate_idea(news_items: list, prompt_template: str = "") -> str:
    """Claude AI로 뉴스 3개를 결합하여 아이디어 생성."""
    client = anthropic.Anthropic()

    news_block = "\n\n".join(
        f"**뉴스 {i + 1} ({item['source']})**\n"
        f"제목: {item['title']}\n"
        f"내용: {item['summary']}"
        for i, item in enumerate(news_items)
    )

    template = prompt_template.strip() if prompt_template and prompt_template.strip() else DEFAULT_PROMPT_TEMPLATE

    if "{news_block}" in template:
        prompt = template.replace("{news_block}", news_block)
    else:
        prompt = template + "\n\n" + news_block

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


# ---------------------------------------------------------------------------
# 3. Supabase 저장
# ---------------------------------------------------------------------------

def save_to_supabase(news_items: list, idea: str, generated_at: datetime) -> bool:
    """Supabase news_ideas 테이블에 결과 저장 (REST API 사용)."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        print("경고: SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY가 없습니다.", file=sys.stderr)
        return False

    payload = json.dumps({
        "generated_at": generated_at.isoformat(),
        "news_items": news_items,
        "idea": idea,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{url}/rest/v1/news_ideas",
        data=payload,
        headers={**_supabase_headers(), "Prefer": "return=minimal"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            print(f"Supabase 저장 완료 (status: {resp.status})")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Supabase 저장 실패 ({e.code}): {body}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 4. 텔레그램 발송
# ---------------------------------------------------------------------------

def send_to_telegram(news_items: list, idea: str, generated_at: datetime) -> bool:
    """텔레그램 봇으로 결과 메시지 발송."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("경고: TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 없습니다.", file=sys.stderr)
        return False

    timestamp = generated_at.strftime("%Y년 %m월 %d일 %H시 (KST)")

    news_lines = "\n".join(
        f"{i + 1}. [{item['source']}] {item['title']}"
        for i, item in enumerate(news_items)
    )

    message = (
        f"<b>뉴스 아이디어 리포트</b>\n"
        f"<i>{timestamp}</i>\n\n"
        f"<b>수집된 뉴스</b>\n"
        f"{news_lines}\n\n"
        f"<b>AI 도출 아이디어</b>\n"
        f"{idea[:2000]}"
    )

    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
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
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                print("텔레그램 발송 완료")
                return True
            else:
                print(f"텔레그램 발송 실패: {result}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"텔레그램 발송 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    print("=== 뉴스 아이디어 에이전트 시작 ===\n")

    print("[설정] Supabase에서 설정 로드 중...")
    settings = fetch_settings()

    if not settings["enabled"]:
        print("에이전트가 비활성화되어 있습니다. 종료합니다.")
        sys.exit(0)

    run_every = int(settings["run_every_hours"])
    if run_every > 1:
        current_hour_utc = datetime.now(timezone.utc).hour
        if current_hour_utc % run_every != 0:
            print(f"현재 {current_hour_utc}시 (UTC) — {run_every}시간 간격 미해당. 건너뜀.")
            sys.exit(0)

    active_sources = settings["active_sources"]
    prompt_template = settings.get("prompt_template", "")
    print(f"활성 소스: {active_sources} | 실행 주기: {run_every}시간\n")

    print("[1/3] 주요 뉴스 수집 중...")
    news_items = fetch_top_news(active_sources, 3)
    if not news_items:
        print("오류: 뉴스를 수집하지 못했습니다.", file=sys.stderr)
        sys.exit(1)
    print(f"수집 완료: {len(news_items)}개\n")

    print("[2/3] Claude AI로 아이디어 생성 중...")
    idea = generate_idea(news_items, prompt_template)
    print("생성 완료\n")

    generated_at = datetime.now(KST)

    print("[3/3] 결과 저장 & 발송 중...")
    supabase_ok = save_to_supabase(news_items, idea, generated_at)
    telegram_ok = send_to_telegram(news_items, idea, generated_at)

    print("\n=== 완료 ===")
    print(f"  Supabase: {'OK' if supabase_ok else 'FAIL'}")
    print(f"  Telegram: {'OK' if telegram_ok else 'FAIL'}")

    if not supabase_ok and not telegram_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
