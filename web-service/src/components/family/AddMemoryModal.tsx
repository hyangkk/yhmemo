'use client';

import { useState } from 'react';
import { FamilyMember } from '@/lib/family-types';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: {
    member_id?: string;
    title: string;
    content?: string;
    date?: string;
  }) => void;
  members: FamilyMember[];
}

export default function AddMemoryModal({ isOpen, onClose, onSubmit, members }: Props) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [memberId, setMemberId] = useState('');
  const [date, setDate] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || submitting) return;
    setSubmitting(true);

    try {
      await onSubmit({
        member_id: memberId || undefined,
        title: title.trim(),
        content: content || undefined,
        date: date || undefined,
      });
      setTitle(''); setContent(''); setMemberId(''); setDate('');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-900 rounded-t-2xl sm:rounded-2xl w-full sm:max-w-md max-h-[85vh] overflow-y-auto p-6 shadow-xl"
        onClick={e => e.stopPropagation()}>

        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">추억 기록</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">&times;</button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* 제목 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">제목 *</label>
            <input type="text" value={title} onChange={e => setTitle(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-emerald-500 focus:border-transparent"
              placeholder="예: 2025 설날 할머니댁 모임" required />
          </div>

          {/* 관련 인물 */}
          {members.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">관련 인물</label>
              <select value={memberId} onChange={e => setMemberId(e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm">
                <option value="">전체 가족</option>
                {members.map(m => (
                  <option key={m.id} value={m.id}>{m.name} {m.is_deceased ? '(故)' : ''}</option>
                ))}
              </select>
            </div>
          )}

          {/* 날짜 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">날짜</label>
            <input type="date" value={date} onChange={e => setDate(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white" />
          </div>

          {/* 내용 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">내용</label>
            <textarea value={content} onChange={e => setContent(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white resize-none"
              rows={4} placeholder="어떤 일이 있었는지, 느낌, 에피소드..." />
          </div>

          <div className="flex gap-3 pt-2 pb-safe">
            <button type="button" onClick={onClose}
              className="flex-1 py-3 rounded-lg border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors active:scale-95">취소</button>
            <button type="submit" disabled={submitting}
              className="flex-1 py-3 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium transition-colors active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed">
              {submitting ? '기록 중...' : '기록'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
