"""
DevRunner - Claude Code CLI 실행 모듈

NL 핸들러와 커맨드 큐에서 공통으로 사용하는
Claude Code CLI 실행 로직을 캡슐화.
"""

import asyncio
import logging
import os

logger = logging.getLogger("orchestrator.dev_runner")


class DevRunner:
    """Claude Code CLI를 통한 개발 작업 실행"""

    AUTONOMOUS_INSTRUCTIONS = """

[자율 실행 지침]
- 권한 요청하지 말고 바로 실행하세요. 모든 파일 쓰기/수정 권한이 있습니다.
- 작업 완료 후 git add, git commit, git push까지 자동으로 하세요.
- 커밋 메시지는 한국어로, 변경 내용을 요약하세요.
- git push는 현재 브랜치로 하세요.
- 사용자에게 승인을 묻지 마세요. 모든 것이 사전 승인됨.
- 작업 디렉토리: /home/user/yhmemo
- 결과를 간결하게 요약하세요 (무엇을 만들었는지, 어떤 파일, 다음 단계)."""

    def __init__(self, curator, reply_fn):
        """
        Args:
            curator: CuratorAgent (ai_think 메서드 사용, 결과 요약용)
            reply_fn: _reply 헬퍼 함수
        """
        self.curator = curator
        self._reply = reply_fn

    def _build_clean_env(self) -> dict:
        """Claude Code 실행을 위한 깨끗한 환경변수 구성"""
        clean_env = {k: v for k, v in os.environ.items()}
        clean_env["CLAUDECODE"] = ""
        if "ANTHROPIC_API_KEY" not in clean_env:
            from dotenv import dotenv_values
            env_vals = dotenv_values()
            if "ANTHROPIC_API_KEY" in env_vals:
                clean_env["ANTHROPIC_API_KEY"] = env_vals["ANTHROPIC_API_KEY"]
        return clean_env

    async def run_dev_task(self, prompt: str, channel: str, thread_ts: str = None,
                          notify_start: bool = True, summarize_long: bool = True) -> tuple[bool, str]:
        """
        Claude Code CLI로 개발 작업 실행.

        Args:
            prompt: 실행할 프롬프트 (자율 실행 지침 미포함)
            channel: 슬랙 채널
            thread_ts: 스레드 타임스탬프
            notify_start: 시작 알림 전송 여부
            summarize_long: 긴 결과를 AI로 요약할지 여부

        Returns:
            (success, result_text) 튜플
        """
        full_prompt = prompt + self.AUTONOMOUS_INSTRUCTIONS

        if notify_start:
            await self._reply(channel, "🔨 코드 작업 시작합니다. 진행 상황을 알려드릴게요.", thread_ts)

        try:
            clean_env = self._build_clean_env()
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", full_prompt,
                "--output-format", "text",
                "--permission-mode", "acceptEdits",
                cwd="/home/user/yhmemo",
                env=clean_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=300  # 5분 타임아웃
            )
            output = stdout.decode("utf-8", errors="replace").strip()
            err_output = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0 and output:
                if summarize_long and len(output) > 3000:
                    summary = await self.curator.ai_think(
                        system_prompt="아래 Claude Code 실행 결과를 슬랙 메시지로 요약하세요. 무엇을 만들었는지, 어떤 파일을 생성/수정했는지, 다음 단계는 무엇인지 핵심만. 최대 1500자.",
                        user_prompt=output,
                    )
                    await self._reply(channel, f"✅ *[마스터]* 작업 완료!\n\n{summary or output[:1500]}", thread_ts)
                else:
                    result = output[:3000]
                    await self._reply(channel, f"✅ *[마스터]* 작업 완료!\n\n{result}", thread_ts)
                return True, f"dev 완료"
            else:
                error_msg = err_output or output or "알 수 없는 오류"
                await self._reply(channel, f"⚠️ *[마스터]* 작업 중 문제가 생겼어요:\n```\n{error_msg[:1000]}\n```\n다시 시도하거나 작업을 수정해서 알려주세요.", thread_ts)
                return False, f"dev 오류: {error_msg[:100]}"

        except asyncio.TimeoutError:
            await self._reply(channel, "⏱️ 작업이 5분을 초과했어요. 좀 더 작은 단위로 나눠서 요청해주세요.", thread_ts)
            return False, "dev 타임아웃"
