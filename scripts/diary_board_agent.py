#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys as _sys; _sys.stdout.reconfigure(line_buffering=True)  # GitHub Actions 로그 순서 보장
"""
생각일기 이사회 에이전트
- 최근 N시간 생각일기 항목 수집
- 브리핑: 항목 수, 제목 목록, 주요 내용 요약
- 이사회 멤버(Supabase에서 동적 로드)별 의견
- 합의 사항 / 액션 아이템 도출
- 텔레그램 발송 + Notion 이사회DB + Supabase 기록 저장
- 이사회 후 각 멤버의 personality 자동 업데이트
- 텔레그램 커맨드: /생각일기 N시간 → 즉시 이사회 분석
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
# Supabase 헬퍼
# ---------------------------------------------------------------------------

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")

def _sb_key() -> str:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

def _sb_headers(extra: dict = None) -> dict:
    h = {
        "apikey": _sb_key(),
        "Authorization": f"Bearer {_sb_key()}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h

def _supabase_get(path: str) -> list:
    if not _sb_url() or not _sb_key():
        return []
    req = urllib.request.Request(
        f"{_sb_url()}{path}",
        headers=_sb_headers(),
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Supabase GET 오류 ({path}): {e}", file=sys.stderr)
        return []

def _supabase_post(path: str, data: dict) -> bool:
    if not _sb_url() or not _sb_key():
        return False
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{_sb_url()}{path}",
        data=payload,
        headers=_sb_headers({"Prefer": "return=minimal"}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        print(f"Supabase POST 오류: {e}", file=sys.stderr)
        return False

def _supabase_patch(path: str, data: dict) -> bool:
    if not _sb_url() or not _sb_key():
        return False
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{_sb_url()}{path}",
        data=payload,
        headers=_sb_headers({"Prefer": "return=minimal"}),
        method="PATCH",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"Supabase PATCH 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 설정 & 멤버 로드
# ---------------------------------------------------------------------------

DEFAULT_MEMBERS = [
    {"key": "roi",          "name": "💰 냉정한 이익주의자", "role": "ROI · 데이터",   "description": "ROI와 데이터를 중심으로 냉철하게 판단하는 분석가",              "personality": ""},
    {"key": "romantic",     "name": "🌈 낭만 긍정주의자",   "role": "가능성 · 도전",  "description": "가능성과 설렘에 집중하며 도전을 응원하는 꿈꾸는 사람",          "personality": ""},
    {"key": "conservative", "name": "🛡️ 보수적 조심주의자", "role": "리스크 · 안전",  "description": "리스크와 안전을 최우선으로 검토하는 신중한 이",                 "personality": ""},
    {"key": "zen",          "name": "🧘 내면 평온주의자",   "role": "감정 · 균형추",  "description": "감정과 내면의 균형을 중시하며 삶의 질을 살피는 이",              "personality": ""},
    {"key": "challenger",   "name": "🚀 도전과 발전주의자", "role": "성장 · 돌파",    "description": "성장과 돌파를 추구하며 현실에 안주하지 않는 불굴의 도전가",      "personality": ""},
]

def load_settings() -> dict:
    default = {
        "board_enabled": True,
        "board_run_every_hours": 3,
        "diary_notion_database_id": os.environ.get("NOTION_DATABASE_ID", ""),
        "board_notion_db_id": os.environ.get("BOARD_NOTION_DATABASE_ID", ""),
    }
    rows = _supabase_get("/rest/v1/agent_settings?id=eq.1")
    if not rows:
        return default
    s = rows[0]
    # 생각일기 DB: Supabase 설정 우선, 환경변수는 fallback
    diary_db = (
        s.get("diary_notion_database_id")
        or os.environ.get("NOTION_DATABASE_ID")
        or ""
    )
    return {
        "board_enabled": s.get("board_enabled", True),
        "board_run_every_hours": int(s.get("board_run_every_hours", 3)),
        "diary_notion_database_id": diary_db,
        "board_notion_db_id": s.get("board_notion_db_id") or os.environ.get("BOARD_NOTION_DATABASE_ID", ""),
        "board_command_hours": int(s.get("board_command_hours") or 0),
        "board_command_msg_id": int(s.get("board_command_msg_id") or 0),
    }

def load_board_members() -> list:
    """Supabase board_members에서 활성 멤버 로드. 없으면 기본값."""
    rows = _supabase_get("/rest/v1/board_members?enabled=eq.true&order=sort_order.asc")
    if rows:
        print(f"  Supabase에서 {len(rows)}명 로드")
        return rows
    print("  board_members 테이블 없거나 비어있음 — 기본 멤버 사용")
    return DEFAULT_MEMBERS


# ---------------------------------------------------------------------------
# Notion 생각일기 조회
# ---------------------------------------------------------------------------

def notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('NOTION_API_KEY', '')}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }

def fetch_recent_pages(hours: int, database_id: str = "") -> list:
    if not database_id:
        database_id = os.environ.get("NOTION_DATABASE_ID", "")
    if not database_id:
        print("오류: 생각일기 Notion DB ID가 없습니다. 웹 설정에서 'diary_notion_database_id'를 입력해주세요.", file=sys.stderr)
        sys.exit(1)

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    filter_body = {
        "filter": {"timestamp": "created_time", "created_time": {"after": cutoff}},
        "sorts": [{"timestamp": "created_time", "direction": "descending"}],
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

def collect_entries(pages: list) -> list:
    entries = []
    for page in pages:
        title = extract_title(page)
        content = get_page_text(page.get("id", ""))
        created_str = page.get("created_time", "")
        created_kst = ""
        if created_str:
            try:
                dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")).astimezone(KST)
                created_kst = dt.strftime("%m/%d %H:%M")
            except ValueError:
                pass
        entries.append({"title": title, "content": content, "created_kst": created_kst})
        print(f"  - {title} ({created_kst})")
    return entries


# ---------------------------------------------------------------------------
# Claude AI — 브리핑 + 이사회 의견 + 액션 아이템
# ---------------------------------------------------------------------------

def generate_board_report(entries: list, members: list) -> dict:
    client = anthropic.Anthropic()

    entries_text = ""
    for i, e in enumerate(entries, 1):
        entries_text += f"\n\n[항목 {i}] {e['title']} ({e['created_kst']})\n"
        if e["content"]:
            entries_text += e["content"][:800]

    member_keys = [m["key"] for m in members]
    member_instructions = ""
    for m in members:
        desc = m.get("description", "")
        personality = m.get("personality", "")
        persona = desc
        if personality:
            persona += f"\n  (지금까지 파악된 특성: {personality})"
        member_instructions += f'  "{m["key"]}": {m["name"]} — {persona}\n'

    keys_json = json.dumps(member_keys, ensure_ascii=False)

    prompt = f"""다음은 생각일기의 최근 항목들입니다.
{entries_text}

---
이사회 형식으로 분석해주세요. 반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트는 쓰지 마세요.

이사회 멤버:
{member_instructions}

{{
  "briefing": {{
    "summary": "전체 내용을 2~3문장으로 핵심 요약",
    "titles": ["항목1 제목", "항목2 제목"],
    "key_points": ["주요 내용 1", "주요 내용 2", "주요 내용 3"]
  }},
  "opinions": {{
    {', '.join(f'"{k}": "해당 이사 관점에서 1~2문장 의견"' for k in member_keys)}
  }},
  "consensus": "이사들이 공통으로 동의하는 핵심 관점 (없으면 빈 문자열)",
  "action_items": ["구체적인 제안/액션 아이템 1", "제안 2"]
}}"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"briefing": {"summary": raw, "titles": [], "key_points": []}, "opinions": {}, "consensus": "", "action_items": []}


# ---------------------------------------------------------------------------
# personality 자동 업데이트
# ---------------------------------------------------------------------------

def update_member_personalities(members: list, report: dict) -> None:
    """각 멤버의 최신 의견을 바탕으로 personality를 AI로 업데이트."""
    client = anthropic.Anthropic()
    opinions = report.get("opinions", {})

    for m in members:
        key = m["key"]
        opinion = opinions.get(key, "").strip()
        if not opinion:
            continue

        existing = m.get("personality", "").strip()
        prompt = f"""이사회 멤버 "{m['name']}"의 이번 의견입니다:
"{opinion}"

기존에 파악된 특성:
"{existing if existing else '아직 없음'}"

이번 의견을 반영하여 이 이사의 personality를 1~2문장으로 업데이트해주세요.
실제로 드러난 성향, 가치관, 언어 패턴을 바탕으로 구체적으로 작성해주세요.
JSON 없이 텍스트만 반환하세요."""

        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            new_personality = msg.content[0].text.strip()
            member_id = m.get("id")
            if member_id:
                ok = _supabase_patch(
                    f"/rest/v1/board_members?id=eq.{member_id}",
                    {"personality": new_personality, "updated_at": datetime.now(timezone.utc).isoformat()},
                )
                status = "✓" if ok else "✗"
                print(f"  {status} {m['name']} personality 업데이트")
            else:
                print(f"  - {m['name']}: id 없음 (기본 멤버), 업데이트 생략")
        except Exception as e:
            print(f"  {m['name']} personality 업데이트 오류: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 텔레그램 발송
# ---------------------------------------------------------------------------

def send_to_telegram(report: dict, members: list, entry_count: int, run_every: int, now: datetime, reply_to: int = None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("경고: 텔레그램 환경변수 누락", file=sys.stderr)
        return False

    briefing = report.get("briefing", {})
    opinions = report.get("opinions", {})
    consensus = report.get("consensus", "").strip()
    action_items = report.get("action_items", [])

    time_str = now.strftime("%m/%d %H:%M")
    lines = [f"<b>🏛️ 생각일기 이사회 · {time_str} KST</b>"]

    # 브리핑
    lines.append(f"\n<b>📋 브리핑 (최근 {run_every}시간 · {entry_count}개 항목)</b>")
    lines.append(briefing.get("summary", ""))

    titles = briefing.get("titles", [])
    if titles:
        lines.append("\n<i>항목 목록</i>")
        for t in titles:
            lines.append(f"  • {t}")

    key_points = briefing.get("key_points", [])
    if key_points:
        lines.append("\n<i>주요 내용</i>")
        for p in key_points:
            lines.append(f"  · {p}")

    # 이사 의견
    lines.append("\n<b>💬 이사회 의견</b>")
    member_map = {m["key"]: m["name"] for m in members}
    for key, name in member_map.items():
        opinion = opinions.get(key, "").strip()
        if opinion:
            lines.append(f"\n<b>{name}</b>\n{opinion}")

    # 합의 + 액션 아이템
    if consensus:
        lines.append(f"\n<b>🤝 합의 사항</b>\n{consensus}")

    if action_items:
        lines.append("\n<b>✅ 액션 아이템</b>")
        for item in action_items:
            lines.append(f"  • {item}")

    message = "\n".join(lines).strip()
    tg_payload = {
        "chat_id": chat_id,
        "text": message[:4096],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_to:
        tg_payload["reply_to_message_id"] = reply_to
    payload = json.dumps(tg_payload).encode("utf-8")

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
# Notion 이사회 DB 저장
# ---------------------------------------------------------------------------

def save_to_board_notion_db(report: dict, members: list, entry_count: int, run_every: int, now: datetime, db_id: str) -> bool:
    if not db_id:
        return False

    briefing = report.get("briefing", {})
    opinions = report.get("opinions", {})
    consensus = report.get("consensus", "")
    action_items = report.get("action_items", [])

    title = f"이사회 보고 · {now.strftime('%Y/%m/%d %H:%M')} KST"
    children = [
        {"object": "block", "type": "callout", "callout": {
            "icon": {"type": "emoji", "emoji": "🏛️"},
            "color": "gray_background",
            "rich_text": [{"type": "text", "text": {"content": f"최근 {run_every}시간 · {entry_count}개 항목 | {now.strftime('%Y-%m-%d %H:%M')} KST"}}],
        }},
        {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📋 브리핑"}}]}},
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": briefing.get("summary", "")}}]}},
    ]

    titles = briefing.get("titles", [])
    if titles:
        children.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": "항목 목록"}, "annotations": {"bold": True}}]
        }})
        for t in titles:
            children.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {
                "rich_text": [{"type": "text", "text": {"content": t}}]
            }})

    key_points = briefing.get("key_points", [])
    if key_points:
        children.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": "주요 내용"}}]}})
        for p in key_points:
            children.append({"object": "block", "type": "numbered_list_item", "numbered_list_item": {
                "rich_text": [{"type": "text", "text": {"content": p}}]
            }})

    children.append({"object": "block", "type": "divider", "divider": {}})
    children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💬 이사회 의견"}}]}})

    member_map = {m["key"]: m["name"] for m in members}
    for key, name in member_map.items():
        opinion = opinions.get(key, "").strip()
        if opinion:
            children.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": name}}]}})
            children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": opinion}}]}})

    if consensus:
        children.append({"object": "block", "type": "divider", "divider": {}})
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🤝 합의 사항"}}]}})
        children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": consensus}}]}})

    if action_items:
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "✅ 액션 아이템"}}]}})
        for item in action_items:
            children.append({"object": "block", "type": "to_do", "to_do": {
                "checked": False,
                "rich_text": [{"type": "text", "text": {"content": item}}],
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
            print(f"Notion 이사회 DB 저장 완료: {result.get('url', '')}")
            return True
    except urllib.error.HTTPError as e:
        print(f"Notion 이사회 DB 저장 실패 ({e.code}): {e.read().decode()}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Notion 이사회 DB 저장 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Supabase board_reports 저장
# ---------------------------------------------------------------------------

def save_to_supabase(report: dict, entry_count: int, run_every: int, now: datetime) -> bool:
    opinions = report.get("opinions", {})
    briefing = report.get("briefing", {})
    data = {
        "created_at": now.astimezone(timezone.utc).isoformat(),
        "entry_count": entry_count,
        "run_every_hours": run_every,
        "summary": briefing.get("summary", ""),
        # 동적 멤버 지원: 모든 의견/브리핑/액션 아이템을 JSONB로 저장
        "opinions":     opinions,
        "briefing":     briefing,
        "action_items": report.get("action_items", []),
        # 기존 고정 컬럼 호환 유지 (기본 5인)
        "opinion_roi":          opinions.get("roi", ""),
        "opinion_romantic":     opinions.get("romantic", ""),
        "opinion_conservative": opinions.get("conservative", ""),
        "opinion_zen":          opinions.get("zen", ""),
        "opinion_challenger":   opinions.get("challenger", ""),
    }
    ok = _supabase_post("/rest/v1/board_reports", data)
    if ok:
        print("Supabase board_reports 저장 완료")
    return ok


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    print("=== 생각일기 이사회 에이전트 시작 ===\n")

    if not os.environ.get("NOTION_API_KEY"):
        print("오류: NOTION_API_KEY가 없습니다.", file=sys.stderr)
        sys.exit(1)

    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    settings = load_settings()
    diary_db_id = settings["diary_notion_database_id"]
    print(f"설정: enabled={settings['board_enabled']}, run_every={settings['board_run_every_hours']}h, manual={is_manual}")
    print(f"  생각일기 DB: {diary_db_id or '(미설정)'}\n")

    # 멤버 로드
    print("[멤버] 이사회 멤버 로드 중...")
    members = load_board_members()
    print(f"  → {len(members)}명\n")

    # 텔레그램 커맨드 요청 확인 (웹훅이 저장해둔 값)
    command_hours = settings.get("board_command_hours", 0)
    command_msg_id = settings.get("board_command_msg_id", 0)
    is_command = command_hours > 0

    if is_command:
        run_every = command_hours
        print(f"[커맨드] /생각일기 {run_every}시간 요청 — 즉시 실행\n")
        # 중복 실행 방지: 즉시 초기화
        _supabase_patch("/rest/v1/agent_settings?id=eq.1", {
            "board_command_hours": 0, "board_command_msg_id": 0
        })
    else:
        # 스케줄 실행 체크
        if not settings["board_enabled"] and not is_manual:
            print("이사회 에이전트 비활성화 상태. 종료.")
            return

        run_every = settings["board_run_every_hours"]
        if run_every > 1 and not is_manual:
            current_hour_utc = datetime.now(timezone.utc).hour
            if current_hour_utc % run_every != 0:
                print(f"현재 {current_hour_utc}시 (UTC) — {run_every}시간 간격 미해당. 건너뜀.")
                return

    print(f"[1/4] 최근 {run_every}시간 생각일기 조회 중...")
    pages = fetch_recent_pages(hours=run_every, database_id=diary_db_id)
    print(f"조회된 페이지: {len(pages)}개\n")

    if not pages:
        print(f"최근 {run_every}시간 내 새 항목 없음. 발송 생략.")
        return

    print("[2/4] 내용 수집 중...")
    entries = collect_entries(pages)
    print(f"수집 항목: {len(entries)}개\n")

    print("[3/4] 이사회 보고서 생성 중...")
    report = generate_board_report(entries, members)
    now = datetime.now(KST)

    print("[4/4] 발송 및 저장 중...")
    reply_to = command_msg_id if is_command else None
    ok = send_to_telegram(report, members, len(entries), run_every, now, reply_to=reply_to)

    board_db_id = settings.get("board_notion_db_id", "")
    if board_db_id:
        save_to_board_notion_db(report, members, len(entries), run_every, now, board_db_id)
    else:
        print("BOARD_NOTION_DATABASE_ID 미설정 — Notion 저장 생략")

    save_to_supabase(report, len(entries), run_every, now)

    print("\n[후처리] 이사 personality 업데이트 중...")
    update_member_personalities(members, report)

    print("\n=== 완료 ===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
