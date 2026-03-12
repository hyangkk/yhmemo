// 멀티카메라 스튜디오 공용 타입 및 유틸리티

export interface StudioSession {
  id: string;
  code: string;
  title: string;
  host_device_id: string | null;
  status: 'waiting' | 'recording' | 'uploading' | 'editing' | 'done';
  created_at: string;
  updated_at: string;
}

export interface StudioDevice {
  id: string;
  session_id: string;
  name: string;
  camera_index: number;
  status: 'connected' | 'recording' | 'uploading' | 'done' | 'error';
  joined_at: string;
}

export interface StudioClip {
  id: string;
  session_id: string;
  device_id: string;
  storage_path: string;
  duration_ms: number | null;
  file_size: number | null;
  uploaded_at: string;
}

export interface StudioResult {
  id: string;
  session_id: string;
  storage_path: string;
  duration_ms: number | null;
  status: 'processing' | 'done' | 'error';
  created_at: string;
}

// 2자리 숫자 참여 코드 생성 (00~99)
export function generateSessionCode(): string {
  const num = Math.floor(Math.random() * 100);
  return num.toString().padStart(2, '0');
}

// 디바이스 이름 자동 생성
export function getDeviceName(index: number): string {
  return `카메라 ${index + 1}`;
}
