#!/usr/bin/env python3
"""
뉴스 아이디어 에이전트
- 매 시간 정각 GitHub Actions에 의해 자동 실행
- RSS 피드에서 주요 뉴스 3개 수집
- Claude AI로 3개 뉴스를 결합하여 새로운 아이디어 도출
- 결과를 news-ideas/ 폴더에 마크다운으로 저장
"""

import os
import sys
import feedparser
import anthropic
from datetime import datetime, timezone, timedelta


# 수집할 RSS 피드 목록 (순서대로 하나씩 가져옴)
RSS_FEEDS = [
    ("BBC News", "http://feeds.bbci.co.uk/news/rss.xml"),
    ("Reuters", "https://feeds.reuters.com/reuters/topNews"),
    ("AP News", "https://feeds.apnews.com/rss/apf-topnews"),
]

KST = timezone(timedelta(hours=9))


def fetch_top_news(count: int = 3) -> list[dict]:
    """각 RSS 피드에서 최신 뉴스 1개씩 수집하여 count개 반환."""
    news_items = []

    for source_name, feed_url in RSS_FEEDS:
        if len(news_items) >= count:
            break
        try:
            print(f"  [{source_name}] 뉴스 수집 중: {feed_url}")
            feed = feedparser.parse(feed_url)

            if not feed.entries:
                print(f"  [{source_name}] 항목 없음, 건너뜀")
                continue

            entry = feed.entries[0]
            title = entry.get("title", "").strip()
            summary = entry.get("summary", entry.get("description", title)).strip()
            link = entry.get("link", "")

            # HTML 태그 간단 제거
            import re
            summary = re.sub(r"<[^>]+>", "", summary).strip()

            # 요약이 너무 길면 자름
            if len(summary) > 500:
                summary = summary[:497] + "..."

            news_items.append(
                {"source": source_name, "title": title, "summary": summary, "link": link}
            )
            print(f"  [{source_name}] 수집 완료: {title[:60]}...")

        except Exception as e:
            print(f"  [{source_name}] 수집 실패: {e}", file=sys.stderr)

    if len(news_items) < count:
        print(f"경고: {count}개 중 {len(news_items)}개만 수집됨", file=sys.stderr)

    return news_items[:count]


def generate_idea(news_items: list[dict]) -> str:
    """Claude AI로 뉴스 3개를 결합하여 새로운 아이디어 생성."""
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


def save_result(news_items: list[dict], idea: str) -> str:
    """결과를 마크다운 파일로 news-ideas/ 에 저장."""
    now_kst = datetime.now(KST)
    filename = now_kst.strftime("%Y-%m-%d-%H") + ".md"
    output_dir = os.path.join(os.path.dirname(__file__), "..", "news-ideas")
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    news_section = ""
    for i, item in enumerate(news_items):
        news_section += (
            f"### 뉴스 {i + 1}: {item['title']}\n\n"
            f"- **출처**: {item['source']}\n"
            f"- **링크**: [{item['link']}]({item['link']})\n"
            f"- **요약**: {item['summary']}\n\n"
        )

    content = f"""# 뉴스 아이디어 리포트

> 생성 시각: {now_kst.strftime("%Y년 %m월 %d일 %H시 %M분")} (KST)
> 자동 생성: GitHub Actions 뉴스 아이디어 에이전트

---

## 수집된 주요 뉴스 3개

{news_section}---

## AI 도출 아이디어

{idea}
"""

    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return filepath


def main():
    print("=== 뉴스 아이디어 에이전트 시작 ===\n")

    # 1. 뉴스 수집
    print("[1/3] 주요 뉴스 수집 중...")
    news_items = fetch_top_news(3)

    if not news_items:
        print("오류: 뉴스를 하나도 수집하지 못했습니다.", file=sys.stderr)
        sys.exit(1)

    print(f"\n수집 완료: {len(news_items)}개\n")

    # 2. AI 아이디어 생성
    print("[2/3] Claude AI로 아이디어 생성 중...")
    idea = generate_idea(news_items)
    print("아이디어 생성 완료\n")

    # 3. 결과 저장
    print("[3/3] 결과 저장 중...")
    filepath = save_result(news_items, idea)
    print(f"저장 완료: {filepath}\n")

    print("=== 완료 ===")
    print(f"\n--- 생성된 아이디어 미리보기 ---\n{idea[:300]}...")


if __name__ == "__main__":
    main()
