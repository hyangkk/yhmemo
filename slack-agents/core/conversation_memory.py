"""
대화 메모리 - 유저별 대화 이력 저장 및 맥락 제공

유저가 봇과 나눈 대화를 기억하여:
1. chat 대화 시 이전 맥락을 활용해 깊은 대화 가능
2. collect/briefing 등 작업 시에도 유저의 관심사/선호를 참고
"""

import json
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("conversation_memory")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MEMORY_FILE = os.path.join(DATA_DIR, "conversation_memory.json")

# 유저별 최대 대화 턴 수
MAX_TURNS_PER_USER = 50
# LLM 컨텍스트에 넣을 최근 대화 수
CONTEXT_TURNS = 15


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
    """대화 턴 저장

    Args:
        user_id: 슬랙 유저 ID
        role: "user" 또는 "assistant"
        content: 메시지 내용
        metadata: 추가 정보 (intent, action 등)
    """
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
    # 최대 턴 수 유지
    data[user_id] = data[user_id][-MAX_TURNS_PER_USER:]
    _save_all(data)


def get_recent_turns(user_id: str, n: int = CONTEXT_TURNS) -> list[dict]:
    """유저의 최근 대화 턴 가져오기"""
    data = _load_all()
    turns = data.get(user_id, [])
    return turns[-n:]


def build_chat_context(user_id: str) -> str:
    """LLM에 넘길 대화 이력 문자열 생성"""
    turns = get_recent_turns(user_id)
    if not turns:
        return ""

    lines = []
    for t in turns:
        role_label = "유저" if t["role"] == "user" else "어시스턴트"
        meta = t.get("meta", {})
        action = meta.get("action", "")
        suffix = f" [{action}]" if action else ""
        lines.append(f"[{role_label}{suffix}] {t['content']}")

    return "\n".join(lines)


def get_user_summary(user_id: str) -> str:
    """유저의 관심사/패턴 요약 (작업 맥락용)

    최근 대화에서 유저가 어떤 주제에 관심 있는지 파악
    """
    turns = get_recent_turns(user_id, n=30)
    if not turns:
        return ""

    user_messages = [t["content"] for t in turns if t["role"] == "user"]
    if not user_messages:
        return ""

    # 최근 유저 메시지들만 요약용으로 반환
    recent = user_messages[-10:]
    return "유저의 최근 대화/관심사:\n" + "\n".join(f"- {m[:100]}" for m in recent)
