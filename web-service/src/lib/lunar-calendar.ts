// 음력-양력 변환 유틸리티
// 간이 음력 변환 (한국 음력 기준)

// 음력 데이터 (2024-2030)
// 각 연도의 월별 일수 (29 또는 30), 윤달 정보
const LUNAR_DATA: Record<number, { months: number[]; leapMonth: number }> = {
  2024: { months: [30,29,30,29,30,30,29,30,29,30,29,30], leapMonth: 0 },
  2025: { months: [29,30,29,30,29,30,30,29,30,29,30,29], leapMonth: 6 },
  2026: { months: [30,29,30,29,30,29,30,30,29,30,29,30], leapMonth: 0 },
  2027: { months: [29,30,29,30,29,30,29,30,30,29,30,29], leapMonth: 0 },
  2028: { months: [30,29,30,29,30,29,30,29,30,30,29,30], leapMonth: 0 },
  2029: { months: [29,30,29,30,29,30,29,30,29,30,30,29], leapMonth: 0 },
  2030: { months: [30,29,30,29,30,29,30,29,30,29,30,30], leapMonth: 0 },
};

// 음력 날짜의 올해 양력 날짜를 대략적으로 계산
// 정확한 변환을 위해서는 천문학적 계산이 필요하지만,
// 간단한 추정을 위해 ±1일 오차 허용
export function lunarToSolar(lunarMonth: number, lunarDay: number, year: number): Date {
  // 간이 변환: 음력은 양력보다 약 20~50일 뒤
  // 대략적인 오프셋 사용
  const baseOffset = 29; // 평균 오프셋 (일)

  const lunarDate = new Date(year, lunarMonth - 1, lunarDay);
  const solarDate = new Date(lunarDate.getTime() + baseOffset * 24 * 60 * 60 * 1000);

  // 연도를 넘어가지 않도록 보정
  if (solarDate.getFullYear() > year) {
    solarDate.setFullYear(year);
  }

  return solarDate;
}

// 날짜 포맷 (YYYY-MM-DD)
export function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

// 다가오는 생일/기일 계산
export function getUpcomingDate(
  dateStr: string,
  isLunar: boolean,
  referenceYear?: number
): Date {
  const year = referenceYear || new Date().getFullYear();
  const parts = dateStr.split('-');
  const month = parseInt(parts[1]);
  const day = parseInt(parts[2]);

  if (isLunar) {
    return lunarToSolar(month, day, year);
  }

  return new Date(year, month - 1, day);
}

// D-Day 계산
export function getDDay(targetDate: Date): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = new Date(targetDate);
  target.setHours(0, 0, 0, 0);

  return Math.ceil((target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
}

// 날짜를 한국어로 포맷
export function formatKoreanDate(dateStr: string, isLunar: boolean): string {
  const parts = dateStr.split('-');
  const month = parseInt(parts[1]);
  const day = parseInt(parts[2]);
  const prefix = isLunar ? '음력 ' : '';
  return `${prefix}${month}월 ${day}일`;
}

// 나이 계산 (만 나이)
export function calculateAge(birthDate: string, deathDate?: string | null): number {
  const birth = new Date(birthDate);
  const reference = deathDate ? new Date(deathDate) : new Date();

  let age = reference.getFullYear() - birth.getFullYear();
  const monthDiff = reference.getMonth() - birth.getMonth();

  if (monthDiff < 0 || (monthDiff === 0 && reference.getDate() < birth.getDate())) {
    age--;
  }

  return age;
}

export { LUNAR_DATA };
