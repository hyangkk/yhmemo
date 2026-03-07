# CLAUDE.md - Project Configuration

## 토큰 저장 위치
- **루트 `.env`** (`/home/user/yhmemo/.env`): `GH_TOKEN`, `FLY_API_TOKEN`
- **slack-agents/.env**: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `NOTION_API_KEY`
- **web-service/.env.local**: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `ANTHROPIC_API_KEY`
- **GitHub Secrets** (repo: hyangkk/yhmemo): `VERCEL_TOKEN`, `GH_PAT`, `FLY_API_TOKEN`, `ANTHROPIC_API_KEY`, `NOTION_API_KEY`, `SLACK_BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` 등
- GitHub API 작업 시: `GH_TOKEN`은 루트 `.env`에서 로드

## Repository
- Owner: hyangkk
- Repo: yhmemo
