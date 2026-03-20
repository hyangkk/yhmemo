// 가계도 서비스 타입 정의

export interface FamilyTree {
  id: string;
  user_id: string;
  name: string;
  created_at: string;
}

export interface FamilyMember {
  id: string;
  tree_id: string;
  name: string;
  birth_date: string | null;
  is_lunar_birth: boolean;
  death_date: string | null;
  photo_url: string | null;
  bio: string | null;
  is_deceased: boolean;
  gender: 'male' | 'female';
  created_at: string;
}

export type RelationType = 'spouse' | 'parent' | 'child';

export interface FamilyRelation {
  id: string;
  tree_id: string;
  from_member_id: string;
  to_member_id: string;
  relation_type: RelationType;
  created_at: string;
}

export type EventType = 'birthday' | 'memorial' | 'holiday' | 'wedding' | 'funeral' | 'other';

export interface FamilyEvent {
  id: string;
  tree_id: string;
  member_id: string | null;
  event_type: EventType;
  title: string;
  date: string;
  is_lunar: boolean;
  description: string | null;
  created_at: string;
}

export type LedgerDirection = 'sent' | 'received';
export type LedgerCategory = 'condolence' | 'gift';

export interface FamilyLedger {
  id: string;
  tree_id: string;
  event_id: string | null;
  member_id: string | null;
  category: LedgerCategory;
  direction: LedgerDirection;
  item: string | null;
  amount: number | null;
  note: string | null;
  date: string;
  created_at: string;
}

export interface FamilyMemory {
  id: string;
  tree_id: string;
  member_id: string | null;
  title: string;
  content: string | null;
  photo_urls: string[];
  date: string | null;
  created_at: string;
}

// 촌수 계산을 위한 관계 그래프 노드
export interface FamilyNode {
  member: FamilyMember;
  spouse?: FamilyMember;
  children: FamilyNode[];
  parent?: FamilyNode;
}

// 호칭 결과
export interface HonorificResult {
  title: string;       // 호칭 (예: "큰아버지")
  chonsu: number;      // 촌수
  path: string;        // 관계 경로 설명
}
