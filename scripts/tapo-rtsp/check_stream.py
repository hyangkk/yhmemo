#!/usr/bin/env python3
"""Tapo 카메라 RTSP 스트림 연결 테스트"""

import subprocess
import sys
from config import RTSP_URL_HIGH, RTSP_URL_LOW, CAMERA_IP


def check_camera_reachable():
    """카메라 IP TCP 연결 테스트"""
    import socket
    print(f"[1/3] 카메라 IP ({CAMERA_IP}) 연결 확인 중...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        # 554(RTSP) 또는 80(HTTP) 포트로 연결 시도
        result = sock.connect_ex((CAMERA_IP, 554))
        if result == 0:
            print("  ✓ 카메라 네트워크 연결 OK")
            return True
        # 554 실패 시 80 포트 시도
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock2.settimeout(5)
        result2 = sock2.connect_ex((CAMERA_IP, 80))
        sock2.close()
        if result2 == 0:
            print("  ✓ 카메라 네트워크 연결 OK (HTTP)")
            return True
        print("  ✗ 카메라에 도달할 수 없습니다. 같은 네트워크인지 확인하세요.")
        return False
    finally:
        sock.close()


def check_rtsp_port():
    """RTSP 포트(554) 열려있는지 확인"""
    import socket
    print(f"[2/3] RTSP 포트 (554) 확인 중...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        result = sock.connect_ex((CAMERA_IP, 554))
        if result == 0:
            print("  ✓ RTSP 포트 열려있음")
            return True
        else:
            print("  ✗ RTSP 포트 닫혀있음. 카메라 설정에서 RTSP 활성화 필요")
            return False
    finally:
        sock.close()


def check_rtsp_stream():
    """ffprobe로 RTSP 스트림 정보 확인"""
    print(f"[3/3] RTSP 스트림 연결 테스트 중...")

    for label, url in [("고화질(stream1)", RTSP_URL_HIGH), ("저화질(stream2)", RTSP_URL_LOW)]:
        print(f"\n  --- {label} ---")
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-rtsp_transport", "tcp",
                "-print_format", "json",
                "-show_streams",
                "-timeout", "5000000",  # 5초 타임아웃
                url
            ],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            import json
            try:
                info = json.loads(result.stdout)
                for stream in info.get("streams", []):
                    codec = stream.get("codec_name", "unknown")
                    width = stream.get("width", "?")
                    height = stream.get("height", "?")
                    codec_type = stream.get("codec_type", "unknown")
                    if codec_type == "video":
                        print(f"  ✓ 비디오: {codec} {width}x{height}")
                    elif codec_type == "audio":
                        print(f"  ✓ 오디오: {codec}")
            except json.JSONDecodeError:
                print(f"  ✓ 스트림 연결 성공 (상세 정보 파싱 실패)")
        else:
            print(f"  ✗ 스트림 연결 실패")
            if result.stderr:
                print(f"    에러: {result.stderr[:200]}")


def main():
    print("=" * 50)
    print("Tapo 카메라 RTSP 연결 테스트")
    print("=" * 50)
    print()

    if not check_camera_reachable():
        print("\n카메라에 연결할 수 없습니다. 네트워크를 확인하세요.")
        sys.exit(1)

    if not check_rtsp_port():
        print("\nTapo 앱에서 '고급 설정 > 카메라 계정'에서 RTSP 계정을 설정했는지 확인하세요.")
        sys.exit(1)

    check_rtsp_stream()
    print("\n" + "=" * 50)
    print("테스트 완료")


if __name__ == "__main__":
    main()
