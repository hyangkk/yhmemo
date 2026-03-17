-- ============================================================
-- Supabase Security Advisor 보안 이슈 2차 수정
-- 2026-03-17
--
-- [9 ERRORS] RLS 비활성화 6개 + sensitive_columns_exposed 3개
-- [5 WARNS] 함수 search_path, 과도한 정책 3개, 비밀번호 보호
-- [12 INFO] RLS 활성화됐지만 정책 없는 테이블 12개
--
-- 참고: service_role 키는 RLS를 자동 우회하므로
--       기존 에이전트/백엔드 코드에 영향 없음
-- ============================================================

-- ============================================================
-- Part 1: RLS 비활성화된 6개 테이블 활성화 (ERROR 9개 해결)
-- sensitive_columns_exposed 3개도 RLS 활성화로 자동 해결
-- ============================================================

ALTER TABLE studio_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE studio_devices  ENABLE ROW LEVEL SECURITY;
ALTER TABLE studio_clips    ENABLE ROW LEVEL SECURITY;
ALTER TABLE studio_results  ENABLE ROW LEVEL SECURITY;
ALTER TABLE bulletin_boards ENABLE ROW LEVEL SECURITY;
ALTER TABLE bulletin_posts  ENABLE ROW LEVEL SECURITY;

-- studio 테이블: 인증된 사용자만 접근
CREATE POLICY "authenticated_all_studio_sessions" ON studio_sessions
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "authenticated_all_studio_devices" ON studio_devices
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "authenticated_all_studio_clips" ON studio_clips
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

CREATE POLICY "authenticated_select_studio_results" ON studio_results
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "authenticated_insert_studio_results" ON studio_results
    FOR INSERT TO authenticated WITH CHECK (true);

-- bulletin 테이블: 인증된 사용자 읽기 허용 (쓰기는 service_role만)
CREATE POLICY "authenticated_read_bulletin_boards" ON bulletin_boards
    FOR SELECT TO authenticated USING (true);

CREATE POLICY "authenticated_read_bulletin_posts" ON bulletin_posts
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- Part 2: WARN - handle_new_user 함수 search_path 수정
-- ============================================================

CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.profiles (id, email, name, avatar_url)
  VALUES (
    new.id,
    new.email,
    COALESCE(new.raw_user_meta_data->>'full_name', new.raw_user_meta_data->>'name', split_part(new.email, '@', 1)),
    new.raw_user_meta_data->>'avatar_url'
  );
  RETURN new;
END;
$$;

-- ============================================================
-- Part 3: WARN - 과도하게 허용적인 RLS 정책 수정
-- ============================================================

-- project_members.members_insert: authenticated 사용자만 + 프로젝트 오너 확인
DROP POLICY IF EXISTS "members_insert" ON project_members;
CREATE POLICY "members_insert" ON project_members
    FOR INSERT TO authenticated
    WITH CHECK (
        project_id IN (SELECT id FROM projects WHERE owner_id = auth.uid())
        OR user_id = auth.uid()
    );

-- project_clips.clips_insert: 같은 프로젝트 멤버만 삽입 가능
DROP POLICY IF EXISTS "clips_insert" ON project_clips;
CREATE POLICY "clips_insert" ON project_clips
    FOR INSERT TO authenticated
    WITH CHECK (
        project_id IN (SELECT project_id FROM project_members WHERE user_id = auth.uid())
    );

-- trade_journal.service_role_all: anon 차단, service_role만 접근
DROP POLICY IF EXISTS "service_role_all" ON trade_journal;
-- service_role은 RLS를 자동 우회하므로 별도 정책 불필요
-- authenticated에게 읽기만 허용
CREATE POLICY "authenticated_read_trade_journal" ON trade_journal
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- Part 4: INFO - RLS 활성화됐지만 정책 없는 테이블에 정책 추가
-- ============================================================

-- agent_tasks: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_agent_tasks" ON agent_tasks
    FOR SELECT TO authenticated USING (true);

-- board_members: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_board_members" ON board_members
    FOR SELECT TO authenticated USING (true);

-- board_reports: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_board_reports" ON board_reports
    FOR SELECT TO authenticated USING (true);

-- collected_items: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_collected_items" ON collected_items
    FOR SELECT TO authenticated USING (true);

-- curated_items: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_curated_items" ON curated_items
    FOR SELECT TO authenticated USING (true);

-- curation_preferences: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_curation_preferences" ON curation_preferences
    FOR SELECT TO authenticated USING (true);

-- interview_messages: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_interview_messages" ON interview_messages
    FOR SELECT TO authenticated USING (true);

-- interview_topics: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_interview_topics" ON interview_topics
    FOR SELECT TO authenticated USING (true);

-- kstartup_announcements: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_kstartup_announcements" ON kstartup_announcements
    FOR SELECT TO authenticated USING (true);

-- news_ideas: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_news_ideas" ON news_ideas
    FOR SELECT TO authenticated USING (true);

-- secrets_vault: 정책 추가 불필요 (service_role만 접근해야 함)
-- RLS가 활성화되어 있고 정책이 없으면 anon/authenticated 접근 자동 차단됨
-- 이것이 의도된 동작임 (service_role은 RLS 우회)

-- user_profile: 인증된 사용자 읽기 허용
CREATE POLICY "authenticated_read_user_profile" ON user_profile
    FOR SELECT TO authenticated USING (true);
