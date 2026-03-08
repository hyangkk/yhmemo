"use client";

import { useEffect, useState, useCallback } from "react";

interface Signal {
  asset: string;
  direction: "bullish" | "bearish" | "neutral";
  confidence: number;
  timeframe: string;
  title: string;
  rationale: string;
  risk: string;
  catalyst: string;
}

interface KeyLevel {
  asset: string;
  support: number;
  resistance: number;
  note: string;
}

interface CrossAnalysis {
  correlations: string[];
  flow_pattern: string;
  anomaly: string | null;
}

interface SignalData {
  signal: {
    market_regime: string;
    regime_description: string;
    overall_sentiment: number;
    signals: Signal[];
    cross_analysis: CrossAnalysis;
    key_levels: KeyLevel[];
    action_summary: string;
    watch_list: string[];
    disclaimer: string;
  };
  market: Array<{
    id: string;
    name: string;
    usd: number;
    change24h: number;
  }>;
  fearGreedHistory: Array<{
    value: number;
    classification: string;
    date: string;
  }>;
  newsCount: number;
  generatedAt: string;
  cached?: boolean;
}

const directionConfig = {
  bullish: { label: "매수 우위", color: "text-green-600 dark:text-green-400", bg: "bg-green-50 dark:bg-green-900/20", border: "border-green-200 dark:border-green-800/50", icon: "▲" },
  bearish: { label: "매도 우위", color: "text-red-600 dark:text-red-400", bg: "bg-red-50 dark:bg-red-900/20", border: "border-red-200 dark:border-red-800/50", icon: "▼" },
  neutral: { label: "관망", color: "text-yellow-600 dark:text-yellow-400", bg: "bg-yellow-50 dark:bg-yellow-900/20", border: "border-yellow-200 dark:border-yellow-800/50", icon: "■" },
};

const regimeLabels: Record<string, { label: string; emoji: string }> = {
  bull_trend: { label: "상승 추세", emoji: "🐂" },
  bear_trend: { label: "하락 추세", emoji: "🐻" },
  sideways: { label: "횡보", emoji: "➡️" },
  volatile: { label: "고변동성", emoji: "⚡" },
  transition: { label: "국면 전환", emoji: "🔄" },
};

const SIGNAL_REFRESH = 15 * 60; // seconds

export default function InvestSignal() {
  const [data, setData] = useState<SignalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  const fetchSignal = useCallback(async () => {
    try {
      setError(false);
      const res = await fetch("/api/insight/signal");
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
  }, []);

  useEffect(() => {
    fetchSignal();
    const interval = setInterval(fetchSignal, SIGNAL_REFRESH * 1000);
    return () => clearInterval(interval);
  }, [fetchSignal]);

  if (loading) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-56 bg-gray-200 dark:bg-gray-800 rounded-lg" />
          <div className="h-24 bg-gray-100 dark:bg-gray-800 rounded-2xl" />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {[1, 2].map((i) => (
              <div key={i} className="h-40 bg-gray-100 dark:bg-gray-800 rounded-2xl" />
            ))}
          </div>
        </div>
      </section>
    );
  }

  if (error || !data?.signal) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="rounded-2xl border border-amber-200 dark:border-amber-800/50 bg-amber-50 dark:bg-amber-900/10 p-6 text-center">
          <p className="text-2xl mb-2">🔍</p>
          <p className="text-sm text-amber-700 dark:text-amber-400 mb-2">투자 시그널을 분석 중입니다...</p>
          <button onClick={fetchSignal} className="px-4 py-2 rounded-lg bg-amber-600 text-white text-xs font-medium hover:bg-amber-700 transition">
            새로고침
          </button>
        </div>
      </section>
    );
  }

  const { signal } = data;
  const regime = regimeLabels[signal.market_regime] || { label: signal.market_regime, emoji: "📊" };

  // 센티먼트 바 색상
  const sentimentColor = signal.overall_sentiment > 30 ? "bg-green-500" :
    signal.overall_sentiment > 0 ? "bg-green-400" :
    signal.overall_sentiment > -30 ? "bg-yellow-500" :
    signal.overall_sentiment > -60 ? "bg-orange-500" : "bg-red-500";

  return (
    <section className="max-w-5xl mx-auto px-4 py-8">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <span className="w-8 h-8 rounded-lg bg-gradient-to-r from-violet-500 to-purple-600 flex items-center justify-center text-white text-sm">
            ⚡
          </span>
          투자 시그널
        </h2>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400">{data.newsCount}건 뉴스 분석</span>
          {data.cached && (
            <span className="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-[10px] text-gray-400">캐시</span>
          )}
        </div>
      </div>

      {/* 시장 국면 + 센티먼트 */}
      <div className="mb-6 p-5 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xl">{regime.emoji}</span>
              <span className="font-bold text-gray-900 dark:text-white">{regime.label}</span>
            </div>
            <p className="text-sm text-gray-500 dark:text-gray-400">{signal.regime_description}</p>
          </div>
          <div className="text-right">
            <p className="text-xs text-gray-400 mb-1">시장 센티먼트</p>
            <span className={`text-2xl font-bold ${signal.overall_sentiment >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}>
              {signal.overall_sentiment > 0 ? "+" : ""}{signal.overall_sentiment}
            </span>
          </div>
        </div>
        <div className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${sentimentColor}`}
            style={{ width: `${Math.max(5, (signal.overall_sentiment + 100) / 2)}%` }}
          />
        </div>
        <div className="flex justify-between mt-1 text-xs text-gray-400">
          <span>극도의 공포</span>
          <span>중립</span>
          <span>극도의 탐욕</span>
        </div>
      </div>

      {/* 시그널 카드 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
        {signal.signals?.map((sig, i) => {
          const cfg = directionConfig[sig.direction] || directionConfig.neutral;
          const isExpanded = expanded === i;
          return (
            <div
              key={i}
              className={`rounded-2xl border p-5 cursor-pointer transition-all hover:shadow-md ${cfg.bg} ${cfg.border}`}
              onClick={() => setExpanded(isExpanded ? null : i)}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`text-lg font-bold ${cfg.color}`}>{cfg.icon}</span>
                  <span className="font-bold text-gray-900 dark:text-white text-sm">{sig.asset}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${cfg.color} bg-white/50 dark:bg-black/20`}>
                    {cfg.label}
                  </span>
                  <span className="text-xs text-gray-400">{sig.timeframe}</span>
                </div>
              </div>

              <p className="font-semibold text-gray-800 dark:text-gray-200 text-sm mb-2">{sig.title}</p>

              {/* 확신도 바 */}
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs text-gray-400">확신도</span>
                <div className="flex-1 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${sig.confidence >= 0.7 ? "bg-green-500" : sig.confidence >= 0.4 ? "bg-yellow-500" : "bg-gray-400"}`}
                    style={{ width: `${sig.confidence * 100}%` }}
                  />
                </div>
                <span className="text-xs font-bold text-gray-600 dark:text-gray-300">
                  {Math.round(sig.confidence * 100)}%
                </span>
              </div>

              {/* 확장 내용 */}
              {isExpanded && (
                <div className="mt-3 pt-3 border-t border-gray-200/50 dark:border-gray-700/50 space-y-2 text-xs">
                  <div>
                    <p className="font-semibold text-gray-600 dark:text-gray-300 mb-0.5">근거</p>
                    <p className="text-gray-500 dark:text-gray-400 leading-relaxed">{sig.rationale}</p>
                  </div>
                  <div>
                    <p className="font-semibold text-red-500 mb-0.5">리스크</p>
                    <p className="text-gray-500 dark:text-gray-400">{sig.risk}</p>
                  </div>
                  <div>
                    <p className="font-semibold text-blue-500 mb-0.5">주시 트리거</p>
                    <p className="text-gray-500 dark:text-gray-400">{sig.catalyst}</p>
                  </div>
                </div>
              )}

              {!isExpanded && (
                <p className="text-[10px] text-gray-400 mt-1">탭하여 상세 보기</p>
              )}
            </div>
          );
        })}
      </div>

      {/* 크로스 분석 */}
      {signal.cross_analysis && (
        <div className="mb-6 p-5 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
          <h3 className="font-bold text-gray-900 dark:text-white text-sm mb-3 flex items-center gap-2">
            🔗 크로스 분석
          </h3>
          {signal.cross_analysis.correlations?.map((c, i) => (
            <p key={i} className="text-sm text-gray-600 dark:text-gray-400 mb-1">• {c}</p>
          ))}
          {signal.cross_analysis.flow_pattern && (
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
              <span className="font-semibold">자금 흐름:</span> {signal.cross_analysis.flow_pattern}
            </p>
          )}
          {signal.cross_analysis.anomaly && (
            <div className="mt-3 px-3 py-2 rounded-lg bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800/50">
              <p className="text-xs font-semibold text-red-600 dark:text-red-400">⚠️ 이상 징후</p>
              <p className="text-xs text-red-500 dark:text-red-400">{signal.cross_analysis.anomaly}</p>
            </div>
          )}
        </div>
      )}

      {/* 주요 레벨 */}
      {signal.key_levels && signal.key_levels.length > 0 && (
        <div className="mb-6 p-5 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
          <h3 className="font-bold text-gray-900 dark:text-white text-sm mb-3">📐 주요 가격 레벨</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {signal.key_levels.map((lvl, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-800/50">
                <span className="font-medium text-sm text-gray-900 dark:text-white">{lvl.asset}</span>
                <div className="flex items-center gap-3 text-xs">
                  <span className="text-green-600 dark:text-green-400">S: ${lvl.support?.toLocaleString()}</span>
                  <span className="text-red-600 dark:text-red-400">R: ${lvl.resistance?.toLocaleString()}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 종합 판단 + Watch List */}
      <div className="p-5 rounded-2xl bg-gradient-to-r from-violet-50 to-purple-50 dark:from-violet-900/10 dark:to-purple-900/10 border border-violet-200 dark:border-violet-800/50">
        <p className="text-sm font-medium text-gray-800 dark:text-gray-200 mb-3">{signal.action_summary}</p>
        {signal.watch_list && (
          <div className="flex flex-wrap gap-2">
            {signal.watch_list.map((item, i) => (
              <span key={i} className="px-3 py-1 rounded-full bg-white/70 dark:bg-black/20 text-xs font-medium text-violet-700 dark:text-violet-300 border border-violet-200 dark:border-violet-700">
                👁️ {item}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 면책조항 */}
      <p className="text-center text-[10px] text-gray-300 dark:text-gray-600 mt-4">
        {signal.disclaimer || "본 분석은 투자 조언이 아니며, 투자 결정은 본인 책임입니다."}
      </p>
    </section>
  );
}
