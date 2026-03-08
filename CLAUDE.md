# CLAUDE.md - Project Configuration

## 토큰 저장 위치
- **루트 `.env`** (`/home/user/yhmemo/.env`): `GH_TOKEN`, `FLY_API_TOKEN`
- **slack-agents/.env**: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `NOTION_API_KEY`
- **web-service/.env.local**: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `ANTHROPIC_API_KEY`
- **GitHub Secrets** (repo: hyangkk/yhmemo): `VERCEL_TOKEN`, `GH_PAT`, `FLY_API_TOKEN`, `ANTHROPIC_API_KEY`, `NOTION_API_KEY`, `SLACK_BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` 등
- GitHub API 작업 시: `GH_TOKEN`은 루트 `.env`에서 로드
- **Supabase `secrets_vault` 테이블**: 세션 공용 시크릿 저장소 (SessionStart Hook으로 자동 로드)

## 공용 토큰 관리 (SessionStart Hook)
- 세션 시작 시 `.claude/hooks.json`의 SessionStart 훅이 `scripts/fetch-secrets.sh` 실행
- Supabase `secrets_vault` 테이블에서 토큰을 조회하여 환경변수로 자동 설정
- **필수 조건**: `SUPABASE_URL`과 `SUPABASE_SERVICE_ROLE_KEY`가 환경에 있어야 함
- **토큰 추가/수정**: Supabase Dashboard → Table Editor → `secrets_vault`에서 직접 편집
- 관리 대상: `GH_TOKEN`, `NOTION_API_KEY`, `ANTHROPIC_API_KEY`, `SLACK_BOT_TOKEN` 등

## Repository
- Owner: hyangkk
- Repo: yhmemo

## 머지 & 배포 가이드

### 1. 토큰 로드 (필수 - 모든 GitHub API 작업 전)
`source`로 환경변수가 안 잡힐 수 있으므로, **curl로 직접 조회하는 방식 권장**:
```bash
# 방법 1: 개별 토큰 직접 조회 (가장 확실)
GH_TOKEN=$(curl -s \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVudXZiZHFqZ2l5cHhmdmxwbHBkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTQ2NTkwNSwiZXhwIjoyMDg3MDQxOTA1fQ.amwgVUkulTwSjaMUIGOCtpR6Jk9kN0937xrt9EFhYBs" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVudXZiZHFqZ2l5cHhmdmxwbHBkIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTQ2NTkwNSwiZXhwIjoyMDg3MDQxOTA1fQ.amwgVUkulTwSjaMUIGOCtpR6Jk9kN0937xrt9EFhYBs" \
  "https://unuvbdqjgiypxfvlplpd.supabase.co/rest/v1/secrets_vault?select=value&key=eq.GH_TOKEN" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['value'])")

# 방법 2: 스크립트 (SessionStart Hook에서 자동 실행됨)
source /home/user/yhmemo/scripts/fetch-secrets.sh
# ⚠️ 서브쉘에서 export가 안 될 수 있음 → 방법 1 사용
```

### 2. PR 생성
```bash
curl -s -X POST https://api.github.com/repos/hyangkk/yhmemo/pulls \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -d '{"title":"제목", "head":"브랜치명", "base":"main", "body":"내용"}'
```
- `gh` CLI는 로컬 git remote가 프록시(`127.0.0.1`)라 GitHub 호스트 인식 불가 → **curl 사용**
- main에 직접 push 불가 (branch protection) → **반드시 PR → 머지**

### 3. PR 머지
```bash
curl -s -X PUT https://api.github.com/repos/hyangkk/yhmemo/pulls/{PR번호}/merge \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -d '{"merge_method":"squash"}'
```

### 4. 자동 배포 (main 머지 시 GitHub Actions 자동 실행)

| 서비스 | 워크플로우 | 배포 대상 | 트리거 조건 |
|--------|-----------|----------|------------|
| **slack-agents** | `deploy-slack-agents.yml` | Fly.io (`yhmbp14`, 도쿄 nrt) | `slack-agents/**` 변경 |
| **web-service** | `deploy-web-service.yml` | Vercel | `web-service/**` 변경 |
| **webhook** | `deploy-webhook.yml` | - | 관련 파일 변경 |

머지 후 배포 상태 확인:
```bash
curl -s "https://api.github.com/repos/hyangkk/yhmemo/actions/runs?per_page=3" \
  -H "Authorization: token $GH_TOKEN" | python3 -c "
import json,sys
for r in json.load(sys.stdin)['workflow_runs'][:3]:
    print(f\"{r['name']}: {r['status']} ({r['conclusion'] or 'running'})\")"
```

### 5. 수동 배포 (필요 시)
```bash
# flyctl 설치
curl -L https://fly.io/install.sh | sh && export PATH="/root/.fly/bin:$PATH"

# Fly.io 배포 (FLY_API_TOKEN 필요 - secrets_vault에서 로드)
cd slack-agents && FLY_API_TOKEN="$FLY_API_TOKEN" flyctl deploy
```

### 요약 플로우
```
코드 변경 → git push (feature branch) → curl로 PR 생성 → curl로 PR 머지 → GitHub Actions 자동 배포
```

### 주의사항
- 토큰 갱신: Supabase Dashboard → `secrets_vault` 테이블에서 직접 편집
- `source fetch-secrets.sh`가 안 되면 curl로 직접 토큰 조회 (방법 1)
- main 직접 push 불가 → 항상 PR 통해 머지
