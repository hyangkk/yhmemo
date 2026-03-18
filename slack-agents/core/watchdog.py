"""
워치독 (Watchdog)

마스터 헬스체크, 로그 파싱, 계획 이행 추적 등
주기적 모니터링 관련 유틸리티 모음.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("watchdog")

KST = timezone(timedelta(hours=9))
_BASE_DIR = os.path.dirname(os.path.dirname(__file__))
PLANNED_TASKS_FILE = os.path.join(_BASE_DIR, "data", "planned_tasks.json")


def save_planned_tasks(slot: str, tasks: list[str]):
    """다음 1시간 계획을 파일에 저장"""
    try:
        data = {"slot": slot, "tasks": tasks, "saved_at": datetime.now(KST).isoformat()}
        with open(PLANNED_TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_planned_tasks() -> dict:
    """이전 계획 로드"""
    try:
        if os.path.exists(PLANNED_TASKS_FILE):
            with open(PLANNED_TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def extract_keywords(task: str) -> list[str]:
    """태스크 설명에서 매칭용 키워드 추출"""
    keywords = []
    task_lower = task.lower()
    agent_keywords = {
        "투자": ["invest", "투자", "cycle"],
        "뉴스": ["curator", "뉴스", "news", "received"],
        "명언": ["quote", "명언"],
        "운세": ["fortune", "운세"],
        "폴링": ["poll", "polling"],
        "slot_check": ["slot_check"],
        "시간별": ["hourly", "execute_hourly"],
        "목표": ["goal", "execute_goal"],
        "제안": ["proposal", "initiative", "propose"],
        "리서치": ["research", "business_research"],
        "트렌드": ["trend", "trend_check"],
        "모니터링": ["measure", "monitor", "성과"],
        "커뮤니케이트": ["communicate", "외부"],
        "빌드": ["build", "개발", "구축"],
    }
    for key, kws in agent_keywords.items():
        if key in task_lower or any(k in task_lower for k in kws):
            keywords.extend(kws)
    for word in task_lower.split():
        if len(word) > 2:
            keywords.append(word)
    return keywords


def check_plan_fulfillment(past_activities: list[str]) -> list[str]:
    """이전 계획 vs 실제 활동 비교"""
    prev = load_planned_tasks()
    if not prev or not prev.get("tasks"):
        return []
    planned = prev["tasks"]
    slot = prev.get("slot", "?")
    activity_text = " ".join(past_activities).lower()
    results = []
    done_count = 0
    for task in planned:
        keywords = extract_keywords(task)
        matched = any(kw in activity_text for kw in keywords)
        if matched:
            results.append(f"  ✅ {task}")
            done_count += 1
        else:
            results.append(f"  ❌ {task}")
    total = len(planned)
    pct = int(done_count / total * 100) if total > 0 else 0
    header = f"*계획 이행률* ({slot}): {done_count}/{total} ({pct}%)"
    return [header] + results


def parse_recent_log_activities(now: datetime) -> list[str]:
    """최근 1시간 로그에서 주요 활동 추출"""
    activities = []
    now_utc = now.astimezone(timezone.utc)
    log_file = os.path.join(
        _BASE_DIR, "data", "logs",
        f"orchestrator-{now_utc.strftime('%Y%m%d')}.log"
    )
    if not os.path.exists(log_file):
        return activities
    one_hour_ago = now_utc - timedelta(hours=1)
    one_hour_ago_str = one_hour_ago.strftime("%Y-%m-%d %H:%M")
    now_date_str = now_utc.strftime("%Y-%m-%d %H:%M")
    log_files = [log_file]
    if one_hour_ago.date() != now_utc.date():
        prev_log = os.path.join(
            _BASE_DIR, "data", "logs",
            f"orchestrator-{one_hour_ago.strftime('%Y%m%d')}.log"
        )
        if os.path.exists(prev_log):
            log_files.insert(0, prev_log)
    _SKIP_ACTIONS = {"slot_check", "find_work"}
    _IGNORE_ERRORS = {"Failed to connect", "Unclosed client session", "Task was destroyed"}
    seen = set()
    slack_msg_count = 0
    try:
      for lf in log_files:
        with open(lf, "r") as f:
            for line in f:
                if len(line) < 20:
                    continue
                date_time_part = line[:16]
                if date_time_part < one_hour_ago_str or date_time_part > now_date_str:
                    continue
                if "New message:" in line:
                    slack_msg_count += 1
                    continue
                if "Poll tick" in line or "Polling" in line or "HTTP Request" in line:
                    continue
                if "Executing:" in line:
                    idx = line.index("Executing:")
                    desc = line[idx + 10:].strip()
                    if any(skip in desc for skip in _SKIP_ACTIONS):
                        continue
                    key = f"proactive: {desc}"
                    if key not in seen:
                        seen.add(key)
                        activities.append(desc)
                elif "[executor]" in line and ("✅" in line or "❌" in line):
                    idx = line.index("[executor]")
                    desc = line[idx + 10:].strip()[:80]
                    key = f"exec: {desc}"
                    if key not in seen:
                        seen.add(key)
                        activities.append(f"실행: {desc}")
                elif "Step completed:" in line or "Step failed:" in line:
                    idx = line.index("Step")
                    desc = line[idx:].strip()[:80]
                    key = f"step: {desc}"
                    if key not in seen:
                        seen.add(key)
                        activities.append(desc)
                elif "Daily plan generated:" in line or "Fallback plan set:" in line:
                    activities.append("일일 계획 생성 완료")
                elif "Sent quote" in line:
                    if "quote" not in seen:
                        seen.add("quote")
                        activities.append("명언 전송 완료")
                elif "[curator] Received" in line:
                    idx = line.index("Received")
                    desc = line[idx:].strip()
                    if "curator" not in seen:
                        seen.add("curator")
                        activities.append(f"뉴스 큐레이션 — {desc}")
                elif "Cycle" in line and "complete" in line and "invest" in line.lower():
                    if "invest_cycle" not in seen:
                        seen.add("invest_cycle")
                        activities.append("투자 분석 사이클 완료")
                elif "[self_memory] Insight" in line:
                    idx = line.index("Insight")
                    desc = line[idx:].strip()[:60]
                    activities.append(f"메모리 저장: {desc}")
                elif "error" in line.lower() and "ERROR" in line:
                    if any(pat in line for pat in _IGNORE_ERRORS):
                        continue
                    short = line.split("ERROR:")[-1].strip()[:60] if "ERROR:" in line else ""
                    if short and short not in seen:
                        seen.add(short)
                        activities.append(f"⚠️ {short}")
      if slack_msg_count > 0:
          activities.append(f"슬랙 메시지 {slack_msg_count}건 수신/처리")
    except Exception as e:
        logger.debug(f"[report] Log parse error: {e}")
    return activities[:8]


def get_next_1h_plan(now: datetime) -> list[str]:
    """앞으로 1시간 실제 실행될 작업"""
    plan = []
    current_hour = now.hour
    pstate = {}
    try:
        mem_file = os.path.join(_BASE_DIR, "data", "self_memory.json")
        with open(mem_file, "r", encoding="utf-8") as f:
            mem = json.load(f)
        hourly_plan = mem.get("plans", {}).get("current_plan", {}).get("hours", {})
        state_file = os.path.join(_BASE_DIR, "data", "proactive_state.json")
        with open(state_file, "r", encoding="utf-8") as f:
            pstate = json.load(f)
        last_exec_hour = pstate.get("last_executed_hour", -1)
        hour_key = f"{current_hour:02d}"
        hour_task = hourly_plan.get(hour_key, {})
        if hour_task:
            task_name = hour_task.get("task", "")
            method = hour_task.get("method", "")
            expected = hour_task.get("expected", "")
            if current_hour != last_exec_hour:
                plan.append(f"[{method}] {task_name} → {expected}")
            else:
                slot_key = f"slot_{current_hour:02d}:{(now.minute // 10) * 10:02d}_result"
                slot_result = pstate.get(slot_key, {})
                if slot_result:
                    grade = slot_result.get("grade", "?")
                    result = slot_result.get("result", "")[:50]
                    plan.append(f"[완료:{grade}] {task_name} — {result}")
                next_hour_key = f"{(current_hour + 1) % 24:02d}"
                next_task = hourly_plan.get(next_hour_key, {})
                if next_task:
                    plan.append(f"[예정] {next_task.get('task','')} [{next_task.get('method','')}]")
    except Exception:
        pass
    try:
        goals_file = os.path.join(_BASE_DIR, "data", "goals.json")
        with open(goals_file, "r", encoding="utf-8") as f:
            goals = json.load(f)
        if isinstance(goals, list):
            goal_list = goals
        else:
            goal_list = goals.get("goals", [])
        for g in goal_list:
            if g.get("status") != "active":
                continue
            steps = g.get("steps", [])
            pending = [s for s in steps if s.get("status") == "pending"]
            if pending:
                plan.append(f"[목표] {g.get('title','')[:30]} → {pending[0].get('description','')[:40]}")
                break
    except Exception:
        pass
    plan.append("AI 전략실 진행보고 (30분 간격)")
    try:
        retry_queue = pstate.get("retry_queue", [])
        if retry_queue:
            for rt in retry_queue[:2]:
                plan.append(f"[재시도] {rt.get('task', '미상')[:40]}")
    except Exception:
        pass
    if not plan:
        plan = ["슬랙 메시지 폴링 (12초 간격)", "활성 목표 스텝 실행"]
    return plan
