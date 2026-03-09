"use client";

import { useEffect, useState, useCallback } from "react";

/* ── 타입 ─────────────────────────────────────── */

interface SourcePost {
  title: string;
  url?: string;
  score?: number;
  comments?: number;
  snippet?: string;
  votes?: { positive?: number; negative?: number };
  sentiment?: string;
}

interface SentimentData {
  latest: {
    overallScore: number;
    overallLabel: string;
    assetScores: Record<string, number>;
    trendingTopics: string[];
    summary: string;
    riskAlert: string;
    sourceFeeds: Record<string, SourcePost[]>;
    bullishSignals: string[];
    bearishSignals: string[];
    analyzedAt: string;
  } | null;
  history: Array<{ score: number; label: string; time: string }>;
  hasData: boolean;
}

/* ── 유틸 ─────────────────────────────────────── */

function getScoreColor(score: number): string {
  if (score <= 25) return "text-red-600 dark:text-red-400";
  if (score <= 45) return "text-orange-600 dark:text-orange-400";
  if (score <= 55) return "text-yellow-600 dark:text-yellow-400";
  if (score <= 75) return "text-green-600 dark:text-green-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function getScoreBg(score: number): string {
  if (score <= 25) return "bg-red-500";
  if (score <= 45) return "bg-orange-500";
  if (score <= 55) return "bg-yellow-500";
  if (score <= 75) return "bg-green-500";
  return "bg-emerald-500";
}

function getScoreEmoji(score: number): string {
  if (score <= 20) return "😱";
  if (score <= 35) return "😰";
  if (score <= 45) return "😟";
  if (score <= 55) return "😐";
  if (score <= 65) return "😊";
  if (score <= 80) return "😄";
  return "🤑";
}

function getAssetEmoji(asset: string): string {
  const map: Record<string, string> = {
    BTC: "🟠", ETH: "🔷", SOL: "🟣", XRP: "⚪",
    "AI/반도체": "🤖", "전체시장": "🌐",
  };
  return map[asset] || "📊";
}

function getChannelMeta(channel: string): { icon: string; color: string; label: string } {
  if (channel.startsWith("r/")) {
    return {
      icon: "🔴",
      color: "border-orange-300 dark:border-orange-700 bg-orange-50 dark:bg-orange-950/30",
      label: `Reddit ${channel}`,
    };
  }
  if (channel === "CryptoPanic") {
    return {
      icon: "📰",
      color: "border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-950/30",
      label: "CryptoPanic News",
    };
  }
  if (channel === "GoogleNews") {
    return {
      icon: "🗞️",
      color: "border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-950/30",
      label: "Google News",
    };
  }
  return {
    icon: "📡",
    color: "border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-950/30",
    label: channel,
  };
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}분 전`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}시간 전`;
  return `${Math.floor(hrs / 24)}일 전`;
}

/* ── 미니 추세 차트 ──────────────────────────── */

function MiniTrendChart({ history }: { history: SentimentData["history"] }) {
  if (history.length < 2) return null;
  const scores = history.map((h) => h.score);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 1;
  const H = 32, W = 120;
  const step = W / (scores.length - 1);
  const points = scores.map((s, i) => `${i * step},${H - ((s - min) / range) * H}`).join(" ");
  const trend = scores[scores.length - 1] - scores[0];
  const color = trend > 0 ? "#22c55e" : trend < 0 ? "#ef4444" : "#eab308";
  return (
    <div className="flex items-center gap-1.5">
      <svg width={W} height={H} className="overflow-visible">
        <polyline points={points} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <span className={`text-xs font-bold ${trend > 0 ? "text-green-600 dark:text-green-400" : trend < 0 ? "text-red-600 dark:text-red-400" : "text-yellow-600"}`}>
        {trend > 0 ? "↗" : trend < 0 ? "↘" : "→"}
      </span>
    </div>
  );
}

/* ── 채널 피드 카드 ──────────────────────────── */

function ChannelFeed({ channel, posts }: { channel: string; posts: SourcePost[] }) {
  const [expanded, setExpanded] = useState(false);
  const meta = getChannelMeta(channel);
  const visiblePosts = expanded ? posts : posts.slice(0, 3);

  return (
    <div className={`rounded-xl border ${meta.color} overflow-hidden`}>
      {/* 채널 헤더 */}
      <div className="px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg">{meta.icon}</span>
          <span className="font-semibold text-sm text-gray-800 dark:text-gray-200">
            {meta.label}
          </span>
          <span className="text-xs text-gray-400 dark:text-gray-500">
            {posts.length}개 글
          </span>
        </div>
      </div>

      {/* 글 목록 */}
      <div className="divide-y divide-gray-200/50 dark:divide-gray-700/50">
        {visiblePosts.map((post, i) => (
          <div key={i} className="px-4 py-3 hover:bg-white/50 dark:hover:bg-gray-900/50 transition-colors">
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                {post.url ? (
                  <a
                    href={post.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium text-gray-800 dark:text-gray-200 hover:text-blue-600 dark:hover:text-blue-400 transition-colors line-clamp-2"
                  >
                    {post.title}
                  </a>
                ) : (
                  <p className="text-sm font-medium text-gray-800 dark:text-gray-200 line-clamp-2">
                    {post.title}
                  </p>
                )}
                {post.snippet && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 line-clamp-1">
                    {post.snippet}
                  </p>
                )}
              </div>

              {/* 메타 (Reddit: upvote/comments, News: votes) */}
              <div className="flex-shrink-0 flex items-center gap-2 text-xs text-gray-400">
                {post.score !== undefined && (
                  <span className="inline-flex items-center gap-0.5" title="Upvotes">
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                    </svg>
                    {post.score >= 1000 ? `${(post.score / 1000).toFixed(1)}k` : post.score}
                  </span>
                )}
                {post.comments !== undefined && (
                  <span className="inline-flex items-center gap-0.5" title="Comments">
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    {post.comments}
                  </span>
                )}
                {post.votes && (
                  <span className="inline-flex items-center gap-1">
                    <span className="text-green-500">+{post.votes.positive || 0}</span>
                    <span className="text-red-500">-{post.votes.negative || 0}</span>
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 더보기 */}
      {posts.length > 3 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full px-4 py-2.5 text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-white/30 dark:hover:bg-gray-800/30 transition-colors text-center"
        >
          {expanded ? "접기" : `+${posts.length - 3}개 더보기`}
        </button>
      )}
    </div>
  );
}

/* ── 메인 컴포넌트 ───────────────────────────── */

const REFRESH_INTERVAL = 5 * 60;

export default function SocialSentiment() {
  const [data, setData] = useState<SentimentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [activeTab, setActiveTab] = useState<"feeds" | "analysis">("feeds");

  const fetchData = useCallback(async () => {
    try {
      setError(false);
      const res = await fetch("/api/sentiment");
      if (!res.ok) { setError(true); return; }
      setData(await res.json());
    } catch { setError(true); } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_INTERVAL * 1000);
    return () => clearInterval(interval);
  }, [fetchData]);

  /* ── 로딩/에러/빈 상태 ── */

  if (loading) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="space-y-4">
          <div className="h-24 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-48 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
            ))}
          </div>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="rounded-2xl border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-900/10 p-6 text-center">
          <p className="text-sm text-red-600 dark:text-red-400 mb-2">센티멘트 데이터를 불러오지 못했습니다</p>
          <button onClick={fetchData} className="px-4 py-2 rounded-lg bg-red-600 text-white text-xs font-medium hover:bg-red-700 transition">다시 시도</button>
        </div>
      </section>
    );
  }

  if (!data?.hasData || !data.latest) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 text-center">
          <p className="text-3xl mb-3">🔍</p>
          <p className="font-semibold text-gray-700 dark:text-gray-200 mb-1">소셜 센티멘트 분석 준비 중</p>
          <p className="text-sm text-gray-500 dark:text-gray-400">에이전트가 Reddit, CryptoPanic 등에서 데이터를 수집하고 있습니다. 첫 분석 결과가 곧 표시됩니다.</p>
        </div>
      </section>
    );
  }

  const { latest, history } = data;
  const {
    overallScore, overallLabel, assetScores, trendingTopics,
    summary, riskAlert, sourceFeeds, bullishSignals, bearishSignals, analyzedAt,
  } = latest;

  const sortedAssets = Object.entries(assetScores).sort(([, a], [, b]) => b - a);
  const channels = Object.entries(sourceFeeds || {}).filter(([, posts]) => posts.length > 0);
  const totalPosts = channels.reduce((sum, [, posts]) => sum + posts.length, 0);

  return (
    <section className="max-w-5xl mx-auto px-4 py-8">
      {/* ── 헤더 ── */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <span className="w-8 h-8 rounded-lg bg-gradient-to-r from-blue-500 to-purple-600 flex items-center justify-center text-white text-sm">💬</span>
          소셜 센티멘트
        </h2>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 text-xs font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
            {totalPosts}개 소스 분석
          </span>
          <span className="text-xs text-gray-400">{timeAgo(analyzedAt)} 분석</span>
        </div>
      </div>

      {/* ── 종합 게이지 + 자산별 ── */}
      <div className="mb-6 p-5 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
        <div className="flex items-center justify-between mb-3">
          <div>
            <span className="text-sm font-medium text-gray-500 dark:text-gray-400">시장 소셜 감성 지수</span>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">Reddit · CryptoPanic · 뉴스 종합</p>
          </div>
          <div className="text-right">
            <span className={`text-2xl font-bold ${getScoreColor(overallScore)}`}>
              {getScoreEmoji(overallScore)} {overallScore}<span className="text-base font-normal text-gray-400">/100</span>
            </span>
            <p className={`text-sm font-medium ${getScoreColor(overallScore)}`}>{overallLabel}</p>
          </div>
        </div>
        <div className="w-full h-4 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden mb-2">
          <div className={`h-full rounded-full transition-all duration-1000 ${getScoreBg(overallScore)}`} style={{ width: `${overallScore}%` }} />
        </div>
        <div className="flex justify-between text-xs text-gray-400">
          <span>😱 극도 공포</span><span>😐 중립</span><span>🤑 극도 탐욕</span>
        </div>

        {/* 자산별 + 추세 */}
        <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-800 flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="flex-1 grid grid-cols-3 sm:grid-cols-6 gap-2">
            {sortedAssets.map(([asset, score]) => (
              <div key={asset} className="text-center">
                <span className="text-xs text-gray-500 dark:text-gray-400">{getAssetEmoji(asset)} {asset}</span>
                <div className="mt-1 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full ${getScoreBg(score)}`} style={{ width: `${score}%` }} />
                </div>
                <span className={`text-xs font-bold ${getScoreColor(score)}`}>{score}</span>
              </div>
            ))}
          </div>
          {history.length >= 2 && (
            <div className="flex-shrink-0">
              <span className="text-xs text-gray-400 block mb-1">24h 추세</span>
              <MiniTrendChart history={history} />
            </div>
          )}
        </div>
      </div>

      {/* ── 탭: 원본 피드 / AI 분석 ── */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setActiveTab("feeds")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            activeTab === "feeds"
              ? "bg-blue-600 text-white shadow-md"
              : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
          }`}
        >
          📡 채널별 원본 글 ({totalPosts})
        </button>
        <button
          onClick={() => setActiveTab("analysis")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
            activeTab === "analysis"
              ? "bg-purple-600 text-white shadow-md"
              : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700"
          }`}
        >
          🧠 AI 종합 분석
        </button>
      </div>

      {/* ── 탭 콘텐츠: 채널별 원본 글 ── */}
      {activeTab === "feeds" && (
        <div className="space-y-4">
          {channels.length > 0 ? (
            channels.map(([channel, posts]) => (
              <ChannelFeed key={channel} channel={channel} posts={posts as SourcePost[]} />
            ))
          ) : (
            <div className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 text-center">
              <p className="text-sm text-gray-500 dark:text-gray-400">수집된 원본 글이 없습니다. 다음 분석 사이클에서 수집됩니다.</p>
            </div>
          )}
        </div>
      )}

      {/* ── 탭 콘텐츠: AI 종합 분석 ── */}
      {activeTab === "analysis" && (
        <div className="space-y-4">
          {/* AI 요약 */}
          {summary && (
            <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">💡 AI 종합 분석</h3>
              <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed whitespace-pre-line">{summary}</p>
            </div>
          )}

          {/* 강세/약세 시그널 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {bullishSignals && bullishSignals.length > 0 && (
              <div className="rounded-2xl border border-green-200 dark:border-green-800/50 bg-green-50 dark:bg-green-950/20 p-5">
                <h3 className="text-sm font-semibold text-green-700 dark:text-green-400 mb-3">📈 강세 시그널</h3>
                <ul className="space-y-2">
                  {bullishSignals.map((s: string, i: number) => (
                    <li key={i} className="text-sm text-green-700 dark:text-green-300 flex items-start gap-2">
                      <span className="mt-0.5">•</span>{s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {bearishSignals && bearishSignals.length > 0 && (
              <div className="rounded-2xl border border-red-200 dark:border-red-800/50 bg-red-50 dark:bg-red-950/20 p-5">
                <h3 className="text-sm font-semibold text-red-700 dark:text-red-400 mb-3">📉 약세 시그널</h3>
                <ul className="space-y-2">
                  {bearishSignals.map((s: string, i: number) => (
                    <li key={i} className="text-sm text-red-700 dark:text-red-300 flex items-start gap-2">
                      <span className="mt-0.5">•</span>{s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* 핫토픽 */}
          {trendingTopics.length > 0 && (
            <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">🔥 핫토픽</h3>
              <div className="flex flex-wrap gap-2">
                {trendingTopics.map((topic: string, i: number) => (
                  <span key={i} className="px-3 py-1.5 rounded-full bg-gray-100 dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-300 font-medium">#{topic}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 위험 경고 */}
      {riskAlert && (
        <div className="mt-4 p-4 rounded-xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/10">
          <p className="text-sm text-amber-700 dark:text-amber-400 flex items-center gap-2">
            <span className="text-base">⚠️</span>{riskAlert}
          </p>
        </div>
      )}

      <p className="text-center text-xs text-gray-300 dark:text-gray-600 mt-6">
        소셜 센티멘트는 Reddit · CryptoPanic · 뉴스 기반 AI 분석이며, 투자 조언이 아닙니다.
      </p>
    </section>
  );
}
