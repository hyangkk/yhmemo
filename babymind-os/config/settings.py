"""
BabyMind OS 설정 모듈
- 환경변수 로드 및 전역 설정 관리
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ===== Tapo CCTV 설정 =====
TAPO_USERNAME = os.getenv("TAPO_USERNAME", "")
TAPO_PASSWORD = os.getenv("TAPO_PASSWORD", "")
# RTSP URL 형식: rtsp://{username}:{password}@{ip}:{port}/stream1
# Tapo 기본 RTSP 포트: 554, 스트림1(HD), 스트림2(SD)
TAPO_CAMERA_IP = os.getenv("TAPO_CAMERA_IP", "")
TAPO_RTSP_PORT = int(os.getenv("TAPO_RTSP_PORT", "554"))

# ===== AI 분석 설정 =====
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# 분석 주기 (초) - 기본 30초마다 프레임 캡처 및 분석
ANALYSIS_INTERVAL_SECONDS = int(os.getenv("ANALYSIS_INTERVAL", "30"))
# 프레임 캡처 해상도 (너비)
CAPTURE_WIDTH = int(os.getenv("CAPTURE_WIDTH", "1280"))
CAPTURE_HEIGHT = int(os.getenv("CAPTURE_HEIGHT", "720"))
# Claude 모델
VISION_MODEL = os.getenv("VISION_MODEL", "claude-haiku-4-5-20251001")

# ===== 아이 프로필 =====
CHILD_NAME = os.getenv("CHILD_NAME", "아이")
CHILD_AGE_MONTHS = int(os.getenv("CHILD_AGE_MONTHS", "24"))

# ===== 알림 설정 =====
# 이메일 (Resend)
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
PARENT_EMAIL = os.getenv("PARENT_EMAIL", "")
ALERT_FROM_EMAIL = os.getenv("ALERT_FROM_EMAIL", "babymind@resend.dev")

# 카카오톡
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
KAKAO_ACCESS_TOKEN = os.getenv("KAKAO_ACCESS_TOKEN", "")

# 알림 레벨: "all" | "important" | "danger_only"
NOTIFICATION_LEVEL = os.getenv("NOTIFICATION_LEVEL", "important")

# ===== Supabase 저장소 =====
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# ===== MCP 서버 설정 =====
MCP_SERVER_HOST = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8765"))

# ===== 위험 구역 설정 =====
# 화면 좌표 기반 위험 구역 (정규화 좌표 0~1)
# 예: [{"name": "주방", "x1": 0.0, "y1": 0.0, "x2": 0.4, "y2": 0.5}]
DANGER_ZONES = []

# ===== 데이터 보관 정책 =====
# 원본 프레임 보관 시간 (분) - 분석 후 삭제
FRAME_RETENTION_MINUTES = int(os.getenv("FRAME_RETENTION_MINUTES", "5"))
# 분석 결과(JSON) 보관 일수
ANALYSIS_RETENTION_DAYS = int(os.getenv("ANALYSIS_RETENTION_DAYS", "90"))


def get_rtsp_url() -> str:
    """Tapo 카메라 RTSP URL 생성"""
    if not all([TAPO_USERNAME, TAPO_PASSWORD, TAPO_CAMERA_IP]):
        return ""
    # 비밀번호에 특수문자(@, : 등)가 포함될 수 있으므로 URL 인코딩
    from urllib.parse import quote
    encoded_password = quote(TAPO_PASSWORD, safe="")
    return (
        f"rtsp://{TAPO_USERNAME}:{encoded_password}"
        f"@{TAPO_CAMERA_IP}:{TAPO_RTSP_PORT}/stream1"
    )


def validate_config() -> list[str]:
    """필수 설정값 검증. 누락된 항목 리스트 반환."""
    missing = []
    if not TAPO_USERNAME:
        missing.append("TAPO_USERNAME")
    if not TAPO_PASSWORD:
        missing.append("TAPO_PASSWORD")
    if not TAPO_CAMERA_IP:
        missing.append("TAPO_CAMERA_IP")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    return missing
