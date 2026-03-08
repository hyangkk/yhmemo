-- 공용 토큰/시크릿 저장 테이블
-- Claude Code 세션 시작 시 자동으로 로드됨
CREATE TABLE IF NOT EXISTS secrets_vault (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS 활성화 (service_role_key로만 접근 가능)
ALTER TABLE secrets_vault ENABLE ROW LEVEL SECURITY;

-- service_role만 접근 가능하도록 정책 설정 (anon 키로는 접근 불가)
-- service_role은 RLS를 우회하므로 별도 정책 불필요

-- updated_at 자동 갱신 트리거
CREATE OR REPLACE FUNCTION update_secrets_vault_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_secrets_vault_updated_at
  BEFORE UPDATE ON secrets_vault
  FOR EACH ROW
  EXECUTE FUNCTION update_secrets_vault_updated_at();

-- 초기 시크릿 키 목록 (값은 Supabase Dashboard에서 직접 입력)
INSERT INTO secrets_vault (key, description) VALUES
  ('GH_TOKEN', 'GitHub Personal Access Token'),
  ('NOTION_API_KEY', 'Notion Integration API Key'),
  ('ANTHROPIC_API_KEY', 'Anthropic API Key'),
  ('SLACK_BOT_TOKEN', 'Slack Bot Token'),
  ('SLACK_APP_TOKEN', 'Slack App Token'),
  ('FLY_API_TOKEN', 'Fly.io Deploy Token')
ON CONFLICT (key) DO NOTHING;
