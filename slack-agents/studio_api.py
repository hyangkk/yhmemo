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

    # 총 단계: 다운로드(N) + 분석(N) + 세그먼트(1) + 인코딩(1) + [BGM(1)] + [자막(1)] + 업로드(1)
    has_bgm = prompt_opts and prompt_opts.get("bgm", False)
    has_subtitle = prompt_opts and prompt_opts.get("subtitle", False)
    total_steps = n_clips + n_clips + 3 + (1 if has_bgm else 0) + (1 if has_subtitle else 0)

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
            bgm_style = (prompt_opts or {}).get("bgm_style", "ambient")
            bgm_volume = (prompt_opts or {}).get("bgm_volume", 0.5)
            print(f"[studio] BGM 추가: style={bgm_style}, volume={bgm_volume}", flush=True)
            bgm_output = work_dir / f"result_{result_id}_bgm.mp4"
            try:
                _add_bgm_to_video(str(output_path), str(bgm_output), bgm_style=bgm_style, bgm_volume=bgm_volume)
                # BGM 파일 검증 후 교체
                if bgm_output.exists() and bgm_output.stat().st_size > 0:
                    output_path.unlink(missing_ok=True)
                    bgm_output.rename(output_path)
                    print(f"[studio] BGM 적용 완료", flush=True)
                else:
                    print(f"[studio] BGM 출력 파일 없음/비어있음, 원본 유지", flush=True)
                    bgm_output.unlink(missing_ok=True)
            except Exception as bgm_err:
                print(f"[studio] BGM 적용 실패: {bgm_err}, 원본 유지", flush=True)
                bgm_output.unlink(missing_ok=True)
                # BGM 실패해도 원본 영상은 유지하여 편집 결과 전달

        # 자막 추가 (프롬프트에서 요청된 경우)
        if has_subtitle:
            subtitle_step_num = n_clips * 2 + 3 + (1 if has_bgm else 0)
            _update_edit_step(sb, result_id, subtitle_step_num, total_steps, "자막 생성 중 (음성인식)")
            subtitle_style = prompt_opts.get("subtitle", "blackBg") if prompt_opts else "blackBg"
            # bool True가 올 수 있음 → 기본값으로 교정
            if subtitle_style is True or subtitle_style not in ("blackBg", "outline"):
                subtitle_style = "blackBg"
            print(f"[studio] 자막 추가: style={subtitle_style}", flush=True)
            subtitle_output = work_dir / f"result_{result_id}_sub.mp4"
            try:
                success = _add_subtitles_to_video(str(output_path), str(subtitle_output), subtitle_style)
                if success and subtitle_output.exists() and subtitle_output.stat().st_size > 0:
                    output_path.unlink(missing_ok=True)
                    subtitle_output.rename(output_path)
                    print("[studio] 자막 적용 완료", flush=True)
                else:
                    print("[studio] 자막 출력 없음, 원본 유지", flush=True)
                    subtitle_output.unlink(missing_ok=True)
            except Exception as sub_err:
                print(f"[studio] 자막 적용 실패: {sub_err}, 원본 유지", flush=True)
                subtitle_output.unlink(missing_ok=True)

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

import math
import struct
import wave
import random

BGM_CACHE_DIR = DATA_DIR / "bgm_cache"
BGM_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 음계 주파수 (Hz) - C3~C6
_NOTE_FREQ = {
    "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61,
    "G3": 196.00, "A3": 220.00, "B3": 246.94,
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23,
    "G4": 392.00, "A4": 440.00, "B4": 493.88,
    "C5": 523.25, "D5": 587.33, "E5": 659.25, "F5": 698.46,
    "G5": 783.99, "A5": 880.00, "B5": 987.77,
    "C6": 1046.50,
}

# 스타일별 코드 진행 & 설정
_BGM_PRESETS = {
    "ambient": {
        # I → IV → V → I (C → F → G → C) - 클래식 정통 진행, 아름답고 잔잔한 느낌
        "chords": [
            ["C4", "E4", "G4"],       # C (토닉)
            ["F3", "A3", "C4"],       # F (서브도미넌트)
            ["G3", "B3", "D4"],       # G (도미넌트)
            ["C4", "E4", "G4"],       # C (해결)
        ],
        "bass_notes": ["C3", "F3", "G3", "C3"],
        "bpm": 60,
        "arp_pattern": "up",        # 아르페지오 상행 (클래식 느낌)
        "waveform": "soft_sine",    # 부드러운 사인파
        "reverb_mix": 0.35,
    },
    "upbeat": {
        # I → IV → V → vi (C → F → G → Am) - 밝은 진행
        "chords": [
            ["C4", "E4", "G4"],       # C
            ["F4", "A4", "C5"],       # F
            ["G4", "B4", "D5"],       # G
            ["A4", "C5", "E5"],       # Am
        ],
        "bass_notes": ["C3", "F3", "G3", "A3"],
        "bpm": 120,
        "arp_pattern": "up_down",   # 상행-하행 아르페지오
        "waveform": "triangle",     # 트라이앵글파 (밝은 느낌)
        "reverb_mix": 0.15,
    },
}


def _adsr_envelope(t: float, note_dur: float,
                   attack: float = 0.05, decay: float = 0.1,
                   sustain_level: float = 0.7, release: float = 0.1) -> float:
    """ADSR 엔벨로프: 어택-디케이-서스테인-릴리즈"""
    if t < attack:
        return t / attack
    elif t < attack + decay:
        return 1.0 - (1.0 - sustain_level) * ((t - attack) / decay)
    elif t < note_dur - release:
        return sustain_level
    elif t < note_dur:
        return sustain_level * (1.0 - (t - (note_dur - release)) / release)
    return 0.0


def _oscillator(phase: float, waveform: str = "soft_sine") -> float:
    """다양한 파형 생성"""
    if waveform == "triangle":
        # 트라이앵글파 (부드럽지만 밝은 느낌)
        return 2.0 * abs(2.0 * (phase / (2 * math.pi) % 1.0) - 1.0) - 1.0
    elif waveform == "warm_sine":
        # 디튠된 사인파 2개 합성 (따뜻한 느낌)
        return 0.7 * math.sin(phase) + 0.3 * math.sin(phase * 1.003)
    else:
        # soft_sine: 기본 사인파 + 약한 2배음
        return 0.85 * math.sin(phase) + 0.15 * math.sin(phase * 2)


def _generate_bgm(duration: float, style: str = "ambient") -> str:
    """Python wave 모듈로 실제 음악적 BGM 생성

    코드 진행, 아르페지오, 베이스라인, ADSR 엔벨로프 포함.
    WAV 생성 후 FFmpeg로 MP3 변환.

    style: ambient (잔잔/클래식), upbeat (경쾌/신나는)
    """
    cache_key = f"bgm_v2_{style}_{int(duration)}.mp3"
    cached = BGM_CACHE_DIR / cache_key
    if cached.exists():
        return str(cached)

    preset = _BGM_PRESETS.get(style, _BGM_PRESETS["ambient"])
    sample_rate = 48000
    total_samples = int(duration * sample_rate)
    samples = [0.0] * total_samples

    chords = preset["chords"]
    bass_notes = preset["bass_notes"]
    bpm = preset["bpm"]
    waveform = preset["waveform"]
    arp_pattern = preset["arp_pattern"]
    reverb_mix = preset["reverb_mix"]

    beat_dur = 60.0 / bpm  # 1비트 길이 (초)
    bar_dur = beat_dur * 4  # 1마디 = 4비트
    num_chords = len(chords)

    # 시드 고정 (같은 스타일이면 같은 음악)
    rng = random.Random(42 + hash(style))

    # ── 1. 패드 (코드 전체음) ──
    pad_volume = 0.06
    for si in range(total_samples):
        t = si / sample_rate
        bar_index = int(t / bar_dur) % num_chords
        chord = chords[bar_index]
        t_in_bar = t % bar_dur

        env = _adsr_envelope(t_in_bar, bar_dur, attack=0.3, decay=0.2,
                             sustain_level=0.6, release=0.3)
        val = 0.0
        for note_name in chord:
            freq = _NOTE_FREQ[note_name]
            phase = 2 * math.pi * freq * t
            val += _oscillator(phase, waveform)
        samples[si] += val / len(chord) * pad_volume * env

    # ── 2. 아르페지오 ──
    arp_volume = 0.09
    notes_per_beat = 2 if style == "upbeat" else 1
    arp_note_dur = beat_dur / notes_per_beat

    for si in range(total_samples):
        t = si / sample_rate
        bar_index = int(t / bar_dur) % num_chords
        chord = chords[bar_index]
        t_in_bar = t % bar_dur

        # 아르페지오 순서 결정
        if arp_pattern == "up":
            note_seq = list(chord)
        elif arp_pattern == "up_down":
            note_seq = list(chord) + list(reversed(chord[1:-1])) if len(chord) > 2 else list(chord) * 2
        else:  # broken
            note_seq = list(chord)
            rng_bar = random.Random(42 + bar_index)
            rng_bar.shuffle(note_seq)

        # 아르페지오 노트별로 추가 (비트 단위)
        total_arp_notes = int(4 * notes_per_beat)
        arp_idx = int(t_in_bar / arp_note_dur) % total_arp_notes
        note_in_seq = arp_idx % len(note_seq)
        t_in_note = t_in_bar - arp_idx * arp_note_dur

        if 0 <= t_in_note < arp_note_dur:
            env = _adsr_envelope(t_in_note, arp_note_dur,
                                 attack=0.02, decay=0.05,
                                 sustain_level=0.4, release=0.05)
            freq = _NOTE_FREQ[note_seq[note_in_seq]]
            # 아르페지오는 1옥타브 위
            freq *= 2.0
            phase = 2 * math.pi * freq * t
            samples[si] += _oscillator(phase, waveform) * arp_volume * env

    # ── 3. 베이스라인 ──
    bass_volume = 0.10
    for si in range(total_samples):
        t = si / sample_rate
        bar_index = int(t / bar_dur) % num_chords
        bass_note = bass_notes[bar_index]
        bass_freq = _NOTE_FREQ[bass_note]
        t_in_bar = t % bar_dur

        # 베이스: 마디 시작에 강, 반박에 약하게
        if style == "upbeat":
            # 8비트 베이스 (각 비트마다)
            beat_idx = int(t_in_bar / beat_dur)
            t_in_beat = t_in_bar - beat_idx * beat_dur
            env = _adsr_envelope(t_in_beat, beat_dur,
                                 attack=0.01, decay=0.15,
                                 sustain_level=0.3, release=0.05)
            # 루트 - 5도 패턴
            if beat_idx % 2 == 1:
                bass_freq *= 1.5  # 5도 위
        else:
            # 긴 베이스 노트 (마디 전체)
            env = _adsr_envelope(t_in_bar, bar_dur,
                                 attack=0.05, decay=0.3,
                                 sustain_level=0.5, release=0.2)

        phase = 2 * math.pi * bass_freq * t
        # 베이스는 사인파 (깨끗한 저음)
        samples[si] += math.sin(phase) * bass_volume * env

    # ── 4. 리버브 효과 (딜레이 믹스) ──
    if reverb_mix > 0:
        delay_samples_1 = int(0.08 * sample_rate)  # 80ms
        delay_samples_2 = int(0.15 * sample_rate)  # 150ms
        reverb = [0.0] * total_samples
        for si in range(total_samples):
            val = samples[si]
            if si >= delay_samples_1:
                val += samples[si - delay_samples_1] * 0.4
            if si >= delay_samples_2:
                val += samples[si - delay_samples_2] * 0.2
            reverb[si] = val
        for si in range(total_samples):
            samples[si] = samples[si] * (1 - reverb_mix) + reverb[si] * reverb_mix

    # ── 5. 페이드 인/아웃 ──
    fade_in_dur = 2.0
    fade_out_dur = 3.0
    fade_in_samples = int(fade_in_dur * sample_rate)
    fade_out_samples = int(fade_out_dur * sample_rate)
    for si in range(min(fade_in_samples, total_samples)):
        samples[si] *= si / fade_in_samples
    for si in range(min(fade_out_samples, total_samples)):
        idx = total_samples - 1 - si
        if idx >= 0:
            samples[idx] *= si / fade_out_samples

    # ── 6. 노멀라이즈 ──
    peak = max(abs(s) for s in samples) if samples else 1.0
    if peak > 0:
        normalize_factor = 0.9 / peak
        samples = [s * normalize_factor for s in samples]

    # ── 7. WAV 저장 → MP3 변환 ──
    wav_path = BGM_CACHE_DIR / f"bgm_v2_{style}_{int(duration)}.wav"
    with wave.open(str(wav_path), "w") as wf:
        wf.setnchannels(2)  # 스테레오
        wf.setsampwidth(2)  # 16bit
        wf.setframerate(sample_rate)
        for s in samples:
            val = max(-1.0, min(1.0, s))
            packed = struct.pack("<h", int(val * 32767))
            wf.writeframes(packed * 2)  # L+R 동일

    _run_ffmpeg(["-i", str(wav_path), "-c:a", "libmp3lame", "-b:a", "192k", str(cached)])
    wav_path.unlink(missing_ok=True)

    print(f"[studio] BGM 생성 완료: style={style}, duration={duration:.1f}s", flush=True)
    return str(cached)


def _download_pixabay_bgm(duration: float, style: str = "ambient") -> str | None:
    """Pixabay API에서 무료 로열티프리 음악 다운로드

    PIXABAY_API_KEY 환경변수 필요. 없으면 None 반환.
    """
    api_key = os.environ.get("PIXABAY_API_KEY")
    if not api_key:
        return None

    # 스타일별 검색어 매핑
    search_map = {
        "ambient": "classical beautiful calm piano",
        "upbeat": "upbeat happy energetic",
    }
    query = search_map.get(style, "background music")

    cache_key = f"pixabay_{style}.mp3"
    cached = BGM_CACHE_DIR / cache_key
    if cached.exists():
        return str(cached)

    try:
        import urllib.request
        import urllib.parse
        import json

        url = (
            f"https://pixabay.com/api/videos/music/"
            f"?key={api_key}&q={urllib.parse.quote(query)}"
            f"&per_page=5&order=popular"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "StudioBot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())

        hits = data.get("hits", [])
        if not hits:
            print(f"[studio] Pixabay 검색 결과 없음: {query}", flush=True)
            return None

        # 첫 번째 결과 다운로드
        audio_url = hits[0].get("audio", {}).get("url") or hits[0].get("url")
        if not audio_url:
            return None

        print(f"[studio] Pixabay BGM 다운로드: {audio_url[:80]}...", flush=True)
        urllib.request.urlretrieve(audio_url, str(cached))

        if cached.exists() and cached.stat().st_size > 1000:
            print(f"[studio] Pixabay BGM 다운로드 완료: {cached.stat().st_size} bytes", flush=True)
            return str(cached)

        cached.unlink(missing_ok=True)
        return None
    except Exception as e:
        print(f"[studio] Pixabay BGM 다운로드 실패: {e}", flush=True)
        cached.unlink(missing_ok=True)
        return None


def _fetch_or_generate_bgm(duration: float, style: str = "ambient") -> str:
    """BGM 조달 우선순위: Supabase Storage → Pixabay API → Python 생성"""
    # 1순위: Supabase Storage (사용자 업로드 BGM)
    try:
        sb = _get_supabase()
        files = sb.storage.from_("studio-clips").list("bgm")
        if files:
            for f in files:
                name = f.get("name", "")
                if style in name.lower() and (name.endswith(".mp3") or name.endswith(".m4a")):
                    local_path = BGM_CACHE_DIR / name
                    if not local_path.exists():
                        data = sb.storage.from_("studio-clips").download(f"bgm/{name}")
                        local_path.write_bytes(data)
                    return str(local_path)
            for f in files:
                name = f.get("name", "")
                if name.endswith(".mp3") or name.endswith(".m4a"):
                    local_path = BGM_CACHE_DIR / name
                    if not local_path.exists():
                        data = sb.storage.from_("studio-clips").download(f"bgm/{name}")
                        local_path.write_bytes(data)
                    return str(local_path)
    except Exception as e:
        print(f"[studio] BGM 스토리지 조회 실패: {e}", flush=True)

    # 2순위: Pixabay API (무료 로열티프리 음악)
    pixabay_path = _download_pixabay_bgm(duration, style)
    if pixabay_path:
        return pixabay_path

    # 3순위: Python으로 직접 음악 생성
    return _generate_bgm(duration, style)


def _has_audio_stream(video_path: str) -> bool:
    """비디오 파일에 오디오 스트림이 있는지 확인"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", video_path],
            capture_output=True, text=True, timeout=10)
        return bool(result.stdout.strip())
    except Exception:
        return True  # 확인 불가 시 있다고 가정


def _add_bgm_to_video(video_path: str, output_path: str, bgm_style: str = "ambient", bgm_volume: float = 0.5):
    """편집된 영상에 배경음악 믹싱 (원본 오디오 유지 + BGM 저볼륨 깔기)"""
    duration = _get_duration(video_path) or 30.0
    bgm_path = _fetch_or_generate_bgm(duration, bgm_style)
    print(f"[studio] BGM 파일: {bgm_path} (영상 {duration:.1f}초)", flush=True)

    # BGM 파일 존재 및 크기 검증
    bgm_file = Path(bgm_path)
    if not bgm_file.exists() or bgm_file.stat().st_size < 100:
        print(f"[studio] BGM 파일 손상/없음, 재생성: {bgm_path}", flush=True)
        bgm_file.unlink(missing_ok=True)
        bgm_path = _generate_bgm(duration, bgm_style)

    # BGM 길이 확인
    bgm_duration = _get_duration(bgm_path) or 0
    print(f"[studio] BGM 길이: {bgm_duration:.1f}초", flush=True)

    # BGM 길이가 0이면 재생성
    if bgm_duration <= 0:
        print(f"[studio] BGM 길이 0, 재생성 시도", flush=True)
        Path(bgm_path).unlink(missing_ok=True)
        bgm_path = _generate_bgm(duration, bgm_style)
        bgm_duration = _get_duration(bgm_path) or 0
        if bgm_duration <= 0:
            raise Exception("BGM 생성 실패: 길이 0")

    # BGM이 영상보다 짧으면 반복, 길면 자르기
    loop_count = max(1, int(duration / bgm_duration) + 1)

    # 입력 영상에 오디오 트랙이 있는지 확인
    has_audio = _has_audio_stream(video_path)
    fade_out_st = max(0, duration - 2)

    if has_audio:
        # amerge+pan으로 수동 믹싱 (amix의 자동 normalize 문제 회피)
        # amerge: 2개 스테레오 → 4채널(origL,origR,bgmL,bgmR)
        # pan: c0=origL+bgmL, c1=origR+bgmR → 원본 100% + BGM 볼륨 유지
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
    else:
        # 오디오 없는 영상 → BGM만 단독으로 추가
        print(f"[studio] 원본 오디오 없음, BGM만 추가", flush=True)
        _run_ffmpeg([
            "-i", video_path,
            "-stream_loop", str(loop_count), "-i", bgm_path,
            "-filter_complex",
            f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
            f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"volume={bgm_volume},afade=t=in:d=1,afade=t=out:st={fade_out_st}:d=2[outa]",
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
            "bgm_style": "ambient"|"upbeat",
            "bgm_volume": 0.5,
            "interval": 3.0,  # 카메라 전환 주기 (초)
            "audio_mode": "each"|"best",
        }
    """
    text = prompt_text.lower()
    opts: dict = {
        "base_mode": "auto",
        "bgm": False,
        "bgm_style": "ambient",
        "bgm_volume": 0.5,
        "interval": 3.0,
        "audio_mode": "each",
        "subtitle": False,
    }

    # 배경음악 감지
    bgm_keywords = ["배경음악", "bgm", "음악", "배경 음악", "브금", "뮤직", "music",
                    "background", "사운드", "sound", "노래", "멜로디", "melody"]
    if any(kw in text for kw in bgm_keywords):
        opts["bgm"] = True
        if any(kw in text for kw in ["경쾌", "신나", "밝은", "활기", "upbeat", "energetic"]):
            opts["bgm_style"] = "upbeat"
        elif any(kw in text for kw in ["차분", "잔잔", "조용", "클래식", "고전", "아름다운", "calm", "classical",
                                        "로파이", "chill", "lofi"]):
            opts["bgm_style"] = "ambient"

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

    # 자막 감지
    subtitle_keywords = ["자막", "subtitle", "caption", "자동 자막", "자동자막"]
    if any(kw in text for kw in subtitle_keywords):
        if any(kw in text for kw in ["테두리", "외곽선", "outline"]):
            opts["subtitle"] = "outline"
        else:
            opts["subtitle"] = "blackBg"

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
{{"base_mode": "auto"|"director"|"split"|"pip", "bgm": true|false, "bgm_style": "ambient"|"upbeat", "bgm_volume": 0.3~0.7, "interval": 1~30, "audio_mode": "each"|"best", "subtitle": false|"blackBg"|"outline"}}

규칙:
- base_mode: 교차편집/자동=auto, 감독모드/메인카메라=director, 화면분할=split, PIP=pip
- bgm: 배경음악/BGM/음악 언급 시 true
- bgm_style: 경쾌/신나는=upbeat, 차분/잔잔/클래식/로파이/chill=ambient (2가지만 지원)
- interval: 카메라 전환 주기(초), 기본 3
- audio_mode: 최적음성/좋은마이크=best, 그외=each
- subtitle: 자막/자동자막/caption/subtitle 언급 시. 검은배경/검은 배경/박스=blackBg, 테두리/외곽선/outline=outline, 그외 자막 언급=blackBg"""}],
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
        # chill은 삭제됨 → ambient로 교정
        if result.get("bgm_style") not in ("ambient", "upbeat"):
            result["bgm_style"] = "ambient"
        result.setdefault("bgm_volume", 0.5)
        result.setdefault("interval", 3.0)
        result.setdefault("audio_mode", "each")
        result.setdefault("subtitle", False)
        return result
    except Exception as e:
        print(f"[studio] AI 프롬프트 파싱 실패, 키워드 매칭으로 대체: {e}", flush=True)
        return _parse_prompt(prompt_text)


# ── 자막 (Subtitle) ────────────────────────────────────

def _transcribe_audio_groq(audio_path: str) -> list[dict]:
    """Groq Whisper API로 음성 인식 (무료, 빠름)

    Returns: [{"start": 0.0, "end": 1.5, "text": "안녕하세요"}, ...]
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        # Supabase secrets_vault에서 런타임 로드 시도
        try:
            sb = _get_supabase()
            row = sb.table("secrets_vault").select("value").eq("key", "GROQ_API_KEY").single().execute()
            if row.data:
                api_key = row.data["value"]
                os.environ["GROQ_API_KEY"] = api_key
                print("[studio] GROQ_API_KEY를 secrets_vault에서 로드 완료", flush=True)
        except Exception as e:
            print(f"[studio] secrets_vault에서 GROQ_API_KEY 로드 실패: {e}", flush=True)
    if not api_key:
        print("[studio] GROQ_API_KEY 없음, 자막 건너뜀", flush=True)
        return []

    import json

    # 오디오 파일 크기 확인 (Groq 25MB 제한)
    audio_file_size = Path(audio_path).stat().st_size
    if audio_file_size > 25 * 1024 * 1024:
        print(f"[studio] 오디오 파일 {audio_file_size / 1024 / 1024:.1f}MB > 25MB 제한, 자막 건너뜀", flush=True)
        return []

    # curl 기반 Groq Whisper API 호출 (urllib.request는 Cloudflare 403 차단됨)
    try:
        result = subprocess.run(
            [
                "curl", "-s",
                "-H", f"Authorization: Bearer {api_key}",
                "-F", "model=whisper-large-v3-turbo",
                "-F", "response_format=verbose_json",
                "-F", "language=ko",
                "-F", "timestamp_granularities[]=segment",
                "-F", f"file=@{audio_path}",
                "https://api.groq.com/openai/v1/audio/transcriptions",
            ],
            capture_output=True, text=True, timeout=120,  # 긴 영상 대비 120초
        )
        if result.returncode != 0:
            print(f"[studio] Groq Whisper curl 실패: {result.stderr}", flush=True)
            return []

        data = json.loads(result.stdout)
        segments = data.get("segments", [])
        print(f"[studio] Whisper 인식 완료: {len(segments)}개 세그먼트", flush=True)
        return [{"start": s["start"], "end": s["end"], "text": s["text"].strip()} for s in segments if s.get("text", "").strip()]
    except subprocess.TimeoutExpired:
        print("[studio] Groq Whisper API 타임아웃 (120초 초과)", flush=True)
        return []
    except Exception as e:
        print(f"[studio] Groq Whisper API 실패: {e}", flush=True)
        return []


def _generate_ass_subtitle(segments: list[dict], style: str, output_path: str):
    """ASS 자막 파일 생성

    style: "blackBg" (검은 반투명 배경) | "outline" (검은 테두리)
    """
    # ASS 스타일 정의
    if style == "outline":
        # 흰색 글씨 + 검은 테두리 (BorderStyle=1: 외곽선+그림자)
        style_line = (
            "Style: Default,Noto Sans CJK KR,28,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
            "-1,0,0,0,100,100,0,0,1,3,1,2,20,20,40,1"
        )
    else:
        # 흰색 글씨 + 검은 반투명 배경 박스 (BorderStyle=3: 불투명 박스)
        style_line = (
            "Style: Default,Noto Sans CJK KR,28,&H00FFFFFF,&H000000FF,&H80000000,&H80000000,"
            "-1,0,0,0,100,100,0,0,3,2,0,2,20,20,40,1"
        )

    # ASS 파일 작성
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1280",
        "PlayResY: 720",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style_line,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for seg in segments:
        start_t = _format_ass_time(seg["start"])
        end_t = _format_ass_time(seg["end"])
        text = seg["text"].replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{start_t},{end_t},Default,,0,0,0,,{text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[studio] ASS 자막 생성: {len(segments)}줄 → {output_path}", flush=True)


def _format_ass_time(seconds: float) -> str:
    """초 → ASS 타임스탬프 (H:MM:SS.CC)"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _add_subtitles_to_video(video_path: str, output_path: str, subtitle_style: str):
    """영상에 자막 오버레이 (음성인식 → ASS 자막 → FFmpeg 번인)"""
    work_dir = Path(video_path).parent
    audio_path = str(work_dir / "subtitle_audio.mp3")
    ass_path = str(work_dir / "subtitle.ass")

    # 1. 오디오 추출
    print("[studio] 자막: 오디오 추출 중", flush=True)
    try:
        _run_ffmpeg(["-i", video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "4",
                     "-ar", "16000", "-ac", "1", audio_path])
    except Exception as e:
        print(f"[studio] 자막: 오디오 추출 실패 (오디오 스트림 없음?): {e}", flush=True)
        return False

    # 오디오 파일 크기 확인
    audio_size = Path(audio_path).stat().st_size if Path(audio_path).exists() else 0
    if audio_size < 1000:
        print(f"[studio] 자막: 오디오 파일 너무 작음 ({audio_size} bytes), 자막 건너뜀", flush=True)
        return False

    # 2. 음성 인식
    print("[studio] 자막: 음성 인식 중 (Groq Whisper)", flush=True)
    segments = _transcribe_audio_groq(audio_path)
    if not segments:
        print("[studio] 자막: 인식된 텍스트 없음, 건너뜀", flush=True)
        return False

    # 3. ASS 자막 파일 생성
    _generate_ass_subtitle(segments, subtitle_style, ass_path)

    # 4. FFmpeg로 자막 번인 (ASS 필터)
    print("[studio] 자막: FFmpeg 번인 중", flush=True)
    # ASS 경로의 특수문자 이스케이프 (FFmpeg filter_complex용)
    escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    try:
        _run_ffmpeg([
            "-i", video_path,
            "-vf", f"ass={escaped_ass}",
            "-c:a", "copy",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            output_path,
        ])
    except Exception as e:
        print(f"[studio] 자막: FFmpeg 번인 실패: {e}", flush=True)
        return False

    # 출력 파일 검증
    if not Path(output_path).exists() or Path(output_path).stat().st_size < 1000:
        print("[studio] 자막: FFmpeg 번인 출력 파일 없거나 너무 작음", flush=True)
        return False

    print("[studio] 자막 적용 완료", flush=True)
    return True


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
