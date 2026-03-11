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

// 6자리 참여 코드 생성
export function generateSessionCode(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // 혼동 방지: O,0,I,1 제외
  let code = '';
  for (let i = 0; i < 6; i++) {
    code += chars[Math.floor(Math.random() * chars.length)];
  }
  return code;
}

// 디바이스 이름 자동 생성
export function getDeviceName(index: number): string {
  return `카메라 ${index + 1}`;
}
