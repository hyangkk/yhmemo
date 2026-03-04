#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys as _sys; _sys.stdout.reconfigure(line_buffering=True)
"""
생각일기 분석 에이전트
- 특정 기간(N개월)의 생각일기 항목을 수집
- Claude AI로 장기 트렌드, 패턴, 성장 포인트 등 종합 분석
- Notion 이사회 DB에 분석 결과 저장
- 텔레그램에 완료 알림 + Notion 링크 발송
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

def generate_analysis(entries_text: str, total_count: int, months: int, date_range: str) -> dict:
    """Claude로 장기 생각일기 종합 분석. JSON dict 반환."""
    client = anthropic.Anthropic()

    prompt = f"""다음은 최근 {months}개월간의 생각일기 항목들입니다 ({date_range}, 총 {total_count}개).

{entries_text}

---
위 생각일기들을 종합 분석해서 아래 JSON 형식으로만 응답하세요.

작성 규칙:
- overview: 3~4문장 (기간, 항목 수, 전반적 특징)
- top_themes: 5~7개 (주제명 + 1~2문장 설명)
- timeline_flow: 4~6문장 (초기→중기→최근 흐름)
- emotion_pattern: 3~4문장
- recurring_patterns: 3~5개
- recurring_problems: 3~5개
- key_insights: 3~5개 (각 1~2문장)
- growth_points: 3~4문장
- suggestions: 3~5개 (각 1~2문장, 구체적으로)

{{
  "overview": "...",
  "top_themes": [{{"theme": "주제명", "description": "설명"}}],
  "timeline_flow": "...",
  "emotion_pattern": "...",
  "recurring_patterns": ["..."],
  "recurring_problems": ["..."],
  "key_insights": ["..."],
  "growth_points": "...",
  "suggestions": ["..."]
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # 응답이 잘렸는지 확인
    if message.stop_reason == "max_tokens":
        print("경고: Claude 응답이 max_tokens로 잘림, 복구 시도", file=sys.stderr)

    # 코드블록 제거
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    # JSON 파싱 시도
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 잘린 JSON 복구 시도: 닫히지 않은 괄호를 닫아본다
    repaired = _try_repair_json(raw)
    if repaired is not None:
        print("잘린 JSON 복구 성공")
        return repaired

    # 최후 수단: 텍스트를 overview로
    print("JSON 파싱 실패 — 텍스트로 대체", file=sys.stderr)
    return {"overview": raw[:2000], "top_themes": [], "timeline_flow": "", "emotion_pattern": "",
            "recurring_patterns": [], "recurring_problems": [], "key_insights": [],
            "growth_points": "", "suggestions": []}


def _try_repair_json(raw: str) -> dict | None:
    """잘린 JSON을 닫아서 복구를 시도한다."""
    # 마지막 완전한 값 위치를 찾아 잘라낸 뒤 괄호를 닫는다
    import re
    # 문자열 끝에서 불완전한 부분 제거
    # 마지막 완성된 키-값 쌍 또는 배열 원소까지만 남기기
    text = raw.rstrip()

    # 끝에 열린 문자열이 있으면 닫기
    for attempt in range(5):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 끝에서 불완전한 부분을 점진적으로 제거
        # 마지막 , 또는 완전한 값 이후를 잘라냄
        last_comma = text.rfind(",")
        last_close_bracket = max(text.rfind("]"), text.rfind("}"), text.rfind('"'))

        if last_comma > last_close_bracket:
            text = text[:last_comma]
        elif last_close_bracket > 0:
            text = text[:last_close_bracket + 1]
        else:
            break

        # 닫히지 않은 괄호 수 계산하여 닫기
        opens = text.count("[") - text.count("]")
        opens_curly = text.count("{") - text.count("}")
        text = text + "]" * opens + "}" * opens_curly

    return None


# ---------------------------------------------------------------------------
# Notion 이사회 DB에 분석 결과 저장
# ---------------------------------------------------------------------------

def _text_block(block_type: str, content: str) -> dict:
    """Notion 텍스트 블록 생성 헬퍼. 2000자 제한 처리."""
    content = content[:2000] if len(content) > 2000 else content
    return {"object": "block", "type": block_type, block_type: {
        "rich_text": [{"type": "text", "text": {"content": content}}]
    }}


def save_to_notion(analysis: dict, entry_count: int, months: int, date_range: str, now: datetime, db_id: str) -> str | None:
    """분석 결과를 Notion 이사회 DB에 저장. 성공 시 페이지 URL 반환."""
    if not db_id:
        print("BOARD_NOTION_DATABASE_ID 미설정 — Notion 저장 불가", file=sys.stderr)
        return None

    title = f"생각분석 · {date_range} ({months}개월)"
    children = [
        {"object": "block", "type": "callout", "callout": {
            "icon": {"type": "emoji", "emoji": "🔍"},
            "color": "blue_background",
            "rich_text": [{"type": "text", "text": {"content": f"{date_range} · {entry_count}개 항목 · {months}개월 분석 | {now.strftime('%Y-%m-%d %H:%M')} KST"}}],
        }},
    ]

    # 전체 개요
    children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📋 전체 개요"}}]}})
    children.append(_text_block("paragraph", analysis.get("overview", "")))

    # 핵심 주제 TOP 5
    top_themes = analysis.get("top_themes", [])
    if top_themes:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🏷️ 핵심 주제 TOP 5"}}]}})
        for t in top_themes:
            if isinstance(t, dict):
                text = f"{t.get('theme', '')} — {t.get('description', '')}"
            else:
                text = str(t)
            children.append(_text_block("numbered_list_item", text))

    # 시간별 변화 흐름
    timeline = analysis.get("timeline_flow", "")
    if timeline:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📈 시간별 변화 흐름"}}]}})
        children.append(_text_block("paragraph", timeline))

    # 감정/에너지 패턴
    emotion = analysis.get("emotion_pattern", "")
    if emotion:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💫 감정/에너지 패턴"}}]}})
        children.append(_text_block("paragraph", emotion))

    children.append({"object": "block", "type": "divider", "divider": {}})

    # 자주 나타나는 패턴 및 공통점
    patterns = analysis.get("recurring_patterns", [])
    if patterns:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🔄 자주 나타나는 패턴 및 공통점"}}]}})
        for p in patterns:
            children.append(_text_block("bulleted_list_item", str(p)))

    # 반복되는 문제점
    problems = analysis.get("recurring_problems", [])
    if problems:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "⚠️ 반복되는 문제점"}}]}})
        for p in problems:
            children.append(_text_block("bulleted_list_item", str(p)))

    children.append({"object": "block", "type": "divider", "divider": {}})

    # 핵심 인사이트
    insights = analysis.get("key_insights", [])
    if insights:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💡 핵심 인사이트"}}]}})
        for item in insights:
            children.append(_text_block("numbered_list_item", str(item)))

    # 성장 포인트
    growth = analysis.get("growth_points", "")
    if growth:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🌱 성장 포인트"}}]}})
        children.append(_text_block("paragraph", growth))

    # 앞으로의 제안
    suggestions = analysis.get("suggestions", [])
    if suggestions:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "✅ 앞으로의 제안"}}]}})
        for item in suggestions:
            children.append({"object": "block", "type": "to_do", "to_do": {
                "checked": False,
                "rich_text": [{"type": "text", "text": {"content": str(item)}}],
            }})

    page_data = {
        "parent": {"database_id": db_id},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        "children": children,
    }

    req = urllib.request.Request(
        "https://api.notion.com/v1/pages",
        data=json.dumps(page_data, ensure_ascii=False).encode("utf-8"),
        headers=notion_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
            url = result.get("url", "")
            print(f"Notion 저장 완료: {url}")
            return url
    except urllib.error.HTTPError as e:
        print(f"Notion 저장 실패 ({e.code}): {e.read().decode()}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Notion 저장 오류: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 텔레그램 알림 (링크만 발송)
# ---------------------------------------------------------------------------

def send_to_telegram(text: str, reply_to: int = None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("경고: 텔레그램 환경변수 누락", file=sys.stderr)
        return False

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_to:
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
            if result.get("ok"):
                print("텔레그램 발송 완료")
                return True
            print(f"텔레그램 발송 실패: {result}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"텔레그램 발송 오류: {e}", file=sys.stderr)
        return False


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

def load_settings() -> dict:
    """Supabase agent_settings에서 설정 로드."""
    default = {
        "diary_notion_database_id": os.environ.get("NOTION_DATABASE_ID", ""),
        "board_notion_db_id": os.environ.get("BOARD_NOTION_DATABASE_ID", ""),
    }
    if not _sb_url() or not _sb_key():
        return default
    try:
        req = urllib.request.Request(
            f"{_sb_url()}/rest/v1/agent_settings?id=eq.1",
            headers=_sb_headers(),
        )
        with urllib.request.urlopen(req) as resp:
            rows = json.loads(resp.read().decode())
        if rows:
            s = rows[0]
            return {
                "diary_notion_database_id": s.get("diary_notion_database_id") or default["diary_notion_database_id"],
                "board_notion_db_id": s.get("board_notion_db_id") or default["board_notion_db_id"],
            }
    except Exception as e:
        print(f"Supabase 설정 로드 오류: {e}", file=sys.stderr)
    return default


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

    settings = load_settings()
    diary_db_id = settings["diary_notion_database_id"]
    board_db_id = settings["board_notion_db_id"]

    if not diary_db_id:
        print("오류: 생각일기 Notion DB ID가 없습니다.", file=sys.stderr)
        sys.exit(1)

    print(f"분석 기간: {months}개월")
    print(f"생각일기 DB: {diary_db_id}")
    print(f"이사회 DB: {board_db_id or '(미설정)'}\n")

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
    now = datetime.now(KST)

    # Notion 이사회 DB에 저장
    notion_url = save_to_notion(analysis, len(entries), months, date_range, now, board_db_id)

    # 텔레그램에 완료 알림 + 핵심 요약
    tg_msg = f"🔍 <b>생각일기 종합 분석 완료</b>\n<i>{date_range} · {len(entries)}개 항목 · {months}개월</i>\n"

    # 핵심 요약 포함
    overview = analysis.get("overview", "")
    if overview:
        tg_msg += f"\n📋 <b>개요</b>\n{overview}\n"

    top_themes = analysis.get("top_themes", [])
    if top_themes:
        themes_str = ", ".join(
            t.get("theme", str(t)) if isinstance(t, dict) else str(t)
            for t in top_themes[:5]
        )
        tg_msg += f"\n🏷️ <b>핵심 주제</b>\n{themes_str}\n"

    insights = analysis.get("key_insights", [])
    if insights:
        tg_msg += "\n💡 <b>핵심 인사이트</b>\n"
        for i, item in enumerate(insights[:3], 1):
            tg_msg += f"{i}. {item}\n"

    if notion_url:
        tg_msg += f"\n👉 <a href=\"{notion_url}\">전체 분석 보기</a>"
        ok = send_to_telegram(tg_msg, reply_to)
    else:
        tg_msg += "\n⚠️ Notion 저장에 실패했습니다."
        ok = send_to_telegram(tg_msg, reply_to)

    print("\n=== 완료 ===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
