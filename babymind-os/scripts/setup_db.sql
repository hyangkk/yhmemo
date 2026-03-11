-- BabyMind OS Supabase 테이블 생성
-- Supabase SQL Editor에서 실행

-- 프레임 분석 결과 테이블
CREATE TABLE IF NOT EXISTS babymind_analyses (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    camera_id TEXT DEFAULT 'main',
    scene_summary TEXT,
    child_detected BOOLEAN DEFAULT FALSE,
    child_position TEXT,
    child_posture TEXT,
    child_emotion TEXT,
    objects JSONB DEFAULT '[]'::jsonb,
    actions JSONB DEFAULT '[]'::jsonb,
    toy_interactions JSONB DEFAULT '{}'::jsonb,
    safety_events JSONB DEFAULT '[]'::jsonb,
    special_events JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_analyses_timestamp ON babymind_analyses(timestamp);
CREATE INDEX IF NOT EXISTS idx_analyses_child_detected ON babymind_analyses(child_detected);
CREATE INDEX IF NOT EXISTS idx_analyses_safety ON babymind_analyses USING GIN (safety_events);
CREATE INDEX IF NOT EXISTS idx_analyses_toys ON babymind_analyses USING GIN (toy_interactions);

-- 일일 요약 테이블
CREATE TABLE IF NOT EXISTS babymind_daily_digests (
    id BIGSERIAL PRIMARY KEY,
    date TEXT NOT NULL,
    child_name TEXT,
    highlights JSONB DEFAULT '[]'::jsonb,
    toy_summary JSONB DEFAULT '{}'::jsonb,
    total_active_minutes INTEGER DEFAULT 0,
    main_activities JSONB DEFAULT '[]'::jsonb,
    safety_alerts JSONB DEFAULT '[]'::jsonb,
    special_moments JSONB DEFAULT '[]'::jsonb,
    ai_comment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_digest_date ON babymind_daily_digests(date);

-- RLS 정책 (보안)
ALTER TABLE babymind_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE babymind_daily_digests ENABLE ROW LEVEL SECURITY;

-- service_role만 접근 가능
CREATE POLICY "service_role_analyses" ON babymind_analyses
    FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "service_role_digests" ON babymind_daily_digests
    FOR ALL USING (auth.role() = 'service_role');

-- 자동 데이터 정리 (90일 이상 된 분석 데이터)
-- pg_cron 확장이 필요 (Supabase Pro 플랜)
-- SELECT cron.schedule('cleanup-old-analyses', '0 3 * * *',
--     $$DELETE FROM babymind_analyses WHERE timestamp < NOW() - INTERVAL '90 days'$$);
