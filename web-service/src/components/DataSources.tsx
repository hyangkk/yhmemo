"use client";

import { useState, useEffect, useCallback } from "react";

interface SourceStat {
  source: string;
  count: number;
  latest: string | null;
}

interface DataSourcesResponse {
  sources: SourceStat[];
  totalCollected: number;
  recentCount24h: number;
  curatedCount: number;
  updated_at: string;
}

// 소스 메타 정보
const SOURCE_META: Record<
  string,
  { label: string; type: string; icon: string; description: string }
> = {
  구글뉴스: {
    label: "Google News (종합)",
    type: "RSS",
    icon: "📰",
    description: "구글 뉴스 한국어 메인 피드",
  },
  구글뉴스_경제: {
    label: "Google News (경제)",
    type: "RSS",
    icon: "💰",
    description: "경제·금융 분야 뉴스",
  },
  구글뉴스_IT: {
    label: "Google News (IT/기술)",
    type: "RSS",
    icon: "💻",
    description: "IT·기술 분야 뉴스",
  },
  구글뉴스_AI: {
    label: "Google News (AI)",
    type: "RSS",
    icon: "🤖",
    description: "인공지능 관련 뉴스",
  },
  연합뉴스: {
    label: "연합뉴스",
    type: "RSS",
    icon: "🇰🇷",
    description: "대한민국 대표 통신사",
  },
  한국경제: {
    label: "한국경제",
    type: "RSS",
    icon: "📊",
    description: "경제·증시 전문 뉴스",
  },
  케이스타트업: {
    label: "K-Startup",
    type: "RSS",
    icon: "🚀",
    description: "스타트업·창업 관련 공고",
  },
  TechCrunch: {
    label: "TechCrunch",
    type: "RSS",
    icon: "⚡",
    description: "글로벌 테크 뉴스",
  },
  GeekNews: {
    label: "GeekNews",
    type: "RSS",
    icon: "🔧",
    description: "개발자·IT 커뮤니티 뉴스",
  },
  google_news_search: {
    label: "Google News (키워드 검색)",
    type: "RSS",
    icon: "🔍",
    description: "동적 키워드 기반 뉴스 검색",
  },
};

// 실시간 데이터 수집 소스 (API 기반)
const REALTIME_SOURCES = [
  {
    id: "coingecko",
    label: "CoinGecko",
    type: "API",
    icon: "🪙",
    description: "BTC, ETH, SOL, XRP, Gold 실시간 가격",
    frequency: "10분",
    status: "active" as const,
    assets: ["BTC", "ETH", "SOL", "XRP", "PAXG(Gold)"],
  },
  {
    id: "fear_greed",
    label: "Fear & Greed Index",
    type: "API",
    icon: "😱",
    description: "크립토 시장 심리 지수 (0-100)",
    frequency: "10분",
    status: "active" as const,
  },
  {
    id: "yfinance",
    label: "Yahoo Finance",
    type: "API",
    icon: "📈",
    description: "미국 주요 ETF OHLCV + 기술적 지표",
    frequency: "30분",
    status: "active" as const,
    assets: ["SPY", "QQQ", "IWM", "TLT", "GLD"],
  },
];

// 예정된 소스
const PLANNED_SOURCES = [
  {
    id: "onchain",
    label: "온체인 데이터",
    type: "API",
    icon: "⛓️",
    description: "블록체인 트랜잭션, 고래 움직임, 스마트컨트랙트 활동",
    priority: "P1",
  },
  {
    id: "social_sentiment",
    label: "소셜 센티먼트",
    type: "API",
    icon: "🐦",
    description: "X(Twitter), Reddit 커뮤니티 감성 분석",
    priority: "P1",
  },
  {
    id: "macro_data",
    label: "매크로 경제 지표",
    type: "API",
    icon: "🏛️",
    description: "금리, CPI, 고용지표 등 주요 경제 데이터",
    priority: "P2",
  },
  {
    id: "exchange_flow",
    label: "거래소 자금 흐름",
    type: "API",
    icon: "🏦",
    description: "거래소 입출금 추적, 스테이블코인 유통량",
    priority: "P2",
  },
];

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "—";
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "방금 전";
  if (mins < 60) return `${mins}분 전`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}시간 전`;
  const days = Math.floor(hours / 24);
  return `${days}일 전`;
}

export default function DataSources() {
  const [data, setData] = useState<DataSourcesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch("/api/data-sources");
      if (!res.ok) throw new Error("Failed to fetch");
      const json = await res.json();
      setData(json);
      setError(null);
    } catch {
      setError("데이터를 불러올 수 없습니다");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5 * 60 * 1000); // 5분마다 갱신
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-12">
        <div className="animate-pulse space-y-4">
          {[...Array(6)].map((_, i) => (
            <div
              key={i}
              className="h-20 bg-gray-200 dark:bg-gray-800 rounded-xl"
            />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-12 text-center text-red-500">
        {error}
      </div>
    );
  }

  const maxCount = Math.max(
    ...(data?.sources.map((s) => s.count) || [1])
  );

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-10">
      {/* 요약 통계 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          label="총 수집 건수"
          value={data?.totalCollected.toLocaleString() || "0"}
          icon="📦"
        />
        <StatCard
          label="최근 24시간"
          value={data?.recentCount24h.toLocaleString() || "0"}
          icon="⚡"
          highlight
        />
        <StatCard
          label="AI 큐레이션"
          value={data?.curatedCount?.toLocaleString() || "0"}
          icon="✨"
        />
        <StatCard
          label="활성 소스"
          value={String(
            (data?.sources.length || 0) + REALTIME_SOURCES.length
          )}
          icon="🔌"
        />
      </div>

      {/* 뉴스 수집 소스 (RSS) */}
      <section>
        <SectionHeader
          title="뉴스 수집 소스"
          subtitle="RSS 피드 기반 자동 수집 — 10분 간격"
          badge="ACTIVE"
          badgeColor="green"
        />
        <div className="space-y-3">
          {data?.sources.map((src) => {
            const meta = SOURCE_META[src.source];
            return (
              <SourceRow
                key={src.source}
                icon={meta?.icon || "📄"}
                label={meta?.label || src.source}
                type={meta?.type || "RSS"}
                description={meta?.description || ""}
                count={src.count}
                maxCount={maxCount}
                latest={src.latest}
                status="active"
              />
            );
          })}
          {(!data?.sources || data.sources.length === 0) && (
            <p className="text-gray-400 text-sm py-4 text-center">
              아직 수집된 데이터가 없습니다
            </p>
          )}
        </div>
      </section>

      {/* 실시간 시장 데이터 */}
      <section>
        <SectionHeader
          title="실시간 시장 데이터"
          subtitle="외부 API 기반 실시간 모니터링"
          badge="ACTIVE"
          badgeColor="green"
        />
        <div className="space-y-3">
          {REALTIME_SOURCES.map((src) => (
            <div
              key={src.id}
              className="flex items-start gap-4 p-4 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-green-300 dark:hover:border-green-700 transition-colors"
            >
              <span className="text-2xl flex-shrink-0 mt-0.5">{src.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-gray-900 dark:text-white">
                    {src.label}
                  </span>
                  <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300">
                    {src.type}
                  </span>
                  <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300">
                    {src.frequency} 간격
                  </span>
                </div>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {src.description}
                </p>
                {src.assets && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {src.assets.map((asset) => (
                      <span
                        key={asset}
                        className="px-2 py-0.5 rounded-md text-xs bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 font-mono"
                      >
                        {asset}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex-shrink-0">
                <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                  <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                  수집 중
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* AI 분석 보고서 */}
      <section>
        <SectionHeader
          title="AI 분석 보고서"
          subtitle="수집된 데이터 기반 AI 자동 생성"
          badge="ACTIVE"
          badgeColor="green"
        />
        <div className="space-y-3">
          <ReportRow
            icon="📋"
            label="투자 전략 리포트"
            schedule="매일 오전 9시 / 오후 3시 (KST)"
            topics={[
              "미국 증시",
              "한국 증시",
              "AI·반도체",
              "원자재·금·유가",
              "금리·통화정책",
              "지정학 리스크",
            ]}
          />
          <ReportRow
            icon="🧬"
            label="유전 알고리즘 전략 진화"
            schedule="30분 간격"
            topics={["SMA", "RSI", "ATR", "손절/익절", "백테스팅"]}
          />
          <ReportRow
            icon="📡"
            label="리딩방 진행 보고"
            schedule="30분 간격"
            topics={["슬롯 실행 결과", "인사이트 요약", "다음 계획"]}
          />
          <ReportRow
            icon="✨"
            label="뉴스 큐레이션"
            schedule="자동 (수집 시 즉시)"
            topics={["관련성 스코어링", "AI 요약", "Notion 연동"]}
          />
        </div>
      </section>

      {/* 수집 예정 소스 */}
      <section>
        <SectionHeader
          title="수집 예정 소스"
          subtitle="투자급 인사이트 플랫폼 고도화를 위해 추가 예정"
          badge="PLANNED"
          badgeColor="amber"
        />
        <div className="space-y-3">
          {PLANNED_SOURCES.map((src) => (
            <div
              key={src.id}
              className="flex items-start gap-4 p-4 rounded-xl bg-gray-50 dark:bg-gray-900/50 border border-dashed border-gray-300 dark:border-gray-700"
            >
              <span className="text-2xl flex-shrink-0 mt-0.5 opacity-60">
                {src.icon}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-gray-700 dark:text-gray-300">
                    {src.label}
                  </span>
                  <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300">
                    {src.priority}
                  </span>
                  <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
                    {src.type}
                  </span>
                </div>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  {src.description}
                </p>
              </div>
              <div className="flex-shrink-0">
                <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
                  <span className="w-2 h-2 rounded-full bg-amber-400" />
                  예정
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 데이터 흐름 */}
      <section>
        <SectionHeader
          title="데이터 처리 파이프라인"
          subtitle="수집 → 분석 → 시그널 도출 전체 흐름"
        />
        <div className="p-6 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
          <div className="flex flex-col sm:flex-row items-stretch gap-3">
            <PipelineStep
              step="1"
              title="수집"
              items={["RSS 11개 소스", "CoinGecko API", "Yahoo Finance", "Fear & Greed"]}
              color="blue"
            />
            <PipelineArrow />
            <PipelineStep
              step="2"
              title="저장"
              items={["Supabase DB", "중복 제거(SHA256)", "메타데이터 태깅"]}
              color="purple"
            />
            <PipelineArrow />
            <PipelineStep
              step="3"
              title="AI 분석"
              items={["관련성 스코어링", "크로스 분석", "전략 진화(GA)", "시그널 도출"]}
              color="green"
            />
            <PipelineArrow />
            <PipelineStep
              step="4"
              title="전달"
              items={["웹 대시보드", "Slack 알림", "Notion 기록", "API 제공"]}
              color="amber"
            />
          </div>
        </div>
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  icon,
  highlight,
}: {
  label: string;
  value: string;
  icon: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={`p-4 rounded-xl border ${
        highlight
          ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800"
          : "bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800"
      }`}
    >
      <div className="text-2xl mb-1">{icon}</div>
      <div className="text-2xl font-bold text-gray-900 dark:text-white">
        {value}
      </div>
      <div className="text-xs text-gray-500 dark:text-gray-400">{label}</div>
    </div>
  );
}

function SectionHeader({
  title,
  subtitle,
  badge,
  badgeColor,
}: {
  title: string;
  subtitle: string;
  badge?: string;
  badgeColor?: "green" | "amber";
}) {
  return (
    <div className="mb-4">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-bold text-gray-900 dark:text-white">
          {title}
        </h2>
        {badge && (
          <span
            className={`px-2 py-0.5 rounded-full text-xs font-bold ${
              badgeColor === "green"
                ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300"
                : "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300"
            }`}
          >
            {badge}
          </span>
        )}
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
        {subtitle}
      </p>
    </div>
  );
}

function SourceRow({
  icon,
  label,
  type,
  description,
  count,
  maxCount,
  latest,
  status,
}: {
  icon: string;
  label: string;
  type: string;
  description: string;
  count: number;
  maxCount: number;
  latest: string | null;
  status: "active" | "inactive";
}) {
  const barWidth = maxCount > 0 ? (count / maxCount) * 100 : 0;

  return (
    <div className="flex items-start gap-4 p-4 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 hover:border-green-300 dark:hover:border-green-700 transition-colors">
      <span className="text-2xl flex-shrink-0 mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-gray-900 dark:text-white">
            {label}
          </span>
          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300">
            {type}
          </span>
        </div>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">
          {description}
        </p>
        {/* 수집량 바 */}
        <div className="mt-2 flex items-center gap-3">
          <div className="flex-1 h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-violet-500 to-purple-500 rounded-full transition-all duration-500"
              style={{ width: `${barWidth}%` }}
            />
          </div>
          <span className="text-xs font-mono text-gray-500 dark:text-gray-400 flex-shrink-0">
            {count.toLocaleString()}건
          </span>
        </div>
      </div>
      <div className="flex-shrink-0 text-right">
        <span
          className={`inline-flex items-center gap-1 text-xs ${
            status === "active"
              ? "text-green-600 dark:text-green-400"
              : "text-gray-400"
          }`}
        >
          <span
            className={`w-2 h-2 rounded-full ${
              status === "active" ? "bg-green-500 animate-pulse" : "bg-gray-400"
            }`}
          />
          {status === "active" ? "수집 중" : "중지"}
        </span>
        <div className="text-xs text-gray-400 mt-1">{timeAgo(latest)}</div>
      </div>
    </div>
  );
}

function ReportRow({
  icon,
  label,
  schedule,
  topics,
}: {
  icon: string;
  label: string;
  schedule: string;
  topics: string[];
}) {
  return (
    <div className="flex items-start gap-4 p-4 rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
      <span className="text-2xl flex-shrink-0 mt-0.5">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-semibold text-gray-900 dark:text-white">
            {label}
          </span>
          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300">
            {schedule}
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5 mt-2">
          {topics.map((topic) => (
            <span
              key={topic}
              className="px-2 py-0.5 rounded-md text-xs bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
            >
              {topic}
            </span>
          ))}
        </div>
      </div>
      <div className="flex-shrink-0">
        <span className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
          <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          운영 중
        </span>
      </div>
    </div>
  );
}

function PipelineStep({
  step,
  title,
  items,
  color,
}: {
  step: string;
  title: string;
  items: string[];
  color: "blue" | "purple" | "green" | "amber";
}) {
  const colors = {
    blue: "from-blue-500 to-blue-600 bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800",
    purple:
      "from-purple-500 to-purple-600 bg-purple-50 dark:bg-purple-900/20 border-purple-200 dark:border-purple-800",
    green:
      "from-green-500 to-green-600 bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800",
    amber:
      "from-amber-500 to-amber-600 bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800",
  };
  const parts = colors[color].split(" ");
  const gradientFrom = parts[0];
  const gradientTo = parts[1];
  const bgClasses = parts.slice(2).join(" ");

  return (
    <div
      className={`flex-1 p-4 rounded-xl border ${bgClasses}`}
    >
      <div className="flex items-center gap-2 mb-2">
        <span
          className={`w-6 h-6 rounded-full bg-gradient-to-r ${gradientFrom} ${gradientTo} text-white text-xs font-bold flex items-center justify-center`}
        >
          {step}
        </span>
        <span className="font-semibold text-sm text-gray-900 dark:text-white">
          {title}
        </span>
      </div>
      <ul className="space-y-1">
        {items.map((item) => (
          <li
            key={item}
            className="text-xs text-gray-600 dark:text-gray-400 flex items-center gap-1.5"
          >
            <span className="w-1 h-1 rounded-full bg-gray-400" />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function PipelineArrow() {
  return (
    <div className="flex items-center justify-center sm:py-0 py-1">
      <svg
        className="w-5 h-5 text-gray-300 dark:text-gray-600 hidden sm:block"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M9 5l7 7-7 7"
        />
      </svg>
      <svg
        className="w-5 h-5 text-gray-300 dark:text-gray-600 sm:hidden"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M19 14l-7 7m0 0l-7-7"
        />
      </svg>
    </div>
  );
}
