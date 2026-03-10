"use client";

import { useEffect, useState, useCallback } from "react";

interface TrendingPost {
  title: string;
  url: string;
  score: number;
  comments: number;
  source: string;
  sourceIcon: string;
  sourceColor: string;
  createdAt: string;
  flair?: string;
  snippet?: string;
}

interface TrendingData {
  posts: TrendingPost[];
  sources: string[];
  fetchedAt: string;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}분 전`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}시간 전`;
  return `${Math.floor(hrs / 24)}일 전`;
}

function formatScore(n: number): string {
  if (n >= 10000) return `${(n / 1000).toFixed(0)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

const SOURCE_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  orange: { bg: "bg-orange-100 dark:bg-orange-900/30", text: "text-orange-700 dark:text-orange-300", border: "border-orange-200 dark:border-orange-800/50" },
  blue: { bg: "bg-blue-100 dark:bg-blue-900/30", text: "text-blue-700 dark:text-blue-300", border: "border-blue-200 dark:border-blue-800/50" },
};

export default function TrendingPosts() {
  const [data, setData] = useState<TrendingData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [filter, setFilter] = useState<string>("all");
  const [showAll, setShowAll] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      setError(false);
      const res = await fetch("/api/trending-posts");
      if (!res.ok) { setError(true); return; }
      setData(await res.json());
    } catch { setError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10 * 60 * 1000); // 10분 갱신
    const onVisible = () => {
      if (document.visibilityState === "visible") fetchData();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(interval); document.removeEventListener("visibilitychange", onVisible); };
  }, [fetchData]);

  if (loading) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-20 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="rounded-2xl border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/10 p-6 text-center">
          <p className="text-sm text-red-600 dark:text-red-400 mb-2">SNS 인기 글을 불러오지 못했습니다</p>
          <button onClick={fetchData} className="px-4 py-2 rounded-lg bg-red-600 text-white text-xs font-medium hover:bg-red-700 transition">다시 시도</button>
        </div>
      </section>
    );
  }

  if (!data || data.posts.length === 0) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 text-center">
          <p className="text-3xl mb-3">🌐</p>
          <p className="font-semibold text-gray-700 dark:text-gray-200 mb-1">SNS 인기 글 수집 중</p>
          <p className="text-sm text-gray-500 dark:text-gray-400">Reddit, CryptoPanic에서 인기 글을 가져오고 있습니다.</p>
        </div>
      </section>
    );
  }

  // 소스별 필터
  const uniqueSources = [...new Set(data.posts.map((p) => p.source))];
  const filtered = filter === "all" ? data.posts : data.posts.filter((p) => p.source === filter);
  const visible = showAll ? filtered : filtered.slice(0, 8);

  return (
    <section className="max-w-5xl mx-auto px-4 py-8 space-y-5">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <span className="w-8 h-8 rounded-lg bg-gradient-to-r from-rose-500 to-pink-600 flex items-center justify-center text-white text-sm">🔥</span>
          SNS 인기 글
        </h2>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-400 text-xs font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-pink-500 animate-pulse" />
            {data.posts.length}개 글
          </span>
          <span className="text-xs text-gray-400">{timeAgo(data.fetchedAt)}</span>
        </div>
      </div>

      {/* 소스 필터 */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => { setFilter("all"); setShowAll(false); }}
          className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
            filter === "all"
              ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900"
              : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
          }`}
        >
          전체
        </button>
        {uniqueSources.map((src) => (
          <button
            key={src}
            onClick={() => { setFilter(src); setShowAll(false); }}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
              filter === src
                ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900"
                : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
            }`}
          >
            {src}
          </button>
        ))}
      </div>

      {/* 글 목록 */}
      <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden shadow-sm">
        <div className="divide-y divide-gray-100 dark:divide-gray-800/50">
          {visible.map((post, i) => {
            const style = SOURCE_STYLES[post.sourceColor] || SOURCE_STYLES.orange;
            return (
              <a
                key={i}
                href={post.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-start gap-4 px-5 py-4 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors group"
              >
                {/* 순위 */}
                <div className="flex-shrink-0 w-7 h-7 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center">
                  <span className="text-xs font-bold text-gray-500 dark:text-gray-400">{i + 1}</span>
                </div>

                {/* 콘텐츠 */}
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-medium text-gray-800 dark:text-gray-200 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors line-clamp-2 leading-snug">
                    {post.title}
                  </h3>
                  <div className="mt-1.5 flex items-center flex-wrap gap-2">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${style.bg} ${style.text}`}>
                      {post.sourceIcon} {post.source}
                    </span>
                    {post.flair && (
                      <span className="px-2 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/30 text-[11px] text-purple-600 dark:text-purple-400 font-medium">
                        {post.flair}
                      </span>
                    )}
                    <span className="text-[11px] text-gray-400">{timeAgo(post.createdAt)}</span>
                  </div>
                </div>

                {/* 점수 + 댓글 */}
                <div className="flex-shrink-0 flex flex-col items-end gap-1">
                  <span className="inline-flex items-center gap-1 text-xs font-bold text-orange-500">
                    <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M3.293 9.707a1 1 0 010-1.414l6-6a1 1 0 011.414 0l6 6a1 1 0 01-1.414 1.414L11 5.414V17a1 1 0 11-2 0V5.414L4.707 9.707a1 1 0 01-1.414 0z" clipRule="evenodd" />
                    </svg>
                    {formatScore(post.score)}
                  </span>
                  {post.comments > 0 && (
                    <span className="text-[11px] text-gray-400 flex items-center gap-0.5">
                      💬 {formatScore(post.comments)}
                    </span>
                  )}
                </div>
              </a>
            );
          })}
        </div>

        {/* 더보기 */}
        {filtered.length > 8 && (
          <button
            onClick={() => setShowAll(!showAll)}
            className="w-full px-4 py-3 text-xs font-medium text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors text-center border-t border-gray-100 dark:border-gray-800/50"
          >
            {showAll ? "접기 ▲" : `+${filtered.length - 8}개 더보기 ▼`}
          </button>
        )}
      </div>

      <p className="text-center text-xs text-gray-300 dark:text-gray-600">
        Reddit · CryptoPanic 기반 실시간 인기 글 — 클릭 시 원문으로 이동합니다.
      </p>
    </section>
  );
}
