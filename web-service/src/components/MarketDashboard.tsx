"use client";

import { useEffect, useState } from "react";

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
  fearGreed: {
    value: number;
    classification: string;
  };
  updatedAt: string;
}

function formatNumber(n: number): string {
  if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return `$${n.toLocaleString()}`;
}

function getFearGreedEmoji(value: number): string {
  if (value <= 25) return "😱";
  if (value <= 45) return "😰";
  if (value <= 55) return "😐";
  if (value <= 75) return "😊";
  return "🤑";
}

function getFearGreedColor(value: number): string {
  if (value <= 25) return "text-red-600 dark:text-red-400";
  if (value <= 45) return "text-orange-600 dark:text-orange-400";
  if (value <= 55) return "text-yellow-600 dark:text-yellow-400";
  if (value <= 75) return "text-green-600 dark:text-green-400";
  return "text-emerald-600 dark:text-emerald-400";
}

function getFearGreedBg(value: number): string {
  if (value <= 25) return "bg-red-500";
  if (value <= 45) return "bg-orange-500";
  if (value <= 55) return "bg-yellow-500";
  if (value <= 75) return "bg-green-500";
  return "bg-emerald-500";
}

export default function MarketDashboard() {
  const [data, setData] = useState<MarketData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 2 * 60 * 1000); // 2분마다
    return () => clearInterval(interval);
  }, []);

  async function fetchData() {
    try {
      const res = await fetch("/api/market");
      if (!res.ok) return;
      const json = await res.json();
      setData(json);
    } catch {
      // silent fail
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <section className="max-w-5xl mx-auto px-4 py-8">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[...Array(5)].map((_, i) => (
            <div
              key={i}
              className="h-28 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse"
            />
          ))}
        </div>
      </section>
    );
  }

  if (!data || data.assets.length === 0) return null;

  const { assets, fearGreed, updatedAt } = data;

  return (
    <section className="max-w-5xl mx-auto px-4 py-8">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <span className="w-8 h-8 rounded-lg bg-gradient-to-r from-amber-500 to-orange-600 flex items-center justify-center text-white text-sm">
            $
          </span>
          시장 현황
        </h2>
        <span className="text-xs text-gray-400">
          {new Date(updatedAt).toLocaleTimeString("ko-KR")} 기준
        </span>
      </div>

      {/* Fear & Greed Index */}
      <div className="mb-6 p-4 rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
            Fear &amp; Greed Index
          </span>
          <span className={`text-lg font-bold ${getFearGreedColor(fearGreed.value)}`}>
            {getFearGreedEmoji(fearGreed.value)} {fearGreed.value}/100
          </span>
        </div>
        <div className="w-full h-3 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${getFearGreedBg(fearGreed.value)}`}
            style={{ width: `${fearGreed.value}%` }}
          />
        </div>
        <div className="flex justify-between mt-1 text-xs text-gray-400">
          <span>극도의 공포</span>
          <span className="font-medium">{fearGreed.classification}</span>
          <span>극도의 탐욕</span>
        </div>
      </div>

      {/* 자산 카드 그리드 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {assets.map((asset) => (
          <div
            key={asset.id}
            className="relative rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 hover:shadow-lg transition-all"
          >
            {/* 헤더 */}
            <div className="flex items-center gap-3 mb-3">
              <span className="text-2xl">{asset.emoji}</span>
              <div>
                <p className="font-bold text-gray-900 dark:text-white">
                  {asset.name}
                </p>
                <p className="text-xs text-gray-400">{asset.symbol}</p>
              </div>
            </div>

            {/* 가격 */}
            <div className="mb-2">
              <p className="text-xl font-bold text-gray-900 dark:text-white">
                ${asset.usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                ₩{asset.krw.toLocaleString()}
              </p>
            </div>

            {/* 24h 변동 */}
            <div
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-sm font-semibold ${
                asset.change24h >= 0
                  ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
                  : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
              }`}
            >
              {asset.change24h >= 0 ? "▲" : "▼"}{" "}
              {asset.change24h >= 0 ? "+" : ""}
              {asset.change24h.toFixed(2)}%
            </div>

            {/* 시총/거래량 */}
            <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800 grid grid-cols-2 gap-2 text-xs text-gray-400">
              <div>
                <p>시가총액</p>
                <p className="font-medium text-gray-600 dark:text-gray-300">
                  {formatNumber(asset.marketCap)}
                </p>
              </div>
              <div>
                <p>24h 거래량</p>
                <p className="font-medium text-gray-600 dark:text-gray-300">
                  {formatNumber(asset.volume24h)}
                </p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 면책조항 */}
      <p className="text-center text-xs text-gray-300 dark:text-gray-600 mt-6">
        실시간 시세는 CoinGecko 기준이며, 투자 조언이 아닙니다.
      </p>
    </section>
  );
}
