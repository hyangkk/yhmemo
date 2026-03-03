#!/usr/bin/env python3
"""
인터뷰 에이전트
- 설정된 주기마다 텔레그램으로 인터뷰 질문 발송
- 사용자 답변을 수집하여 Supabase에 저장
- 노션에 체계적으로 정리
- 충분한 내용이 쌓이면 유튜브 대본 초안 자동 생성

GitHub Actions에서 15분마다 실행:
  1) 텔레그램 새 메시지(답변) 수집
  2) 설정된 주기에 맞으면 새 질문 발송
"""

import os
import re
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

def _sb_headers():
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _sb_url():
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def sb_get(path):
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/{path}", headers=_sb_headers()
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def sb_post(path, data, extra_headers=None):
    headers = {**_sb_headers(), "Prefer": "return=representation"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/{path}",
        data=json.dumps(data).encode(),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def sb_patch(path, data):
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/{path}",
        data=json.dumps(data).encode(),
        headers={**_sb_headers(), "Prefer": "return=representation"},
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        text = resp.read().decode()
        return json.loads(text) if text.strip() else None


# ---------------------------------------------------------------------------
# 설정 로드
# ---------------------------------------------------------------------------

def fetch_settings() -> dict:
    default = {
        "interview_enabled": True,
        "interview_interval_hours": 3,
        "interview_last_update_id": 0,
        "interview_last_question_at": None,
        "interview_notion_database_id": "",
    }
    try:
        rows = sb_get("agent_settings?id=eq.1")
        if rows:
            return {**default, **rows[0]}
    except Exception as e:
        print(f"설정 로드 실패 (기본값 사용): {e}", file=sys.stderr)
    return default


# ---------------------------------------------------------------------------
# 텔레그램 헬퍼
# ---------------------------------------------------------------------------

def _tg_token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _tg_chat_id():
    return os.environ.get("TELEGRAM_CHAT_ID", "")


def tg_send(text, reply_to=None):
    """텔레그램 메시지 발송. 성공 시 message_id, 실패 시 None."""
    payload = {
        "chat_id": _tg_chat_id(),
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{_tg_token()}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get("ok"):
                return result["result"]["message_id"]
    except Exception as e:
        print(f"텔레그램 발송 실패: {e}", file=sys.stderr)
    return None


def tg_get_updates(offset=0):
    """텔레그램 새 메시지 가져오기 (long-polling 5초)."""
    payload = {"offset": offset, "timeout": 5, "allowed_updates": ["message"]}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{_tg_token()}/getUpdates",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read().decode())
            if not result.get("ok"):
                return []
            chat_id = _tg_chat_id()
            return [
                u for u in result.get("result", [])
                if str(u.get("message", {}).get("chat", {}).get("id")) == chat_id
            ]
    except Exception as e:
        print(f"텔레그램 업데이트 조회 실패: {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# 주제 / 메시지 DB 조회
# ---------------------------------------------------------------------------

def get_active_topics():
    try:
        return sb_get("interview_topics?enabled=eq.true&order=id.asc")
    except Exception:
        return []


def get_topic_messages(topic_id, limit=50):
    try:
        return sb_get(
            f"interview_messages?topic_id=eq.{topic_id}"
            f"&order=created_at.asc&limit={limit}"
        )
    except Exception:
        return []


def get_pending_question():
    """아직 답변되지 않은 최근 에이전트 질문 조회."""
    try:
        last_qs = sb_get(
            "interview_messages?role=eq.agent&order=created_at.desc&limit=1"
        )
        if not last_qs:
            return None
        q = last_qs[0]
        replies = sb_get(
            f"interview_messages?role=eq.user&topic_id=eq.{q['topic_id']}"
            f"&created_at=gt.{q['created_at']}&limit=1"
        )
        return None if replies else q
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Claude AI — 질문 생성
# ---------------------------------------------------------------------------

def generate_question(topic, previous_qa):
    client = anthropic.Anthropic()

    qa_history = ""
    if previous_qa:
        for msg in previous_qa[-20:]:
            label = "Q" if msg["role"] == "agent" else "A"
            qa_history += f"{label}: {msg['content']}\n\n"

    desc_line = f"주제 설명: {topic['description']}" if topic.get("description") else ""
    history_block = f"지금까지의 인터뷰 내용:\n{qa_history}" if qa_history else "이번이 첫 질문입니다."
    guide = (
        "첫 질문이니 가볍게 시작하세요. 이 주제에 어떻게 관심을 갖게 되었는지, 시작하게 된 계기를 물어보세요."
        if not previous_qa
        else "이전 답변 내용을 기반으로 더 깊이 파고들거나, 아직 다루지 않은 새로운 측면에 대해 질문하세요."
    )

    prompt = f"""당신은 유튜브 콘텐츠를 위한 전문 인터뷰어입니다.
아래 주제에 대해 상대방을 인터뷰하고 있습니다.

주제: {topic['name']}
{desc_line}

{history_block}

다음 규칙을 따라 질문을 하나 생성하세요:
1. 이전에 이미 물어본 내용은 절대 반복하지 마세요.
2. 구체적인 에피소드, 감정, 디테일을 끌어낼 수 있는 질문을 하세요.
3. 유튜브 시청자가 흥미로워할 만한 이야기를 이끌어내세요.
4. 친근하고 자연스러운 대화체로 질문하세요.
5. 한 번에 하나의 질문만 하세요.
6. 질문만 출력하세요 (다른 설명 없이).

{guide}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# Claude AI — 콘텐츠 정리 & 대본 생성
# ---------------------------------------------------------------------------

def generate_organized_content(topic, all_qa):
    """수집된 Q&A를 정리하고 유튜브 대본 초안을 생성."""
    client = anthropic.Anthropic()

    qa_text = ""
    for msg in all_qa:
        label = "질문" if msg["role"] == "agent" else "답변"
        qa_text += f"{label}: {msg['content']}\n\n"

    prompt = f"""당신은 유튜브 콘텐츠 전문가이자 구성작가입니다.
아래는 "{topic['name']}" 주제로 진행된 인터뷰 전체 내용입니다.

{qa_text}

위 인터뷰 내용을 바탕으로 아래 두 가지를 작성해주세요.

---
핵심 내용 정리

인터뷰에서 나온 모든 핵심 포인트를 카테고리별로 체계적으로 정리하세요.
- 빠진 내용 없이 모든 에피소드와 디테일 포함
- 시청자가 공감하거나 놀랄 만한 포인트는 별도로 표시
- 시간순 또는 주제별로 분류

---
유튜브 대본 초안

10~15분 분량의 유튜브 영상 대본을 작성하세요.
- 시청자를 확 끌어당기는 오프닝 (충격적이거나 공감되는 한마디로 시작)
- 자연스러운 기승전결 흐름
- 핵심 에피소드 중심의 스토리텔링
- 중간중간 시청자에게 말을 거는 듯한 멘트
- 시청자에게 인사이트를 주는 마무리
- 실제로 카메라 앞에서 읽을 수 있는 자연스러운 말투 (대화체)
- 마크다운 기호(#, *, **) 사용하지 마세요

각 섹션을 명확히 구분해서 작성해주세요."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# 노션 연동
# ---------------------------------------------------------------------------

def _notion_headers():
    token = os.environ.get("NOTION_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def _notion_available():
    return bool(os.environ.get("NOTION_TOKEN"))


def _notion_db_id(settings):
    return (
        settings.get("interview_notion_database_id")
        or os.environ.get("NOTION_DATABASE_ID", "")
    )


def _notion_request(method, url, data=None):
    """범용 Notion API 요청 헬퍼."""
    kwargs = {"headers": _notion_headers(), "method": method}
    if data is not None:
        kwargs["data"] = json.dumps(data).encode()
    req = urllib.request.Request(url, **kwargs)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"  Notion API 오류 ({e.code}): {body[:500]}", file=sys.stderr)
        raise


def _text_block(text, block_type="paragraph"):
    """텍스트 → 노션 블록 (2000자 제한 자동 처리)."""
    blocks = []
    while text:
        chunk = text[:2000]
        text = text[2000:]
        blocks.append({
            "type": block_type,
            block_type: {
                "rich_text": [{"type": "text", "text": {"content": chunk}}]
            },
        })
    return blocks


def _callout_block(text, emoji=""):
    """콜아웃 블록 (질문용)."""
    blocks = []
    while text:
        chunk = text[:2000]
        text = text[2000:]
        blocks.append({
            "type": "callout",
            "callout": {
                "icon": {"emoji": emoji},
                "rich_text": [{"type": "text", "text": {"content": chunk}}],
            },
        })
    return blocks


def _heading_block(text, level=2):
    key = f"heading_{level}"
    return {
        "type": key,
        key: {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
    }


def _divider():
    return {"type": "divider", "divider": {}}


def notion_create_page(db_id, title, blocks):
    """노션 데이터베이스에 새 페이지 생성."""
    payload = {
        "parent": {"database_id": db_id},
        "properties": {
            "이름": {"title": [{"text": {"content": title}}]},
        },
        "children": blocks[:100],  # Notion 한 번에 최대 100 블록
    }
    result = _notion_request("POST", "https://api.notion.com/v1/pages", payload)
    page_id = result["id"]

    # 100개 초과 시 나머지 블록 추가
    remaining = blocks[100:]
    while remaining:
        batch = remaining[:100]
        remaining = remaining[100:]
        _notion_request(
            "PATCH",
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            {"children": batch},
        )
    return page_id


def notion_append_blocks(page_id, blocks):
    """기존 노션 페이지에 블록 추가."""
    while blocks:
        batch = blocks[:100]
        blocks = blocks[100:]
        _notion_request(
            "PATCH",
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            {"children": batch},
        )


def notion_clear_and_rewrite(page_id, blocks):
    """노션 페이지의 기존 블록을 모두 삭제하고 새로 작성."""
    # 기존 블록 삭제
    try:
        data = _notion_request(
            "GET",
            f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100",
        )
        for block in data.get("results", []):
            try:
                _notion_request(
                    "DELETE",
                    f"https://api.notion.com/v1/blocks/{block['id']}",
                )
            except Exception:
                pass
    except Exception:
        pass

    # 새 블록 추가
    notion_append_blocks(page_id, blocks)


def build_qa_blocks(all_qa):
    """Q&A 메시지 목록 → 노션 블록 목록."""
    blocks = [_heading_block("인터뷰 기록")]
    for msg in all_qa:
        if msg["role"] == "agent":
            blocks.extend(_callout_block(msg["content"], emoji="\u2753"))
        else:
            blocks.extend(_text_block(msg["content"]))
    return blocks


def build_content_blocks(organized_content):
    """정리된 콘텐츠 텍스트 → 노션 블록 목록."""
    blocks = [_divider(), _heading_block("핵심 내용 정리 & 유튜브 대본 초안")]
    for para in organized_content.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        # 간단한 섹션 헤딩 파싱
        if para.startswith("## "):
            blocks.append(_heading_block(para[3:], level=2))
        elif para.startswith("# "):
            blocks.append(_heading_block(para[2:], level=1))
        elif para.startswith("---"):
            blocks.append(_divider())
        else:
            blocks.extend(_text_block(para))
    return blocks


def _notion_page_url(page_id):
    """노션 페이지 ID → URL 변환."""
    clean_id = page_id.replace("-", "")
    return f"https://www.notion.so/{clean_id}"


def sync_to_notion(settings, topic, all_qa, organized_content=None):
    """주제의 인터뷰 내용을 노션에 동기화. 성공 시 page_id 반환."""
    if not _notion_available():
        print("  노션 토큰 없음 — 동기화 건너뜀")
        return None

    db_id = _notion_db_id(settings)
    if not db_id:
        print("  노션 데이터베이스 ID 없음 — 동기화 건너뜀")
        return None

    # 전체 블록 구성
    blocks = build_qa_blocks(all_qa)
    if organized_content:
        blocks.extend(build_content_blocks(organized_content))
    blocks.append(_divider())
    blocks.extend(_text_block(
        f"마지막 업데이트: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}"
    ))

    page_id = topic.get("notion_page_id") or ""

    if page_id:
        try:
            notion_clear_and_rewrite(page_id, blocks)
            print(f"  노션 업데이트 완료: {topic['name']}")
            return page_id
        except Exception as e:
            print(f"  노션 업데이트 실패 (새로 생성): {e}", file=sys.stderr)

    # 페이지 새로 생성
    try:
        new_id = notion_create_page(
            db_id, f"[인터뷰] {topic['name']}", blocks
        )
        sb_patch(
            f"interview_topics?id=eq.{topic['id']}",
            {"notion_page_id": new_id},
        )
        print(f"  노션 페이지 생성 완료: {topic['name']} ({new_id})")
        return new_id
    except Exception as e:
        print(f"  노션 페이지 생성 실패: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 봇 명령어 처리
# ---------------------------------------------------------------------------

def handle_command(text, settings):
    """텔레그램 봇 명령어 처리. 처리했으면 True, 아니면 False."""
    cmd = text.strip().split()[0].lower()

    if cmd in ("/명령어", "/help", "/commands"):
        help_text = (
            "<b>전체 명령어 목록</b>\n"
            "\n"
            "<b>인터뷰 에이전트</b>\n"
            "  /주제 — 인터뷰 주제 목록\n"
            "  /인터뷰 — 에이전트 상태 확인\n"
            "  /주기 — 질문 주기 확인/변경\n"
            "  /대본 — 유튜브 대본 생성\n"
            "  /대본 주제명 — 특정 주제 대본 생성\n"
            "  /질문줘 — 지금 바로 질문 받기\n"
            "  /건너뛰기 — 현재 질문 건너뛰기\n"
            "\n"
            "<b>뉴스 에이전트</b>\n"
            "  자동 실행 (설정 주기마다)\n"
            "\n"
            "<b>K-Startup 에이전트</b>\n"
            "  자동 실행 (설정 주기마다)\n"
            "\n"
            "<b>공통</b>\n"
            "  /명령어 — 이 도움말 표시\n"
            "\n"
            "<i>일반 텍스트를 보내면 현재 진행 중인\n"
            "인터뷰 주제에 답변으로 기록됩니다.</i>"
        )
        tg_send(help_text)
        return True

    if cmd in ("/주제", "/topics"):
        topics = get_active_topics()
        if not topics:
            tg_send("활성화된 인터뷰 주제가 없습니다.\n설정 페이지에서 주제를 추가해주세요.")
        else:
            lines = ["<b>인터뷰 주제 목록</b>\n"]
            for t in topics:
                q_count = t.get("total_questions", 0) or 0
                lines.append(f"  {t['name']}  (질문 {q_count}개)")
            tg_send("\n".join(lines))
        return True

    if cmd in ("/인터뷰", "/status"):
        pending = get_pending_question()
        interval = settings.get("interview_interval_hours", 3)
        last_at = settings.get("interview_last_question_at")
        status_parts = [
            f"<b>인터뷰 에이전트 상태</b>\n",
            f"실행 주기: {interval}시간마다",
            f"마지막 질문: {last_at or '없음'}",
            f"미답변 질문: {'있음' if pending else '없음'}",
        ]
        topics = get_active_topics()
        if topics:
            status_parts.append(f"\n활성 주제: {', '.join(t['name'] for t in topics)}")
        tg_send("\n".join(status_parts))
        return True

    if cmd in ("/대본", "/draft"):
        parts = text.strip().split(maxsplit=1)
        topic_name = parts[1] if len(parts) > 1 else None

        topics = get_active_topics()
        if not topics:
            tg_send("활성화된 주제가 없습니다.")
            return True

        target = None
        if topic_name:
            for t in topics:
                if topic_name in t["name"]:
                    target = t
                    break
        else:
            # 가장 Q&A가 많은 주제 선택
            target = max(topics, key=lambda t: t.get("total_questions", 0) or 0)

        if not target:
            tg_send(f"'{topic_name}' 주제를 찾을 수 없습니다.")
            return True

        all_qa = get_topic_messages(target["id"], limit=200)
        user_answers = [m for m in all_qa if m["role"] == "user"]
        if len(user_answers) < 3:
            tg_send(f"'{target['name']}' 주제의 답변이 아직 {len(user_answers)}개뿐입니다.\n최소 3개 이상의 답변이 필요합니다.")
            return True

        tg_send(f"'{target['name']}' 대본 생성 중... 잠시 기다려주세요.")
        try:
            content = generate_organized_content(target, all_qa)
            # Supabase에 대본 저장
            sb_patch(
                f"interview_topics?id=eq.{target['id']}",
                {
                    "draft": content,
                    "draft_updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            # 노션에 저장
            page_id = sync_to_notion(settings, target, all_qa, content)
            # 텔레그램에 노션 링크 발송
            if page_id:
                url = _notion_page_url(page_id)
                tg_send(
                    f"<b>[{target['name']}] 대본이 생성되었습니다.</b>\n\n"
                    f'<a href="{url}">노션에서 보기</a>'
                )
            else:
                tg_send(f"<b>[{target['name']}]</b> 대본이 생성되었습니다. (노션 동기화 실패)")
        except Exception as e:
            tg_send(f"대본 생성 실패: {e}")
        return True

    if cmd in ("/질문줘", "/질문", "/ask"):
        topics = get_active_topics()
        if not topics:
            tg_send("활성화된 주제가 없습니다.")
            return True

        pending = get_pending_question()
        if pending:
            tg_send("아직 답변하지 않은 질문이 있습니다!\n답변을 보내거나 /건너뛰기 후 다시 시도해주세요.")
            return True

        topic = pick_next_topic(topics)
        prev_qa = get_topic_messages(topic["id"])

        tg_send(f"'{topic['name']}' 주제로 질문 생성 중...")
        try:
            question = generate_question(topic, prev_qa)
            q_num = (topic.get("total_questions", 0) or 0) + 1
            label = (
                f"<b>[{topic['name']}]</b> (Q{q_num})\n\n"
                f"{question}\n\n"
                f"<i>답변을 입력해주세요. /건너뛰기 로 건너뛸 수 있습니다.</i>"
            )
            msg_id = tg_send(label)
            if msg_id:
                sb_post("interview_messages", {
                    "topic_id": topic["id"],
                    "role": "agent",
                    "content": question,
                    "telegram_message_id": msg_id,
                })
                sb_patch("agent_settings?id=eq.1", {
                    "interview_last_question_at": datetime.now(timezone.utc).isoformat(),
                })
                sb_patch(f"interview_topics?id=eq.{topic['id']}", {
                    "total_questions": q_num,
                })
        except Exception as e:
            tg_send(f"질문 생성 실패: {e}")
        return True

    if cmd in ("/건너뛰기", "/skip"):
        pending = get_pending_question()
        if pending:
            # 빈 답변으로 처리
            sb_post("interview_messages", {
                "topic_id": pending["topic_id"],
                "role": "user",
                "content": "(건너뛰기)",
            })
            tg_send("현재 질문을 건너뛰었습니다. 다음 질문을 기다려주세요.")
        else:
            tg_send("건너뛸 질문이 없습니다.")
        return True

    if cmd in ("/주기", "/interval"):
        parts = text.strip().split(maxsplit=1)
        if len(parts) < 2:
            current = _get_interval_minutes(settings)
            tg_send(
                f"<b>현재 질문 주기:</b> {_format_interval(current)}\n\n"
                "<b>변경 예시:</b>\n"
                "  /주기 45분\n"
                "  /주기 1시간 30분\n"
                "  /주기 2시간\n"
                "  /주기 90  (숫자만 쓰면 분 단위)"
            )
            return True

        raw = parts[1].strip()
        minutes = _parse_interval(raw)
        if minutes is None or minutes < 15:
            tg_send("주기를 인식할 수 없거나 15분 미만입니다.\n예: /주기 45분, /주기 2시간, /주기 1시간 30분")
            return True

        sb_patch("agent_settings?id=eq.1", {"interview_interval_minutes": minutes})
        tg_send(f"질문 주기가 <b>{_format_interval(minutes)}</b>(으)로 변경되었습니다.")
        return True

    return False


def _parse_interval(text):
    """자연어 주기 텍스트를 분(int)으로 변환. 실패 시 None."""
    text = text.strip()

    # 순수 숫자 → 분으로 해석
    if text.isdigit():
        return int(text)

    total = 0
    # "1시간 30분", "2시간", "45분", "1.5시간" 등 파싱
    h_match = re.search(r"(\d+(?:\.\d+)?)\s*시간", text)
    m_match = re.search(r"(\d+)\s*분", text)

    if h_match:
        hours = float(h_match.group(1))
        total += int(hours * 60)
    if m_match:
        total += int(m_match.group(1))

    return total if total > 0 else None


# ---------------------------------------------------------------------------
# 메인 로직: 수집(COLLECT) + 질문(ASK)
# ---------------------------------------------------------------------------

def pick_next_topic(topics):
    """다음 질문할 주제 선택 (가장 적게 질문한 주제 우선)."""
    if not topics:
        return None
    return min(topics, key=lambda t: t.get("total_questions", 0) or 0)


def _get_interval_minutes(settings):
    """설정에서 질문 주기(분)를 가져온다. interview_interval_minutes 우선, 없으면 hours 변환."""
    mins = settings.get("interview_interval_minutes")
    if mins is not None and int(mins) > 0:
        return int(mins)
    return int(settings.get("interview_interval_hours", 3)) * 60


def _format_interval(minutes):
    """분 → 사람이 읽기 좋은 형식."""
    if minutes < 60:
        return f"{minutes}분"
    hours = minutes / 60
    if hours == int(hours):
        return f"{int(hours)}시간"
    return f"{int(hours)}시간 {minutes % 60}분"


def should_ask_now(settings):
    """설정된 주기에 따라 지금 질문을 보낼 시간인지 확인."""
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if is_manual:
        return True

    last_asked = settings.get("interview_last_question_at")
    if not last_asked:
        return True

    interval_min = _get_interval_minutes(settings)
    try:
        last_dt = datetime.fromisoformat(last_asked.replace("Z", "+00:00"))
        elapsed = datetime.now(timezone.utc) - last_dt
        return elapsed >= timedelta(minutes=interval_min)
    except Exception:
        return True


def process_collect(settings):
    """텔레그램에서 새 메시지를 가져와 답변으로 저장."""
    last_uid = int(settings.get("interview_last_update_id", 0) or 0)

    print(f"  텔레그램 업데이트 확인 (offset: {last_uid + 1})...")
    updates = tg_get_updates(offset=last_uid + 1)

    if not updates:
        print("  새 메시지 없음")
        return set()

    print(f"  {len(updates)}개 새 메시지 발견")

    new_uid = last_uid
    topics_updated = set()

    for update in updates:
        uid = update["update_id"]
        if uid > new_uid:
            new_uid = uid

        msg = update.get("message", {})
        text = (msg.get("text") or "").strip()
        if not text:
            continue

        # 봇 명령어 처리
        if text.startswith("/"):
            handle_command(text, settings)
            continue

        # 일반 텍스트 → 현재 활성 주제에 답변으로 저장
        # 대기 중인 질문 여부와 관계없이, 가장 최근 활성 주제에 기록
        pending = get_pending_question()
        topic_id = None
        topic_name = None

        if pending:
            topic_id = pending["topic_id"]
        else:
            topics = get_active_topics()
            if topics:
                # 가장 최근에 질문이 있었던 주제 선택
                recent = max(topics, key=lambda t: t.get("total_questions", 0) or 0)
                topic_id = recent["id"]
                topic_name = recent["name"]

        if topic_id:
            sb_post("interview_messages", {
                "topic_id": topic_id,
                "role": "user",
                "content": text,
                "telegram_message_id": msg.get("message_id"),
            })
            topics_updated.add(topic_id)
            print(f"  답변 저장 (topic_id={topic_id}): {text[:60]}...")
            tg_send("답변이 기록되었습니다!")
        else:
            print(f"  활성 주제 없음, 메시지 무시: {text[:60]}...")

    # update_id 갱신
    if new_uid > last_uid:
        sb_patch("agent_settings?id=eq.1", {"interview_last_update_id": new_uid})

    return topics_updated


def process_ask(settings):
    """설정된 주기에 맞으면 새 인터뷰 질문 발송."""
    if not should_ask_now(settings):
        interval = settings.get("interview_interval_hours", 3)
        print(f"  아직 질문 시간 아님 (주기: {interval}시간)")
        return

    topics = get_active_topics()
    if not topics:
        print("  활성 주제 없음 — 질문 보류")
        return

    topic = pick_next_topic(topics)
    print(f"  선택된 주제: {topic['name']}")

    prev_qa = get_topic_messages(topic["id"])

    print("  Claude로 질문 생성 중...")
    question = generate_question(topic, prev_qa)
    print(f"  생성된 질문: {question[:80]}...")

    q_num = (topic.get("total_questions", 0) or 0) + 1
    label = (
        f"<b>[{topic['name']}]</b> (Q{q_num})\n\n"
        f"{question}\n\n"
        f"<i>답변을 입력해주세요. /건너뛰기 로 건너뛸 수 있습니다.</i>"
    )
    msg_id = tg_send(label)

    if msg_id:
        sb_post("interview_messages", {
            "topic_id": topic["id"],
            "role": "agent",
            "content": question,
            "telegram_message_id": msg_id,
        })
        sb_patch("agent_settings?id=eq.1", {
            "interview_last_question_at": datetime.now(timezone.utc).isoformat(),
        })
        sb_patch(f"interview_topics?id=eq.{topic['id']}", {
            "total_questions": q_num,
        })
        print(f"  질문 발송 완료 (Q{q_num}, msg_id={msg_id})")
    else:
        print("  질문 발송 실패!", file=sys.stderr)


def process_notion_sync(settings, topics_updated):
    """답변이 추가된 주제들의 노션 동기화."""
    if not topics_updated:
        return
    if not _notion_available():
        print("  노션 미설정 — 건너뜀")
        return

    for topic_id in topics_updated:
        try:
            rows = sb_get(f"interview_topics?id=eq.{topic_id}")
            if not rows:
                continue
            topic = rows[0]
            all_qa = get_topic_messages(topic_id, limit=200)

            # 답변이 5개, 10개, 15개... 단위로 대본 자동 생성
            answer_count = len([m for m in all_qa if m["role"] == "user"])
            organized = None
            if answer_count >= 5 and answer_count % 5 == 0:
                print(f"  [{topic['name']}] 답변 {answer_count}개 — 대본 자동 생성")
                organized = generate_organized_content(topic, all_qa)
                # Supabase에도 대본 저장
                sb_patch(
                    f"interview_topics?id=eq.{topic_id}",
                    {
                        "draft": organized,
                        "draft_updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                print(f"  Supabase에 대본 저장 완료")

            sync_to_notion(settings, topic, all_qa, organized)
        except Exception as e:
            print(f"  노션 동기화 실패 (topic_id={topic_id}): {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def _webhook_active():
    """텔레그램 웹훅이 설정되어 있는지 확인."""
    token = _tg_token()
    if not token:
        return False
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/getWebhookInfo",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            info = json.loads(resp.read().decode())
            url = info.get("result", {}).get("url", "")
            return bool(url)
    except Exception:
        return False


def main():
    print("=== 인터뷰 에이전트 시작 ===\n")

    print("[설정] Supabase에서 설정 로드 중...")
    settings = fetch_settings()

    if not settings.get("interview_enabled"):
        print("인터뷰 에이전트가 비활성화 상태입니다. 종료합니다.")
        sys.exit(0)

    interval_min = _get_interval_minutes(settings)
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    webhook = _webhook_active()
    print(f"질문 주기: {_format_interval(interval_min)} | 노션: {'연결됨' if _notion_available() else '미설정'} | 웹훅: {'활성' if webhook else '비활성'}")
    if is_manual:
        print("수동 실행 모드")
    print()

    topics_updated = set()

    # 1단계: 텔레그램 답변 수집 (웹훅 미사용 시에만)
    if webhook:
        print("[1/2] 웹훅 활성 — 메시지 수집 건너뜀 (실시간 처리 중)")
    else:
        print("[1/2] 답변 수집 중 (폴링 모드)...")
        try:
            topics_updated = process_collect(settings)
        except Exception as e:
            print(f"답변 수집 오류: {e}", file=sys.stderr)

    # 2단계: 질문 발송
    print(f"\n[2/2] 질문 발송 확인...")
    try:
        process_ask(settings)
    except Exception as e:
        print(f"질문 발송 오류: {e}", file=sys.stderr)

    # 노션 동기화 (답변이 새로 수집된 경우에만)
    if topics_updated:
        print("\n[추가] 노션 동기화...")
        try:
            process_notion_sync(settings, topics_updated)
        except Exception as e:
            print(f"노션 동기화 오류: {e}", file=sys.stderr)

    print("\n=== 인터뷰 에이전트 완료 ===")


if __name__ == "__main__":
    main()
