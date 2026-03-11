#!/usr/bin/env python3
"""
Tapo 카메라 RTSP 영상 가로채기 (녹화/스냅샷)

사용법:
  # 실시간 녹화 (기본 60초)
  python3 capture.py record

  # 10분 녹화
  python3 capture.py record --duration 600

  # 스냅샷 1장 캡처
  python3 capture.py snapshot

  # 연속 스냅샷 (5초 간격, 10장)
  python3 capture.py snapshot --interval 5 --count 10

  # 저화질 스트림 사용
  python3 capture.py record --low
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from config import RTSP_URL_HIGH, RTSP_URL_LOW, SAVE_DIR, SNAPSHOT_DIR


def ensure_dirs():
    os.makedirs(SAVE_DIR, exist_ok=True)
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def get_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def record_stream(rtsp_url: str, duration: int, output_path: str = None):
    """RTSP 스트림을 파일로 녹화"""
    ensure_dirs()

    if not output_path:
        output_path = os.path.join(SAVE_DIR, f"tapo_{get_timestamp()}.mp4")

    print(f"녹화 시작: {duration}초")
    print(f"저장 경로: {output_path}")
    print("Ctrl+C로 중지 가능\n")

    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-t", str(duration),
        "-c:v", "libx264",       # H.264로 변환 (macOS QuickTime 호환)
        "-pix_fmt", "yuv420p",   # QuickTime 필수 픽셀 포맷
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",           # pcm_alaw → AAC 변환
        "-ar", "44100",          # 오디오 샘플레이트 표준화
        "-ac", "1",              # 모노
        "-f", "mp4",             # 명시적 MP4 컨테이너
        "-movflags", "+faststart",
        output_path
    ]

    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        # 실시간 진행 표시
        process.wait(timeout=duration + 30)

        if process.returncode == 0:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"\n녹화 완료! ({size_mb:.1f}MB)")
            print(f"파일: {output_path}")
        else:
            stderr = process.stderr.read().decode()
            print(f"\n녹화 실패: {stderr[:500]}")
    except KeyboardInterrupt:
        process.terminate()
        process.wait()
        if os.path.exists(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"\n녹화 중단됨. 저장된 파일: {output_path} ({size_mb:.1f}MB)")


def take_snapshot(rtsp_url: str, output_path: str = None):
    """RTSP 스트림에서 스냅샷 1장 캡처"""
    ensure_dirs()

    if not output_path:
        output_path = os.path.join(SNAPSHOT_DIR, f"snap_{get_timestamp()}.jpg")

    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-frames:v", "1",
        "-q:v", "2",  # JPEG 품질 (2=고화질)
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode == 0 and os.path.exists(output_path):
        size_kb = os.path.getsize(output_path) / 1024
        print(f"스냅샷 저장: {output_path} ({size_kb:.0f}KB)")
        return output_path
    else:
        print(f"스냅샷 실패: {result.stderr[:300]}")
        return None


def continuous_snapshot(rtsp_url: str, interval: int, count: int):
    """연속 스냅샷 캡처"""
    ensure_dirs()
    print(f"연속 스냅샷: {interval}초 간격, {count}장")
    print("Ctrl+C로 중지 가능\n")

    try:
        for i in range(count):
            path = os.path.join(SNAPSHOT_DIR, f"snap_{get_timestamp()}.jpg")
            take_snapshot(rtsp_url, path)
            if i < count - 1:
                time.sleep(interval)
    except KeyboardInterrupt:
        print("\n스냅샷 중단됨.")

    print(f"\n저장 폴더: {SNAPSHOT_DIR}")


def stream_to_hls(rtsp_url: str, output_dir: str = None):
    """RTSP를 HLS로 변환 (웹 브라우저에서 실시간 시청용)"""
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(__file__), "hls")
    os.makedirs(output_dir, exist_ok=True)

    playlist = os.path.join(output_dir, "stream.m3u8")
    print(f"HLS 스트리밍 시작")
    print(f"재생 URL: {playlist}")
    print(f"VLC 등에서 열기: vlc {playlist}")
    print("Ctrl+C로 중지\n")

    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-c:v", "copy",
        "-c:a", "aac",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "10",
        "-hls_flags", "delete_segments",
        playlist
    ]

    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.wait()
    except KeyboardInterrupt:
        process.terminate()
        print("\nHLS 스트리밍 중단됨.")


def main():
    parser = argparse.ArgumentParser(description="Tapo 카메라 RTSP 영상 가로채기")
    subparsers = parser.add_subparsers(dest="command", help="명령어")

    # record 명령
    rec = subparsers.add_parser("record", help="영상 녹화")
    rec.add_argument("--duration", "-d", type=int, default=60, help="녹화 시간(초, 기본 60)")
    rec.add_argument("--low", action="store_true", help="저화질 스트림 사용")
    rec.add_argument("--output", "-o", help="출력 파일 경로")

    # snapshot 명령
    snap = subparsers.add_parser("snapshot", help="스냅샷 캡처")
    snap.add_argument("--interval", "-i", type=int, default=5, help="연속 스냅샷 간격(초)")
    snap.add_argument("--count", "-c", type=int, default=1, help="스냅샷 장수")
    snap.add_argument("--low", action="store_true", help="저화질 스트림 사용")

    # hls 명령
    hls = subparsers.add_parser("hls", help="HLS 실시간 스트리밍 (웹 시청용)")
    hls.add_argument("--low", action="store_true", help="저화질 스트림 사용")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    rtsp_url = RTSP_URL_LOW if getattr(args, "low", False) else RTSP_URL_HIGH

    if args.command == "record":
        record_stream(rtsp_url, args.duration, args.output)
    elif args.command == "snapshot":
        if args.count > 1:
            continuous_snapshot(rtsp_url, args.interval, args.count)
        else:
            take_snapshot(rtsp_url)
    elif args.command == "hls":
        stream_to_hls(rtsp_url)


if __name__ == "__main__":
    main()
