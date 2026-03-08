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

## 배포 가이드

### 토큰 로드 (세션 시작 시 자동, 수동 필요 시)
```bash
source /home/user/yhmemo/scripts/fetch-secrets.sh
```
- Supabase `secrets_vault`에서 `GH_TOKEN`, `ANTHROPIC_API_KEY` 등 자동 로드
- SUPABASE_URL/KEY 기본값이 스크립트에 내장되어 있어 별도 설정 불필요

### PR 생성 (gh CLI 안 될 때 curl 사용)
```bash
source scripts/fetch-secrets.sh
curl -s -X POST https://api.github.com/repos/hyangkk/yhmemo/pulls \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -d '{"title":"...", "head":"브랜치명", "base":"main", "body":"..."}'
```
- 로컬 git remote가 프록시(`127.0.0.1:28810`)라서 `gh` CLI가 GitHub 호스트 인식 불가 → curl 직접 사용
- main 브랜치 직접 push 불가 (branch protection) → 반드시 PR 통해 머지

### PR 머지 (curl)
```bash
curl -s -X PUT https://api.github.com/repos/hyangkk/yhmemo/pulls/{PR번호}/merge \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -d '{"merge_method":"squash"}'
```

### 서비스별 자동 배포 (main 머지 시 GitHub Actions 자동 실행)

| 서비스 | 워크플로우 | 배포 대상 | 트리거 조건 |
|--------|-----------|----------|------------|
| **slack-agents** | `.github/workflows/deploy-slack-agents.yml` | Fly.io (`yhmbp14`, 도쿄 nrt) | `slack-agents/**` 변경 시 |
| **web-service** | `.github/workflows/deploy-web-service.yml` | Vercel | `web-service/**` 변경 시 |
| **webhook** | `.github/workflows/deploy-webhook.yml` | - | 관련 파일 변경 시 |

### 수동 배포 (필요 시)
```bash
# Fly.io (slack-agents)
source scripts/fetch-secrets.sh
cd slack-agents && flyctl deploy  # FLY_API_TOKEN 필요

# flyctl 미설치 시
curl -L https://fly.io/install.sh | sh
export PATH="/root/.fly/bin:$PATH"
```

### 주의사항
- `GH_TOKEN`이 만료되면 Supabase Dashboard → `secrets_vault` 테이블에서 갱신
- main에 직접 push 불가 → PR 생성 후 머지만 가능
- 머지하면 해당 경로 변경에 따라 자동 배포 워크플로우 실행됨
