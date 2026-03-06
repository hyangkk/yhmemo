#!/bin/bash
# crontab watchdog: orchestrator가 죽었으면 run_forever.sh로 재시작
# crontab -e → */1 * * * * /home/user/yhmemo/slack-agents/watchdog_cron.sh

LOCKFILE="/tmp/orchestrator_forever.lock"
LOGFILE="/tmp/orchestrator_stdout.log"

# run_forever.sh가 살아있는지 확인
if [ -f "$LOCKFILE" ]; then
    PID=$(cat "$LOCKFILE")
    if kill -0 "$PID" 2>/dev/null; then
        exit 0  # 살아있으면 아무것도 안 함
    fi
fi

# 죽었으면 재시작
echo "$(date -u '+%Y-%m-%d %H:%M:%S') [cron-watchdog] Restarting orchestrator..." >> "$LOGFILE"
rm -f "$LOCKFILE"
cd /home/user/yhmemo/slack-agents
nohup bash run_forever.sh > /dev/null 2>&1 &
disown
