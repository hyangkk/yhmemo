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
    build_sha = os.environ.get("BUILD_SHA", "dev")
    return {"status": "ok", "service": "studio", "ffmpeg": ffmpeg_ok, "build_sha": build_sha}


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

    total_steps = 4

    try:
        # 1. 클립 다운로드
        _update_edit_step(sb, result_id, 1, total_steps, "클립 다운로드 중")
        supabase_url = os.environ["SUPABASE_URL"]
        local_files = []
        async with httpx.AsyncClient(timeout=120) as client:
            for clip in sorted(clips, key=lambda c: c.get("device_id", "")):
                url = f"{supabase_url}/storage/v1/object/public/studio-clips/{clip['storage_path']}"
                resp = await client.get(url)
                if resp.status_code != 200:
                    raise Exception(f"클립 다운로드 실패: {clip['storage_path']}")
                local_path = work_dir / f"clip_{clip['id']}.webm"
                local_path.write_bytes(resp.content)
                local_files.append(str(local_path))

        if not local_files:
            raise Exception("다운로드된 클립이 없습니다")

        # 2. 영상 분석
        _update_edit_step(sb, result_id, 2, total_steps, "영상 분석 중")

        # 3. FFmpeg 편집
        _update_edit_step(sb, result_id, 3, total_steps, "영상 편집 중")
        output_path = work_dir / f"result_{result_id}.mp4"

        if len(local_files) == 1:
            _run_ffmpeg(["-i", local_files[0]] + IOS_VIDEO_OPTS + IOS_AUDIO_OPTS +
                        IOS_CONTAINER_OPTS + [str(output_path)])
        elif mode == "split":
            _edit_split_screen(local_files, str(output_path))
        elif mode == "pip":
            _edit_pip(local_files, str(output_path))
        else:
            _edit_auto_cut(local_files, str(output_path))

        # 4. 결과 업로드
        _update_edit_step(sb, result_id, 4, total_steps, "결과 업로드 중")
        result_storage_path = f"{session_id}/result_{result_id}.mp4"
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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise Exception(f"FFmpeg 오류: {result.stderr}")


# iOS 호환 인코딩 옵션 (H.264 Baseline/Main + yuv420p)
IOS_VIDEO_OPTS = [
    "-c:v", "libx264",
    "-profile:v", "main",
    "-level", "4.0",
    "-pix_fmt", "yuv420p",
    "-preset", "fast",
]
IOS_AUDIO_OPTS = ["-c:a", "aac", "-b:a", "128k"]
IOS_CONTAINER_OPTS = ["-movflags", "+faststart"]


def _get_duration(path: str) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
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


def _edit_auto_cut(files: list[str], output: str, interval: float = 3.0):
    """자동 컷편집: 3초 간격으로 카메라 전환, 오디오 분석 가능 시 스마트 전환"""
    durations = [_get_duration(f) or 0 for f in files]
    min_dur = min(durations) if durations else 0
    if min_dur <= 0:
        _simple_concat(files, output)
        return

    n = len(files)
    total_secs = int(min_dur)

    # 오디오 분석 시도
    audio_ok = False
    all_levels: list[list[float]] = []
    for f in files:
        levels = _analyze_audio_levels(f)
        all_levels.append(levels)
        print(f"[studio] 오디오 분석: {f} → {len(levels)}개 샘플", flush=True)

    # 오디오 데이터가 충분한지 확인 (최소 3초 이상)
    min_samples = min(len(l) for l in all_levels)
    if min_samples >= 3:
        audio_ok = True
        print(f"[studio] 오디오 분석 성공: {min_samples}개 샘플, 스마트 전환 사용", flush=True)
    else:
        print(f"[studio] 오디오 분석 부족({min_samples}개 샘플), 라운드로빈 전환 사용", flush=True)

    if audio_ok:
        # 오디오 기반 세그먼트 생성
        max_len = min(total_secs, min_samples)
        for i in range(n):
            all_levels[i] = all_levels[i][:max_len]

        # 초별로 가장 소리가 큰 카메라 선택
        best_cam_per_sec = []
        for sec in range(max_len):
            best = 0
            best_level = all_levels[0][sec]
            for cam in range(1, n):
                if all_levels[cam][sec] > best_level:
                    best_level = all_levels[cam][sec]
                    best = cam
            best_cam_per_sec.append(best)

        segments = []
        seg_start = 0.0
        current_cam = best_cam_per_sec[0]

        for sec in range(1, max_len):
            elapsed = sec - seg_start
            preferred_cam = best_cam_per_sec[sec]

            should_switch = preferred_cam != current_cam and elapsed >= interval
            force_switch = elapsed >= interval and n > 1

            if should_switch or force_switch:
                segments.append((current_cam, seg_start, float(sec)))
                seg_start = float(sec)
                if force_switch and preferred_cam == current_cam:
                    current_cam = (current_cam + 1) % n
                else:
                    current_cam = preferred_cam

        if seg_start < min_dur:
            segments.append((current_cam, seg_start, min_dur))
    else:
        # 오디오 분석 실패 → 고정 간격 라운드로빈
        segments = _build_round_robin_segments(n, min_dur, interval)

    if not segments:
        _simple_concat(files, output)
        return

    print(f"[studio] 자동 편집: {len(segments)}개 세그먼트 (카메라 {n}대, 총 {min_dur:.1f}초)", flush=True)
    for i, (cam, s, e) in enumerate(segments):
        print(f"[studio]   세그먼트 {i}: 카메라{cam} {s:.1f}~{e:.1f}초", flush=True)

    parts = []
    concat_in = []
    for i, (cam, start, end) in enumerate(segments):
        dur = end - start
        parts.append(f"[{cam}:v]trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS[v{i}];")
        parts.append(f"[{cam}:a]atrim=start={start:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS[a{i}];")
        concat_in.append(f"[v{i}][a{i}]")

    fc = "".join(parts) + "".join(concat_in) + f"concat=n={len(segments)}:v=1:a=1[outv][outa]"
    inp = []
    for f in files:
        inp.extend(["-i", f])

    _run_ffmpeg(inp + ["-filter_complex", fc, "-map", "[outv]", "-map", "[outa]"] +
                IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + [output])


def _edit_split_screen(files: list[str], output: str):
    """화면 분할"""
    n = len(files)
    inp = []
    for f in files:
        inp.extend(["-i", f])

    if n == 2:
        fc = "[0:v]scale=640:360[l];[1:v]scale=640:360[r];[l][r]hstack=inputs=2[outv]"
    elif n == 3:
        fc = ("[0:v]scale=1280:360[top];[1:v]scale=640:360[bl];[2:v]scale=640:360[br];"
              "[bl][br]hstack=inputs=2[bottom];[top][bottom]vstack=inputs=2[outv]")
    else:
        fc = ("[0:v]scale=640:360[tl];[1:v]scale=640:360[tr];"
              f"{'[2:v]scale=640:360[bl];' if n > 2 else 'color=black:640x360[bl];'}"
              f"{'[3:v]scale=640:360[br];' if n > 3 else 'color=black:640x360[br];'}"
              "[tl][tr]hstack=inputs=2[top];[bl][br]hstack=inputs=2[bottom];"
              "[top][bottom]vstack=inputs=2[outv]")

    _run_ffmpeg(inp + ["-filter_complex", fc, "-map", "[outv]", "-map", "0:a?"] +
                IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + ["-shortest", output])


def _edit_pip(files: list[str], output: str):
    """PIP (Picture-in-Picture)"""
    inp = []
    for f in files:
        inp.extend(["-i", f])

    parts = ["[0:v]scale=1280:720[main]"]
    cur = "[main]"
    for i in range(1, len(files)):
        sl = f"s{i}"
        parts.append(f"[{i}:v]scale=240:135[{sl}]")
        out = f"[pip{i}]" if i < len(files) - 1 else "[outv]"
        y = 720 - 135 * i - 10 * i
        parts.append(f"{cur}[{sl}]overlay=W-w-10:{y}{out}")
        cur = f"[pip{i}]"

    _run_ffmpeg(inp + ["-filter_complex", ";".join(parts), "-map", "[outv]", "-map", "0:a?"] +
                IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + ["-shortest", output])


def _simple_concat(files: list[str], output: str):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for p in files:
            f.write(f"file '{p}'\n")
        list_path = f.name
    try:
        _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", list_path] +
                    IOS_VIDEO_OPTS + IOS_AUDIO_OPTS + IOS_CONTAINER_OPTS + [output])
    finally:
        os.unlink(list_path)


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

                for sess in sessions.data:
                    sid = sess["id"]
                    # 이미 처리 중인 result가 있는지 확인
                    existing = sb.table("studio_results").select("id,status").eq("session_id", sid).execute()
                    if existing.data and any(r["status"] == "processing" for r in existing.data):
                        continue  # 이미 처리 중
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

                    # 편집 시작
                    print(f"[studio] 세션 {sid}: 편집 시작 ({len(clips.data)}개 클립)", flush=True)
                    result = sb.table("studio_results").insert({
                        "session_id": sid,
                        "storage_path": "",
                        "status": "processing",
                    }).execute()
                    result_id = result.data[0]["id"]

                    # 동기적으로 편집 실행 (폴링 스레드에서)
                    asyncio.run(process_edit(sid, result_id, clips.data, "auto"))
                    print(f"[studio] 세션 {sid}: 편집 완료", flush=True)

            except Exception as e:
                print(f"[studio] 폴링 오류: {e}", flush=True)
                logger.error(f"[studio] 폴링 오류: {e}")

    t_server = threading.Thread(target=_run_server, daemon=True)
    t_server.start()
    t_polling = threading.Thread(target=_run_polling, daemon=True)
    t_polling.start()
    print(f"[studio] 스레드 시작됨 (server={t_server.is_alive()}, polling={t_polling.is_alive()})", flush=True)
    return t_server
