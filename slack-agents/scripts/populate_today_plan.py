"""
오늘(3/7) 노션 타임라인 업데이트 — 어제 미완 항목 이관 + 오늘 계획

실행: cd slack-agents && python -m scripts.populate_today_plan
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from integrations.notion_client import NotionClient

KST = timezone(timedelta(hours=9))

# 3/7 시간별 계획 — 어제 못한 것 우선 + 오늘 할 것
HOURLY_PLAN = {
    "09": {"task": "Vercel 토큰 설정 & 프로덕션 배포", "method": "build", "expected": "베타 서비스 URL 생성", "assignee": "마스터에이전트"},
    "10": {"task": "배포 후 QA — 모닝브리핑/대시보드/API 동작 확인", "method": "build", "expected": "주요 기능 정상 동작", "assignee": "마스터에이전트"},
    "11": {"task": "수집 데이터 품질 개선 — 소스 추가, 중복 제거", "method": "build", "expected": "수집 소스 3개 이상", "assignee": "Collector"},
    "12": {"task": "서비스 소개 콘텐츠 작성 (블로그/SNS)", "method": "communicate", "expected": "소개글 1건 완성", "assignee": "마스터에이전트"},
    "13": {"task": "프리미엄 기능 설계 — 심층분석, 맞춤 알림", "method": "research", "expected": "프리미엄 스펙 초안", "assignee": "마스터에이전트"},
    "14": {"task": "사용자 피드백 수집 기능 추가", "method": "build", "expected": "피드백 버튼 동작", "assignee": "마스터에이전트"},
    "15": {"task": "실시간 데이터 갱신 기능 (ISR/SSR)", "method": "build", "expected": "자동 갱신 적용", "assignee": "마스터에이전트"},
    "16": {"task": "성과 측정 & 모니터링 세팅", "method": "measure", "expected": "접속 수 모니터링", "assignee": "마스터에이전트"},
    "17": {"task": "수익 모델 초안 — 가격 정책 & 프리미엄 기능", "method": "research", "expected": "가격 정책 문서", "assignee": "마스터에이전트"},
    "18": {"task": "외부 공유 & 커뮤니티 소개", "method": "communicate", "expected": "1곳 이상 소개 완료", "assignee": "마스터에이전트"},
    "19": {"task": "UX 개선 — 모바일 최적화, 로딩 개선", "method": "build", "expected": "UX 개선 3건 반영", "assignee": "마스터에이전트"},
    "20": {"task": "내일 계획 수립 & 노션 업데이트", "method": "measure", "expected": "3/8 계획 등록", "assignee": "마스터에이전트"},
    "21": {"task": "코드 정리 & 커밋", "method": "build", "expected": "깨끗한 커밋", "assignee": "마스터에이전트"},
    "22": {"task": "일일 리뷰 & 자기 평가", "method": "measure", "expected": "하루 종합 평가", "assignee": "마스터에이전트"},
}


async def main():
    api_key = os.environ.get("NOTION_API_KEY", "")
    if not api_key:
        print("ERROR: NOTION_API_KEY 없음")
        return

    state_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "proactive_state.json")
    with open(state_file, "r") as f:
        state = json.loads(f.read())
    db_id = state.get("notion_timeline_db_id", "")
    if not db_id:
        print("ERROR: notion_timeline_db_id 없음")
        return

    client = NotionClient(api_key)
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")

    print(f"오늘({today}) 시간별 계획 등록 중...\n")

    for hour_str in sorted(HOURLY_PLAN.keys()):
        plan = HOURLY_PLAN[hour_str]
        hour = int(hour_str)

        start_dt = f"{today}T{hour_str}:00:00+09:00"
        end_dt = f"{today}T{hour_str}:59:00+09:00"

        if hour < now.hour:
            status = "대기"  # 지난 시간이지만 아직 미완
            progress = 0.0
        elif hour == now.hour:
            status = "진행중"
            progress = 0.5
        else:
            status = "대기"
            progress = 0.0

        name = f"[{hour_str}:00] {plan['task']}"

        method = plan.get("method", "build")
        cat_map = {"build": "베타런칭", "research": "수익화", "measure": "인프라", "communicate": "영향력"}
        category = cat_map.get(method, "베타런칭")

        result = await client.add_timeline_item(
            db_id=db_id,
            name=name,
            status=status,
            assignee=plan.get("assignee", "마스터에이전트"),
            start=start_dt,
            end=end_dt,
            priority="P1-긴급" if hour <= 12 else "P2-높음",
            category=category,
            progress=progress,
            memo=f"예상 결과: {plan['expected']}",
        )

        icon = "✅" if result else "❌"
        print(f"  {icon} {name}")

    print(f"\n완료! 노션 타임라인에서 확인하세요.")
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
