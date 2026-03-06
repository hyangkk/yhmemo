"""
MasterWatchdog - 마스터 헬스체크 모듈

10분마다 전체 시스템을 점검하고, 죽은 에이전트를 자동 재시작하고,
Slack에 상태를 보고한다.
"""

import logging
from datetime import datetime, timezone, timedelta

from core import agent_tracker

logger = logging.getLogger("orchestrator.watchdog")

KST = timezone(timedelta(hours=9))


class MasterWatchdog:
    """에이전트 생존 확인 + 자동 재시작 + Slack 보고"""

    def __init__(self, slack, agent_tasks: dict, agent_starters: dict):
        """
        Args:
            slack: SlackClient 인스턴스
            agent_tasks: {name: asyncio.Task} 딕셔너리 (mutable, 외부와 공유)
            agent_starters: {name: lambda -> Task} 팩토리 딕셔너리
        """
        self.slack = slack
        self.agent_tasks = agent_tasks
        self.agent_starters = agent_starters

    async def check(self):
        """전체 시스템 점검 + 죽은 에이전트 자동 재시작 + Slack 보고"""
        now = datetime.now(KST)
        now_str = now.strftime("%H:%M")
        issues = []
        restarts = []

        # 1. 에이전트 태스크 생존 확인 + 자동 재시작
        for name, task in list(self.agent_tasks.items()):
            if task.done():
                exc = task.exception() if not task.cancelled() else None
                err_msg = str(exc)[:100] if exc else "unknown"
                logger.warning(f"[watchdog] Agent '{name}' is DEAD (error: {err_msg})")
                agent_tracker.record_error(name, f"Task died: {err_msg}")

                # 재시작
                if name in self.agent_starters:
                    try:
                        self.agent_tasks[name] = self.agent_starters[name]()
                        agent_tracker.register_agent(name, f"자동 재시작됨 ({now_str})")
                        restarts.append(name)
                        logger.info(f"[watchdog] Restarted agent: {name}")
                    except Exception as e:
                        issues.append(f"❌ {name}: 재시작 실패 ({e})")
                        logger.error(f"[watchdog] Failed to restart {name}: {e}")
                else:
                    issues.append(f"❌ {name}: 죽음 (재시작 불가)")

        # 2. heartbeat 체크 -- 15분 이상 응답 없으면 경고
        tracker_data = agent_tracker._load()
        for name, info in tracker_data.get("agents", {}).items():
            last_hb = info.get("last_heartbeat", "")
            if last_hb:
                try:
                    hb_time = datetime.fromisoformat(last_hb)
                    if hb_time.tzinfo is None:
                        hb_time = hb_time.replace(tzinfo=KST)
                    elapsed = (now - hb_time).total_seconds()
                    if elapsed > 900:  # 15분 초과
                        mins = int(elapsed / 60)
                        issues.append(f"⚠️ {name}: heartbeat {mins}분 전 (무응답)")
                except (ValueError, TypeError):
                    pass

        # 3. Slack 보고 (이슈/재시작 있거나 매시 정각)
        is_hourly = now.minute < 10
        if issues or restarts or is_hourly:
            report_lines = [f"*🔍 마스터 점검* ({now_str} KST)"]
            if restarts:
                report_lines.append(f"🔄 자동 재시작: *{', '.join(restarts)}*")
            if issues:
                for issue in issues:
                    report_lines.append(issue)
            alive = sum(1 for t in self.agent_tasks.values() if not t.done())
            total = len(self.agent_tasks)
            report_lines.append(f"✅ 가동: {alive}/{total} 에이전트")
            try:
                await self.slack.send_message("ai-agent-logs", "\n".join(report_lines))
            except Exception as e:
                logger.error(f"[watchdog] Slack report failed: {e}")

        if restarts:
            logger.info(f"[watchdog] Restarted: {restarts}")
        elif issues:
            logger.warning(f"[watchdog] Issues: {len(issues)}")
        else:
            logger.info(f"[watchdog] All {len(self.agent_tasks)} agents OK")
