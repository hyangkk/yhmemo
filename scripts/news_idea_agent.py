#!/usr/bin/env python3
"""
뉴스 아이디어 에이전트
- 매 시간 정각 GitHub Actions에 의해 자동 실행
- RSS 피드에서 주요 뉴스 3개 수집
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


RSS_FEEDS = [
    ("BBC News", "http://feeds.bbci.co.uk/news/rss.xml"),
    ("Reuters", "https://feeds.reuters.com/reuters/topNews"),
    ("AP News", "https://feeds.apnews.com/rss/apf-topnews"),
]

KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# 1. 뉴스 수집
# ---------------------------------------------------------------------------

def fetch_top_news(count: int = 3) -> list[dict]:
    """각 RSS 피드에서 최신 뉴스 1개씩 수집."""
    news_items = []

    for source_name, feed_url in RSS_FEEDS:
        if len(news_items) >= count:
            break
        try:
            print(f"  [{source_name}] 수집 중...")
            feed = feedparser.parse(feed_url)

            if not feed.entries:
                print(f"  [{source_name}] 항목 없음, 건너뜀")
                continue

            entry = feed.entries[0]
            title = entry.get("title", "").strip()
            summary = entry.get("summary", entry.get("description", title)).strip()
            link = entry.get("link", "")

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

def generate_idea(news_items: list[dict]) -> str:
    """Claude AI로 뉴스 3개를 결합하여 아이디어 생성."""
    client = anthropic.Anthropic()

    news_block = "\n\n".join(
        f"**뉴스 {i + 1} ({item['source']})**\n"
        f"제목: {item['title']}\n"
        f"내용: {item['summary']}"
        for i, item in enumerate(news_items)
    )

    prompt = f"""당신은 창의적인 아이디어 기획자입니다.
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
(이 아이디어가 가져올 변화와 가치)
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text


# ---------------------------------------------------------------------------
# 3. Supabase 저장
# ---------------------------------------------------------------------------

def save_to_supabase(news_items: list[dict], idea: str, generated_at: datetime) -> bool:
    """Supabase news_ideas 테이블에 결과 저장 (REST API 사용)."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    if not url or not key:
        print("경고: SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY가 없습니다.", file=sys.stderr)
        return False

    endpoint = f"{url}/rest/v1/news_ideas"

    payload = json.dumps({
        "generated_at": generated_at.isoformat(),
        "news_items": news_items,
        "idea": idea,
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
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

def send_to_telegram(news_items: list[dict], idea: str, generated_at: datetime) -> bool:
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

    # 텔레그램 MarkdownV2는 특수문자 이스케이프 필요 → HTML 모드 사용
    message = (
        f"<b>뉴스 아이디어 리포트</b>\n"
        f"<i>{timestamp}</i>\n\n"
        f"<b>수집된 뉴스</b>\n"
        f"{news_lines}\n\n"
        f"<b>AI 도출 아이디어</b>\n"
        f"{idea[:2000]}"  # 텔레그램 메시지 길이 제한 대비
    )

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
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

    print("[1/3] 주요 뉴스 수집 중...")
    news_items = fetch_top_news(3)
    if not news_items:
        print("오류: 뉴스를 수집하지 못했습니다.", file=sys.stderr)
        sys.exit(1)
    print(f"수집 완료: {len(news_items)}개\n")

    print("[2/3] Claude AI로 아이디어 생성 중...")
    idea = generate_idea(news_items)
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
