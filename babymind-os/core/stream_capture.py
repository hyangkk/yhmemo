"""
Tapo CCTV RTSP 스트림 캡처 모듈
- RTSP 스트림에서 주기적으로 프레임 캡처
- 캡처된 프레임을 base64 인코딩하여 AI 분석에 전달
- 원본 프레임은 설정된 시간 후 자동 파기
"""

import asyncio
import base64
import io
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from config import settings

logger = logging.getLogger("babymind.capture")


class TapoStreamCapture:
    """Tapo IP 카메라 RTSP 스트림에서 프레임을 캡처하는 클래스"""

    def __init__(
        self,
        rtsp_url: Optional[str] = None,
        width: int = settings.CAPTURE_WIDTH,
        height: int = settings.CAPTURE_HEIGHT,
    ):
        self.rtsp_url = rtsp_url or settings.get_rtsp_url()
        self.width = width
        self.height = height
        self._cap: Optional[cv2.VideoCapture] = None
        self._connected = False
        self._retry_count = 0
        self._max_retries = 5
        self._last_frame_time: Optional[float] = None

    def connect(self) -> bool:
        """RTSP 스트림에 연결"""
        if not self.rtsp_url:
            logger.error("RTSP URL이 설정되지 않음. TAPO_USERNAME, TAPO_PASSWORD, TAPO_CAMERA_IP 확인 필요")
            return False

        try:
            # OpenCV RTSP 연결 (TCP 전송 강제로 안정성 확보)
            self._cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 버퍼 최소화 (최신 프레임만)

            if self._cap.isOpened():
                self._connected = True
                self._retry_count = 0
                logger.info(f"Tapo 카메라 연결 성공: {self._mask_url(self.rtsp_url)}")
                return True
            else:
                logger.error("Tapo 카메라 연결 실패: 스트림을 열 수 없음")
                return False

        except Exception as e:
            logger.error(f"Tapo 카메라 연결 오류: {e}")
            return False

    def disconnect(self):
        """스트림 연결 해제"""
        if self._cap:
            self._cap.release()
            self._cap = None
        self._connected = False
        logger.info("Tapo 카메라 연결 해제")

    def _reconnect(self) -> bool:
        """연결 끊김 시 재연결 (지수 백오프)"""
        self._retry_count += 1
        if self._retry_count > self._max_retries:
            logger.error(f"최대 재연결 시도 횟수({self._max_retries}) 초과")
            return False

        wait_time = min(2 ** self._retry_count, 30)
        logger.warning(f"재연결 시도 {self._retry_count}/{self._max_retries} ({wait_time}초 대기)")
        time.sleep(wait_time)

        self.disconnect()
        return self.connect()

    def capture_frame(self) -> Optional[np.ndarray]:
        """현재 프레임 한 장 캡처. 실패 시 None 반환."""
        if not self._connected or not self._cap:
            if not self._reconnect():
                return None

        try:
            # 버퍼 비우기 (최신 프레임 확보)
            for _ in range(3):
                self._cap.grab()

            ret, frame = self._cap.read()
            if not ret or frame is None:
                logger.warning("프레임 읽기 실패, 재연결 시도")
                if self._reconnect():
                    ret, frame = self._cap.read()
                    if not ret:
                        return None
                else:
                    return None

            # 리사이즈
            if frame.shape[1] != self.width or frame.shape[0] != self.height:
                frame = cv2.resize(frame, (self.width, self.height))

            self._last_frame_time = time.time()
            self._retry_count = 0
            return frame

        except Exception as e:
            logger.error(f"프레임 캡처 오류: {e}")
            return None

    def frame_to_base64(self, frame: np.ndarray, quality: int = 85) -> str:
        """프레임을 base64 인코딩된 JPEG로 변환 (Claude Vision API용)"""
        # BGR -> RGB 변환
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb_frame)

        # JPEG 압축
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)

        return base64.standard_b64encode(buffer.read()).decode("utf-8")

    def capture_as_base64(self, quality: int = 85) -> Optional[str]:
        """프레임 캡처 + base64 변환을 한 번에 수행"""
        frame = self.capture_frame()
        if frame is None:
            return None
        return self.frame_to_base64(frame, quality)

    @staticmethod
    def _mask_url(url: str) -> str:
        """로그에 비밀번호가 노출되지 않도록 마스킹"""
        # rtsp://user:pass@ip:port/stream -> rtsp://user:***@ip:port/stream
        if "@" in url:
            prefix, rest = url.split("@", 1)
            if ":" in prefix:
                scheme_user = prefix.rsplit(":", 1)[0]
                return f"{scheme_user}:***@{rest}"
        return url

    @property
    def is_connected(self) -> bool:
        return self._connected and self._cap is not None and self._cap.isOpened()


class FrameBuffer:
    """최근 프레임을 임시 보관하는 순환 버퍼 (자동 클리핑용)"""

    def __init__(self, max_frames: int = 30):
        self.max_frames = max_frames
        self._frames: list[dict] = []

    def add(self, frame_b64: str, timestamp: datetime, analysis: Optional[dict] = None):
        """프레임 추가"""
        self._frames.append({
            "frame_b64": frame_b64,
            "timestamp": timestamp.isoformat(),
            "analysis": analysis,
        })
        # 오래된 프레임 제거
        if len(self._frames) > self.max_frames:
            self._frames = self._frames[-self.max_frames:]

    def get_recent(self, count: int = 5) -> list[dict]:
        """최근 N개 프레임 반환"""
        return self._frames[-count:]

    def find_event_frames(self, event_type: str) -> list[dict]:
        """특정 이벤트가 감지된 프레임 검색"""
        results = []
        for f in self._frames:
            if f.get("analysis") and event_type in str(f["analysis"]):
                results.append(f)
        return results

    def clear(self):
        """버퍼 비우기"""
        self._frames.clear()

    @property
    def size(self) -> int:
        return len(self._frames)
