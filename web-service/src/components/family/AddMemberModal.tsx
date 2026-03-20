'use client';

import { useState } from 'react';
import { FamilyMember, RelationType } from '@/lib/family-types';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: {
    name: string;
    gender: 'male' | 'female';
    birth_date?: string;
    is_lunar_birth?: boolean;
    death_date?: string;
    is_deceased?: boolean;
    bio?: string;
    relation?: { targetId: string; type: RelationType };
  }) => void;
  existingMembers: FamilyMember[];
}

export default function AddMemberModal({ isOpen, onClose, onSubmit, existingMembers }: Props) {
  const [name, setName] = useState('');
  const [gender, setGender] = useState<'male' | 'female'>('male');
  const [birthDate, setBirthDate] = useState('');
  const [isLunarBirth, setIsLunarBirth] = useState(false);
  const [isDeceased, setIsDeceased] = useState(false);
  const [deathDate, setDeathDate] = useState('');
  const [bio, setBio] = useState('');
  const [relationTargetId, setRelationTargetId] = useState('');
  const [relationType, setRelationType] = useState<RelationType>('child');
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || submitting) return;
    setSubmitting(true);

    try {
      await onSubmit({
        name: name.trim(),
        gender,
        birth_date: birthDate || undefined,
        is_lunar_birth: isLunarBirth,
        death_date: isDeceased && deathDate ? deathDate : undefined,
        is_deceased: isDeceased,
        bio: bio || undefined,
        relation: relationTargetId ? { targetId: relationTargetId, type: relationType } : undefined,
      });
      // 리셋
      setName(''); setGender('male'); setBirthDate(''); setIsLunarBirth(false);
      setIsDeceased(false); setDeathDate(''); setBio('');
      setRelationTargetId(''); setRelationType('child');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-900 rounded-t-2xl sm:rounded-2xl w-full sm:max-w-md max-h-[85vh] overflow-y-auto p-6 shadow-xl"
        onClick={e => e.stopPropagation()}>

        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">가족 구성원 추가</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">&times;</button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* 이름 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">이름 *</label>
            <input type="text" value={name} onChange={e => setName(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-emerald-500 focus:border-transparent transition-shadow"
              placeholder="홍길동" required />
          </div>

          {/* 성별 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">성별 *</label>
            <div className="flex gap-3">
              <button type="button" onClick={() => setGender('male')}
                className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all active:scale-95 ${
                  gender === 'male'
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                    : 'border-gray-300 dark:border-gray-700 text-gray-500'
                }`}>남성</button>
              <button type="button" onClick={() => setGender('female')}
                className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all active:scale-95 ${
                  gender === 'female'
                    ? 'border-pink-500 bg-pink-50 dark:bg-pink-900/30 text-pink-700 dark:text-pink-300'
                    : 'border-gray-300 dark:border-gray-700 text-gray-500'
                }`}>여성</button>
            </div>
          </div>

          {/* 생년월일 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">생년월일</label>
            <div className="flex gap-2 items-center">
              <input type="date" value={birthDate} onChange={e => setBirthDate(e.target.value)}
                className="flex-1 px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white" />
              <label className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap cursor-pointer">
                <input type="checkbox" checked={isLunarBirth} onChange={e => setIsLunarBirth(e.target.checked)}
                  className="rounded border-gray-300 text-emerald-600 focus:ring-emerald-500" />
                음력
              </label>
            </div>
          </div>

          {/* 고인 여부 */}
          <div>
            <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
              <input type="checkbox" checked={isDeceased} onChange={e => setIsDeceased(e.target.checked)}
                className="rounded border-gray-300 text-emerald-600 focus:ring-emerald-500" />
              고인 (돌아가신 분)
            </label>
            {isDeceased && (
              <input type="date" value={deathDate} onChange={e => setDeathDate(e.target.value)}
                className="mt-2 w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                placeholder="기일" />
            )}
          </div>

          {/* 관계 설정 */}
          {existingMembers.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">관계 (선택)</label>
              <div className="flex gap-2">
                <select value={relationTargetId} onChange={e => setRelationTargetId(e.target.value)}
                  className="flex-1 px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm">
                  <option value="">관계 없음</option>
                  {existingMembers.map(m => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                </select>
                <select value={relationType} onChange={e => setRelationType(e.target.value as RelationType)}
                  className="px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm">
                  <option value="child">의 자녀</option>
                  <option value="parent">의 부모</option>
                  <option value="spouse">의 배우자</option>
                </select>
              </div>
              {relationTargetId && (
                <p className="mt-1.5 text-xs text-emerald-600 dark:text-emerald-400">
                  {name || '새 구성원'}은(는) {existingMembers.find(m => m.id === relationTargetId)?.name}
                  {relationType === 'child' ? '의 자녀' : relationType === 'parent' ? '의 부모' : '의 배우자'}
                </p>
              )}
            </div>
          )}

          {/* 메모 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">한줄 소개</label>
            <input type="text" value={bio} onChange={e => setBio(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              placeholder="예: 서울 강남구 거주, 교사" />
          </div>

          {/* 버튼 */}
          <div className="flex gap-3 pt-2 pb-safe">
            <button type="button" onClick={onClose}
              className="flex-1 py-3 rounded-lg border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors active:scale-95">
              취소
            </button>
            <button type="submit" disabled={submitting}
              className="flex-1 py-3 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium transition-colors active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed">
              {submitting ? '추가 중...' : '추가'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
