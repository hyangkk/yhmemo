#!/usr/bin/env python3
"""
Tapo 카메라 녹화본 다운로드 및 아기 활동 분석

3월 11일 하루 동안의 녹화본을 다운로드하고,
시간대별 움직임을 분석합니다.

사용법:
  # 맥북에서 실행 (pip3 install pytapo opencv-python-headless 필요)
  python3 analyze_day.py --date 2026-03-11
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from config import CAMERA_IP, CAMERA_USER, CAMERA_PASS, SAVE_DIR


async def get_recordings_list(date_str: str):
    """특정 날짜의 녹화 목록 조회"""
    from pytapo import Tapo

    print(f"카메라 연결 중 ({CAMERA_IP})...")
    tapo = Tapo(CAMERA_IP, CAMERA_USER, CAMERA_PASS)

    year, month, day = date_str.split("-")
    date_compact = f"{year}{month}{day}"

    print(f"{date_str} 녹화 목록 조회 중...")
    try:
        recordings = tapo.getRecordings(date_compact)
        return recordings
    except Exception as e:
        print(f"녹화 목록 조회 실패: {e}")
        return None


async def download_recordings(date_str: str, output_dir: str = None):
    """특정 날짜의 녹화본 다운로드"""
    from pytapo import Tapo
    from pytapo.media_stream.downloader import Downloader

    if not output_dir:
        output_dir = os.path.join(SAVE_DIR, date_str)
    os.makedirs(output_dir, exist_ok=True)

    print(f"카메라 연결 중 ({CAMERA_IP})...")
    tapo = Tapo(CAMERA_IP, CAMERA_USER, CAMERA_PASS)

    year, month, day = date_str.split("-")
    date_compact = f"{year}{month}{day}"

    print(f"{date_str} 녹화 목록 조회 중...")
    recordings = tapo.getRecordings(date_compact)

    if not recordings:
        print("해당 날짜에 녹화본이 없습니다.")
        return []

    # 녹화 세그먼트 정보 출력
    segments = []
    for rec_list in recordings:
        for search_result in rec_list.get("searchVideoResult", {}).get("video", []):
            start = search_result.get("startTime", "")
            end = search_result.get("endTime", "")
            segments.append({
                "start": start,
                "end": end,
                "raw": search_result
            })

    print(f"\n총 {len(segments)}개 녹화 세그먼트 발견:")
    for i, seg in enumerate(segments):
        print(f"  [{i+1}] {seg['start']} ~ {seg['end']}")

    # 다운로드
    print(f"\n녹화본 다운로드 시작 → {output_dir}")
    downloaded_files = []

    window_size = 50  # 동시 다운로드 수

    async def download_callback(current, total, file_path):
        if current == total:
            print(f"  완료: {os.path.basename(file_path)}")
            downloaded_files.append(file_path)

    try:
        downloader = Downloader(
            tapo,
            date_compact,
            2,  # 저화질 (1=고화질, 분석용이니 저화질로)
            output_dir,
            None,  # fileName prefix
            window_size
        )
        await downloader.download(download_callback)
    except Exception as e:
        print(f"다운로드 중 오류: {e}")

    return downloaded_files


def analyze_motion_in_video(video_path: str, sample_interval: int = 30):
    """
    비디오에서 움직임 수준을 분석

    Args:
        video_path: 비디오 파일 경로
        sample_interval: 프레임 샘플링 간격 (초)

    Returns:
        시간대별 움직임 점수 리스트
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        print("opencv 미설치. pip3 install opencv-python-headless")
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    frame_skip = int(fps * sample_interval)
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


def analyze_day(date_str: str, recordings_dir: str):
    """하루치 녹화본을 분석하여 활동 리포트 생성"""
    import glob

    video_files = sorted(glob.glob(os.path.join(recordings_dir, "*.mp4")))
    if not video_files:
        print(f"분석할 비디오 파일이 없습니다: {recordings_dir}")
        return

    print(f"\n{'='*60}")
    print(f" {date_str} 하루 활동 분석")
    print(f"{'='*60}")
    print(f"분석 대상: {len(video_files)}개 파일\n")

    all_scores = []
    hourly_activity = {h: [] for h in range(24)}

    for i, vf in enumerate(video_files):
        basename = os.path.basename(vf)
        print(f"분석 중 [{i+1}/{len(video_files)}]: {basename}")

        # 파일명에서 시간 추출 시도
        try:
            # pytapo 다운로드 파일명 형식에서 시간 파싱
            parts = basename.replace(".mp4", "").split("_")
            # 시간 정보가 파일명에 있으면 파싱
            for part in parts:
                if len(part) == 6 and part.isdigit():
                    hour = int(part[:2])
                    break
            else:
                hour = -1
        except (ValueError, IndexError):
            hour = -1

        scores = analyze_motion_in_video(vf, sample_interval=10)
        for s in scores:
            s["file"] = basename
            if hour >= 0:
                target_hour = hour + int(s["time_sec"] / 3600)
                if 0 <= target_hour < 24:
                    hourly_activity[target_hour].append(s["score"])
        all_scores.extend(scores)

    # 시간대별 리포트
    print(f"\n{'='*60}")
    print(f" 시간대별 활동량")
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
            print(f"  {hour:02d}:00  {'─' * 5} (녹화 없음)")

    # 요약
    if activity_levels:
        peak_hour = max(activity_levels, key=lambda x: x["avg"])
        quiet_hours = [a for a in activity_levels if a["level"] == "낮음"]
        active_hours = [a for a in activity_levels if a["level"] in ("높음", "보통")]

        print(f"\n{'='*60}")
        print(f" 요약")
        print(f"{'='*60}")
        print(f"  가장 활발한 시간: {peak_hour['hour']:02d}시 (활동점수 {peak_hour['avg']:.1f})")
        print(f"  활동적인 시간대: {len(active_hours)}시간")
        print(f"  조용한 시간대: {len(quiet_hours)}시간 (수면/휴식 추정)")

    # 결과 JSON 저장
    result_path = os.path.join(recordings_dir, "analysis_result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": date_str,
            "total_files": len(video_files),
            "hourly_activity": activity_levels,
            "motion_scores": all_scores[:100]  # 샘플만 저장
        }, f, ensure_ascii=False, indent=2)
    print(f"\n분석 결과 저장: {result_path}")


async def main():
    parser = argparse.ArgumentParser(description="Tapo 카메라 하루 활동 분석")
    parser.add_argument("--date", "-d", default="2026-03-11",
                        help="분석할 날짜 (YYYY-MM-DD, 기본 2026-03-11)")
    parser.add_argument("--skip-download", action="store_true",
                        help="다운로드 건너뛰기 (이미 다운로드한 경우)")
    parser.add_argument("--output", "-o", help="저장 폴더 경로")

    args = parser.parse_args()
    output_dir = args.output or os.path.join(SAVE_DIR, args.date)

    if not args.skip_download:
        await download_recordings(args.date, output_dir)

    analyze_day(args.date, output_dir)


if __name__ == "__main__":
    asyncio.run(main())
