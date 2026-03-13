"""
멀티캠 스튜디오 - 영상 처리 API
기존 slack-agents 서버(yhmbp14)에서 함께 동작.
별도 스레드로 FastAPI/uvicorn을 띄워 HTTP 요청 처리.
"""

import asyncio
import os
import shutil
import subprocess
import tempfile
import threading
import logging
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client

logger = logging.getLogger("studio_api")

app = FastAPI(title="멀티캠 스튜디오 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(os.environ.get("STUDIO_DATA_DIR", "/app/data/studio"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _get_supabase():
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


class EditRequest(BaseModel):
    session_id: str
    mode: str = "auto"  # auto, split, pip


@app.get("/health")
async def health():
    ffmpeg_ok = _check_ffmpeg()
    build_num = os.environ.get("BUILD_NUM", "0")
    return {"status": "ok", "service": "studio", "ffmpeg": ffmpeg_ok, "build_num": build_num}


@app.post("/edit")
async def start_edit(req: EditRequest, background_tasks: BackgroundTasks):
    """영상 편집 작업 시작"""
    sb = _get_supabase()

    session = sb.table("studio_sessions").select("*").eq("id", req.session_id).single().execute()
    if not session.data:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    clips = sb.table("studio_clips").select("*").eq("session_id", req.session_id).execute()
    if not clips.data or len(clips.data) < 1:
        raise HTTPException(400, "업로드된 클립이 없습니다")

    result = sb.table("studio_results").insert({
        "session_id": req.session_id,
        "storage_path": "",
        "status": "processing",
    }).execute()

    result_id = result.data[0]["id"]

    sb.table("studio_sessions").update({"status": "editing"}).eq("id", req.session_id).execute()

    background_tasks.add_task(process_edit, req.session_id, result_id, clips.data, req.mode)

    return {"result_id": result_id, "status": "processing"}


@app.get("/edit/{result_id}")
async def get_edit_status(result_id: str):
    """편집 결과 상태 조회"""
    sb = _get_supabase()
    result = sb.table("studio_results").select("*").eq("id", result_id).single().execute()
    if not result.data:
        raise HTTPException(404, "결과를 찾을 수 없습니다")
    return result.data


def _update_edit_step(sb, result_id: str, step: int, total: int, description: str):
    """편집 진행 단계를 DB에 기록 (프론트엔드 폴링용)"""
    sb.table("studio_results").update({
        "storage_path": f"step:{step}/{total}:{description}",
    }).eq("id", result_id).execute()
    logger.info(f"[studio] 편집 진행: {step}/{total} - {description}")


async def process_edit(session_id: str, result_id: str, clips: list[dict], mode: str):
    """FFmpeg로 영상 편집"""
    sb = _get_supabase()
    work_dir = DATA_DIR / session_id
    work_dir.mkdir(parents=True, exist_ok=True)

    n_clips = len(clips)
    # 총 단계: 클립별 다운로드(N) + 클립별 분석(N) + 세그먼트 계산(1) + 인코딩(1) + 업로드(1)
    total_steps = n_clips + n_clips + 3

    try:
        # 1~N. 클립 개별 다운로드
        supabase_url = os.environ["SUPABASE_URL"]
        local_files = []
        sorted_clips = sorted(clips, key=lambda c: c.get("device_id", ""))
        async with httpx.AsyncClient(timeout=120) as client:
            for i, clip in enumerate(sorted_clips):
                step = i + 1
                _update_edit_step(sb, result_id, step, total_steps,
                                  f"클립 다운로드 중 ({i+1}/{n_clips})")
                url = f"{supabase_url}/storage/v1/object/public/studio-clips/{clip['storage_path']}"
                resp = await client.get(url)
                if resp.status_code != 200:
                    raise Exception(f"클립 다운로드 실패: {clip['storage_path']}")
                local_path = work_dir / f"clip_{clip['id']}.webm"
                local_path.write_bytes(resp.content)
                local_files.append(str(local_path))

        if not local_files:
            raise Exception("다운로드된 클립이 없습니다")

        # N+1 ~ 2N. 클립별 영상 분석
        def on_analyze(clip_idx: int):
            step = n_clips + clip_idx + 1
            _update_edit_step(sb, result_id, step, total_steps,
                              f"오디오 분석 중 ({clip_idx+1}/{n_clips})")

        # 2N+1. 세그먼트 계산
        def on_segments():
            step = n_clips * 2 + 1
            _update_edit_step(sb, result_id, step, total_steps, "편집 구간 계산 중")

        # 2N+2. FFmpeg 인코딩
        def on_encode():
            step = n_clips * 2 + 2
            _update_edit_step(sb, result_id, step, total_steps, "FFmpeg 인코딩 중")

        output_path = work_dir / f"result_{result_id}.mp4"

        progress_cb = {"on_analyze": on_analyze, "on_segments": on_segments, "on_encode": on_encode}

        if len(local_files) == 1:
            on_analyze(0)
            on_segments()
            on_encode()
            _run_ffmpeg(["-i", local_files[0],
                        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black"]
                        + IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + [str(output_path)])
        elif mode == "director":
            _edit_ai_director(local_files, str(output_path), progress=progress_cb)
        elif mode == "split":
            on_analyze(0)
            on_segments()
            on_encode()
            _edit_split_screen(local_files, str(output_path))
        elif mode == "pip":
            on_analyze(0)
            on_segments()
            on_encode()
            _edit_pip(local_files, str(output_path))
        else:
            _edit_auto_cut(local_files, str(output_path), progress=progress_cb)

        # 마지막 단계: 결과 업로드
        _update_edit_step(sb, result_id, total_steps, total_steps, "결과 업로드 중")
        result_storage_path = f"{session_id}/result_{result_id}_{mode}.mp4"
        with open(output_path, "rb") as f:
            sb.storage.from_("studio-clips").upload(
                result_storage_path, f.read(),
                file_options={"content-type": "video/mp4"},
            )

        duration = _get_duration(str(output_path))
        sb.table("studio_results").update({
            "storage_path": result_storage_path,
            "duration_ms": int(duration * 1000) if duration else None,
            "status": "done",
        }).eq("id", result_id).execute()

        sb.table("studio_sessions").update({"status": "done"}).eq("id", session_id).execute()
        logger.info(f"[studio] 편집 완료: session={session_id}")

    except Exception as e:
        logger.error(f"[studio] 편집 오류: {e}")
        sb.table("studio_results").update({"status": "error"}).eq("id", result_id).execute()
        sb.table("studio_sessions").update({"status": "done"}).eq("id", session_id).execute()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ── FFmpeg 유틸리티 ───────────────────────────────────

def _run_ffmpeg(args: list[str]):
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
    print(f"[studio] FFmpeg 실행: {' '.join(cmd[:10])}...", flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise Exception(f"FFmpeg 오류: {result.stderr}")


# 범용 고품질 인코딩 (H.264 High + CRF, 다양한 기기 입력 정규화)
ENCODE_VIDEO_OPTS = [
    "-c:v", "libx264",
    "-profile:v", "high",
    "-level", "4.1",
    "-pix_fmt", "yuv420p",
    "-crf", "20",          # 고품질 (18=거의 무손실, 23=기본, 20=좋은 품질)
    "-preset", "medium",   # 품질/속도 균형
    "-r", "30",            # 출력 프레임레이트 통일 (기기별 fps 차이 정규화)
]
ENCODE_AUDIO_OPTS = [
    "-c:a", "aac",
    "-b:a", "192k",        # 192kbps AAC (표준 품질)
    "-ar", "48000",        # 오디오 샘플레이트 통일 (안드로이드/iOS 차이 정규화)
    "-ac", "2",            # 스테레오 통일 (모노 입력도 처리)
]
# 하위 호환 별칭
IOS_VIDEO_OPTS = ENCODE_VIDEO_OPTS
IOS_AUDIO_OPTS = ENCODE_AUDIO_OPTS
IOS_CONTAINER_OPTS = ["-movflags", "+faststart"]


def _get_duration(path: str) -> float | None:
    """영상 길이 조회 (webm 등 컨테이너에 duration 없는 경우도 처리)"""
    # 1차: format=duration (mp4 등 대부분 컨테이너)
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        val = result.stdout.strip()
        if val and val != "N/A":
            dur = float(val)
            if dur > 0:
                return dur
    except (ValueError, subprocess.TimeoutExpired):
        pass

    # 2차: stream duration (webm/matroska에서 스트림 레벨 duration)
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        val = result.stdout.strip()
        if val and val != "N/A":
            dur = float(val)
            if dur > 0:
                return dur
    except (ValueError, subprocess.TimeoutExpired):
        pass

    # 3차: 패킷 기반 duration 계산 (가장 느리지만 확실)
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "packet=pts_time",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60,
        )
        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip() and l.strip() != "N/A"]
        if lines:
            return float(lines[-1])
    except (ValueError, subprocess.TimeoutExpired, IndexError):
        pass

    return None


def _analyze_audio_levels(filepath: str, interval: float = 1.0) -> list[float]:
    """각 초 단위로 오디오 볼륨(RMS) 측정"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-f", "lavfi",
             "-i", f"amovie={filepath},astats=metadata=1:reset={int(1/interval)}",
             "-show_entries", "frame_tags=lavfi.astats.Overall.RMS_level",
             "-of", "csv=p=0"],
            capture_output=True, text=True, timeout=120,
        )
        levels = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line or line == "-inf":
                levels.append(-100.0)
            else:
                try:
                    levels.append(float(line))
                except ValueError:
                    levels.append(-100.0)
        return levels if levels else [-100.0]
    except Exception:
        return [-100.0]


def _build_round_robin_segments(n: int, total_dur: float, interval: float = 3.0) -> list[tuple[int, float, float]]:
    """고정 간격 라운드로빈 세그먼트 생성"""
    segments = []
    t = 0.0
    while t < total_dur:
        cam = len(segments) % n
        end = min(t + interval, total_dur)
        segments.append((cam, t, end))
        t = end
    return segments


def _edit_auto_cut(files: list[str], output: str, interval: float = 3.0, progress: dict | None = None):
    """자동 컷편집: 3초 간격으로 카메라 전환, 오디오 분석 가능 시 스마트 전환"""
    durations = [_get_duration(f) or 0 for f in files]
    print(f"[studio] 클립 durations: {durations}", flush=True)
    max_dur = max(durations) if durations else 0
    if max_dur <= 0:
        print(f"[studio] duration 감지 실패, 단순 이어붙이기 fallback", flush=True)
        if progress:
            for i in range(len(files)):
                progress["on_analyze"](i)
            progress["on_segments"]()
            progress["on_encode"]()
        _simple_concat(files, output)
        return

    n = len(files)

    # 오디오 분석 시도
    audio_ok = False
    all_levels: list[list[float]] = []
    for i, f in enumerate(files):
        if progress:
            progress["on_analyze"](i)
        levels = _analyze_audio_levels(f)
        all_levels.append(levels)
        print(f"[studio] 오디오 분석: {f} → {len(levels)}개 샘플", flush=True)

    # 오디오 데이터가 충분한지 확인 (최소 3초 이상)
    max_samples = max(len(l) for l in all_levels)
    if max_samples >= 3:
        audio_ok = True
        print(f"[studio] 오디오 분석 성공: {max_samples}개 샘플, 스마트 전환 사용", flush=True)
    else:
        print(f"[studio] 오디오 분석 부족({max_samples}개 샘플), 라운드로빈 전환 사용", flush=True)

    # 초별 가용 카메라 (해당 시점에 영상이 있는 카메라만)
    total_secs = int(max_dur)
    def _alive_cams(sec: float) -> list[int]:
        return [i for i in range(n) if durations[i] > sec]

    if audio_ok:
        max_len = min(total_secs, max_samples)
        # 짧은 클립의 오디오는 -100으로 패딩
        for i in range(n):
            while len(all_levels[i]) < max_len:
                all_levels[i].append(-100.0)

        # 초별로 가용 카메라 중 가장 소리가 큰 카메라 선택
        best_cam_per_sec = []
        for sec in range(max_len):
            alive = _alive_cams(sec)
            if not alive:
                alive = list(range(n))
            best = alive[0]
            best_level = all_levels[best][sec]
            for cam in alive[1:]:
                if all_levels[cam][sec] > best_level:
                    best_level = all_levels[cam][sec]
                    best = cam
            best_cam_per_sec.append(best)

        segments = []
        seg_start = 0.0
        current_cam = best_cam_per_sec[0]

        for sec in range(1, max_len):
            alive = _alive_cams(sec)
            elapsed = sec - seg_start
            preferred_cam = best_cam_per_sec[sec]

            # 현재 카메라의 영상이 끝났으면 강제 전환
            if current_cam not in alive and alive:
                segments.append((current_cam, seg_start, float(sec)))
                seg_start = float(sec)
                current_cam = preferred_cam if preferred_cam in alive else alive[0]
                continue

            should_switch = preferred_cam != current_cam and elapsed >= interval
            force_switch = elapsed >= interval and len(alive) > 1

            if should_switch or force_switch:
                segments.append((current_cam, seg_start, float(sec)))
                seg_start = float(sec)
                if force_switch and preferred_cam == current_cam:
                    # 다음 가용 카메라로 전환
                    others = [c for c in alive if c != current_cam]
                    current_cam = others[0] if others else current_cam
                else:
                    current_cam = preferred_cam if preferred_cam in alive else (alive[0] if alive else current_cam)

        if seg_start < max_dur:
            segments.append((current_cam, seg_start, max_dur))
    else:
        # 오디오 분석 실패 → 가용 카메라만으로 라운드로빈
        segments = []
        t = 0.0
        cam_idx = 0
        while t < max_dur:
            alive = _alive_cams(t)
            if not alive:
                break
            cam = alive[cam_idx % len(alive)]
            end = min(t + interval, max_dur)
            # 이 카메라의 영상이 구간 중간에 끝나면 그 시점까지만
            if durations[cam] < end:
                end = durations[cam]
            segments.append((cam, t, end))
            t = end
            cam_idx += 1

    if progress:
        progress["on_segments"]()

    if not segments:
        if progress:
            progress["on_encode"]()
        _simple_concat(files, output)
        return

    print(f"[studio] 자동 편집: {len(segments)}개 세그먼트 (카메라 {n}대, 총 {max_dur:.1f}초)", flush=True)
    for i, (cam, s, e) in enumerate(segments):
        print(f"[studio]   세그먼트 {i}: 카메라{cam} {s:.1f}~{e:.1f}초", flush=True)

    if progress:
        progress["on_encode"]()

    # 출력 해상도 (가로 기준)
    out_w, out_h = 1280, 720

    parts = []
    concat_in = []
    for i, (cam, start, end) in enumerate(segments):
        dur = end - start
        # 세로 영상도 가로 프레임에 맞춤: 비율 유지 + 양옆 검정 (pillarbox)
        parts.append(
            f"[{cam}:v]trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS,"
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,fps=30[v{i}];"
        )
        parts.append(f"[{cam}:a]atrim=start={start:.3f}:duration={dur:.3f},aresample=48000,asetpts=PTS-STARTPTS[a{i}];")
        concat_in.append(f"[v{i}][a{i}]")

    fc = "".join(parts) + "".join(concat_in) + f"concat=n={len(segments)}:v=1:a=1[outv][outa]"
    inp = []
    for f in files:
        inp.extend(["-i", f])

    _run_ffmpeg(inp + ["-filter_complex", fc, "-map", "[outv]", "-map", "[outa]"] +
                IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + [output])


def _edit_ai_director(files: list[str], output: str, progress: dict | None = None):
    """AI 감독 모드: 메인 카메라 중심 + 리액션 컷어웨이 (3~5초 주기)"""
    durations = [_get_duration(f) or 0 for f in files]
    print(f"[studio] AI감독 durations: {durations}", flush=True)
    max_dur = max(durations) if durations else 0

    if max_dur <= 0 or len(files) < 2:
        if progress:
            for i in range(len(files)):
                progress["on_analyze"](i)
            progress["on_segments"]()
            progress["on_encode"]()
        _simple_concat(files, output)
        return

    n = len(files)

    # 가용 카메라 (해당 시점에 영상이 있는 카메라만)
    def _alive(sec: float) -> list[int]:
        return [i for i in range(n) if durations[i] > sec]

    # 오디오 분석
    all_levels: list[list[float]] = []
    for i, f in enumerate(files):
        if progress:
            progress["on_analyze"](i)
        levels = _analyze_audio_levels(f)
        all_levels.append(levels)
        print(f"[studio] AI감독 오디오: {f} → {len(levels)}샘플", flush=True)

    max_samples = max(len(l) for l in all_levels)
    max_len = min(int(max_dur), max_samples)

    # 짧은 클립 오디오 패딩
    for i in range(n):
        while len(all_levels[i]) < max_len:
            all_levels[i].append(-100.0)

    # 메인 카메라 결정 (평균 오디오가 가장 큰 카메라 = 화자)
    def _avg_active(levels: list[float], dur: float) -> float:
        active = [l for l in levels[:int(dur)] if l > -80]
        return sum(active) / len(active) if active else -100.0

    avg_levels = [_avg_active(all_levels[i], durations[i]) for i in range(n)]
    main_cam = avg_levels.index(max(avg_levels))
    print(f"[studio] AI감독 메인카메라: {main_cam} (avg={avg_levels})", flush=True)

    if progress:
        progress["on_segments"]()

    # 세그먼트 구성: 메인(2~3.5초) → 컷어웨이(0.8~1.5초) → 메인 → ...
    segments: list[tuple[int, float, float]] = []
    t = 0.0
    on_main = True

    while t < max_dur - 0.3:
        alive = _alive(t)
        if not alive:
            break

        # 메인 카메라가 끝났으면 가용 카메라 중 첫 번째를 메인으로
        active_main = main_cam if main_cam in alive else alive[0]

        if on_main:
            base_dur = 2.5
            best_cut = min(t + base_dur, max_dur)

            # 사이드 카메라 반응 탐색 (가용한 사이드 카메라만)
            side_cams = [c for c in alive if c != active_main]
            search_start = int(t) + 2
            search_end = min(int(t) + 5, max_len)
            best_spike = -200.0
            for sec in range(search_start, search_end):
                for cam in side_cams:
                    spike = all_levels[cam][sec] - avg_levels[cam]
                    if spike > best_spike and spike > 2.0:
                        best_spike = spike
                        best_cut = float(sec)

            # 메인 카메라 영상이 구간 중간에 끝나면 그 시점까지만
            if durations[active_main] < best_cut:
                best_cut = durations[active_main]

            segments.append((active_main, t, best_cut))
            t = best_cut
            on_main = not side_cams  # 사이드 카메라가 없으면 계속 메인
        else:
            sec_idx = min(int(t), max_len - 1)
            side_cams = [c for c in alive if c != active_main]

            if not side_cams:
                on_main = True
                continue

            # 가장 활발한 사이드 카메라 선택
            side_cam = side_cams[0]
            best_level = -200.0
            for cam in side_cams:
                lvl = all_levels[cam][sec_idx]
                if lvl > best_level:
                    best_level = lvl
                    side_cam = cam

            cutaway_dur = 1.0
            if best_level > avg_levels[side_cam] + 5:
                cutaway_dur = 1.5

            end_t = min(t + cutaway_dur, max_dur)
            if durations[side_cam] < end_t:
                end_t = durations[side_cam]

            segments.append((side_cam, t, end_t))
            t = end_t
            on_main = True

    # 남은 시간 처리
    if t < max_dur:
        alive = _alive(t)
        if alive:
            cam = main_cam if main_cam in alive else alive[0]
            segments.append((cam, t, max_dur))

    if not segments:
        if progress:
            progress["on_encode"]()
        _simple_concat(files, output)
        return

    print(f"[studio] AI감독: {len(segments)}개 세그먼트 (메인=카메라{main_cam})", flush=True)
    for i, (cam, s, e) in enumerate(segments):
        tag = "메인" if cam == main_cam else "컷어웨이"
        print(f"[studio]   [{tag}] 카메라{cam} {s:.1f}~{e:.1f}초 ({e-s:.1f}s)", flush=True)

    if progress:
        progress["on_encode"]()

    # FFmpeg filter_complex 빌드 (auto_cut과 동일 구조)
    out_w, out_h = 1280, 720
    parts = []
    concat_in = []
    for i, (cam, start, end) in enumerate(segments):
        dur = end - start
        parts.append(
            f"[{cam}:v]trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS,"
            f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,fps=30[v{i}];"
        )
        parts.append(f"[{cam}:a]atrim=start={start:.3f}:duration={dur:.3f},aresample=48000,asetpts=PTS-STARTPTS[a{i}];")
        concat_in.append(f"[v{i}][a{i}]")

    fc = "".join(parts) + "".join(concat_in) + f"concat=n={len(segments)}:v=1:a=1[outv][outa]"
    inp = []
    for f in files:
        inp.extend(["-i", f])

    _run_ffmpeg(inp + ["-filter_complex", fc, "-map", "[outv]", "-map", "[outa]"] +
                IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + [output])


def _edit_split_screen(files: list[str], output: str):
    """화면 분할 (세로 영상은 pillarbox 처리)"""
    n = len(files)
    inp = []
    for f in files:
        inp.extend(["-i", f])

    # 각 입력을 비율 유지하면서 셀 크기에 맞춤
    def _fit(idx: int, w: int, h: int, label: str) -> str:
        return (f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black[{label}]")

    if n == 2:
        fc = f"{_fit(0,640,360,'l')};{_fit(1,640,360,'r')};[l][r]hstack=inputs=2[outv]"
    elif n == 3:
        fc = (f"{_fit(0,1280,360,'top')};{_fit(1,640,360,'bl')};{_fit(2,640,360,'br')};"
              "[bl][br]hstack=inputs=2[bottom];[top][bottom]vstack=inputs=2[outv]")
    else:
        fc = (f"{_fit(0,640,360,'tl')};{_fit(1,640,360,'tr')};"
              f"{_fit(2,640,360,'bl') if n > 2 else 'color=black:640x360[bl]'};"
              f"{_fit(3,640,360,'br') if n > 3 else 'color=black:640x360[br]'};"
              "[tl][tr]hstack=inputs=2[top];[bl][br]hstack=inputs=2[bottom];"
              "[top][bottom]vstack=inputs=2[outv]")

    _run_ffmpeg(inp + ["-filter_complex", fc, "-map", "[outv]", "-map", "0:a?"] +
                IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + ["-shortest", output])


def _edit_pip(files: list[str], output: str):
    """PIP (Picture-in-Picture) - 세로 영상 pillarbox 처리"""
    inp = []
    for f in files:
        inp.extend(["-i", f])

    parts = ["[0:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black[main]"]
    cur = "[main]"
    for i in range(1, len(files)):
        sl = f"s{i}"
        parts.append(f"[{i}:v]scale=240:135:force_original_aspect_ratio=decrease,pad=240:135:(ow-iw)/2:(oh-ih)/2:black[{sl}]")
        out = f"[pip{i}]" if i < len(files) - 1 else "[outv]"
        y = 720 - 135 * i - 10 * i
        parts.append(f"{cur}[{sl}]overlay=W-w-10:{y}{out}")
        cur = f"[pip{i}]"

    _run_ffmpeg(inp + ["-filter_complex", ";".join(parts), "-map", "[outv]", "-map", "0:a?"] +
                IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + ["-shortest", output])


def _simple_concat(files: list[str], output: str):
    """단순 이어붙이기 (다양한 기기 입력 정규화 후 concat)"""
    if len(files) == 1:
        # 단일 파일은 재인코딩만
        _run_ffmpeg(["-i", files[0],
                     "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black"]
                    + ENCODE_VIDEO_OPTS + ENCODE_AUDIO_OPTS + IOS_CONTAINER_OPTS + [output])
        return

    # 복수 파일: filter_complex로 해상도/fps 정규화 후 concat (기기별 차이 대응)
    inp = []
    parts = []
    concat_in = []
    for i, f in enumerate(files):
        inp.extend(["-i", f])
        parts.append(
            f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
            f"pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,fps=30,setpts=PTS-STARTPTS[v{i}];"
        )
        parts.append(f"[{i}:a]aresample=48000,asetpts=PTS-STARTPTS[a{i}];")
        concat_in.append(f"[v{i}][a{i}]")

    fc = "".join(parts) + "".join(concat_in) + f"concat=n={len(files)}:v=1:a=1[outv][outa]"
    _run_ffmpeg(inp + ["-filter_complex", fc, "-map", "[outv]", "-map", "[outa]"] +
                ENCODE_VIDEO_OPTS + ENCODE_AUDIO_OPTS + IOS_CONTAINER_OPTS + [output])


def _check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ── 서버 시작 (orchestrator에서 호출) ─────────────────

def start_studio_server(port: int = 8000):
    """별도 스레드에서 스튜디오 API 서버 + 편집 폴링 루프 시작"""
    def _run_server():
        try:
            print(f"[studio] API 서버 시작 시도 (port={port})", flush=True)
            logger.info(f"[studio] API 서버 시작 (port={port})")
            uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
        except Exception as e:
            print(f"[studio] API 서버 크래시: {e}", flush=True)
            logger.error(f"[studio] API 서버 크래시: {e}")

    def _run_polling():
        """DB 폴링: status='editing'인 세션을 자동 감지하여 편집 실행"""
        import time
        print("[studio] 편집 폴링 루프 시작", flush=True)
        while True:
            try:
                time.sleep(10)  # 10초마다 체크
                sb = _get_supabase()
                # editing 상태이면서 아직 result가 없는 세션 찾기
                sessions = sb.table("studio_sessions").select("id").eq("status", "editing").execute()
                if not sessions.data:
                    continue

                from datetime import datetime, timezone, timedelta
                for sess in sessions.data:
                    sid = sess["id"]
                    # 이미 처리 중인 result가 있는지 확인
                    existing = sb.table("studio_results").select("id,status,created_at,storage_path").eq("session_id", sid).execute()
                    processing = [r for r in (existing.data or []) if r["status"] == "processing"]
                    if processing:
                        handled = False
                        for r in processing:
                            sp = r.get("storage_path", "")
                            created = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                            age = datetime.now(timezone.utc) - created

                            if sp.startswith("step:"):
                                # 이미 편집 진행 중 → stuck 체크만
                                if age > timedelta(minutes=5):
                                    print(f"[studio] 세션 {sid}: result {r['id']} 5분 초과, error 처리", flush=True)
                                    sb.table("studio_results").update({"status": "error"}).eq("id", r["id"]).execute()
                                else:
                                    handled = True
                            elif sp.startswith("mode:") or sp == "":
                                # 새로 생성된 result (아직 편집 시작 안됨) → 편집 시작
                                mode = sp.split(":", 1)[1] if sp.startswith("mode:") else "auto"
                                clips = sb.table("studio_clips").select("*").eq("session_id", sid).execute()
                                if clips.data:
                                    print(f"[studio] 세션 {sid}: 편집 시작 (모드={mode}, {len(clips.data)}개 클립)", flush=True)
                                    asyncio.run(process_edit(sid, r["id"], clips.data, mode))
                                    print(f"[studio] 세션 {sid}: 편집 완료 (모드={mode})", flush=True)
                                handled = True
                                break
                        if handled:
                            continue
                        # stuck 처리 후 아직 processing 남았는지 재확인
                        still_processing = sb.table("studio_results").select("id").eq("session_id", sid).eq("status", "processing").execute()
                        if still_processing.data:
                            continue

                    if existing.data and any(r["status"] == "done" for r in existing.data):
                        # 결과는 있는데 세션이 아직 editing → done으로 전환
                        sb.table("studio_sessions").update({"status": "done"}).eq("id", sid).execute()
                        continue

                    # 클립 확인
                    clips = sb.table("studio_clips").select("*").eq("session_id", sid).execute()
                    if not clips.data:
                        print(f"[studio] 세션 {sid}: 클립 없음, done으로 전환", flush=True)
                        sb.table("studio_sessions").update({"status": "done"}).eq("id", sid).execute()
                        continue

                    # 편집 시작 (기본 auto 모드)
                    print(f"[studio] 세션 {sid}: 편집 시작 (auto, {len(clips.data)}개 클립)", flush=True)
                    result = sb.table("studio_results").insert({
                        "session_id": sid,
                        "storage_path": "mode:auto",
                        "status": "processing",
                    }).execute()
                    result_id = result.data[0]["id"]
                    asyncio.run(process_edit(sid, result_id, clips.data, "auto"))
                    print(f"[studio] 세션 {sid}: 편집 완료 (auto)", flush=True)

            except Exception as e:
                print(f"[studio] 폴링 오류: {e}", flush=True)
                logger.error(f"[studio] 폴링 오류: {e}")

    t_server = threading.Thread(target=_run_server, daemon=True)
    t_server.start()
    t_polling = threading.Thread(target=_run_polling, daemon=True)
    t_polling.start()
    print(f"[studio] 스레드 시작됨 (server={t_server.is_alive()}, polling={t_polling.is_alive()})", flush=True)
    return t_server
