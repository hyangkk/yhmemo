import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";
import Anthropic from "@anthropic-ai/sdk";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const supabase = getServiceSupabase();

    // 최근 24시간 뉴스 가져오기
    const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

    const { data: collected } = await supabase
      .from("collected_items")
      .select("*")
      .gte("collected_at", since)
      .order("collected_at", { ascending: false })
      .limit(50);

    const { data: curated } = await supabase
      .from("curated_items")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(20);

    const allNews = collected || [];
    const curatedItems = curated || [];

    if (allNews.length === 0) {
      return NextResponse.json({
        stories: [],
        generated_at: new Date().toISOString(),
        message: "아직 수집된 뉴스가 없습니다.",
      });
    }

    // AI로 5개 핵심 스토리 선별
    const newsContext = allNews
      .map(
        (item, i) =>
          `[${i}] 제목: ${item.title}\n출처: ${item.source}\n내용: ${(item.content || "").slice(0, 200)}\nURL: ${item.url}`
      )
      .join("\n\n");

    const curatedContext =
      curatedItems.length > 0
        ? `\n\nAI가 이미 선별한 중요 뉴스:\n${curatedItems.map((c) => `- ${c.title || c.ai_summary}`).join("\n")}`
        : "";

    const anthropic = new Anthropic({
      apiKey: process.env.ANTHROPIC_API_KEY,
    });

    const response = await anthropic.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 2000,
      system: `당신은 뉴스 큐레이터이자 클릭베이트 탐지기입니다. 사용자에게 오늘 반드시 알아야 할 딱 5개의 뉴스만 골라주되, 각 원본 헤드라인의 낚시성(클릭베이트) 수준도 평가합니다.

선별 기준:
1. 중요도: 많은 사람에게 영향을 미치는 뉴스
2. 다양성: 5개가 서로 다른 주제/분야를 커버
3. 시의성: 가장 최신이고 긴급한 뉴스 우선
4. 실용성: 독자가 알면 도움이 되는 정보

클릭베이트 평가 기준:
- honesty_score: 1-10 (10=매우 정직, 1=완전 낚시)
- 과장, 감정 자극, 오해 유도, "충격", "경악", "알고보니" 등 낚시 표현 감지
- 내용과 제목의 괴리 평가

반드시 JSON 배열로 응답하세요. 다른 텍스트 없이 JSON만 출력하세요.
각 항목: { "index": 원본인덱스, "headline": "한줄 핵심 헤드라인 (15자 이내)", "summary": "왜 이게 중요한지 2-3문장 설명", "emoji": "주제를 나타내는 이모지 1개", "category": "카테고리", "honesty_score": 1-10, "clickbait_reason": "낚시성 평가 한줄 (정직하면 '정직한 제목' 등)" }`,
      messages: [
        {
          role: "user",
          content: `오늘의 뉴스 목록:\n${newsContext}${curatedContext}\n\n위 뉴스 중 오늘 꼭 알아야 할 5개만 골라주세요. JSON 배열로만 답변하세요.`,
        },
      ],
    });

    const aiText =
      response.content[0].type === "text" ? response.content[0].text : "";

    // JSON 파싱
    let picks;
    try {
      const jsonMatch = aiText.match(/\[[\s\S]*\]/);
      picks = jsonMatch ? JSON.parse(jsonMatch[0]) : [];
    } catch {
      picks = [];
    }

    // 원본 뉴스 데이터와 합치기
    const stories = picks.slice(0, 5).map(
      (pick: {
        index: number;
        headline: string;
        summary: string;
        emoji: string;
        category: string;
        honesty_score?: number;
        clickbait_reason?: string;
      }) => {
        const original = allNews[pick.index] || allNews[0];
        return {
          id: original.id,
          title: pick.headline,
          original_title: original.title,
          summary: pick.summary,
          emoji: pick.emoji,
          category: pick.category,
          source: original.source,
          url: original.url,
          published_at: original.collected_at,
          honesty_score: pick.honesty_score || 7,
          clickbait_reason: pick.clickbait_reason || "",
        };
      }
    );

    return NextResponse.json({
      stories,
      total_news_count: allNews.length,
      generated_at: new Date().toISOString(),
    });
  } catch (err) {
    console.error("Morning briefing error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
