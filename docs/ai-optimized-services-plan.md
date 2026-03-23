# AI 에이전트를 위한 필수 서비스 기획서

> **관점 전환**: 기존 인간용 서비스를 에이전트에 맞추는 게 아니다.
> AI 에이전트가 **존재하고 작동하기 위해 반드시 필요한 것**을 만든다.

---

## 에이전트에게 없으면 안 되는 것들

사람에게 물, 공기, 집이 필수이듯 — AI 에이전트에게도 기본 생존 인프라가 있다.

```
사람의 필수          에이전트의 필수
────────────        ──────────────
기억               → Memory (기억 저장소)
신분증             → Identity (누구인지, 뭘 할 수 있는지)
언어               → Protocol (다른 에이전트와 소통하는 방법)
지갑               → Wallet (대신 돈을 쓸 수 있는 능력)
감각기관           → Perception (세상의 변화를 감지하는 능력)
도구               → Tools (실제로 무언가를 실행하는 능력)
```

현재 시장에 이것들을 **통합적으로 제공하는 서비스가 없다.** 각각 파편화되어 있다.

---

## 서비스 1: Agent Memory (에이전트 기억 저장소)

### 왜 필수인가
- 에이전트는 **세션이 끝나면 모든 것을 잊는다**
- 매번 같은 질문을 다시 하고, 같은 실수를 반복한다
- "지난번에 이 사용자가 뭘 좋아했지?"를 기억 못 한다

### 현재 시장의 빈틈
- OpenAI Memory: 자사 에이전트 전용, 폐쇄적
- Mem0, Zep: 개인 메모리만 지원, 에이전트 간 공유 불가
- Supabase/Pinecone: 범용 DB이지 에이전트 메모리 특화가 아님

### 우리가 만드는 것

```
┌─────────────────────────────────────────────────┐
│              Agent Memory Service                │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │
│  │ 단기기억  │  │ 장기기억  │  │ 공유기억      │  │
│  │ (세션)   │  │ (영구)   │  │ (에이전트간)  │  │
│  │          │  │          │  │               │  │
│  │ 대화맥락 │  │ 사용자    │  │ "A가 알아낸   │  │
│  │ 작업상태 │  │ 선호도    │  │  것을 B도     │  │
│  │ 중간결과 │  │ 학습데이터│  │  안다"        │  │
│  └──────────┘  └──────────┘  └───────────────┘  │
│                                                  │
│  검색 방식:                                       │
│  - 키 기반: get("user_preference:stock_style")   │
│  - 시맨틱: recall("지난주 비트코인 분석 결과")      │
│  - 시간 기반: recent("market_insight", hours=24)  │
│                                                  │
│  자동 관리:                                       │
│  - TTL 기반 만료 (중요도에 따라 자동 조절)          │
│  - 중복 제거 (같은 내용 여러번 저장 방지)           │
│  - 요약 압축 (오래된 기억을 요약본으로 압축)         │
└─────────────────────────────────────────────────┘
```

### API

```
POST   /memory/store     — 기억 저장
POST   /memory/recall    — 기억 검색 (키/시맨틱/시간)
POST   /memory/share     — 다른 에이전트와 기억 공유
DELETE /memory/forget     — 기억 삭제
GET    /memory/stats      — 메모리 사용량 확인
```

### 데이터 모델

```sql
create table agent_memory (
  id uuid primary key default gen_random_uuid(),
  agent_id text not null,
  owner_id text,                    -- 어떤 사용자의 맥락인지
  namespace text not null,          -- 'session', 'long_term', 'shared'
  key text not null,
  value jsonb not null,
  embedding vector(1536),           -- 시맨틱 검색용
  importance float default 0.5,     -- 0~1, 높을수록 오래 보관
  access_count int default 0,       -- 자주 조회되면 중요도 상승
  ttl interval,
  created_at timestamptz default now(),
  last_accessed_at timestamptz default now(),
  unique(agent_id, namespace, key)
);
```

---

## 서비스 2: Agent Identity & Registry (에이전트 신분증)

### 왜 필수인가
- 에이전트가 다른 에이전트/서비스에 "나는 누구이고 이것을 할 수 있다"를 증명할 방법이 없다
- 사용자가 "이 에이전트에게 내 주식 계좌 접근을 허용할까?"를 판단할 정보가 없다
- 에이전트끼리 협업하려면 상대가 무엇을 잘하는지 알아야 한다

### 우리가 만드는 것

```json
// 에이전트 신분증 예시
{
  "agent_id": "invest-analyst-v2",
  "display_name": "투자 분석 에이전트",
  "capabilities": [
    "market_analysis",
    "sentiment_analysis",
    "news_curation",
    "price_alert"
  ],
  "permissions": {
    "can_read": ["market_data", "news", "social_sentiment"],
    "can_write": ["alerts", "reports"],
    "can_execute": ["price_lookup", "sentiment_scan"],
    "cannot": ["trade_execution", "fund_transfer"]
  },
  "trust_score": 0.92,
  "created_by": "hyangkk",
  "verified": true,
  "usage_stats": {
    "total_calls": 15420,
    "success_rate": 0.97,
    "avg_response_ms": 340
  }
}
```

### Agent Registry (에이전트 전화번호부)

```
GET  /registry/search?capability=sentiment_analysis
→ "센티멘트 분석 잘하는 에이전트 찾아줘"

GET  /registry/agent/{agent_id}
→ 특정 에이전트의 상세 프로필

POST /registry/register
→ 새 에이전트 등록

POST /registry/delegate
→ "이 작업은 저 에이전트한테 맡길게"
```

**핵심 가치**: 에이전트가 **혼자 못하는 일을 다른 에이전트를 찾아서 위임**할 수 있다.

---

## 서비스 3: Agent Protocol Hub (에이전트 소통 프로토콜)

### 왜 필수인가
- MCP, OpenAI Function Calling, LangChain Tools — 프로토콜이 파편화됨
- 에이전트 A가 MCP를 쓰고 에이전트 B가 Function Calling을 쓰면 대화가 안 된다
- **통역사**가 필요하다

### 우리가 만드는 것

```
┌─────────────────────────────────────────────────┐
│              Agent Protocol Hub                  │
│                                                  │
│  외부 에이전트 ──→ ┌─────────────┐ ──→ 내부 서비스│
│                    │  Protocol   │               │
│  MCP ─────────→   │  Adapter    │ ──→ 시세조회   │
│  OpenAI Tools ──→  │  Layer      │ ──→ 센티멘트  │
│  REST API ────→   │             │ ──→ 뉴스검색   │
│  A2A Protocol ──→  │             │ ──→ 메모리     │
│                    └─────────────┘               │
│                                                  │
│  지원 프로토콜:                                    │
│  1. MCP (Model Context Protocol) — Claude 네이티브│
│  2. OpenAI Function Calling — GPT 호환            │
│  3. REST + JSON Schema — 범용                     │
│  4. Google A2A — Agent-to-Agent 통신              │
│  5. SSE Event Stream — 실시간 이벤트              │
└─────────────────────────────────────────────────┘
```

### 자기 서술형 매니페스트

에이전트가 이 URL 하나만 알면 모든 것을 파악:

```
GET /well-known/agent.json

→ 이 서비스에 무엇이 있는지 (capabilities)
→ 각각 어떻게 호출하는지 (schemas)
→ 어떤 프로토콜을 지원하는지 (protocols)
→ 인증은 어떻게 하는지 (auth)
→ 언제 이걸 써야 하는지 (use_when)
→ 무엇과 조합하면 좋은지 (combine_with)
```

---

## 서비스 4: Agent Wallet (에이전트 지갑)

### 왜 필수인가
- 에이전트가 사용자 대신 유료 API를 호출하려면 **결제 수단**이 필요
- "이 분석을 위해 뉴스 API에 $0.02를 쓸 건데 허용할까?"
- 현재는 사람이 직접 API 키를 넣어줘야 하지만, 에이전트가 자율적으로 판단하려면 **예산 개념**이 필요

### 우리가 만드는 것

```
┌─────────────────────────────────────────────────┐
│                Agent Wallet                      │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │  사용자 설정                               │    │
│  │  - 일일 예산: ₩10,000                     │    │
│  │  - 단건 한도: ₩1,000                      │    │
│  │  - 허용 카테고리: [시장분석, 뉴스, 알림]    │    │
│  │  - 차단 카테고리: [매매실행]                │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  에이전트 요청 흐름:                               │
│  1. 에이전트: "뉴스 API 호출에 ₩50 필요"          │
│  2. Wallet: 예산 확인 → 카테고리 확인 → 승인       │
│  3. 에이전트: API 호출 실행                        │
│  4. Wallet: 잔액 차감 + 사용 로그 기록             │
│                                                  │
│  예산 초과 시:                                    │
│  - 사용자에게 슬랙/푸시 알림                       │
│  - "오늘 예산의 80%를 사용했습니다"                 │
│  - 자동 차단 또는 승인 요청                        │
└─────────────────────────────────────────────────┘
```

---

## 서비스 5: Agent Perception (에이전트 감각기관)

### 왜 필수인가
- 에이전트는 **요청이 올 때만 반응**하는 게 한계 — 스스로 세상을 감지해야 한다
- "비트코인 10% 폭락" 같은 이벤트를 **능동적으로 감지**해서 행동해야 한다
- 현재 슬랙 에이전트들이 개별적으로 크롤링하지만, 이걸 **공통 인프라**로 만들어야 한다

### 우리가 만드는 것

```
┌─────────────────────────────────────────────────┐
│              Agent Perception Layer              │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │  감지 소스 (Sources)                       │    │
│  │  - 시장 데이터 (실시간 시세, 거래량 급변)   │    │
│  │  - 뉴스 피드 (RSS, 크롤링)                 │    │
│  │  - 소셜 미디어 (X/트위터, 레딧)            │    │
│  │  - 일정 (시장 개장/폐장, 실적 발표)         │    │
│  │  - 시스템 이벤트 (서비스 다운, 에러 급증)   │    │
│  └──────────────────────────────────────────┘    │
│                      ↓                           │
│  ┌──────────────────────────────────────────┐    │
│  │  이벤트 평가 (Evaluation)                  │    │
│  │  - 중요도 판단 (AI 기반)                   │    │
│  │  - 관련 에이전트 매칭                       │    │
│  │  - 중복 이벤트 필터링                       │    │
│  └──────────────────────────────────────────┘    │
│                      ↓                           │
│  ┌──────────────────────────────────────────┐    │
│  │  구독 & 배포 (Subscription)                │    │
│  │  - 에이전트별 관심사 구독                    │    │
│  │  - SSE/WebSocket 실시간 전달                │    │
│  │  - 웹훅 콜백                               │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

### API

```
POST /perception/subscribe
{
  "topics": ["market.crash", "news.breaking", "sentiment.shift"],
  "filters": { "symbols": ["BTC", "005930"], "min_urgency": "medium" },
  "delivery": "sse"  // 또는 "webhook"
}

GET /perception/stream  (SSE)
→ data: {"type": "market.crash", "symbol": "BTC", "change": -12.3, "urgency": "critical"}
→ data: {"type": "sentiment.shift", "symbol": "005930", "from": "neutral", "to": "bearish"}
```

---

## 서비스 6: Agent Sandbox (에이전트 실행 환경)

### 왜 필수인가
- 에이전트가 코드를 생성하고 실행해야 할 때가 있다 (데이터 분석, 차트 생성 등)
- 안전한 격리 환경 없이는 위험하다
- "이 Python 코드로 주가 차트 그려줘"를 안전하게 실행할 공간

### 우리가 만드는 것

```
POST /sandbox/execute
{
  "language": "python",
  "code": "import pandas as pd\n...",
  "timeout_ms": 30000,
  "memory_limit_mb": 256,
  "allowed_packages": ["pandas", "matplotlib", "numpy"],
  "input_data": { "prices": [...] }
}

→ {
    "ok": true,
    "output": "...",
    "files": [
      { "name": "chart.png", "url": "/sandbox/files/abc123", "type": "image/png" }
    ],
    "execution_ms": 1250
  }
```

---

## 전체 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                AI 에이전트 필수 서비스 플랫폼                   │
│                                                              │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │
│  │ Memory  │ │ Identity │ │ Protocol │ │   Perception    │  │
│  │ 기억    │ │ 신분증    │ │ 소통     │ │   감각기관       │  │
│  └────┬────┘ └────┬─────┘ └────┬─────┘ └───────┬─────────┘  │
│       │           │            │               │             │
│       └───────────┴────────────┴───────────────┘             │
│                          │                                    │
│                   ┌──────▼──────┐                             │
│                   │   Wallet    │                             │
│                   │   지갑      │                             │
│                   └──────┬──────┘                             │
│                          │                                    │
│                   ┌──────▼──────┐                             │
│                   │  Sandbox    │                             │
│                   │  실행환경    │                             │
│                   └─────────────┘                             │
│                                                              │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│                                                              │
│  기존 서비스 (이 위에서 동작):                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│  │ 시세조회  │ │ 센티멘트  │ │ 뉴스수집  │ │ 모닝브리핑│        │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
└─────────────────────────────────────────────────────────────┘
```

---

## 구현 우선순위

### Phase 1: 생존 필수 (즉시)
| 순위 | 서비스 | 이유 |
|------|--------|------|
| 1 | **Memory** | 기억 없는 에이전트는 반쪽짜리. 현재 가장 큰 페인포인트 |
| 2 | **Protocol Hub** | MCP 서버 하나면 Claude가 바로 쓸 수 있음. 즉시 가치 발생 |
| 3 | **Identity** | 에이전트 인증/권한 없으면 보안 구멍 |

### Phase 2: 자율성 확보
| 순위 | 서비스 | 이유 |
|------|--------|------|
| 4 | **Perception** | 능동적 감지 → 에이전트가 진짜 자율적으로 동작 |
| 5 | **Wallet** | 유료 API 호출이 늘어나면 예산 관리 필수 |

### Phase 3: 확장
| 순위 | 서비스 | 이유 |
|------|--------|------|
| 6 | **Sandbox** | 코드 실행은 있으면 좋지만 초기엔 없어도 됨 |

---

## 경쟁 현황 & 포지셔닝

```
                    범용 ←────────────────→ 특화(투자/한국)
                     │                          │
          통합 ──    │  (빈 공간 = 우리 자리)     │  ← 우리 목표
          플랫폼     │                          │
                     │                          │
                     │  LangChain  ·  Mem0      │
                     │  CrewAI     ·  Zep       │
                     │                          │
          개별 ──    │  OpenAI     ·  Pinecone  │
          서비스     │  Anthropic  ·  Weaviate  │
                     │                          │
```

**우리의 포지셔닝**: 에이전트 필수 서비스를 **통합 제공**하면서, **한국 시장/한국어에 특화**된 유일한 플랫폼.

---

## 수익 모델

| 티어 | 가격 | 포함 서비스 |
|------|------|-----------|
| **Free** | ₩0 | Memory 100MB, 100 API calls/day, MCP 읽기 전용 |
| **Pro** | ₩29,000/월 | Memory 10GB, 10K calls/day, 전체 기능, Perception 구독 5개 |
| **Team** | ₩99,000/월 | Memory 100GB, 무제한, Sandbox, 에이전트간 공유 메모리 |
| **Enterprise** | 협의 | 전용 인스턴스, SLA, 커스텀 연동 |

---

## 한 줄 요약

> **AI 에이전트의 기억, 신분증, 언어, 지갑, 감각, 실행환경을 만든다.**
> 에이전트가 사람 없이도 스스로 기억하고, 소통하고, 판단하고, 행동할 수 있게.
