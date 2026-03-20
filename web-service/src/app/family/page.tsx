'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { fetchTrees, createTree, fetchTreeData, addMember, addRelation, addEvent, addLedgerEntry, addMemory } from '@/lib/family-api';
import type { FamilyTree, FamilyMember, FamilyRelation, FamilyEvent, FamilyLedger, FamilyMemory, RelationType } from '@/lib/family-types';
import FamilyTreeView from '@/components/family/FamilyTreeView';
import UpcomingEvents from '@/components/family/UpcomingEvents';
import QuickAddButton from '@/components/family/QuickAddButton';
import AddMemberModal from '@/components/family/AddMemberModal';
import AddEventModal from '@/components/family/AddEventModal';
import AddLedgerModal from '@/components/family/AddLedgerModal';
import AddMemoryModal from '@/components/family/AddMemoryModal';

type Tab = 'tree' | 'events' | 'ledger' | 'memories';

export default function FamilyPage() {
  const { user, loading: authLoading } = useAuth();

  // 가계도 목록
  const [trees, setTrees] = useState<FamilyTree[]>([]);
  const [selectedTreeId, setSelectedTreeId] = useState<string>('');
  const [newTreeName, setNewTreeName] = useState('');
  const [showCreateTree, setShowCreateTree] = useState(false);
  const [treesLoading, setTreesLoading] = useState(true);

  // 현재 선택된 가계도 데이터
  const [members, setMembers] = useState<FamilyMember[]>([]);
  const [relations, setRelations] = useState<FamilyRelation[]>([]);
  const [events, setEvents] = useState<FamilyEvent[]>([]);
  const [ledger, setLedger] = useState<FamilyLedger[]>([]);
  const [memories, setMemories] = useState<FamilyMemory[]>([]);

  // UI 상태
  const [tab, setTab] = useState<Tab>('tree');
  const [selectedMember, setSelectedMember] = useState<FamilyMember | null>(null);
  const [dataLoading, setDataLoading] = useState(false);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  // 모달
  const [showAddMember, setShowAddMember] = useState(false);
  const [showAddEvent, setShowAddEvent] = useState(false);
  const [showAddLedger, setShowAddLedger] = useState(false);
  const [showAddMemory, setShowAddMemory] = useState(false);

  // 가계도 목록 로드
  useEffect(() => {
    if (!user) { setTreesLoading(false); return; }
    setTreesLoading(true);
    fetchTrees().then(t => {
      setTrees(t);
      if (t.length > 0) setSelectedTreeId(t[0].id);
    }).catch(() => {}).finally(() => setTreesLoading(false));
  }, [user]);

  // 선택된 가계도 데이터 로드
  const loadTreeData = useCallback(async () => {
    if (!selectedTreeId) return;
    setDataLoading(true);
    try {
      const data = await fetchTreeData(selectedTreeId);
      setMembers(data.members);
      setRelations(data.relations);
      setEvents(data.events);
      setLedger(data.ledger);
      setMemories(data.memories);
      setError('');
    } catch {
      setError('데이터를 불러오는 데 실패했습니다');
    } finally {
      setDataLoading(false);
    }
  }, [selectedTreeId]);

  useEffect(() => {
    loadTreeData();
  }, [loadTreeData]);

  // 새 가계도 만들기
  const handleCreateTree = async () => {
    if (!newTreeName.trim() || creating) return;
    setCreating(true);
    try {
      const tree = await createTree(newTreeName.trim());
      setTrees(prev => [tree, ...prev]);
      setSelectedTreeId(tree.id);
      setNewTreeName('');
      setShowCreateTree(false);
    } catch {
      setError('가계도 생성에 실패했습니다');
    } finally {
      setCreating(false);
    }
  };

  // 구성원 추가
  const handleAddMember = async (data: {
    name: string; gender: 'male' | 'female';
    birth_date?: string; is_lunar_birth?: boolean;
    death_date?: string; is_deceased?: boolean; bio?: string;
    relation?: { targetId: string; type: RelationType };
  }) => {
    try {
      const member = await addMember(selectedTreeId, data);
      if (data.relation) {
        const { targetId, type } = data.relation;
        if (type === 'child') {
          await addRelation(selectedTreeId, { from_member_id: targetId, to_member_id: member.id, relation_type: 'parent' });
        } else if (type === 'parent') {
          await addRelation(selectedTreeId, { from_member_id: member.id, to_member_id: targetId, relation_type: 'parent' });
        } else if (type === 'spouse') {
          await addRelation(selectedTreeId, { from_member_id: targetId, to_member_id: member.id, relation_type: 'spouse' });
        }
      }
      setShowAddMember(false);
      loadTreeData();
    } catch {
      setError('구성원 추가에 실패했습니다');
    }
  };

  // 이벤트 추가
  const handleAddEvent = async (data: Parameters<typeof addEvent>[1]) => {
    try {
      await addEvent(selectedTreeId, data);
      setShowAddEvent(false);
      loadTreeData();
    } catch {
      setError('일정 추가에 실패했습니다');
    }
  };

  // 부조/선물 추가
  const handleAddLedger = async (data: Parameters<typeof addLedgerEntry>[1]) => {
    try {
      await addLedgerEntry(selectedTreeId, data);
      setShowAddLedger(false);
      loadTreeData();
    } catch {
      setError('기록 추가에 실패했습니다');
    }
  };

  // 추억 추가
  const handleAddMemory = async (data: Parameters<typeof addMemory>[1]) => {
    try {
      await addMemory(selectedTreeId, data);
      setShowAddMemory(false);
      loadTreeData();
    } catch {
      setError('추억 기록에 실패했습니다');
    }
  };

  // 로그인 전 / 인증 로딩
  if (authLoading || treesLoading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-b from-emerald-50 to-white dark:from-gray-950 dark:to-gray-900">
        <div className="text-5xl mb-4 animate-bounce">🌳</div>
        <div className="text-emerald-600 dark:text-emerald-400 font-medium">불러오는 중...</div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-b from-emerald-50 to-white dark:from-gray-950 dark:to-gray-900 px-4">
        <div className="text-6xl mb-4">🌳</div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">우리가계</h1>
        <p className="text-gray-500 dark:text-gray-400 mb-6 text-center">가족의 관계, 추억, 경조사를 한곳에</p>
        <Link href="/login"
          className="px-6 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-medium transition-colors">
          로그인하고 시작하기
        </Link>
      </div>
    );
  }

  // 가계도 없을 때
  if (trees.length === 0 && !showCreateTree) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-emerald-50 to-white dark:from-gray-950 dark:to-gray-900">
        <Header />
        <div className="max-w-lg mx-auto px-4 pt-20 text-center">
          <div className="text-6xl mb-4">🌳</div>
          <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-2">첫 가계도를 만들어보세요</h2>
          <p className="text-gray-500 dark:text-gray-400 mb-6">우리 가족의 이야기를 기록하는 첫걸음</p>
          <button onClick={() => setShowCreateTree(true)}
            className="px-6 py-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-medium transition-colors active:scale-95">
            가계도 만들기
          </button>
        </div>
      </div>
    );
  }

  const TABS: { key: Tab; label: string; icon: string }[] = [
    { key: 'tree', label: '가계도', icon: '🌳' },
    { key: 'events', label: '일정', icon: '📅' },
    { key: 'ledger', label: '부조/선물', icon: '🎁' },
    { key: 'memories', label: '추억', icon: '📝' },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-b from-emerald-50 to-white dark:from-gray-950 dark:to-gray-900">
      <Header />

      <main className="max-w-4xl mx-auto px-4 pt-2 pb-24">
        {/* 가계도 선택 / 생성 */}
        <div className="flex items-center gap-3 mb-5">
          {trees.length > 0 && (
            <select value={selectedTreeId} onChange={e => setSelectedTreeId(e.target.value)}
              className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm font-medium focus:ring-2 focus:ring-emerald-500 focus:border-transparent">
              {trees.map(t => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          )}
          <button onClick={() => setShowCreateTree(true)}
            className="px-3 py-2 rounded-lg border border-dashed border-gray-300 dark:border-gray-700 text-gray-500 text-sm hover:border-emerald-500 hover:text-emerald-600 transition-colors active:scale-95">
            + 새 가계도
          </button>
        </div>

        {/* 새 가계도 생성 폼 */}
        {showCreateTree && (
          <div className="mb-5 p-4 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-sm">
            <h3 className="text-sm font-bold text-gray-800 dark:text-gray-200 mb-3">새 가계도 만들기</h3>
            <div className="flex gap-2">
              <input type="text" value={newTreeName} onChange={e => setNewTreeName(e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:ring-2 focus:ring-emerald-500"
                placeholder="예: 우리 가족, 김씨 가계도" autoFocus
                onKeyDown={e => e.key === 'Enter' && handleCreateTree()} />
              <button onClick={handleCreateTree} disabled={creating}
                className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors active:scale-95">
                {creating ? '생성 중...' : '만들기'}
              </button>
              <button onClick={() => setShowCreateTree(false)}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-700 text-gray-500 text-sm hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">취소</button>
            </div>
          </div>
        )}

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError('')} className="text-red-400 hover:text-red-600 ml-2">&times;</button>
          </div>
        )}

        {/* 탭 네비게이션 */}
        <div className="flex gap-1 mb-5 bg-gray-100 dark:bg-gray-800/80 rounded-xl p-1">
          {TABS.map(t => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`flex-1 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 ${
                tab === t.key
                  ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 active:bg-white/50 dark:active:bg-gray-700/50'
              }`}>
              <span className="mr-1">{t.icon}</span>
              <span className="text-xs sm:text-sm">{t.label}</span>
            </button>
          ))}
        </div>

        {/* 탭 콘텐츠 - 로딩 오버레이 방식 */}
        <div className="relative min-h-[200px]">
          {/* 로딩 오버레이: 이전 콘텐츠 위에 표시 */}
          {dataLoading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/60 dark:bg-gray-900/60 backdrop-blur-sm rounded-2xl">
              <div className="flex flex-col items-center gap-2">
                <div className="w-8 h-8 border-3 border-emerald-200 border-t-emerald-600 rounded-full animate-spin" />
                <span className="text-sm text-emerald-600 dark:text-emerald-400">불러오는 중...</span>
              </div>
            </div>
          )}

          {/* 가계도 탭 */}
          <div className={tab === 'tree' ? 'block' : 'hidden'}>
            <div className="space-y-5">
              {members.length > 0 && (
                <div className="p-4 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-sm">
                  <h3 className="text-sm font-bold text-gray-800 dark:text-gray-200 mb-3">다가오는 일정</h3>
                  <UpcomingEvents members={members} events={events} />
                </div>
              )}
              <div className="p-4 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 overflow-hidden shadow-sm">
                <h3 className="text-sm font-bold text-gray-800 dark:text-gray-200 mb-3">가계도</h3>
                <FamilyTreeView
                  members={members}
                  relations={relations}
                  onSelectMember={(m) => setSelectedMember(m)}
                  selectedMemberId={selectedMember?.id}
                />
              </div>
              {selectedMember && (
                <MemberInfoCard
                  member={selectedMember}
                  members={members}
                  relations={relations}
                  memories={memories}
                  ledger={ledger}
                  onClose={() => setSelectedMember(null)}
                />
              )}
            </div>
          </div>

          {/* 일정 탭 */}
          <div className={tab === 'events' ? 'block' : 'hidden'}>
            <EventsTab events={events} members={members} />
          </div>

          {/* 부조/선물 탭 */}
          <div className={tab === 'ledger' ? 'block' : 'hidden'}>
            <LedgerTab ledger={ledger} members={members} />
          </div>

          {/* 추억 탭 */}
          <div className={tab === 'memories' ? 'block' : 'hidden'}>
            <MemoriesTab memories={memories} members={members} />
          </div>
        </div>
      </main>

      {/* 빠른 추가 버튼 */}
      {selectedTreeId && (
        <QuickAddButton
          onAddMember={() => setShowAddMember(true)}
          onAddEvent={() => setShowAddEvent(true)}
          onAddMemory={() => setShowAddMemory(true)}
          onAddLedger={() => setShowAddLedger(true)}
        />
      )}

      {/* 모달들 */}
      <AddMemberModal isOpen={showAddMember} onClose={() => setShowAddMember(false)}
        onSubmit={handleAddMember} existingMembers={members} />
      <AddEventModal isOpen={showAddEvent} onClose={() => setShowAddEvent(false)}
        onSubmit={handleAddEvent} members={members} />
      <AddLedgerModal isOpen={showAddLedger} onClose={() => setShowAddLedger(false)}
        onSubmit={handleAddLedger} members={members} />
      <AddMemoryModal isOpen={showAddMemory} onClose={() => setShowAddMemory(false)}
        onSubmit={handleAddMemory} members={members} />
    </div>
  );
}

function Header() {
  return (
    <header className="sticky top-0 z-30 bg-white/80 dark:bg-gray-950/80 backdrop-blur-md border-b border-gray-200 dark:border-gray-800">
      <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Link href="/" className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 text-sm transition-colors">
            YH Hub
          </Link>
          <span className="text-gray-300 dark:text-gray-700">/</span>
          <h1 className="text-lg font-bold text-gray-900 dark:text-white flex items-center gap-2">
            🌳 우리가계
          </h1>
        </div>
      </div>
    </header>
  );
}

function MemberInfoCard({ member, members, relations, memories, ledger, onClose }: {
  member: FamilyMember;
  members: FamilyMember[];
  relations: FamilyRelation[];
  memories: FamilyMemory[];
  ledger: FamilyLedger[];
  onClose: () => void;
}) {
  const memberMemories = memories.filter(m => m.member_id === member.id);
  const memberLedger = ledger.filter(l => l.member_id === member.id);

  return (
    <div className="p-4 rounded-2xl bg-white dark:bg-gray-900 border border-emerald-200 dark:border-emerald-800 relative shadow-sm animate-fade-in">
      <button onClick={onClose}
        className="absolute top-3 right-3 w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors text-lg">
        &times;
      </button>

      <div className="flex items-start gap-4">
        <div className={`w-16 h-16 rounded-full flex items-center justify-center text-2xl flex-shrink-0
          ${member.gender === 'male' ? 'bg-blue-50 dark:bg-blue-900/30' : 'bg-pink-50 dark:bg-pink-900/30'}`}>
          {member.is_deceased ? '🕯️' : '👤'}
        </div>
        <div className="min-w-0">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">
            {member.name} {member.is_deceased && <span className="text-sm text-gray-400">(故)</span>}
          </h3>
          {member.bio && <p className="text-sm text-gray-500 mt-0.5">{member.bio}</p>}
          {member.birth_date && (
            <p className="text-xs text-gray-400 mt-1">
              {member.is_lunar_birth ? '음력 ' : ''}{member.birth_date}
              {member.death_date && ` ~ ${member.death_date}`}
            </p>
          )}
        </div>
      </div>

      {memberMemories.length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-bold text-gray-500 uppercase mb-2">추억</h4>
          <div className="space-y-2">
            {memberMemories.slice(0, 3).map(m => (
              <div key={m.id} className="p-2.5 rounded-lg bg-gray-50 dark:bg-gray-800">
                <p className="text-sm font-medium text-gray-800 dark:text-gray-200">{m.title}</p>
                {m.content && <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{m.content}</p>}
                {m.date && <p className="text-xs text-gray-400 mt-0.5">{m.date}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {memberLedger.length > 0 && (
        <div className="mt-4">
          <h4 className="text-xs font-bold text-gray-500 uppercase mb-2">부조/선물 내역</h4>
          <div className="space-y-1">
            {memberLedger.slice(0, 5).map(l => (
              <div key={l.id} className="flex items-center justify-between text-sm py-1">
                <span className="text-gray-600 dark:text-gray-400">
                  {l.direction === 'sent' ? '보냄' : '받음'} {l.item || ''}
                </span>
                <span className={`font-medium ${l.direction === 'sent' ? 'text-red-500' : 'text-blue-500'}`}>
                  {l.amount ? `${l.amount.toLocaleString()}원` : '-'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function EventsTab({ events, members }: { events: FamilyEvent[]; members: FamilyMember[] }) {
  const memberMap = new Map(members.map(m => [m.id, m]));

  if (events.length === 0) {
    return <EmptyState icon="📅" message="등록된 일정이 없습니다" sub="+ 버튼으로 일정을 추가해보세요" />;
  }

  return (
    <div className="space-y-3">
      {events.map(e => (
        <div key={e.id} className="p-4 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="font-medium text-gray-900 dark:text-white">{e.title}</p>
              <p className="text-sm text-gray-500 mt-0.5">
                {e.is_lunar ? '음력 ' : ''}{e.date}
                {e.member_id && memberMap.get(e.member_id) && ` · ${memberMap.get(e.member_id)!.name}`}
              </p>
              {e.description && <p className="text-sm text-gray-400 mt-1">{e.description}</p>}
            </div>
            <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 whitespace-nowrap flex-shrink-0">
              {e.event_type === 'birthday' ? '생일' : e.event_type === 'memorial' ? '기일' :
               e.event_type === 'wedding' ? '결혼' : e.event_type === 'holiday' ? '명절' :
               e.event_type === 'funeral' ? '장례' : '기타'}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function LedgerTab({ ledger, members }: { ledger: FamilyLedger[]; members: FamilyMember[] }) {
  const memberMap = new Map(members.map(m => [m.id, m]));

  const totalSent = ledger.filter(l => l.direction === 'sent').reduce((sum, l) => sum + (l.amount || 0), 0);
  const totalReceived = ledger.filter(l => l.direction === 'received').reduce((sum, l) => sum + (l.amount || 0), 0);

  if (ledger.length === 0) {
    return <EmptyState icon="🎁" message="부조/선물 기록이 없습니다" sub="+ 버튼으로 기록을 시작해보세요" />;
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="p-4 rounded-xl bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
          <p className="text-xs text-blue-600 dark:text-blue-400 font-medium">받은 총액</p>
          <p className="text-xl font-bold text-blue-700 dark:text-blue-300 mt-1">{totalReceived.toLocaleString()}원</p>
        </div>
        <div className="p-4 rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
          <p className="text-xs text-red-600 dark:text-red-400 font-medium">보낸 총액</p>
          <p className="text-xl font-bold text-red-700 dark:text-red-300 mt-1">{totalSent.toLocaleString()}원</p>
        </div>
      </div>

      <div className="space-y-2">
        {ledger.map(l => (
          <div key={l.id} className="flex items-center gap-3 p-3 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-sm">
            <span className="text-xl flex-shrink-0">{l.category === 'gift' ? '🎁' : '💰'}</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                {l.member_id && memberMap.get(l.member_id) ? memberMap.get(l.member_id)!.name : '(미지정)'}
                {l.item ? ` · ${l.item}` : ''}
              </p>
              <p className="text-xs text-gray-500">{l.date} {l.note ? `· ${l.note}` : ''}</p>
            </div>
            <span className={`text-sm font-bold whitespace-nowrap flex-shrink-0 ${
              l.direction === 'sent' ? 'text-red-500' : 'text-blue-500'
            }`}>
              {l.direction === 'sent' ? '-' : '+'}{l.amount?.toLocaleString() || '?'}원
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MemoriesTab({ memories, members }: { memories: FamilyMemory[]; members: FamilyMember[] }) {
  const memberMap = new Map(members.map(m => [m.id, m]));

  if (memories.length === 0) {
    return <EmptyState icon="📝" message="기록된 추억이 없습니다" sub="+ 버튼으로 가족의 이야기를 남겨보세요" />;
  }

  return (
    <div className="space-y-3">
      {memories.map(m => (
        <div key={m.id} className="p-4 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-sm">
          <div className="flex items-start gap-3">
            <span className="text-2xl mt-0.5 flex-shrink-0">📝</span>
            <div className="flex-1 min-w-0">
              <p className="font-medium text-gray-900 dark:text-white">{m.title}</p>
              {m.content && <p className="text-sm text-gray-500 mt-1 whitespace-pre-wrap line-clamp-4">{m.content}</p>}
              <div className="flex items-center gap-2 mt-2 text-xs text-gray-400">
                {m.date && <span>{m.date}</span>}
                {m.member_id && memberMap.get(m.member_id) && (
                  <span className="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800">
                    {memberMap.get(m.member_id)!.name}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ icon, message, sub }: { icon: string; message: string; sub: string }) {
  return (
    <div className="text-center py-16 px-4">
      <div className="text-5xl mb-3">{icon}</div>
      <p className="text-gray-500 dark:text-gray-400 font-medium">{message}</p>
      <p className="text-sm text-gray-400 mt-1">{sub}</p>
    </div>
  );
}
