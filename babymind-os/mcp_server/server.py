"""
BabyMind OS MCP 서버
- Model Context Protocol을 통해 육아 데이터를 외부 AI 에이전트에 노출
- 리소스: 활동 로그, 장난감 선호도, 발달 리포트
- 도구: 추천 생성, 알림 트리거, 리포트 요청
"""

import json
import logging
from datetime import datetime
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
)

from analyzers.activity_tracker import ActivityTracker
from analyzers.vision_analyzer import VisionAnalyzer
from config import settings

logger = logging.getLogger("babymind.mcp")

# MCP 서버 인스턴스
app = Server("babymind-os")

# 전역 트래커 (메인에서 주입)
_tracker: ActivityTracker | None = None
_analyzer: VisionAnalyzer | None = None


def set_tracker(tracker: ActivityTracker):
    global _tracker
    _tracker = tracker


def set_analyzer(analyzer: VisionAnalyzer):
    global _analyzer
    _analyzer = analyzer


# ===== MCP 리소스 =====

@app.list_resources()
async def list_resources() -> list[Resource]:
    """사용 가능한 리소스 목록"""
    return [
        Resource(
            uri="babymind://activity-log",
            name="오늘의 활동 로그",
            description="오늘 아이의 활동을 시간순으로 정리한 로그",
            mimeType="application/json",
        ),
        Resource(
            uri="babymind://toy-affinity",
            name="장난감 선호도",
            description="최근 7일간 장난감별 사용 시간 및 선호도 분석",
            mimeType="application/json",
        ),
        Resource(
            uri="babymind://development-report",
            name="발달 단계 리포트",
            description="소근육/대근육 발달, 집중력, 활동량 분석",
            mimeType="application/json",
        ),
        Resource(
            uri="babymind://daily-digest",
            name="일일 요약",
            description="오늘 하루의 종합 요약 리포트",
            mimeType="application/json",
        ),
        Resource(
            uri="babymind://safety-log",
            name="안전 이벤트 로그",
            description="위험 구역 접근, 안전 관련 이벤트 기록",
            mimeType="application/json",
        ),
        Resource(
            uri="babymind://child-profile",
            name="아이 프로필",
            description="아이의 기본 정보 및 현재 상태",
            mimeType="application/json",
        ),
    ]


@app.read_resource()
async def read_resource(uri: str) -> str:
    """리소스 데이터 반환"""
    if not _tracker:
        return json.dumps({"error": "트래커가 초기화되지 않음"}, ensure_ascii=False)

    if uri == "babymind://activity-log":
        digest = _tracker.get_daily_digest()
        return json.dumps({
            "date": digest.date,
            "highlights": digest.highlights,
            "main_activities": digest.main_activities,
            "total_active_minutes": digest.total_active_minutes,
        }, ensure_ascii=False, indent=2)

    elif uri == "babymind://toy-affinity":
        report = _tracker.get_toy_affinity()
        return json.dumps({
            "period": report.period,
            "rankings": report.rankings,
            "trends": report.trends,
            "recommendation": report.recommendation,
        }, ensure_ascii=False, indent=2)

    elif uri == "babymind://development-report":
        report = _tracker.get_development_report()
        return json.dumps({
            "period": report.period,
            "age_months": report.child_age_months,
            "fine_motor": {
                "score": report.fine_motor_score,
                "activities": report.fine_motor_activities,
            },
            "gross_motor": {
                "score": report.gross_motor_score,
                "activities": report.gross_motor_activities,
            },
            "focus": {
                "avg_minutes": report.avg_focus_minutes,
                "max_minutes": report.max_focus_minutes,
            },
            "activity_level": report.activity_level,
            "active_hours": report.active_hours,
        }, ensure_ascii=False, indent=2)

    elif uri == "babymind://daily-digest":
        digest = _tracker.get_daily_digest()
        return digest.model_dump_json(indent=2)

    elif uri == "babymind://safety-log":
        return json.dumps({
            "events": _tracker._safety_log,
        }, ensure_ascii=False, indent=2)

    elif uri == "babymind://child-profile":
        return json.dumps({
            "name": settings.CHILD_NAME,
            "age_months": settings.CHILD_AGE_MONTHS,
            "monitoring_active": True,
        }, ensure_ascii=False, indent=2)

    return json.dumps({"error": f"알 수 없는 리소스: {uri}"}, ensure_ascii=False)


# ===== MCP 도구 =====

@app.list_tools()
async def list_tools() -> list[Tool]:
    """사용 가능한 도구 목록"""
    return [
        Tool(
            name="get_toy_recommendation",
            description="아이의 나이와 현재 관심도를 바탕으로 장난감/교구 추천 리스트 생성",
            inputSchema={
                "type": "object",
                "properties": {
                    "age_months": {
                        "type": "integer",
                        "description": "아이의 나이 (개월)",
                    },
                    "budget_krw": {
                        "type": "integer",
                        "description": "예산 (원)",
                        "default": 50000,
                    },
                },
                "required": ["age_months"],
            },
        ),
        Tool(
            name="get_daily_report",
            description="오늘의 일일 리포트를 자연어로 생성",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="trigger_alert",
            description="부모에게 즉시 알림 발송 (이메일/카카오톡)",
            inputSchema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "알림 메시지 내용",
                    },
                    "level": {
                        "type": "string",
                        "enum": ["info", "important", "warning", "danger"],
                        "description": "알림 수준",
                        "default": "info",
                    },
                },
                "required": ["message"],
            },
        ),
        Tool(
            name="ask_about_child",
            description="아이에 대한 자연어 질문에 CCTV 분석 데이터를 바탕으로 답변",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "아이에 대한 질문 (예: '오늘 뭐하고 놀았어?')",
                    },
                },
                "required": ["question"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """도구 실행"""

    if name == "get_toy_recommendation":
        return await _handle_toy_recommendation(arguments)

    elif name == "get_daily_report":
        return await _handle_daily_report()

    elif name == "trigger_alert":
        return await _handle_trigger_alert(arguments)

    elif name == "ask_about_child":
        return await _handle_ask_about_child(arguments)

    return [TextContent(type="text", text=f"알 수 없는 도구: {name}")]


async def _handle_toy_recommendation(args: dict) -> list[TextContent]:
    """장난감 추천"""
    age = args.get("age_months", settings.CHILD_AGE_MONTHS)
    budget = args.get("budget_krw", 50000)

    if not _tracker or not _analyzer:
        return [TextContent(type="text", text="시스템이 초기화되지 않았습니다.")]

    affinity = _tracker.get_toy_affinity()
    current_interests = json.dumps(affinity.rankings[:5], ensure_ascii=False)

    prompt = f"""아이 나이: {age}개월
현재 관심 장난감: {current_interests}
예산: {budget:,}원

현재 관심도와 발달 단계를 고려하여 새로운 장난감/교구 3~5개를 추천해주세요.
각 추천 항목에 대해:
1. 장난감/교구 이름
2. 예상 가격대
3. 발달 기여 영역 (소근육, 대근육, 인지, 언어 등)
4. 추천 이유

한국어로 답변해주세요."""

    try:
        response = _analyzer.client.messages.create(
            model=_analyzer.model,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        return [TextContent(type="text", text=response.content[0].text)]
    except Exception as e:
        return [TextContent(type="text", text=f"추천 생성 실패: {e}")]


async def _handle_daily_report() -> list[TextContent]:
    """일일 리포트"""
    if not _tracker or not _analyzer:
        return [TextContent(type="text", text="시스템이 초기화되지 않았습니다.")]

    report = await _analyzer.generate_daily_summary(_tracker._today_analyses)
    return [TextContent(type="text", text=report)]


async def _handle_trigger_alert(args: dict) -> list[TextContent]:
    """알림 발송"""
    from notifications.notifier import NotificationManager

    message = args.get("message", "")
    level = args.get("level", "info")

    notifier = NotificationManager()
    success = await notifier.send_alert(
        title=f"[BabyMind] {level.upper()} 알림",
        message=message,
        level=level,
    )

    if success:
        return [TextContent(type="text", text=f"알림 발송 완료: {message}")]
    return [TextContent(type="text", text="알림 발송 실패")]


async def _handle_ask_about_child(args: dict) -> list[TextContent]:
    """아이에 대한 질문 답변"""
    question = args.get("question", "")

    if not _tracker or not _analyzer:
        return [TextContent(type="text", text="시스템이 초기화되지 않았습니다.")]

    digest = _tracker.get_daily_digest()
    context = digest.model_dump_json()

    prompt = f"""당신은 육아 AI 비서입니다. CCTV 분석 데이터를 바탕으로 부모의 질문에 답변합니다.

아이 이름: {settings.CHILD_NAME}
나이: {settings.CHILD_AGE_MONTHS}개월

오늘의 데이터:
{context}

부모의 질문: {question}

따뜻하고 자세하게 한국어로 답변해주세요."""

    try:
        response = _analyzer.client.messages.create(
            model=_analyzer.model,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return [TextContent(type="text", text=response.content[0].text)]
    except Exception as e:
        return [TextContent(type="text", text=f"답변 생성 실패: {e}")]


async def run_mcp_server():
    """MCP 서버 실행 (stdio 모드)"""
    logger.info("BabyMind OS MCP 서버 시작")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
