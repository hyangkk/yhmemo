"""
이메일 모니터링 에이전트 - Gmail 수신 문의를 슬랙으로 알림

역할:
- 1시간마다 ai.agent.yh@gmail.com 계정의 새 이메일 체크
- 새 문의 이메일이 있으면 AI가 요약하여 슬랙에 알림
- 스팸/프로모션 제외, 실제 사용자 문의만 보고

자율 행동:
- Observe: IMAP으로 읽지 않은 이메일 확인
- Think: AI가 문의 내용 요약 + 긴급도 판단
- Act: 슬랙 ai-agents-general 채널에 알림
"""

import imaplib
import email
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from email.header import decode_header

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 상태 파일
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
EMAIL_STATE_FILE = os.path.join(DATA_DIR, "email_monitor_state.json")

# 무시할 발신자 패턴 (스팸/프로모션)
IGNORE_SENDERS = [
    "noreply", "no-reply", "newsletter", "marketing",
    "promotion", "notification", "mailer-daemon",
    "google.com", "accounts.google",
]


def decode_mime_header(raw: str) -> str:
    """MIME 인코딩된 헤더를 디코딩"""
    if not raw:
        return ""
    parts = decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def get_email_body(msg) -> str:
    """이메일 본문 텍스트 추출"""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
            elif content_type == "text/html" and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
    # 너무 긴 본문 자르기
    return body[:2000] if body else "(본문 없음)"


def should_ignore(sender: str) -> bool:
    """무시할 발신자인지 확인"""
    sender_lower = sender.lower()
    return any(pattern in sender_lower for pattern in IGNORE_SENDERS)


class EmailMonitorAgent(BaseAgent):
    """Gmail 수신 문의 모니터링 에이전트"""

    def __init__(self, **kwargs):
        super().__init__(
            name="email_monitor",
            description="Gmail 수신 문의를 모니터링하고 슬랙으로 알림하는 에이전트",
            slack_channel="C0AJJ469SV8",  # ai-agents-general
            loop_interval=3600,  # 1시간 간격
            **kwargs,
        )
        self.gmail_user = os.getenv("GMAIL_USER", "ai.agent.yh@gmail.com")
        self.gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
        self._load_state()

    def _load_state(self):
        """마지막 체크 시각 로드"""
        try:
            if os.path.exists(EMAIL_STATE_FILE):
                with open(EMAIL_STATE_FILE) as f:
                    self._state = json.load(f)
            else:
                self._state = {"last_check_uid": 0, "notified_uids": []}
        except Exception:
            self._state = {"last_check_uid": 0, "notified_uids": []}

    def _save_state(self):
        """상태 저장"""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            # notified_uids가 너무 커지지 않게 최근 200개만 유지
            self._state["notified_uids"] = self._state.get("notified_uids", [])[-200:]
            with open(EMAIL_STATE_FILE, "w") as f:
                json.dump(self._state, f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[email_monitor] State save error: {e}")

    async def observe(self) -> dict | None:
        """IMAP으로 새 이메일 확인"""
        if not self.gmail_app_password:
            # 앱 비밀번호가 없으면 건너뜀
            return None

        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.gmail_user, self.gmail_app_password)
            mail.select("INBOX")

            # 읽지 않은 메일 검색
            status, messages = mail.search(None, "UNSEEN")
            if status != "OK" or not messages[0]:
                mail.logout()
                return None

            mail_ids = messages[0].split()
            new_emails = []
            notified = set(self._state.get("notified_uids", []))

            for mail_id in mail_ids[-10:]:  # 최근 10개만
                uid_str = mail_id.decode()
                if uid_str in notified:
                    continue

                status, data = mail.fetch(mail_id, "(RFC822)")
                if status != "OK":
                    continue

                raw = data[0][1]
                msg = email.message_from_bytes(raw)

                sender = decode_mime_header(msg.get("From", ""))
                subject = decode_mime_header(msg.get("Subject", "(제목 없음)"))
                date_str = msg.get("Date", "")
                body = get_email_body(msg)

                if should_ignore(sender):
                    continue

                new_emails.append({
                    "uid": uid_str,
                    "from": sender,
                    "subject": subject,
                    "date": date_str,
                    "body": body,
                })

            mail.logout()

            if new_emails:
                return {"new_emails": new_emails}
            return None

        except imaplib.IMAP4.error as e:
            logger.error(f"[email_monitor] IMAP error: {e}")
            return None
        except Exception as e:
            logger.error(f"[email_monitor] Observe error: {e}")
            return None

    async def think(self, context: dict) -> dict | None:
        """AI가 이메일 내용을 요약하고 긴급도 판단"""
        emails = context.get("new_emails", [])
        if not emails:
            return None

        email_summaries = []
        for em in emails:
            summary_text = f"발신: {em['from']}\n제목: {em['subject']}\n날짜: {em['date']}\n본문:\n{em['body'][:500]}"
            email_summaries.append(summary_text)

        prompt = "\n\n---\n\n".join(email_summaries)

        try:
            result = await self.ai_think(
                system_prompt="""당신은 이메일 분류 및 요약 AI입니다. 수신된 이메일을 분석하여:
1. 각 이메일의 한줄 요약 (한국어)
2. 카테고리 분류: 사용자문의 / 기술문의 / 결제문의 / 파트너십 / 스팸 / 기타
3. 긴급도: 🔴높음 / 🟡보통 / 🟢낮음
4. 답장이 필요한지 여부

JSON 배열로 응답:
[{"summary": "요약", "category": "카테고리", "urgency": "🟡보통", "needs_reply": true}]

스팸이나 자동발송 메일은 category를 "스팸"으로 분류하세요.""",
                user_prompt=f"다음 {len(emails)}개 이메일을 분석해주세요:\n\n{prompt}",
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
            )

            # JSON 파싱
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0]
            elif "```" in result:
                result = result.split("```")[1].split("```")[0]

            analyses = json.loads(result.strip())

            # 스팸 제외
            notifications = []
            for i, analysis in enumerate(analyses):
                if i < len(emails) and analysis.get("category") != "스팸":
                    notifications.append({
                        **emails[i],
                        "analysis": analysis,
                    })

            if notifications:
                return {"notifications": notifications}
            return None

        except Exception as e:
            logger.error(f"[email_monitor] Think error: {e}")
            # AI 분석 실패해도 기본 알림은 보냄
            return {"notifications": [
                {**em, "analysis": {"summary": em["subject"], "category": "미분류", "urgency": "🟡보통", "needs_reply": True}}
                for em in emails
            ]}

    async def act(self, decision: dict):
        """슬랙에 이메일 알림 전송"""
        notifications = decision.get("notifications", [])
        if not notifications:
            return

        lines = [f"📧 *새 이메일 {len(notifications)}건*\n"]

        for notif in notifications:
            analysis = notif.get("analysis", {})
            urgency = analysis.get("urgency", "🟡보통")
            category = analysis.get("category", "기타")
            summary = analysis.get("summary", notif.get("subject", ""))
            needs_reply = analysis.get("needs_reply", False)
            reply_tag = " · 💬답장필요" if needs_reply else ""

            lines.append(
                f"{urgency} *[{category}]* {summary}\n"
                f"   └ 발신: {notif['from']}{reply_tag}"
            )

            # 알림 완료한 UID 기록
            uid = notif.get("uid")
            if uid:
                self._state.setdefault("notified_uids", []).append(uid)

        message = "\n".join(lines)
        await self.say(message)
        self._save_state()
        logger.info(f"[email_monitor] Notified {len(notifications)} emails to Slack")
