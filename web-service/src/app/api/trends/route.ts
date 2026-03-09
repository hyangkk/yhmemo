import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";
import { getSecret } from "@/lib/secrets";
import Anthropic from "@anthropic-ai/sdk";

export const dynamic = "force-dynamic";

// 캐시 (30분 TTL)
let trendsCache: { data: unknown; timestamp: number } | null = null;
const CACHE_TTL = 30 * 60 * 1000;

export async function GET() {
  try {
    if (trendsCache && Date.now() - trendsCache.timestamp < CACHE_TTL) {
      return NextResponse.json({
        ...(trendsCache.data as Record<string, unknown>),
        cached: true,
      });
    }

    const supabase = getServiceSupabase();

    // 최근 48시간 뉴스 가져오기 (트렌드 분석용)
    const since = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    const { data: news } = await supabase
      .from("collected_items")
      .select("title, source, content, collected_at")
      .gte("collected_at", since)
      .order("collected_at", { ascending: false })
      .limit(100);

    if (!news || news.length === 0) {
      return NextResponse.json({
        topics: [],
        keywords: [],
        summary: "아직 분석할 뉴스가 충분하지 않습니다.",
        generatedAt: new Date().toISOString(),
      });
    }

    // 시간대별 뉴스 분포 (6시간 단위)
    const timeSlots = [0, 6, 12, 18, 24, 30, 36, 42, 48];
    const now = Date.now();
    const distribution = timeSlots.slice(0, -1).map((start, i) => {
      const slotStart = now - timeSlots[i + 1] * 60 * 60 * 1000;
      const slotEnd = now - start * 60 * 60 * 1000;
      const count = news.filter((n) => {
        const t = new Date(n.collected_at).getTime();
        return t >= slotStart && t < slotEnd;
      }).length;
      return { hoursAgo: `${start}-${timeSlots[i + 1]}h`, count };
    });

    // AI 트렌드 분석
    const newsTitles = news.map((n) => `[${n.source}] ${n.title}`).join("\n");

    const apiKey = await getSecret("ANTHROPIC_API_KEY");
    if (!apiKey) {
      return NextResponse.json({ error: "ANTHROPIC_API_KEY not configured" }, { status: 500 });
    }
    const anthropic = new Anthropic({ apiKey });

    const response = await anthropic.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 1500,
      system: `당신은 뉴스 트렌드 분석가입니다. 최근 48시간 뉴스 제목들을 분석하여 핵심 트렌드를 추출합니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "topics": [
    {
      "name": "토픽명 (5자 이내)",
      "count": 관련_뉴스_수,
      "heat": "hot|warm|cool",
      "emoji": "이모지1개",
      "one_liner": "한줄 설명 (20자 이내)"
    }
  ],
  "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
  "emerging": "지금 막 떠오르는 이슈 한줄 (30자 이내)",
  "summary": "전체 트렌드 요약 2-3문장"
}

규칙:
- topics는 최대 6개, 뉴스에서 반복되는 주제 위주
- heat: 관련 뉴스 5개 이상이면 hot, 3개 이상이면 warm, 그 외 cool
- keywords: 가장 자주 언급되는 핵심 키워드 5개
- emerging: 이전에 없다가 갑자기 나타난 새로운 이슈
- 한국어로 작성`,
      messages: [
        {
          role: "user",
          content: `최근 48시간 뉴스 제목 ${news.length}건:\n${newsTitles}\n\n트렌드 분석을 해주세요.`,
        },
      ],
    });

    const aiText =
      response.content[0].type === "text" ? response.content[0].text : "";

    let trends;
    try {
      const jsonMatch = aiText.match(/\{[\s\S]*\}/);
      trends = jsonMatch ? JSON.parse(jsonMatch[0]) : null;
    } catch {
      trends = null;
    }

    const result = {
      ...(trends || {}),
      newsCount: news.length,
      distribution,
      generatedAt: new Date().toISOString(),
    };

    trendsCache = { data: result, timestamp: Date.now() };

    return NextResponse.json(result);
  } catch (err) {
    console.error("Trends error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
