"""
DevRunner - Claude Code CLI 실행 모듈

Claude Code CLI를 비동기로 호출하여 개발 작업을 수행하고
결과를 요약하여 반환한다.
"""

import asyncio
import logging
import os

from core.security import sanitize_dev_prompt, validate_cwd

logger = logging.getLogger("orchestrator.dev_runner")

# 자율 실행 지침 (NL handler와 command queue 모두 사용)
DEV_INSTRUCTIONS = """

[자율 실행 지침]
- 권한 요청하지 말고 바로 실행하세요. 모든 파일 쓰기/수정 권한이 있습니다.
- 작업 완료 후 git add, git commit, git push까지 자동으로 하세요.
- 커밋 메시지는 한국어로, 변경 내용을 요약하세요.
- git push는 현재 브랜치로 하세요.
- 사용자에게 승인을 묻지 마세요. 모든 것이 사전 승인됨.
- 작업 디렉토리: /home/user/yhmemo
- 결과를 간결하게 요약하세요 (무엇을 만들었는지, 어떤 파일, 다음 단계)."""


class DevRunner:
    """Claude Code CLI를 통해 개발 작업을 실행하는 러너"""

    def __init__(self, summarizer=None, timeout: int = 300):
        """
        Args:
            summarizer: ai_think 메서드를 가진 객체 (curator 등). 결과 요약에 사용.
            timeout: CLI 실행 타임아웃 (초). 기본 300초(5분).
        """
        self.summarizer = summarizer
        self.timeout = timeout

    def _build_env(self) -> dict:
        """Claude Code CLI 실행을 위한 환경변수 구성"""
        clean_env = {k: v for k, v in os.environ.items()}
        clean_env["CLAUDECODE"] = ""
        if "ANTHROPIC_API_KEY" not in clean_env:
            from dotenv import dotenv_values
            env_vals = dotenv_values()
            if "ANTHROPIC_API_KEY" in env_vals:
                clean_env["ANTHROPIC_API_KEY"] = env_vals["ANTHROPIC_API_KEY"]
        return clean_env

    def build_prompt(self, task: str, thread_context: str = "") -> str:
        """실행 프롬프트 조립 (스레드 맥락 + 작업 + 자율실행 지침)"""
        full_prompt = task
        if thread_context:
            full_prompt = f"[이전 대화 맥락]\n{thread_context}\n\n[요청]\n{task}"
        full_prompt += DEV_INSTRUCTIONS
        return full_prompt

    async def run(self, prompt: str) -> dict:
        """
        Claude Code CLI를 실행하고 결과를 반환한다.

        Returns:
            dict with keys:
                success (bool), output (str), error (str), timed_out (bool)
        """
        # Security: sanitize prompt before passing to CLI
        prompt, sec_warnings = sanitize_dev_prompt(prompt)
        if not prompt:
            warn_msg = f"보안 차단: {'; '.join(sec_warnings)}"
            logger.warning(f"[dev_runner] Prompt blocked: {sec_warnings}")
            return {"success": False, "output": "", "error": warn_msg, "timed_out": False}
        if sec_warnings:
            logger.warning(f"[dev_runner] Security warnings: {sec_warnings}")

        # Security: validate working directory
        dev_cwd = "/home/user/yhmemo"
        if not validate_cwd(dev_cwd):
            return {"success": False, "output": "", "error": "보안 차단: invalid cwd", "timed_out": False}

        clean_env = self._build_env()
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                "--output-format", "text",
                "--permission-mode", "acceptEdits",
                cwd=dev_cwd,
                env=clean_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout
            )
            output = stdout.decode("utf-8", errors="replace").strip()
            err_output = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0 and output:
                return {"success": True, "output": output, "error": "", "timed_out": False}
            else:
                error_msg = err_output or output or "알 수 없는 오류"
                return {"success": False, "output": output, "error": error_msg, "timed_out": False}
        except asyncio.TimeoutError:
            return {"success": False, "output": "", "error": "타임아웃", "timed_out": True}

    async def summarize_output(self, output: str, max_len: int = 3000) -> str:
        """긴 출력을 요약한다. summarizer가 없으면 앞부분만 잘라 반환."""
        if len(output) <= max_len:
            return output
        if self.summarizer:
            summary = await self.summarizer.ai_think(
                system_prompt="아래 Claude Code 실행 결과를 슬랙 메시지로 요약하세요. 무엇을 만들었는지, 어떤 파일을 생성/수정했는지, 다음 단계는 무엇인지 핵심만. 최대 1500자.",
                user_prompt=output,
            )
            return summary or output[:1500]
        return output[:1500]
