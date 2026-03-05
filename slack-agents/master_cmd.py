#!/usr/bin/env python3
"""
마스터 명령 큐 - Claude Code 세션에서 봇에게 명령을 보내는 유틸리티

사용법:
    python master_cmd.py send_message --text "안녕" --channel ai-agents-general
    python master_cmd.py dev --task "webapp 프로젝트 빌드해줘"
    python master_cmd.py collect --query "AI 스타트업"
    python master_cmd.py briefing
    python master_cmd.py trigger_proactive --action propose_initiative
    python master_cmd.py slack_reply --thread_ts 1234.5678 --text "진행해"

또는 Python에서 직접:
    from master_cmd import send_command
    send_command({"type": "dev", "task": "..."})
"""

import json
import os
import sys

QUEUE_FILE = os.path.join(os.path.dirname(__file__), "data", "command_queue.json")


def send_command(cmd: dict):
    """명령을 큐에 추가"""
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        queue = []
    queue.append(cmd)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        f.write(json.dumps(queue, ensure_ascii=False, indent=2))
    print(f"Command queued: {cmd.get('type', 'unknown')}")


def send_commands(cmds: list):
    """여러 명령을 한번에 큐에 추가"""
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            queue = json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        queue = []
    queue.extend(cmds)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        f.write(json.dumps(queue, ensure_ascii=False, indent=2))
    print(f"Queued {len(cmds)} commands")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd_type = sys.argv[1]
    cmd = {"type": cmd_type}

    # Parse --key value pairs
    i = 2
    while i < len(sys.argv):
        if sys.argv[i].startswith("--"):
            key = sys.argv[i][2:]
            if i + 1 < len(sys.argv):
                cmd[key] = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        else:
            i += 1

    send_command(cmd)
