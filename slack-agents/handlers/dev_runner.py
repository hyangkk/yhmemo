"""
DevRunner - AI API 기반 개발 작업 실행 모듈

NL 핸들러와 커맨드 큐에서 공통으로 사용하는
작업 실행 로직을 캡슐화.
"""

import logging

logger = logging.getLogger("orchestrator.dev_runner")


class DevRunner:
    """Anthropic API를 통한 개발 작업 실행"""

    def __init__(self, curator, reply_fn):
        """
        Args:
            curator: CuratorAgent (ai_think 메서드 사용, 결과 요약용)
            reply_fn: _reply 헬퍼 함수
        """
        self.curator = curator
        self._reply = reply_fn

    async def run_dev_task(self, prompt: str, channel: str, thread_ts: str = None,
                          notify_start: bool = True, summarize_long: bool = True) -> tuple[bool, str]:
        """
        AI API로 개발 작업 실행.

        Args:
            prompt: 실행할 프롬프트
            channel: 슬랙 채널
            thread_ts: 스레드 타임스탬프
            notify_start: 시작 알림 전송 여부
            summarize_long: 긴 결과를 AI로 요약할지 여부

        Returns:
            (success, result_text) 튜플
        """
        if notify_start:
            await self._reply(channel, "🔨 작업 시작합니다. 진행 상황을 알려드릴게요.", thread_ts)

        try:
            output = await self.curator.ai_think(
                system_prompt="""당신은 소프트웨어 엔지니어입니다. 요청된 작업을 분석하고 구체적 결과물을 만드세요.
- 코드가 필요하면 구체적 구현 계획 + 핵심 코드 제공
- 분석/리서치면 구체적 결과 제공
- 반드시 실행 가능한 결과물을 만들 것""",
                user_prompt=prompt,
            )

            if output:
                if summarize_long and len(output) > 3000:
                    summary = await self.curator.ai_think(
                        system_prompt="아래 결과를 슬랙 메시지로 요약하세요. 핵심만. 최대 1500자.",
                        user_prompt=output,
                    )
                    await self._reply(channel, f"✅ *[마스터]* 작업 완료!\n\n{summary or output[:1500]}", thread_ts)
                else:
                    result = output[:3000]
                    await self._reply(channel, f"✅ *[마스터]* 작업 완료!\n\n{result}", thread_ts)
                return True, "dev 완료"
            else:
                await self._reply(channel, "⚠️ *[마스터]* 작업 결과를 생성하지 못했어요. 다시 시도해주세요.", thread_ts)
                return False, "dev 오류: 결과 없음"

        except Exception as e:
            await self._reply(channel, f"⚠️ *[마스터]* 작업 중 오류:\n```{str(e)[:500]}```", thread_ts)
            return False, f"dev 오류: {str(e)[:100]}"
