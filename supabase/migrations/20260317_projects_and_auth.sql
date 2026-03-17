-- 프로젝트 기반 멀티클립 시스템 + 인증 + 결제

-- 1. 사용자 프로필 (Supabase Auth 연동)
CREATE TABLE IF NOT EXISTS profiles (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email text,
  name text,
  avatar_url text,
  plan varchar(20) NOT NULL DEFAULT 'free',  -- free, pro
  created_at timestamptz DEFAULT now()
);

-- 프로필 자동 생성 트리거
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
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
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- 2. 프로젝트
CREATE TABLE IF NOT EXISTS projects (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  owner_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  code varchar(6) NOT NULL UNIQUE,
  title text NOT NULL DEFAULT '새 프로젝트',
  description text,
  status varchar(20) NOT NULL DEFAULT 'active',  -- active, archived
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- 3. 프로젝트 멤버
CREATE TABLE IF NOT EXISTS project_members (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id uuid REFERENCES profiles(id) ON DELETE SET NULL,
  name text NOT NULL DEFAULT '참여자',
  role varchar(20) NOT NULL DEFAULT 'member',  -- owner, member
  device_id text,  -- 비로그인 참여자용 디바이스 식별자
  created_at timestamptz DEFAULT now(),
  UNIQUE(project_id, user_id)
);

-- 4. 프로젝트 클립 (started_at 포함!)
CREATE TABLE IF NOT EXISTS project_clips (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  member_id uuid NOT NULL REFERENCES project_members(id) ON DELETE CASCADE,
  storage_path text NOT NULL,
  duration_ms int,
  file_size bigint,
  started_at timestamptz NOT NULL,  -- 촬영 시작 시각 (타임라인 정렬용)
  ended_at timestamptz,             -- 촬영 종료 시각
  uploaded_at timestamptz DEFAULT now()
);

-- 5. 프로젝트 편집 결과
CREATE TABLE IF NOT EXISTS project_results (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  storage_path text NOT NULL,
  duration_ms int,
  status varchar(20) NOT NULL DEFAULT 'processing',  -- processing, done, error
  edit_mode text,  -- auto, director, timeline, prompt
  created_at timestamptz DEFAULT now()
);

-- 6. 결제 내역
CREATE TABLE IF NOT EXISTS payments (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
  stripe_session_id text,
  stripe_payment_intent text,
  amount int NOT NULL,  -- 원 단위
  currency varchar(10) NOT NULL DEFAULT 'krw',
  feature text NOT NULL,  -- pro_edit, premium_edit
  status varchar(20) NOT NULL DEFAULT 'pending',  -- pending, completed, failed
  created_at timestamptz DEFAULT now()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_code ON projects(code);
CREATE INDEX IF NOT EXISTS idx_project_members_project ON project_members(project_id);
CREATE INDEX IF NOT EXISTS idx_project_clips_project ON project_clips(project_id);
CREATE INDEX IF NOT EXISTS idx_project_clips_started ON project_clips(started_at);
CREATE INDEX IF NOT EXISTS idx_project_results_project ON project_results(project_id);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);

-- RLS
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_clips ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;

-- profiles: 자기 프로필만 읽기/수정
CREATE POLICY "profiles_select_own" ON profiles FOR SELECT USING (auth.uid() = id);
CREATE POLICY "profiles_update_own" ON profiles FOR UPDATE USING (auth.uid() = id);

-- projects: 멤버만 읽기, 오너만 수정
CREATE POLICY "projects_select_member" ON projects FOR SELECT USING (
  owner_id = auth.uid() OR id IN (SELECT project_id FROM project_members WHERE user_id = auth.uid())
);
CREATE POLICY "projects_insert_auth" ON projects FOR INSERT WITH CHECK (owner_id = auth.uid());
CREATE POLICY "projects_update_owner" ON projects FOR UPDATE USING (owner_id = auth.uid());

-- project_members: 같은 프로젝트 멤버끼리 읽기
CREATE POLICY "members_select" ON project_members FOR SELECT USING (
  project_id IN (SELECT project_id FROM project_members WHERE user_id = auth.uid())
);
CREATE POLICY "members_insert" ON project_members FOR INSERT WITH CHECK (true);

-- project_clips: 같은 프로젝트 멤버끼리 읽기
CREATE POLICY "clips_select" ON project_clips FOR SELECT USING (
  project_id IN (SELECT project_id FROM project_members WHERE user_id = auth.uid())
);
CREATE POLICY "clips_insert" ON project_clips FOR INSERT WITH CHECK (true);

-- project_results: 같은 프로젝트 멤버끼리 읽기
CREATE POLICY "results_select" ON project_results FOR SELECT USING (
  project_id IN (SELECT project_id FROM project_members WHERE user_id = auth.uid())
);

-- payments: 본인만
CREATE POLICY "payments_select_own" ON payments FOR SELECT USING (user_id = auth.uid());

-- Realtime
ALTER PUBLICATION supabase_realtime ADD TABLE projects;
ALTER PUBLICATION supabase_realtime ADD TABLE project_clips;
