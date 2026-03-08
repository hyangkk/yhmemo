#!/bin/bash
# Claude Code 세션 시작 시 Supabase에서 시크릿을 로드하여 환경변수로 설정
# 사용법: source scripts/fetch-secrets.sh

set -euo pipefail

# Supabase 접속 정보 (CLAUDE.md 또는 GitHub Secrets에서 관리)
SUPABASE_URL="${SUPABASE_URL:-}"
SUPABASE_SERVICE_ROLE_KEY="${SUPABASE_SERVICE_ROLE_KEY:-}"

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_SERVICE_ROLE_KEY" ]; then
  echo "[fetch-secrets] SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY가 설정되지 않았습니다." >&2
  echo "[fetch-secrets] GitHub Secrets에서 이 값들을 먼저 설정해주세요." >&2
  exit 1
fi

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

echo "[fetch-secrets] ${COUNT}개 시크릿 로드 완료"
