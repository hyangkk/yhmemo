-- 우리가계 서비스 테이블 생성
-- Supabase SQL Editor에서 실행

-- 가계도
CREATE TABLE IF NOT EXISTS family_trees (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 가족 구성원
CREATE TABLE IF NOT EXISTS family_members (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tree_id UUID NOT NULL REFERENCES family_trees(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  gender TEXT NOT NULL CHECK (gender IN ('male', 'female')),
  birth_date DATE,
  is_lunar_birth BOOLEAN DEFAULT false,
  death_date DATE,
  photo_url TEXT,
  bio TEXT,
  is_deceased BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 가족 관계
CREATE TABLE IF NOT EXISTS family_relations (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tree_id UUID NOT NULL REFERENCES family_trees(id) ON DELETE CASCADE,
  from_member_id UUID NOT NULL REFERENCES family_members(id) ON DELETE CASCADE,
  to_member_id UUID NOT NULL REFERENCES family_members(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL CHECK (relation_type IN ('spouse', 'parent', 'child')),
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 가족 이벤트
CREATE TABLE IF NOT EXISTS family_events (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tree_id UUID NOT NULL REFERENCES family_trees(id) ON DELETE CASCADE,
  member_id UUID REFERENCES family_members(id) ON DELETE SET NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('birthday', 'memorial', 'holiday', 'wedding', 'funeral', 'other')),
  title TEXT NOT NULL,
  date DATE NOT NULL,
  is_lunar BOOLEAN DEFAULT false,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 부조/선물 장부
CREATE TABLE IF NOT EXISTS family_ledger (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tree_id UUID NOT NULL REFERENCES family_trees(id) ON DELETE CASCADE,
  event_id UUID REFERENCES family_events(id) ON DELETE SET NULL,
  member_id UUID REFERENCES family_members(id) ON DELETE SET NULL,
  category TEXT NOT NULL CHECK (category IN ('condolence', 'gift')),
  direction TEXT NOT NULL CHECK (direction IN ('sent', 'received')),
  item TEXT,
  amount INTEGER,
  note TEXT,
  date DATE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 추억/메모
CREATE TABLE IF NOT EXISTS family_memories (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  tree_id UUID NOT NULL REFERENCES family_trees(id) ON DELETE CASCADE,
  member_id UUID REFERENCES family_members(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  content TEXT,
  photo_urls JSONB DEFAULT '[]',
  date DATE,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_family_trees_user ON family_trees(user_id);
CREATE INDEX IF NOT EXISTS idx_family_members_tree ON family_members(tree_id);
CREATE INDEX IF NOT EXISTS idx_family_relations_tree ON family_relations(tree_id);
CREATE INDEX IF NOT EXISTS idx_family_events_tree ON family_events(tree_id);
CREATE INDEX IF NOT EXISTS idx_family_ledger_tree ON family_ledger(tree_id);
CREATE INDEX IF NOT EXISTS idx_family_memories_tree ON family_memories(tree_id);

-- RLS (Row Level Security) 비활성화 - service role 사용하므로
-- 필요시 나중에 활성화
