"""Tapo 카메라 RTSP 설정"""

# 카메라 접속 정보
CAMERA_IP = "172.30.1.79"
CAMERA_USER = "admin"
CAMERA_PASS = "asdfzxcv12@"
RTSP_PORT = 554

# RTSP URL (Tapo 카메라 표준 경로)
# stream1: 고화질 (1080p/2K), stream2: 저화질 (360p)
RTSP_URL_HIGH = f"rtsp://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}/stream1"
RTSP_URL_LOW = f"rtsp://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}/stream2"

# 녹화 저장 경로
import os
SAVE_DIR = os.path.join(os.path.dirname(__file__), "recordings")
SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "snapshots")
