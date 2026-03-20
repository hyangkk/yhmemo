'use client';

import { useState } from 'react';
import { FamilyMember, EventType } from '@/lib/family-types';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (data: {
    member_id?: string;
    event_type: EventType;
    title: string;
    date: string;
    is_lunar?: boolean;
    description?: string;
  }) => void;
  members: FamilyMember[];
}

const EVENT_TYPES: { value: EventType; label: string; icon: string }[] = [
  { value: 'birthday', label: '생일', icon: '🎂' },
  { value: 'memorial', label: '기일', icon: '🕯️' },
  { value: 'wedding', label: '결혼', icon: '💒' },
  { value: 'funeral', label: '장례', icon: '🙏' },
  { value: 'holiday', label: '명절/모임', icon: '🏮' },
  { value: 'other', label: '기타', icon: '📌' },
];

export default function AddEventModal({ isOpen, onClose, onSubmit, members }: Props) {
  const [eventType, setEventType] = useState<EventType>('holiday');
  const [title, setTitle] = useState('');
  const [date, setDate] = useState('');
  const [isLunar, setIsLunar] = useState(false);
  const [memberId, setMemberId] = useState('');
  const [description, setDescription] = useState('');

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !date) return;

    onSubmit({
      member_id: memberId || undefined,
      event_type: eventType,
      title: title.trim(),
      date,
      is_lunar: isLunar,
      description: description || undefined,
    });

    setTitle(''); setDate(''); setIsLunar(false); setMemberId(''); setDescription('');
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-900 rounded-2xl w-full max-w-md max-h-[90vh] overflow-y-auto p-6 shadow-xl"
        onClick={e => e.stopPropagation()}>

        <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-4">일정 추가</h3>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* 이벤트 유형 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">종류</label>
            <div className="grid grid-cols-3 gap-2">
              {EVENT_TYPES.map(et => (
                <button key={et.value} type="button" onClick={() => setEventType(et.value)}
                  className={`py-2 rounded-lg border text-sm font-medium transition-colors ${
                    eventType === et.value
                      ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
                      : 'border-gray-300 dark:border-gray-700 text-gray-500'
                  }`}>
                  {et.icon} {et.label}
                </button>
              ))}
            </div>
          </div>

          {/* 제목 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">제목 *</label>
            <input type="text" value={title} onChange={e => setTitle(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:ring-2 focus:ring-emerald-500"
              placeholder="예: 2026 설날 모임" required />
          </div>

          {/* 날짜 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">날짜 *</label>
            <div className="flex gap-2 items-center">
              <input type="date" value={date} onChange={e => setDate(e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white" required />
              <label className="flex items-center gap-1 text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap">
                <input type="checkbox" checked={isLunar} onChange={e => setIsLunar(e.target.checked)} className="rounded" />
                음력
              </label>
            </div>
          </div>

          {/* 관련 인물 */}
          {members.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">관련 인물</label>
              <select value={memberId} onChange={e => setMemberId(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm">
                <option value="">선택 안함</option>
                {members.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* 메모 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">메모</label>
            <textarea value={description} onChange={e => setDescription(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white resize-none"
              rows={2} placeholder="어디서 뭘 했는지, 누가 왔는지..." />
          </div>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose}
              className="flex-1 py-2.5 rounded-lg border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium">취소</button>
            <button type="submit"
              className="flex-1 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium">추가</button>
          </div>
        </form>
      </div>
    </div>
  );
}
