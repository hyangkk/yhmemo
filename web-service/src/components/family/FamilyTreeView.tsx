'use client';

import { useState } from 'react';
import { FamilyMember, FamilyRelation } from '@/lib/family-types';
import { buildFamilyTree, TreeNode } from '@/lib/family-utils';

interface Props {
  members: FamilyMember[];
  relations: FamilyRelation[];
  onSelectMember: (member: FamilyMember) => void;
  selectedMemberId?: string;
}

export default function FamilyTreeView({ members, relations, onSelectMember, selectedMemberId }: Props) {
  const [zoom, setZoom] = useState(1);

  if (members.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-400">
        <div className="text-6xl mb-4">🌳</div>
        <p className="text-lg">아직 가족 구성원이 없습니다</p>
        <p className="text-sm mt-1">첫 번째 구성원을 추가해보세요</p>
      </div>
    );
  }

  // 루트 찾기: 부모가 없는 가장 오래된 남성 (또는 첫 번째 구성원)
  const childIds = new Set(
    relations.filter(r => r.relation_type === 'parent').map(r => r.to_member_id)
  );
  const parentIds = new Set(
    relations.filter(r => r.relation_type === 'parent').map(r => r.from_member_id)
  );

  // 부모 역할은 하지만 자식이 아닌 사람 = 최상위
  let rootId = members[0].id;
  for (const m of members) {
    if (parentIds.has(m.id) && !childIds.has(m.id)) {
      rootId = m.id;
      break;
    }
  }

  const { nodes, links } = buildFamilyTree(rootId, members, relations);

  // depth별로 그룹화
  const maxDepth = Math.max(...nodes.map(n => n.depth), 0);
  const depthGroups = new Map<number, TreeNode[]>();
  for (const node of nodes) {
    if (!depthGroups.has(node.depth)) depthGroups.set(node.depth, []);
    depthGroups.get(node.depth)!.push(node);
  }

  return (
    <div className="relative overflow-auto">
      {/* 줌 컨트롤 */}
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <button onClick={() => setZoom(z => Math.min(z + 0.1, 1.5))}
          className="w-8 h-8 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-sm font-bold hover:bg-gray-50 dark:hover:bg-gray-700">+</button>
        <button onClick={() => setZoom(z => Math.max(z - 0.1, 0.5))}
          className="w-8 h-8 rounded-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-sm font-bold hover:bg-gray-50 dark:hover:bg-gray-700">-</button>
      </div>

      <div style={{ transform: `scale(${zoom})`, transformOrigin: 'top center', minHeight: (maxDepth + 1) * 140 + 40 }}
        className="transition-transform">
        {Array.from(depthGroups.entries()).map(([depth, groupNodes]) => (
          <div key={depth} className="flex justify-center gap-6 mb-4" style={{ paddingTop: depth === 0 ? 16 : 0 }}>
            {groupNodes.map((node) => (
              <div key={node.id} className="flex flex-col items-center">
                {/* 위쪽 연결선 */}
                {depth > 0 && (
                  <div className="w-px h-4 bg-emerald-300 dark:bg-emerald-700" />
                )}

                {/* 부부 카드 */}
                <div className="flex items-center gap-1">
                  <MemberCard
                    member={node.member}
                    isSelected={selectedMemberId === node.member.id}
                    onClick={() => onSelectMember(node.member)}
                  />
                  {node.spouse && (
                    <>
                      <div className="w-4 h-px bg-pink-400 dark:bg-pink-600" />
                      <MemberCard
                        member={node.spouse}
                        isSelected={selectedMemberId === node.spouse.id}
                        onClick={() => onSelectMember(node.spouse!)}
                      />
                    </>
                  )}
                </div>

                {/* 아래쪽 연결선 */}
                {links.some(l => l.from === node.id) && (
                  <div className="w-px h-4 bg-emerald-300 dark:bg-emerald-700" />
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function MemberCard({ member, isSelected, onClick }: {
  member: FamilyMember;
  isSelected: boolean;
  onClick: () => void;
}) {
  const genderColor = member.gender === 'male'
    ? 'border-blue-400 dark:border-blue-600'
    : 'border-pink-400 dark:border-pink-600';

  const selectedStyle = isSelected
    ? 'ring-2 ring-emerald-500 shadow-lg'
    : '';

  const deceasedStyle = member.is_deceased
    ? 'opacity-70'
    : '';

  return (
    <button
      onClick={onClick}
      className={`relative flex flex-col items-center p-3 rounded-xl border-2 ${genderColor} ${selectedStyle} ${deceasedStyle}
        bg-white dark:bg-gray-800 hover:shadow-md transition-all min-w-[80px]`}
    >
      {/* 프로필 이미지 또는 아이콘 */}
      <div className={`w-12 h-12 rounded-full flex items-center justify-center text-xl
        ${member.gender === 'male' ? 'bg-blue-50 dark:bg-blue-900/30' : 'bg-pink-50 dark:bg-pink-900/30'}`}>
        {member.photo_url ? (
          <img src={member.photo_url} alt={member.name} className="w-full h-full rounded-full object-cover" />
        ) : (
          member.is_deceased ? '🕯️' : (member.gender === 'male' ? '👤' : '👤')
        )}
      </div>

      {/* 이름 */}
      <span className="mt-1 text-xs font-semibold text-gray-800 dark:text-gray-200 whitespace-nowrap">
        {member.name}
      </span>

      {/* 고인 표시 */}
      {member.is_deceased && (
        <span className="text-[10px] text-gray-400">故</span>
      )}
    </button>
  );
}
