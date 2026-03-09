"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

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

export default function CollectionSummary() {
  const [data, setData] = useState<DataSourcesResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/data-sources")
      .then((res) => res.json())
      .then((json) => {
        setData(json);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto px-4 py-6">
        <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white/80 dark:bg-gray-900/80 backdrop-blur p-6 animate-pulse">
          <div className="h-5 w-40 bg-gray-200 dark:bg-gray-700 rounded mb-4" />
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-16 bg-gray-100 dark:bg-gray-800 rounded-xl" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const activeSources = data.sources.length;
  const lastUpdated = data.updated_at
    ? formatRelativeTime(new Date(data.updated_at))
    : "";

  // 최근 활동 소스 (24시간 내 수집된 상위 소스)
  const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const recentSources = data.sources
    .filter((s) => s.latest && s.latest > oneDayAgo)
    .slice(0, 5);

  return (
    <div className="max-w-5xl mx-auto px-4 py-6">
      <Link href="/sources" className="block group">
        <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white/80 dark:bg-gray-900/80 backdrop-blur p-5 sm:p-6 transition-all hover:border-violet-300 dark:hover:border-violet-700 hover:shadow-lg hover:shadow-violet-500/5">
          {/* 헤더 */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-purple-600 flex items-center justify-center">
                <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7M4 7c0-2 1-3 3-3h10c2 0 3 1 3 3M4 7h16M8 11h.01M12 11h.01M16 11h.01" />
                </svg>
              </div>
              <h3 className="text-base font-bold text-gray-900 dark:text-white">
                정보 수집 현황
              </h3>
            </div>
            <div className="flex items-center gap-1.5 text-sm text-violet-600 dark:text-violet-400 opacity-0 group-hover:opacity-100 transition-opacity">
              상세보기
              <svg className="w-4 h-4 transition-transform group-hover:translate-x-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </div>
          </div>

          {/* 통계 카드 */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard
              label="전체 수집"
              value={data.totalCollected.toLocaleString()}
              icon={
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
              }
              color="blue"
            />
            <StatCard
              label="24시간"
              value={`+${data.recentCount24h.toLocaleString()}`}
              icon={
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              }
              color="green"
            />
            <StatCard
              label="AI 큐레이션"
              value={data.curatedCount.toLocaleString()}
              icon={
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              }
              color="purple"
            />
            <StatCard
              label="활성 소스"
              value={`${activeSources}개`}
              icon={
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              }
              color="amber"
            />
          </div>

          {/* 최근 활동 소스 태그 + 업데이트 시간 */}
          <div className="mt-4 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-1.5 flex-wrap">
              {recentSources.map((s) => (
                <span
                  key={s.source}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-xs text-gray-600 dark:text-gray-400"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                  {s.source}
                </span>
              ))}
              {data.sources.length > 5 && (
                <span className="text-xs text-gray-400 dark:text-gray-500">
                  +{data.sources.length - 5}
                </span>
              )}
            </div>
            {lastUpdated && (
              <span className="text-xs text-gray-400 dark:text-gray-500">
                {lastUpdated} 업데이트
              </span>
            )}
          </div>
        </div>
      </Link>
    </div>
  );
}

function StatCard({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  color: "blue" | "green" | "purple" | "amber";
}) {
  const colors = {
    blue: "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/50",
    green: "text-green-600 dark:text-green-400 bg-green-50 dark:bg-green-950/50",
    purple: "text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-950/50",
    amber: "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/50",
  };

  return (
    <div className="rounded-xl bg-gray-50 dark:bg-gray-800/50 p-3">
      <div className="flex items-center gap-1.5 mb-1">
        <div className={`w-5 h-5 rounded flex items-center justify-center ${colors[color]}`}>
          {icon}
        </div>
        <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
      </div>
      <p className={`text-lg font-bold ${colors[color].split(" ").slice(0, 2).join(" ")}`}>
        {value}
      </p>
    </div>
  );
}

function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);

  if (diffMin < 1) return "방금";
  if (diffMin < 60) return `${diffMin}분 전`;

  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour}시간 전`;

  const diffDay = Math.floor(diffHour / 24);
  return `${diffDay}일 전`;
}
