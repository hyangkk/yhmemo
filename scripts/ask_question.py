#!/usr/bin/env python3
"""
인터뷰 질문 즉시 생성 (독립 실행)

텔레그램 /질문줘 명령어로 트리거되며,
주기와 관계없이 즉시 새 인터뷰 질문을 생성하여 발송합니다.
"""

import sys
from datetime import datetime, timezone

sys.path.insert(0, "scripts")
from interview_agent import (
    fetch_settings,
    get_active_topics,
    get_topic_messages,
    pick_next_topic,
    generate_question,
    tg_send,
    sb_post,
    sb_patch,
)


def main():
    print("=== 질문 즉시 생성 시작 ===\n")

    settings = fetch_settings()
    topics = get_active_topics()

    if not topics:
        tg_send("활성화된 주제가 없습니다.")
        print("활성 주제 없음")
        return

    topic = pick_next_topic(topics)
    print(f"대상 주제: {topic['name']}")

    prev_qa = get_topic_messages(topic["id"])

    print("Claude로 질문 생성 중...")
    question = generate_question(topic, prev_qa)
    print(f"생성된 질문: {question[:80]}...")

    q_num = (topic.get("total_questions", 0) or 0) + 1
    label = (
        f"<b>[{topic['name']}]</b> (Q{q_num})\n\n"
        f"{question}"
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
        print(f"질문 발송 완료 (Q{q_num})")
    else:
        print("질문 발송 실패!", file=sys.stderr)
        sys.exit(1)

    print("\n=== 질문 즉시 생성 완료 ===")


if __name__ == "__main__":
    main()
