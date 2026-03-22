-- 자율 경영 시스템 테이블
-- CEO Agent가 사업 운영에 사용하는 핵심 테이블

-- 수익 기록
CREATE TABLE IF NOT EXISTS business_revenue (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    amount_krw INTEGER NOT NULL,
    source TEXT NOT NULL,  -- 'paddle', 'trading', 'api_service', 'digital_product', 'other'
    description TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 비용 기록
CREATE TABLE IF NOT EXISTS business_costs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    amount_krw INTEGER NOT NULL,
    category TEXT NOT NULL,  -- 'anthropic', 'slack', 'gcp', 'vercel', 'fly_io', 'other'
    description TEXT DEFAULT '',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 시장 조사 결과
CREATE TABLE IF NOT EXISTS business_research (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    research_type TEXT NOT NULL,  -- 'market_scan', 'competitor', 'customer', 'trend'
    results JSONB NOT NULL DEFAULT '{}',
    status TEXT DEFAULT 'completed',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 사업 가설 & 검증
CREATE TABLE IF NOT EXISTS business_hypotheses (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    hypothesis TEXT NOT NULL,
    category TEXT DEFAULT 'service',  -- 'service', 'market', 'pricing', 'growth'
    status TEXT DEFAULT 'unvalidated',  -- 'unvalidated', 'testing', 'validated', 'invalidated'
    evidence JSONB DEFAULT '[]',
    revenue_potential_krw INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    validated_at TIMESTAMPTZ
);

-- 서비스 포트폴리오
CREATE TABLE IF NOT EXISTS business_services (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'planning',  -- 'planning', 'building', 'beta', 'live', 'paused', 'retired'
    revenue_model TEXT DEFAULT '',
    monthly_revenue_krw INTEGER DEFAULT 0,
    monthly_cost_krw INTEGER DEFAULT 0,
    url TEXT DEFAULT '',
    metrics JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    launched_at TIMESTAMPTZ
);

-- 경영 의사결정 로그
CREATE TABLE IF NOT EXISTS business_decisions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    decision_type TEXT NOT NULL,
    description TEXT NOT NULL,
    rationale TEXT DEFAULT '',
    outcome TEXT DEFAULT '',
    impact_krw INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_revenue_created ON business_revenue(created_at);
CREATE INDEX IF NOT EXISTS idx_revenue_source ON business_revenue(source);
CREATE INDEX IF NOT EXISTS idx_costs_created ON business_costs(created_at);
CREATE INDEX IF NOT EXISTS idx_costs_category ON business_costs(category);
CREATE INDEX IF NOT EXISTS idx_services_status ON business_services(status);
CREATE INDEX IF NOT EXISTS idx_hypotheses_status ON business_hypotheses(status);
