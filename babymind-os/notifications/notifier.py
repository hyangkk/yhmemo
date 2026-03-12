"""
알림 시스템
- 이메일 (Resend API)
- 카카오톡 (카카오 REST API)
- 알림 수준별 필터링
"""

import json
import logging
from datetime import datetime
from typing import Optional

import httpx

from config import settings
from core.models import AlertLevel

logger = logging.getLogger("babymind.notify")


class EmailNotifier:
    """Resend API를 사용한 이메일 알림"""

    def __init__(self):
        self.api_key = settings.RESEND_API_KEY
        self.from_email = settings.ALERT_FROM_EMAIL
        self.to_email = settings.PARENT_EMAIL

    async def send(
        self,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
    ) -> bool:
        """이메일 발송"""
        if not self.api_key or not self.to_email:
            logger.warning("이메일 설정 누락 (RESEND_API_KEY 또는 PARENT_EMAIL)")
            return False

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": self.from_email,
                        "to": [self.to_email],
                        "subject": subject,
                        "html": html_body,
                        "text": text_body or "",
                    },
                    timeout=10.0,
                )

                if response.status_code == 200:
                    logger.info(f"이메일 발송 성공: {subject}")
                    return True
                else:
                    logger.error(f"이메일 발송 실패: {response.status_code} - {response.text}")
                    return False

        except Exception as e:
            logger.error(f"이메일 발송 오류: {e}")
            return False


class KakaoNotifier:
    """카카오톡 나에게 보내기 API"""

    def __init__(self):
        self.rest_api_key = settings.KAKAO_REST_API_KEY
        self.access_token = settings.KAKAO_ACCESS_TOKEN

    async def send(self, text: str) -> bool:
        """카카오톡 나에게 보내기"""
        if not self.access_token:
            logger.warning("카카오톡 설정 누락 (KAKAO_ACCESS_TOKEN)")
            return False

        try:
            template = {
                "object_type": "text",
                "text": text[:2000],  # 카카오톡 메시지 길이 제한
                "link": {
                    "web_url": "https://babymind.app",
                    "mobile_web_url": "https://babymind.app",
                },
                "button_title": "상세 보기",
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://kapi.kakao.com/v2/api/talk/memo/default/send",
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "template_object": json.dumps(template, ensure_ascii=False),
                    },
                    timeout=10.0,
                )

                if response.status_code == 200:
                    logger.info("카카오톡 발송 성공")
                    return True
                else:
                    logger.error(f"카카오톡 발송 실패: {response.status_code} - {response.text}")
                    return False

        except Exception as e:
            logger.error(f"카카오톡 발송 오류: {e}")
            return False


class NotificationManager:
    """알림 통합 관리자 - 수준별 필터링 및 채널 선택"""

    def __init__(self):
        self.email = EmailNotifier()
        self.kakao = KakaoNotifier()
        self.notification_level = settings.NOTIFICATION_LEVEL

    def _should_notify(self, level: str) -> bool:
        """알림 수준 필터링"""
        levels_order = ["info", "important", "warning", "danger"]
        try:
            level_idx = levels_order.index(level)
        except ValueError:
            level_idx = 0

        if self.notification_level == "all":
            return True
        elif self.notification_level == "important":
            return level_idx >= 1
        elif self.notification_level == "danger_only":
            return level_idx >= 3
        return True

    async def send_alert(
        self,
        title: str,
        message: str,
        level: str = "info",
    ) -> bool:
        """알림 발송 (수준에 따라 채널 선택)"""
        if not self._should_notify(level):
            logger.debug(f"알림 수준 필터링됨: {level} (설정: {self.notification_level})")
            return True

        success = False
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 이메일 발송
        html_body = self._build_email_html(title, message, level, now)
        email_ok = await self.email.send(
            subject=title,
            html_body=html_body,
            text_body=message,
        )
        if email_ok:
            success = True

        # 위험 수준은 카카오톡도 발송 (즉시 확인 필요)
        if level in ("warning", "danger"):
            emoji = "⚠️" if level == "warning" else "🚨"
            kakao_text = f"{emoji} {title}\n\n{message}\n\n{now}"
            kakao_ok = await self.kakao.send(kakao_text)
            if kakao_ok:
                success = True

        return success

    async def send_daily_digest(self, report_text: str) -> bool:
        """일일 리포트 발송"""
        now = datetime.now().strftime("%Y-%m-%d")
        title = f"[BabyMind] {settings.CHILD_NAME}의 하루 ({now})"

        html_body = self._build_email_html(title, report_text, "info", now)
        email_ok = await self.email.send(
            subject=title,
            html_body=html_body,
            text_body=report_text,
        )

        # 카카오톡으로 요약 발송
        summary = report_text[:500] + ("..." if len(report_text) > 500 else "")
        kakao_ok = await self.kakao.send(f"📋 {title}\n\n{summary}")

        return email_ok or kakao_ok

    async def send_safety_alert(self, event_description: str, severity: AlertLevel) -> bool:
        """안전 알림 즉시 발송"""
        title = f"[BabyMind] 안전 알림 - {severity.value.upper()}"
        return await self.send_alert(title, event_description, severity.value)

    @staticmethod
    def _build_email_html(title: str, message: str, level: str, timestamp: str) -> str:
        """이메일 HTML 템플릿 생성"""
        color_map = {
            "info": "#3B82F6",
            "important": "#8B5CF6",
            "warning": "#F59E0B",
            "danger": "#EF4444",
        }
        color = color_map.get(level, "#3B82F6")

        # 줄바꿈을 <br>로 변환
        html_message = message.replace("\n", "<br>")

        return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
  <div style="background: {color}; color: white; padding: 16px 24px; border-radius: 12px 12px 0 0;">
    <h2 style="margin: 0; font-size: 18px;">{title}</h2>
    <p style="margin: 4px 0 0; opacity: 0.8; font-size: 13px;">{timestamp}</p>
  </div>
  <div style="background: #F9FAFB; padding: 24px; border: 1px solid #E5E7EB; border-top: none; border-radius: 0 0 12px 12px;">
    <div style="font-size: 15px; line-height: 1.7; color: #374151;">
      {html_message}
    </div>
  </div>
  <p style="text-align: center; color: #9CA3AF; font-size: 12px; margin-top: 16px;">
    BabyMind OS - 육아 AI 인텔리전스
  </p>
</body>
</html>"""
