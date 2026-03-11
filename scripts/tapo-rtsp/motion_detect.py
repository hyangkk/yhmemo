#!/usr/bin/env python3
"""
Tapo 카메라 모션 감지 녹화

RTSP 스트림을 모니터링하다가 움직임이 감지되면 자동으로 녹화를 시작합니다.

사용법:
  python3 motion_detect.py
  python3 motion_detect.py --sensitivity 30 --min-area 800
  python3 motion_detect.py --low  # 저화질 (CPU 부하 줄임)
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

import cv2
import numpy as np

from config import RTSP_URL_HIGH, RTSP_URL_LOW, SAVE_DIR


def get_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def motion_detect_loop(rtsp_url: str, sensitivity: int = 25, min_area: int = 500,
                       record_duration: int = 30, cooldown: int = 10):
    """
    모션 감지 루프

    Args:
        sensitivity: 변화 감지 임계값 (낮을수록 민감)
        min_area: 최소 움직임 영역 크기 (픽셀)
        record_duration: 모션 감지 시 녹화 시간(초)
        cooldown: 녹화 후 대기 시간(초)
    """
    os.makedirs(SAVE_DIR, exist_ok=True)

    print("모션 감지 시작")
    print(f"  민감도: {sensitivity} (낮을수록 민감)")
    print(f"  최소 영역: {min_area}px")
    print(f"  감지 시 녹화: {record_duration}초")
    print("  Ctrl+C로 중지\n")

    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not cap.isOpened():
        print("RTSP 스트림 연결 실패!")
        sys.exit(1)

    prev_frame = None
    motion_count = 0
    recording_process = None
    last_record_time = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("프레임 읽기 실패, 재연결 시도...")
                cap.release()
                time.sleep(2)
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                continue

            # 분석용 축소 + 그레이스케일
            small = cv2.resize(frame, (320, 240))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_frame is None:
                prev_frame = gray
                continue

            # 프레임 차이 계산
            delta = cv2.absdiff(prev_frame, gray)
            thresh = cv2.threshold(delta, sensitivity, 255, cv2.THRESH_BINARY)[1]
            thresh = cv2.dilate(thresh, None, iterations=2)

            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            motion_detected = False
            for contour in contours:
                if cv2.contourArea(contour) > min_area:
                    motion_detected = True
                    break

            now = time.time()

            if motion_detected and (now - last_record_time) > (record_duration + cooldown):
                motion_count += 1
                timestamp = get_timestamp()
                output_path = os.path.join(SAVE_DIR, f"motion_{timestamp}.mp4")

                print(f"[{timestamp}] 모션 감지 #{motion_count}! 녹화 시작 ({record_duration}초)")

                # ffmpeg로 백그라운드 녹화 시작
                cmd = [
                    "ffmpeg", "-y",
                    "-rtsp_transport", "tcp",
                    "-i", rtsp_url,
                    "-t", str(record_duration),
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    output_path
                ]
                recording_process = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                last_record_time = now

            prev_frame = gray

            # CPU 부하 줄이기: 초당 ~5프레임만 분석
            time.sleep(0.2)

    except KeyboardInterrupt:
        print(f"\n모션 감지 종료. 총 {motion_count}건 감지됨.")
        print(f"녹화 파일: {SAVE_DIR}")
    finally:
        cap.release()
        if recording_process and recording_process.poll() is None:
            recording_process.terminate()


def main():
    parser = argparse.ArgumentParser(description="Tapo 카메라 모션 감지 녹화")
    parser.add_argument("--sensitivity", "-s", type=int, default=25,
                        help="변화 감지 임계값 (기본 25, 낮을수록 민감)")
    parser.add_argument("--min-area", "-a", type=int, default=500,
                        help="최소 움직임 영역(px, 기본 500)")
    parser.add_argument("--duration", "-d", type=int, default=30,
                        help="감지 시 녹화 시간(초, 기본 30)")
    parser.add_argument("--cooldown", "-c", type=int, default=10,
                        help="녹화 후 대기 시간(초, 기본 10)")
    parser.add_argument("--low", action="store_true",
                        help="저화질 스트림 (CPU 절약)")

    args = parser.parse_args()
    rtsp_url = RTSP_URL_LOW if args.low else RTSP_URL_HIGH

    motion_detect_loop(rtsp_url, args.sensitivity, args.min_area,
                       args.duration, args.cooldown)


if __name__ == "__main__":
    main()
