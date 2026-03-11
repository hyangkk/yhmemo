"""
Supabase 기반 데이터 저장소
- 분석 결과 영속적 저장
- 히스토리 데이터 조회
- 일일/주간 통계 집계
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from supabase import create_client, Client

from config import settings
from core.models import FrameAnalysis, DailyDigest

logger = logging.getLogger("babymind.storage")


class BabyMindStorage:
    """Supabase 기반 분석 데이터 저장소"""

    def __init__(self):
        self._client: Optional[Client] = None

    def _get_client(self) -> Optional[Client]:
        """Supabase 클라이언트 (지연 초기화)"""
        if self._client is None:
            if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
                logger.warning("Supabase 설정 누락 - 로컬 파일 저장만 사용")
                return None
            self._client = create_client(
                settings.SUPABASE_URL,
                settings.SUPABASE_SERVICE_ROLE_KEY,
            )
        return self._client

    async def save_analysis(self, analysis: FrameAnalysis) -> bool:
        """프레임 분석 결과 저장"""
        client = self._get_client()
        if not client:
            return False

        try:
            data = {
                "timestamp": analysis.timestamp.isoformat(),
                "camera_id": analysis.camera_id,
                "scene_summary": analysis.scene_summary,
                "child_detected": analysis.child_detected,
                "child_position": analysis.child_position,
                "child_posture": analysis.child_posture,
                "child_emotion": analysis.child_emotion,
                "objects": [obj.model_dump() for obj in analysis.objects],
                "actions": [act.model_dump() for act in analysis.actions],
                "toy_interactions": analysis.toy_interactions,
                "safety_events": [evt.model_dump() for evt in analysis.safety_events],
                "special_events": analysis.special_events,
            }

            client.table("babymind_analyses").insert(data).execute()
            return True

        except Exception as e:
            logger.error(f"분석 결과 저장 실패: {e}")
            return False

    async def save_daily_digest(self, digest: DailyDigest) -> bool:
        """일일 요약 저장"""
        client = self._get_client()
        if not client:
            return False

        try:
            data = digest.model_dump()
            client.table("babymind_daily_digests").insert(data).execute()
            return True

        except Exception as e:
            logger.error(f"일일 요약 저장 실패: {e}")
            return False

    async def get_toy_history(self, days: int = 7) -> list[dict]:
        """최근 N일간 장난감 사용 히스토리"""
        client = self._get_client()
        if not client:
            return []

        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            result = (
                client.table("babymind_analyses")
                .select("timestamp, toy_interactions")
                .gte("timestamp", since)
                .not_.is_("toy_interactions", "null")
                .order("timestamp")
                .execute()
            )
            return result.data

        except Exception as e:
            logger.error(f"장난감 히스토리 조회 실패: {e}")
            return []

    async def get_safety_events(self, days: int = 7) -> list[dict]:
        """최근 안전 이벤트 조회"""
        client = self._get_client()
        if not client:
            return []

        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            result = (
                client.table("babymind_analyses")
                .select("timestamp, safety_events")
                .gte("timestamp", since)
                .neq("safety_events", "[]")
                .order("timestamp", desc=True)
                .execute()
            )
            return result.data

        except Exception as e:
            logger.error(f"안전 이벤트 조회 실패: {e}")
            return []

    async def cleanup_old_data(self):
        """보관 기간 초과 데이터 삭제"""
        client = self._get_client()
        if not client:
            return

        try:
            cutoff = (
                datetime.now() - timedelta(days=settings.ANALYSIS_RETENTION_DAYS)
            ).isoformat()
            client.table("babymind_analyses").delete().lt("timestamp", cutoff).execute()
            logger.info(f"{settings.ANALYSIS_RETENTION_DAYS}일 이전 데이터 정리 완료")

        except Exception as e:
            logger.error(f"데이터 정리 실패: {e}")
