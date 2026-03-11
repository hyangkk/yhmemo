"""
BabyMind OS 데이터 모델
- 분석 결과, 이벤트, 리포트 등의 구조화된 데이터 모델
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class AlertLevel(str, Enum):
    """알림 수준"""
    INFO = "info"           # 일반 정보 (놀이 기록 등)
    IMPORTANT = "important" # 중요 (발달 마일스톤 등)
    WARNING = "warning"     # 주의 (위험 구역 접근)
    DANGER = "danger"       # 위험 (낙상, 가구 매달리기 등)


class DetectedObject(BaseModel):
    """감지된 물체"""
    name: str                   # 물체 이름 (예: "레고", "미끄럼틀")
    category: str               # 카테고리 (예: "장난감", "가구", "사람")
    confidence: float = 0.0     # 신뢰도 (0~1)
    location: str = ""          # 화면 내 위치 (예: "중앙", "좌측 상단")


class ChildAction(BaseModel):
    """아이의 행동"""
    action: str                 # 행동 (예: "레고 쌓기", "걷기", "앉아서 놀기")
    body_part: str = ""         # 관련 신체 부위 (예: "손", "전신")
    motor_type: str = ""        # 운동 유형: "fine_motor"(소근육) | "gross_motor"(대근육)
    intensity: str = "normal"   # 활동 강도: "low" | "normal" | "high"


class SafetyEvent(BaseModel):
    """안전 관련 이벤트"""
    event_type: str             # 이벤트 유형 (예: "위험구역_접근", "낙상_감지", "울음_감지")
    severity: AlertLevel = AlertLevel.WARNING
    description: str = ""
    location: str = ""          # 위치


class FrameAnalysis(BaseModel):
    """단일 프레임 분석 결과"""
    timestamp: datetime = Field(default_factory=datetime.now)
    camera_id: str = "main"

    # 장면 요약
    scene_summary: str = ""     # 자연어 장면 설명

    # 아이 상태
    child_detected: bool = False
    child_position: str = ""    # 화면 내 위치
    child_posture: str = ""     # 자세 (서있음, 앉아있음, 누워있음 등)
    child_emotion: str = ""     # 감정 상태 (즐거움, 집중, 불안 등)

    # 감지된 물체들
    objects: list[DetectedObject] = Field(default_factory=list)

    # 아이의 행동
    actions: list[ChildAction] = Field(default_factory=list)

    # 장난감 상호작용
    toy_interactions: dict[str, float] = Field(default_factory=dict)
    # {"레고": 0.8, "기차": 0.1} - 상호작용 강도 (0~1)

    # 안전 이벤트
    safety_events: list[SafetyEvent] = Field(default_factory=list)

    # 특별 이벤트 (자동 클리핑 대상)
    special_events: list[str] = Field(default_factory=list)
    # 예: ["첫걸음", "웃는 얼굴", "새로운 장난감 사용"]


class ToyAffinityReport(BaseModel):
    """장난감 선호도 리포트"""
    period: str = "7d"          # 분석 기간
    generated_at: datetime = Field(default_factory=datetime.now)
    rankings: list[dict] = Field(default_factory=list)
    # [{"name": "레고", "total_minutes": 120, "sessions": 15, "trend": "rising"}]
    trends: dict[str, str] = Field(default_factory=dict)
    # {"레고": "rising", "기차": "declining", "미끄럼틀": "stable"}
    recommendation: str = ""    # AI 추천 메시지


class DevelopmentReport(BaseModel):
    """발달 단계 리포트"""
    period: str = "7d"
    generated_at: datetime = Field(default_factory=datetime.now)
    child_age_months: int = 0

    # 운동 발달
    fine_motor_score: float = 0.0   # 소근육 점수 (0~100)
    gross_motor_score: float = 0.0  # 대근육 점수 (0~100)
    fine_motor_activities: list[str] = Field(default_factory=list)
    gross_motor_activities: list[str] = Field(default_factory=list)

    # 집중력
    avg_focus_minutes: float = 0.0  # 평균 집중 시간 (분)
    max_focus_minutes: float = 0.0  # 최장 집중 시간

    # 활동량
    activity_level: str = "normal"  # "low" | "normal" | "high"
    active_hours: list[int] = Field(default_factory=list)  # 활동적인 시간대

    # AI 코멘트
    summary: str = ""
    milestones: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class DailyDigest(BaseModel):
    """일일 요약 리포트 (부모에게 발송)"""
    date: str = ""              # YYYY-MM-DD
    child_name: str = ""

    # 오늘의 하이라이트
    highlights: list[str] = Field(default_factory=list)
    # ["오늘 레고로 30분 집중 놀이!", "미끄럼틀 5번 탔어요"]

    # 장난감 사용 요약
    toy_summary: dict[str, int] = Field(default_factory=dict)
    # {"레고": 45, "기차": 20, "미끄럼틀": 15}  (분)

    # 활동 요약
    total_active_minutes: int = 0
    main_activities: list[str] = Field(default_factory=list)

    # 안전 이슈
    safety_alerts: list[str] = Field(default_factory=list)

    # 특별한 순간들 (자동 클리핑)
    special_moments: list[dict] = Field(default_factory=list)
    # [{"event": "첫걸음", "time": "14:30", "frame_url": "..."}]

    # AI 코멘트
    ai_comment: str = ""
