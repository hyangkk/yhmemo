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
import socket
import hashlib
import feedparser
import anthropic
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta


ALL_SOURCES = {
    # Google News (해외 서버에서도 안정적으로 접근 가능 — 최우선 시도)
    "구글뉴스": "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
    "구글뉴스_경제": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
    "구글뉴스_IT": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGd3TVRBU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
    # 방송사
    "KBS":    "https://news.kbs.co.kr/rss/rss.do",
    "MBC":    "https://imnews.imbc.com/rss/news/news_00.xml",
    "SBS":    "https://news.sbs.co.kr/news/headlineRssFeed.do?plink=RSSREADER",
    "JTBC":   "https://news.jtbc.co.kr/RSS/NewsFlash.xml",
    # 통신사
    "연합뉴스":  "https://www.yna.co.kr/RSS/news.xml",
    "뉴스1":   "https://www.news1.kr/rss/allNews.xml",
    "뉴시스":  "https://www.newsis.com/RSS/",
    # 종합일간지
    "조선일보": "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
    "중앙일보": "https://rss.joinsmsn.com/news/sectlist/uAll.xml",
    "동아일보": "https://rss.donga.com/total.xml",
    "한겨레":  "https://www.hani.co.kr/rss/",
    "경향신문": "https://www.khan.co.kr/rss/rssdata/total_news.xml",
    # 경제지
    "매일경제": "https://www.mk.co.kr/rss/30000001/",
    "한국경제": "https://www.hankyung.com/feed/all-news",
    "머니투데이": "https://rss.mt.co.kr/rss/mt_news.xml",
    # 스타트업
    "케이스타트업": "https://www.k-startup.go.kr/web/contents/rss/startupnews.do",
}

# GitHub Actions 환경에서도 항상 접근 가능한 보장 소스
GUARANTEED_SOURCES = ["구글뉴스", "구글뉴스_경제", "구글뉴스_IT"]

DEFAULT_PROMPT_TEMPLATE = """당신은 창의적인 아이디어 기획자입니다.
아래 오늘의 주요 뉴스들을 깊이 분석하고, 이 뉴스들의 흐름을 창의적으로 결합하여 혁신적인 새로운 아이디어를 하나 도출해주세요.

{news_block}

다음 형식으로 아이디어를 제시해주세요:

## 아이디어 이름
(간결하고 인상적인 이름)

## 핵심 통찰
(뉴스들이 어떤 공통된 흐름이나 기회를 가리키는지 설명)

## 아이디어 설명
(구체적인 서비스/제품/정책/캠페인 아이디어)

## 실현 방안
(단계별 접근법 또는 주요 실행 포인트 3가지)

## 기대 효과
(이 아이디어가 가져올 변화와 가치)

[주의사항]
- 표(테이블) 형식을 사용하지 말고 글 형식으로 작성하세요.
- 뉴스 원문 링크와 이미지는 시스템에서 자동으로 첨부됩니다. 직접 링크나 이미지 설명을 추가하지 마세요.
- 위의 5개 섹션만 작성하세요."""

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

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _extract_image_url(entry) -> str:
    """RSS 항목에서 실제 이미지 URL 추출 (media_thumbnail → media_content → enclosures 순)."""
    for thumb in entry.get("media_thumbnail", []):
        if thumb.get("url"):
            return thumb["url"]
    for media in entry.get("media_content", []):
        url = media.get("url", "")
        if url and "image" in media.get("type", "image"):
            return url
    for enc in entry.get("enclosures", []):
        if "image" in enc.get("type", "") and (enc.get("href") or enc.get("url")):
            return enc.get("href") or enc.get("url", "")
    return ""


def _resolve_google_news_url(url: str) -> str:
    """Google News URL → 실제 기사 URL (HTTP 리디렉션 추적, 실패 시 원본 반환)."""
    if "news.google.com" not in url:
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            final = resp.url
            return final if "news.google.com" not in final else url
    except Exception as e:
        print(f"    Google URL 변환 실패: {e}", file=sys.stderr)
        return url


def _download_image(image_url: str) -> tuple:
    """이미지 URL에서 바이너리 데이터 다운로드. (bytes, content_type) 반환. 실패 시 (b'', '')."""
    if not image_url:
        return b"", ""
    try:
        req = urllib.request.Request(image_url, headers={"User-Agent": _BROWSER_UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            if not ct.startswith("image/"):
                return b"", ""
            return resp.read(), ct
    except Exception as e:
        print(f"    이미지 다운로드 실패 ({image_url[:70]}): {e}", file=sys.stderr)
        return b"", ""


def _ensure_supabase_bucket(bucket: str) -> bool:
    """Supabase Storage 버킷이 없으면 public 버킷으로 생성."""
    supa_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supa_url or not key:
        return False
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    try:
        req = urllib.request.Request(f"{supa_url}/storage/v1/bucket/{bucket}", headers=headers)
        urllib.request.urlopen(req, timeout=10)
        return True  # 이미 존재
    except urllib.error.HTTPError as e:
        if e.code not in (400, 404):
            return False
    except Exception:
        return False
    # 버킷 생성
    payload = json.dumps({"id": bucket, "name": bucket, "public": True}).encode()
    req2 = urllib.request.Request(
        f"{supa_url}/storage/v1/bucket",
        data=payload,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req2, timeout=10)
        print(f"  Supabase 버킷 '{bucket}' 생성 완료")
        return True
    except Exception as e:
        print(f"  Supabase 버킷 생성 실패: {e}", file=sys.stderr)
        return False


def _upload_image_to_supabase(image_data: bytes, filename: str, content_type: str) -> str:
    """이미지를 Supabase Storage에 업로드하고 공개 URL 반환. 실패 시 빈 문자열."""
    supa_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supa_url or not key:
        return ""
    bucket = "news-images"
    req = urllib.request.Request(
        f"{supa_url}/storage/v1/object/{bucket}/{filename}",
        data=image_data,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=30)
        public_url = f"{supa_url}/storage/v1/object/public/{bucket}/{filename}"
        print(f"    이미지 업로드 완료: {filename}")
        return public_url
    except Exception as e:
        print(f"    이미지 업로드 실패 ({filename}): {e}", file=sys.stderr)
        return ""


def process_news_images(news_items: list) -> None:
    """각 뉴스 항목의 이미지를 다운로드하여 Supabase Storage에 업로드.
    news_items[i]['image_url']을 Supabase 공개 URL로 교체 (실패 시 빈 문자열로 설정)."""
    has_images = any(item.get("image_url") for item in news_items)
    if not has_images:
        print("  이미지 없음 — 건너뜀")
        return

    _ensure_supabase_bucket("news-images")
    date_prefix = datetime.now(KST).strftime("%Y%m%d")
    ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}

    for i, item in enumerate(news_items):
        raw_url = item.get("image_url", "")
        if not raw_url:
            continue
        print(f"  [{i+1}] 이미지 처리 중: {raw_url[:70]}")
        image_data, ct = _download_image(raw_url)
        if not image_data:
            item["image_url"] = ""
            continue
        ext = ext_map.get(ct, "jpg")
        title_hash = hashlib.md5(item["title"].encode()).hexdigest()[:8]
        filename = f"{date_prefix}/{i+1}_{title_hash}.{ext}"
        item["image_url"] = _upload_image_to_supabase(image_data, filename, ct)


def fetch_top_news(active_sources: list, count: int = 3) -> list:
    """활성화된 RSS 피드에서 최신 뉴스 수집. 소스별로 순환하며 count개 수집."""
    news_items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)

    # active_sources 기반 피드 목록 (ALL_SOURCES 순서 유지)
    feeds = [(name, url) for name, url in ALL_SOURCES.items() if name in active_sources]

    # Supabase 설정에 없더라도 구글뉴스는 항상 앞에 추가 (GitHub Actions에서 안정적으로 접근 가능)
    guaranteed_feeds = [
        (name, ALL_SOURCES[name]) for name in GUARANTEED_SOURCES
        if name not in active_sources and name in ALL_SOURCES
    ]
    feeds = guaranteed_feeds + feeds

    # 일부 한국 뉴스 사이트는 봇 User-Agent 차단 → 브라우저처럼 위장
    ua_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    for source_name, feed_url in feeds:
        if len(news_items) >= count:
            break
        try:
            print(f"  [{source_name}] 수집 중...")

            # 타임아웃 15초 설정 (무한 대기 방지)
            prev_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(15)
            try:
                feed = feedparser.parse(feed_url, request_headers=ua_headers)
            finally:
                socket.setdefaulttimeout(prev_timeout)

            # 네트워크/파싱 오류로 항목이 없는 경우
            if not feed.entries:
                reason = str(getattr(feed, "bozo_exception", "항목 없음"))
                print(f"  [{source_name}] 건너뜀 — {reason}", file=sys.stderr)
                continue

            # 한 소스에서 필요한 만큼 여러 기사 수집 (기존: 1개 고정 → 개선: 최대 needed개)
            needed = count - len(news_items)
            collected = 0
            for entry in feed.entries:
                if collected >= needed:
                    break
                parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_time_str = ""
                if parsed_time:
                    pub_dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue  # 너무 오래된 기사 건너뜀
                    pub_time_str = pub_dt.astimezone(KST).strftime("%m/%d %H:%M")
                title = entry.get("title", "").strip()
                summary = entry.get("summary", entry.get("description", title)).strip()
                link = entry.get("link", "")
                # Google News 단축 URL → 실제 기사 URL 변환
                if "news.google.com" in link:
                    link = _resolve_google_news_url(link)
                summary = re.sub(r"<[^>]+>", "", summary).strip()
                if len(summary) > 500:
                    summary = summary[:497] + "..."
                if not title:
                    continue
                news_items.append({
                    "source": source_name,
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published_at": pub_time_str,
                    "image_url": _extract_image_url(entry),
                })
                collected += 1

            if collected > 0:
                print(f"  [{source_name}] OK: {collected}개 수집")
            else:
                print(f"  [{source_name}] 최근 뉴스 없음", file=sys.stderr)

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
        f"**뉴스 {i + 1} ({item['source']}"
        + (f", {item['published_at']}" if item.get('published_at') else "")
        + f")**\n제목: {item['title']}\n내용: {item['summary']}"
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

def _send_telegram_photos(token: str, chat_id: str, news_items: list) -> None:
    """뉴스 항목별 이미지를 텔레그램 sendPhoto로 개별 발송.
    캡션에 제목 + 원문 링크 포함. Supabase Storage URL을 이미지로 사용."""
    for i, item in enumerate(news_items):
        img = item.get("image_url", "")
        if not img:
            continue
        pub = f" {item['published_at']}" if item.get('published_at') else ""
        caption = f"[{item['source']}]{pub} {item['title']}"
        payload = json.dumps({
            "chat_id": chat_id,
            "photo": img,
            "caption": caption,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                result = json.loads(resp.read().decode())
                if result.get("ok"):
                    print(f"  [{i+1}] 이미지 발송 완료")
                else:
                    print(f"  [{i+1}] 이미지 발송 실패: {result.get('description')}", file=sys.stderr)
        except Exception as e:
            print(f"  [{i+1}] 이미지 발송 오류: {e}", file=sys.stderr)


def send_to_telegram(news_items: list, idea: str, generated_at: datetime) -> bool:
    """텔레그램 봇으로 결과 메시지 발송."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("경고: TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 없습니다.", file=sys.stderr)
        return False

    # 실제 이미지가 있으면 먼저 이미지 그룹으로 전송
    _send_telegram_photos(token, chat_id, news_items)

    timestamp = generated_at.strftime("%Y년 %m월 %d일 %H시 (KST)")

    # idea 후처리: 깨진 URL 및 이미지 없음 텍스트 제거
    idea = re.sub(r'\(https?://[^\)]+\)', '', idea)  # [원문 링크](url) → [원문 링크]
    idea = re.sub(r'🖼️[^\n]*이미지[^\n]*없음[^\n]*\n?', '', idea)
    idea = re.sub(r'🖼️[^\n]*\n?', '', idea)
    idea = re.sub(r'\n{3,}', '\n\n', idea).strip()

    # 뉴스 목록: 게시 시각 + 제목 + 실제 원문 링크
    news_lines = "\n".join(
        f"{i + 1}. [{item['source']}]"
        + (f" {item['published_at']}" if item.get('published_at') else "")
        + f" {item['title']}"
        + (f"\n   <a href=\"{item['link']}\">원문 보기</a>" if item.get('link') else "")
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
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if run_every > 1 and not is_manual:
        current_hour_utc = datetime.now(timezone.utc).hour
        if current_hour_utc % run_every != 0:
            print(f"현재 {current_hour_utc}시 (UTC) — {run_every}시간 간격 미해당. 건너뜀.")
            sys.exit(0)
    if is_manual:
        print("수동 실행 — 시간 간격 체크 건너뜀.")

    active_sources = settings["active_sources"]
    prompt_template = settings.get("prompt_template", "")
    print(f"활성 소스: {active_sources} | 실행 주기: {run_every}시간\n")

    print("[1/4] 주요 뉴스 수집 중...")
    news_items = fetch_top_news(active_sources, 3)
    if not news_items:
        print("오류: 뉴스를 수집하지 못했습니다.", file=sys.stderr)
        sys.exit(1)
    print(f"수집 완료: {len(news_items)}개\n")

    print("[2/4] 뉴스 이미지 처리 중 (다운로드 → Supabase Storage)...")
    process_news_images(news_items)
    print()

    print("[3/4] Claude AI로 아이디어 생성 중...")
    idea = generate_idea(news_items, prompt_template)
    print("생성 완료\n")

    generated_at = datetime.now(KST)

    print("[4/4] 결과 저장 & 발송 중...")
    supabase_ok = save_to_supabase(news_items, idea, generated_at)
    telegram_ok = send_to_telegram(news_items, idea, generated_at)

    print("\n=== 완료 ===")
    print(f"  Supabase: {'OK' if supabase_ok else 'FAIL'}")
    print(f"  Telegram: {'OK' if telegram_ok else 'FAIL'}")

    if not supabase_ok and not telegram_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
