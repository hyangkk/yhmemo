"""
TaskBoard 에이전트 — 노션 'AI 업무 지시 보드 DB' 폴링

노션 DB에서 '착수 대기중' 상태인 업무를 읽어와서
AI가 분석 → 실행 계획 수립 → executor로 실행 → 결과를 노션에 기록

상태 흐름:
  작성중 → 착수 대기중 → 진행 중 → 완료
  - 작성중: 사용자가 요청사항을 작성하는 단계 (에이전트 착수 금지)
  - 착수 대기중: 사용자가 작성 완료 후 에이전트에게 착수를 허가한 상태
  - 진행 중: 에이전트가 실행 중
  - 완료: 실행 완료

또한, 완료된 업무의 댓글을 모니터링하여
후속 지시가 있으면 자동으로 수행한다.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.base_agent import BaseAgent

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 처리 완료된 댓글 ID를 영속 저장하는 파일
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PROCESSED_COMMENTS_FILE = _DATA_DIR / "processed_comment_ids.json"


def _load_processed_comment_ids() -> set[str]:
    """이전에 처리한 댓글 ID 목록 로드"""
    try:
        if _PROCESSED_COMMENTS_FILE.exists():
            data = json.loads(_PROCESSED_COMMENTS_FILE.read_text(encoding="utf-8"))
            return set(data)
    except Exception:
        pass
    return set()


def _save_processed_comment_ids(ids: set[str]):
    """처리 완료된 댓글 ID 목록 저장"""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        # 최근 500개만 유지 (무한 증가 방지)
        trimmed = sorted(ids)[-500:]
        _PROCESSED_COMMENTS_FILE.write_text(
            json.dumps(trimmed, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"[task_board] Failed to save processed comment IDs: {e}")


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
        self._processed_comment_ids: set[str] = _load_processed_comment_ids()

    # ── Observe ─────────────────────────────────────────

    async def observe(self) -> dict | None:
        """노션 DB에서 '착수 대기중' 상태 항목 확인 + 댓글 후속 지시 확인"""
        if not self.notion or not self._db_id:
            return None

        # 1) 새 업무 확인 (기존 로직)
        new_task = await self._observe_new_tasks()
        if new_task:
            return new_task

        # 2) 댓글 후속 지시 확인
        comment_task = await self._observe_comments()
        if comment_task:
            return comment_task

        return None

    async def _observe_new_tasks(self) -> dict | None:
        """'착수 대기중' 상태 업무 확인 ('작성중'은 무시)"""
        try:
            items = await self.notion.query_database(
                self._db_id,
                filter_dict={
                    "property": "상태",
                    "status": {"equals": "착수 대기중"},
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

        item = new_items[0]
        page_id = item["id"]
        props = item.get("properties", {})

        title = self._extract_title(props)
        memo = self._extract_memo(props)
        body_text = await self._read_page_blocks(page_id)

        logger.info(f"[task_board] New task found: '{title}' (id: {page_id})")

        return {
            "type": "new_task",
            "page_id": page_id,
            "title": title,
            "memo": memo,
            "body": body_text,
            "created": item.get("created_time", ""),
        }

    async def _observe_comments(self) -> dict | None:
        """완료/진행 중 업무의 새 댓글(후속 지시) 확인"""
        try:
            # 완료 상태 업무에서 댓글 확인
            items = await self.notion.query_database(
                self._db_id,
                filter_dict={
                    "or": [
                        {"property": "상태", "status": {"equals": "완료"}},
                        {"property": "상태", "status": {"equals": "진행 중"}},
                    ]
                },
                sorts=[{"property": "생성 일시", "direction": "descending"}],
                page_size=20,
            )
        except Exception as e:
            logger.error(f"[task_board] Notion comment query failed: {e}")
            return None

        if not items:
            return None

        for item in items:
            page_id = item["id"]
            if page_id in self._processing_ids:
                continue

            props = item.get("properties", {})
            title = self._extract_title(props)

            # 댓글 조회
            try:
                comments = await self.notion.get_comments(page_id)
            except Exception as e:
                logger.debug(f"[task_board] Comment fetch failed for {page_id}: {e}")
                continue

            if not comments:
                continue

            # 새 댓글 필터링 (에이전트가 작성한 댓글과 이미 처리한 댓글 제외)
            for comment in comments:
                comment_id = comment.get("id", "")
                if comment_id in self._processed_comment_ids:
                    continue

                # 댓글 작성자 확인 — bot/integration이 작성한 것은 무시
                created_by = comment.get("created_by", {})
                if created_by.get("type") == "bot":
                    self._processed_comment_ids.add(comment_id)
                    continue

                # 댓글 텍스트 추출
                rich_text = comment.get("rich_text", [])
                comment_text = "".join(
                    t.get("plain_text", "") for t in rich_text
                ).strip()

                if not comment_text:
                    self._processed_comment_ids.add(comment_id)
                    continue

                # 이전 실행 결과(본문) 가져오기 — 맥락 유지
                body_text = await self._read_page_blocks(page_id)
                memo = self._extract_memo(props)

                logger.info(
                    f"[task_board] Follow-up comment on '{title}': {comment_text[:80]}"
                )

                return {
                    "type": "follow_up",
                    "page_id": page_id,
                    "title": title,
                    "comment_id": comment_id,
                    "comment_text": comment_text,
                    "memo": memo,
                    "body": body_text,
                    "created": comment.get("created_time", ""),
                }

        return None

    # ── 프로퍼티 추출 헬퍼 ─────────────────────────────

    @staticmethod
    def _extract_title(props: dict) -> str:
        title_prop = props.get("이름", {})
        title_parts = title_prop.get("title", [])
        return "".join(t.get("plain_text", "") for t in title_parts)

    @staticmethod
    def _extract_memo(props: dict) -> str:
        memo_prop = props.get("메모", {})
        memo_parts = memo_prop.get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in memo_parts)

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
        ctx_type = context.get("type", "new_task")

        if ctx_type == "follow_up":
            return await self._think_follow_up(context)
        else:
            return await self._think_new_task(context)

    async def _think_new_task(self, context: dict) -> dict | None:
        """새 업무에 대한 실행 계획"""
        title = context["title"]
        memo = context.get("memo", "")
        body = context.get("body", "")

        task_description = title
        if memo:
            task_description += f"\n\n메모: {memo}"
        if body:
            task_description += f"\n\n상세 내용:\n{body}"

        plan = await self._generate_plan(task_description)

        return {
            "type": "new_task",
            "page_id": context["page_id"],
            "title": context["title"],
            "plan": plan,
        }

    async def _think_follow_up(self, context: dict) -> dict | None:
        """댓글 후속 지시에 대한 실행 계획"""
        title = context["title"]
        comment_text = context["comment_text"]
        memo = context.get("memo", "")
        body = context.get("body", "")

        task_description = (
            f"[후속 지시] 기존 업무: {title}\n\n"
            f"사용자 후속 댓글 지시:\n{comment_text}"
        )
        if memo:
            task_description += f"\n\n이전 실행 메모:\n{memo}"
        if body:
            task_description += f"\n\n페이지 본문 (이전 실행 결과 포함):\n{body}"

        plan = await self._generate_plan(task_description)

        return {
            "type": "follow_up",
            "page_id": context["page_id"],
            "title": title,
            "comment_id": context["comment_id"],
            "comment_text": comment_text,
            "plan": plan,
        }

    async def _generate_plan(self, task_description: str) -> dict:
        """AI에게 실행 계획 요청 (공통)"""
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
- [후속 지시]인 경우, 이전 실행 결과를 참고하여 추가 작업을 계획하세요

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

        return plan

    # ── Act ─────────────────────────────────────────────

    async def act(self, decision: dict):
        """실행 계획을 수행하고 결과를 노션에 기록"""
        decision_type = decision.get("type", "new_task")

        if decision_type == "follow_up":
            await self._act_follow_up(decision)
        else:
            await self._act_new_task(decision)

    async def _act_new_task(self, decision: dict):
        """새 업무 실행"""
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

            # 2. 실행 및 결과 기록
            result_text, success, approach = await self._execute_plan(plan, title, page_id=page_id)

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

    async def _act_follow_up(self, decision: dict):
        """댓글 후속 지시 실행"""
        page_id = decision["page_id"]
        title = decision["title"]
        comment_id = decision["comment_id"]
        comment_text = decision["comment_text"]
        plan = decision["plan"]

        self._processing_ids.add(page_id)

        try:
            # 1. 상태를 '진행 중'으로 변경
            await self.notion.update_page(page_id, {
                "상태": {"status": {"name": "진행 중"}},
            })
            await self.log(f"💬 후속 지시 착수: {title} — {comment_text[:50]}")
            await self.say(
                f"💬 *[후속 지시 감지]* {title}\n"
                f"> 댓글: {comment_text[:200]}\n"
                f"> 처리를 시작합니다."
            )

            # 2. 실행
            result_text, success, approach = await self._execute_plan(plan, f"{title} (후속)", page_id=page_id)

            # 3. AI에게 결과 요약
            summary = await self.ai_think(
                system_prompt="후속 지시 실행 결과를 간결하게 요약하세요. 핵심 결과를 포함. 200자 이내.",
                user_prompt=f"원래 업무: {title}\n후속 지시: {comment_text}\n실행 결과:\n{result_text[:3000]}",
            )

            # 4. 노션 댓글로 결과 회신
            now_str = self.now_str()
            reply_text = f"[{now_str} 후속 지시 완료]\n{summary[:1800]}"
            await self.notion.create_comment(page_id, reply_text)

            # 5. 상태 업데이트 + 메모 갱신
            await self.notion.update_page(page_id, {
                "상태": {"status": {"name": "완료"}},
                "메모": self.notion.prop_rich_text(
                    f"[{now_str} 후속 완료] {comment_text[:100]}\n{summary[:1600]}"
                ),
            })

            # 6. 페이지 본문에도 기록
            await self.notion.append_blocks(page_id, [
                self.notion.block_divider(),
                self.notion.block_heading(f"후속 지시 결과 ({now_str})", level=2),
                self.notion.block_paragraph(f"댓글 지시: {comment_text[:500]}"),
                self.notion.block_paragraph(f"접근 방식: {approach}"),
                self.notion.block_paragraph(summary[:2000]),
            ])

            await self.say(f"✅ *후속 지시 완료: {title}*\n> {summary[:300]}")
            await self.log(f"✅ 후속 지시 완료: {title}")

        except Exception as e:
            logger.error(
                f"[task_board] Follow-up execution failed for '{title}': {e}",
                exc_info=True,
            )
            # 실패 시 댓글로 에러 회신
            try:
                await self.notion.create_comment(
                    page_id,
                    f"[{self.now_str()} 후속 지시 실패]\n에러: {str(e)[:500]}",
                )
            except Exception:
                pass
            await self.log(f"❌ 후속 지시 실패: {title} — {e}")
        finally:
            # 댓글 처리 완료 기록
            self._processed_comment_ids.add(comment_id)
            _save_processed_comment_ids(self._processed_comment_ids)
            self._processing_ids.discard(page_id)

    # ── 공통 실행 로직 ──────────────────────────────────

    async def _execute_plan(self, plan: dict, label: str, page_id: str = "") -> tuple[str, bool, str]:
        """실행 계획을 수행하고 (결과텍스트, 성공여부, 접근방식) 반환"""
        steps = plan.get("steps", [])
        analysis = plan.get("analysis", "")
        approach = plan.get("approach", "")
        notion_link = f"\n<https://notion.so/{page_id.replace('-', '')}|노션에서 보기>" if page_id else ""

        result_text = ""
        success = True

        if steps:
            from core.executor import execute_plan, format_execution_results, ALLOWED_BASE

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
                f"{status_emoji} *실행 완료: {label}*\n"
                f"> {approach}\n"
                f"> 결과: {success_count}/{len(exec_results)}단계 성공{notion_link}"
            )
        elif analysis:
            result_text = analysis
            # 분석 결과는 첫 줄만 간략히 표시
            first_line = analysis.strip().split("\n")[0][:100]
            await self.say(
                f"✅ *실행 완료: {label}*\n"
                f"> {first_line}{notion_link}"
            )
        else:
            result_text = "실행할 단계가 없습니다."
            success = False

        return result_text, success, approach
