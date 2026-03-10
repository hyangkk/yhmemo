-- 자율 거래 에이전트 거래 로그 테이블
-- Supabase Dashboard → SQL Editor에서 실행

CREATE TABLE IF NOT EXISTS auto_trade_log (
    id bigserial PRIMARY KEY,
    trade_time timestamptz NOT NULL DEFAULT now(),
    action text NOT NULL,           -- '매수' or '매도'
    stock_code text NOT NULL,
    stock_name text,
    quantity int NOT NULL,
    success boolean DEFAULT true,
    order_no text,
    reason text,                    -- 매매 사유
    error_msg text,
    created_at timestamptz DEFAULT now()
);

-- RLS 활성화 + service_role 전체 접근 허용
ALTER TABLE auto_trade_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON auto_trade_log
    FOR ALL USING (true);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_auto_trade_log_time ON auto_trade_log(trade_time DESC);
CREATE INDEX IF NOT EXISTS idx_auto_trade_log_stock ON auto_trade_log(stock_code);
