"""
BabyMind OS - 메인 오케스트레이터
====================================
Tapo CCTV → Claude Vision 분석 → MCP 데이터 노출 → 부모 알림

실행: python main.py
MCP 모드: python main.py --mcp
"""

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime, time as dtime

from config import settings
from core.stream_capture import TapoStreamCapture, FrameBuffer
from analyzers.vision_analyzer import VisionAnalyzer
from analyzers.activity_tracker import ActivityTracker
from notifications.notifier import NotificationManager
from core.models import AlertLevel

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("babymind.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("babymind.main")


class BabyMindOrchestrator:
    """메인 오케스트레이터 - 모든 모듈을 연결하고 실행 루프 관리"""

    def __init__(self):
        self.capture = TapoStreamCapture()
        self.analyzer = VisionAnalyzer()
        self.tracker = ActivityTracker()
        self.notifier = NotificationManager()
        self.frame_buffer = FrameBuffer(max_frames=60)

        self._running = False
        self._last_daily_reset: str = ""
        self._previous_context: str = ""  # 연속 분석용 이전 컨텍스트
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10

    async def start(self):
        """시스템 시작"""
        logger.info("=" * 60)
        logger.info("BabyMind OS 시작")
        logger.info(f"아이: {settings.CHILD_NAME} ({settings.CHILD_AGE_MONTHS}개월)")
        logger.info(f"분석 주기: {settings.ANALYSIS_INTERVAL_SECONDS}초")
        logger.info("=" * 60)

        # 설정 검증
        missing = settings.validate_config()
        if missing:
            logger.error(f"필수 설정 누락: {', '.join(missing)}")
            logger.error("babymind-os/.env 파일을 확인해주세요.")
            return

        # 카메라 연결
        if not self.capture.connect():
            logger.error("카메라 연결 실패. 설정을 확인해주세요.")
            return

        # 시작 알림
        await self.notifier.send_alert(
            title=f"[BabyMind] 모니터링 시작",
            message=f"{settings.CHILD_NAME}의 스마트 모니터링이 시작되었습니다.",
            level="info",
        )

        # 메인 루프
        self._running = True
        try:
            await self._main_loop()
        except KeyboardInterrupt:
            logger.info("사용자 중단 (Ctrl+C)")
        finally:
            await self.shutdown()

    async def _main_loop(self):
        """주기적 프레임 캡처 → 분석 → 알림 루프"""
        while self._running:
            try:
                # 일일 리셋 체크
                today = datetime.now().strftime("%Y-%m-%d")
                if today != self._last_daily_reset:
                    if self._last_daily_reset:  # 첫 실행이 아닐 때
                        await self._send_daily_report()
                        self.tracker.reset_daily()
                    self._last_daily_reset = today

                # 프레임 캡처
                frame_b64 = self.capture.capture_as_base64()
                if frame_b64 is None:
                    self._consecutive_errors += 1
                    if self._consecutive_errors >= self._max_consecutive_errors:
                        logger.error("연속 캡처 실패 초과. 알림 발송 후 대기.")
                        await self.notifier.send_alert(
                            title="[BabyMind] 카메라 연결 문제",
                            message="카메라 스트림 연결이 불안정합니다. 확인이 필요합니다.",
                            level="warning",
                        )
                        self._consecutive_errors = 0
                    await asyncio.sleep(settings.ANALYSIS_INTERVAL_SECONDS)
                    continue

                self._consecutive_errors = 0

                # AI 분석
                analysis = await self.analyzer.analyze_frame(
                    frame_b64,
                    previous_context=self._previous_context,
                )

                if analysis:
                    # 결과 기록
                    self.tracker.record(analysis)
                    self.frame_buffer.add(
                        frame_b64=frame_b64,
                        timestamp=analysis.timestamp,
                        analysis=analysis.model_dump(),
                    )

                    # 이전 컨텍스트 업데이트
                    self._previous_context = analysis.scene_summary

                    # 안전 이벤트 즉시 알림
                    for event in analysis.safety_events:
                        if event.severity in (AlertLevel.WARNING, AlertLevel.DANGER):
                            await self.notifier.send_safety_alert(
                                event.description, event.severity
                            )

                    # 특별 이벤트 알림
                    for event in analysis.special_events:
                        await self.notifier.send_alert(
                            title=f"[BabyMind] 특별한 순간!",
                            message=f"✨ {event}",
                            level="important",
                        )

                    logger.info(
                        f"분석 완료: {analysis.scene_summary[:80]}..."
                        if len(analysis.scene_summary) > 80
                        else f"분석 완료: {analysis.scene_summary}"
                    )

                # 다음 분석까지 대기
                await asyncio.sleep(settings.ANALYSIS_INTERVAL_SECONDS)

            except Exception as e:
                logger.error(f"메인 루프 오류: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _send_daily_report(self):
        """일일 리포트 생성 및 발송"""
        logger.info("일일 리포트 생성 중...")
        try:
            report = await self.analyzer.generate_daily_summary(
                self.tracker._today_analyses
            )
            await self.notifier.send_daily_digest(report)
            logger.info("일일 리포트 발송 완료")
        except Exception as e:
            logger.error(f"일일 리포트 발송 실패: {e}")

    async def shutdown(self):
        """시스템 종료"""
        logger.info("BabyMind OS 종료 중...")
        self._running = False
        self.tracker.save_daily_data()
        self.capture.disconnect()

        await self.notifier.send_alert(
            title="[BabyMind] 모니터링 종료",
            message="모니터링이 종료되었습니다.",
            level="info",
        )
        logger.info("BabyMind OS 종료 완료")


async def run_monitoring():
    """모니터링 모드 실행"""
    orchestrator = BabyMindOrchestrator()

    # 시그널 핸들러
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(orchestrator.shutdown()))

    await orchestrator.start()


async def run_mcp():
    """MCP 서버 모드 실행"""
    from mcp_server.server import run_mcp_server, set_tracker, set_analyzer

    tracker = ActivityTracker()
    analyzer = VisionAnalyzer()
    set_tracker(tracker)
    set_analyzer(analyzer)

    await run_mcp_server()


def main():
    parser = argparse.ArgumentParser(description="BabyMind OS - 육아 AI 인텔리전스")
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="MCP 서버 모드로 실행 (stdio)",
    )
    parser.add_argument(
        "--test-frame",
        type=str,
        help="테스트 이미지 파일 경로 (카메라 대신 정적 이미지 분석)",
    )
    args = parser.parse_args()

    if args.mcp:
        logger.info("MCP 서버 모드로 시작")
        asyncio.run(run_mcp())
    elif args.test_frame:
        asyncio.run(test_single_frame(args.test_frame))
    else:
        asyncio.run(run_monitoring())


async def test_single_frame(image_path: str):
    """단일 이미지 테스트 (개발용)"""
    import base64
    from pathlib import Path

    logger.info(f"테스트 이미지 분석: {image_path}")

    img_data = Path(image_path).read_bytes()
    frame_b64 = base64.standard_b64encode(img_data).decode("utf-8")

    analyzer = VisionAnalyzer()
    analysis = await analyzer.analyze_frame(frame_b64)

    if analysis:
        print("\n" + "=" * 60)
        print("📷 분석 결과")
        print("=" * 60)
        print(f"장면: {analysis.scene_summary}")
        print(f"아이 감지: {analysis.child_detected}")
        print(f"위치: {analysis.child_position}")
        print(f"자세: {analysis.child_posture}")
        print(f"감정: {analysis.child_emotion}")
        print(f"\n감지된 물체:")
        for obj in analysis.objects:
            print(f"  - {obj.name} ({obj.category}) [{obj.location}]")
        print(f"\n행동:")
        for act in analysis.actions:
            print(f"  - {act.action} ({act.motor_type}, {act.intensity})")
        print(f"\n장난감 상호작용:")
        for toy, score in analysis.toy_interactions.items():
            bar = "█" * int(score * 10)
            print(f"  - {toy}: {bar} ({score:.1f})")
        if analysis.safety_events:
            print(f"\n⚠️ 안전 이벤트:")
            for evt in analysis.safety_events:
                print(f"  - [{evt.severity}] {evt.description}")
        if analysis.special_events:
            print(f"\n✨ 특별한 순간:")
            for evt in analysis.special_events:
                print(f"  - {evt}")
        print("=" * 60)
    else:
        print("분석 실패")


if __name__ == "__main__":
    main()
