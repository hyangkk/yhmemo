import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";
import Anthropic from "@anthropic-ai/sdk";

export const dynamic = "force-dynamic";

// 캐시 (30분 TTL — 섹터 분석은 느리게 변함)
let sectorCache: { data: unknown; timestamp: number } | null = null;
const CACHE_TTL = 30 * 60 * 1000;

export async function GET() {
  try {
    if (sectorCache && Date.now() - sectorCache.timestamp < CACHE_TTL) {
      return NextResponse.json({
        ...(sectorCache.data as Record<string, unknown>),
        cached: true,
      });
    }

    const supabase = getServiceSupabase();

    // 48시간 뉴스
    const since = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    const { data: news } = await supabase
      .from("collected_items")
      .select("title, source, content, collected_at")
      .gte("collected_at", since)
      .order("collected_at", { ascending: false })
      .limit(80);

    if (!news || news.length < 5) {
      return NextResponse.json({
        sectors: [],
        summary: "분석할 뉴스가 충분하지 않습니다.",
        newsCount: news?.length || 0,
        generatedAt: new Date().toISOString(),
      });
    }

    const newsContext = news
      .map((n) => `[${n.source}] ${n.title}: ${(n.content || "").slice(0, 100)}`)
      .join("\n");

    const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

    const response = await anthropic.messages.create({
      model: "claude-sonnet-4-5-20250514",
      max_tokens: 2000,
      system: `당신은 섹터 분석 전문가입니다.
뉴스를 섹터/테마별로 분류하고, 각 섹터의 모멘텀과 투자 시사점을 분석합니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "sectors": [
    {
      "name": "섹터/테마명",
      "emoji": "이모지",
      "momentum": "strong_up|up|neutral|down|strong_down",
      "news_count": 관련뉴스수,
      "key_event": "핵심 이벤트 한줄",
      "implication": "투자 시사점 2-3문장",
      "related_assets": ["관련 자산/종목"]
    }
  ],
  "flow_narrative": "섹터간 자금 흐름 스토리 (3-4문장)",
  "hot_sector": "가장 주목할 섹터명",
  "cold_sector": "가장 부진한 섹터명"
}

규칙:
- 섹터는 5-8개 (AI/반도체, 크립토/블록체인, 거시경제, 에너지, 바이오, 소비재, 부동산 등)
- 뉴스에 실제로 등장하는 섹터만 포함
- momentum은 뉴스 톤과 빈도로 판단
- 한국어로 작성`,
      messages: [
        {
          role: "user",
          content: `최근 48시간 뉴스 ${news.length}건:\n${newsContext}\n\n섹터별 분석을 해주세요.`,
        },
      ],
    });

    const aiText = response.content[0].type === "text" ? response.content[0].text : "";

    let analysis;
    try {
      const jsonMatch = aiText.match(/\{[\s\S]*\}/);
      analysis = jsonMatch ? JSON.parse(jsonMatch[0]) : null;
    } catch {
      analysis = null;
    }

    const result = {
      ...(analysis || { sectors: [], flow_narrative: "" }),
      newsCount: news.length,
      generatedAt: new Date().toISOString(),
    };

    sectorCache = { data: result, timestamp: Date.now() };

    return NextResponse.json(result);
  } catch (err) {
    console.error("Sector analysis error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
