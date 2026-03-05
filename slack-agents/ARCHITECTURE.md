# Slack AI Agents - 자율 협업 에이전트 시스템 아키텍처

## 개요

슬랙을 중심으로 여러 AI 에이전트가 자율적으로 판단하고, 서로 협업하며,
24시간 정보를 수집·선별하는 멀티 에이전트 시스템.

```
┌─────────────────────────────────────────────────────────────────┐
│                        사용자 (You)                              │
│   슬랙 메시지로 지시  /  노션 액션아이템으로 지시                     │
└────────┬──────────────────────────────────┬─────────────────────┘
         │                                  │
    ┌────▼────┐                      ┌──────▼──────┐
    │  Slack  │◄────────────────────►│   Notion    │
    │  (소통) │                      │ (결과 저장) │
    └────┬────┘                      └──────┬──────┘
         │                                  │
    ┌────▼──────────────────────────────────▼────┐
    │          Agent Orchestrator (24/7)          │
    │  ┌─────────────────────────────────────┐   │
    │  │         Message Bus (내부)           │   │
    │  │   에이전트 간 작업 요청/결과 전달      │   │
    │  └──┬──────────────┬───────────────┬───┘   │
    │     │              │               │       │
    │  ┌──▼───┐    ┌─────▼────┐    ┌─────▼────┐  │
    │  │수집   │    │선별      │    │ (확장)   │  │
    │  │Agent │◄──►│Agent    │◄──►│ Agent N  │  │
    │  └──────┘    └──────────┘    └──────────┘  │
    └────────────────────────────────────────────┘
```

## 핵심 설계 원칙

### 1. 에이전트 자율성 (Autonomy)
- 각 에이전트는 **자체 판단 루프**를 가짐 (Observe → Think → Act)
- Claude AI를 "두뇌"로 사용하여 상황 판단, 작업 정의, 실행 결정
- 정해진 스케줄 없이도 새로운 상황 감지 시 자율 행동

### 2. 에이전트 간 협업 (Collaboration)
- 내부 Message Bus를 통해 에이전트 간 작업 요청/결과 전달
- 슬랙 채널에서 에이전트 간 대화 가시화 (사람도 볼 수 있음)
- Supabase `agent_tasks` 테이블로 작업 추적

### 3. 소통 채널
- **슬랙**: 모든 소통의 중심 (에이전트↔사람, 에이전트↔에이전트)
- **노션**: 결과물 저장, 액션아이템 관리, 상세 보고서
- **Supabase**: 에이전트 상태, 학습 데이터, 작업 큐

---

## 시스템 구성요소

### 1. Agent Base Class (`core/base_agent.py`)
모든 에이전트의 공통 기능:

```python
class BaseAgent:
    # 자율 판단 루프
    async def run_loop():
        while True:
            context = await self.observe()     # 환경 감지
            decision = await self.think(context)  # AI 판단
            await self.act(decision)           # 실행
            await asyncio.sleep(interval)

    # 슬랙 소통
    async def say(channel, message)
    async def ask_agent(agent_name, task)

    # 노션 연동
    async def save_to_notion(database_id, data)
    async def read_notion_tasks()

    # AI 판단
    async def think(context) -> Decision
```

### 2. Message Bus (`core/message_bus.py`)
에이전트 간 비동기 통신:

```
TaskRequest  → { from: "curator", to: "collector", task: "AI 관련 뉴스 더 수집해줘" }
TaskResult   → { from: "collector", to: "curator", result: [...articles] }
Broadcast    → { from: "collector", event: "new_articles", data: [...] }
```

### 3. Slack Integration (`integrations/slack_client.py`)
- Slack Bolt (Socket Mode) 사용 → 웹훅 서버 불필요
- 에이전트별 전용 채널 + 공용 협업 채널
- 슬래시 커맨드로 직접 지시 가능

### 4. Notion Integration (`integrations/notion_client.py`)
- 수집 결과 데이터베이스 저장
- 액션아이템 읽기/업데이트
- 선별 결과 보고서 페이지 생성

---

## 에이전트 상세

### Agent 1: 정보 수집 에이전트 (Collector)

**역할**: 뉴스, 사업공고, 채용정보 등 다양한 소스에서 정보 수집

**자율 행동**:
- 주기적으로 등록된 소스 크롤링
- 다른 에이전트 요청 시 특정 주제 집중 수집
- 새로운 소스 발견 시 자동 등록 제안

**Observe**: RSS 피드, 웹 크롤링, API 호출
**Think**: "새로운 정보가 있는가? 요청받은 주제가 있는가?"
**Act**: 수집 → Supabase 저장 → 슬랙 알림 → 선별 에이전트에 전달

### Agent 2: 정보 선별 에이전트 (Curator)

**역할**: 수집된 정보 중 사용자에게 가치 있는 것 선별

**자율 행동**:
- 수집된 정보 자동 분석 및 점수 매기기
- 사용자 피드백 학습 (슬랙 이모지 반응 추적)
- 부족한 정보 영역 파악 → 수집 에이전트에 추가 요청

**Observe**: 새로 수집된 정보, 사용자 피드백, 노션 액션아이템
**Think**: "이 정보가 사용자에게 가치 있는가? 어떤 정보가 부족한가?"
**Act**: 선별 → 요약 작성 → 노션 저장 → 슬랙 브리핑 → 추가 수집 요청

---

## 슬랙 채널 구조

```
#ai-agents-general    ← 에이전트 간 협업 대화, 사용자 지시
#ai-collector         ← 수집 에이전트 알림 (새 정보 발견)
#ai-curator           ← 선별 에이전트 브리핑 (일간/주간 리포트)
#ai-agent-logs        ← 에이전트 내부 동작 로그 (디버깅용)
```

---

## 데이터 흐름

```
1. 수집 에이전트가 RSS/웹에서 뉴스 수집
       ↓
2. Supabase collected_items에 저장
       ↓
3. Message Bus로 선별 에이전트에 "새 정보 도착" 알림
       ↓
4. 선별 에이전트가 Claude AI로 관련성/가치 판단
       ↓
5. 높은 가치 정보 → 노션 데이터베이스에 저장
       ↓
6. 슬랙 #ai-curator 채널에 선별 결과 브리핑
       ↓
7. 부족한 영역 발견 시 → 수집 에이전트에 추가 수집 요청
       ↓
8. 사용자가 슬랙 이모지(👍/👎)로 피드백
       ↓
9. 선별 에이전트가 피드백 학습하여 기준 업데이트
```

---

## 배포 방식

**Docker Compose**로 24/7 실행:
- `orchestrator` 컨테이너: 메인 루프 + 모든 에이전트
- Slack Socket Mode 사용 → 인바운드 포트 불필요
- Supabase Cloud 사용 → DB 별도 운영 불필요

---

## 필요 API 키

| 서비스 | 환경변수 | 용도 |
|--------|---------|------|
| Slack | `SLACK_BOT_TOKEN` | Bot OAuth Token (xoxb-...) |
| Slack | `SLACK_APP_TOKEN` | App-Level Token (xapp-...) |
| Notion | `NOTION_API_KEY` | Internal Integration Token |
| Claude | `ANTHROPIC_API_KEY` | AI 판단 엔진 |
| Supabase | `SUPABASE_URL` | 데이터 저장소 |
| Supabase | `SUPABASE_SERVICE_ROLE_KEY` | 서비스 인증 |

---

## Supabase 추가 테이블

```sql
-- 에이전트 간 작업 큐
create table agent_tasks (
  id uuid primary key default gen_random_uuid(),
  from_agent text not null,
  to_agent text not null,
  task_type text not null,
  payload jsonb not null default '{}',
  status text not null default 'pending',  -- pending, in_progress, completed, failed
  result jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- 수집된 원본 정보
create table collected_items (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  source_type text not null,  -- rss, web, api
  title text not null,
  url text,
  content text,
  metadata jsonb default '{}',
  collected_at timestamptz default now(),
  hash text unique not null  -- 중복 방지
);

-- 선별된 정보 + 사용자 피드백
create table curated_items (
  id uuid primary key default gen_random_uuid(),
  collected_item_id uuid references collected_items(id),
  relevance_score float not null,
  ai_summary text,
  ai_reasoning text,
  user_feedback int,  -- +1, -1, null
  notion_page_id text,
  curated_at timestamptz default now()
);

-- 선별 기준 학습 데이터
create table curation_preferences (
  id uuid primary key default gen_random_uuid(),
  category text not null,
  keywords jsonb default '[]',
  weight float default 1.0,
  learned_from text,  -- 'user_feedback', 'explicit_instruction'
  updated_at timestamptz default now()
);
```
