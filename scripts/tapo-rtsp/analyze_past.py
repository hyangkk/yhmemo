#!/usr/bin/env python3
"""
Tapo 카메라 SD카드 녹화본 시간대별 샘플링 분석

특정 날짜의 각 시간대에서 짧은 샘플을 추출하여 움직임 분석.
RTSP 재생 URL을 사용하므로 pytapo 불필요.

사용법:
  python3 analyze_past.py                          # 오늘 분석
  python3 analyze_past.py --date 2026-03-11        # 3월 11일 분석
  python3 analyze_past.py --date 2026-03-11 --start 7 --end 21  # 7시~21시만
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime
from config import CAMERA_IP, CAMERA_USER, CAMERA_PASS, RTSP_PORT, SAVE_DIR


def get_playback_url(date_str: str, hour: int, minute: int = 0):
    """Tapo SD카드 재생용 RTSP URL 생성"""
    y, m, d = date_str.split("-")
    start = f"{y}{m}{d}T{hour:02d}{minute:02d}00"
    # stream2 = 저화질 (빠른 분석용)
    return (
        f"rtsp://{CAMERA_USER}:{CAMERA_PASS}@{CAMERA_IP}:{RTSP_PORT}"
        f"/stream2?starttime={start}"
    )


def capture_sample(rtsp_url: str, output_path: str, duration: int = 15):
    """RTSP 재생에서 짧은 샘플 캡처"""
    cmd = [
        "ffmpeg", "-y",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "ultrafast",
        "-crf", "30",
        "-an",
        "-f", "mp4",
        "-movflags", "+faststart",
        output_path
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=duration + 20
        )
        return result.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception:
        return False


def analyze_motion(video_path: str):
    """비디오 움직임 점수 계산"""
    try:
        import cv2
    except ImportError:
        print("pip install opencv-python-headless 필요")
        sys.exit(1)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0, 0

    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    frame_skip = max(1, int(fps * 2))  # 2초마다 샘플링
    prev_gray = None
    scores = []
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
                scores.append(float(delta.mean()))
            prev_gray = gray
        frame_idx += 1

    cap.release()
    if not scores:
        return 0, 0
    return sum(scores) / len(scores), max(scores)


def main():
    parser = argparse.ArgumentParser(description="과거 녹화본 시간대별 분석")
    parser.add_argument("--date", "-d", default="2026-03-11")
    parser.add_argument("--start", type=int, default=6, help="시작 시간 (기본 6시)")
    parser.add_argument("--end", type=int, default=23, help="끝 시간 (기본 23시)")
    parser.add_argument("--sample-sec", type=int, default=15, help="시간당 샘플 길이(초)")
    parser.add_argument("--output", "-o", help="저장 폴더")
    args = parser.parse_args()

    output_dir = args.output or os.path.join(SAVE_DIR, f"{args.date}_analysis")
    os.makedirs(output_dir, exist_ok=True)

    print(f"{'='*55}")
    print(f"  {args.date} 아기 활동 분석")
    print(f"  {args.start}시 ~ {args.end}시, 시간당 {args.sample_sec}초 샘플")
    print(f"{'='*55}\n")

    results = []

    for hour in range(args.start, args.end + 1):
        # 매 시간 정각 + 30분 2개 샘플
        for minute in [0, 30]:
            label = f"{hour:02d}:{minute:02d}"
            url = get_playback_url(args.date, hour, minute)
            out_path = os.path.join(output_dir, f"h{hour:02d}m{minute:02d}.mp4")

            sys.stdout.write(f"  {label} 캡처 중...")
            sys.stdout.flush()

            ok = capture_sample(url, out_path, args.sample_sec)
            if ok:
                avg, peak = analyze_motion(out_path)
                size_kb = os.path.getsize(out_path) / 1024
                level = "🔴높음" if avg > 10 else ("🟡보통" if avg > 3 else "🟢낮음")
                print(f" {level} (평균:{avg:.1f} 최대:{peak:.1f}, {size_kb:.0f}KB)")
                results.append({
                    "time": label, "hour": hour, "minute": minute,
                    "avg": avg, "peak": peak, "level": level
                })
            else:
                print(f" ─ 녹화 없음")
                results.append({
                    "time": label, "hour": hour, "minute": minute,
                    "avg": 0, "peak": 0, "level": "없음"
                })

    # 시간대별 막대 그래프
    print(f"\n{'='*55}")
    print(f"  시간대별 활동량 그래프")
    print(f"{'='*55}")

    hourly = {}
    for r in results:
        h = r["hour"]
        if h not in hourly:
            hourly[h] = []
        if r["avg"] > 0:
            hourly[h].append(r["avg"])

    for hour in range(args.start, args.end + 1):
        if hourly.get(hour):
            avg = sum(hourly[hour]) / len(hourly[hour])
            bar = "█" * min(int(avg * 3), 40)
            level = "높음" if avg > 10 else ("보통" if avg > 3 else "낮음")
            print(f"  {hour:02d}시  {bar:<40} {avg:.1f} [{level}]")
        else:
            print(f"  {hour:02d}시  ───── (녹화 없음)")

    # 요약
    active = [r for r in results if r["avg"] > 3]
    quiet = [r for r in results if 0 < r["avg"] <= 3]
    no_data = [r for r in results if r["avg"] == 0]

    if active:
        peak = max(active, key=lambda x: x["avg"])
        print(f"\n{'='*55}")
        print(f"  요약")
        print(f"{'='*55}")
        print(f"  가장 활발한 시간: {peak['time']} (점수 {peak['avg']:.1f})")
        print(f"  활동적 구간: {len(active)}개")
        print(f"  조용한 구간: {len(quiet)}개 (수면/휴식)")
        print(f"  녹화 없음: {len(no_data)}개")

    # JSON 저장
    result_path = os.path.join(output_dir, "result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({"date": args.date, "samples": results}, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {result_path}")


if __name__ == "__main__":
    main()
