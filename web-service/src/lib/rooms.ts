export interface StrategyRoom {
  id: string;
  name: string;
  subtitle: string;
  description: string;
  icon: string;
  gradient: string;
  accentColor: string;
  status: "active" | "coming_soon";
  path: string;
  features: string[];
}

export const ROOMS: StrategyRoom[] = [
  {
    id: "invest",
    name: "AI 투자전략실",
    subtitle: "Investment Strategy",
    description:
      "실시간 시장 시그널 포착 + 뉴스 크로스 분석 + 투자 전략 제시. AI가 24시간 시장을 모니터링합니다.",
    icon: "📈",
    gradient: "from-amber-500 to-orange-600",
    accentColor: "amber",
    status: "active",
    path: "/invest",
    features: ["실시간 시그널", "크로스 분석", "24시간 운영"],
  },
  {
    id: "healthcare",
    name: "AI 헬스케어 사업전략실",
    subtitle: "Healthcare Strategy",
    description:
      "헬스케어·바이오 산업 동향 분석 + 규제 변화 추적 + 사업 기회 포착. 데이터 기반 전략 수립을 지원합니다.",
    icon: "🏥",
    gradient: "from-emerald-500 to-teal-600",
    accentColor: "emerald",
    status: "coming_soon",
    path: "/healthcare",
    features: ["산업 동향", "규제 추적", "기회 분석"],
  },
  {
    id: "marketing",
    name: "AI 마케팅 전략실",
    subtitle: "Marketing Strategy",
    description:
      "소비자 트렌드 분석 + 경쟁사 모니터링 + 캠페인 인사이트. AI가 마케팅 의사결정을 지원합니다.",
    icon: "📢",
    gradient: "from-pink-500 to-rose-600",
    accentColor: "pink",
    status: "coming_soon",
    path: "/marketing",
    features: ["트렌드 분석", "경쟁사 추적", "캠페인 인사이트"],
  },
];

export function getRoomById(id: string): StrategyRoom | undefined {
  return ROOMS.find((r) => r.id === id);
}
