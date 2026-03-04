#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys as _sys; _sys.stdout.reconfigure(line_buffering=True)
"""
이사회 자연어 대화 에이전트
- 이사회 관련 상호작용 후 30분간 자연어 대화 모드 활성화
- 의도 분류: 지시(기억해), 질문(물어보기), 일반 대화
- 3-tier 메모리: memory(최근 raw) → meta_memory(장기 요약) → user_directives(사용자 지시)
"""

import os
import sys
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

import anthropic

KST = timezone(timedelta(hours=9))

MEMORY_RAW_LIMIT = 6000       # raw memory가 이 글자수 넘으면 통합
META_MEMORY_LIMIT = 20000     # meta_memory 최대 글자수


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
    req = urllib.request.Request(f"{_sb_url()}{path}", headers=_sb_headers())
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Supabase GET 오류 ({path}): {e}", file=sys.stderr)
        return []

def _supabase_patch(path: str, data: dict) -> bool:
    if not _sb_url() or not _sb_key():
        return False
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{_sb_url()}{path}", data=payload,
        headers=_sb_headers({"Prefer": "return=minimal"}), method="PATCH",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"Supabase PATCH 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 멤버 로드
# ---------------------------------------------------------------------------

def load_board_members() -> list:
    rows = _supabase_get("/rest/v1/board_members?enabled=eq.true&order=sort_order.asc")
    if rows:
        print(f"  Supabase에서 {len(rows)}명 로드")
        return rows
    print("  board_members 비어있음")
    return []


# ---------------------------------------------------------------------------
# 메모리 통합 (memory → meta_memory)
# ---------------------------------------------------------------------------

def consolidate_memory(member: dict, client: anthropic.Anthropic) -> tuple[str, str]:
    """raw memory가 MEMORY_RAW_LIMIT를 초과하면 오래된 내용을 meta_memory로 통합.
    Returns (updated_memory, updated_meta_memory)."""
    memory = member.get("memory", "").strip()
    meta_memory = member.get("meta_memory", "").strip()

    if len(memory) <= MEMORY_RAW_LIMIT:
        return memory, meta_memory

    lines = memory.split("\n")
    # 최근 절반만 남기고 나머지를 통합 대상으로
    midpoint = len(lines) // 2
    old_lines = lines[:midpoint]
    keep_lines = lines[midpoint:]

    old_text = "\n".join(old_lines).strip()
    if not old_text:
        return memory, meta_memory

    prompt = f"""아래는 이사회 멤버 "{member.get('name', '')}"의 과거 발언/기록입니다.

{old_text}

---
기존 장기 기억 요약:
{meta_memory if meta_memory else '(없음)'}

---
위의 과거 발언을 기존 장기 기억에 통합하여 새로운 장기 기억 요약을 작성해주세요.

작성 규칙:
- 핵심 가치관, 반복되는 패턴, 중요한 의사결정을 중심으로
- 시간 순서대로 주요 변화와 일관된 경향 정리
- 구체적인 숫자나 날짜, 사건은 보존
- 최대 2000자 이내로 작성
- 텍스트만 반환 (JSON 없이)"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        new_meta = msg.content[0].text.strip()

        # meta_memory 길이 제한
        if len(new_meta) > META_MEMORY_LIMIT:
            new_meta = new_meta[:META_MEMORY_LIMIT]

        updated_memory = "\n".join(keep_lines).strip()
        print(f"  메모리 통합: {len(memory):,}자 → {len(updated_memory):,}자 (meta: {len(new_meta):,}자)")
        return updated_memory, new_meta
    except Exception as e:
        print(f"  메모리 통합 오류: {e}", file=sys.stderr)
        return memory, meta_memory


# ---------------------------------------------------------------------------
# 의도 분류
# ---------------------------------------------------------------------------

def classify_intent(message: str, client: anthropic.Anthropic) -> dict:
    """사용자 메시지의 의도를 분류한다.
    Returns: {"intent": "directive"|"question"|"conversation", "detail": "..."}"""
    prompt = f"""사용자가 이사회 멤버들에게 보낸 메시지의 의도를 분류해주세요.

메시지: "{message}"

의도 분류:
1. "directive" — 기억하라, 목표 설정, 지시사항 (예: "이번달 목표는 매출 1억", "기억해 나 다음주에 면접있어")
2. "question" — 질문, 의견 요청 (예: "내 지난달 목표 뭐였지?", "요즘 내가 뭘 고민하고 있었지?")
3. "conversation" — 일반 대화, 감정 표현, 근황 공유 (예: "오늘 힘들었다", "요즘 좀 바쁘네")

반드시 아래 JSON으로만 응답:
{{"intent": "directive 또는 question 또는 conversation", "detail": "핵심 내용 한 줄 요약"}}"""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:].lstrip()
        return json.loads(raw)
    except Exception:
        # 기본적으로 conversation으로 처리
        return {"intent": "conversation", "detail": message[:100]}


# ---------------------------------------------------------------------------
# 지시사항 저장
# ---------------------------------------------------------------------------

def save_directive(members: list, message: str, detail: str) -> None:
    """모든 활성 멤버의 user_directives에 지시사항 추가."""
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    new_entry = f"[{now_str}] {message.strip()}"

    for m in members:
        member_id = m.get("id")
        if not member_id:
            continue

        existing = m.get("user_directives", "").strip()
        updated = f"{existing}\n{new_entry}".strip()

        # 지시사항은 최대 5000자
        if len(updated) > 5000:
            lines = updated.split("\n")
            while len("\n".join(lines)) > 5000 and len(lines) > 3:
                lines.pop(0)
            updated = "\n".join(lines)

        ok = _supabase_patch(
            f"/rest/v1/board_members?id=eq.{member_id}",
            {"user_directives": updated, "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        if ok:
            m["user_directives"] = updated

    print(f"  지시사항 저장 완료: {detail}")


# ---------------------------------------------------------------------------
# 이사회 응답 생성
# ---------------------------------------------------------------------------

def generate_board_response(message: str, intent: dict, members: list, client: anthropic.Anthropic) -> dict:
    """이사회 멤버들의 응답을 생성한다.
    Returns: {"responses": {"key": "응답"}, "summary": "종합"}"""

    member_context = ""
    for m in members:
        desc = m.get("description", "")
        personality = m.get("personality", "")
        meta_mem = m.get("meta_memory", "")
        memory = m.get("memory", "")
        directives = m.get("user_directives", "")

        member_context += f'\n"{m["key"]}": {m["name"]} — {desc}'
        if personality:
            member_context += f"\n  성격: {personality}"
        if directives:
            member_context += f"\n  사용자 지시사항: {directives[-1000:]}"
        if meta_mem:
            member_context += f"\n  장기 기억: {meta_mem[-1500:]}"
        if memory:
            member_context += f"\n  최근 기록: {memory[-1000:]}"
        member_context += "\n"

    member_keys = [m["key"] for m in members]
    intent_type = intent.get("intent", "conversation")

    if intent_type == "question":
        instruction = """사용자가 질문을 했습니다. 각 이사는 자신이 기억하는 내용(장기 기억, 최근 기록, 사용자 지시사항)을 바탕으로 답변해주세요.
모르는 내용은 솔직히 모른다고 하되, 관련 기억이 있으면 연결해서 답변해주세요.
각 이사는 2~3문장으로 답변합니다."""
    elif intent_type == "directive":
        instruction = """사용자가 기억하라고 지시했습니다. 각 이사는 자신의 관점에서 해당 지시를 어떻게 받아들이는지 짧게(1~2문장) 확인 응답해주세요.
예: "알겠습니다. [관점에서의 코멘트]" """
    else:
        instruction = """사용자가 일상 대화를 했습니다. 각 이사는 자신의 관점과 기억을 바탕으로 자연스럽게 반응해주세요.
각 이사는 1~2문장으로 짧고 따뜻하게 응답합니다. 불필요하게 길게 쓰지 마세요."""

    prompt = f"""사용자가 이사회에 메시지를 보냈습니다.

💬 메시지: {message}

이사회 멤버 정보:
{member_context}

{instruction}

반드시 아래 JSON으로만 응답:
{{
  "responses": {{
    {', '.join(f'"{k}": "응답"' for k in member_keys)}
  }},
  "summary": "이사들의 응답을 한 줄로 종합 (선택사항, 필요 없으면 빈 문자열)"
}}"""

    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"responses": {}, "summary": raw[:1000]}


# ---------------------------------------------------------------------------
# 텔레그램 발송
# ---------------------------------------------------------------------------

def send_telegram(text: str, reply_to: int = None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    payload = {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML", "disable_web_page_preview": True}
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
            return result.get("ok", False)
    except Exception as e:
        print(f"텔레그램 발송 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 포맷
# ---------------------------------------------------------------------------

def format_response(intent: dict, result: dict, members: list) -> str:
    """응답을 텔레그램 메시지로 포맷."""
    intent_type = intent.get("intent", "conversation")

    if intent_type == "directive":
        emoji = "📌"
        title = "지시사항 확인"
    elif intent_type == "question":
        emoji = "💭"
        title = "이사회 답변"
    else:
        emoji = "🗣️"
        title = "이사회"

    lines = [f"<b>{emoji} {title}</b>\n"]

    responses = result.get("responses", {})
    for m in members:
        resp = responses.get(m["key"], "").strip()
        if resp:
            lines.append(f"<b>{m['name']}</b>\n{resp}\n")

    summary = result.get("summary", "").strip()
    if summary:
        lines.append(f"<i>{summary}</i>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 대화 기록을 memory에 추가
# ---------------------------------------------------------------------------

def update_memories(members: list, user_message: str, result: dict, client: anthropic.Anthropic) -> None:
    """대화 내용을 각 멤버 memory에 추가하고, 필요시 meta_memory로 통합."""
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    responses = result.get("responses", {})

    for m in members:
        key = m["key"]
        resp = responses.get(key, "").strip()
        if not resp:
            continue

        member_id = m.get("id")
        if not member_id:
            continue

        existing_memory = m.get("memory", "").strip()
        new_entry = f"[{now_str} 대화] 사용자: {user_message[:100]} → {m['name']}: {resp[:150]}"
        updated_memory = f"{existing_memory}\n{new_entry}".strip()

        # 통합 체크
        m["memory"] = updated_memory
        updated_memory, updated_meta = consolidate_memory(m, client)

        patch_data = {
            "memory": updated_memory,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if updated_meta != m.get("meta_memory", ""):
            patch_data["meta_memory"] = updated_meta

        ok = _supabase_patch(f"/rest/v1/board_members?id=eq.{member_id}", patch_data)
        status = "✓" if ok else "✗"
        print(f"  {status} {m['name']} memory 업데이트 ({len(updated_memory):,}자)")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    message = os.environ.get("INPUT_MESSAGE", "").strip()
    reply_to = int(os.environ.get("INPUT_MSG_ID", "0")) or None

    if not message:
        print("오류: 메시지가 없습니다.", file=sys.stderr)
        sys.exit(1)

    print("=== 이사회 자연어 대화 에이전트 시작 ===\n")
    print(f"메시지: {message}\n")

    client = anthropic.Anthropic()

    print("[1/5] 이사회 멤버 로드...")
    members = load_board_members()
    if not members:
        send_telegram("이사회 멤버가 설정되지 않았습니다.", reply_to)
        return
    print(f"  → {len(members)}명\n")

    print("[2/5] 의도 분류...")
    intent = classify_intent(message, client)
    print(f"  → {intent.get('intent', '?')}: {intent.get('detail', '')}\n")

    # 지시사항이면 저장
    if intent.get("intent") == "directive":
        print("[2.5/5] 지시사항 저장...")
        save_directive(members, message, intent.get("detail", ""))
        # 멤버 데이터 다시 로드 (directives 반영)
        members = load_board_members()

    print("[3/5] 이사회 응답 생성...")
    result = generate_board_response(message, intent, members, client)

    print("[4/5] 텔레그램 발송...")
    tg_msg = format_response(intent, result, members)
    ok = send_telegram(tg_msg, reply_to)
    print(f"  발송 {'완료' if ok else '실패'}\n")

    print("[5/5] 메모리 업데이트...")
    update_memories(members, message, result, client)

    print("\n=== 완료 ===")


if __name__ == "__main__":
    main()
