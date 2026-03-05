"""
대화 메모리 - 유저별 대화 이력 저장 및 맥락 제공

2단계 메모리 구조:
1. 원본 저장: 유저별 최대 500턴 보관
2. 컨텍스트 빌드 시:
   - 최근 50턴: 전문 포함 (디테일 유지)
   - 오래된 턴: 압축 요약 (핵심만 유지)
   → 거의 모든 대화 맥락을 LLM에 전달 가능
"""

import json
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("conversation_memory")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MEMORY_FILE = os.path.join(DATA_DIR, "conversation_memory.json")

# 유저별 최대 대화 턴 수 (원본 보관)
MAX_TURNS_PER_USER = 500
# LLM 컨텍스트에 전문으로 넣을 최근 대화 수
RECENT_VERBATIM = 50
# 오래된 대화 압축 시 포함할 최대 턴 수
OLDER_COMPRESSED_MAX = 450


def _load_all() -> dict:
    """전체 메모리 로드 {user_id: [turns]}"""
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_all(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))


def save_turn(user_id: str, role: str, content: str, metadata: dict = None):
    """대화 턴 저장"""
    data = _load_all()
    if user_id not in data:
        data[user_id] = []

    turn = {
        "role": role,
        "content": content,
        "ts": datetime.now(KST).isoformat(),
    }
    if metadata:
        turn["meta"] = metadata

    data[user_id].append(turn)
    data[user_id] = data[user_id][-MAX_TURNS_PER_USER:]
    _save_all(data)


def get_recent_turns(user_id: str, n: int = RECENT_VERBATIM) -> list[dict]:
    """유저의 최근 대화 턴 가져오기"""
    data = _load_all()
    turns = data.get(user_id, [])
    return turns[-n:]


def _compress_older_turns(turns: list[dict]) -> str:
    """오래된 턴들을 압축 요약 (날짜별 그룹핑 + 핵심만)"""
    if not turns:
        return ""

    # 날짜별로 그룹핑
    by_date = {}
    for t in turns:
        ts = t.get("ts", "")
        date_key = ts[:10] if len(ts) >= 10 else "unknown"
        if date_key not in by_date:
            by_date[date_key] = []
        by_date[date_key].append(t)

    lines = []
    for date_key in sorted(by_date.keys()):
        day_turns = by_date[date_key]
        lines.append(f"[{date_key}]")
        for t in day_turns:
            role = "U" if t["role"] == "user" else "A"
            meta = t.get("meta", {})
            action = meta.get("action", "")
            tag = f"({action})" if action else ""
            # 유저 메시지는 좀 더 길게, 어시스턴트 응답은 짧게
            max_len = 200 if role == "U" else 120
            content = t["content"][:max_len]
            if len(t["content"]) > max_len:
                content += "…"
            lines.append(f"  {role}{tag}: {content}")

    return "\n".join(lines)


def build_chat_context(user_id: str) -> str:
    """LLM에 넘길 대화 이력 문자열 생성 (2단계 메모리)

    구조:
    1. [장기 기억] 오래된 대화 압축 요약
    2. [최근 대화] 최근 50턴 전문
    """
    data = _load_all()
    all_turns = data.get(user_id, [])
    if not all_turns:
        return ""

    parts = []

    # 1단계: 오래된 턴 압축 (RECENT_VERBATIM 이전)
    if len(all_turns) > RECENT_VERBATIM:
        older = all_turns[:-RECENT_VERBATIM]
        compressed = _compress_older_turns(older)
        if compressed:
            parts.append(f"=== 이전 대화 기록 (요약) ===\n{compressed}")

    # 2단계: 최근 턴 전문
    recent = all_turns[-RECENT_VERBATIM:]
    recent_lines = []
    for t in recent:
        role_label = "유저" if t["role"] == "user" else "어시스턴트"
        meta = t.get("meta", {})
        action = meta.get("action", "")
        suffix = f" [{action}]" if action else ""
        ts = t.get("ts", "")
        time_str = ts[11:16] if len(ts) >= 16 else ""  # HH:MM
        date_str = ts[:10] if len(ts) >= 10 else ""
        prefix = f"({date_str} {time_str})" if date_str else ""
        recent_lines.append(f"{prefix} [{role_label}{suffix}] {t['content']}")

    parts.append(f"=== 최근 대화 (전문) ===\n" + "\n".join(recent_lines))

    return "\n\n".join(parts)


def get_user_summary(user_id: str) -> str:
    """유저의 관심사/패턴 요약 (작업 맥락용)"""
    data = _load_all()
    all_turns = data.get(user_id, [])
    if not all_turns:
        return ""

    user_messages = [t["content"] for t in all_turns if t["role"] == "user"]
    if not user_messages:
        return ""

    # 전체 유저 메시지에서 패턴 추출
    recent = user_messages[-20:]
    return "유저의 최근 대화/관심사:\n" + "\n".join(f"- {m[:150]}" for m in recent)
