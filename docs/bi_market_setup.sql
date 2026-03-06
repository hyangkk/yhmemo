-- AI BI 시장 인텔리전스 에이전트 Supabase 테이블 설정
-- Supabase 대시보드 → SQL Editor에서 실행

-- 1. 시장 분석 리포트 저장 테이블
CREATE TABLE IF NOT EXISTS bi_market_reports (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  report_date    date NOT NULL,
  report_type    text NOT NULL DEFAULT 'daily_summary',
    -- 'daily_summary': 일일 전체 분석
    -- 'item': 개별 뉴스 아이템 (향후 확장)
  news_hash      text,            -- 중복 방지용 (item 타입 시 사용)
  headline       text,            -- 오늘의 핵심 메시지
  top_action     text,            -- 최우선 액션 아이템
  opportunities  jsonb DEFAULT '[]',  -- 시장 기회 배열
  competitive    jsonb DEFAULT '[]',  -- 경쟁사 동향 배열
  funding        jsonb DEFAULT '[]',  -- 투자 트렌드 배열
  threats        jsonb DEFAULT '[]',  -- 위협 요인 배열
  news_count     int  DEFAULT 0,
  created_at     timestamptz DEFAULT now()
);

-- 날짜별 조회 인덱스
CREATE INDEX IF NOT EXISTS bi_market_reports_date_idx
  ON bi_market_reports (report_date DESC);

-- 리포트 타입 인덱스
CREATE INDEX IF NOT EXISTS bi_market_reports_type_idx
  ON bi_market_reports (report_type);

-- 2. RLS(Row Level Security) 설정 — 서비스 롤만 접근 허용
ALTER TABLE bi_market_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY "서비스 롤 전체 접근" ON bi_market_reports
  FOR ALL USING (auth.role() = 'service_role');

-- 3. 확인 쿼리
SELECT 'bi_market_reports 테이블 생성 완료' AS status;
