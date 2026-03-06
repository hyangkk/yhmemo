import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const coinId = searchParams.get("id") || "bitcoin";
  const days = Math.min(Number(searchParams.get("days") || "7"), 365);

  try {
    const res = await fetch(
      `https://api.coingecko.com/api/v3/coins/${coinId}/market_chart?vs_currency=usd&days=${days}&interval=${days <= 7 ? "hourly" : "daily"}`,
      { next: { revalidate: 300 } }
    );

    if (!res.ok) {
      return NextResponse.json({ error: "CoinGecko API error" }, { status: 502 });
    }

    const data = await res.json();
    const prices: [number, number][] = data.prices || [];

    // 리샘플링 (최대 100 포인트)
    const step = Math.max(1, Math.floor(prices.length / 100));
    const sampled = prices.filter((_, i) => i % step === 0);

    const first = sampled[0]?.[1] || 0;
    const last = sampled[sampled.length - 1]?.[1] || 0;
    const max = Math.max(...sampled.map((p) => p[1]));
    const min = Math.min(...sampled.map((p) => p[1]));
    const change = first > 0 ? ((last - first) / first) * 100 : 0;

    return NextResponse.json({
      coinId,
      days,
      points: sampled.map(([ts, price]) => ({
        t: ts,
        p: Math.round(price * 100) / 100,
      })),
      stats: {
        first: Math.round(first * 100) / 100,
        last: Math.round(last * 100) / 100,
        max: Math.round(max * 100) / 100,
        min: Math.round(min * 100) / 100,
        change: Math.round(change * 100) / 100,
      },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
