'use client';

import { useState, useEffect, useRef } from 'react';

interface Props {
  onAddMember: () => void;
  onAddEvent: () => void;
  onAddMemory: () => void;
  onAddLedger: () => void;
}

export default function QuickAddButton({ onAddMember, onAddEvent, onAddMemory, onAddLedger }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // 바깥 클릭으로 메뉴 닫기
  useEffect(() => {
    if (!isOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isOpen]);

  const actions = [
    { label: '구성원 추가', icon: '👤', onClick: onAddMember, color: 'bg-blue-500' },
    { label: '일정 추가', icon: '📅', onClick: onAddEvent, color: 'bg-amber-500' },
    { label: '추억 기록', icon: '📝', onClick: onAddMemory, color: 'bg-purple-500' },
    { label: '부조/선물', icon: '🎁', onClick: onAddLedger, color: 'bg-pink-500' },
  ];

  return (
    <div ref={containerRef} className="fixed bottom-6 right-6 z-40 flex flex-col items-end gap-2">
      {/* 액션 메뉴 */}
      <div className={`flex flex-col gap-2 mb-2 transition-all duration-200 ${
        isOpen ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4 pointer-events-none'
      }`}>
        {actions.map((action, i) => (
          <button
            key={action.label}
            onClick={() => { action.onClick(); setIsOpen(false); }}
            className="flex items-center gap-2 px-4 py-2.5 rounded-full bg-white dark:bg-gray-800 shadow-lg border border-gray-200 dark:border-gray-700 hover:shadow-xl active:scale-95 transition-all"
            style={{ transitionDelay: isOpen ? `${(actions.length - 1 - i) * 30}ms` : '0ms' }}
          >
            <span className={`w-8 h-8 rounded-full ${action.color} flex items-center justify-center text-sm`}>
              {action.icon}
            </span>
            <span className="text-sm font-medium text-gray-800 dark:text-gray-200 whitespace-nowrap">
              {action.label}
            </span>
          </button>
        ))}
      </div>

      {/* FAB 버튼 */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`w-14 h-14 rounded-full shadow-xl flex items-center justify-center text-white text-2xl transition-all duration-200 active:scale-90
          ${isOpen
            ? 'bg-gray-600 rotate-45'
            : 'bg-emerald-600 hover:bg-emerald-700 hover:scale-105'
          }`}
      >
        +
      </button>
    </div>
  );
}
