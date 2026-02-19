# yhmemo - 뉴스 아이디어 에이전트

매 시간 자동으로 한국 주요 뉴스 3개를 수집하여 Claude AI가 새로운 아이디어를 도출하고, Supabase에 저장 후 텔레그램으로 발송하는 에이전트입니다.

---

## 동작 방식

```
매 시간 정각 (GitHub Actions 자동 실행)
    ↓
Supabase agent_settings에서 설정 로드
    ↓
KBS / MBC / SBS / JTBC / 연합뉴스 RSS에서 최신 뉴스 3개 수집
    ↓
Claude AI가 3개 뉴스를 분석·결합하여 창의적 아이디어 도출
    ↓
Supabase news_ideas 테이블에 저장
    ↓
텔레그램 봇으로 결과 발송
```

---

## 설정 방법

### 1. Supabase 테이블 생성

Supabase 대시보드 → **SQL Editor** 에서 아래 SQL 실행:

```sql
-- 뉴스 아이디어 저장 테이블
create table news_ideas (
  id uuid primary key default gen_random_uuid(),
  generated_at timestamptz not null,
  news_items jsonb not null,
  idea text not null,
  created_at timestamptz default now()
);

-- 에이전트 설정 테이블
create table agent_settings (
  id int primary key default 1,
  enabled boolean not null default true,
  run_every_hours int not null default 1,
  active_sources jsonb not null default '["KBS","MBC","SBS","JTBC","연합뉴스"]',
  prompt_template text not null default '',
  updated_at timestamptz default now()
);

insert into agent_settings (id) values (1);
```

### 2. 텔레그램 봇 설정

1. 텔레그램에서 **@BotFather** 에게 `/newbot` 명령 → 봇 토큰 발급
2. 봇에게 메시지를 보낸 후, `https://api.telegram.org/bot<TOKEN>/getUpdates` 에서 `chat_id` 확인

### 3. GitHub Secrets 설정

저장소의 **Settings → Secrets and variables → Actions** 에서 아래 시크릿 추가:

| 시크릿 이름 | 값 위치 |
|---|---|
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) |
| `SUPABASE_URL` | Supabase → Integrations → Data API → Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase → Settings → API Keys → `sb_secret_...` 키 |
| `TELEGRAM_BOT_TOKEN` | BotFather에서 발급받은 봇 토큰 |
| `TELEGRAM_CHAT_ID` | getUpdates API로 확인한 chat_id |

### 4. 설정 웹페이지 활성화 (GitHub Pages)

저장소의 **Settings → Pages** 에서:
- Source: `Deploy from a branch`
- Branch: `main` / `docs` 폴더 선택 → Save

이후 `https://hyangkk.github.io/yhmemo/` 에서 설정 페이지에 접근할 수 있습니다.

---

## 설정 웹페이지

GitHub Pages를 활성화하면 웹 UI에서 아래 항목을 실시간으로 변경할 수 있습니다:

- **전체 기능 ON/OFF** — 에이전트 일시 중단
- **실행 주기** — 1시간 / 2시간 / 3시간 / 6시간 / 12시간 / 하루 1회
- **뉴스 소스** — KBS, MBC, SBS, JTBC, 연합뉴스 개별 ON/OFF
- **AI 프롬프트** — 아이디어 생성 방식 직접 수정 (`{news_block}` 위치에 뉴스 삽입)

---

## 수동 실행

GitHub Actions 탭 → **뉴스 아이디어 에이전트** → **Run workflow** 버튼으로 즉시 실행할 수 있습니다.

---

## 프로젝트 구조

```
yhmemo/
├── .github/
│   └── workflows/
│       └── news-idea-agent.yml   # 매 시간 실행되는 워크플로우
├── docs/
│   └── index.html                # 설정 웹페이지 (GitHub Pages)
└── scripts/
    └── news_idea_agent.py        # 뉴스 수집 + AI 아이디어 생성 스크립트
```
