// 프로젝트 시스템 타입 정의

export interface Project {
  id: string;
  owner_id: string;
  code: string;
  title: string;
  description: string | null;
  status: 'active' | 'archived';
  created_at: string;
  updated_at: string;
}

export interface ProjectMember {
  id: string;
  project_id: string;
  user_id: string | null;
  name: string;
  role: 'owner' | 'member';
  device_id: string | null;
  created_at: string;
}

export interface ProjectClip {
  id: string;
  project_id: string;
  member_id: string;
  storage_path: string;
  duration_ms: number | null;
  file_size: number | null;
  started_at: string;
  ended_at: string | null;
  uploaded_at: string;
}

export interface ProjectResult {
  id: string;
  project_id: string;
  storage_path: string;
  duration_ms: number | null;
  status: 'processing' | 'done' | 'error';
  edit_mode: string | null;
  created_at: string;
}

// 6자리 프로젝트 코드 생성
export function generateProjectCode(): string {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let code = '';
  for (let i = 0; i < 6; i++) {
    code += chars[Math.floor(Math.random() * chars.length)];
  }
  return code;
}
