-- ============================================================
-- Supabase Security Advisor 보안 이슈 전체 수정
-- 2026-03-11
--
-- [Errors] RLS 비활성화된 9개 테이블에 RLS 활성화
-- [Warnings] 과도하게 허용적인 RLS 정책 3개 수정
--
-- 참고: service_role 키는 RLS를 자동 우회하므로
--       기존 에이전트/백엔드 코드에 영향 없음
-- ============================================================

-- ============================================================
-- Part 1: RLS 비활성화된 9개 테이블에 RLS 활성화 (Errors 해결)
-- ============================================================

ALTER TABLE board_reports          ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profile           ENABLE ROW LEVEL SECURITY;
ALTER TABLE board_members          ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_tasks            ENABLE ROW LEVEL SECURITY;
ALTER TABLE collected_items        ENABLE ROW LEVEL SECURITY;
ALTER TABLE curated_items          ENABLE ROW LEVEL SECURITY;
ALTER TABLE curation_preferences   ENABLE ROW LEVEL SECURITY;
ALTER TABLE interview_topics       ENABLE ROW LEVEL SECURITY;
ALTER TABLE interview_messages     ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- Part 2: 과도하게 허용적인 RLS 정책 수정 (Warnings 해결)
--
-- 문제: USING(true) / WITH CHECK(true) 정책이 anon 포함
--       모든 사용자에게 읽기/쓰기를 허용
-- 해결: 기존 정책 삭제 후 authenticated 사용자만 허용하는 정책으로 교체
--       (service_role은 RLS 우회하므로 기존 동작 유지)
-- ============================================================

-- 2-1. agent_settings: anon_read_write 정책 제거 및 교체
DROP POLICY IF EXISTS "anon_read_write" ON agent_settings;

CREATE POLICY "authenticated_read" ON agent_settings
    FOR SELECT TO authenticated
    USING (true);

CREATE POLICY "authenticated_write" ON agent_settings
    FOR INSERT TO authenticated
    WITH CHECK (true);

CREATE POLICY "authenticated_update" ON agent_settings
    FOR UPDATE TO authenticated
    USING (true)
    WITH CHECK (true);

-- 2-2. auto_trade_log: service_role_all 정책 제거 및 교체
DROP POLICY IF EXISTS "service_role_all" ON auto_trade_log;

CREATE POLICY "authenticated_read_trade_log" ON auto_trade_log
    FOR SELECT TO authenticated
    USING (true);

-- 2-3. social_sentiment: 과도한 정책 제거 및 교체
DROP POLICY IF EXISTS "Service role full access" ON social_sentiment;

CREATE POLICY "authenticated_read_sentiment" ON social_sentiment
    FOR SELECT TO authenticated
    USING (true);
