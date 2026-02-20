#!/usr/bin/env python3
"""
생각일기 알림 에이전트
- 매일 오전 7시 KST에 GitHub Actions에 의해 자동 실행
- Notion '생각일기 DB'에서 다음 항목 수집:
    1) 생성일 기준 48시간 이내에 생성된 항목
    2) '상단 고정 기간' 속성의 기간이 현재 시점에 유효한 항목
- Claude AI로 항목들을 간략히 요약
- 텔레그램으로 요약 발송
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta, date
import anthropic

KST = timezone(timedelta(hours=9))


def notion_headers() -> dict:
    token = os.environ.get("NOTION_API_KEY", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


# ---------------------------------------------------------------------------
# 1. Notion DB 조회
# ---------------------------------------------------------------------------

def fetch_diary_pages() -> list:
    """Notion 생각일기 DB에서 후보 페이지 조회.
    필터: (생성일 >= 48시간 전) OR (상단 고정 기간 시작 <= 오늘)
    상단 고정 기간의 종료일 유효성은 Python에서 추가 검사.
    """
    database_id = os.environ.get("NOTION_DATABASE_ID", "")
    if not database_id:
        print("오류: NOTION_DATABASE_ID가 없습니다.", file=sys.stderr)
        sys.exit(1)

    cutoff_48h = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    today_kst = datetime.now(KST).date().isoformat()

    filter_body = {
        "filter": {
            "or": [
                {
                    "timestamp": "created_time",
                    "created_time": {"after": cutoff_48h},
                },
                {
                    "and": [
                        {
                            "property": "상단 고정 기간",
                            "date": {"on_or_before": today_kst},
                        },
                        {
                            "property": "상단 고정 기간",
                            "date": {"is_not_empty": True},
                        },
                    ]
                },
            ]
        },
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }

    payload = json.dumps(filter_body).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        data=payload,
        headers=notion_headers(),
        method="POST",
    )

    all_pages = []
    try:
        while True:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
            all_pages.extend(data.get("results", []))

            # 페이지네이션 처리
            if not data.get("has_more"):
                break
            next_cursor = data.get("next_cursor")
            filter_body["start_cursor"] = next_cursor
            payload = json.dumps(filter_body).encode("utf-8")
            req = urllib.request.Request(
                f"https://api.notion.com/v1/databases/{database_id}/query",
                data=payload,
                headers=notion_headers(),
                method="POST",
            )
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Notion API 오류 ({e.code}): {body}", file=sys.stderr)
        sys.exit(1)

    return all_pages


def get_page_text(page_id: str) -> str:
    """페이지 블록에서 텍스트 내용 추출."""
    req = urllib.request.Request(
        f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100",
        headers=notion_headers(),
    )
    try:
        with urllib.request.urlopen(req) as resp:
            blocks = json.loads(resp.read().decode()).get("results", [])
    except Exception as e:
        print(f"  페이지 내용 로드 실패 ({page_id[:8]}...): {e}", file=sys.stderr)
        return ""

    lines = []
    for block in blocks:
        btype = block.get("type", "")
        rich_text = block.get(btype, {}).get("rich_text", [])
        if rich_text:
            text = "".join(rt.get("plain_text", "") for rt in rich_text).strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


def extract_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(
                rt.get("plain_text", "") for rt in prop.get("title", [])
            ).strip() or "(제목 없음)"
    return "(제목 없음)"


def is_pinned_valid(page: dict) -> bool:
    """상단 고정 기간이 오늘 날짜를 포함하는지 확인."""
    today = datetime.now(KST).date()
    pinned = page.get("properties", {}).get("상단 고정 기간", {})
    if pinned.get("type") != "date":
        return False
    date_data = pinned.get("date")
    if not date_data or not date_data.get("start"):
        return False
    try:
        start = date.fromisoformat(date_data["start"][:10])
        if start > today:
            return False
        end_str = date_data.get("end")
        if end_str:
            return date.fromisoformat(end_str[:10]) >= today
        return True  # 종료일 없으면 무기한 고정
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# 2. 항목 필터링 및 내용 수집
# ---------------------------------------------------------------------------

def collect_entries(pages: list) -> list:
    """Notion 결과에서 실제 조건에 맞는 항목만 추려 내용 수집."""
    cutoff_48h = datetime.now(timezone.utc) - timedelta(hours=48)
    entries = []

    for page in pages:
        # 48시간 이내 생성 여부
        created_str = page.get("created_time", "")
        within_48h = False
        if created_str:
            try:
                created_dt = datetime.fromisoformat(
                    created_str.replace("Z", "+00:00")
                )
                within_48h = created_dt >= cutoff_48h
            except ValueError:
                pass

        # 상단 고정 기간 유효 여부
        pinned = is_pinned_valid(page)

        if not (within_48h or pinned):
            continue

        page_id = page.get("id", "")
        title = extract_title(page)
        content = get_page_text(page_id)

        created_kst = ""
        if created_str:
            try:
                dt = datetime.fromisoformat(
                    created_str.replace("Z", "+00:00")
                ).astimezone(KST)
                created_kst = dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass

        tag = (
            "[최신+고정]" if within_48h and pinned
            else "[최신]" if within_48h
            else "[고정]"
        )
        entries.append(
            {
                "title": title,
                "content": content,
                "created_kst": created_kst,
                "tag": tag,
            }
        )
        print(f"  {tag} {title} ({created_kst})")

    return entries


# ---------------------------------------------------------------------------
# 3. Claude AI 요약
# ---------------------------------------------------------------------------

def summarize_entries(entries: list) -> str:
    if not entries:
        return "오늘 공유할 생각일기 항목이 없습니다."

    client = anthropic.Anthropic()

    entries_text = ""
    for i, e in enumerate(entries, 1):
        entries_text += (
            f"\n\n[항목 {i}] {e['title']} {e['tag']} (작성: {e['created_kst']})\n"
        )
        if e["content"]:
            entries_text += e["content"][:1200]

    prompt = (
        "다음은 생각일기의 최근 항목들입니다. "
        "각 항목의 핵심 내용을 1~2문장으로 요약하고, "
        "공통된 주제나 흐름이 있으면 마지막에 짧게 언급해주세요. "
        "친근하고 간결한 어조로 작성해주세요.\n\n"
        f"생각일기 항목:{entries_text}"
    )

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# 4. 텔레그램 발송
# ---------------------------------------------------------------------------

def send_to_telegram(summary: str, entry_count: int, generated_at: datetime) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("경고: TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 없습니다.", file=sys.stderr)
        return False

    date_str = generated_at.strftime("%Y년 %m월 %d일")
    header = (
        f"<b>오늘의 생각일기 요약</b>\n"
        f"<i>{date_str} · {entry_count}개 항목</i>\n\n"
    )
    message = header + summary[:3800]

    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")

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
            print(f"텔레그램 발송 실패: {result}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"텔레그램 발송 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    print("=== 생각일기 알림 에이전트 시작 ===\n")

    if not os.environ.get("NOTION_API_KEY"):
        print("오류: NOTION_API_KEY가 없습니다.", file=sys.stderr)
        sys.exit(1)

    print("[1/3] Notion 생각일기 DB 조회 중...")
    pages = fetch_diary_pages()
    print(f"후보 페이지: {len(pages)}개\n")

    print("[2/3] 조건 검증 및 내용 수집 중...")
    entries = collect_entries(pages)
    print(f"최종 항목: {len(entries)}개\n")

    print("[3/3] 요약 생성 및 텔레그램 발송 중...")
    summary = summarize_entries(entries)
    generated_at = datetime.now(KST)
    telegram_ok = send_to_telegram(summary, len(entries), generated_at)

    print("\n=== 완료 ===")
    print(f"  처리 항목: {len(entries)}개")
    print(f"  Telegram: {'OK' if telegram_ok else 'FAIL'}")

    if not telegram_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
