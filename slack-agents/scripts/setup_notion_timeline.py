"""
노션 타임라인(간트차트) 데이터베이스 초기 설정 스크립트

실행:
  cd slack-agents && python -m scripts.setup_notion_timeline

필요 환경변수:
  NOTION_API_KEY — Notion Integration Token
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

from integrations.notion_client import NotionClient


async def main():
    api_key = os.environ.get("NOTION_API_KEY", "")
    if not api_key:
        print("ERROR: NOTION_API_KEY 환경변수가 비어있습니다.")
        print("  1. https://www.notion.so/my-integrations 에서 Integration 생성")
        print("  2. slack-agents/.env 에 NOTION_API_KEY=<token> 추가")
        print("  3. 노션에서 해당 Integration을 워크스페이스에 연결")
        return

    client = NotionClient(api_key)

    print("노션 워크스페이스 검색 중...")
    pages = await client.search_pages()

    if not pages:
        print("ERROR: 접근 가능한 노션 페이지가 없습니다.")
        print("  노션에서 Integration 연결을 확인하세요.")
        await client.close()
        return

    # 첫 번째 페이지를 부모로 사용
    parent_page = pages[0]
    parent_id = parent_page["id"]
    parent_title = ""
    props = parent_page.get("properties", {})
    title_prop = props.get("title", props.get("Name", {}))
    if isinstance(title_prop, dict):
        title_arr = title_prop.get("title", [])
        if title_arr:
            parent_title = title_arr[0].get("plain_text", "")

    print(f"부모 페이지: {parent_title or parent_id}")
    print("타임라인 데이터베이스 생성 중...")

    result = await client.create_timeline_database(parent_id)

    if result:
        db_id = result["id"]
        db_url = result.get("url", "")
        print(f"\n✅ 타임라인 데이터베이스 생성 완료!")
        print(f"  DB ID: {db_id}")
        print(f"  URL: {db_url}")

        # proactive_state.json에 저장
        state_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "proactive_state.json"
        )
        os.makedirs(os.path.dirname(state_file), exist_ok=True)

        state = {}
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.loads(f.read())
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        state["notion_timeline_db_id"] = db_id
        with open(state_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(state, ensure_ascii=False, indent=2))

        print(f"  → proactive_state.json에 notion_timeline_db_id 저장 완료")

        # 기본 목표 항목 추가
        print("\n기본 목표 항목 추가 중...")
        goals = [
            {
                "name": "AI 뉴스 브리핑 베타 서비스 런칭",
                "status": "진행중",
                "assignee": "마스터에이전트",
                "start": "2026-03-05",
                "end": "2026-03-08",
                "priority": "P1-긴급",
                "category": "베타런칭",
                "progress": 0,
                "memo": "이번 주말까지 웹 서비스 런칭",
            },
            {
                "name": "긍정적 영향력 확대",
                "status": "대기",
                "assignee": "마스터에이전트",
                "start": "2026-03-05",
                "end": "2026-03-15",
                "priority": "P2-높음",
                "category": "영향력",
                "progress": 0,
                "memo": "콘텐츠/서비스 대외 활동",
            },
            {
                "name": "수익 모델 설계 및 검증",
                "status": "대기",
                "assignee": "마스터에이전트",
                "start": "2026-03-08",
                "end": "2026-03-20",
                "priority": "P3-보통",
                "category": "수익화",
                "progress": 0,
                "memo": "베타 기반 수익 모델 검증",
            },
            {
                "name": "시장 모니터링 유지",
                "status": "진행중",
                "assignee": "Collector",
                "start": "2026-03-05",
                "end": "2026-03-31",
                "priority": "P4-낮음",
                "category": "인프라",
                "progress": 0.3,
                "memo": "뉴스/시장 데이터 수집 자동화",
            },
        ]

        for g in goals:
            item = await client.add_timeline_item(
                db_id=db_id,
                name=g["name"],
                status=g["status"],
                assignee=g["assignee"],
                start=g["start"],
                end=g["end"],
                priority=g["priority"],
                category=g["category"],
                progress=g["progress"],
                memo=g["memo"],
            )
            if item:
                print(f"  ✅ {g['name']}")
            else:
                print(f"  ❌ {g['name']} (실패)")

        print(f"\n완료! 노션에서 타임라인 뷰로 전환하면 간트차트가 보입니다.")
        print(f"URL: {db_url}")
    else:
        print("❌ 데이터베이스 생성 실패")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
