-- 학습 사이클용 스키마 확장
-- auto_trade_log에 정량 분석 컬럼 추가 + 매매일지 테이블 생성

-- 1) auto_trade_log 확장: 체결가, 수익률, 보유시간, 에이전트 구분
ALTER TABLE auto_trade_log ADD COLUMN IF NOT EXISTS price numeric;
ALTER TABLE auto_trade_log ADD COLUMN IF NOT EXISTS pnl_pct numeric;
ALTER TABLE auto_trade_log ADD COLUMN IF NOT EXISTS hold_minutes int;
ALTER TABLE auto_trade_log ADD COLUMN IF NOT EXISTS agent_name text DEFAULT 'auto_trader';

-- 2) 매매일지 테이블 (일별 AI 분석 + 교훈)
CREATE TABLE IF NOT EXISTS trade_journal (
    id bigserial PRIMARY KEY,
    journal_date date NOT NULL,
    agent_name text NOT NULL DEFAULT 'combined',
    total_trades int DEFAULT 0,
    win_count int DEFAULT 0,
    loss_count int DEFAULT 0,
    total_pnl numeric DEFAULT 0,
    net_asset numeric DEFAULT 0,
    lessons jsonb DEFAULT '[]'::jsonb,
    strategy_notes text,
    raw_analysis text,
    created_at timestamptz DEFAULT now(),
    UNIQUE(journal_date, agent_name)
);

ALTER TABLE trade_journal ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all" ON trade_journal FOR ALL USING (true);
CREATE INDEX IF NOT EXISTS idx_trade_journal_date ON trade_journal(journal_date DESC);
