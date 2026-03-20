'use client';

import { getBrowserSupabase } from './auth';
import type {
  FamilyTree, FamilyMember, FamilyRelation,
  FamilyEvent, FamilyLedger, FamilyMemory,
  RelationType, EventType, LedgerCategory, LedgerDirection,
} from './family-types';

// 인증 토큰 가져오기
async function getToken(): Promise<string> {
  const sb = getBrowserSupabase();
  const { data: { session } } = await sb.auth.getSession();
  return session?.access_token || '';
}

async function apiFetch(path: string, options?: RequestInit) {
  const token = await getToken();
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: '요청 실패' }));
    throw new Error(err.error || '요청 실패');
  }
  return res.json();
}

// 가계도
export async function fetchTrees(): Promise<FamilyTree[]> {
  const data = await apiFetch('/api/family');
  return data.trees;
}

export async function createTree(name: string): Promise<FamilyTree> {
  const data = await apiFetch('/api/family', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
  return data.tree;
}

export async function deleteTree(treeId: string): Promise<void> {
  await apiFetch(`/api/family/${treeId}`, { method: 'DELETE' });
}

// 가계도 상세 데이터
export interface FamilyTreeData {
  tree: FamilyTree;
  members: FamilyMember[];
  relations: FamilyRelation[];
  events: FamilyEvent[];
  ledger: FamilyLedger[];
  memories: FamilyMemory[];
}

export async function fetchTreeData(treeId: string): Promise<FamilyTreeData> {
  return apiFetch(`/api/family/${treeId}`);
}

// 구성원
export async function addMember(treeId: string, member: {
  name: string;
  gender: 'male' | 'female';
  birth_date?: string;
  is_lunar_birth?: boolean;
  death_date?: string;
  is_deceased?: boolean;
  bio?: string;
}): Promise<FamilyMember> {
  const data = await apiFetch(`/api/family/${treeId}/members`, {
    method: 'POST',
    body: JSON.stringify(member),
  });
  return data.member;
}

export async function updateMember(treeId: string, id: string, updates: Partial<FamilyMember>): Promise<FamilyMember> {
  const data = await apiFetch(`/api/family/${treeId}/members`, {
    method: 'PUT',
    body: JSON.stringify({ id, ...updates }),
  });
  return data.member;
}

// 관계
export async function addRelation(treeId: string, relation: {
  from_member_id: string;
  to_member_id: string;
  relation_type: RelationType;
}): Promise<FamilyRelation> {
  const data = await apiFetch(`/api/family/${treeId}/relations`, {
    method: 'POST',
    body: JSON.stringify(relation),
  });
  return data.relation;
}

export async function deleteRelation(treeId: string, relationId: string): Promise<void> {
  await apiFetch(`/api/family/${treeId}/relations?id=${relationId}`, { method: 'DELETE' });
}

// 이벤트
export async function addEvent(treeId: string, event: {
  member_id?: string;
  event_type: EventType;
  title: string;
  date: string;
  is_lunar?: boolean;
  description?: string;
}): Promise<FamilyEvent> {
  const data = await apiFetch(`/api/family/${treeId}/events`, {
    method: 'POST',
    body: JSON.stringify(event),
  });
  return data.event;
}

export async function updateEvent(treeId: string, id: string, updates: Partial<FamilyEvent>): Promise<FamilyEvent> {
  const data = await apiFetch(`/api/family/${treeId}/events`, {
    method: 'PUT',
    body: JSON.stringify({ id, ...updates }),
  });
  return data.event;
}

// 부조/선물
export async function addLedgerEntry(treeId: string, entry: {
  member_id?: string;
  event_id?: string;
  category: LedgerCategory;
  direction: LedgerDirection;
  item?: string;
  amount?: number;
  note?: string;
  date: string;
}): Promise<FamilyLedger> {
  const data = await apiFetch(`/api/family/${treeId}/ledger`, {
    method: 'POST',
    body: JSON.stringify(entry),
  });
  return data.entry;
}

export async function deleteLedgerEntry(treeId: string, entryId: string): Promise<void> {
  await apiFetch(`/api/family/${treeId}/ledger?id=${entryId}`, { method: 'DELETE' });
}

// 추억
export async function addMemory(treeId: string, memory: {
  member_id?: string;
  title: string;
  content?: string;
  photo_urls?: string[];
  date?: string;
}): Promise<FamilyMemory> {
  const data = await apiFetch(`/api/family/${treeId}/memories`, {
    method: 'POST',
    body: JSON.stringify(memory),
  });
  return data.memory;
}

export async function updateMemory(treeId: string, id: string, updates: Partial<FamilyMemory>): Promise<FamilyMemory> {
  const data = await apiFetch(`/api/family/${treeId}/memories`, {
    method: 'PUT',
    body: JSON.stringify({ id, ...updates }),
  });
  return data.memory;
}
