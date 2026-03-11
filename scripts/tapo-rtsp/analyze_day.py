#!/usr/bin/env python3
"""
Tapo 카메라 RTSP 기반 하루 활동 분석

pytapo 대신 ffmpeg + RTSP로 직접 녹화/분석합니다.
시간대별로 짧은 샘플을 캡처하여 움직임을 분석합니다.

사용법:
  # venv 활성화 후 (pip install opencv-python-headless)
  python3 analyze_day.py                    # 현재 시점부터 샘플 캡처 + 분석
  python3 analyze_day.py --hours 12         # 최근 12시간 분석
  python3 analyze_day.py --analyze-only     # 이미 캡처된 파일만 분석
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from config import CAMERA_IP, CAMERA_USER, CAMERA_PASS, RTSP_PORT, SAVE_DIR


RTSP_URL = f"rtsp://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}/stream2"


def capture_sample(output_path: str, duration: int = 30):
    """RTSP에서 짧은 샘플 캡처"""
    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "tcp",
        "-i", RTSP_URL,
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "ultrafast",
        "-crf", "28",
        "-an",  # 오디오 제외 (분석용)
        "-f", "mp4",
        "-movflags", "+faststart",
        output_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
        if result.returncode == 0 and os.path.exists(output_path):
            size_kb = os.path.getsize(output_path) / 1024
            return True
        return False
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"    캡처 실패: {e}")
        return False


def capture_continuous(output_dir: str, chunk_minutes: int = 10, total_hours: float = 1):
    """연속 캡처 (chunk 단위로 분할 저장)"""
    os.makedirs(output_dir, exist_ok=True)

    total_seconds = int(total_hours * 3600)
    chunk_seconds = chunk_minutes * 60
    num_chunks = max(1, total_seconds // chunk_seconds)

    print(f"연속 캡처 시작: {total_hours}시간, {chunk_minutes}분 단위")
    print(f"총 {num_chunks}개 청크 → {output_dir}\n")

    captured = []
    for i in range(num_chunks):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_dir, f"chunk_{ts}.mp4")
        print(f"  [{i+1}/{num_chunks}] 캡처 중... ({chunk_minutes}분)")

        ok = capture_sample(output_path, chunk_seconds)
        if ok:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"    저장: {os.path.basename(output_path)} ({size_mb:.1f}MB)")
            captured.append(output_path)
        else:
            print(f"    실패, 건너뜀")

    print(f"\n캡처 완료: {len(captured)}/{num_chunks}개 성공")
    return captured


def capture_snapshot_per_hour(output_dir: str, sample_duration: int = 60):
    """현재 RTSP에서 1분짜리 샘플 1개 캡처 (테스트용)"""
    os.makedirs(output_dir, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    hour = datetime.now().strftime("%H")
    output_path = os.path.join(output_dir, f"sample_{hour}h_{ts}.mp4")

    print(f"샘플 캡처 중 ({sample_duration}초)...")
    ok = capture_sample(output_path, sample_duration)
    if ok:
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"저장: {output_path} ({size_mb:.1f}MB)")
        return [output_path]
    else:
        print("캡처 실패. RTSP 연결을 확인하세요.")
        print(f"  URL: {RTSP_URL}")
        return []


def analyze_motion_in_video(video_path: str, sample_interval: int = 5):
    """비디오에서 움직임 수준을 분석"""
    try:
        import cv2
    except ImportError:
        print("opencv 미설치. pip install opencv-python-headless")
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    frame_skip = max(1, int(fps * sample_interval))
    prev_gray = None
    motion_scores = []

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_skip == 0:
            small = cv2.resize(frame, (160, 120))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)

            if prev_gray is not None:
                delta = cv2.absdiff(prev_gray, gray)
                score = delta.mean()
                timestamp_sec = frame_idx / fps
                motion_scores.append({
                    "time_sec": timestamp_sec,
                    "score": float(score)
                })

            prev_gray = gray

        frame_idx += 1

    cap.release()
    return motion_scores


def analyze_videos(date_str: str, recordings_dir: str):
    """폴더 내 비디오 파일들을 분석하여 활동 리포트 생성"""
    video_files = sorted(
        glob.glob(os.path.join(recordings_dir, "*.mp4"))
    )
    if not video_files:
        print(f"분석할 비디오 파일이 없습니다: {recordings_dir}")
        return

    print(f"\n{'='*60}")
    print(f"  {date_str} 활동 분석")
    print(f"{'='*60}")
    print(f"분석 대상: {len(video_files)}개 파일\n")

    all_scores = []
    hourly_activity = {h: [] for h in range(24)}

    for i, vf in enumerate(video_files):
        basename = os.path.basename(vf)
        print(f"분석 중 [{i+1}/{len(video_files)}]: {basename}")

        # 파일명에서 시간 추출 (sample_HHh_... 또는 chunk_YYYYMMDD_HHMMSS)
        hour = -1
        try:
            if "sample_" in basename:
                # sample_14h_20260311_143000.mp4
                hour = int(basename.split("_")[1].replace("h", ""))
            elif "chunk_" in basename:
                # chunk_20260311_143000.mp4
                time_part = basename.split("_")[2]  # HHMMSS
                hour = int(time_part[:2])
            else:
                # 숫자 6자리 파트 찾기
                parts = basename.replace(".mp4", "").split("_")
                for part in parts:
                    if len(part) == 6 and part.isdigit():
                        hour = int(part[:2])
                        break
        except (ValueError, IndexError):
            pass

        scores = analyze_motion_in_video(vf, sample_interval=5)
        for s in scores:
            s["file"] = basename
            if hour >= 0:
                target_hour = hour + int(s["time_sec"] / 3600)
                if 0 <= target_hour < 24:
                    hourly_activity[target_hour].append(s["score"])
        all_scores.extend(scores)

    # 전체 활동 통계
    if all_scores:
        avg_all = sum(s["score"] for s in all_scores) / len(all_scores)
        max_all = max(s["score"] for s in all_scores)
        print(f"\n전체 평균 움직임: {avg_all:.1f}, 최대: {max_all:.1f}")

    # 시간대별 리포트
    print(f"\n{'='*60}")
    print(f"  시간대별 활동량")
    print(f"{'='*60}")

    activity_levels = []
    for hour in range(24):
        scores = hourly_activity[hour]
        if scores:
            avg = sum(scores) / len(scores)
            max_s = max(scores)
            bar_len = int(avg * 3)
            bar = "█" * min(bar_len, 40)
            level = "높음" if avg > 10 else ("보통" if avg > 3 else "낮음")
            print(f"  {hour:02d}:00  {bar:<40} 평균:{avg:.1f} 최대:{max_s:.1f} [{level}]")
            activity_levels.append({"hour": hour, "avg": avg, "max": max_s, "level": level})
        else:
            print(f"  {hour:02d}:00  {'─' * 5} (데이터 없음)")

    # 요약
    if activity_levels:
        peak_hour = max(activity_levels, key=lambda x: x["avg"])
        quiet_hours = [a for a in activity_levels if a["level"] == "낮음"]
        active_hours = [a for a in activity_levels if a["level"] in ("높음", "보통")]

        print(f"\n{'='*60}")
        print(f"  요약")
        print(f"{'='*60}")
        print(f"  가장 활발한 시간: {peak_hour['hour']:02d}시 (점수 {peak_hour['avg']:.1f})")
        print(f"  활동적인 시간대: {len(active_hours)}시간")
        print(f"  조용한 시간대: {len(quiet_hours)}시간 (수면/휴식 추정)")

    # JSON 저장
    result_path = os.path.join(recordings_dir, "analysis_result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": date_str,
            "total_files": len(video_files),
            "hourly_activity": activity_levels,
            "motion_scores": all_scores[:200]
        }, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {result_path}")


def main():
    parser = argparse.ArgumentParser(description="Tapo 카메라 RTSP 기반 활동 분석")
    parser.add_argument("--date", "-d", default=datetime.now().strftime("%Y-%m-%d"),
                        help="날짜 라벨 (기본: 오늘)")
    parser.add_argument("--analyze-only", action="store_true",
                        help="캡처 없이 기존 파일만 분석")
    parser.add_argument("--output", "-o", help="저장 폴더")
    parser.add_argument("--sample", type=int, default=0,
                        help="테스트용 짧은 샘플 캡처 (초, 예: 60)")
    parser.add_argument("--continuous", type=float, default=0,
                        help="연속 캡처 시간 (시간 단위, 예: 2)")
    parser.add_argument("--chunk", type=int, default=10,
                        help="연속 캡처 시 청크 크기 (분, 기본 10)")
    parser.add_argument("--test", action="store_true",
                        help="RTSP 연결 테스트 (5초 캡처)")

    args = parser.parse_args()
    output_dir = args.output or os.path.join(SAVE_DIR, args.date)

    if args.test:
        print("RTSP 연결 테스트 (5초)...")
        os.makedirs(output_dir, exist_ok=True)
        test_path = os.path.join(output_dir, "test.mp4")
        ok = capture_sample(test_path, 5)
        if ok:
            size_kb = os.path.getsize(test_path) / 1024
            print(f"성공! {size_kb:.0f}KB 캡처됨")
        else:
            print("실패. RTSP URL 확인:")
            print(f"  {RTSP_URL}")
        return

    if args.analyze_only:
        analyze_videos(args.date, output_dir)
        return

    if args.sample > 0:
        captured = capture_snapshot_per_hour(output_dir, args.sample)
    elif args.continuous > 0:
        captured = capture_continuous(output_dir, args.chunk, args.continuous)
    else:
        # 기본: 1분 샘플 캡처
        captured = capture_snapshot_per_hour(output_dir, 60)

    if captured:
        analyze_videos(args.date, output_dir)


if __name__ == "__main__":
    main()
