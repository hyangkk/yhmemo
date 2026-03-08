#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys as _sys; _sys.stdout.reconfigure(line_buffering=True)
"""
이사회 안건/표결 에이전트
- /안건 OOOO → 5인 이사가 각자 관점에서 의견 제시
- /표결 OOOO → 5인 이사가 찬성/반대 + 사유로 투표
- 결과를 텔레그램 발송 + Notion 이사회DB 저장
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
# Supabase 헬퍼 (diary_board_agent.py와 동일)
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
        "board_notion_db_id": os.environ.get("BOARD_NOTION_DATABASE_ID", ""),
    }
    rows = _supabase_get("/rest/v1/agent_settings?id=eq.1")
    if not rows:
        return default
    s = rows[0]
    return {
        "board_notion_db_id": s.get("board_notion_db_id") or os.environ.get("BOARD_NOTION_DATABASE_ID", ""),
    }

def load_board_members() -> list:
    rows = _supabase_get("/rest/v1/board_members?enabled=eq.true&order=sort_order.asc")
    if rows:
        print(f"  Supabase에서 {len(rows)}명 로드")
        return rows
    print("  board_members 테이블 없거나 비어있음 — 기본 멤버 사용")
    return DEFAULT_MEMBERS


# ---------------------------------------------------------------------------
# Notion 헬퍼
# ---------------------------------------------------------------------------

def notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('NOTION_API_KEY', '')}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


# ---------------------------------------------------------------------------
# 과거 이사회 분석 기록 검색
# ---------------------------------------------------------------------------

def search_past_reports(topic: str) -> str:
    """Supabase board_reports에서 과거 이사회 분석 기록을 검색하여 관련 내용을 반환한다."""
    # 최근 30건의 board_reports 요약 가져오기
    rows = _supabase_get(
        "/rest/v1/board_reports?select=created_at,summary,opinions,action_items"
        "&order=created_at.desc&limit=30"
    )
    if not rows:
        print("  과거 이사회 기록 없음")
        return ""

    # 각 보고서를 간결한 형태로 정리
    report_summaries = []
    for r in rows:
        created = r.get("created_at", "")[:10]
        summary = r.get("summary", "").strip()
        opinions = r.get("opinions", {})
        if not summary and not opinions:
            continue

        # 의견 요약 (각 이사 의견의 앞부분만)
        opinion_snippets = []
        if isinstance(opinions, dict):
            for key, val in opinions.items():
                if isinstance(val, str) and val.strip():
                    opinion_snippets.append(f"  {key}: {val[:150]}")
                elif isinstance(val, dict):
                    vote = val.get("vote", "")
                    reason = val.get("reason", "")
                    opinion_snippets.append(f"  {key}: {vote} - {reason[:100]}")

        entry = f"[{created}] {summary}"
        if opinion_snippets:
            entry += "\n" + "\n".join(opinion_snippets[:5])
        report_summaries.append(entry)

    if not report_summaries:
        print("  과거 기록 있으나 유의미한 내용 없음")
        return ""

    # Claude로 관련 기록 필터링
    all_reports = "\n\n---\n".join(report_summaries)
    client = anthropic.Anthropic()

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": f"""아래는 과거 이사회 분석 기록입니다.

현재 안건: {topic}

과거 기록:
{all_reports[:8000]}

---
현재 안건과 관련된 과거 기록이 있으면 요약해주세요.
- 비슷한 고민이나 상황이 있었는지
- 그때 이사회의 판단은 어땠는지
- 그때의 결정 이후 어떤 흐름이 있었는지

관련 기록이 없으면 "관련 과거 기록 없음"이라고만 답하세요.
간결하게 bullet point로 작성."""}],
        )
        result = msg.content[0].text.strip()
        if "관련 과거 기록 없음" in result:
            print("  관련 과거 기록 없음")
            return ""
        print(f"  관련 과거 기록 발견 ({len(result):,}자)")
        return result
    except Exception as e:
        print(f"  과거 기록 검색 오류 (무시하고 진행): {e}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# 웹 검색 기반 사전 조사
# ---------------------------------------------------------------------------

def research_topic(topic: str) -> str:
    """안건/표결 주제에 대해 웹 검색으로 최신 정보를 조사한다."""
    client = anthropic.Anthropic()

    prompt = f"""다음 안건/표결 주제에 대해 의사결정에 필요한 최신 정보를 조사해주세요.

주제: {topic}

조사 방향:
- 이 주제와 관련된 최신 뉴스, 현황, 리스크
- 의사결정에 영향을 줄 수 있는 객관적 사실 (안전, 비용, 시기 등)
- 현재 상황에서 고려해야 할 중요 정보

조사 결과를 간결하게 정리해주세요. 핵심 사실 위주로 bullet point로 작성."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305"}],
            messages=[{"role": "user", "content": prompt}],
        )

        # tool_use + text 결과에서 텍스트만 추출
        research_text = ""
        for block in message.content:
            if block.type == "text":
                research_text += block.text + "\n"

        research_text = research_text.strip()
        if research_text:
            print(f"  웹 조사 완료 ({len(research_text):,}자)")
            return research_text
        else:
            print("  웹 조사 결과 없음")
            return ""
    except Exception as e:
        print(f"  웹 조사 오류 (무시하고 진행): {e}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# Claude AI — 안건 의견 생성
# ---------------------------------------------------------------------------

def generate_agenda_opinions(agenda: str, members: list, research: str = "", past_context: str = "") -> dict:
    """안건에 대해 각 이사의 의견을 생성한다."""
    client = anthropic.Anthropic()

    member_instructions = ""
    for m in members:
        desc = m.get("description", "")
        personality = m.get("personality", "")
        meta_mem = m.get("meta_memory", "").strip()
        directives = m.get("user_directives", "").strip()
        persona = desc
        if personality:
            persona += f"\n  (성격: {personality})"
        if directives:
            persona += f"\n  (사용자 지시사항: {directives[-500:]})"
        if meta_mem:
            persona += f"\n  (장기 기억: {meta_mem[-500:]})"
        member_instructions += f'  "{m["key"]}": {m["name"]} — {persona}\n'

    member_keys = [m["key"] for m in members]

    research_section = ""
    if research:
        research_section = f"""
📌 사전 조사 결과 (웹 검색 기반 최신 정보):
{research}

위 조사 결과를 반드시 참고하여 의견을 제시하세요. 현실과 동떨어진 의견은 지양하세요.
"""

    past_section = ""
    if past_context:
        past_section = f"""
📂 과거 관련 기록 (이전 이사회 분석에서 발견):
{past_context}

과거에 비슷한 고민이나 상황이 있었다면 그때의 판단과 결과를 참고하여 의견을 제시하세요.
"""

    prompt = f"""다음 안건에 대해 이사회 멤버 각자의 관점에서 의견을 제시해주세요.

📋 안건: {agenda}
{research_section}{past_section}
이사회 멤버:
{member_instructions}

반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트는 쓰지 마세요.
각 이사의 의견은 3~5문장으로 구체적이고 실질적으로 작성해주세요.
해당 이사의 역할과 성격에 맞는 고유한 관점을 반영하세요.

{{
  "opinions": {{
    {', '.join(f'"{k}": "해당 이사 관점의 구체적 의견 (3~5문장)"' for k in member_keys)}
  }},
  "summary": "이사들의 의견을 종합한 핵심 요약 (2~3문장)",
  "action_items": ["구체적인 제안/다음 단계 1", "제안 2", "제안 3"]
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
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
        return {"opinions": {}, "summary": raw[:2000], "action_items": []}


# ---------------------------------------------------------------------------
# Claude AI — 표결 생성
# ---------------------------------------------------------------------------

def generate_vote(topic: str, members: list, research: str = "", past_context: str = "") -> dict:
    """안건에 대해 각 이사의 찬반 투표를 생성한다."""
    client = anthropic.Anthropic()

    member_instructions = ""
    for m in members:
        desc = m.get("description", "")
        personality = m.get("personality", "")
        meta_mem = m.get("meta_memory", "").strip()
        directives = m.get("user_directives", "").strip()
        persona = desc
        if personality:
            persona += f"\n  (성격: {personality})"
        if directives:
            persona += f"\n  (사용자 지시사항: {directives[-500:]})"
        if meta_mem:
            persona += f"\n  (장기 기억: {meta_mem[-500:]})"
        member_instructions += f'  "{m["key"]}": {m["name"]} — {persona}\n'

    member_keys = [m["key"] for m in members]

    research_section = ""
    if research:
        research_section = f"""
📌 사전 조사 결과 (웹 검색 기반 최신 정보):
{research}

위 조사 결과를 반드시 참고하여 투표하세요. 최신 정세, 안전 이슈, 현실적 리스크를 무시한 투표는 지양하세요.
"""

    past_section = ""
    if past_context:
        past_section = f"""
📂 과거 관련 기록 (이전 이사회 분석에서 발견):
{past_context}

과거에 비슷한 고민이나 결정이 있었다면 그때의 판단과 결과를 참고하여 투표하세요.
"""

    prompt = f"""다음 안건에 대해 이사회 멤버 각자가 찬성, 반대, 또는 기권 투표를 해주세요.

🗳️ 표결 안건: {topic}
{research_section}{past_section}
이사회 멤버:
{member_instructions}

반드시 아래 JSON 형식으로만 응답하세요. JSON 외 다른 텍스트는 쓰지 마세요.

투표 규칙:
- 각 이사는 자신의 역할과 성격에 기반해 솔직하게 찬성/반대/기권을 결정
- 사전 조사 결과가 있으면 반드시 참고하여 현실에 기반한 판단을 내릴 것
- 안건이 애매하거나, 자신의 관점에서 판단이 불가능하거나, 정보가 부족하면 "기권" 가능
- 기권 사유도 반드시 작성 (예: "현재 정보만으로는 판단이 어렵습니다")
- 안건의 논리가 불충분하면 반대하거나 기권하고, 어떤 추가 정보/논리가 있으면 찬성할 수 있을지 제시
- 찬성/반대 시 사유를 1~2문장으로 간결하게 설명 (핵심만)

가결 기준: 찬성 3표 이상이면 가결, 미만이면 부결 (기권은 찬성도 반대도 아님)

중요: summary에서 가결/부결을 직접 판단하지 마세요. 각 이사의 투표 사유를 종합 분석하고, 부결 시 어떤 조건이 추가되면 가결될 수 있을지만 제안하세요.

{{
  "votes": {{
    {', '.join(f'"{k}": {{"vote": "찬성 또는 반대 또는 기권", "reason": "핵심 사유 1~2문장"}}' for k in member_keys)}
  }},
  "summary": "핵심 쟁점과 개선 제안 1~2문장. 가결/부결 판정은 쓰지 말 것"
}}"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].lstrip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"votes": {}, "result": "", "summary": raw[:2000]}

    # 찬성 3표 이상 단순 가결
    votes = data.get("votes", {})
    yes_count = 0
    no_count = 0
    abstain_count = 0
    for k in member_keys:
        v = votes.get(k, {})
        vote_str = v.get("vote", "") if isinstance(v, dict) else str(v)
        if "찬성" in vote_str:
            yes_count += 1
        elif "반대" in vote_str:
            no_count += 1
        else:
            abstain_count += 1

    passed = yes_count >= 3
    verdict = "✅ 가결" if passed else "❌ 부결"
    result_str = f"찬성 {yes_count} · 반대 {no_count} · 기권 {abstain_count} — {verdict}"

    data["result"] = result_str
    data["passed"] = passed
    return data


# ---------------------------------------------------------------------------
# 텔레그램 발송
# ---------------------------------------------------------------------------

def send_telegram(text: str, reply_to: int = None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("경고: 텔레그램 환경변수 누락", file=sys.stderr)
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
            if result.get("ok"):
                print("텔레그램 발송 완료")
                return True
            print(f"텔레그램 발송 실패: {result}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"텔레그램 발송 오류: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Notion 저장
# ---------------------------------------------------------------------------

def save_agenda_to_notion(mode: str, topic: str, result: dict, members: list, now: datetime, db_id: str) -> str | None:
    """안건/표결 결과를 Notion 이사회 DB에 저장. 성공 시 URL 반환."""
    if not db_id:
        print("BOARD_NOTION_DATABASE_ID 미설정 — Notion 저장 불가", file=sys.stderr)
        return None

    emoji = "📋" if mode == "agenda" else "🗳️"
    label = "안건" if mode == "agenda" else "표결"
    title = f"{label} · {topic[:40]}"

    children = [
        {"object": "block", "type": "callout", "callout": {
            "icon": {"type": "emoji", "emoji": emoji},
            "color": "blue_background" if mode == "agenda" else "yellow_background",
            "rich_text": [{"type": "text", "text": {"content": f"{label}: {topic} | {now.strftime('%Y-%m-%d %H:%M')} KST"}}],
        }},
    ]

    if mode == "agenda":
        # 각 이사 의견
        opinions = result.get("opinions", {})
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "💬 이사회 의견"}}]}})
        for m in members:
            opinion = opinions.get(m["key"], "").strip()
            if opinion:
                children.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": m["name"]}}]}})
                children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": opinion[:2000]}}]}})

        # 종합
        summary = result.get("summary", "")
        if summary:
            children.append({"object": "block", "type": "divider", "divider": {}})
            children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🤝 종합"}}]}})
            children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": summary}}]}})

        # 액션 아이템
        action_items = result.get("action_items", [])
        if action_items:
            children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "✅ 다음 단계"}}]}})
            for item in action_items:
                children.append({"object": "block", "type": "to_do", "to_do": {
                    "checked": False, "rich_text": [{"type": "text", "text": {"content": str(item)}}],
                }})

    else:  # vote
        votes = result.get("votes", {})
        vote_result = result.get("result", "")
        summary = result.get("summary", "")

        # 투표 결과 요약
        if vote_result:
            children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": f"📊 결과: {vote_result}"}}]}})

        # 각 이사 투표
        children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "🗳️ 개별 투표"}}]}})
        for m in members:
            v = votes.get(m["key"], {})
            if isinstance(v, dict):
                vote_str = v.get("vote", "")
                reason = v.get("reason", "")
                if "찬성" in vote_str:
                    icon = "✅"
                elif "반대" in vote_str:
                    icon = "❌"
                else:
                    icon = "⬜"
                children.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": f"{icon} {m['name']} — {vote_str}"}}]}})
                if reason:
                    children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": reason}}]}})

        if summary:
            children.append({"object": "block", "type": "divider", "divider": {}})
            children.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": "📝 종합 해석"}}]}})
            children.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": summary}}]}})

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
            page = json.loads(resp.read().decode())
            url = page.get("url", "")
            print(f"Notion 저장 완료: {url}")
            return url
    except urllib.error.HTTPError as e:
        print(f"Notion 저장 실패 ({e.code}): {e.read().decode()}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Notion 저장 오류: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# personality 자동 업데이트 (memory 누적)
# ---------------------------------------------------------------------------

MEMORY_RAW_LIMIT = 6000
META_MEMORY_LIMIT = 20000


def _consolidate_memory(member: dict, client: anthropic.Anthropic) -> tuple:
    """raw memory가 MEMORY_RAW_LIMIT를 초과하면 오래된 내용을 meta_memory로 통합."""
    memory = member.get("memory", "").strip()
    meta_memory = member.get("meta_memory", "").strip()

    if len(memory) <= MEMORY_RAW_LIMIT:
        return memory, meta_memory

    lines = memory.split("\n")
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
핵심 가치관, 반복 패턴, 중요 의사결정 중심. 구체적 날짜/숫자 보존. 최대 2000자. 텍스트만 반환."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        new_meta = msg.content[0].text.strip()
        if len(new_meta) > META_MEMORY_LIMIT:
            new_meta = new_meta[:META_MEMORY_LIMIT]
        updated_memory = "\n".join(keep_lines).strip()
        print(f"    메모리 통합: {len(memory):,}자 → {len(updated_memory):,}자 (meta: {len(new_meta):,}자)")
        return updated_memory, new_meta
    except Exception as e:
        print(f"    메모리 통합 오류: {e}", file=sys.stderr)
        return memory, meta_memory


def update_member_personalities(members: list, result: dict, mode: str, topic: str) -> None:
    """발언을 memory에 누적하고 3-tier 메모리 시스템으로 관리."""
    client = anthropic.Anthropic()
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    context_label = f"안건: {topic[:30]}" if mode == "agenda" else f"표결: {topic[:30]}"

    if mode == "vote":
        raw_opinions = result.get("votes", {})
    else:
        raw_opinions = result.get("opinions", {})

    for m in members:
        key = m["key"]
        raw = raw_opinions.get(key, "")
        if isinstance(raw, dict):
            opinion = f"{raw.get('vote', '')} — {raw.get('reason', '')}".strip()
        else:
            opinion = str(raw).strip()
        if not opinion:
            continue

        member_id = m.get("id")
        if not member_id:
            continue

        existing_memory = m.get("memory", "").strip()

        new_entry = f"[{now_str} {context_label}] {opinion}"
        updated_memory = f"{existing_memory}\n{new_entry}".strip()
        m["memory"] = updated_memory

        # 3-tier 메모리 통합
        updated_memory, updated_meta = _consolidate_memory(m, client)

        # 전체 기록으로 personality 종합
        full_context = ""
        if updated_meta:
            full_context += f"[장기 기억]\n{updated_meta}\n\n"
        directives = m.get("user_directives", "").strip()
        if directives:
            full_context += f"[사용자 지시사항]\n{directives}\n\n"
        full_context += f"[최근 기록]\n{updated_memory}"

        prompt = f"""이사회 멤버 "{m['name']}" ({m.get('role', '')})의 전체 기록입니다:

{full_context}

---
위 기록을 바탕으로 이 이사의 personality를 종합해주세요.

작성 규칙:
- 3~5문장으로 작성
- 핵심 가치관, 사고 패턴, 판단 기준을 구체적으로
- 시간에 따른 변화나 일관된 패턴이 있으면 언급
- 사용자 지시사항이 있으면 그것도 반영
- JSON 없이 텍스트만 반환"""

        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            new_personality = msg.content[0].text.strip()
            patch_data = {
                "personality": new_personality,
                "memory": updated_memory,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if updated_meta != m.get("meta_memory", ""):
                patch_data["meta_memory"] = updated_meta
            ok = _supabase_patch(
                f"/rest/v1/board_members?id=eq.{member_id}",
                patch_data,
            )
            status = "✓" if ok else "✗"
            print(f"  {status} {m['name']} personality 업데이트 (memory {len(updated_memory):,}자, meta {len(updated_meta):,}자)")
        except Exception as e:
            print(f"  {m['name']} personality 업데이트 오류: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 텔레그램 포맷
# ---------------------------------------------------------------------------

def format_agenda_telegram(topic: str, result: dict, members: list, now: datetime, notion_url: str | None) -> str:
    """안건 결과를 텔레그램 메시지로 포맷."""
    lines = [f"<b>📋 이사회 안건</b>", f"<i>{topic}</i>\n"]

    opinions = result.get("opinions", {})
    for m in members:
        opinion = opinions.get(m["key"], "").strip()
        if opinion:
            lines.append(f"<b>{m['name']}</b>\n{opinion}\n")

    summary = result.get("summary", "")
    if summary:
        lines.append(f"<b>🤝 종합</b>\n{summary}\n")

    action_items = result.get("action_items", [])
    if action_items:
        lines.append("<b>✅ 다음 단계</b>")
        for item in action_items:
            lines.append(f"  • {item}")

    if notion_url:
        lines.append(f"\n👉 <a href=\"{notion_url}\">전체 보기</a>")

    return "\n".join(lines)


def format_vote_telegram(topic: str, result: dict, members: list, now: datetime, notion_url: str | None) -> str:
    """표결 결과를 텔레그램 메시지로 포맷."""
    lines = [f"<b>🗳️ 이사회 표결</b>", f"<i>{topic}</i>\n"]

    vote_result = result.get("result", "")
    if vote_result:
        lines.append(f"<b>📊 {vote_result}</b>\n")

    votes = result.get("votes", {})
    for m in members:
        v = votes.get(m["key"], {})
        if isinstance(v, dict):
            vote_str = v.get("vote", "")
            reason = v.get("reason", "")
            if "찬성" in vote_str:
                icon = "✅"
            elif "반대" in vote_str:
                icon = "❌"
            else:
                icon = "⬜"  # 기권
            lines.append(f"{icon} <b>{m['name']}</b> — {vote_str}")
            if reason:
                lines.append(f"  {reason}\n")

    summary = result.get("summary", "")
    if summary:
        lines.append(f"<b>📝 종합</b>\n{summary}")

    if not result.get("passed", True):
        lines.append("\n<i>💡 안건을 수정하거나 추가 논리를 제시하여 다시 /표결 할 수 있습니다.</i>")

    if notion_url:
        lines.append(f"\n👉 <a href=\"{notion_url}\">전체 보기</a>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    mode = os.environ.get("INPUT_MODE", "agenda")  # "agenda" or "vote"
    topic = os.environ.get("INPUT_TOPIC", "").strip()
    reply_to = int(os.environ.get("INPUT_MSG_ID", "0")) or None

    if not topic:
        print("오류: 안건/표결 내용이 없습니다.", file=sys.stderr)
        sys.exit(1)

    label = "안건" if mode == "agenda" else "표결"
    print(f"=== 이사회 {label} 에이전트 시작 ===\n")
    print(f"모드: {mode}")
    print(f"내용: {topic}\n")

    settings = load_settings()
    board_db_id = settings["board_notion_db_id"]

    print("[1/5] 이사회 멤버 로드 중...")
    members = load_board_members()
    print(f"  → {len(members)}명\n")

    print("[2/5] 과거 이사회 기록 검색 중...")
    past_context = search_past_reports(topic)

    print("[3/5] 웹 검색으로 관련 정보 조사 중...")
    research = research_topic(topic)
    if research:
        print(f"  → 조사 결과 확보\n")
    else:
        print(f"  → 추가 조사 없이 진행\n")

    print(f"[4/5] {label} 분석 중...")
    if mode == "vote":
        result = generate_vote(topic, members, research, past_context)
    else:
        result = generate_agenda_opinions(topic, members, research, past_context)
    now = datetime.now(KST)

    print(f"[5/6] 발송 및 저장 중...")
    notion_url = save_agenda_to_notion(mode, topic, result, members, now, board_db_id)

    if mode == "vote":
        tg_msg = format_vote_telegram(topic, result, members, now, notion_url)
    else:
        tg_msg = format_agenda_telegram(topic, result, members, now, notion_url)

    ok = send_telegram(tg_msg, reply_to)

    print(f"\n[6/6] 이사 personality 업데이트 중...")
    update_member_personalities(members, result, mode, topic)

    print("\n=== 완료 ===")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
