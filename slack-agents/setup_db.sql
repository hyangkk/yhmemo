-- Slack AI Agents - Supabase 추가 테이블
-- 기존 테이블(news_ideas, agent_settings 등)은 유지

-- 에이전트 간 작업 큐
create table if not exists agent_tasks (
  id uuid primary key default gen_random_uuid(),
  from_agent text not null,
  to_agent text not null,
  task_type text not null,
  payload jsonb not null default '{}',
  status text not null default 'pending',
  result jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- 수집된 원본 정보
create table if not exists collected_items (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  source_type text not null,
  title text not null,
  url text,
  content text,
  metadata jsonb default '{}',
  collected_at timestamptz default now(),
  hash text unique not null
);

-- 선별된 정보 + 사용자 피드백
create table if not exists curated_items (
  id uuid primary key default gen_random_uuid(),
  collected_item_id uuid references collected_items(id),
  relevance_score float not null,
  ai_summary text,
  ai_reasoning text,
  user_feedback int,
  notion_page_id text,
  curated_at timestamptz default now()
);

-- 선별 기준 학습 데이터
create table if not exists curation_preferences (
  id uuid primary key default gen_random_uuid(),
  category text not null,
  keywords jsonb default '[]',
  weight float default 1.0,
  learned_from text,
  updated_at timestamptz default now()
);

-- 인덱스
create index if not exists idx_agent_tasks_status on agent_tasks(status);
create index if not exists idx_agent_tasks_to_agent on agent_tasks(to_agent);
create index if not exists idx_collected_items_hash on collected_items(hash);
create index if not exists idx_collected_items_collected_at on collected_items(collected_at);
create index if not exists idx_curated_items_score on curated_items(relevance_score);
