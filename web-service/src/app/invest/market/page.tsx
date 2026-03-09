"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";

// ─── 타입 ────────────────────────────────────────────

interface Asset {
  id: string;
  name: string;
  symbol: string;
  emoji: string;
  usd: number;
  krw: number;
  change24h: number;
  marketCap: number;
  volume24h: number;
}

interface MarketData {
  assets: Asset[];
  fearGreed: { value: number; classification: string };
  updatedAt: string;
}

interface ChartPoint {
  t: number;
  p: number;
}

interface ChartData {
  coinId: string;
  days: number;
  points: ChartPoint[];
  stats: {
    first: number;
    last: number;
    max: number;
    min: number;
    change: number;
  };
}

interface InsightItem {
  title: string;
  body: string;
  type: string;
}

interface MarketInsight {
  insight: {
    headline: string;
    market_mood: string;
    insights: InsightItem[];
    news_market_link: string;
    what_to_watch: string[];
  } | null;
  newsCount: number;
  generatedAt: string;
}

// ─── 유틸 ────────────────────────────────────────────

function fmt(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function fgEmoji(v: number) {
  if (v <= 25) return "😱";
  if (v <= 45) return "😰";
  if (v <= 55) return "😐";
  if (v <= 75) return "😊";
  return "🤑";
}

function fgColor(v: number) {
  if (v <= 25) return "#ef4444";
  if (v <= 45) return "#f97316";
  if (v <= 55) return "#eab308";
  if (v <= 75) return "#22c55e";
  return "#10b981";
}

// ─── SVG 차트 컴포넌트 ───────────────────────────────

function PriceChart({
  points,
  stats,
  width = 700,
  height = 300,
}: {
  points: ChartPoint[];
  stats: ChartData["stats"];
  width?: number;
  height?: number;
}) {
  if (points.length < 2) return null;

  const pad = { top: 20, right: 60, bottom: 30, left: 10 };
  const w = width - pad.left - pad.right;
  const h = height - pad.top - pad.bottom;

  const minP = stats.min * 0.999;
  const maxP = stats.max * 1.001;
  const range = maxP - minP || 1;

  const toX = (i: number) => pad.left + (i / (points.length - 1)) * w;
  const toY = (p: number) => pad.top + h - ((p - minP) / range) * h;

  const pathD = points
    .map((pt, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(pt.p).toFixed(1)}`)
    .join(" ");

  // 면적 채우기
  const areaD =
    pathD +
    ` L${toX(points.length - 1).toFixed(1)},${(pad.top + h).toFixed(1)} L${pad.left},${(pad.top + h).toFixed(1)} Z`;

  const isUp = stats.change >= 0;
  const lineColor = isUp ? "#22c55e" : "#ef4444";
  const fillColor = isUp ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)";

  // Y축 라벨 (5단계)
  const yLabels = Array.from({ length: 5 }, (_, i) => {
    const val = minP + (range * i) / 4;
    return { y: toY(val), label: `$${val >= 1000 ? (val / 1000).toFixed(1) + "k" : val.toFixed(2)}` };
  });

  // X축 라벨 (5단계)
  const xLabels = Array.from({ length: 5 }, (_, i) => {
    const idx = Math.floor((i / 4) * (points.length - 1));
    const pt = points[idx];
    const d = new Date(pt.t);
    return {
      x: toX(idx),
      label: `${(d.getMonth() + 1).toString().padStart(2, "0")}/${d.getDate().toString().padStart(2, "0")}`,
    };
  });

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto"
      preserveAspectRatio="xMidYMid meet"
    >
      {/* 그리드 */}
      {yLabels.map((yl, i) => (
        <g key={i}>
          <line
            x1={pad.left}
            y1={yl.y}
            x2={width - pad.right}
            y2={yl.y}
            stroke="currentColor"
            strokeOpacity={0.06}
          />
          <text
            x={width - pad.right + 8}
            y={yl.y + 4}
            fontSize={10}
            fill="currentColor"
            fillOpacity={0.35}
          >
            {yl.label}
          </text>
        </g>
      ))}

      {/* X 라벨 */}
      {xLabels.map((xl, i) => (
        <text
          key={i}
          x={xl.x}
          y={height - 5}
          fontSize={10}
          fill="currentColor"
          fillOpacity={0.35}
          textAnchor="middle"
        >
          {xl.label}
        </text>
      ))}

      {/* 면적 */}
      <path d={areaD} fill={fillColor} />

      {/* 라인 */}
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth={2} strokeLinejoin="round" />

      {/* 현재가 도트 */}
      <circle
        cx={toX(points.length - 1)}
        cy={toY(points[points.length - 1].p)}
        r={4}
        fill={lineColor}
      />
      <circle
        cx={toX(points.length - 1)}
        cy={toY(points[points.length - 1].p)}
        r={8}
        fill={lineColor}
        fillOpacity={0.2}
      />
    </svg>
  );
}

// ─── Fear & Greed 게이지 ────────────────────────────

function FearGreedGauge({ value, classification }: { value: number; classification: string }) {
  const angle = -90 + (value / 100) * 180; // -90 ~ 90도
  const color = fgColor(value);

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 120" className="w-48 h-auto">
        {/* 배경 호 */}
        <path
          d="M 20 100 A 80 80 0 0 1 180 100"
          fill="none"
          stroke="currentColor"
          strokeOpacity={0.1}
          strokeWidth={12}
          strokeLinecap="round"
        />
        {/* 색상 호 */}
        <path
          d="M 20 100 A 80 80 0 0 1 180 100"
          fill="none"
          stroke={color}
          strokeWidth={12}
          strokeLinecap="round"
          strokeDasharray={`${(value / 100) * 251.3} 251.3`}
        />
        {/* 바늘 */}
        <line
          x1="100"
          y1="100"
          x2={100 + 60 * Math.cos((angle * Math.PI) / 180)}
          y2={100 + 60 * Math.sin((angle * Math.PI) / 180)}
          stroke={color}
          strokeWidth={3}
          strokeLinecap="round"
        />
        <circle cx="100" cy="100" r="5" fill={color} />
        {/* 값 */}
        <text x="100" y="85" textAnchor="middle" fontSize="28" fontWeight="bold" fill={color}>
          {value}
        </text>
      </svg>
      <div className="text-center -mt-2">
        <span className="text-2xl">{fgEmoji(value)}</span>
        <p className="text-sm font-medium mt-1" style={{ color }}>
          {classification}
        </p>
      </div>
    </div>
  );
}

// ─── 메인 페이지 ─────────────────────────────────────

export default function MarketPage() {
  const [market, setMarket] = useState<MarketData | null>(null);
  const [chart, setChart] = useState<ChartData | null>(null);
  const [insight, setInsight] = useState<MarketInsight | null>(null);
  const [insightLoading, setInsightLoading] = useState(true);
  const [selectedAsset, setSelectedAsset] = useState("bitcoin");
  const [chartDays, setChartDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [chartLoading, setChartLoading] = useState(false);

  const fetchMarket = useCallback(async () => {
    try {
      const res = await fetch("/api/market");
      if (res.ok) setMarket(await res.json());
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchChart = useCallback(async () => {
    setChartLoading(true);
    try {
      const res = await fetch(`/api/market/chart?id=${selectedAsset}&days=${chartDays}`);
      if (res.ok) setChart(await res.json());
    } catch {
      // silent
    } finally {
      setChartLoading(false);
    }
  }, [selectedAsset, chartDays]);

  const fetchInsight = useCallback(async () => {
    setInsightLoading(true);
    try {
      const res = await fetch("/api/market/insight");
      if (res.ok) setInsight(await res.json());
    } catch {
      // silent
    } finally {
      setInsightLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMarket();
    fetchInsight();
    const interval = setInterval(fetchMarket, 2 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchMarket, fetchInsight]);

  useEffect(() => {
    fetchChart();
  }, [fetchChart]);

  if (loading) {
    return (
      <main className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900">
        <div className="max-w-6xl mx-auto px-4 py-16">
          <div className="animate-pulse space-y-6">
            <div className="h-12 w-64 bg-gray-200 dark:bg-gray-800 rounded-xl" />
            <div className="h-80 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
            <div className="grid grid-cols-3 gap-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-32 bg-gray-200 dark:bg-gray-800 rounded-2xl" />
              ))}
            </div>
          </div>
        </div>
      </main>
    );
  }

  const assets = market?.assets || [];
  const current = assets.find((a) => a.id === selectedAsset);
  const fg = market?.fearGreed || { value: 50, classification: "Neutral" };

  return (
    <main className="min-h-screen bg-gradient-to-b from-gray-50 to-white dark:from-gray-950 dark:to-gray-900">
      {/* 네비게이션 */}
      <nav className="max-w-6xl mx-auto px-4 py-4 flex items-center justify-between">
        <Link
          href="/invest"
          className="text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 transition flex items-center gap-1"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          투자전략실
        </Link>
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 text-xs font-medium">
          <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
          실시간
        </div>
      </nav>

      {/* 히어로 */}
      <header className="max-w-6xl mx-auto px-4 pt-4 pb-8">
        <h1 className="text-3xl sm:text-4xl font-extrabold text-gray-900 dark:text-white">
          시장{" "}
          <span className="bg-gradient-to-r from-green-500 to-emerald-600 bg-clip-text text-transparent">
            실시간
          </span>
        </h1>
        <p className="mt-2 text-gray-500 dark:text-gray-400">
          AI가 모니터링하는 주요 자산 현황
          {market?.updatedAt && (
            <span className="ml-2 text-xs">
              ({new Date(market.updatedAt).toLocaleTimeString("ko-KR")} 기준)
            </span>
          )}
        </p>
      </header>

      <div className="max-w-6xl mx-auto px-4 pb-16">
        {/* 상단: Fear & Greed + 선택된 자산 */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 mb-8">
          {/* Fear & Greed */}
          <div className="lg:col-span-1 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6 flex items-center justify-center">
            <FearGreedGauge value={fg.value} classification={fg.classification} />
          </div>

          {/* 메인 차트 */}
          <div className="lg:col-span-3 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6">
            {/* 차트 헤더 */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
              <div className="flex items-center gap-3">
                {current && (
                  <>
                    <span className="text-3xl">{current.emoji}</span>
                    <div>
                      <h2 className="text-xl font-bold text-gray-900 dark:text-white">
                        {current.name}
                        <span className="ml-2 text-sm font-normal text-gray-400">
                          {current.symbol}
                        </span>
                      </h2>
                      <p className="text-2xl font-bold text-gray-900 dark:text-white">
                        ${current.usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                        <span
                          className={`ml-2 text-sm font-semibold ${
                            current.change24h >= 0 ? "text-green-600" : "text-red-600"
                          }`}
                        >
                          {current.change24h >= 0 ? "+" : ""}
                          {current.change24h.toFixed(2)}%
                        </span>
                      </p>
                    </div>
                  </>
                )}
              </div>

              {/* 기간 선택 */}
              <div className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
                {[
                  { label: "24H", days: 1 },
                  { label: "7D", days: 7 },
                  { label: "30D", days: 30 },
                  { label: "90D", days: 90 },
                  { label: "1Y", days: 365 },
                ].map((opt) => (
                  <button
                    key={opt.days}
                    onClick={() => setChartDays(opt.days)}
                    className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${
                      chartDays === opt.days
                        ? "bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm"
                        : "text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 차트 */}
            {chartLoading ? (
              <div className="h-72 flex items-center justify-center">
                <div className="w-8 h-8 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" />
              </div>
            ) : chart?.points && chart.points.length > 0 ? (
              <div>
                <PriceChart points={chart.points} stats={chart.stats} />
                {/* 통계 */}
                <div className="grid grid-cols-4 gap-4 mt-4 pt-4 border-t border-gray-100 dark:border-gray-800">
                  <div className="text-center">
                    <p className="text-xs text-gray-400">시작가</p>
                    <p className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                      ${chart.stats.first.toLocaleString()}
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-400">최고가</p>
                    <p className="text-sm font-semibold text-green-600">
                      ${chart.stats.max.toLocaleString()}
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-400">최저가</p>
                    <p className="text-sm font-semibold text-red-600">
                      ${chart.stats.min.toLocaleString()}
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-400">변동</p>
                    <p
                      className={`text-sm font-semibold ${
                        chart.stats.change >= 0 ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {chart.stats.change >= 0 ? "+" : ""}
                      {chart.stats.change}%
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="h-72 flex items-center justify-center text-gray-400">
                차트 데이터를 불러올 수 없습니다
              </div>
            )}
          </div>
        </div>

        {/* 자산 목록 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          {assets.map((asset) => (
            <button
              key={asset.id}
              onClick={() => setSelectedAsset(asset.id)}
              className={`text-left rounded-2xl border p-5 transition-all hover:shadow-lg ${
                selectedAsset === asset.id
                  ? "border-blue-500 dark:border-blue-400 bg-blue-50/50 dark:bg-blue-900/10 ring-1 ring-blue-500/20"
                  : "border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900"
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xl">{asset.emoji}</span>
                <span className="font-bold text-sm text-gray-900 dark:text-white">
                  {asset.symbol}
                </span>
              </div>
              <p className="text-lg font-bold text-gray-900 dark:text-white">
                ${asset.usd.toLocaleString(undefined, { maximumFractionDigits: asset.usd < 1 ? 4 : 2 })}
              </p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                ₩{asset.krw.toLocaleString()}
              </p>
              <span
                className={`inline-block text-xs font-semibold px-2 py-0.5 rounded-full ${
                  asset.change24h >= 0
                    ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                    : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                }`}
              >
                {asset.change24h >= 0 ? "+" : ""}
                {asset.change24h.toFixed(2)}%
              </span>
              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-400">
                <span>시총 {fmt(asset.marketCap)}</span>
              </div>
            </button>
          ))}
        </div>

        {/* 24시간 변동 비교 */}
        {assets.length > 0 && (
          <div className="mt-8 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6">
            <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-4">24시간 변동률 비교</h3>
            <div className="space-y-3">
              {[...assets].sort((a, b) => b.change24h - a.change24h).map((asset) => {
                const maxAbs = Math.max(...assets.map(a => Math.abs(a.change24h)), 1);
                const widthPct = Math.abs(asset.change24h) / maxAbs * 50;
                const isUp = asset.change24h >= 0;
                return (
                  <div key={asset.id} className="flex items-center gap-3">
                    <div className="w-16 flex items-center gap-1.5 flex-shrink-0">
                      <span className="text-sm">{asset.emoji}</span>
                      <span className="text-xs font-bold text-gray-700 dark:text-gray-300">{asset.symbol}</span>
                    </div>
                    <div className="flex-1 relative h-6">
                      <div className="absolute inset-0 flex items-center">
                        <div className="w-full h-px bg-gray-200 dark:bg-gray-700" />
                      </div>
                      <div className="absolute left-1/2 top-0 bottom-0 w-px bg-gray-300 dark:bg-gray-600" />
                      <div
                        className={`absolute top-0.5 h-5 rounded-sm transition-all ${
                          isUp ? "bg-green-500/80" : "bg-red-500/80"
                        }`}
                        style={{
                          ...(isUp
                            ? { left: "50%", width: `${widthPct}%` }
                            : { right: "50%", width: `${widthPct}%` }),
                        }}
                      />
                    </div>
                    <span className={`w-16 text-right text-xs font-bold flex-shrink-0 ${
                      isUp ? "text-green-600" : "text-red-600"
                    }`}>
                      {isUp ? "+" : ""}{asset.change24h.toFixed(2)}%
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* AI 크로스 분석 인사이트 */}
        <div className="mt-10">
          <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
            <span className="w-7 h-7 rounded-lg bg-gradient-to-r from-purple-500 to-pink-600 flex items-center justify-center text-white text-xs">
              AI
            </span>
            뉴스 x 시장 크로스 분석
          </h2>

          {insightLoading ? (
            <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8">
              <div className="animate-pulse space-y-4">
                <div className="h-6 w-3/4 bg-gray-200 dark:bg-gray-800 rounded" />
                <div className="h-4 w-1/2 bg-gray-200 dark:bg-gray-800 rounded" />
                <div className="h-20 bg-gray-200 dark:bg-gray-800 rounded-xl" />
                <div className="h-20 bg-gray-200 dark:bg-gray-800 rounded-xl" />
              </div>
              <p className="text-sm text-gray-400 mt-4 text-center">
                AI가 뉴스와 시장을 크로스 분석하고 있어요...
              </p>
            </div>
          ) : insight?.insight ? (
            <div className="space-y-4">
              {/* 헤드라인 + 시장 분위기 */}
              <div className="rounded-2xl border border-purple-200 dark:border-purple-800/50 bg-gradient-to-r from-purple-50 to-pink-50 dark:from-purple-900/10 dark:to-pink-900/10 p-6">
                <p className="text-lg font-bold text-gray-900 dark:text-white mb-1">
                  {insight.insight.headline}
                </p>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {insight.insight.market_mood}
                </p>
                <p className="text-xs text-gray-400 mt-2">
                  {insight.newsCount}개 뉴스 + 5개 자산 데이터 기반 분석
                </p>
              </div>

              {/* 개별 인사이트 */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {insight.insight.insights.map((item, i) => {
                  const typeConfig: Record<string, { bg: string; icon: string }> = {
                    correlation: { bg: "bg-blue-50 dark:bg-blue-900/10 border-blue-200 dark:border-blue-800/50", icon: "🔗" },
                    news_impact: { bg: "bg-amber-50 dark:bg-amber-900/10 border-amber-200 dark:border-amber-800/50", icon: "📰" },
                    pattern: { bg: "bg-green-50 dark:bg-green-900/10 border-green-200 dark:border-green-800/50", icon: "📊" },
                    risk: { bg: "bg-red-50 dark:bg-red-900/10 border-red-200 dark:border-red-800/50", icon: "⚠️" },
                    opportunity: { bg: "bg-emerald-50 dark:bg-emerald-900/10 border-emerald-200 dark:border-emerald-800/50", icon: "💡" },
                  };
                  const cfg = typeConfig[item.type] || typeConfig.pattern;
                  return (
                    <div
                      key={i}
                      className={`rounded-xl border p-4 ${cfg.bg}`}
                    >
                      <p className="font-semibold text-gray-900 dark:text-white mb-1">
                        {cfg.icon} {item.title}
                      </p>
                      <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                        {item.body}
                      </p>
                    </div>
                  );
                })}
              </div>

              {/* 뉴스-시장 연결 */}
              <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6">
                <h3 className="font-semibold text-gray-900 dark:text-white mb-2 flex items-center gap-2">
                  <span>📰</span> 뉴스가 시장에 미치는 영향
                </h3>
                <p className="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
                  {insight.insight.news_market_link}
                </p>
              </div>

              {/* 주시 포인트 */}
              <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-6">
                <h3 className="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                  <span>👀</span> 주시해야 할 포인트
                </h3>
                <div className="space-y-2">
                  {insight.insight.what_to_watch.map((item, i) => (
                    <div key={i} className="flex items-start gap-3">
                      <span className="flex-shrink-0 w-6 h-6 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-xs font-bold text-gray-500">
                        {i + 1}
                      </span>
                      <p className="text-sm text-gray-700 dark:text-gray-300 pt-0.5">
                        {item}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              <p className="text-xs text-gray-400 text-center">
                {new Date(insight.generatedAt).toLocaleString("ko-KR")} 생성 | 5분마다 자동 갱신
              </p>
            </div>
          ) : (
            <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-8 text-center">
              <p className="text-gray-400">인사이트를 불러올 수 없습니다.</p>
              <button
                onClick={fetchInsight}
                className="mt-3 px-4 py-2 rounded-lg bg-purple-600 text-white text-sm hover:bg-purple-700 transition"
              >
                다시 시도
              </button>
            </div>
          )}
        </div>

        {/* 면책 */}
        <p className="text-center text-xs text-gray-300 dark:text-gray-600 mt-10">
          데이터 출처: CoinGecko, Alternative.me | 이 정보는 투자 조언이 아닙니다.
        </p>
      </div>
    </main>
  );
}
