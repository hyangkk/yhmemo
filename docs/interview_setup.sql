-- ============================================================
-- 인터뷰 에이전트 Supabase 테이블 설정
-- Supabase Dashboard > SQL Editor에서 실행
-- ============================================================


-- 1. 인터뷰 주제 테이블
-- ============================================================
CREATE TABLE IF NOT EXISTS interview_topics (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,                -- 주제명 (예: 공간대여 사업 썰)
    description     TEXT DEFAULT '',              -- 주제 설명 (AI 질문 생성 시 참고)
    enabled         BOOLEAN DEFAULT TRUE,
    total_questions INTEGER DEFAULT 0,            -- 누적 질문 수
    notion_page_id  TEXT DEFAULT '',              -- 연결된 노션 페이지 ID
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE interview_topics DISABLE ROW LEVEL SECURITY;


-- 2. 인터뷰 메시지 테이블 (Q&A 기록)
-- ============================================================
CREATE TABLE IF NOT EXISTS interview_messages (
    id                  BIGSERIAL PRIMARY KEY,
    topic_id            INTEGER REFERENCES interview_topics(id) ON DELETE CASCADE,
    role                TEXT NOT NULL CHECK (role IN ('agent', 'user')),
    content             TEXT NOT NULL,
    telegram_message_id INTEGER,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interview_messages_topic
    ON interview_messages (topic_id, created_at);

ALTER TABLE interview_messages DISABLE ROW LEVEL SECURITY;


-- 3. agent_settings에 인터뷰 관련 컬럼 추가
-- ============================================================
ALTER TABLE agent_settings
  ADD COLUMN IF NOT EXISTS interview_enabled BOOLEAN DEFAULT TRUE;

ALTER TABLE agent_settings
  ADD COLUMN IF NOT EXISTS interview_interval_hours INTEGER DEFAULT 3;

ALTER TABLE agent_settings
  ADD COLUMN IF NOT EXISTS interview_last_update_id BIGINT DEFAULT 0;

ALTER TABLE agent_settings
  ADD COLUMN IF NOT EXISTS interview_last_question_at TIMESTAMPTZ;

ALTER TABLE agent_settings
  ADD COLUMN IF NOT EXISTS interview_notion_database_id TEXT DEFAULT '';
