"use client";

import { useEffect, useState } from "react";

interface Topic {
  name: string;
  count: number;
  heat: "hot" | "warm" | "cool";
  emoji: string;
  one_liner: string;
}

interface TrendData {
  topics: Topic[];
  keywords: string[];
  emerging: string;
  summary: string;
  newsCount: number;
  generatedAt: string;
}

const heatConfig = {
  hot: {
    bg: "bg-red-50 dark:bg-red-900/20",
    border: "border-red-200 dark:border-red-800/50",
    badge: "bg-red-500 text-white",
    label: "HOT",
  },
  warm: {
    bg: "bg-amber-50 dark:bg-amber-900/20",
    border: "border-amber-200 dark:border-amber-800/50",
    badge: "bg-amber-500 text-white",
    label: "WARM",
  },
  cool: {
    bg: "bg-gray-50 dark:bg-gray-800/50",
    border: "border-gray-200 dark:border-gray-800",
    badge: "bg-gray-400 text-white",
    label: "",
  },
};

const TREND_REFRESH = 10 * 60; // seconds

export default function TrendingTopics() {
  const [data, setData] = useState<TrendData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [countdown, setCountdown] = useState(TREND_REFRESH);

  async function fetchTrends() {
    try {
      setError(false);
      const res = await fetch("/api/trends");
      if (res.ok) {
        setData(await res.json());
      } else {
        setError(true);
      }
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchTrends();
    const interval = setInterval(fetchTrends, TREND_REFRESH * 1000);
    const onVisible = () => { if (!document.hidden) fetchTrends(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 카운트다운
  useEffect(() => {
    setCountdown(TREND_REFRESH);
    const timer = setInterval(() => {
      setCountdown((prev) => (prev <= 1 ? TREND_REFRESH : prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [data]);

  if (loading) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-6">
        <div className="animate-pulse space-y-3">
          <div className="h-8 w-48 bg-gray-200 dark:bg-gray-800 rounded-lg" />
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-24 bg-gray-100 dark:bg-gray-800 rounded-xl"
              />
            ))}
          </div>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-6">
        <div className="rounded-xl border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/10 p-6 text-center">
          <p className="text-sm text-red-600 dark:text-red-400 mb-2">트렌드 데이터를 불러오지 못했습니다</p>
          <button onClick={fetchTrends} className="px-4 py-2 rounded-lg bg-red-600 text-white text-xs font-medium hover:bg-red-700 transition">
            다시 시도
          </button>
        </div>
      </section>
    );
  }

  if (!data || !data.topics || data.topics.length === 0) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-6">
        <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 p-6 text-center">
          <p className="text-2xl mb-2">📊</p>
          <p className="text-sm text-gray-500 dark:text-gray-400">아직 분석할 뉴스가 충분하지 않습니다.</p>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">뉴스가 수집되면 자동으로 트렌드가 표시됩니다.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="max-w-5xl mx-auto px-4 py-6">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <span className="w-8 h-8 rounded-lg bg-gradient-to-r from-rose-500 to-pink-600 flex items-center justify-center text-white text-sm">
            #
          </span>
          지금 뜨는 토픽
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">{data.newsCount}개 뉴스 분석</span>
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-rose-50 dark:bg-rose-900/20 text-rose-600 dark:text-rose-400 text-xs font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-pulse" />
            {countdown < 60 ? `${countdown}초` : `${Math.floor(countdown / 60)}분`} 후 갱신
          </span>
        </div>
      </div>

      {/* 떠오르는 이슈 */}
      {data.emerging && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-gradient-to-r from-yellow-50 to-amber-50 dark:from-yellow-900/10 dark:to-amber-900/10 border border-yellow-200 dark:border-yellow-800/50">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold text-yellow-700 dark:text-yellow-400 bg-yellow-200 dark:bg-yellow-800/50 px-2 py-0.5 rounded-full">
              NEW
            </span>
            <p className="text-sm font-medium text-gray-800 dark:text-gray-200">
              {data.emerging}
            </p>
          </div>
        </div>
      )}

      {/* 토픽 카드 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {data.topics.map((topic, i) => {
          const cfg = heatConfig[topic.heat] || heatConfig.cool;
          return (
            <div
              key={i}
              className={`relative rounded-xl border p-4 ${cfg.bg} ${cfg.border} transition-all hover:shadow-md`}
            >
              {topic.heat !== "cool" && (
                <span
                  className={`absolute top-2 right-2 text-[10px] font-bold px-1.5 py-0.5 rounded-full ${cfg.badge}`}
                >
                  {cfg.label}
                </span>
              )}
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xl">{topic.emoji}</span>
                <span className="font-bold text-gray-900 dark:text-white text-sm">
                  {topic.name}
                </span>
              </div>
              <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">
                {topic.one_liner}
              </p>
              <p className="text-[10px] text-gray-400 mt-2">
                관련 뉴스 {topic.count}건
              </p>
            </div>
          );
        })}
      </div>

      {/* 키워드 태그 */}
      <div className="mt-4 flex flex-wrap gap-2">
        {data.keywords.map((kw, i) => (
          <span
            key={i}
            className="px-3 py-1 rounded-full bg-gray-100 dark:bg-gray-800 text-xs font-medium text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700"
          >
            #{kw}
          </span>
        ))}
      </div>

      {/* 요약 */}
      {data.summary && (
        <p className="mt-4 text-sm text-gray-500 dark:text-gray-400 leading-relaxed">
          {data.summary}
        </p>
      )}
    </section>
  );
}
