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
    return {"status": "ok", "service": "studio", "ffmpeg": ffmpeg_ok}


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


async def process_edit(session_id: str, result_id: str, clips: list[dict], mode: str):
    """FFmpeg로 영상 편집"""
    sb = _get_supabase()
    work_dir = DATA_DIR / session_id
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 클립 다운로드
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

        # 2. FFmpeg 편집
        output_path = work_dir / f"result_{result_id}.mp4"

        if len(local_files) == 1:
            _run_ffmpeg(["-i", local_files[0], "-c:v", "libx264", "-preset", "fast",
                         "-c:a", "aac", "-movflags", "+faststart", str(output_path)])
        elif mode == "split":
            _edit_split_screen(local_files, str(output_path))
        elif mode == "pip":
            _edit_pip(local_files, str(output_path))
        else:
            _edit_auto_cut(local_files, str(output_path))

        # 3. 업로드
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


def _edit_auto_cut(files: list[str], output: str, interval_sec: float = 5.0):
    """자동 컷편집: 일정 간격마다 카메라 전환"""
    durations = [_get_duration(f) or 0 for f in files]
    min_dur = min(durations) if durations else 0
    if min_dur <= 0:
        _simple_concat(files, output)
        return

    n = len(files)
    segments = []
    t = 0.0
    while t < min_dur:
        cam = len(segments) % n
        end = min(t + interval_sec, min_dur)
        segments.append((cam, t, end))
        t = end

    if not segments:
        _simple_concat(files, output)
        return

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

    _run_ffmpeg(inp + ["-filter_complex", fc, "-map", "[outv]", "-map", "[outa]",
                       "-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
                       "-movflags", "+faststart", output])


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

    _run_ffmpeg(inp + ["-filter_complex", fc, "-map", "[outv]", "-map", "0:a?",
                       "-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
                       "-movflags", "+faststart", "-shortest", output])


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

    _run_ffmpeg(inp + ["-filter_complex", ";".join(parts), "-map", "[outv]", "-map", "0:a?",
                       "-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
                       "-movflags", "+faststart", "-shortest", output])


def _simple_concat(files: list[str], output: str):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for p in files:
            f.write(f"file '{p}'\n")
        list_path = f.name
    try:
        _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", list_path,
                     "-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
                     "-movflags", "+faststart", output])
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
    """별도 스레드에서 스튜디오 API 서버 시작"""
    def _run():
        logger.info(f"[studio] API 서버 시작 (port={port})")
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
