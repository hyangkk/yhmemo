#!/usr/bin/env python3
"""
인터뷰 대본 생성 (독립 실행)

텔레그램 /대본 명령어로 트리거되며,
가장 Q&A가 많은 주제의 대본을 생성하여 Supabase + 노션 + 텔레그램에 전송합니다.
"""

import sys
from datetime import datetime, timezone, timedelta

# 기존 interview_agent 모듈의 함수들을 재사용
sys.path.insert(0, "scripts")
from interview_agent import (
    fetch_settings,
    get_active_topics,
    get_topic_messages,
    generate_organized_content,
    sync_to_notion,
    tg_send,
    sb_patch,
    _notion_page_url,
)

KST = timezone(timedelta(hours=9))


def main():
    print("=== 대본 생성 시작 ===\n")

    settings = fetch_settings()
    topics = get_active_topics()

    if not topics:
        tg_send("활성화된 주제가 없습니다.")
        print("활성 주제 없음")
        return

    # 가장 Q&A가 많은 주제 선택
    target = max(topics, key=lambda t: t.get("total_questions", 0) or 0)
    print(f"대상 주제: {target['name']}")

    all_qa = get_topic_messages(target["id"], limit=200)
    user_answers = [m for m in all_qa if m["role"] == "user"]

    if len(user_answers) < 3:
        tg_send(
            f"'{target['name']}' 주제의 답변이 아직 {len(user_answers)}개뿐입니다.\n"
            f"최소 3개 이상의 답변이 필요합니다."
        )
        return

    print("Claude로 대본 생성 중...")
    try:
        content = generate_organized_content(target, all_qa)

        # 1) Supabase에 대본 저장
        now = datetime.now(timezone.utc).isoformat()
        sb_patch(
            f"interview_topics?id=eq.{target['id']}",
            {"draft": content, "draft_updated_at": now},
        )
        print("  Supabase에 대본 저장 완료")

        # 2) 노션에 저장
        page_id = sync_to_notion(settings, target, all_qa, content)

        # 3) 텔레그램에 노션 링크만 발송
        if page_id:
            url = _notion_page_url(page_id)
            tg_send(
                f"<b>[{target['name']}] 대본이 생성되었습니다.</b>\n\n"
                f'<a href="{url}">노션에서 보기</a>'
            )
        else:
            tg_send(f"<b>[{target['name']}]</b> 대본이 생성되었습니다. (노션 동기화 실패)")
        print("대본 전송 완료")
    except Exception as e:
        tg_send(f"대본 생성 실패: {e}")
        print(f"대본 생성 실패: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n=== 대본 생성 완료 ===")


if __name__ == "__main__":
    main()
