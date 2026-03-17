# CLAUDE.md - Project Configuration

## 핵심 원칙

### 0. 한국어 소통 (Korean Communication)
- **사용자와의 모든 소통은 한국어로 한다.** 코드 주석, 커밋 메시지, 보고, 질문 등 모두 한국어 사용.
- 코드 변수명/함수명은 영어 OK, 그 외 사람이 읽는 텍스트는 한국어.

### 1. 자연어 우선 (Natural Language First)
- **모든 기능은 자연어로 호출 가능해야 한다.** `!명령어`는 단축키일 뿐, 사용자는 자연어로 항상 동일한 기능을 사용할 수 있어야 함.
- 예: "비트코인 시장 분위기 알려줘" = `!센티멘트 bitcoin` = "소셜 센티멘트 분석해줘"
- 새 기능 추가 시 반드시 자연어 인식 패턴도 함께 구현할 것.

### 2. 애매하면 질문하기 (Clarify Before Acting)
- 사용자의 자연어가 **애매하거나 여러 해석이 가능**하면, 바로 실행하지 말고 **질문으로 의도를 확인**한다.
- 예: "삼성 알려줘" → "삼성전자(005930) 시세를 조회할까요, 아니면 삼성전자 관련 뉴스/센티멘트를 분석할까요?"
- 단, 명확한 의도가 파악되면 바로 실행. 불필요한 질문은 하지 않는다.

### 3. 슬랙 봇 기능 구축 규칙
- 모든 새 기능은 `!명령어` + 자연어 인식 두 가지 모두 지원
- 자연어 처리는 `orchestrator.py`의 `on_natural_language()` 함수에서 Claude AI가 판단
- 투자/시세 기능은 `ai-invest` 채널, 일반 기능은 `ai-agents-general` 채널

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

## 코드 변경 안전 수칙 (필수)

### 리베이스/머지 충돌 해결 시
- **충돌 해결 후 반드시 `git diff`로 의도하지 않은 삭제가 없는지 확인**한다.
- 특히 UI 코드(JSX/TSX)에서 충돌 마커 제거 시 **양쪽 코드를 모두 검토**하고, 필요한 코드가 날아가지 않았는지 확인.
- `<<<<<<< HEAD`와 `>>>>>>>` 사이에서 "어느 쪽을 선택"이 아니라 **"양쪽을 어떻게 합칠 것인가"**를 판단할 것.

### PR 머지 후 검증
- squash 머지 후 같은 브랜치에서 추가 커밋 → **반드시 main을 rebase/pull** 한 뒤 충돌 여부 확인.
- 머지 후 변경된 파일의 **핵심 UI/기능이 그대로 살아있는지** 빠르게 확인 (grep 등).

### 코드 삭제 시
- 기능을 삭제할 때 **해당 기능의 UI, 백엔드, 상태 관리를 모두 같이 정리**한다. 하나만 지우고 나머지를 남기지 않는다.
- 반대로, 실수로 관련 코드를 같이 삭제하지 않도록 **삭제 범위를 명확히** 한다.

## 배포 & 검증 필수 수칙

### PR 머지 후 반드시 배포 성공 확인
- PR 머지 후 **배포 완료까지 확인**해야 함. 머지만 하고 "완료"로 보고하지 말 것.
- 배포 실패 시 즉시 로그 확인하고 수정 → 재배포.
- **배포 성공 확인 방법**: GitHub Actions 워크플로우 상태가 `completed (success)`인지 확인.

### TypeScript 빌드 검증
- 코드 변경 후 PR 전에 반드시 `npx tsc --noEmit` 으로 타입 에러가 없는지 확인.
- Supabase 쿼리 빌더는 `PromiseLike`를 반환하므로 `.catch()`를 쓰려면 `Promise.resolve()`로 감싸야 함.
- 외부 라이브러리 API의 반환 타입을 가정하지 말고 실제 타입을 확인할 것.

### Supabase 클라이언트 사용 주의사항
- **`onAuthStateChange` 콜백은 반드시 동기 함수로 작성**. `async` 콜백을 쓰면 Supabase 내부 exclusive lock과 데드락 발생.
- 콜백 안에서 DB 호출이 필요하면 `.then()` 체인으로 콜백 밖에서 비동기 실행.
- `getSession()`은 `INITIAL_SESSION` 이벤트 전에 호출하면 null을 반환할 수 있음.

### 실제 동작 확인 원칙
- 웹 서비스 변경 시: 배포 후 실제 URL에서 기능 동작 확인.
- "코드상 맞는 것 같다"는 보고 금지. **실제 화면에서 확인한 결과**를 보고.
- QA 에이전트를 쓸 경우에도 **빌드 성공 여부를 반드시 포함**시킬 것.

## 슬랙 봇 테스트 가이드

### 테스트 채널
- **투자/시세 관련 기능**: `ai-invest` 채널 (C0AKRJZ395W)에서 테스트
- **일반 기능**: `ai-agents-general` 채널 (C0AJJ469SV8)에서 테스트
- 테스트는 반드시 해당 기능의 전용 채널에서 수행할 것

### 봇 토큰으로 테스트 메시지 보내기
봇은 자신의 메시지를 기본적으로 무시하지만, 다음 접두사는 허용:
- `!` 명령어 (예: `!시세조회 005930`)
- `[마스터]` 접두사 (예: `[마스터] 삼성전자 주가 조회`)

```python
# 테스트 스크립트 예시 (slack-agents/test_price.py 참고)
SLACK_BOT_TOKEN=... python3 test_price.py
```

### 기능 개발 완료 보고 원칙 (필수)
- **슬랙 관련 기능은 반드시 슬랙에서 직접 테스트 후 보고**: 해당 채널에 메시지를 보내고 봇 응답을 확인해야 함
- 코드 배포만으로 "완료"로 보고하지 말 것 → 실제 동작 확인 필수
- 테스트 시 봇 토큰으로 `!명령어` 또는 `[마스터]` 접두사를 사용하여 메시지 전송
- 봇 응답을 받아서 기대 결과와 일치하는지 확인한 후에만 사용자에게 보고
