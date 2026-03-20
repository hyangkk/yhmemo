'use client';

import { useState } from 'react';
import { FamilyMember, LedgerCategory, LedgerDirection } from '@/lib/family-types';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: {
    member_id?: string;
    category: LedgerCategory;
    direction: LedgerDirection;
    item?: string;
    amount?: number;
    note?: string;
    date: string;
  }) => void;
  members: FamilyMember[];
}

export default function AddLedgerModal({ isOpen, onClose, onSubmit, members }: Props) {
  const [category, setCategory] = useState<LedgerCategory>('gift');
  const [direction, setDirection] = useState<LedgerDirection>('sent');
  const [memberId, setMemberId] = useState('');
  const [item, setItem] = useState('');
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!date || submitting) return;
    setSubmitting(true);

    try {
      await onSubmit({
        member_id: memberId || undefined,
        category,
        direction,
        item: item || undefined,
        amount: amount ? parseInt(amount) : undefined,
        note: note || undefined,
        date,
      });
      setItem(''); setAmount(''); setNote(''); setMemberId('');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-900 rounded-t-2xl sm:rounded-2xl w-full sm:max-w-md max-h-[85vh] overflow-y-auto p-6 shadow-xl"
        onClick={e => e.stopPropagation()}>

        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold text-gray-900 dark:text-white">부조/선물 기록</h3>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">&times;</button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* 카테고리 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">종류</label>
            <div className="flex gap-3">
              <button type="button" onClick={() => setCategory('gift')}
                className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all active:scale-95 ${
                  category === 'gift'
                    ? 'border-pink-500 bg-pink-50 dark:bg-pink-900/30 text-pink-700 dark:text-pink-300'
                    : 'border-gray-300 dark:border-gray-700 text-gray-500'
                }`}>🎁 선물</button>
              <button type="button" onClick={() => setCategory('condolence')}
                className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all active:scale-95 ${
                  category === 'condolence'
                    ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
                    : 'border-gray-300 dark:border-gray-700 text-gray-500'
                }`}>💰 부조금</button>
            </div>
          </div>

          {/* 방향 */}
          <div>
            <div className="flex gap-3">
              <button type="button" onClick={() => setDirection('sent')}
                className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all active:scale-95 ${
                  direction === 'sent'
                    ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                    : 'border-gray-300 dark:border-gray-700 text-gray-500'
                }`}>보낸 것</button>
              <button type="button" onClick={() => setDirection('received')}
                className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all active:scale-95 ${
                  direction === 'received'
                    ? 'border-amber-500 bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'
                    : 'border-gray-300 dark:border-gray-700 text-gray-500'
                }`}>받은 것</button>
            </div>
          </div>

          {/* 대상 */}
          {members.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">누구에게/누구로부터</label>
              <select value={memberId} onChange={e => setMemberId(e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm">
                <option value="">선택 안함</option>
                {members.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* 내용/금액 */}
          {category === 'gift' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">선물 내용</label>
              <input type="text" value={item} onChange={e => setItem(e.target.value)}
                className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
                placeholder="예: 한우 세트, 홍삼" />
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">금액 (원)</label>
            <input type="number" value={amount} onChange={e => setAmount(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              placeholder="50000" inputMode="numeric" />
          </div>

          {/* 날짜 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">날짜</label>
            <input type="date" value={date} onChange={e => setDate(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white" required />
          </div>

          {/* 메모 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">메모</label>
            <input type="text" value={note} onChange={e => setNote(e.target.value)}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white"
              placeholder="예: 결혼식 축의금" />
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
