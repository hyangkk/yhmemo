#!/usr/bin/env python3
"""
생각일기 이사회 에이전트
- 매 3시간마다 GitHub Actions에 의해 자동 실행
- Notion '생각일기 DB'에서 최근 3시간 이내 항목 수집
- Claude AI로 요약 + 5인 가상 이사회 의견 생성
- 새 항목 없으면 발송 생략
- 텔레그램으로 발송
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

import anthropic

KST = timezone(timedelta(hours=9))

# (json_key, 표시 이름, Claude에 전달할 역할 설명)
BOARD_MEMBERS = [
    ("roi",          "💰 냉정한 이익주의자", "ROI와 데이터를 중심으로 냉철하게 판단하는 분석가"),
    ("romantic",     "🌈 낭만 긍정주의자",   "가능성과 설렘에 집중하며 도전을 응원하는 꿈꾸는 사람"),
    ("conservative", "🛡️ 보수적 조심주의자", "리스크와 안전을 최우선으로 검토하는 신중한 이"),
    ("zen",          "🧘 내면 평온주의자",   "감정과 내면의 균형을 중시하며 삶의 질을 살피는 이"),
    ("challenger",   "🚀 도전과 발전주의자", "성장과 돌파를 추구하며 현실에 안주하지 않는 불굴의 도전가"),
]


# ---------------------------------------------------------------------------
# 1. Notion 조회
# ---------------------------------------------------------------------------

def notion_headers() -> dict:
    token = os.environ.get("NOTION_API_KEY", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def fetch_recent_pages(hours: int = 3) -> list:
    """최근 N시간 이내 생성된 생각일기 항목 조회."""
    database_id = os.environ.get("NOTION_DATABASE_ID", "")
    if not database_id:
        print("오류: NOTION_DATABASE_ID가 없습니다.", file=sys.stderr)
        sys.exit(1)

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    filter_body = {
        "filter": {
            "timestamp": "created_time",
            "created_time": {"after": cutoff},
        },
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
    }

    all_pages = []
    try:
        while True:
            payload = json.dumps(filter_body).encode("utf-8")
            req = urllib.request.Request(
                f"https://api.notion.com/v1/databases/{database_id}/query",
                data=payload,
                headers=notion_headers(),
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
            all_pages.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            filter_body["start_cursor"] = data.get("next_cursor")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"Notion API 오류 ({e.code}): {body}", file=sys.stderr)
        sys.exit(1)

    return all_pages


def get_page_text(page_id: str) -> str:
    """페이지 블록에서 텍스트 추출."""
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


def collect_entries(pages: list) -> list:
    entries = []
    for page in pages:
        page_id = page.get("id", "")
        title = extract_title(page)
        content = get_page_text(page_id)
        created_str = page.get("created_time", "")
        created_kst = ""
        if created_str:
            try:
                dt = datetime.fromisoformat(
                    created_str.replace("Z", "+00:00")
                ).astimezone(KST)
                created_kst = dt.strftime("%H:%M")
            except ValueError:
                pass
        entries.append({"title": title, "content": content, "created_kst": created_kst})
        print(f"  - {title} ({created_kst})")
    return entries


# ---------------------------------------------------------------------------
# 2. Claude AI — 요약 + 이사회 의견
# ---------------------------------------------------------------------------

def generate_board_report(entries: list) -> dict:
    """요약 및 5인 이사회 의견을 JSON으로 반환."""
    client = anthropic.Anthropic()

    entries_text = ""
    for i, e in enumerate(entries, 1):
        entries_text += f"\n\n[항목 {i}] {e['title']} ({e['created_kst']})\n"
        if e["content"]:
            entries_text += e["content"][:1000]

    member_instructions = "\n".join(
        f'  "{key}": {label}({role})로서 1~2문장 의견'
        for key, label, role in BOARD_MEMBERS
    )

    prompt = f"""다음은 생각일기의 최근 항목들입니다.
{entries_text}

---
아래 JSON 형식으로만 응답해주세요. JSON 외 다른 텍스트는 쓰지 마세요.

{{
  "summary": "항목들의 핵심을 2~3문장으로 간결하게 요약",
{member_instructions}
}}"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # 코드블록 제거
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 파싱 실패 시 raw 텍스트를 summary에 담아 반환
        return {key: "" for key, _, _ in BOARD_MEMBERS} | {"summary": raw}


# ---------------------------------------------------------------------------
# 3. 텔레그램 발송
# ---------------------------------------------------------------------------

def send_to_telegram(report: dict, entry_count: int, now: datetime) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("경고: 텔레그램 환경변수 누락", file=sys.stderr)
        return False

    time_str = now.strftime("%m/%d %H:%M")
    lines = [
        f"<b>📋 생각일기 이사회 보고 · {time_str} KST</b>",
        f"<i>최근 3시간 항목 {entry_count}개</i>\n",
        f"<b>요약</b>\n{report.get('summary', '')}",
    ]

    for key, label, _ in BOARD_MEMBERS:
        opinion = report.get(key, "").strip()
        if opinion:
            lines.append(f"\n<b>{label}</b>\n{opinion}")

    message = "\n".join(lines).strip()

    payload = json.dumps({
        "chat_id": chat_id,
        "text": message[:4096],
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
            print(f"텔레그램 발송 실패: {result}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"텔레그램 발송 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    print("=== 생각일기 이사회 에이전트 시작 ===\n")

    if not os.environ.get("NOTION_API_KEY"):
        print("오류: NOTION_API_KEY가 없습니다.", file=sys.stderr)
        sys.exit(1)

    print("[1/3] 최근 3시간 생각일기 조회 중...")
    pages = fetch_recent_pages(hours=3)
    print(f"조회된 페이지: {len(pages)}개\n")

    if not pages:
        print("최근 3시간 내 새 항목 없음. 발송 생략.")
        return

    print("[2/3] 내용 수집 중...")
    entries = collect_entries(pages)
    print(f"수집 항목: {len(entries)}개\n")

    print("[3/3] 이사회 보고서 생성 및 텔레그램 발송 중...")
    report = generate_board_report(entries)
    now = datetime.now(KST)
    ok = send_to_telegram(report, len(entries), now)

    print("\n=== 완료 ===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
