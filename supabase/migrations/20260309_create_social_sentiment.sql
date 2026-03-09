-- 소셜 센티멘트 분석 결과 저장 테이블
create table if not exists social_sentiment (
  id uuid primary key default gen_random_uuid(),
  overall_score int not null check (overall_score between 0 and 100),
  overall_label text not null default '중립',
  asset_scores jsonb not null default '{}',
  trending_topics text[] default '{}',
  summary text,
  risk_alert text,
  source_feeds jsonb default '{}',
  bullish_signals text[] default '{}',
  bearish_signals text[] default '{}',
  analyzed_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

-- 인덱스: 시간순 조회 최적화
create index if not exists idx_social_sentiment_analyzed_at
  on social_sentiment (analyzed_at desc);

-- RLS 비활성 (서비스 키로만 접근)
alter table social_sentiment enable row level security;
create policy "Service role full access" on social_sentiment
  for all using (true) with check (true);
