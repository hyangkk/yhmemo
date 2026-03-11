#!/usr/bin/env python3
"""
아기 하루 활동 분석기 - Tapo 카메라 SD카드 녹화본 기반

사용법 (로컬 PC에서 실행):
  pip install pytapo opencv-python-headless
  python3 analyze_baby_day.py                    # 오늘 분석
  python3 analyze_baby_day.py --date 2026-03-11  # 3/11 분석
  python3 analyze_baby_day.py --date 2026-03-11 --start 7 --end 21 --quick

옵션:
  --quick    시간당 1개 샘플만 (빠름, ~10분)
  --start N  시작 시간 (기본 7)
  --end N    끝 시간 (기본 22)
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

# === 카메라 설정 (필요시 수정) ===
CAMERA_IP = "172.30.1.79"
CAMERA_USER = "yhtapo"
CAMERA_PASS = "asdfzxcv12@"  # Tapo 카메라 계정 비밀번호
OUTPUT_DIR = "./baby_analysis"


def connect_camera(ip, user, password):
    """카메라 연결 (동기) - 카메라 계정 → admin fallback 순서로 시도"""
    from pytapo import Tapo
    # 1차: 카메라 계정으로 시도
    print(f"카메라 연결 중 ({ip}), 계정: {user}...")
    try:
        tapo = Tapo(ip, user, password, password)
        print("연결 성공!")
        return tapo
    except Exception as e:
        print(f"계정 '{user}' 실패: {e}")
    # 2차: admin으로 fallback
    if user != "admin":
        print("admin 계정으로 재시도...")
        try:
            tapo = Tapo(ip, "admin", password, password)
            print("admin 계정으로 연결 성공!")
            return tapo
        except Exception as e:
            print(f"admin 계정도 실패: {e}")
    raise Exception("카메라 인증 실패 - Tapo 앱에서 카메라 계정/비밀번호를 확인하세요")


def get_recordings(tapo, date_str):
    """특정 날짜 녹화 목록 조회"""
    date_fmt = date_str.replace("-", "")
    print(f"\n{date_str} 녹화 목록 조회 중...")
    recs = tapo.getRecordings(date_fmt)
    print(f"총 {len(recs)}개 녹화 세그먼트 발견")
    return recs


def print_recording_timeline(recs, date_str):
    """녹화 시간대 타임라인 출력"""
    print(f"\n{'='*60}")
    print(f"  {date_str} 녹화 타임라인")
    print(f"{'='*60}")

    segments = []
    for r in recs:
        for k, v in r.items():
            start = datetime.fromtimestamp(v["startTime"])
            end = datetime.fromtimestamp(v["endTime"])
            duration = (end - start).total_seconds()
            segments.append((start, end, duration))
            print(f"  {start.strftime('%H:%M:%S')} ~ {end.strftime('%H:%M:%S')} ({duration/60:.0f}분)")

    return segments


def build_sample_points(recs, date_str, start_hour, end_hour, quick=False):
    """시간대별 샘플 포인트 결정"""
    all_segments = []
    for r in recs:
        for k, v in r.items():
            all_segments.append(v)

    sample_points = []
    for hour in range(start_hour, end_hour + 1):
        minutes = [15] if quick else [10, 30, 50]
        for minute in minutes:
            target_dt = datetime.strptime(f"{date_str} {hour:02d}:{minute:02d}:00", "%Y-%m-%d %H:%M:%S")
            target_ts = int(target_dt.timestamp())

            for seg in all_segments:
                if seg["startTime"] <= target_ts <= seg["endTime"]:
                    sample_points.append({
                        "hour": hour, "minute": minute,
                        "label": f"{hour:02d}:{minute:02d}",
                        "start": target_ts,
                        "end": min(target_ts + 20, seg["endTime"]),
                    })
                    break

    return sample_points


async def download_one_sample(tapo, sp, time_correction, output_dir):
    """단일 샘플 다운로드 (async)"""
    from pytapo.media_stream.downloader import Downloader

    label = sp["label"]
    out_dir = os.path.join(output_dir, f"sample_{label.replace(':', '')}")
    os.makedirs(out_dir, exist_ok=True)

    downloader = Downloader(
        tapo=tapo,
        startTime=sp["start"],
        endTime=sp["end"],
        timeCorrection=time_correction,
        outputDirectory=out_dir,
        window_size=50,
        stall_timeout=30,
    )

    filename = None
    async for status in downloader.download():
        if status.get("fileName"):
            filename = os.path.join(out_dir, status["fileName"])

    if filename and os.path.exists(filename):
        return filename

    # 디렉토리에서 mp4 파일 찾기
    mp4s = [f for f in os.listdir(out_dir) if f.endswith(".mp4")]
    if mp4s:
        return os.path.join(out_dir, mp4s[0])

    return None


async def download_samples(tapo, sample_points, time_correction, output_dir):
    """시간대별 샘플 다운로드"""
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n{len(sample_points)}개 샘플 포인트 다운로드 시작...")

    downloaded = []
    for i, sp in enumerate(sample_points):
        label = sp["label"]
        print(f"  [{i+1}/{len(sample_points)}] {label} 다운로드 중...", end="", flush=True)

        try:
            filepath = await download_one_sample(tapo, sp, time_correction, output_dir)
            if filepath:
                size_kb = os.path.getsize(filepath) / 1024
                print(f" OK ({size_kb:.0f}KB)")
                downloaded.append({"label": label, "hour": sp["hour"], "file": filepath})
            else:
                print(" 스킵")
        except Exception as e:
            print(f" 실패: {e}")

    return downloaded


def analyze_motion(video_path):
    """비디오 움직임 점수 계산"""
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0, 0

    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    frame_skip = max(1, int(fps))
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


def print_results(results, date_str, start_hour, end_hour):
    """분석 결과 출력"""
    print(f"\n{'='*60}")
    print(f"  {date_str} 아기 활동 분석 결과")
    print(f"{'='*60}")

    hourly = {}
    for r in results:
        h = r["hour"]
        if h not in hourly:
            hourly[h] = []
        hourly[h].append(r["avg"])

    print(f"\n시간대별 움직임 (막대가 길수록 활발):\n")
    for hour in range(start_hour, end_hour + 1):
        if hourly.get(hour):
            avg = sum(hourly[hour]) / len(hourly[hour])
            bar_len = min(int(avg * 3), 40)
            bar = "█" * bar_len
            if avg > 12:
                tag = "🔴 매우 활발"
            elif avg > 7:
                tag = "🟠 활발"
            elif avg > 3:
                tag = "🟡 보통"
            elif avg > 1:
                tag = "🟢 조용"
            else:
                tag = "💤 수면"
            print(f"  {hour:02d}시  {bar:<40} {avg:5.1f}  {tag}")
        else:
            print(f"  {hour:02d}시  {'─'*10} (녹화 없음)")

    all_scores = [r for r in results if r["avg"] > 0]
    if all_scores:
        active = [r for r in all_scores if r["avg"] > 5]
        quiet = [r for r in all_scores if r["avg"] <= 3]
        peak = max(all_scores, key=lambda x: x["avg"])

        print(f"\n{'='*60}")
        print(f"  하루 요약")
        print(f"{'='*60}")
        print(f"  분석된 샘플: {len(all_scores)}개")
        print(f"  가장 활발한 시간: {peak['label']} (점수 {peak['avg']:.1f})")
        print(f"  활동적 구간 (>5): {len(active)}개")
        print(f"  조용한 구간 (≤3): {len(quiet)}개 (수면/휴식 추정)")

        print(f"\n  활동 패턴:")
        active_hours = sorted(hourly.keys())
        for h in active_hours:
            avg = sum(hourly[h]) / len(hourly[h])
            if avg > 10:
                print(f"    {h:02d}시 - 매우 활발! (놀이/운동 시간)")
            elif avg > 5:
                print(f"    {h:02d}시 - 활발 (깨어있고 움직임)")
            elif avg > 2:
                print(f"    {h:02d}시 - 조용 (앉아서 놀기/TV)")
            else:
                print(f"    {h:02d}시 - 수면/휴식")

    result_path = os.path.join(OUTPUT_DIR, f"result_{date_str}.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": date_str,
            "samples": [{"label": r["label"], "hour": r["hour"], "avg": r["avg"], "peak": r["peak"]} for r in results]
        }, f, ensure_ascii=False, indent=2)
    print(f"\n결과 JSON: {result_path}")


def main():
    parser = argparse.ArgumentParser(description="아기 하루 활동 분석기")
    parser.add_argument("--date", "-d", default=datetime.now().strftime("%Y-%m-%d"),
                        help="분석할 날짜 (YYYY-MM-DD, 기본: 오늘)")
    parser.add_argument("--start", type=int, default=7, help="시작 시간 (기본 7시)")
    parser.add_argument("--end", type=int, default=22, help="끝 시간 (기본 22시)")
    parser.add_argument("--quick", action="store_true", help="빠른 모드 (시간당 1샘플)")
    parser.add_argument("--ip", default=CAMERA_IP, help="카메라 IP")
    parser.add_argument("--password", "-p", default=CAMERA_PASS, help="Tapo 클라우드 비밀번호")
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"  아기 하루 활동 분석기")
    print(f"  날짜: {args.date} | {args.start}시~{args.end}시")
    print(f"  모드: {'빠른' if args.quick else '상세'}")
    print(f"{'='*60}")

    # 1. 카메라 연결 (동기 - pytapo 내부에서 자체 이벤트 루프 사용)
    tapo = connect_camera(args.ip, CAMERA_USER, args.password)

    # 2. 녹화 목록 조회 (동기)
    recs = get_recordings(tapo, args.date)
    if not recs:
        print("해당 날짜에 녹화가 없습니다!")
        return

    # 3. 타임라인 출력
    print_recording_timeline(recs, args.date)

    # 4. 샘플 포인트 결정 (동기)
    sample_points = build_sample_points(recs, args.date, args.start, args.end, args.quick)
    if not sample_points:
        print("해당 시간대에 녹화가 없습니다!")
        return

    # 5. 시간 보정값 (동기)
    time_correction = tapo.getTimeCorrection()

    # 6. 샘플 다운로드 (async - 별도 이벤트 루프)
    downloaded = asyncio.run(download_samples(tapo, sample_points, time_correction, OUTPUT_DIR))
    if not downloaded:
        print("다운로드된 샘플이 없습니다!")
        return

    # 7. 움직임 분석
    print(f"\n움직임 분석 중...")
    results = []
    for d in downloaded:
        avg, peak = analyze_motion(d["file"])
        results.append({"label": d["label"], "hour": d["hour"], "avg": avg, "peak": peak})
        level = "높음" if avg > 7 else ("보통" if avg > 3 else "낮음")
        print(f"  {d['label']}: 평균={avg:.1f} 최대={peak:.1f} [{level}]")

    # 8. 결과 출력
    print_results(results, args.date, args.start, args.end)


if __name__ == "__main__":
    main()
