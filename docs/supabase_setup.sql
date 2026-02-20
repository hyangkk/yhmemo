-- ============================================================
-- K-Startup 에이전트 Supabase 테이블 설정
-- Supabase Dashboard > SQL Editor에서 실행
-- ============================================================


-- 1. 기업/개인 프로필 테이블
--    에이전트가 자격요건 대조에 사용하는 정보 (id=1 고정)
-- ============================================================
CREATE TABLE IF NOT EXISTS user_profile (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    company_name    TEXT,                   -- 기업명
    company_type    TEXT,                   -- 법인 / 개인사업자 / 해당없음
    founded_year    INTEGER,                -- 설립 연도 (예: 2021)
    industry        TEXT,                   -- 업종/산업 분야 (예: AI, 핀테크, 제조 등)
    main_product    TEXT,                   -- 주요 제품/서비스 설명
    employees       INTEGER,                -- 직원 수
    annual_revenue  BIGINT,                 -- 연간 매출액 (만원 단위)
    location        TEXT,                   -- 사업장 소재지 (예: 서울 강남구)
    certifications  TEXT,                   -- 보유 인증 (예: 벤처기업, 이노비즈, ISO9001)
    notes           TEXT,                   -- 기타 특이사항 (수상, 특허, 투자 유치 등)
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 기본 프로필 행 생성 (내용은 Supabase Dashboard에서 직접 수정)
INSERT INTO user_profile (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;


-- ============================================================
-- agent_settings 테이블 업데이트
--   kstartup_enabled 컬럼 추가 (기존 테이블에 없는 경우)
-- ============================================================
ALTER TABLE agent_settings
  ADD COLUMN IF NOT EXISTS kstartup_enabled BOOLEAN DEFAULT TRUE;


-- 2. K-Startup 공고 처리 기록 테이블
--    새 공고 감지 및 분석 결과 저장
-- ============================================================
CREATE TABLE IF NOT EXISTS kstartup_announcements (
    id              BIGSERIAL PRIMARY KEY,
    announcement_id TEXT NOT NULL UNIQUE,   -- K-Startup 공고 고유 ID
    title           TEXT,                   -- 공고명
    url             TEXT,                   -- 공고 상세 URL
    deadline        TEXT,                   -- 신청 마감일
    eligible        BOOLEAN,                -- 적합 여부 (true/false/null)
    analysis        JSONB,                  -- Claude 분석 결과 (JSON)
    draft           TEXT,                   -- 신청서 초안 (적합 시)
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 중복 방지 인덱스
CREATE UNIQUE INDEX IF NOT EXISTS idx_kstartup_announcement_id
    ON kstartup_announcements (announcement_id);


-- ============================================================
-- 프로필 예시 데이터 (실제 정보로 수정하세요)
-- ============================================================
/*
UPDATE user_profile SET
    company_name   = '(주)예시기업',
    company_type   = '법인',
    founded_year   = 2021,
    industry       = 'AI/소프트웨어',
    main_product   = 'AI 기반 문서 자동화 SaaS 서비스',
    employees      = 5,
    annual_revenue = 15000,    -- 1억 5천만원
    location       = '서울 강남구',
    certifications = '벤처기업',
    notes          = '2023년 TIPS 프로그램 선정, 특허 2건 보유'
WHERE id = 1;
*/
