#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys as _sys; _sys.stdout.reconfigure(line_buffering=True)
"""
생각일기 분석 에이전트
- 특정 기간(N개월)의 생각일기 항목을 수집
- Claude AI로 장기 트렌드, 패턴, 성장 포인트 등 종합 분석
- 텔레그램으로 결과 발송
- 명령어: /생각분석 24개월
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

import anthropic

KST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Notion 헬퍼
# ---------------------------------------------------------------------------

def notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('NOTION_API_KEY', '')}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def fetch_pages_for_period(months: int, database_id: str) -> list:
    """N개월 전부터 현재까지의 생각일기 항목을 모두 가져온다."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=months * 30)).isoformat()
    filter_body = {
        "filter": {"timestamp": "created_time", "created_time": {"after": cutoff}},
        "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
    }
    all_pages = []
    try:
        while True:
            req = urllib.request.Request(
                f"https://api.notion.com/v1/databases/{database_id}/query",
                data=json.dumps(filter_body).encode("utf-8"),
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
        print(f"Notion API 오류 ({e.code}): {e.read().decode()}", file=sys.stderr)
        sys.exit(1)
    return all_pages


def get_page_text(page_id: str) -> str:
    req = urllib.request.Request(
        f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100",
        headers=notion_headers(),
    )
    try:
        with urllib.request.urlopen(req) as resp:
            blocks = json.loads(resp.read().decode()).get("results", [])
    except Exception:
        return ""
    lines = []
    for block in blocks:
        btype = block.get("type", "")
        for rt in block.get(btype, {}).get("rich_text", []):
            text = rt.get("plain_text", "").strip()
            if text:
                lines.append(text)
    return "\n".join(lines)


def extract_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(rt.get("plain_text", "") for rt in prop.get("title", [])).strip() or "(제목 없음)"
    return "(제목 없음)"


# ---------------------------------------------------------------------------
# 항목 수집 & 월별 그룹핑
# ---------------------------------------------------------------------------

def collect_entries(pages: list) -> list:
    """페이지에서 제목, 내용(축약), 생성일을 추출."""
    entries = []
    for page in pages:
        title = extract_title(page)
        content = get_page_text(page.get("id", ""))
        created_str = page.get("created_time", "")
        created_dt = None
        created_kst = ""
        if created_str:
            try:
                created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")).astimezone(KST)
                created_kst = created_dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
        entries.append({
            "title": title,
            "content": content,
            "created_kst": created_kst,
            "created_dt": created_dt,
            "year_month": created_dt.strftime("%Y-%m") if created_dt else "unknown",
        })
    return entries


def group_by_month(entries: list) -> dict:
    """entries를 연-월 기준으로 그룹핑."""
    groups = {}
    for e in entries:
        ym = e["year_month"]
        if ym not in groups:
            groups[ym] = []
        groups[ym].append(e)
    return dict(sorted(groups.items()))


def build_entries_text(entries: list, max_total_chars: int = 120000) -> str:
    """분석용 텍스트 생성. 총 길이가 너무 길면 내용을 점점 축약."""
    grouped = group_by_month(entries)

    # 1차: 내용 포함 (항목당 최대 400자)
    content_limit = 400
    text = _build_text(grouped, content_limit)
    if len(text) <= max_total_chars:
        return text

    # 2차: 내용 더 축약 (항목당 최대 150자)
    content_limit = 150
    text = _build_text(grouped, content_limit)
    if len(text) <= max_total_chars:
        return text

    # 3차: 제목만
    return _build_text(grouped, 0)


def _build_text(grouped: dict, content_limit: int) -> str:
    lines = []
    for ym, entries in grouped.items():
        lines.append(f"\n=== {ym} ({len(entries)}개 항목) ===")
        for e in entries:
            lines.append(f"  [{e['created_kst']}] {e['title']}")
            if content_limit > 0 and e["content"]:
                truncated = e["content"][:content_limit]
                if len(e["content"]) > content_limit:
                    truncated += "..."
                lines.append(f"    {truncated}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude AI 분석
# ---------------------------------------------------------------------------

def generate_analysis(entries_text: str, total_count: int, months: int, date_range: str) -> str:
    """Claude로 장기 생각일기 종합 분석."""
    client = anthropic.Anthropic()

    prompt = f"""다음은 최근 {months}개월간의 생각일기 항목들입니다 ({date_range}, 총 {total_count}개).

{entries_text}

---
위 생각일기들을 종합적으로 분석해서 아래 형식으로 작성해주세요.
마크다운이나 JSON 없이, 아래 구조의 순수 텍스트로 작성하세요.
각 섹션은 충실하게 작성하되, 전체 길이는 텔레그램 메시지에 맞게 간결하게 유지하세요.

[전체 개요]
기간, 항목 수, 전반적인 특징을 2~3문장으로 요약

[핵심 주제 TOP 5]
가장 많이 등장하거나 중요한 주제 5개를 빈도/중요도 순으로 정리
각 주제마다 한 줄 설명

[시간별 변화 흐름]
초기 → 중기 → 최근으로 관심사/고민이 어떻게 변화했는지 흐름 정리

[감정/에너지 패턴]
글에서 읽히는 감정적 흐름, 에너지 높낮이의 패턴

[핵심 인사이트 3가지]
데이터에서 발견되는 가장 중요한 인사이트 3개

[성장 포인트]
이 기간 동안 확인되는 성장이나 변화

[앞으로의 제안]
분석 결과를 바탕으로 한 구체적 제안 2~3개"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# 텔레그램 발송 (긴 메시지 분할)
# ---------------------------------------------------------------------------

def send_to_telegram(text: str, reply_to: int = None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("경고: 텔레그램 환경변수 누락", file=sys.stderr)
        return False

    # 4096자 제한 → 분할 발송
    chunks = split_message(text, 4096)
    success = True

    for i, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if i == 0 and reply_to:
            payload["reply_to_message_id"] = reply_to

        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read().decode())
                if not result.get("ok"):
                    print(f"텔레그램 발송 실패 (파트 {i+1}): {result}", file=sys.stderr)
                    success = False
        except Exception as e:
            print(f"텔레그램 발송 오류 (파트 {i+1}): {e}", file=sys.stderr)
            success = False

    if success:
        print(f"텔레그램 발송 완료 ({len(chunks)}개 메시지)")
    return success


def split_message(text: str, max_len: int = 4096) -> list:
    """텍스트를 줄 단위로 분할."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            if current:
                chunks.append(current.strip())
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks


# ---------------------------------------------------------------------------
# Supabase 헬퍼 (설정 로드용)
# ---------------------------------------------------------------------------

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")

def _sb_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

def _sb_headers() -> dict:
    return {
        "apikey": _sb_key(),
        "Authorization": f"Bearer {_sb_key()}",
        "Content-Type": "application/json",
    }

def load_diary_db_id() -> str:
    """Supabase agent_settings에서 생각일기 DB ID를 로드."""
    if not _sb_url() or not _sb_key():
        return os.environ.get("NOTION_DATABASE_ID", "")
    try:
        req = urllib.request.Request(
            f"{_sb_url()}/rest/v1/agent_settings?id=eq.1",
            headers=_sb_headers(),
        )
        with urllib.request.urlopen(req) as resp:
            rows = json.loads(resp.read().decode())
        if rows:
            db_id = rows[0].get("diary_notion_database_id") or ""
            if db_id:
                return db_id
    except Exception as e:
        print(f"Supabase 설정 로드 오류: {e}", file=sys.stderr)
    return os.environ.get("NOTION_DATABASE_ID", "")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    print("=== 생각일기 분석 에이전트 시작 ===\n")

    if not os.environ.get("NOTION_API_KEY"):
        print("오류: NOTION_API_KEY가 없습니다.", file=sys.stderr)
        sys.exit(1)

    # 파라미터 읽기 (GitHub Actions workflow input)
    months = int(os.environ.get("INPUT_MONTHS", "1"))
    reply_to = int(os.environ.get("INPUT_MSG_ID", "0")) or None

    diary_db_id = load_diary_db_id()
    if not diary_db_id:
        print("오류: 생각일기 Notion DB ID가 없습니다.", file=sys.stderr)
        sys.exit(1)

    print(f"분석 기간: {months}개월")
    print(f"생각일기 DB: {diary_db_id}\n")

    # 1단계: 항목 조회
    print(f"[1/3] 최근 {months}개월 생각일기 조회 중...")
    pages = fetch_pages_for_period(months, diary_db_id)
    print(f"조회된 페이지: {len(pages)}개\n")

    if not pages:
        msg = f"최근 {months}개월 내 생각일기 항목이 없습니다."
        print(msg)
        send_to_telegram(msg, reply_to)
        return

    # 2단계: 내용 수집
    print("[2/3] 내용 수집 중...")
    entries = collect_entries(pages)
    print(f"수집 항목: {len(entries)}개\n")

    # 날짜 범위 계산
    dates = [e["created_dt"] for e in entries if e["created_dt"]]
    if dates:
        date_range = f"{min(dates).strftime('%Y.%m.%d')} ~ {max(dates).strftime('%Y.%m.%d')}"
    else:
        date_range = f"최근 {months}개월"

    entries_text = build_entries_text(entries)
    print(f"분석 텍스트 길이: {len(entries_text):,}자\n")

    # 3단계: AI 분석
    print("[3/3] Claude AI 종합 분석 중...")
    analysis = generate_analysis(entries_text, len(entries), months, date_range)

    # 텔레그램 발송
    now = datetime.now(KST)
    header = (
        f"<b>🔍 생각일기 종합 분석</b>\n"
        f"<i>{date_range} · {len(entries)}개 항목 · {months}개월</i>\n"
        f"<i>{now.strftime('%Y/%m/%d %H:%M')} KST</i>\n\n"
    )
    full_message = header + analysis

    ok = send_to_telegram(full_message, reply_to)

    print("\n=== 완료 ===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
