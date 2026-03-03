#!/usr/bin/env python3
"""
인터뷰 대본 생성 (독립 실행)

텔레그램 /대본 명령어로 트리거되며,
지정된 주제(또는 전체)의 대본을 생성하여 Supabase + 노션 + 텔레그램에 전송합니다.
"""

import os
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


def generate_draft_for_topic(settings, target):
    """단일 주제의 대본을 생성하고 저장·전송한다."""
    all_qa = get_topic_messages(target["id"], limit=200)
    user_answers = [m for m in all_qa if m["role"] == "user"]

    if len(user_answers) < 3:
        tg_send(
            f"'{target['name']}' 주제의 답변이 아직 {len(user_answers)}개뿐입니다.\n"
            f"최소 3개 이상의 답변이 필요합니다."
        )
        print(f"  [{target['name']}] 답변 부족 ({len(user_answers)}개) — 건너뜀")
        return False

    print(f"  [{target['name']}] Claude로 대본 생성 중...")
    content = generate_organized_content(target, all_qa)

    # Supabase에 대본 저장
    now = datetime.now(timezone.utc).isoformat()
    sb_patch(
        f"interview_topics?id=eq.{target['id']}",
        {"draft": content, "draft_updated_at": now},
    )
    print(f"  [{target['name']}] Supabase에 대본 저장 완료")

    # 노션에 새 페이지로 저장
    page_id = sync_to_notion(settings, target, all_qa, content, force_new_page=True)

    # 텔레그램에 노션 링크 발송
    if page_id:
        url = _notion_page_url(page_id)
        tg_send(
            f"<b>[{target['name']}] 대본이 생성되었습니다.</b>\n\n"
            f'<a href="{url}">노션에서 보기</a>'
        )
    else:
        tg_send(f"<b>[{target['name']}]</b> 대본이 생성되었습니다. (노션 동기화 실패)")
    print(f"  [{target['name']}] 대본 전송 완료")
    return True


def main():
    print("=== 대본 생성 시작 ===\n")

    settings = fetch_settings()
    topics = get_active_topics()

    if not topics:
        tg_send("활성화된 주제가 없습니다.")
        print("활성 주제 없음")
        return

    topic_keyword = os.environ.get("TOPIC_NAME", "").strip()

    if topic_keyword == "__all__":
        # 전체 주제 대본 생성
        print(f"전체 주제 대본 생성 ({len(topics)}개)")
        success = 0
        for t in topics:
            try:
                if generate_draft_for_topic(settings, t):
                    success += 1
            except Exception as e:
                tg_send(f"[{t['name']}] 대본 생성 실패: {e}")
                print(f"  [{t['name']}] 실패: {e}", file=sys.stderr)
        print(f"\n전체 {len(topics)}개 중 {success}개 완료")
    else:
        # 단일 주제 선택
        if topic_keyword:
            target = None
            for t in topics:
                if topic_keyword in t["name"]:
                    target = t
                    break
            if not target:
                tg_send(f"'{topic_keyword}' 주제를 찾을 수 없습니다.")
                print(f"주제 '{topic_keyword}' 없음")
                return
        else:
            target = max(topics, key=lambda t: t.get("total_questions", 0) or 0)

        print(f"대상 주제: {target['name']}")
        try:
            generate_draft_for_topic(settings, target)
        except Exception as e:
            tg_send(f"대본 생성 실패: {e}")
            print(f"대본 생성 실패: {e}", file=sys.stderr)
            sys.exit(1)

    print("\n=== 대본 생성 완료 ===")


if __name__ == "__main__":
    main()
