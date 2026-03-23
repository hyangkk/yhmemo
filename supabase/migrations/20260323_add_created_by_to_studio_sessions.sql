-- studio_sessions에 created_by 컬럼 추가 (사용자별 세션 필터링용)
ALTER TABLE studio_sessions ADD COLUMN IF NOT EXISTS created_by uuid REFERENCES auth.users(id) ON DELETE SET NULL;

-- 인덱스 추가 (사용자별 조회 성능)
CREATE INDEX IF NOT EXISTS idx_studio_sessions_created_by ON studio_sessions(created_by);
