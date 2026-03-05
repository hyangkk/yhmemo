"""
에이전트 가동 현황 추적 시스템

각 에이전트의:
- 시작 시각
- 마지막 활동 시각
- 총 사이클 수
- 상태 (running/stopped/error)
- 24시간 가동률 (heartbeat 기반)
"""

import json
import os
import logging
from datetime import datetime, timezone, timedelta
from threading import Lock

logger = logging.getLogger("agent_tracker")

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
TRACKER_FILE = os.path.join(DATA_DIR, "agent_tracker.json")

_lock = Lock()


def _load() -> dict:
    try:
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"agents": {}}


def _save(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TRACKER_FILE, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))


def register_agent(name: str, description: str = "", loop_interval: int = 0):
    """에이전트 등록 (시작 시 호출)"""
    with _lock:
        data = _load()
        now = datetime.now(KST).isoformat()
        agents = data.setdefault("agents", {})
        agents[name] = {
            "description": description,
            "status": "running",
            "started_at": now,
            "last_heartbeat": now,
            "loop_interval": loop_interval,
            "cycle_count": 0,
            "error_count": 0,
            "last_error": "",
            # 24시간 heartbeat 슬롯 (10분 단위 = 144 슬롯)
            "heartbeats_24h": [],
        }
        _save(data)
        logger.info(f"[tracker] Registered agent: {name}")


def heartbeat(name: str):
    """에이전트 heartbeat (루프마다 호출)"""
    with _lock:
        data = _load()
        agent = data.get("agents", {}).get(name)
        if not agent:
            return
        now = datetime.now(KST)
        agent["last_heartbeat"] = now.isoformat()
        agent["cycle_count"] = agent.get("cycle_count", 0) + 1
        agent["status"] = "running"

        # 10분 슬롯 기록 (24시간 = 144 슬롯)
        slot = now.strftime("%Y-%m-%d %H:") + str(now.minute // 10 * 10).zfill(2)
        beats = agent.get("heartbeats_24h", [])
        if not beats or beats[-1] != slot:
            beats.append(slot)
        # 최근 144 슬롯만 보관
        agent["heartbeats_24h"] = beats[-144:]
        _save(data)


def record_error(name: str, error: str):
    """에이전트 에러 기록"""
    with _lock:
        data = _load()
        agent = data.get("agents", {}).get(name)
        if not agent:
            return
        agent["error_count"] = agent.get("error_count", 0) + 1
        agent["last_error"] = str(error)[:200]
        agent["status"] = "error"
        _save(data)


def mark_stopped(name: str):
    """에이전트 중지 기록"""
    with _lock:
        data = _load()
        agent = data.get("agents", {}).get(name)
        if not agent:
            return
        agent["status"] = "stopped"
        _save(data)


def get_status_report() -> str:
    """전체 에이전트 현황 보고 (슬랙 형식)"""
    data = _load()
    agents = data.get("agents", {})

    if not agents:
        return "등록된 에이전트가 없습니다."

    now = datetime.now(KST)
    now_str = now.strftime("%Y-%m-%d %H:%M")

    lines = [f"*🤖 에이전트 현황* ({now_str} KST)\n"]
    lines.append(f"총 에이전트: *{len(agents)}개*\n")

    status_emoji = {"running": "🟢", "stopped": "🔴", "error": "🟡"}

    for name, info in sorted(agents.items()):
        emoji = status_emoji.get(info.get("status", ""), "⚪")
        cycles = info.get("cycle_count", 0)
        interval = info.get("loop_interval", 0)
        desc = info.get("description", "")[:30]

        # 가동률 계산 (최근 24시간)
        uptime_pct = _calc_uptime(info, now)

        # 마지막 활동
        last_hb = info.get("last_heartbeat", "")
        ago = _time_ago(last_hb, now)

        line = f"{emoji} *{name}*"
        if desc:
            line += f" — {desc}"
        lines.append(line)

        detail = f"   사이클: {cycles}회"
        if interval:
            detail += f" (매 {interval}초)"
        detail += f" | 가동률: *{uptime_pct}%*"
        detail += f" | 마지막: {ago}"
        lines.append(detail)

        errors = info.get("error_count", 0)
        if errors > 0:
            lines.append(f"   ⚠️ 에러: {errors}회 | 최근: {info.get('last_error', '')[:60]}")

        lines.append("")

    # 전체 시스템 가동 시간
    started_times = [info.get("started_at", "") for info in agents.values() if info.get("started_at")]
    if started_times:
        earliest = min(started_times)
        system_ago = _time_ago(earliest, now)
        lines.append(f"_시스템 시작: {system_ago}_")

    return "\n".join(lines)


def get_summary_for_report() -> dict:
    """프로액티브 에이전트 보고서용 요약 데이터"""
    data = _load()
    agents = data.get("agents", {})
    now = datetime.now(KST)

    summary = {
        "total_agents": len(agents),
        "running": sum(1 for a in agents.values() if a.get("status") == "running"),
        "agents": {},
    }
    for name, info in agents.items():
        summary["agents"][name] = {
            "status": info.get("status", "unknown"),
            "cycles": info.get("cycle_count", 0),
            "uptime_pct": _calc_uptime(info, now),
            "errors": info.get("error_count", 0),
        }
    return summary


def _calc_uptime(info: dict, now: datetime) -> float:
    """24시간 가동률 (%) 계산"""
    beats = info.get("heartbeats_24h", [])
    if not beats:
        return 0.0

    # 최근 24시간의 10분 슬롯 수 (최대 144)
    cutoff = now - timedelta(hours=24)
    recent = []
    for slot in beats:
        try:
            slot_time = datetime.strptime(slot, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
            if slot_time >= cutoff:
                recent.append(slot)
        except ValueError:
            continue

    # 시작 시간 이후의 총 슬롯 수 계산
    started = info.get("started_at", "")
    try:
        start_time = datetime.fromisoformat(started)
        hours_since_start = (now - start_time).total_seconds() / 3600
        max_slots = min(144, int(hours_since_start * 6) + 1)  # 10분 = 6슬롯/시간
    except (ValueError, TypeError):
        max_slots = 144

    if max_slots <= 0:
        max_slots = 1

    pct = min(100.0, (len(recent) / max_slots) * 100)
    return round(pct, 1)


def _time_ago(iso_str: str, now: datetime) -> str:
    """시간 차이를 사람이 읽기 쉬운 형식으로"""
    if not iso_str:
        return "기록없음"
    try:
        ts = datetime.fromisoformat(iso_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        diff = now - ts
        secs = diff.total_seconds()
        if secs < 60:
            return "방금"
        elif secs < 3600:
            return f"{int(secs/60)}분 전"
        elif secs < 86400:
            return f"{int(secs/3600)}시간 {int((secs%3600)/60)}분 전"
        else:
            return f"{int(secs/86400)}일 전"
    except (ValueError, TypeError):
        return "알수없음"
