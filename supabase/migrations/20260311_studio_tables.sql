-- 멀티카메라 스튜디오 세션 테이블
CREATE TABLE IF NOT EXISTS studio_sessions (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  code varchar(6) NOT NULL UNIQUE,  -- 참여용 6자리 코드
  title text NOT NULL DEFAULT '새 촬영',
  host_device_id uuid,
  status varchar(20) NOT NULL DEFAULT 'waiting',  -- waiting, recording, uploading, editing, done
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

-- 세션에 참여한 디바이스 (카메라)
CREATE TABLE IF NOT EXISTS studio_devices (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
  name text NOT NULL DEFAULT '카메라',  -- 카메라1, 카메라2 등
  camera_index int NOT NULL DEFAULT 0,  -- 0부터 순서
  status varchar(20) NOT NULL DEFAULT 'connected',  -- connected, recording, uploading, done, error
  joined_at timestamptz DEFAULT now()
);

-- 업로드된 영상 클립
CREATE TABLE IF NOT EXISTS studio_clips (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
  device_id uuid NOT NULL REFERENCES studio_devices(id) ON DELETE CASCADE,
  storage_path text NOT NULL,  -- Supabase Storage 경로
  duration_ms int,
  file_size bigint,
  uploaded_at timestamptz DEFAULT now()
);

-- 편집 결과물
CREATE TABLE IF NOT EXISTS studio_results (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  session_id uuid NOT NULL REFERENCES studio_sessions(id) ON DELETE CASCADE,
  storage_path text NOT NULL,
  duration_ms int,
  status varchar(20) NOT NULL DEFAULT 'processing',  -- processing, done, error
  created_at timestamptz DEFAULT now()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_studio_sessions_code ON studio_sessions(code);
CREATE INDEX IF NOT EXISTS idx_studio_devices_session ON studio_devices(session_id);
CREATE INDEX IF NOT EXISTS idx_studio_clips_session ON studio_clips(session_id);

-- Realtime 활성화
ALTER PUBLICATION supabase_realtime ADD TABLE studio_sessions;
ALTER PUBLICATION supabase_realtime ADD TABLE studio_devices;
