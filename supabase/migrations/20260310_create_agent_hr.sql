-- 에이전트 인사관리 (HR) 시스템
-- 재직기간, 연봉, 등급, 인사평가 이력 관리

-- 에이전트 인사 프로필
create table if not exists agent_hr (
  id uuid primary key default gen_random_uuid(),
  agent_name text unique not null,
  display_name text not null default '',
  position text not null default '사원',          -- 사원/주임/대리/과장/차장/부장/이사/상무
  salary int not null default 3000,               -- 만원 단위 (3000 = 3천만원)
  grade text not null default 'C',                -- S/A/B/C/D/F
  hire_date date not null default current_date,
  status text not null default 'active',          -- active/warning/probation/fired/resigned
  warning_count int not null default 0,
  total_evaluations int not null default 0,
  consecutive_low int not null default 0,         -- 연속 저평가 횟수
  consecutive_high int not null default 0,        -- 연속 고평가 횟수
  metadata jsonb not null default '{}',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- 인사평가 이력
create table if not exists agent_hr_evaluations (
  id uuid primary key default gen_random_uuid(),
  agent_name text not null,
  eval_date date not null default current_date,
  grade text not null,                            -- S/A/B/C/D/F
  composite_score float not null default 0.0,
  metrics jsonb not null default '{}',            -- 세부 지표
  ai_review text default '',                      -- AI 평가 코멘트
  salary_before int,
  salary_after int,
  position_before text,
  position_after text,
  hr_action text default '',                      -- 승진/감봉/경고/해고/보상 등
  created_at timestamptz default now()
);

-- 인사 조치 로그
create table if not exists agent_hr_actions (
  id uuid primary key default gen_random_uuid(),
  agent_name text not null,
  action_type text not null,                      -- promotion/demotion/raise/cut/warning/fired/bonus
  description text not null default '',
  old_value text default '',
  new_value text default '',
  reason text default '',
  created_at timestamptz default now()
);

-- 인덱스
create index if not exists idx_agent_hr_name on agent_hr(agent_name);
create index if not exists idx_agent_hr_status on agent_hr(status);
create index if not exists idx_agent_hr_evaluations_name on agent_hr_evaluations(agent_name);
create index if not exists idx_agent_hr_evaluations_date on agent_hr_evaluations(eval_date);
create index if not exists idx_agent_hr_actions_name on agent_hr_actions(agent_name);
