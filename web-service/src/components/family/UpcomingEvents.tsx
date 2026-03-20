'use client';

import { FamilyMember, FamilyEvent } from '@/lib/family-types';
import { getUpcomingDate, getDDay, formatKoreanDate } from '@/lib/lunar-calendar';

interface Props {
  members: FamilyMember[];
  events: FamilyEvent[];
}

interface UpcomingItem {
  id: string;
  title: string;
  subtitle: string;
  date: Date;
  dday: number;
  icon: string;
  type: 'birthday' | 'memorial' | 'event';
}

export default function UpcomingEvents({ members, events }: Props) {
  const now = new Date();
  const year = now.getFullYear();
  const upcoming: UpcomingItem[] = [];

  // 구성원 생일
  for (const m of members) {
    if (!m.birth_date || m.is_deceased) continue;
    const date = getUpcomingDate(m.birth_date, m.is_lunar_birth, year);
    let dday = getDDay(date);
    // 이미 지났으면 내년
    if (dday < -1) {
      const nextDate = getUpcomingDate(m.birth_date, m.is_lunar_birth, year + 1);
      const nextDday = getDDay(nextDate);
      upcoming.push({
        id: `bday-${m.id}`,
        title: `${m.name} 생일`,
        subtitle: formatKoreanDate(m.birth_date, m.is_lunar_birth),
        date: nextDate,
        dday: nextDday,
        icon: '🎂',
        type: 'birthday',
      });
    } else {
      upcoming.push({
        id: `bday-${m.id}`,
        title: `${m.name} 생일`,
        subtitle: formatKoreanDate(m.birth_date, m.is_lunar_birth),
        date,
        dday,
        icon: '🎂',
        type: 'birthday',
      });
    }
  }

  // 고인 기일
  for (const m of members) {
    if (!m.death_date || !m.is_deceased) continue;
    const date = getUpcomingDate(m.death_date, false, year);
    let dday = getDDay(date);
    if (dday < -1) {
      const nextDate = getUpcomingDate(m.death_date, false, year + 1);
      dday = getDDay(nextDate);
      upcoming.push({
        id: `memorial-${m.id}`,
        title: `${m.name} 기일`,
        subtitle: formatKoreanDate(m.death_date, false),
        date: nextDate,
        dday,
        icon: '🕯️',
        type: 'memorial',
      });
    } else {
      upcoming.push({
        id: `memorial-${m.id}`,
        title: `${m.name} 기일`,
        subtitle: formatKoreanDate(m.death_date, false),
        date,
        dday,
        icon: '🕯️',
        type: 'memorial',
      });
    }
  }

  // 등록된 이벤트
  for (const e of events) {
    if (e.event_type === 'birthday' || e.event_type === 'memorial') continue; // 중복 제거
    const date = getUpcomingDate(e.date, e.is_lunar, year);
    const dday = getDDay(date);
    if (dday >= -1 && dday <= 90) {
      upcoming.push({
        id: `event-${e.id}`,
        title: e.title,
        subtitle: formatKoreanDate(e.date, e.is_lunar),
        date,
        dday,
        icon: e.event_type === 'wedding' ? '💒' : e.event_type === 'holiday' ? '🏮' : '📌',
        type: 'event',
      });
    }
  }

  // D-Day 순 정렬
  upcoming.sort((a, b) => a.dday - b.dday);

  // 가까운 10개만
  const display = upcoming.slice(0, 10);

  if (display.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400 text-sm">
        다가오는 일정이 없습니다
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {display.map(item => (
        <div key={item.id} className="flex items-center gap-3 p-3 rounded-xl bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors">
          <span className="text-2xl">{item.icon}</span>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-gray-900 dark:text-white truncate">{item.title}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400">{item.subtitle}</p>
          </div>
          <DdayBadge dday={item.dday} />
        </div>
      ))}
    </div>
  );
}

function DdayBadge({ dday }: { dday: number }) {
  let text: string;
  let color: string;

  if (dday === 0) {
    text = 'D-Day';
    color = 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300';
  } else if (dday < 0) {
    text = `D+${Math.abs(dday)}`;
    color = 'bg-gray-100 dark:bg-gray-800 text-gray-500';
  } else if (dday <= 7) {
    text = `D-${dday}`;
    color = 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400';
  } else if (dday <= 30) {
    text = `D-${dday}`;
    color = 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300';
  } else {
    text = `D-${dday}`;
    color = 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300';
  }

  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-bold whitespace-nowrap ${color}`}>
      {text}
    </span>
  );
}
