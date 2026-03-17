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


async def process_edit(session_id: str, result_id: str, clips: list[dict], mode: str, audio_mode: str = "each"):
    """FFmpeg로 영상 편집"""
    original_mode = mode  # 업로드 경로용 (prompt 모드 유지)
    sb = _get_supabase()
    work_dir = DATA_DIR / session_id
    work_dir.mkdir(parents=True, exist_ok=True)

    n_clips = len(clips)

    # 프롬프트 모드: storage_path 덮어쓰기 전에 먼저 파싱
    prompt_opts = None
    if mode == "prompt":
        result_row = sb.table("studio_results").select("storage_path").eq("id", result_id).single().execute()
        sp = result_row.data.get("storage_path", "") if result_row.data else ""
        prompt_text = ""
        if sp.startswith("mode:prompt:"):
            parts = sp.split(":", 2)
            if len(parts) >= 3:
                prompt_text = parts[2]
                if prompt_text.endswith(":audio=best"):
                    prompt_text = prompt_text[:-len(":audio=best")]

        if prompt_text:
            print(f"[studio] 프롬프트 파싱: '{prompt_text}'", flush=True)
            prompt_opts = _parse_prompt_with_ai(prompt_text)
            print(f"[studio] 파싱 결과: {prompt_opts}", flush=True)
            mode = prompt_opts["base_mode"]
            audio_mode = prompt_opts.get("audio_mode", audio_mode)
        else:
            prompt_opts = {"bgm": False, "interval": 3.0}

    # 총 단계: 다운로드(N) + 분석(N) + 세그먼트(1) + 인코딩(1) + [BGM(1)] + 업로드(1)
    has_bgm = prompt_opts and prompt_opts.get("bgm", False)
    total_steps = n_clips + n_clips + 3 + (1 if has_bgm else 0)

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
            _edit_ai_director(local_files, str(output_path), progress=progress_cb, audio_mode=audio_mode)
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
            interval = prompt_opts.get("interval", 3.0) if prompt_opts else 3.0
            _edit_auto_cut(local_files, str(output_path), interval=interval, progress=progress_cb, audio_mode=audio_mode)

        # BGM 추가 (프롬프트에서 요청된 경우)
        if has_bgm:
            bgm_step = n_clips * 2 + 3
            _update_edit_step(sb, result_id, bgm_step, total_steps, "배경음악 적용 중")
            bgm_style = prompt_opts.get("bgm_style", "ambient")
            bgm_volume = prompt_opts.get("bgm_volume", 0.3)
            print(f"[studio] BGM 추가: style={bgm_style}, volume={bgm_volume}", flush=True)
            bgm_output = work_dir / f"result_{result_id}_bgm.mp4"
            _add_bgm_to_video(str(output_path), str(bgm_output), bgm_style=bgm_style, bgm_volume=bgm_volume)
            # BGM 버전으로 교체
            output_path.unlink(missing_ok=True)
            bgm_output.rename(output_path)
            print(f"[studio] BGM 적용 완료", flush=True)

        # 마지막 단계: 결과 업로드
        _update_edit_step(sb, result_id, total_steps, total_steps, "결과 업로드 중")
        result_storage_path = f"{session_id}/result_{result_id}_{original_mode}.mp4"
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


def _edit_auto_cut(files: list[str], output: str, interval: float = 3.0, progress: dict | None = None, audio_mode: str = "each"):
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
        last_forced_idx = 0  # 라운드로빈용 인덱스

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
                    # 라운드로빈: 모든 카메라를 순환 (항상 다음 카메라)
                    others = [c for c in alive if c != current_cam]
                    last_forced_idx = (last_forced_idx + 1) % len(others) if others else 0
                    current_cam = others[last_forced_idx] if others else current_cam
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

    # audio_mode=best: 평균 오디오 가장 큰 카메라의 오디오만 사용
    best_audio_cam = 0
    if audio_mode == "best" and audio_ok:
        avg_per_cam = []
        for i in range(n):
            active = [l for l in all_levels[i][:int(durations[i])] if l > -80]
            avg_per_cam.append(sum(active) / len(active) if active else -100.0)
        best_audio_cam = avg_per_cam.index(max(avg_per_cam))
        print(f"[studio] 최적 오디오 카메라: {best_audio_cam} (avg={avg_per_cam})", flush=True)

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
        # audio_mode=best: 항상 best_audio_cam의 오디오 사용
        audio_cam = best_audio_cam if audio_mode == "best" else cam
        parts.append(f"[{audio_cam}:a]atrim=start={start:.3f}:duration={dur:.3f},aresample=48000,asetpts=PTS-STARTPTS[a{i}];")
        concat_in.append(f"[v{i}][a{i}]")

    fc = "".join(parts) + "".join(concat_in) + f"concat=n={len(segments)}:v=1:a=1[outv][outa]"
    inp = []
    for f in files:
        inp.extend(["-i", f])

    _run_ffmpeg(inp + ["-filter_complex", fc, "-map", "[outv]", "-map", "[outa]"] +
                IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + [output])


def _edit_ai_director(files: list[str], output: str, progress: dict | None = None, audio_mode: str = "each"):
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
    last_side_idx = 0  # 사이드 카메라 라운드로빈용

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

            # 사이드 카메라 라운드로빈 순환 (모든 사이드 카메라 골고루 사용)
            side_cam = side_cams[last_side_idx % len(side_cams)]
            best_level = all_levels[side_cam][sec_idx]
            last_side_idx += 1

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

    # audio_mode=best: 메인 카메라의 오디오만 사용
    best_audio_cam = main_cam if audio_mode == "best" else None
    if best_audio_cam is not None:
        print(f"[studio] AI감독 최적 오디오: 메인 카메라 {best_audio_cam}", flush=True)

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
        audio_cam = best_audio_cam if best_audio_cam is not None else cam
        parts.append(f"[{audio_cam}:a]atrim=start={start:.3f}:duration={dur:.3f},aresample=48000,asetpts=PTS-STARTPTS[a{i}];")
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


# ── BGM (배경음악) ─────────────────────────────────────

BGM_CACHE_DIR = DATA_DIR / "bgm_cache"
BGM_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _generate_bgm(duration: float, style: str = "ambient") -> str:
    """FFmpeg lavfi로 배경음악 생성 (로열티프리)

    style:
      - ambient: 잔잔한 앰비언트 패드 (기본)
      - upbeat: 경쾌한 리듬감 있는 BGM
      - chill: 차분한 로파이 느낌
    """
    cache_key = f"bgm_{style}_{int(duration)}.mp3"
    cached = BGM_CACHE_DIR / cache_key
    if cached.exists():
        return str(cached)

    if style == "upbeat":
        # C-E-G 메이저 코드 + 리듬 패턴 (경쾌)
        lavfi = (
            f"sine=frequency=261.63:duration={duration}:sample_rate=48000,volume=0.12[c];"
            f"sine=frequency=329.63:duration={duration}:sample_rate=48000,volume=0.10[e];"
            f"sine=frequency=392.00:duration={duration}:sample_rate=48000,volume=0.09[g];"
            f"sine=frequency=523.25:duration={duration}:sample_rate=48000,volume=0.06[c2];"
            # 리듬 펄스 (4비트 느낌)
            f"sine=frequency=130.81:duration={duration}:sample_rate=48000,volume=0.08,"
            f"aeval='val(0)*abs(sin(2*PI*2*t))'[bass];"
            f"[c][e]amix=inputs=2[ce];[ce][g]amix=inputs=2[ceg];"
            f"[ceg][c2]amix=inputs=2[chord];[chord][bass]amix=inputs=2,"
            f"atempo=1.0,afade=t=in:d=2,afade=t=out:st={max(0,duration-3)}:d=3"
        )
    elif style == "chill":
        # Am7 코드 (차분한 느낌) + 느린 페이드
        lavfi = (
            f"sine=frequency=220.00:duration={duration}:sample_rate=48000,volume=0.10[a];"
            f"sine=frequency=261.63:duration={duration}:sample_rate=48000,volume=0.08[c];"
            f"sine=frequency=329.63:duration={duration}:sample_rate=48000,volume=0.07[e];"
            f"sine=frequency=392.00:duration={duration}:sample_rate=48000,volume=0.05[g];"
            f"[a][c]amix=inputs=2[ac];[ac][e]amix=inputs=2[ace];[ace][g]amix=inputs=2,"
            f"atempo=1.0,afade=t=in:d=3,afade=t=out:st={max(0,duration-4)}:d=4"
        )
    else:
        # ambient: C 메이저 코드 패드 (잔잔)
        lavfi = (
            f"sine=frequency=261.63:duration={duration}:sample_rate=48000,volume=0.08[c];"
            f"sine=frequency=329.63:duration={duration}:sample_rate=48000,volume=0.06[e];"
            f"sine=frequency=392.00:duration={duration}:sample_rate=48000,volume=0.05[g];"
            f"[c][e]amix=inputs=2[ce];[ce][g]amix=inputs=2,"
            f"afade=t=in:d=2,afade=t=out:st={max(0,duration-3)}:d=3"
        )

    _run_ffmpeg(["-f", "lavfi", "-i", lavfi, "-c:a", "libmp3lame", "-b:a", "128k", str(cached)])
    return str(cached)


def _fetch_or_generate_bgm(duration: float, style: str = "ambient") -> str:
    """Supabase Storage에서 BGM 찾기, 없으면 생성"""
    try:
        sb = _get_supabase()
        # studio-clips/bgm/ 폴더에서 BGM 파일 검색
        files = sb.storage.from_("studio-clips").list("bgm")
        if files:
            # 스타일에 맞는 파일 찾기
            for f in files:
                name = f.get("name", "")
                if style in name.lower() and (name.endswith(".mp3") or name.endswith(".m4a")):
                    local_path = BGM_CACHE_DIR / name
                    if not local_path.exists():
                        data = sb.storage.from_("studio-clips").download(f"bgm/{name}")
                        local_path.write_bytes(data)
                    return str(local_path)
            # 스타일 무관하게 아무 BGM 파일이라도 사용
            for f in files:
                name = f.get("name", "")
                if name.endswith(".mp3") or name.endswith(".m4a"):
                    local_path = BGM_CACHE_DIR / name
                    if not local_path.exists():
                        data = sb.storage.from_("studio-clips").download(f"bgm/{name}")
                        local_path.write_bytes(data)
                    return str(local_path)
    except Exception as e:
        print(f"[studio] BGM 스토리지 조회 실패 (생성으로 대체): {e}", flush=True)

    # 스토리지에 없으면 FFmpeg로 생성
    return _generate_bgm(duration, style)


def _add_bgm_to_video(video_path: str, output_path: str, bgm_style: str = "ambient", bgm_volume: float = 0.3):
    """편집된 영상에 배경음악 믹싱 (원본 오디오 유지 + BGM 저볼륨 깔기)"""
    duration = _get_duration(video_path) or 30.0
    bgm_path = _fetch_or_generate_bgm(duration, bgm_style)
    print(f"[studio] BGM 파일: {bgm_path} (영상 {duration:.1f}초)", flush=True)

    # BGM 길이 확인
    bgm_duration = _get_duration(bgm_path) or 0
    print(f"[studio] BGM 길이: {bgm_duration:.1f}초", flush=True)

    # BGM이 영상보다 짧으면 반복, 길면 자르기
    # -stream_loop로 BGM 반복 (aloop보다 안정적)
    loop_count = max(0, int(duration / bgm_duration) + 1) if bgm_duration > 0 else 0

    # amerge+pan으로 수동 믹싱 (amix의 자동 normalize 문제 회피)
    # amerge: 2개 스테레오 → 4채널(origL,origR,bgmL,bgmR)
    # pan: c0=origL+bgmL, c1=origR+bgmR → 원본 100% + BGM 볼륨 유지
    fade_out_st = max(0, duration - 2)
    _run_ffmpeg([
        "-i", video_path,
        "-stream_loop", str(loop_count), "-i", bgm_path,
        "-filter_complex",
        f"[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[orig];"
        f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
        f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        f"volume={bgm_volume},afade=t=in:d=1,afade=t=out:st={fade_out_st}:d=2[bgm];"
        f"[orig][bgm]amerge=inputs=2,pan=stereo|c0<c0+c2|c1<c1+c3[outa]",
        "-map", "0:v", "-map", "[outa]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ])


# ── 프롬프트 파싱 (자연어 → 편집 옵션) ───────────────

def _parse_prompt(prompt_text: str) -> dict:
    """자연어 프롬프트에서 편집 옵션 추출

    Returns:
        {
            "base_mode": "auto"|"director"|"split"|"pip",
            "bgm": True|False,
            "bgm_style": "ambient"|"upbeat"|"chill",
            "bgm_volume": 0.3,
            "interval": 3.0,  # 카메라 전환 주기 (초)
            "audio_mode": "each"|"best",
        }
    """
    text = prompt_text.lower()
    opts: dict = {
        "base_mode": "auto",
        "bgm": False,
        "bgm_style": "ambient",
        "bgm_volume": 0.3,
        "interval": 3.0,
        "audio_mode": "each",
    }

    # 배경음악 감지
    bgm_keywords = ["배경음악", "bgm", "음악", "배경 음악", "브금", "뮤직", "music"]
    if any(kw in text for kw in bgm_keywords):
        opts["bgm"] = True
        if any(kw in text for kw in ["경쾌", "신나", "밝은", "활기", "upbeat", "energetic"]):
            opts["bgm_style"] = "upbeat"
        elif any(kw in text for kw in ["차분", "잔잔", "조용", "로파이", "chill", "calm", "lofi"]):
            opts["bgm_style"] = "chill"

    # 편집 모드 감지
    if any(kw in text for kw in ["감독", "메인 카메라", "리액션", "director"]):
        opts["base_mode"] = "director"
    elif any(kw in text for kw in ["분할", "split", "나눠", "격자"]):
        opts["base_mode"] = "split"
    elif any(kw in text for kw in ["pip", "작은 화면", "화면 속 화면"]):
        opts["base_mode"] = "pip"

    # 전환 주기 감지
    import re
    interval_match = re.search(r'(\d+)\s*초\s*(?:마다|간격|주기|씩)', text)
    if interval_match:
        val = int(interval_match.group(1))
        if 1 <= val <= 30:
            opts["interval"] = float(val)

    # 오디오 모드 감지
    if any(kw in text for kw in ["최적 음성", "좋은 마이크", "best", "하나의 음성"]):
        opts["audio_mode"] = "best"

    return opts


def _parse_prompt_with_ai(prompt_text: str) -> dict:
    """Claude API로 프롬프트 파싱 (키워드 매칭보다 정확)"""
    try:
        import anthropic
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": f"""다음 영상 편집 지시를 JSON으로 파싱해줘. 반드시 JSON만 출력해.

지시: "{prompt_text}"

출력 형식:
{{"base_mode": "auto"|"director"|"split"|"pip", "bgm": true|false, "bgm_style": "ambient"|"upbeat"|"chill", "bgm_volume": 0.2~0.5, "interval": 1~30, "audio_mode": "each"|"best"}}

규칙:
- base_mode: 교차편집/자동=auto, 감독모드/메인카메라=director, 화면분할=split, PIP=pip
- bgm: 배경음악/BGM/음악 언급 시 true
- bgm_style: 경쾌/신나는=upbeat, 차분/잔잔=chill, 그외=ambient
- interval: 카메라 전환 주기(초), 기본 3
- audio_mode: 최적음성/좋은마이크=best, 그외=each"""}],
        )
        import json
        text = response.content[0].text.strip()
        # JSON 블록 추출
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        result = json.loads(text)
        # 유효성 검증
        result.setdefault("base_mode", "auto")
        result.setdefault("bgm", False)
        result.setdefault("bgm_style", "ambient")
        result.setdefault("bgm_volume", 0.15)
        result.setdefault("interval", 3.0)
        result.setdefault("audio_mode", "each")
        return result
    except Exception as e:
        print(f"[studio] AI 프롬프트 파싱 실패, 키워드 매칭으로 대체: {e}", flush=True)
        return _parse_prompt(prompt_text)


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
                    # 이미 처리 중이거나 대기 중인 result가 있는지 확인
                    existing = sb.table("studio_results").select("id,status,created_at,storage_path").eq("session_id", sid).execute()
                    # pending → processing으로 변경 후 편집 시작
                    pending = [r for r in (existing.data or []) if r["status"] == "pending"]
                    for r in pending:
                        sb.table("studio_results").update({"status": "processing"}).eq("id", r["id"]).execute()
                        r["status"] = "processing"
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
                                # 포맷: "mode:auto" 또는 "mode:auto:audio=best"
                                mode_part = sp.split(":", 1)[1] if sp.startswith("mode:") else "auto"
                                mode = mode_part.split(":")[0]
                                audio_mode = "best" if "audio=best" in mode_part else "each"
                                clips = sb.table("studio_clips").select("*").eq("session_id", sid).execute()
                                if clips.data:
                                    print(f"[studio] 세션 {sid}: 편집 시작 (모드={mode}, 오디오={audio_mode}, {len(clips.data)}개 클립)", flush=True)
                                    asyncio.run(process_edit(sid, r["id"], clips.data, mode, audio_mode))
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
