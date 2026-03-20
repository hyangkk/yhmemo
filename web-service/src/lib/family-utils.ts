// 가족 관계 유틸리티 - 촌수 계산, 호칭 결정

import { FamilyMember, FamilyRelation, HonorificResult } from './family-types';

// 관계 그래프에서 두 사람 간의 경로를 찾는 BFS
interface GraphNode {
  memberId: string;
  path: Array<{ memberId: string; relationType: string; direction: 'up' | 'down' | 'spouse' }>;
}

export function findRelationPath(
  fromId: string,
  toId: string,
  relations: FamilyRelation[]
): GraphNode['path'] | null {
  if (fromId === toId) return [];

  // 인접 리스트 구성
  const adjacency = new Map<string, Array<{ targetId: string; relationType: string; direction: 'up' | 'down' | 'spouse' }>>();

  for (const rel of relations) {
    if (!adjacency.has(rel.from_member_id)) adjacency.set(rel.from_member_id, []);
    if (!adjacency.has(rel.to_member_id)) adjacency.set(rel.to_member_id, []);

    if (rel.relation_type === 'spouse') {
      adjacency.get(rel.from_member_id)!.push({ targetId: rel.to_member_id, relationType: 'spouse', direction: 'spouse' });
      adjacency.get(rel.to_member_id)!.push({ targetId: rel.from_member_id, relationType: 'spouse', direction: 'spouse' });
    } else if (rel.relation_type === 'parent') {
      // from이 to의 부모
      adjacency.get(rel.to_member_id)!.push({ targetId: rel.from_member_id, relationType: 'parent', direction: 'up' });
      adjacency.get(rel.from_member_id)!.push({ targetId: rel.to_member_id, relationType: 'child', direction: 'down' });
    } else if (rel.relation_type === 'child') {
      adjacency.get(rel.from_member_id)!.push({ targetId: rel.to_member_id, relationType: 'child', direction: 'down' });
      adjacency.get(rel.to_member_id)!.push({ targetId: rel.from_member_id, relationType: 'parent', direction: 'up' });
    }
  }

  // BFS
  const visited = new Set<string>();
  const queue: GraphNode[] = [{ memberId: fromId, path: [] }];
  visited.add(fromId);

  while (queue.length > 0) {
    const current = queue.shift()!;
    const neighbors = adjacency.get(current.memberId) || [];

    for (const neighbor of neighbors) {
      if (visited.has(neighbor.targetId)) continue;

      const newPath = [...current.path, {
        memberId: neighbor.targetId,
        relationType: neighbor.relationType,
        direction: neighbor.direction,
      }];

      if (neighbor.targetId === toId) return newPath;

      visited.add(neighbor.targetId);
      queue.push({ memberId: neighbor.targetId, path: newPath });
    }
  }

  return null;
}

// 촌수 계산
export function calculateChonsu(path: GraphNode['path']): number {
  if (!path) return -1;

  let chonsu = 0;
  for (const step of path) {
    if (step.direction === 'up' || step.direction === 'down') {
      chonsu += 1;
    }
    // 배우자 관계는 촌수에 포함되지 않음 (0촌)
  }
  return chonsu;
}

// 한국어 호칭 결정
export function getHonorific(
  path: GraphNode['path'],
  fromGender: 'male' | 'female',
  members: FamilyMember[],
  relations: FamilyRelation[]
): HonorificResult {
  if (!path || path.length === 0) {
    return { title: '본인', chonsu: 0, path: '본인' };
  }

  const chonsu = calculateChonsu(path);
  const directions = path.map(p => p.direction);
  const memberMap = new Map(members.map(m => [m.id, m]));
  const targetMember = memberMap.get(path[path.length - 1].memberId);
  const targetGender = targetMember?.gender || 'male';

  // 직계 관계
  if (directions.every(d => d === 'up')) {
    // 윗세대
    const gen = directions.length;
    if (gen === 1) return { title: targetGender === 'male' ? '아버지' : '어머니', chonsu: 1, path: '직계 존속' };
    if (gen === 2) return { title: targetGender === 'male' ? '할아버지' : '할머니', chonsu: 2, path: '직계 존속' };
    if (gen === 3) return { title: targetGender === 'male' ? '증조할아버지' : '증조할머니', chonsu: 3, path: '직계 존속' };
    if (gen === 4) return { title: targetGender === 'male' ? '고조할아버지' : '고조할머니', chonsu: 4, path: '직계 존속' };
  }

  if (directions.every(d => d === 'down')) {
    const gen = directions.length;
    if (gen === 1) return { title: targetGender === 'male' ? '아들' : '딸', chonsu: 1, path: '직계 비속' };
    if (gen === 2) return { title: targetGender === 'male' ? '손자' : '손녀', chonsu: 2, path: '직계 비속' };
    if (gen === 3) return { title: targetGender === 'male' ? '증손자' : '증손녀', chonsu: 3, path: '직계 비속' };
  }

  // 배우자
  if (directions.length === 1 && directions[0] === 'spouse') {
    return { title: fromGender === 'male' ? '아내' : '남편', chonsu: 0, path: '배우자' };
  }

  // 부모의 배우자 (계부모)
  if (directions.length === 2 && directions[0] === 'up' && directions[1] === 'spouse') {
    return { title: targetGender === 'male' ? '아버지' : '어머니', chonsu: 1, path: '부모 배우자' };
  }

  // 형제자매 (부모 → 자녀)
  if (directions.length === 2 && directions[0] === 'up' && directions[1] === 'down') {
    if (targetGender === 'male') {
      return { title: fromGender === 'male' ? '형/동생' : '오빠/남동생', chonsu: 2, path: '형제' };
    }
    return { title: fromGender === 'male' ? '누나/여동생' : '언니/동생', chonsu: 2, path: '자매' };
  }

  // 부모의 형제 (삼촌/고모/이모/외숙)
  if (directions.filter(d => d === 'up').length === 2 && directions.filter(d => d === 'down').length === 1) {
    // 부모쪽으로 2세대 올라가고 1세대 내려옴 → 3촌
    if (chonsu === 3) {
      if (targetGender === 'male') return { title: '삼촌/외삼촌', chonsu: 3, path: '부모의 형제' };
      return { title: '고모/이모', chonsu: 3, path: '부모의 자매' };
    }
  }

  // 사촌 (부모 → 조부모 → 삼촌 → 사촌)
  if (directions.filter(d => d === 'up').length === 2 && directions.filter(d => d === 'down').length === 2) {
    if (chonsu === 4) {
      return { title: '사촌 ' + (targetGender === 'male' ? '형제' : '자매'), chonsu: 4, path: '사촌' };
    }
  }

  // 배우자의 부모 (시부모/장인장모)
  if (directions.length === 2 && directions[0] === 'spouse' && directions[1] === 'up') {
    if (fromGender === 'male') {
      return { title: targetGender === 'male' ? '장인어른' : '장모님', chonsu: 1, path: '배우자의 부모' };
    }
    return { title: targetGender === 'male' ? '시아버지' : '시어머니', chonsu: 1, path: '배우자의 부모' };
  }

  // 자녀의 배우자 (사위/며느리)
  if (directions.length === 2 && directions[0] === 'down' && directions[1] === 'spouse') {
    return { title: targetGender === 'male' ? '사위' : '며느리', chonsu: 1, path: '자녀의 배우자' };
  }

  // 기본: 촌수만 표시
  return { title: `${chonsu}촌`, chonsu, path: `${chonsu}촌 관계` };
}

// 가계도 트리 구조 생성 (루트 노드부터)
export function buildFamilyTree(
  rootId: string,
  members: FamilyMember[],
  relations: FamilyRelation[]
): { nodes: TreeNode[]; links: TreeLink[] } {
  const memberMap = new Map(members.map(m => [m.id, m]));
  const nodes: TreeNode[] = [];
  const links: TreeLink[] = [];
  const visited = new Set<string>();

  function traverse(memberId: string, depth: number, x: number) {
    if (visited.has(memberId)) return;
    visited.add(memberId);

    const member = memberMap.get(memberId);
    if (!member) return;

    // 배우자 찾기
    const spouseRel = relations.find(
      r => r.relation_type === 'spouse' && (r.from_member_id === memberId || r.to_member_id === memberId)
    );
    const spouseId = spouseRel
      ? (spouseRel.from_member_id === memberId ? spouseRel.to_member_id : spouseRel.from_member_id)
      : null;
    const spouse = spouseId ? memberMap.get(spouseId) : null;

    nodes.push({ id: memberId, member, spouse: spouse || undefined, depth, x });
    if (spouseId) visited.add(spouseId);

    // 자녀 찾기
    const childRelations = relations.filter(
      r => r.relation_type === 'parent' && (r.from_member_id === memberId || (spouseId && r.from_member_id === spouseId))
    );

    const childIds = [...new Set(childRelations.map(r => r.to_member_id))];

    childIds.forEach((childId, i) => {
      links.push({ from: memberId, to: childId });
      traverse(childId, depth + 1, x + i);
    });
  }

  // 최상위 조상 찾기
  const hasParent = new Set(
    relations.filter(r => r.relation_type === 'parent').map(r => r.to_member_id)
  );

  let root = rootId;
  // rootId의 부모가 있으면 더 위로 올라감
  let current = rootId;
  while (true) {
    const parentRel = relations.find(
      r => r.relation_type === 'parent' && r.to_member_id === current
    );
    if (parentRel) {
      current = parentRel.from_member_id;
      root = current;
    } else {
      break;
    }
  }

  traverse(root, 0, 0);
  return { nodes, links };
}

export interface TreeNode {
  id: string;
  member: FamilyMember;
  spouse?: FamilyMember;
  depth: number;
  x: number;
}

export interface TreeLink {
  from: string;
  to: string;
}
