#!/usr/bin/env python3
"""
대본 텍스트 수정 스크립트

Supabase의 대본 + interview_messages 원본에서 텍스트를 치환하고,
노션 페이지도 업데이트합니다.

환경변수:
  FIND_TEXT: 찾을 텍스트
  REPLACE_TEXT: 바꿀 텍스트
"""

import os
import sys

sys.path.insert(0, "scripts")
from interview_agent import (
    fetch_settings,
    get_active_topics,
    get_topic_messages,
    sync_to_notion,
    tg_send,
    sb_get,
    sb_patch,
)


def main():
    find_text = os.environ.get("FIND_TEXT", "")
    replace_text = os.environ.get("REPLACE_TEXT", "")

    if not find_text or not replace_text:
        print("FIND_TEXT, REPLACE_TEXT 환경변수가 필요합니다.")
        sys.exit(1)

    print(f"=== 대본 수정: '{find_text}' → '{replace_text}' ===\n")

    settings = fetch_settings()
    topics = get_active_topics()

    if not topics:
        print("활성 주제 없음")
        return

    target = max(topics, key=lambda t: t.get("total_questions", 0) or 0)
    print(f"대상 주제: {target['name']}")

    # 1) interview_messages 원본 답변에서도 수정
    all_qa = get_topic_messages(target["id"], limit=200)
    updated_msgs = 0
    for msg in all_qa:
        if find_text in msg["content"]:
            new_content = msg["content"].replace(find_text, replace_text)
            sb_patch(
                f"interview_messages?id=eq.{msg['id']}",
                {"content": new_content},
            )
            updated_msgs += 1
            print(f"  메시지 #{msg['id']} 수정됨")

    print(f"  총 {updated_msgs}개 메시지 수정\n")

    # 2) draft 텍스트 수정
    draft = target.get("draft", "")
    if not draft:
        print("대본이 아직 없습니다. /대본 명령어를 먼저 실행하세요.")
        return

    if find_text not in draft:
        print(f"대본에서 '{find_text}'를 찾을 수 없습니다.")
        # 메시지만 수정된 경우 대본을 재생성할 수 있지만, 일단 노션 동기화만 진행
    else:
        new_draft = draft.replace(find_text, replace_text)
        sb_patch(
            f"interview_topics?id=eq.{target['id']}",
            {"draft": new_draft},
        )
        draft = new_draft
        print("  Supabase 대본 수정 완료")

    # 3) 노션 페이지 업데이트 (수정된 메시지 + 수정된 대본으로)
    updated_qa = get_topic_messages(target["id"], limit=200)
    sync_to_notion(settings, target, updated_qa, draft)

    tg_send(f"'{find_text}' → '{replace_text}' 수정 완료! 노션도 업데이트되었습니다.")
    print("\n=== 수정 완료 ===")


if __name__ == "__main__":
    main()
