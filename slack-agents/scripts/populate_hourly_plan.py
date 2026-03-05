"""
노션 타임라인에 오늘의 시간별 계획을 등록하는 스크립트

실행:
  cd slack-agents && python -m scripts.populate_hourly_plan
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


# 오늘 (3/6) 시간별 계획 — 매시간 결과물이 나와야 함
HOURLY_PLAN = {
    "00": {"task": "시스템 점검 & 코드 안정화", "method": "build", "expected": "에러 0건, 전 에이전트 정상 가동", "assignee": "마스터에이전트"},
    "01": {"task": "웹 서비스 프로젝트 초기 세팅 (Next.js)", "method": "build", "expected": "web-service/ 디렉토리 생성, Next.js 프로젝트 초기화 완료", "assignee": "마스터에이전트"},
    "02": {"task": "Supabase 연동 API 라우트 구축", "method": "build", "expected": "GET /api/briefings 엔드포인트 동작", "assignee": "마스터에이전트"},
    "03": {"task": "메인 대시보드 UI 구축", "method": "build", "expected": "뉴스 카드 리스트 UI 렌더링", "assignee": "마스터에이전트"},
    "04": {"task": "AI 브리핑 요약 표시 기능", "method": "build", "expected": "각 뉴스에 AI 요약 표시", "assignee": "마스터에이전트"},
    "05": {"task": "랜딩 페이지 & 소개 문구 작성", "method": "build", "expected": "랜딩 페이지 완성", "assignee": "마스터에이전트"},
    "06": {"task": "반응형 디자인 & 스타일 마무리", "method": "build", "expected": "모바일/데스크톱 대응 완료", "assignee": "마스터에이전트"},
    "07": {"task": "Vercel 배포 준비 & 테스트", "method": "build", "expected": "로컬 빌드 성공, 배포 설정 완료", "assignee": "마스터에이전트"},
    "08": {"task": "모닝 브리핑 + Vercel 배포 실행", "method": "communicate", "expected": "베타 서비스 URL 생성 완료", "assignee": "마스터에이전트"},
    "09": {"task": "베타 서비스 QA & 버그 수정", "method": "build", "expected": "주요 버그 0건", "assignee": "마스터에이전트"},
    "10": {"task": "뉴스 수집 데이터 품질 개선", "method": "build", "expected": "수집 소스 추가, 중복 제거 강화", "assignee": "Collector"},
    "11": {"task": "AI 선별 정확도 튜닝", "method": "research", "expected": "선별 프롬프트 개선, 정확도 향상", "assignee": "마스터에이전트"},
    "12": {"task": "서비스 소개 콘텐츠 작성", "method": "communicate", "expected": "블로그/SNS 공유용 소개글 완성", "assignee": "마스터에이전트"},
    "13": {"task": "프리미엄 기능 설계 (심층분석)", "method": "research", "expected": "프리미엄 기능 스펙 문서 초안", "assignee": "마스터에이전트"},
    "14": {"task": "사용자 피드백 수집 기능 추가", "method": "build", "expected": "웹에서 피드백 버튼 동작", "assignee": "마스터에이전트"},
    "15": {"task": "SEO & 메타태그 최적화", "method": "build", "expected": "OG 태그, 타이틀 최적화 완료", "assignee": "마스터에이전트"},
    "16": {"task": "실시간 데이터 갱신 기능", "method": "build", "expected": "자동 새로고침 또는 SSR 적용", "assignee": "마스터에이전트"},
    "17": {"task": "성과 측정 & 모니터링 세팅", "method": "measure", "expected": "접속 수/에러 모니터링 대시보드", "assignee": "마스터에이전트"},
    "18": {"task": "수익 모델 초안 작성", "method": "research", "expected": "가격 정책 & 프리미엄 기능 정리", "assignee": "마스터에이전트"},
    "19": {"task": "외부 공유 & 커뮤니티 소개", "method": "communicate", "expected": "최소 1곳에 서비스 소개 완료", "assignee": "마스터에이전트"},
    "20": {"task": "사용자 경험 개선 (UX 리뷰)", "method": "build", "expected": "UI/UX 개선점 3건 이상 반영", "assignee": "마스터에이전트"},
    "21": {"task": "내일 계획 수립 & 노션 업데이트", "method": "measure", "expected": "내일 시간별 계획 등록", "assignee": "마스터에이전트"},
    "22": {"task": "코드 정리 & 커밋", "method": "build", "expected": "깨끗한 커밋 히스토리", "assignee": "마스터에이전트"},
    "23": {"task": "일일 리뷰 & 자기 평가", "method": "measure", "expected": "하루 종합 평가 완료, 깨달음 기록", "assignee": "마스터에이전트"},
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

    # 기존 주 단위 목표 항목은 그대로 두고, 시간별 항목 추가
    print(f"오늘({today}) 시간별 계획 등록 중...\n")

    for hour_str in sorted(HOURLY_PLAN.keys()):
        plan = HOURLY_PLAN[hour_str]
        hour = int(hour_str)

        # 시작/종료 시간 (ISO 형식)
        start_dt = f"{today}T{hour_str}:00:00+09:00"
        end_dt = f"{today}T{hour_str}:59:00+09:00"

        # 현재 시간 기준 상태
        if hour < now.hour:
            status = "완료"  # 이미 지난 시간
            progress = 1.0
        elif hour == now.hour:
            status = "진행중"
            progress = 0.5
        else:
            status = "대기"
            progress = 0.0

        name = f"[{hour_str}:00] {plan['task']}"

        # 카테고리 매핑
        method = plan.get("method", "build")
        cat_map = {"build": "베타런칭", "research": "영향력", "measure": "인프라", "communicate": "영향력"}
        category = cat_map.get(method, "베타런칭")

        result = await client.add_timeline_item(
            db_id=db_id,
            name=name,
            status=status,
            assignee=plan.get("assignee", "마스터에이전트"),
            start=start_dt,
            end=end_dt,
            priority="P1-긴급" if hour <= 8 else "P2-높음",
            category=category,
            progress=progress,
            memo=f"예상 결과: {plan['expected']}",
        )

        icon = "✅" if result else "❌"
        print(f"  {icon} {name}")

    print(f"\n완료! 노션 타임라인 뷰에서 시간별 간트차트를 확인하세요.")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
