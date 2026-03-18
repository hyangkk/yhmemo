"""
에이전트 시스템 공용 데이터 모델 (Pydantic v2)

dict 대신 타입 안전한 모델을 사용하여:
- IDE 자동완성 지원
- 런타임 유효성 검증
- 직렬화/역직렬화 일관성
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── 의도 분석 (Intent) ─────────────────────────────────

class IntentType(str, Enum):
    """자연어 의도 분류"""
    COLLECT = "collect"
    BRIEFING = "briefing"
    DASHBOARD = "dashboard"
    QUOTE = "quote"
    DIARY_QUOTE = "diary_quote"
    DIARY_DAILY_ALERT = "diary_daily_alert"
    FORTUNE = "fortune"
    INVEST_STATUS = "invest_status"
    HR_EVAL = "hr_eval"
    HR_STATUS = "hr_status"
    HR_SALARY = "hr_salary"
    STOCK_TRADE = "stock_trade"
    BULLETIN = "bulletin"
    NAVER_BLOG = "naver_blog"
    QA = "qa"
    DEV = "dev"
    CHAT = "chat"
    CLARIFY = "clarify"


class IntentResult(BaseModel):
    """의도 분석 결과"""
    intent: IntentType
    query: str = ""
    dev_task: str = ""
    stock_code: str = ""
    stock_action: str = ""
    clarify_question: str = ""
    ack: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# ── 에이전트 작업 (Task) ───────────────────────────────

class TaskStatus(str, Enum):
    """작업 상태"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentTask(BaseModel):
    """에이전트 간 작업 메시지"""
    id: str = ""
    from_agent: str
    to_agent: str
    task_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    created_at: datetime = Field(default_factory=datetime.now)


# ── 거래 (Trade) ───────────────────────────────────────

class TradeAction(str, Enum):
    """거래 유형"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class TradeOrder(BaseModel):
    """주식 주문"""
    stock_code: str
    stock_name: str = ""
    action: TradeAction
    quantity: int = Field(ge=0)
    price: int = Field(ge=0)  # 0이면 시장가
    reason: str = ""


class TradeResult(BaseModel):
    """주문 결과"""
    success: bool
    order_no: str = ""
    message: str = ""
    executed_price: int = 0
    executed_qty: int = 0


# ── 센티멘트 (Sentiment) ──────────────────────────────

class SentimentScore(BaseModel):
    """소셜 센티멘트 분석 결과"""
    asset: str
    score: float = Field(ge=-100.0, le=100.0)
    label: str = ""  # "극도의 공포", "공포", "중립", "탐욕", "극도의 탐욕"
    source: str = ""
    analyzed_at: datetime = Field(default_factory=datetime.now)


# ── 서킷 브레이커 상태 ────────────────────────────────

class CircuitStatus(BaseModel):
    """서킷 브레이커 상태 보고"""
    name: str
    state: str  # closed, open, half_open
    failure_count: int = 0
    last_failure: float = 0.0


# ── QA 결과 ────────────────────────────────────────────

class HealthCheckResult(BaseModel):
    """헬스체크 결과"""
    endpoint: str
    status_code: int = 0
    response_time_ms: float = 0.0
    healthy: bool = False
    error: str = ""


class QAReport(BaseModel):
    """QA 보고서"""
    timestamp: datetime = Field(default_factory=datetime.now)
    checks: list[HealthCheckResult] = Field(default_factory=list)
    all_healthy: bool = False
    deploy_status: str = ""
    summary: str = ""


# ── 에이전트 메트릭 ───────────────────────────────────

class AgentMetrics(BaseModel):
    """에이전트 성능 메트릭"""
    name: str
    uptime_hours: float = 0.0
    total_actions: int = 0
    errors: int = 0
    last_heartbeat: datetime | None = None
    ai_cost_today_usd: float = 0.0
    status: str = "unknown"  # running, stopped, error
