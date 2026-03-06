import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";
import Anthropic from "@anthropic-ai/sdk";

export const dynamic = "force-dynamic";

interface AssetPrice {
  id: string;
  name: string;
  usd: number;
  change24h: number;
}

export async function GET() {
  try {
    const supabase = getServiceSupabase();

    // 1. 시장 데이터 가져오기
    const coinIds = "bitcoin,ethereum,pax-gold,solana,ripple";
    const priceRes = await fetch(
      `https://api.coingecko.com/api/v3/simple/price?ids=${coinIds}&vs_currencies=usd,krw&include_24hr_change=true`,
      { next: { revalidate: 300 } }
    );
    const prices = priceRes.ok ? await priceRes.json() : {};

    const assetNames: Record<string, string> = {
      bitcoin: "비트코인",
      ethereum: "이더리움",
      "pax-gold": "금(PAXG)",
      solana: "솔라나",
      ripple: "리플",
    };

    const assetPrices: AssetPrice[] = Object.entries(prices).map(([id, data]) => ({
      id,
      name: assetNames[id] || id,
      usd: (data as Record<string, number>).usd || 0,
      change24h: (data as Record<string, number>).usd_24h_change || 0,
    }));

    // 2. 최근 뉴스 가져오기 (24시간)
    const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const { data: news } = await supabase
      .from("collected_items")
      .select("title, source, content, collected_at")
      .gte("collected_at", since)
      .order("collected_at", { ascending: false })
      .limit(30);

    const newsContext = (news || [])
      .map((n) => `- [${n.source}] ${n.title}`)
      .join("\n");

    // 3. Fear & Greed
    let fgText = "";
    try {
      const fgRes = await fetch("https://api.alternative.me/fng/?limit=1&format=json");
      if (fgRes.ok) {
        const fgData = await fgRes.json();
        if (fgData.data?.[0]) {
          fgText = `Fear & Greed Index: ${fgData.data[0].value}/100 (${fgData.data[0].value_classification})`;
        }
      }
    } catch {
      // skip
    }

    // 4. AI 크로스 분석
    const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

    const marketSummary = assetPrices
      .map((a) => `${a.name}: $${a.usd.toLocaleString()} (24h: ${a.change24h >= 0 ? "+" : ""}${a.change24h.toFixed(2)}%)`)
      .join("\n");

    const response = await anthropic.messages.create({
      model: "claude-sonnet-4-5-20250514",
      max_tokens: 1500,
      system: `당신은 금융 시장 분석가이자 뉴스 분석가입니다.
시장 데이터와 최신 뉴스를 크로스 분석하여 일반인이 스스로 알기 어려운 인사이트를 제공합니다.

규칙:
1. 투자 추천이 아닌 객관적 분석
2. 뉴스가 시장에 미칠 수 있는 영향 연결
3. 자산 간 상관관계나 의외의 패턴 발견
4. "그래서 뭘 해야 하는지"가 아니라 "무엇이 일어나고 있는지"에 집중
5. 한국어로 작성

반드시 아래 JSON 형식으로만 응답하세요:
{
  "headline": "한줄 핵심 인사이트 (20자 이내)",
  "market_mood": "한줄 시장 분위기 요약",
  "insights": [
    {
      "title": "인사이트 제목 (10자 이내)",
      "body": "2-3문장 분석",
      "type": "correlation|news_impact|pattern|risk|opportunity"
    }
  ],
  "news_market_link": "뉴스와 시장의 연결고리 설명 (3-4문장)",
  "what_to_watch": ["주시해야 할 포인트 1", "주시해야 할 포인트 2", "주시해야 할 포인트 3"]
}`,
      messages: [
        {
          role: "user",
          content: `현재 시장:
${marketSummary}
${fgText}

최근 24시간 뉴스:
${newsContext || "(수집된 뉴스 없음)"}

크로스 분석을 해주세요.`,
        },
      ],
    });

    const aiText = response.content[0].type === "text" ? response.content[0].text : "";

    let insight;
    try {
      const jsonMatch = aiText.match(/\{[\s\S]*\}/);
      insight = jsonMatch ? JSON.parse(jsonMatch[0]) : null;
    } catch {
      insight = null;
    }

    return NextResponse.json({
      insight,
      market: assetPrices,
      newsCount: news?.length || 0,
      generatedAt: new Date().toISOString(),
    });
  } catch (err) {
    console.error("Market insight error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
