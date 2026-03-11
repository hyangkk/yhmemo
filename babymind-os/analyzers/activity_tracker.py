"""
활동 추적기
- 시간대별 장난감 사용 통계
- 발달 지표 계산
- 일일/주간 트렌드 분석
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from core.models import (
    DailyDigest,
    DevelopmentReport,
    FrameAnalysis,
    ToyAffinityReport,
)
from config import settings

logger = logging.getLogger("babymind.tracker")

DATA_DIR = Path(settings.BASE_DIR) / "data"


class ActivityTracker:
    """프레임 분석 결과를 누적하여 통계 및 리포트 생성"""

    def __init__(self):
        self._today_analyses: list[FrameAnalysis] = []
        self._toy_time: dict[str, list[datetime]] = defaultdict(list)
        self._action_log: list[dict] = []
        self._safety_log: list[dict] = []
        self._special_events: list[dict] = []
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def record(self, analysis: FrameAnalysis):
        """분석 결과 기록"""
        self._today_analyses.append(analysis)

        # 장난감 상호작용 기록
        for toy, score in analysis.toy_interactions.items():
            if score > 0.3:
                self._toy_time[toy].append(analysis.timestamp)

        # 행동 기록
        for action in analysis.actions:
            self._action_log.append({
                "time": analysis.timestamp.isoformat(),
                "action": action.action,
                "motor_type": action.motor_type,
                "intensity": action.intensity,
            })

        # 안전 이벤트 기록
        for event in analysis.safety_events:
            self._safety_log.append({
                "time": analysis.timestamp.isoformat(),
                "type": event.event_type,
                "severity": event.severity,
                "description": event.description,
            })

        # 특별 이벤트 기록
        for event in analysis.special_events:
            self._special_events.append({
                "time": analysis.timestamp.isoformat(),
                "event": event,
            })

    def get_toy_affinity(self, days: int = 7) -> ToyAffinityReport:
        """장난감 선호도 리포트 생성"""
        toy_stats: dict[str, dict] = {}

        for toy, timestamps in self._toy_time.items():
            # 분석 간격(기본 30초)을 고려한 총 사용 시간 추정
            interval = settings.ANALYSIS_INTERVAL_SECONDS
            total_minutes = len(timestamps) * interval / 60.0
            sessions = self._count_sessions(timestamps, gap_minutes=5)

            toy_stats[toy] = {
                "name": toy,
                "total_minutes": round(total_minutes, 1),
                "sessions": sessions,
                "trend": "stable",  # TODO: 이전 주와 비교
            }

        # 사용 시간 기준 정렬
        rankings = sorted(
            toy_stats.values(),
            key=lambda x: x["total_minutes"],
            reverse=True,
        )

        trends = {toy: stats["trend"] for toy, stats in toy_stats.items()}

        return ToyAffinityReport(
            period=f"{days}d",
            rankings=rankings,
            trends=trends,
            recommendation=self._generate_toy_recommendation(rankings),
        )

    def get_development_report(self, days: int = 7) -> DevelopmentReport:
        """발달 단계 리포트 생성"""
        fine_motor_actions = []
        gross_motor_actions = []
        focus_durations: list[float] = []

        for entry in self._action_log:
            if entry["motor_type"] == "fine_motor":
                fine_motor_actions.append(entry["action"])
            elif entry["motor_type"] == "gross_motor":
                gross_motor_actions.append(entry["action"])

        # 집중 시간 계산 (연속 동일 장난감 사용 시간)
        for toy, timestamps in self._toy_time.items():
            sessions = self._split_sessions(timestamps, gap_minutes=3)
            for session in sessions:
                duration = len(session) * settings.ANALYSIS_INTERVAL_SECONDS / 60.0
                focus_durations.append(duration)

        # 점수 계산 (0~100, 활동 다양성 및 빈도 기반)
        fine_score = min(len(set(fine_motor_actions)) * 15, 100)
        gross_score = min(len(set(gross_motor_actions)) * 15, 100)

        avg_focus = sum(focus_durations) / len(focus_durations) if focus_durations else 0
        max_focus = max(focus_durations) if focus_durations else 0

        # 활동적인 시간대
        active_hours = self._get_active_hours()

        return DevelopmentReport(
            period=f"{days}d",
            child_age_months=settings.CHILD_AGE_MONTHS,
            fine_motor_score=fine_score,
            gross_motor_score=gross_score,
            fine_motor_activities=list(set(fine_motor_actions))[:10],
            gross_motor_activities=list(set(gross_motor_actions))[:10],
            avg_focus_minutes=round(avg_focus, 1),
            max_focus_minutes=round(max_focus, 1),
            activity_level=self._assess_activity_level(),
            active_hours=active_hours,
        )

    def get_daily_digest(self) -> DailyDigest:
        """오늘의 일일 요약 생성"""
        today = datetime.now().strftime("%Y-%m-%d")

        # 장난감 사용 요약 (분 단위)
        toy_summary = {}
        interval = settings.ANALYSIS_INTERVAL_SECONDS
        for toy, timestamps in self._toy_time.items():
            today_ts = [t for t in timestamps if t.strftime("%Y-%m-%d") == today]
            minutes = len(today_ts) * interval / 60.0
            if minutes > 0:
                toy_summary[toy] = round(minutes)

        # 하이라이트 생성
        highlights = []
        if toy_summary:
            top_toy = max(toy_summary, key=toy_summary.get)
            highlights.append(f"{top_toy}(으)로 {toy_summary[top_toy]}분 놀았어요!")
        if self._special_events:
            for evt in self._special_events[-3:]:
                highlights.append(evt["event"])

        # 안전 알림
        safety_alerts = [
            f"{e['description']}" for e in self._safety_log
            if e.get("severity") in ("warning", "danger")
        ]

        return DailyDigest(
            date=today,
            child_name=settings.CHILD_NAME,
            highlights=highlights,
            toy_summary=toy_summary,
            total_active_minutes=self._calc_active_minutes(),
            main_activities=self._get_main_activities(),
            safety_alerts=safety_alerts,
            special_moments=[
                {"event": e["event"], "time": e["time"]}
                for e in self._special_events
            ],
        )

    def save_daily_data(self):
        """오늘의 데이터를 파일로 저장"""
        today = datetime.now().strftime("%Y-%m-%d")
        filepath = DATA_DIR / f"daily_{today}.json"

        data = {
            "date": today,
            "total_frames": len(self._today_analyses),
            "toy_time": {
                toy: [t.isoformat() for t in ts]
                for toy, ts in self._toy_time.items()
            },
            "actions": self._action_log,
            "safety_events": self._safety_log,
            "special_events": self._special_events,
        }

        filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        logger.info(f"일일 데이터 저장: {filepath}")

    def reset_daily(self):
        """일일 데이터 초기화 (새로운 날 시작)"""
        self.save_daily_data()
        self._today_analyses.clear()
        self._toy_time.clear()
        self._action_log.clear()
        self._safety_log.clear()
        self._special_events.clear()

    # ===== 내부 유틸리티 =====

    @staticmethod
    def _count_sessions(timestamps: list[datetime], gap_minutes: int = 5) -> int:
        """연속 타임스탬프를 세션으로 분리하여 세션 수 반환"""
        if not timestamps:
            return 0
        sessions = 1
        sorted_ts = sorted(timestamps)
        for i in range(1, len(sorted_ts)):
            if (sorted_ts[i] - sorted_ts[i - 1]).total_seconds() > gap_minutes * 60:
                sessions += 1
        return sessions

    @staticmethod
    def _split_sessions(
        timestamps: list[datetime], gap_minutes: int = 3
    ) -> list[list[datetime]]:
        """타임스탬프를 세션별로 분리"""
        if not timestamps:
            return []
        sorted_ts = sorted(timestamps)
        sessions: list[list[datetime]] = [[sorted_ts[0]]]
        for i in range(1, len(sorted_ts)):
            if (sorted_ts[i] - sorted_ts[i - 1]).total_seconds() > gap_minutes * 60:
                sessions.append([])
            sessions[-1].append(sorted_ts[i])
        return sessions

    def _get_active_hours(self) -> list[int]:
        """활동이 많은 시간대 반환"""
        hour_counts: dict[int, int] = defaultdict(int)
        for a in self._today_analyses:
            if a.child_detected and a.actions:
                hour_counts[a.timestamp.hour] += 1
        # 상위 시간대 반환
        sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
        return [h for h, _ in sorted_hours[:5]]

    def _assess_activity_level(self) -> str:
        """활동 수준 평가"""
        high_intensity = sum(
            1 for e in self._action_log if e.get("intensity") == "high"
        )
        total = len(self._action_log) or 1
        ratio = high_intensity / total
        if ratio > 0.4:
            return "high"
        elif ratio > 0.15:
            return "normal"
        return "low"

    def _calc_active_minutes(self) -> int:
        """오늘 총 활동 시간 (분)"""
        active_frames = sum(
            1 for a in self._today_analyses
            if a.child_detected and a.actions
        )
        return round(active_frames * settings.ANALYSIS_INTERVAL_SECONDS / 60)

    def _get_main_activities(self) -> list[str]:
        """주요 활동 목록"""
        activities = [e["action"] for e in self._action_log]
        # 빈도순 정렬
        from collections import Counter
        counts = Counter(activities)
        return [act for act, _ in counts.most_common(5)]

    @staticmethod
    def _generate_toy_recommendation(rankings: list[dict]) -> str:
        """장난감 추천 텍스트 생성"""
        if not rankings:
            return "아직 충분한 데이터가 없어요."
        top = rankings[0]
        return f"{top['name']}에 가장 큰 관심을 보이고 있어요! ({top['total_minutes']}분)"
