#!/bin/bash
# forever.sh — orchestrator를 영원히 재시작하는 불멸 래퍼
#
# 사용법:
#   ./forever.sh          (포그라운드)
#   ./forever.sh &         (백그라운드)
#   systemctl start ai-agents  (systemd)
#
# 클로드 세션, SSH 연결과 무관하게 24시간 영구 가동.
# 프로세스가 죽으면 5초 후 자동 재시작.
# 연속 실패 시 대기시간 증가 (최대 5분).

set -euo pipefail
cd "$(dirname "$0")"

LOG_DIR="data/logs"
mkdir -p "$LOG_DIR"

MAX_BACKOFF=300  # 최대 5분
BACKOFF=5
CONSECUTIVE_FAILURES=0

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_DIR/forever.log"
}

cleanup() {
    log "Forever wrapper shutting down (PID $$)"
    # 자식 프로세스 종료
    if [ -n "${CHILD_PID:-}" ] && kill -0 "$CHILD_PID" 2>/dev/null; then
        kill "$CHILD_PID" 2>/dev/null || true
        wait "$CHILD_PID" 2>/dev/null || true
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM

log "=== Forever wrapper started (PID $$) ==="

# 가상환경 확인
if [ ! -d "venv" ]; then
    log "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# 패키지 설치 (최초 또는 변경 시)
pip install -r requirements.txt -q 2>/dev/null || true

# .env 확인
if [ ! -f ".env" ]; then
    log "ERROR: .env file not found"
    exit 1
fi

while true; do
    START_TIME=$(date +%s)
    log "Starting orchestrator (attempt after ${BACKOFF}s backoff, failures: $CONSECUTIVE_FAILURES)"

    # orchestrator 실행 (로그 파일로 + stdout 유지)
    python3 orchestrator.py 2>&1 | tee -a "$LOG_DIR/orchestrator-$(date +%Y%m%d).log" &
    CHILD_PID=$!

    # 자식 프로세스 대기
    wait $CHILD_PID
    EXIT_CODE=$?
    END_TIME=$(date +%s)
    RUNTIME=$((END_TIME - START_TIME))

    log "Orchestrator exited with code $EXIT_CODE after ${RUNTIME}s"

    # 30초 이상 실행됐으면 안정적이었다고 판단 → 백오프 리셋
    if [ "$RUNTIME" -gt 30 ]; then
        CONSECUTIVE_FAILURES=0
        BACKOFF=5
    else
        CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
        BACKOFF=$((BACKOFF * 2))
        if [ "$BACKOFF" -gt "$MAX_BACKOFF" ]; then
            BACKOFF=$MAX_BACKOFF
        fi
    fi

    # 연속 20회 실패 시 슬랙 알림 (curl로 직접)
    if [ "$CONSECUTIVE_FAILURES" -ge 20 ]; then
        log "CRITICAL: 20 consecutive failures, sending slack alert"
        source .env
        curl -s -X POST "https://slack.com/api/chat.postMessage" \
            -H "Authorization: Bearer $SLACK_BOT_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"channel\": \"ai-agents-general\", \"text\": \"🚨 *CRITICAL* 에이전트 시스템이 연속 ${CONSECUTIVE_FAILURES}회 크래시. 수동 점검 필요.\"}" \
            > /dev/null 2>&1 || true
    fi

    log "Restarting in ${BACKOFF}s..."
    sleep "$BACKOFF"
done
