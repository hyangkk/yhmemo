"use client";

import { useEffect, useState } from "react";
import NewsCard from "./NewsCard";

interface NewsItem {
  id?: string;
  title: string;
  url: string;
  source: string;
  content?: string;
  created_at?: string;
  ai_summary?: string;
  relevance_score?: number;
}

interface BriefingData {
  collected: NewsItem[];
  curated: NewsItem[];
  total: number;
  updated_at: string;
}

export default function Dashboard() {
  const [data, setData] = useState<BriefingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    fetchData();
    // 5분마다 자동 갱신
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  async function fetchData() {
    try {
      const res = await fetch("/api/briefings?limit=30");
      if (!res.ok) throw new Error("데이터를 불러올 수 없습니다");
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "오류 발생");
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-12">
        <div className="grid gap-4">
          {[...Array(5)].map((_, i) => (
            <div
              key={i}
              className="h-32 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse"
            />
          ))}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-12 text-center">
        <p className="text-red-500">{error}</p>
        <button
          onClick={fetchData}
          className="mt-4 px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition"
        >
          다시 시도
        </button>
      </section>
    );
  }

  const collected = data?.collected || [];
  const curated = data?.curated || [];

  // 소스 목록
  const sources = [...new Set(collected.map((item) => item.source))];

  const filtered =
    filter === "all"
      ? collected
      : collected.filter((item) => item.source === filter);

  return (
    <section className="max-w-5xl mx-auto px-4 py-8">
      {/* AI Pick 섹션 */}
      {curated.length > 0 && (
        <div className="mb-12">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-6 flex items-center gap-2">
            <span className="w-8 h-8 rounded-lg bg-gradient-to-r from-blue-500 to-purple-600 flex items-center justify-center text-white text-sm">
              AI
            </span>
            오늘의 AI Pick
          </h2>
          <div className="grid gap-4">
            {curated.map((item, i) => (
              <NewsCard key={`curated-${i}`} item={item} curated />
            ))}
          </div>
        </div>
      )}

      {/* 전체 뉴스 */}
      <div>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">
            최신 뉴스
            <span className="ml-2 text-sm font-normal text-gray-500">
              {filtered.length}건
            </span>
          </h2>

          {data?.updated_at && (
            <span className="text-xs text-gray-400">
              마지막 업데이트:{" "}
              {new Date(data.updated_at).toLocaleString("ko-KR")}
            </span>
          )}
        </div>

        {/* 소스 필터 */}
        {sources.length > 1 && (
          <div className="flex flex-wrap gap-2 mb-6">
            <button
              onClick={() => setFilter("all")}
              className={`px-3 py-1.5 rounded-full text-sm font-medium transition ${
                filter === "all"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300"
              }`}
            >
              전체
            </button>
            {sources.map((source) => (
              <button
                key={source}
                onClick={() => setFilter(source)}
                className={`px-3 py-1.5 rounded-full text-sm font-medium transition ${
                  filter === source
                    ? "bg-blue-600 text-white"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300"
                }`}
              >
                {source}
              </button>
            ))}
          </div>
        )}

        {filtered.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <p className="text-lg">아직 수집된 뉴스가 없습니다.</p>
            <p className="text-sm mt-2">
              AI 에이전트가 곧 뉴스를 수집해올 거예요.
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            {filtered.map((item, i) => (
              <NewsCard key={`news-${i}`} item={item} />
            ))}
          </div>
        )}
      </div>

      {/* 새로고침 버튼 */}
      <div className="mt-8 text-center">
        <button
          onClick={fetchData}
          className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition font-medium"
        >
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
          </svg>
          새로고침
        </button>
      </div>
    </section>
  );
}
