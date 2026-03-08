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
