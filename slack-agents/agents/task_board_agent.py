"""
TaskBoard 에이전트 — 노션 'AI 업무 지시 보드 DB' 폴링

노션 DB에서 '시작 전' 상태인 업무를 읽어와서
AI가 분석 → 실행 계획 수립 → executor로 실행 → 결과를 노션에 기록
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class TaskBoardAgent(BaseAgent):
    """노션 업무 지시 보드를 폴링하여 자동 실행하는 에이전트"""

    def __init__(self, task_board_db_id: str = "", **kwargs):
        super().__init__(
            name="task_board",
            description="노션 'AI 업무 지시 보드 DB'에서 업무를 읽어 자동 실행한다.",
            slack_channel="ai-agents-general",
            loop_interval=60,  # 1분 간격으로 폴링
            **kwargs,
        )
        self._db_id = task_board_db_id or os.environ.get("NOTION_TASK_BOARD_DB_ID", "")
        self._processing_ids: set[str] = set()  # 현재 처리 중인 페이지 ID (중복 방지)

    # ── Observe ─────────────────────────────────────────

    async def observe(self) -> dict | None:
        """노션 DB에서 '시작 전' 상태 항목을 확인"""
        if not self.notion or not self._db_id:
            return None

        try:
            items = await self.notion.query_database(
                self._db_id,
                filter_dict={
                    "property": "상태",
                    "status": {"equals": "시작 전"},
                },
                sorts=[{"property": "생성 일시", "direction": "ascending"}],
                page_size=5,
            )
        except Exception as e:
            logger.error(f"[task_board] Notion query failed: {e}")
            return None

        if not items:
            return None

        # 이미 처리 중인 항목 제외
        new_items = [i for i in items if i["id"] not in self._processing_ids]
        if not new_items:
            return None

        # 첫 번째 항목만 처리 (순차 실행)
        item = new_items[0]
        page_id = item["id"]
        props = item.get("properties", {})

        # 제목 추출
        title_prop = props.get("이름", {})
        title_parts = title_prop.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_parts)

        # 메모 추출
        memo_prop = props.get("메모", {})
        memo_parts = memo_prop.get("rich_text", [])
        memo = "".join(t.get("plain_text", "") for t in memo_parts)

        # 페이지 본문 블록 읽기
        body_text = await self._read_page_blocks(page_id)

        logger.info(f"[task_board] New task found: '{title}' (id: {page_id})")

        return {
            "page_id": page_id,
            "title": title,
            "memo": memo,
            "body": body_text,
            "created": item.get("created_time", ""),
        }

    async def _read_page_blocks(self, page_id: str) -> str:
        """페이지 본문 블록을 텍스트로 읽기"""
        try:
            resp = await self.notion._http.get(
                f"/blocks/{page_id}/children", params={"page_size": 50}
            )
            resp.raise_for_status()
            blocks = resp.json().get("results", [])
        except Exception as e:
            logger.debug(f"[task_board] Block read failed: {e}")
            return ""

        lines = []
        for block in blocks:
            btype = block.get("type", "")
            content = block.get(btype, {})
            rich_text = content.get("rich_text", [])
            text = "".join(t.get("plain_text", "") for t in rich_text)
            if text:
                lines.append(text)
        return "\n".join(lines)

    # ── Think ───────────────────────────────────────────

    async def think(self, context: dict) -> dict | None:
        """업무 지시를 분석하여 실행 계획 수립"""
        title = context["title"]
        memo = context.get("memo", "")
        body = context.get("body", "")

        task_description = title
        if memo:
            task_description += f"\n\n메모: {memo}"
        if body:
            task_description += f"\n\n상세 내용:\n{body}"

        # AI에게 실행 계획 요청
        from core.executor import EXECUTOR_TOOL_SCHEMA

        plan_response = await self.ai_think(
            system_prompt=f"""당신은 자율 실행 에이전트입니다. 주어진 업무 지시를 분석하고 실행 계획을 세우세요.

사용 가능한 도구:
{EXECUTOR_TOOL_SCHEMA}

규칙:
- 실행 가능한 구체적인 단계로 분해하세요
- 코드 작성이 필요하면 file_write + shell(git commit/push) 조합
- 정보 수집이 필요하면 http_get, shell(curl) 활용
- 분석/리서치 작업이면 http_get으로 데이터 수집 후 analysis에 결과 작성
- 투자 관련 작업이면 shell로 python 스크립트 실행 가능
- 작업 디렉토리: /home/user/yhmemo
- 반드시 JSON만 응답

현재 시각: {self.now_str()}

응답 형식:
{{
  "task_summary": "업무 요약 (한줄)",
  "approach": "접근 방식 설명",
  "steps": [
    {{"tool": "도구명", "args": {{...}}}}
  ],
  "analysis": "분석 결과 (도구 실행 불필요 시)"
}}""",
            user_prompt=f"업무 지시:\n{task_description}",
        )

        try:
            clean = plan_response.strip()
            if "```json" in clean:
                clean = clean.split("```json", 1)[1].rsplit("```", 1)[0].strip()
            elif "```" in clean:
                clean = clean.split("```", 1)[1].rsplit("```", 1)[0].strip()
            plan = json.loads(clean)
        except json.JSONDecodeError:
            # JSON 객체 추출 시도
            brace_start = plan_response.find("{")
            if brace_start >= 0:
                depth = 0
                for i in range(brace_start, len(plan_response)):
                    if plan_response[i] == "{":
                        depth += 1
                    elif plan_response[i] == "}":
                        depth -= 1
                    if depth == 0:
                        try:
                            plan = json.loads(plan_response[brace_start : i + 1])
                            break
                        except json.JSONDecodeError:
                            pass
                else:
                    plan = {"analysis": plan_response, "steps": []}
            else:
                plan = {"analysis": plan_response, "steps": []}

        return {
            "page_id": context["page_id"],
            "title": context["title"],
            "plan": plan,
        }

    # ── Act ─────────────────────────────────────────────

    async def act(self, decision: dict):
        """실행 계획을 수행하고 결과를 노션에 기록"""
        page_id = decision["page_id"]
        title = decision["title"]
        plan = decision["plan"]

        self._processing_ids.add(page_id)

        try:
            # 1. 상태를 '진행 중'으로 변경
            await self.notion.update_page(page_id, {
                "상태": {"status": {"name": "진행 중"}},
            })
            await self.log(f"📋 업무 착수: {title}")

            # 2. 실행
            steps = plan.get("steps", [])
            analysis = plan.get("analysis", "")
            task_summary = plan.get("task_summary", title)
            approach = plan.get("approach", "")

            result_text = ""
            success = True

            if steps:
                from core.executor import execute_plan, format_execution_results, ALLOWED_BASE

                await self.say(f"📋 *[업무 지시 실행]* {title}\n> 접근: {approach}\n> {len(steps)}단계 실행 시작")

                exec_results = await execute_plan(
                    steps,
                    supabase_client=self.supabase,
                    cwd=str(ALLOWED_BASE),
                )
                result_text = format_execution_results(exec_results)
                success_count = sum(1 for r in exec_results if r["ok"])
                fail_count = len(exec_results) - success_count
                success = fail_count == 0

                status_emoji = "✅" if success else "⚠️"
                await self.say(
                    f"{status_emoji} *업무 완료: {title}*\n"
                    f"> 성공: {success_count}/{len(exec_results)}단계\n"
                    f"```{result_text[:1500]}```"
                )
            elif analysis:
                result_text = analysis
                await self.say(
                    f"✅ *업무 완료: {title}*\n"
                    f"```{analysis[:1500]}```"
                )
            else:
                result_text = "실행할 단계가 없습니다."
                success = False

            # 3. AI에게 결과 요약 요청
            summary = await self.ai_think(
                system_prompt="업무 실행 결과를 간결하게 요약하세요. 핵심 결과와 다음 단계를 포함. 200자 이내.",
                user_prompt=f"업무: {title}\n실행 결과:\n{result_text[:3000]}",
            )

            # 4. 결과를 노션 메모에 기록 + 상태를 '완료'로 변경
            now_str = self.now_str()
            result_memo = f"[{now_str} 실행 완료]\n{summary[:1800]}"

            await self.notion.update_page(page_id, {
                "상태": {"status": {"name": "완료"}},
                "메모": self.notion.prop_rich_text(result_memo),
            })

            # 5. 결과를 페이지 본문에도 추가 (상세 기록)
            await self.notion.append_blocks(page_id, [
                self.notion.block_divider(),
                self.notion.block_heading(f"실행 결과 ({now_str})", level=2),
                self.notion.block_paragraph(f"접근 방식: {approach}"),
                self.notion.block_paragraph(summary[:2000]),
            ])

            await self.log(f"✅ 업무 완료: {title}")

        except Exception as e:
            logger.error(f"[task_board] Execution failed for '{title}': {e}", exc_info=True)
            # 실패 시 메모에 에러 기록
            try:
                await self.notion.update_page(page_id, {
                    "메모": self.notion.prop_rich_text(
                        f"[{self.now_str()} 실행 실패]\n에러: {str(e)[:500]}"
                    ),
                })
            except Exception:
                pass
            await self.log(f"❌ 업무 실패: {title} — {e}")
        finally:
            self._processing_ids.discard(page_id)
