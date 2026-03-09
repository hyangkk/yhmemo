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
    platformSummaries: Record<string, string>;
    bullishSignals: string[];
    bearishSignals: string[];
    analyzedAt: string;
  } | null;
  history: Array<{ score: number; label: string; time: string }>;
  hasData: boolean;
}

/* ── 플랫폼 정의 ─────────────────────────────── */

interface PlatformGroup {
  id: string;
  name: string;
  icon: string;
  color: string;
  headerBg: string;
  borderColor: string;
  bgColor: string;
  summaryKey: string;
  channels: string[];
  posts: SourcePost[];
}

function groupByPlatform(sourceFeeds: Record<string, SourcePost[]>): PlatformGroup[] {
  const platforms: PlatformGroup[] = [];

  const redditPosts: SourcePost[] = [];
  const redditSubs: string[] = [];
  const cryptoPanicPosts: SourcePost[] = [];
  const newsPosts: SourcePost[] = [];

  for (const [channel, posts] of Object.entries(sourceFeeds)) {
    if (channel.startsWith("r/")) {
      redditPosts.push(...posts);
      redditSubs.push(channel);
    } else if (channel === "CryptoPanic") {
      cryptoPanicPosts.push(...posts);
    } else if (channel === "GoogleNews") {
      newsPosts.push(...posts);
    }
  }

  if (redditPosts.length > 0) {
    redditPosts.sort((a, b) => (b.score || 0) - (a.score || 0));
    platforms.push({
      id: "reddit",
      name: "Reddit",
      icon: "🔴",
      color: "text-orange-600 dark:text-orange-400",
      headerBg: "bg-gradient-to-r from-orange-500 to-red-500",
      borderColor: "border-orange-200 dark:border-orange-800/50",
      bgColor: "bg-white dark:bg-gray-900",
      summaryKey: "reddit",
      channels: redditSubs,
      posts: redditPosts,
    });
  }

  if (cryptoPanicPosts.length > 0) {
    platforms.push({
      id: "cryptopanic",
      name: "CryptoPanic",
      icon: "⚡",
      color: "text-blue-600 dark:text-blue-400",
      headerBg: "bg-gradient-to-r from-blue-500 to-cyan-500",
      borderColor: "border-blue-200 dark:border-blue-800/50",
      bgColor: "bg-white dark:bg-gray-900",
      summaryKey: "news",
      channels: ["CryptoPanic"],
      posts: cryptoPanicPosts,
    });
  }

  if (newsPosts.length > 0) {
    platforms.push({
      id: "googlenews",
      name: "Google News",
      icon: "📰",
      color: "text-green-600 dark:text-green-400",
      headerBg: "bg-gradient-to-r from-green-500 to-emerald-500",
      borderColor: "border-green-200 dark:border-green-800/50",
      bgColor: "bg-white dark:bg-gray-900",
      summaryKey: "news",
      channels: ["GoogleNews"],
      posts: newsPosts,
    });
  }

  return platforms;
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

/* ── 플랫폼별 카드 (총체적 상태 + 최근 글) ──── */

function PlatformCard({ platform, platformSummary }: { platform: PlatformGroup; platformSummary?: string }) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? platform.posts : platform.posts.slice(0, 4);

  const subLabel = platform.id === "reddit"
    ? platform.channels.slice(0, 4).join(", ") + (platform.channels.length > 4 ? ` 외 ${platform.channels.length - 4}개` : "")
    : "";

  return (
    <div className={`rounded-2xl border ${platform.borderColor} ${platform.bgColor} overflow-hidden shadow-sm`}>
      {/* 플랫폼 헤더 (컬러 바) */}
      <div className={`${platform.headerBg} px-5 py-3.5 flex items-center justify-between`}>
        <div className="flex items-center gap-2.5">
          <span className="text-xl">{platform.icon}</span>
          <div>
            <h3 className="font-bold text-sm text-white">{platform.name}</h3>
            {subLabel && (
              <p className="text-[11px] text-white/70 mt-0.5">{subLabel}</p>
            )}
          </div>
        </div>
        <span className="text-xs font-medium text-white/80 bg-white/20 px-2.5 py-1 rounded-full">
          {platform.posts.length}개 글
        </span>
      </div>

      {/* 총체적 상태 */}
      <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-start gap-2">
          <span className="text-sm mt-0.5">📊</span>
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1.5">총체적 상태</p>
            <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
              {platformSummary || "분석 데이터가 수집되면 플랫폼별 분위기 요약이 표시됩니다."}
            </p>
          </div>
        </div>
      </div>

      {/* 최근 관련 글 */}
      <div className="px-5 pt-3 pb-1">
        <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-2 flex items-center gap-1.5">
          <span>📝</span> 최근 관련 글
        </p>
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-800/50">
        {visible.map((post, i) => (
          <div key={i} className="px-5 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors">
            <div className="flex items-start gap-3">
              <div className="flex-1 min-w-0">
                {post.url ? (
                  <a
                    href={post.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-gray-800 dark:text-gray-200 hover:text-blue-600 dark:hover:text-blue-400 transition-colors line-clamp-2 leading-snug"
                  >
                    {post.title}
                  </a>
                ) : (
                  <p className="text-sm text-gray-800 dark:text-gray-200 line-clamp-2 leading-snug">
                    {post.title}
                  </p>
                )}
                {post.snippet && (
                  <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 line-clamp-1">{post.snippet}</p>
                )}
              </div>

              {/* Reddit: upvotes + comments */}
              {post.score !== undefined && (
                <div className="flex-shrink-0 flex items-center gap-2 text-xs text-gray-400">
                  <span className="text-orange-500">▲{post.score >= 1000 ? `${(post.score / 1000).toFixed(1)}k` : post.score}</span>
                  {post.comments !== undefined && (
                    <span>💬{post.comments}</span>
                  )}
                </div>
              )}

              {/* CryptoPanic / News: votes */}
              {post.votes && (
                <div className="flex-shrink-0 text-xs">
                  <span className="text-green-500">👍{post.votes.positive || 0}</span>
                  {" "}
                  <span className="text-red-500">👎{post.votes.negative || 0}</span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* 더보기 */}
      {platform.posts.length > 4 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="w-full px-4 py-2.5 text-xs font-medium text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors text-center border-t border-gray-100 dark:border-gray-800/50"
        >
          {showAll ? "접기 ▲" : `+${platform.posts.length - 4}개 더보기 ▼`}
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

  if (loading) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="space-y-4">
          <div className="h-32 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          <div className="h-64 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          <div className="h-64 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
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
          <p className="text-sm text-gray-500 dark:text-gray-400">에이전트가 Reddit, CryptoPanic에서 데이터를 수집하고 있습니다.</p>
        </div>
      </section>
    );
  }

  const { latest, history } = data;
  const {
    overallScore, overallLabel, assetScores, trendingTopics,
    summary, riskAlert, sourceFeeds, platformSummaries,
    bullishSignals, bearishSignals, analyzedAt,
  } = latest;

  const sortedAssets = Object.entries(assetScores).sort(([, a], [, b]) => b - a);
  const platforms = groupByPlatform(sourceFeeds || {});
  const totalPosts = platforms.reduce((sum, p) => sum + p.posts.length, 0);
  const summaries = platformSummaries || {};

  return (
    <section className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      {/* ── 헤더 ── */}
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <span className="w-8 h-8 rounded-lg bg-gradient-to-r from-blue-500 to-purple-600 flex items-center justify-center text-white text-sm">💬</span>
          소셜 센티멘트
        </h2>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 text-xs font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
            {totalPosts}개 소스
          </span>
          <span className="text-xs text-gray-400">{timeAgo(analyzedAt)} 분석</span>
        </div>
      </div>

      {/* ── 종합 센티멘트 카드 ── */}
      <div className="p-5 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
        <div className="flex items-center justify-between mb-3">
          <div>
            <span className="text-sm font-medium text-gray-500 dark:text-gray-400">시장 소셜 감성 지수</span>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">Reddit · CryptoPanic · News 종합</p>
          </div>
          <div className="text-right">
            <span className={`text-2xl font-bold ${getScoreColor(overallScore)}`}>
              {getScoreEmoji(overallScore)} {overallScore}<span className="text-base font-normal text-gray-400">/100</span>
            </span>
            <p className={`text-sm font-medium ${getScoreColor(overallScore)}`}>{overallLabel}</p>
          </div>
        </div>
        <div className="w-full h-3 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden mb-2">
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

      {/* ── 소셜 미디어별 카드 (총체적 상태 + 최근 글) ── */}
      {platforms.length > 0 ? (
        <div className="space-y-5">
          {platforms.map((platform) => (
            <PlatformCard
              key={platform.id}
              platform={platform}
              platformSummary={summaries[platform.summaryKey]}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 text-center">
          <p className="text-sm text-gray-500 dark:text-gray-400">수집된 소셜 데이터가 없습니다. 다음 분석 사이클에서 수집됩니다.</p>
        </div>
      )}

      {/* ── AI 종합 분석 ── */}
      {(summary || (bullishSignals && bullishSignals.length > 0) || (bearishSignals && bearishSignals.length > 0)) && (
        <div className="rounded-2xl border border-purple-200 dark:border-purple-800/50 bg-white dark:bg-gray-900 overflow-hidden shadow-sm">
          <div className="bg-gradient-to-r from-purple-500 to-indigo-500 px-5 py-3.5 flex items-center gap-2">
            <span className="text-lg">🧠</span>
            <h3 className="font-bold text-sm text-white">AI 종합 분석</h3>
          </div>

          <div className="px-5 py-4 space-y-4">
            {summary && (
              <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-line">{summary}</p>
            )}

            {((bullishSignals && bullishSignals.length > 0) || (bearishSignals && bearishSignals.length > 0)) && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {bullishSignals && bullishSignals.length > 0 && (
                  <div className="rounded-xl bg-green-50 dark:bg-green-950/30 border border-green-200 dark:border-green-800/40 p-3.5">
                    <p className="text-xs font-semibold text-green-700 dark:text-green-400 mb-2">📈 강세 시그널</p>
                    <ul className="space-y-1.5">
                      {bullishSignals.map((s: string, i: number) => (
                        <li key={i} className="text-xs text-green-700 dark:text-green-300">• {s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {bearishSignals && bearishSignals.length > 0 && (
                  <div className="rounded-xl bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/40 p-3.5">
                    <p className="text-xs font-semibold text-red-700 dark:text-red-400 mb-2">📉 약세 시그널</p>
                    <ul className="space-y-1.5">
                      {bearishSignals.map((s: string, i: number) => (
                        <li key={i} className="text-xs text-red-700 dark:text-red-300">• {s}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {trendingTopics.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {trendingTopics.map((topic: string, i: number) => (
                  <span key={i} className="px-2.5 py-1 rounded-full bg-purple-100 dark:bg-purple-900/40 text-xs text-purple-700 dark:text-purple-300 font-medium">
                    #{topic}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 위험 경고 */}
      {riskAlert && (
        <div className="p-4 rounded-xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/10">
          <p className="text-sm text-amber-700 dark:text-amber-400 flex items-center gap-2">
            <span className="text-base">⚠️</span>{riskAlert}
          </p>
        </div>
      )}

      <p className="text-center text-xs text-gray-300 dark:text-gray-600">
        Reddit · CryptoPanic · Google News 기반 AI 분석이며, 투자 조언이 아닙니다.
      </p>
    </section>
  );
}
