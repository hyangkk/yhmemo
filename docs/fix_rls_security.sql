-- ============================================================
-- Supabase Security Advisor: RLS 보안 이슈 해결
-- 7개 테이블에 RLS 활성화
--
-- 참고: service_role 키는 RLS를 자동 우회하므로
--       기존 에이전트 스크립트는 영향 없음
-- ============================================================

-- 1. 모든 테이블에 RLS 활성화
ALTER TABLE user_profile              ENABLE ROW LEVEL SECURITY;
ALTER TABLE kstartup_announcements    ENABLE ROW LEVEL SECURITY;
ALTER TABLE board_reports             ENABLE ROW LEVEL SECURITY;
ALTER TABLE board_members             ENABLE ROW LEVEL SECURITY;
ALTER TABLE news_ideas                ENABLE ROW LEVEL SECURITY;
ALTER TABLE interview_topics          ENABLE ROW LEVEL SECURITY;
ALTER TABLE interview_messages        ENABLE ROW LEVEL SECURITY;
