"use client";

import { useEffect, useState, useCallback } from "react";

interface SentimentData {
  latest: {
    overallScore: number;
    overallLabel: string;
    assetScores: Record<string, number>;
    trendingTopics: string[];
    summary: string;
    riskAlert: string;
    analyzedAt: string;
  } | null;
  history: Array<{
    score: number;
    label: string;
    time: string;
  }>;
  hasData: boolean;
}

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
    BTC: "🟠",
    ETH: "🔷",
    SOL: "🟣",
    XRP: "⚪",
    "AI/반도체": "🤖",
    전체시장: "🌐",
  };
  return map[asset] || "📊";
}

function MiniTrendChart({ history }: { history: SentimentData["history"] }) {
  if (history.length < 2) return null;

  const scores = history.map((h) => h.score);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 1;
  const height = 40;
  const width = 160;
  const step = width / (scores.length - 1);

  const points = scores
    .map((s, i) => `${i * step},${height - ((s - min) / range) * height}`)
    .join(" ");

  const trend = scores[scores.length - 1] - scores[0];
  const color = trend > 0 ? "#22c55e" : trend < 0 ? "#ef4444" : "#eab308";

  return (
    <div className="flex items-center gap-2">
      <svg width={width} height={height} className="overflow-visible">
        <polyline
          points={points}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span
        className={`text-xs font-semibold ${
          trend > 0
            ? "text-green-600 dark:text-green-400"
            : trend < 0
              ? "text-red-600 dark:text-red-400"
              : "text-yellow-600 dark:text-yellow-400"
        }`}
      >
        {trend > 0 ? "↗" : trend < 0 ? "↘" : "→"}
      </span>
    </div>
  );
}

const REFRESH_INTERVAL = 5 * 60; // 5분

export default function SocialSentiment() {
  const [data, setData] = useState<SentimentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [countdown, setCountdown] = useState(REFRESH_INTERVAL);

  const fetchData = useCallback(async () => {
    try {
      setError(false);
      const res = await fetch("/api/sentiment");
      if (!res.ok) {
        setError(true);
        return;
      }
      const json = await res.json();
      setData(json);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_INTERVAL * 1000);
    return () => clearInterval(interval);
  }, [fetchData]);

  useEffect(() => {
    setCountdown(REFRESH_INTERVAL);
    const timer = setInterval(() => {
      setCountdown((prev) => (prev <= 1 ? REFRESH_INTERVAL : prev - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [data]);

  if (loading) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="space-y-4">
          <div className="h-32 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-20 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
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
          <p className="text-sm text-red-600 dark:text-red-400 mb-2">
            센티멘트 데이터를 불러오지 못했습니다
          </p>
          <button
            onClick={fetchData}
            className="px-4 py-2 rounded-lg bg-red-600 text-white text-xs font-medium hover:bg-red-700 transition"
          >
            다시 시도
          </button>
        </div>
      </section>
    );
  }

  if (!data || !data.hasData || !data.latest) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 text-center">
          <p className="text-3xl mb-3">🔍</p>
          <p className="font-semibold text-gray-700 dark:text-gray-200 mb-1">
            소셜 센티멘트 분석 준비 중
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            에이전트가 Reddit, 뉴스 등에서 데이터를 수집하고 있습니다.
            <br />
            첫 분석 결과가 곧 표시됩니다.
          </p>
        </div>
      </section>
    );
  }

  const { latest, history } = data;
  const { overallScore, overallLabel, assetScores, trendingTopics, summary, riskAlert, analyzedAt } = latest;

  const sortedAssets = Object.entries(assetScores).sort(
    ([, a], [, b]) => b - a
  );

  return (
    <section className="max-w-5xl mx-auto px-4 py-8">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <span className="w-8 h-8 rounded-lg bg-gradient-to-r from-blue-500 to-purple-600 flex items-center justify-center text-white text-sm">
            💬
          </span>
          소셜 센티멘트
        </h2>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 text-xs font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
            Reddit · News
          </span>
          <span className="text-xs text-gray-400">
            {countdown}초 후 갱신 ·{" "}
            {new Date(analyzedAt).toLocaleTimeString("ko-KR")} 분석
          </span>
        </div>
      </div>

      {/* 전체 센티멘트 게이지 */}
      <div className="mb-6 p-5 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
        <div className="flex items-center justify-between mb-3">
          <div>
            <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
              시장 소셜 감성 지수
            </span>
            <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
              Reddit · CryptoPanic · 뉴스 종합
            </p>
          </div>
          <div className="text-right">
            <span className={`text-2xl font-bold ${getScoreColor(overallScore)}`}>
              {getScoreEmoji(overallScore)} {overallScore}
              <span className="text-base font-normal text-gray-400">/100</span>
            </span>
            <p className={`text-sm font-medium ${getScoreColor(overallScore)}`}>
              {overallLabel}
            </p>
          </div>
        </div>

        {/* 게이지 바 */}
        <div className="w-full h-4 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden mb-2">
          <div
            className={`h-full rounded-full transition-all duration-1000 ${getScoreBg(overallScore)}`}
            style={{ width: `${overallScore}%` }}
          />
        </div>
        <div className="flex justify-between text-xs text-gray-400">
          <span>😱 극도 공포</span>
          <span>😐 중립</span>
          <span>🤑 극도 탐욕</span>
        </div>

        {/* 24시간 추세 */}
        {history.length >= 2 && (
          <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-800">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500 dark:text-gray-400">
                24시간 추세
              </span>
              <MiniTrendChart history={history} />
            </div>
          </div>
        )}
      </div>

      {/* 자산별 센티멘트 그리드 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        {sortedAssets.map(([asset, score]) => (
          <div
            key={asset}
            className="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4 hover:shadow-md transition-all"
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="text-lg">{getAssetEmoji(asset)}</span>
              <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                {asset}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${getScoreBg(score)}`}
                  style={{ width: `${score}%` }}
                />
              </div>
              <span className={`text-sm font-bold min-w-[2rem] text-right ${getScoreColor(score)}`}>
                {score}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* 핫토픽 + AI 요약 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* 핫토픽 */}
        {trendingTopics.length > 0 && (
          <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-1.5">
              🔥 핫토픽
            </h3>
            <div className="flex flex-wrap gap-2">
              {trendingTopics.map((topic: string, i: number) => (
                <span
                  key={i}
                  className="px-3 py-1.5 rounded-full bg-gray-100 dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-300 font-medium"
                >
                  #{topic}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* AI 분석 요약 */}
        {summary && (
          <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3 flex items-center gap-1.5">
              💡 AI 분석
            </h3>
            <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
              {summary}
            </p>
          </div>
        )}
      </div>

      {/* 위험 경고 */}
      {riskAlert && (
        <div className="mt-4 p-4 rounded-xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/10">
          <p className="text-sm text-amber-700 dark:text-amber-400 flex items-center gap-2">
            <span className="text-base">⚠️</span>
            {riskAlert}
          </p>
        </div>
      )}

      {/* 면책조항 */}
      <p className="text-center text-xs text-gray-300 dark:text-gray-600 mt-6">
        소셜 센티멘트는 Reddit · CryptoPanic 기반 AI 분석이며, 투자 조언이 아닙니다.
      </p>
    </section>
  );
}
