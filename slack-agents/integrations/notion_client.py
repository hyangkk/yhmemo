"""
Notion 연동 클라이언트

수집/선별 결과를 노션 데이터베이스에 저장하고,
액션아이템을 읽어와 에이전트에게 작업을 전달.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionClient:
    """노션 API 클라이언트"""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
        self._http = httpx.AsyncClient(
            base_url=NOTION_API_BASE,
            headers=self._headers,
            timeout=30.0,
        )

    # ── 데이터베이스 조회 ──────────────────────────────

    async def query_database(self, database_id: str, filter_dict: dict = None,
                             sorts: list = None, page_size: int = 100) -> list[dict]:
        """노션 데이터베이스 쿼리"""
        body: dict[str, Any] = {"page_size": page_size}
        if filter_dict:
            body["filter"] = filter_dict
        if sorts:
            body["sorts"] = sorts

        try:
            resp = await self._http.post(f"/databases/{database_id}/query", json=body)
            resp.raise_for_status()
            return resp.json().get("results", [])
        except Exception as e:
            logger.error(f"Notion query failed: {e}")
            return []

    # ── 페이지 생성 ────────────────────────────────────

    async def create_page(self, database_id: str, properties: dict,
                          content_blocks: list = None) -> dict | None:
        """노션 데이터베이스에 새 페이지(항목) 생성"""
        body: dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        if content_blocks:
            body["children"] = content_blocks

        try:
            resp = await self._http.post("/pages", json=body)
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"Notion page created: {result.get('id')}")
            return result
        except Exception as e:
            logger.error(f"Notion create page failed: {e}")
            return None

    # ── 페이지 업데이트 ────────────────────────────────

    async def update_page(self, page_id: str, properties: dict) -> dict | None:
        """노션 페이지 속성 업데이트"""
        try:
            resp = await self._http.patch(f"/pages/{page_id}", json={"properties": properties})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Notion update page failed: {e}")
            return None

    # ── 블록 추가 ──────────────────────────────────────

    async def append_blocks(self, page_id: str, blocks: list) -> bool:
        """페이지에 콘텐츠 블록 추가"""
        try:
            resp = await self._http.patch(
                f"/blocks/{page_id}/children",
                json={"children": blocks},
            )
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Notion append blocks failed: {e}")
            return False

    # ── 헬퍼: 노션 프로퍼티 빌더 ──────────────────────

    @staticmethod
    def prop_title(text: str) -> dict:
        return {"title": [{"text": {"content": text}}]}

    @staticmethod
    def prop_rich_text(text: str) -> dict:
        return {"rich_text": [{"text": {"content": text[:2000]}}]}

    @staticmethod
    def prop_select(value: str) -> dict:
        return {"select": {"name": value}}

    @staticmethod
    def prop_multi_select(values: list[str]) -> dict:
        return {"multi_select": [{"name": v} for v in values]}

    @staticmethod
    def prop_url(url: str) -> dict:
        return {"url": url}

    @staticmethod
    def prop_number(value: float) -> dict:
        return {"number": value}

    @staticmethod
    def prop_checkbox(checked: bool) -> dict:
        return {"checkbox": checked}

    @staticmethod
    def prop_date(start: str, end: str = None) -> dict:
        d: dict[str, Any] = {"start": start}
        if end:
            d["end"] = end
        return {"date": d}

    # ── 헬퍼: 콘텐츠 블록 빌더 ────────────────────────

    @staticmethod
    def block_heading(text: str, level: int = 2) -> dict:
        key = f"heading_{level}"
        return {"type": key, key: {"rich_text": [{"text": {"content": text}}]}}

    @staticmethod
    def block_paragraph(text: str) -> dict:
        return {
            "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": text[:2000]}}]},
        }

    @staticmethod
    def block_bulleted(text: str) -> dict:
        return {
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"text": {"content": text}}]},
        }

    @staticmethod
    def block_divider() -> dict:
        return {"type": "divider", "divider": {}}

    # ── 액션아이템 편의 메서드 ─────────────────────────

    async def get_action_items(self, database_id: str, status: str = "Not started") -> list[dict]:
        """노션 액션아이템 데이터베이스에서 미완료 항목 조회"""
        filter_dict = {
            "property": "Status",
            "status": {"equals": status},
        }
        return await self.query_database(database_id, filter_dict=filter_dict)

    async def mark_action_done(self, page_id: str):
        """액션아이템을 완료로 표시"""
        await self.update_page(page_id, {
            "Status": {"status": {"name": "Done"}},
        })

    # ── 데이터베이스 생성 ────────────────────────────────

    async def create_database(self, parent_page_id: str, title: str,
                              properties: dict) -> dict | None:
        """노션 데이터베이스 생성"""
        body = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        }
        try:
            resp = await self._http.post("/databases", json=body)
            resp.raise_for_status()
            result = resp.json()
            logger.info(f"Notion database created: {result.get('id')}")
            return result
        except Exception as e:
            logger.error(f"Notion create database failed: {e}")
            return None

    # ── 타임라인/간트차트용 DB 생성 ────────────────────

    async def create_timeline_database(self, parent_page_id: str) -> dict | None:
        """타임라인(간트차트) 데이터베이스 생성

        Properties: 작업명, 상태, 담당, 시작일, 마감일, 우선순위, 카테고리, 진행률
        """
        properties = {
            "작업명": {"title": {}},
            "상태": {
                "select": {
                    "options": [
                        {"name": "대기", "color": "gray"},
                        {"name": "진행중", "color": "blue"},
                        {"name": "완료", "color": "green"},
                        {"name": "블로커", "color": "red"},
                    ]
                }
            },
            "담당": {
                "select": {
                    "options": [
                        {"name": "마스터에이전트", "color": "purple"},
                        {"name": "Collector", "color": "blue"},
                        {"name": "Curator", "color": "green"},
                        {"name": "파트너", "color": "orange"},
                    ]
                }
            },
            "기간": {"date": {}},
            "우선순위": {
                "select": {
                    "options": [
                        {"name": "P1-긴급", "color": "red"},
                        {"name": "P2-높음", "color": "orange"},
                        {"name": "P3-보통", "color": "yellow"},
                        {"name": "P4-낮음", "color": "gray"},
                    ]
                }
            },
            "카테고리": {
                "select": {
                    "options": [
                        {"name": "베타런칭", "color": "red"},
                        {"name": "영향력", "color": "blue"},
                        {"name": "수익화", "color": "green"},
                        {"name": "인프라", "color": "gray"},
                    ]
                }
            },
            "진행률": {"number": {"format": "percent"}},
            "메모": {"rich_text": {}},
        }

        return await self.create_database(parent_page_id, "에이전트 타임라인", properties)

    async def add_timeline_item(self, db_id: str, name: str, status: str,
                                 assignee: str, start: str, end: str,
                                 priority: str, category: str,
                                 progress: float = 0, memo: str = "") -> dict | None:
        """타임라인 DB에 항목 추가"""
        properties = {
            "작업명": self.prop_title(name),
            "상태": self.prop_select(status),
            "담당": self.prop_select(assignee),
            "기간": self.prop_date(start, end),
            "우선순위": self.prop_select(priority),
            "카테고리": self.prop_select(category),
            "진행률": self.prop_number(progress),
        }
        if memo:
            properties["메모"] = self.prop_rich_text(memo)

        return await self.create_page(db_id, properties)

    async def close(self):
        await self._http.aclose()
