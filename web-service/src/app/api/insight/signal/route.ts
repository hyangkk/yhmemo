import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";
import Anthropic from "@anthropic-ai/sdk";

export const dynamic = "force-dynamic";

// 캐시 (15분 TTL)
let signalCache: { data: unknown; timestamp: number } | null = null;
const CACHE_TTL = 15 * 60 * 1000;

export async function GET() {
  try {
    if (signalCache && Date.now() - signalCache.timestamp < CACHE_TTL) {
      return NextResponse.json({
        ...(signalCache.data as Record<string, unknown>),
        cached: true,
      });
    }

    const supabase = getServiceSupabase();

    // 1. 시장 데이터 (가격 + 변동)
    const coinIds = "bitcoin,ethereum,pax-gold,solana,ripple";
    const [priceRes, fgRes] = await Promise.allSettled([
      fetch(
        `https://api.coingecko.com/api/v3/simple/price?ids=${coinIds}&vs_currencies=usd,krw&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true`,
        { next: { revalidate: 120 } }
      ),
      fetch("https://api.alternative.me/fng/?limit=7&format=json", {
        next: { revalidate: 300 },
      }),
    ]);

    let prices: Record<string, Record<string, number>> = {};
    if (priceRes.status === "fulfilled" && priceRes.value.ok) {
      prices = await priceRes.value.json();
    }

    let fearGreedHistory: Array<{ value: number; classification: string; date: string }> = [];
    if (fgRes.status === "fulfilled" && fgRes.value.ok) {
      const fgData = await fgRes.value.json();
      fearGreedHistory = (fgData.data || []).map(
        (d: { value: string; value_classification: string; timestamp: string }) => ({
          value: parseInt(d.value),
          classification: d.value_classification,
          date: new Date(parseInt(d.timestamp) * 1000).toISOString().split("T")[0],
        })
      );
    }

    const assetNames: Record<string, string> = {
      bitcoin: "비트코인(BTC)",
      ethereum: "이더리움(ETH)",
      "pax-gold": "금(PAXG)",
      solana: "솔라나(SOL)",
      ripple: "리플(XRP)",
    };

    const marketSummary = Object.entries(prices)
      .map(([id, p]) => {
        const name = assetNames[id] || id;
        const change = p.usd_24h_change || 0;
        const vol = p.usd_24h_vol || 0;
        const cap = p.usd_market_cap || 0;
        return `${name}: $${p.usd?.toLocaleString()} (24h: ${change >= 0 ? "+" : ""}${change.toFixed(2)}%, 거래량: $${(vol / 1e9).toFixed(1)}B, 시총: $${(cap / 1e9).toFixed(0)}B)`;
      })
      .join("\n");

    // 2. 뉴스 데이터 (48시간 — 추세 파악용)
    const since48h = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    const { data: news } = await supabase
      .from("collected_items")
      .select("title, source, content, collected_at")
      .gte("collected_at", since48h)
      .order("collected_at", { ascending: false })
      .limit(60);

    const newsContext = (news || [])
      .map((n) => `[${new Date(n.collected_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit" })} ${n.source}] ${n.title}`)
      .join("\n");

    // 3. AI 투자 시그널 분석
    const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

    const fgContext = fearGreedHistory.length > 0
      ? `\n\nFear & Greed Index 7일 추이:\n${fearGreedHistory.map((f) => `${f.date}: ${f.value}/100 (${f.classification})`).join("\n")}`
      : "";

    const response = await anthropic.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 2000,
      system: `당신은 전문 투자 리서치 애널리스트입니다.
시장 데이터, 뉴스, 센티먼트를 종합 분석하여 투자 의사결정에 도움이 되는 시그널을 도출합니다.

분석 원칙:
1. 단순 뉴스 요약이 아닌 "투자 시사점"을 도출
2. 각 시그널에 확신도(confidence)와 근거를 명시
3. 리스크와 기회를 균형있게 분석
4. 자산 간 상관관계, 자금 흐름 패턴 포착
5. 투자 추천이 아닌 객관적 분석 (면책조항 포함)

반드시 아래 JSON 형식으로만 응답하세요:
{
  "market_regime": "bull_trend|bear_trend|sideways|volatile|transition",
  "regime_description": "현재 시장 국면 설명 (1-2문장)",
  "overall_sentiment": -100~100 사이 정수 (매우 비관=-100, 매우 낙관=100),
  "signals": [
    {
      "asset": "자산명 또는 전체시장",
      "direction": "bullish|bearish|neutral",
      "confidence": 0.0~1.0,
      "timeframe": "단기(1-3일)|중기(1-2주)|장기(1개월+)",
      "title": "시그널 제목 (15자 이내)",
      "rationale": "근거 설명 (3-4문장, 구체적 데이터 인용)",
      "risk": "이 시그널의 리스크 요인",
      "catalyst": "주시해야 할 트리거/이벤트"
    }
  ],
  "cross_analysis": {
    "correlations": ["자산간 상관관계 인사이트 1", "인사이트 2"],
    "flow_pattern": "자금 흐름 패턴 설명 (위험자산↔안전자산 이동 등)",
    "anomaly": "이상 징후가 있다면 설명, 없으면 null"
  },
  "key_levels": [
    {
      "asset": "자산명",
      "support": 지지선_가격,
      "resistance": 저항선_가격,
      "note": "주요 레벨 의미"
    }
  ],
  "action_summary": "종합 판단 요약 2-3문장 (투자 추천 아님, 객관적 분석)",
  "watch_list": ["주시 포인트 1", "주시 포인트 2", "주시 포인트 3"],
  "disclaimer": "본 분석은 투자 조언이 아니며, 투자 결정은 본인 책임입니다."
}`,
      messages: [
        {
          role: "user",
          content: `현재 시장 데이터:\n${marketSummary}${fgContext}\n\n최근 48시간 뉴스 (${news?.length || 0}건):\n${newsContext || "(수집된 뉴스 없음)"}\n\n종합 투자 시그널 분석을 해주세요.`,
        },
      ],
    });

    const aiText = response.content[0].type === "text" ? response.content[0].text : "";

    let signal;
    try {
      const jsonMatch = aiText.match(/\{[\s\S]*\}/);
      signal = jsonMatch ? JSON.parse(jsonMatch[0]) : null;
    } catch {
      signal = null;
    }

    if (!signal) {
      return NextResponse.json({
        error: "시그널 분석 실패",
        generatedAt: new Date().toISOString(),
      }, { status: 500 });
    }

    const result = {
      signal,
      market: Object.entries(prices).map(([id, p]) => ({
        id,
        name: assetNames[id] || id,
        usd: p.usd || 0,
        krw: p.krw || 0,
        change24h: p.usd_24h_change || 0,
        marketCap: p.usd_market_cap || 0,
        volume24h: p.usd_24h_vol || 0,
      })),
      fearGreedHistory,
      newsCount: news?.length || 0,
      generatedAt: new Date().toISOString(),
    };

    signalCache = { data: result, timestamp: Date.now() };

    return NextResponse.json(result);
  } catch (err) {
    console.error("Signal API error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
