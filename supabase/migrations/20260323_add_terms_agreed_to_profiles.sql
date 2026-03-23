-- profiles에 약관 동의 일시 추가
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS terms_agreed_at timestamptz;
