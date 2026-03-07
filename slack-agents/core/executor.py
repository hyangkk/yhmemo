"""
실행 엔진 — 에이전트가 실제 작업을 수행할 수 있게 하는 모듈

지원 도구:
  - shell: 안전한 쉘 명령 실행 (allowlist 기반)
  - http_get/http_post: HTTP 요청
  - file_read/file_write: 파일 읽기/쓰기 (허용 경로 내)
  - supabase_query: Supabase DB 쿼리
  - supabase_upsert: Supabase DB 쓰기

AI가 JSON 도구 호출 배열을 생성하면 순차적으로 실행하고 결과를 모아 반환한다.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from pathlib import Path

import httpx

logger = logging.getLogger("executor")

# ── 안전 설정 ────────────────────────────────────────────

ALLOWED_BASE = Path("/home/user/yhmemo")

# shell에서 허용되는 명령어 (prefix 매칭)
SHELL_ALLOWLIST = [
    "ls", "cat", "head", "tail", "wc",
    "grep", "find", "du", "df",
    "git status", "git log", "git diff", "git branch",
    "git add", "git commit", "git push", "git pull", "git fetch",
    "git checkout", "git switch", "git merge",
    "npm", "npx", "node", "pnpm",
    "python", "pip",
    "curl", "wget",
    "echo", "date", "whoami", "pwd",
    "mkdir", "cp", "mv", "touch",
    "docker", "fly",
    "supabase",
    "vercel",
]

# 절대 차단
SHELL_BLOCKLIST = [
    "rm -rf /", "rm -rf /*",
    "sudo ", "chmod 777",
    "curl | bash", "wget | sh",
    "> /dev/", "dd if=",
    ":(){ ", "fork bomb",
    "mkfs", "fdisk",
    "passwd", "useradd", "userdel",
]

SHELL_TIMEOUT = 60  # seconds
HTTP_TIMEOUT = 30
FILE_MAX_SIZE = 100_000  # 100KB write limit


# ── 도구 정의 (AI에게 알려줄 스키마) ──────────────────────

EXECUTOR_TOOL_SCHEMA = """사용 가능한 실행 도구:

1. shell(command) — 쉘 명령 실행. git, npm, python, curl 등 허용.
   예: {"tool": "shell", "args": {"command": "git status"}}
   예: {"tool": "shell", "args": {"command": "npm run build"}}
   예: {"tool": "shell", "args": {"command": "python scripts/check_db.py"}}

2. http_get(url) — HTTP GET 요청 (API 호출 등)
   예: {"tool": "http_get", "args": {"url": "https://api.example.com/health"}}

3. http_post(url, body, headers) — HTTP POST 요청
   예: {"tool": "http_post", "args": {"url": "https://api.example.com/data", "body": {"key": "value"}}}

4. file_read(path) — 파일 읽기 (/home/user/yhmemo 하위만)
   예: {"tool": "file_read", "args": {"path": "slack-agents/core/tools.py"}}

5. file_write(path, content) — 파일 쓰기 (/home/user/yhmemo 하위만, 100KB 제한)
   예: {"tool": "file_write", "args": {"path": "slack-agents/data/report.json", "content": "{...}"}}

6. supabase_query(table, select, filters, limit) — Supabase 테이블 조회
   예: {"tool": "supabase_query", "args": {"table": "collected_items", "select": "*", "filters": {"source_type": "rss"}, "limit": 10}}

7. supabase_upsert(table, data) — Supabase 테이블에 데이터 삽입/업데이트
   예: {"tool": "supabase_upsert", "args": {"table": "agent_tasks", "data": {"from_agent": "proactive", "task_type": "report"}}}

응답 형식:
{"steps": [
  {"description": "무엇을 하는지 설명", "tool": "도구명", "args": {...}},
  ...
]}

규칙:
- 한 번에 최대 10단계까지
- 각 단계는 이전 단계 결과에 의존 가능 (순차 실행됨)
- 설명은 한국어로, 왜 이 작업이 필요한지 포함
- rm, sudo, chmod 777 등 위험한 명령은 차단됨
- 파일 쓰기는 /home/user/yhmemo 하위만 가능"""


# ── 도구 실행 함수들 ─────────────────────────────────────

def _validate_shell_command(command: str) -> tuple[bool, str]:
    """쉘 명령이 안전한지 검증"""
    cmd_lower = command.strip().lower()

    # blocklist 체크
    for blocked in SHELL_BLOCKLIST:
        if blocked.lower() in cmd_lower:
            return False, f"차단된 패턴: {blocked}"

    # allowlist 체크 — 첫 번째 토큰이 허용 목록에 있어야 함
    first_token = cmd_lower.split()[0] if cmd_lower.split() else ""

    # pipe/chain 명령의 경우 각 부분 검증
    parts = re.split(r'\s*[|;&]\s*', cmd_lower)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        part_cmd = part.split()[0] if part.split() else ""
        allowed = any(part_cmd.startswith(a.split()[0]) for a in SHELL_ALLOWLIST)
        if not allowed:
            return False, f"허용되지 않은 명령: {part_cmd}"

    return True, ""


async def _exec_shell(command: str, cwd: str | None = None) -> str:
    """안전한 쉘 명령 실행"""
    ok, reason = _validate_shell_command(command)
    if not ok:
        return f"[차단] {reason}"

    work_dir = cwd or str(ALLOWED_BASE)
    # cwd 검증
    real_cwd = os.path.realpath(work_dir)
    real_base = os.path.realpath(str(ALLOWED_BASE))
    if not (real_cwd == real_base or real_cwd.startswith(real_base + os.sep)):
        return f"[차단] 작업 디렉토리가 허용 범위 밖: {work_dir}"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SHELL_TIMEOUT)

        out = stdout.decode("utf-8", errors="replace")[:5000]
        err = stderr.decode("utf-8", errors="replace")[:2000]

        result = ""
        if out:
            result += out
        if err:
            result += f"\n[stderr] {err}"
        if proc.returncode != 0:
            result += f"\n[exit code: {proc.returncode}]"

        return result.strip() or "(빈 출력)"

    except asyncio.TimeoutError:
        return f"[타임아웃] {SHELL_TIMEOUT}초 초과"
    except Exception as e:
        return f"[오류] {str(e)[:300]}"


async def _exec_http_get(url: str) -> str:
    """HTTP GET 요청"""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            return f"[{resp.status_code}] {resp.text[:3000]}"
    except Exception as e:
        return f"[오류] {str(e)[:300]}"


async def _exec_http_post(url: str, body: dict | None = None, headers: dict | None = None) -> str:
    """HTTP POST 요청"""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = await client.post(url, json=body or {}, headers=headers or {})
            return f"[{resp.status_code}] {resp.text[:3000]}"
    except Exception as e:
        return f"[오류] {str(e)[:300]}"


def _validate_file_path(path: str) -> tuple[bool, Path]:
    """파일 경로가 안전한지 검증. 상대 경로는 ALLOWED_BASE 기준."""
    try:
        p = Path(path)
        if not p.is_absolute():
            p = ALLOWED_BASE / p
        real = p.resolve()
        if not str(real).startswith(str(ALLOWED_BASE.resolve())):
            return False, real
        return True, real
    except Exception:
        return False, Path(path)


async def _exec_file_read(path: str) -> str:
    """파일 읽기"""
    ok, real_path = _validate_file_path(path)
    if not ok:
        return f"[차단] 허용 범위 밖 경로: {path}"
    try:
        content = real_path.read_text(encoding="utf-8", errors="replace")
        if len(content) > 10_000:
            return content[:10_000] + f"\n... (총 {len(content)} bytes, 잘림)"
        return content or "(빈 파일)"
    except FileNotFoundError:
        return f"[오류] 파일 없음: {path}"
    except Exception as e:
        return f"[오류] {str(e)[:300]}"


async def _exec_file_write(path: str, content: str) -> str:
    """파일 쓰기"""
    ok, real_path = _validate_file_path(path)
    if not ok:
        return f"[차단] 허용 범위 밖 경로: {path}"

    if len(content) > FILE_MAX_SIZE:
        return f"[차단] 파일 크기 초과 ({len(content)} > {FILE_MAX_SIZE})"

    # .env 파일 쓰기 차단
    if real_path.name.startswith(".env"):
        return "[차단] .env 파일 직접 수정 불가"

    try:
        real_path.parent.mkdir(parents=True, exist_ok=True)
        real_path.write_text(content, encoding="utf-8")
        return f"✅ 파일 저장 완료: {real_path.relative_to(ALLOWED_BASE)} ({len(content)} bytes)"
    except Exception as e:
        return f"[오류] {str(e)[:300]}"


async def _exec_supabase_query(
    supabase_client,
    table: str,
    select: str = "*",
    filters: dict | None = None,
    limit: int = 20,
) -> str:
    """Supabase 테이블 조회"""
    if not supabase_client:
        return "[오류] Supabase 클라이언트 없음"
    try:
        query = supabase_client.table(table).select(select)
        if filters:
            for k, v in filters.items():
                query = query.eq(k, v)
        query = query.limit(limit)
        result = query.execute()
        data = result.data if result.data else []
        return json.dumps(data[:limit], ensure_ascii=False, default=str)[:5000]
    except Exception as e:
        return f"[오류] {str(e)[:300]}"


async def _exec_supabase_upsert(supabase_client, table: str, data: dict | list) -> str:
    """Supabase 테이블 upsert"""
    if not supabase_client:
        return "[오류] Supabase 클라이언트 없음"

    # 위험한 테이블 보호
    protected = {"auth", "users", "curation_preferences"}
    if table in protected:
        return f"[차단] 보호된 테이블: {table}"

    try:
        records = data if isinstance(data, list) else [data]
        result = supabase_client.table(table).upsert(records).execute()
        count = len(result.data) if result.data else 0
        return f"✅ {table}에 {count}건 upsert 완료"
    except Exception as e:
        return f"[오류] {str(e)[:300]}"


# ── 메인 실행 엔진 ────────────────────────────────────────

async def execute_plan(
    steps: list[dict],
    supabase_client=None,
    cwd: str | None = None,
) -> list[dict]:
    """AI가 생성한 실행 계획을 순차적으로 실행.

    Parameters
    ----------
    steps : list[dict]
        각 항목은 {"description": str, "tool": str, "args": dict}
    supabase_client : optional
        Supabase 클라이언트 (DB 작업용)
    cwd : optional
        shell 작업 디렉토리

    Returns
    -------
    list[dict]
        각 항목은 {"step": int, "description": str, "tool": str, "result": str, "ok": bool}
    """
    results = []
    max_steps = 10

    for i, step in enumerate(steps[:max_steps]):
        tool = step.get("tool", "")
        args = step.get("args", {})
        desc = step.get("description", f"Step {i+1}")

        logger.info(f"[executor] Step {i+1}/{len(steps)}: {desc} ({tool})")

        try:
            if tool == "shell":
                result = await _exec_shell(args.get("command", ""), cwd=cwd)
            elif tool == "http_get":
                result = await _exec_http_get(args.get("url", ""))
            elif tool == "http_post":
                result = await _exec_http_post(
                    args.get("url", ""),
                    body=args.get("body"),
                    headers=args.get("headers"),
                )
            elif tool == "file_read":
                result = await _exec_file_read(args.get("path", ""))
            elif tool == "file_write":
                result = await _exec_file_write(args.get("path", ""), args.get("content", ""))
            elif tool == "supabase_query":
                result = await _exec_supabase_query(
                    supabase_client,
                    args.get("table", ""),
                    select=args.get("select", "*"),
                    filters=args.get("filters"),
                    limit=args.get("limit", 20),
                )
            elif tool == "supabase_upsert":
                result = await _exec_supabase_upsert(
                    supabase_client,
                    args.get("table", ""),
                    args.get("data", {}),
                )
            else:
                result = f"[오류] 알 수 없는 도구: {tool}"

            ok = not result.startswith("[차단]") and not result.startswith("[오류]")
            results.append({
                "step": i + 1,
                "description": desc,
                "tool": tool,
                "result": result[:2000],
                "ok": ok,
            })

            logger.info(f"[executor] Step {i+1} {'✅' if ok else '❌'}: {result[:100]}")

        except Exception as e:
            results.append({
                "step": i + 1,
                "description": desc,
                "tool": tool,
                "result": f"[예외] {str(e)[:300]}",
                "ok": False,
            })
            logger.error(f"[executor] Step {i+1} exception: {e}")

    return results


def format_execution_results(results: list[dict]) -> str:
    """실행 결과를 사람이 읽을 수 있는 형태로 포매팅"""
    lines = []
    success_count = sum(1 for r in results if r["ok"])
    total = len(results)

    lines.append(f"실행 결과: {success_count}/{total} 성공")
    lines.append("")

    for r in results:
        icon = "✅" if r["ok"] else "❌"
        lines.append(f"{icon} Step {r['step']}: {r['description']}")
        # 결과는 200자로 요약
        result_preview = r["result"][:200]
        if len(r["result"]) > 200:
            result_preview += "..."
        lines.append(f"   → {result_preview}")
        lines.append("")

    return "\n".join(lines)
