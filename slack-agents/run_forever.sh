#!/bin/bash
# 불사 orchestrator: 죽으면 5초 후 자동 재시작
# Usage: nohup bash /home/user/yhmemo/slack-agents/run_forever.sh &

LOCKFILE="/tmp/orchestrator_forever.lock"
LOGFILE="/tmp/orchestrator_stdout.log"

# 이미 실행 중이면 중복 방지
if [ -f "$LOCKFILE" ]; then
    OLD_PID=$(cat "$LOCKFILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Already running (PID $OLD_PID). Exiting."
        exit 0
    fi
fi
echo $$ > "$LOCKFILE"

cleanup() {
    rm -f "$LOCKFILE"
    # 자식 프로세스도 종료
    if [ -n "$CHILD_PID" ]; then
        kill "$CHILD_PID" 2>/dev/null
    fi
    exit 0
}
trap cleanup EXIT SIGINT SIGTERM

cd /home/user/yhmemo/slack-agents
source venv/bin/activate

while true; do
    echo "$(date -u '+%Y-%m-%d %H:%M:%S') [run_forever] Starting orchestrator..." >> "$LOGFILE"
    python3 orchestrator.py >> "$LOGFILE" 2>&1 &
    CHILD_PID=$!
    wait $CHILD_PID
    EXIT_CODE=$?
    echo "$(date -u '+%Y-%m-%d %H:%M:%S') [run_forever] Orchestrator exited (code=$EXIT_CODE). Restarting in 5s..." >> "$LOGFILE"
    sleep 5
done
