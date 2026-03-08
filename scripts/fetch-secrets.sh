#!/bin/bash
# Claude Code 세션 시작 시 Supabase에서 시크릿을 로드하여 환경변수로 설정
# 사용법: source scripts/fetch-secrets.sh

set -euo pipefail

# Supabase 접속 정보
# URL은 공개 정보이므로 기본값으로 설정
SUPABASE_URL="${SUPABASE_URL:-https://unuvbdqjgiypxfvlplpd.supabase.co}"
export SUPABASE_URL

# Service Role Key: 환경변수 → .env 파일 순서로 탐색
if [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  # slack-agents/.env에서 찾기
  ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/slack-agents/.env"
  if [ -f "$ENV_FILE" ]; then
    SUPABASE_SERVICE_ROLE_KEY=$(grep -m1 '^SUPABASE_SERVICE_ROLE_KEY=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' || true)
  fi
fi
if [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  # web-service/.env.local에서 찾기
  ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/web-service/.env.local"
  if [ -f "$ENV_FILE" ]; then
    SUPABASE_SERVICE_ROLE_KEY=$(grep -m1 '^SUPABASE_SERVICE_ROLE_KEY=' "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' || true)
  fi
fi

if [ -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]; then
  echo "[fetch-secrets] SUPABASE_SERVICE_ROLE_KEY를 찾을 수 없습니다." >&2
  echo "[fetch-secrets] GitHub Secrets 또는 slack-agents/.env에 설정해주세요." >&2
  exit 1
fi
export SUPABASE_SERVICE_ROLE_KEY

# Supabase REST API로 시크릿 조회
RESPONSE=$(curl -s \
  -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  "${SUPABASE_URL}/rest/v1/secrets_vault?select=key,value&value=not.is.null" \
)

if [ -z "$RESPONSE" ] || echo "$RESPONSE" | grep -q '"message"'; then
  echo "[fetch-secrets] 시크릿 조회 실패: $RESPONSE" >&2
  exit 1
fi

# JSON 응답을 파싱하여 환경변수로 export
# jq가 없으면 python3 사용
if command -v jq &>/dev/null; then
  eval "$(echo "$RESPONSE" | jq -r '.[] | "export \(.key)=\(.value | @sh)"')"
  COUNT=$(echo "$RESPONSE" | jq length)
elif command -v python3 &>/dev/null; then
  eval "$(python3 -c "
import json, shlex, sys
data = json.loads(sys.stdin.read())
for item in data:
    if item.get('value'):
        print(f\"export {item['key']}={shlex.quote(item['value'])}\")
" <<< "$RESPONSE")"
  COUNT=$(python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())))" <<< "$RESPONSE")
else
  echo "[fetch-secrets] jq 또는 python3이 필요합니다." >&2
  exit 1
fi

# SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY도 export 유지
export SUPABASE_URL
export SUPABASE_SERVICE_ROLE_KEY
echo "[fetch-secrets] ${COUNT}개 시크릿 로드 완료 (SUPABASE_URL/KEY 포함)"
