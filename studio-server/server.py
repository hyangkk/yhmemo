"""
멀티캠 스튜디오 - 영상 처리 서버
Fly.io 상시 서버에서 동작. FFmpeg로 다중 카메라 영상을 자동 편집합니다.
"""

import asyncio
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client

app = FastAPI(title="멀티캠 스튜디오 서버")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
DATA_DIR = Path("/app/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


class EditRequest(BaseModel):
    session_id: str
    mode: str = "auto"  # auto, split, pip (picture-in-picture)


class EditMode:
    """편집 모드 정의"""
    AUTO = "auto"        # 자동 컷편집 (일정 간격으로 카메라 전환)
    SPLIT = "split"      # 화면 분할 (2분할, 3분할 등)
    PIP = "pip"          # PIP (메인 + 작은 화면)


@app.get("/health")
async def health():
    return {"status": "ok", "ffmpeg": _check_ffmpeg()}


@app.post("/edit")
async def start_edit(req: EditRequest, background_tasks: BackgroundTasks):
    """영상 편집 작업 시작"""
    sb = get_supabase()

    # 세션 정보 확인
    session = sb.table("studio_sessions").select("*").eq("id", req.session_id).single().execute()
    if not session.data:
        raise HTTPException(404, "세션을 찾을 수 없습니다")

    # 클립 목록
    clips = sb.table("studio_clips").select("*").eq("session_id", req.session_id).execute()
    if not clips.data or len(clips.data) < 1:
        raise HTTPException(400, "업로드된 클립이 없습니다")

    # 결과 레코드 생성
    result = sb.table("studio_results").insert({
        "session_id": req.session_id,
        "storage_path": "",
        "status": "processing",
    }).execute()

    result_id = result.data[0]["id"]

    # 세션 상태를 editing으로 변경
    sb.table("studio_sessions").update({
        "status": "editing"
    }).eq("id", req.session_id).execute()

    # 백그라운드에서 편집 실행
    background_tasks.add_task(
        process_edit,
        req.session_id,
        result_id,
        clips.data,
        req.mode,
    )

    return {"result_id": result_id, "status": "processing"}


@app.get("/edit/{result_id}")
async def get_edit_status(result_id: str):
    """편집 결과 상태 조회"""
    sb = get_supabase()
    result = sb.table("studio_results").select("*").eq("id", result_id).single().execute()
    if not result.data:
        raise HTTPException(404, "결과를 찾을 수 없습니다")
    return result.data


async def process_edit(
    session_id: str,
    result_id: str,
    clips: list[dict],
    mode: str,
):
    """FFmpeg로 영상 편집 실행"""
    sb = get_supabase()
    work_dir = DATA_DIR / session_id
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. 클립 다운로드
        local_files = []
        async with httpx.AsyncClient() as client:
            for clip in sorted(clips, key=lambda c: c.get("device_id", "")):
                storage_path = clip["storage_path"]
                # Supabase Storage에서 공개 URL
                url = f"{SUPABASE_URL}/storage/v1/object/public/studio-clips/{storage_path}"
                resp = await client.get(url)
                if resp.status_code != 200:
                    raise Exception(f"클립 다운로드 실패: {storage_path}")

                local_path = work_dir / f"clip_{clip['id']}.webm"
                local_path.write_bytes(resp.content)
                local_files.append(str(local_path))

        if not local_files:
            raise Exception("다운로드된 클립이 없습니다")

        # 2. FFmpeg로 편집
        output_path = work_dir / f"result_{result_id}.mp4"

        if len(local_files) == 1:
            # 카메라 1대 → 그대로 mp4 변환
            _run_ffmpeg([
                "-i", local_files[0],
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(output_path),
            ])
        elif mode == EditMode.SPLIT:
            _edit_split_screen(local_files, str(output_path))
        elif mode == EditMode.PIP:
            _edit_pip(local_files, str(output_path))
        else:
            # auto: 자동 컷편집 (일정 간격으로 카메라 전환)
            _edit_auto_cut(local_files, str(output_path))

        # 3. 결과물 업로드
        result_storage_path = f"{session_id}/result_{result_id}.mp4"
        with open(output_path, "rb") as f:
            sb.storage.from_("studio-clips").upload(
                result_storage_path,
                f.read(),
                file_options={"content-type": "video/mp4"},
            )

        # 4. 결과 업데이트
        file_size = output_path.stat().st_size
        duration = _get_duration(str(output_path))

        sb.table("studio_results").update({
            "storage_path": result_storage_path,
            "duration_ms": int(duration * 1000) if duration else None,
            "status": "done",
        }).eq("id", result_id).execute()

        sb.table("studio_sessions").update({
            "status": "done"
        }).eq("id", session_id).execute()

    except Exception as e:
        print(f"편집 오류: {e}")
        sb.table("studio_results").update({
            "status": "error",
        }).eq("id", result_id).execute()

        sb.table("studio_sessions").update({
            "status": "done"  # 에러여도 세션은 done으로
        }).eq("id", session_id).execute()

    finally:
        # 임시 파일 정리
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)


def _run_ffmpeg(args: list[str]):
    """FFmpeg 실행"""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise Exception(f"FFmpeg 오류: {result.stderr}")


def _get_duration(path: str) -> float | None:
    """영상 길이(초) 조회"""
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
    """
    자동 컷편집: 일정 간격(기본 5초)마다 카메라를 순환하며 전환.
    각 클립에서 해당 구간을 잘라 concat으로 연결.
    """
    # 각 클립의 길이 확인
    durations = []
    for f in files:
        d = _get_duration(f)
        durations.append(d if d else 0)

    min_duration = min(durations) if durations else 0
    if min_duration <= 0:
        # 길이를 못 구하면 단순 concat
        _simple_concat(files, output)
        return

    # 세그먼트 생성
    n_cameras = len(files)
    segments = []
    t = 0.0

    while t < min_duration:
        cam_idx = len(segments) % n_cameras
        end_t = min(t + interval_sec, min_duration)
        segments.append((cam_idx, t, end_t))
        t = end_t

    if not segments:
        _simple_concat(files, output)
        return

    # FFmpeg complex filter로 세그먼트 연결
    filter_parts = []
    concat_inputs = []

    for i, (cam_idx, start, end) in enumerate(segments):
        dur = end - start
        filter_parts.append(
            f"[{cam_idx}:v]trim=start={start:.3f}:duration={dur:.3f},setpts=PTS-STARTPTS[v{i}];"
        )
        filter_parts.append(
            f"[{cam_idx}:a]atrim=start={start:.3f}:duration={dur:.3f},asetpts=PTS-STARTPTS[a{i}];"
        )
        concat_inputs.append(f"[v{i}][a{i}]")

    filter_complex = "".join(filter_parts)
    filter_complex += "".join(concat_inputs)
    filter_complex += f"concat=n={len(segments)}:v=1:a=1[outv][outa]"

    input_args = []
    for f in files:
        input_args.extend(["-i", f])

    _run_ffmpeg(
        input_args +
        ["-filter_complex", filter_complex,
         "-map", "[outv]", "-map", "[outa]",
         "-c:v", "libx264", "-preset", "fast",
         "-c:a", "aac",
         "-movflags", "+faststart",
         output]
    )


def _edit_split_screen(files: list[str], output: str):
    """화면 분할 편집"""
    n = len(files)
    input_args = []
    for f in files:
        input_args.extend(["-i", f])

    if n == 2:
        # 2분할 (좌우)
        filter_complex = (
            "[0:v]scale=640:360[l];"
            "[1:v]scale=640:360[r];"
            "[l][r]hstack=inputs=2[outv]"
        )
    elif n == 3:
        # 3분할 (상단1 + 하단2)
        filter_complex = (
            "[0:v]scale=1280:360[top];"
            "[1:v]scale=640:360[bl];"
            "[2:v]scale=640:360[br];"
            "[bl][br]hstack=inputs=2[bottom];"
            "[top][bottom]vstack=inputs=2[outv]"
        )
    else:
        # 4분할 (2x2 그리드)
        filter_complex = (
            "[0:v]scale=640:360[tl];"
            "[1:v]scale=640:360[tr];"
            f"{'[2:v]scale=640:360[bl];' if n > 2 else 'color=black:640x360[bl];'}"
            f"{'[3:v]scale=640:360[br];' if n > 3 else 'color=black:640x360[br];'}"
            "[tl][tr]hstack=inputs=2[top];"
            "[bl][br]hstack=inputs=2[bottom];"
            "[top][bottom]vstack=inputs=2[outv]"
        )

    _run_ffmpeg(
        input_args +
        ["-filter_complex", filter_complex,
         "-map", "[outv]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "fast",
         "-c:a", "aac",
         "-movflags", "+faststart",
         "-shortest",
         output]
    )


def _edit_pip(files: list[str], output: str):
    """PIP (Picture-in-Picture) 편집: 첫 번째 카메라가 메인, 나머지는 작은 화면"""
    input_args = []
    for f in files:
        input_args.extend(["-i", f])

    # 메인 화면 + 우측 하단에 작은 화면들
    overlay_parts = ["[0:v]scale=1280:720[main]"]
    current = "[main]"

    for i in range(1, len(files)):
        small_label = f"s{i}"
        overlay_parts.append(f"[{i}:v]scale=240:135[{small_label}]")
        out_label = f"[pip{i}]" if i < len(files) - 1 else "[outv]"
        # 우측 하단부터 위로 쌓기
        y_offset = 720 - 135 * i - 10 * i
        overlay_parts.append(
            f"{current}[{small_label}]overlay=W-w-10:{y_offset}{out_label}"
        )
        current = f"[pip{i}]"

    filter_complex = ";".join(overlay_parts)

    _run_ffmpeg(
        input_args +
        ["-filter_complex", filter_complex,
         "-map", "[outv]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "fast",
         "-c:a", "aac",
         "-movflags", "+faststart",
         "-shortest",
         output]
    )


def _simple_concat(files: list[str], output: str):
    """단순 연결 (폴백)"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        for path in files:
            f.write(f"file '{path}'\n")
        list_path = f.name

    try:
        _run_ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac",
            "-movflags", "+faststart",
            output,
        ])
    finally:
        os.unlink(list_path)


def _check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
