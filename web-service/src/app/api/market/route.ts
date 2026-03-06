import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

interface CoinGeckoPrice {
  usd: number;
  krw: number;
  usd_24h_change: number;
  usd_market_cap: number;
  usd_24h_vol: number;
}

interface FearGreedData {
  data: Array<{
    value: string;
    value_classification: string;
  }>;
}

const ASSETS = [
  { id: "bitcoin", name: "비트코인", symbol: "BTC", emoji: "🟠" },
  { id: "ethereum", name: "이더리움", symbol: "ETH", emoji: "🔷" },
  { id: "pax-gold", name: "금(PAXG)", symbol: "GOLD", emoji: "🥇" },
  { id: "solana", name: "솔라나", symbol: "SOL", emoji: "🟣" },
  { id: "ripple", name: "리플", symbol: "XRP", emoji: "⚪" },
];

export async function GET() {
  try {
    const coinIds = ASSETS.map((a) => a.id).join(",");

    // 가격 + Fear & Greed 동시 요청
    const [priceRes, fgRes] = await Promise.allSettled([
      fetch(
        `https://api.coingecko.com/api/v3/simple/price?ids=${coinIds}&vs_currencies=usd,krw&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true`,
        { next: { revalidate: 120 } }
      ),
      fetch("https://api.alternative.me/fng/?limit=1&format=json", {
        next: { revalidate: 300 },
      }),
    ]);

    // 가격 데이터
    let prices: Record<string, CoinGeckoPrice> = {};
    if (priceRes.status === "fulfilled" && priceRes.value.ok) {
      prices = await priceRes.value.json();
    }

    // Fear & Greed
    let fearGreed = { value: 50, classification: "Neutral" };
    if (fgRes.status === "fulfilled" && fgRes.value.ok) {
      const fgData: FearGreedData = await fgRes.value.json();
      if (fgData.data?.[0]) {
        fearGreed = {
          value: parseInt(fgData.data[0].value),
          classification: fgData.data[0].value_classification,
        };
      }
    }

    // 자산 데이터 매핑
    const assets = ASSETS.map((asset) => {
      const p = prices[asset.id];
      if (!p) {
        return { ...asset, usd: 0, krw: 0, change24h: 0, marketCap: 0, volume24h: 0 };
      }
      return {
        ...asset,
        usd: p.usd || 0,
        krw: p.krw || 0,
        change24h: p.usd_24h_change || 0,
        marketCap: p.usd_market_cap || 0,
        volume24h: p.usd_24h_vol || 0,
      };
    });

    return NextResponse.json({
      assets,
      fearGreed,
      updatedAt: new Date().toISOString(),
    });
  } catch (err) {
    console.error("Market API error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
