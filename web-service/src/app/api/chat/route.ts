import { NextResponse } from "next/server";
import { getSecret } from "@/lib/secrets";
import Anthropic from "@anthropic-ai/sdk";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const { question, article } = await request.json();

    if (!question || !article) {
      return NextResponse.json(
        { error: "질문과 기사 정보가 필요합니다." },
        { status: 400 }
      );
    }

    const apiKey = await getSecret("ANTHROPIC_API_KEY");
    if (!apiKey) {
      return NextResponse.json({ error: "ANTHROPIC_API_KEY not configured" }, { status: 500 });
    }
    const anthropic = new Anthropic({ apiKey });

    const response = await anthropic.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 800,
      system: `당신은 뉴스 기사에 대해 질문에 답하는 AI 어시스턴트입니다.
주어진 기사 정보를 바탕으로 사용자의 질문에 친절하고 간결하게 답변하세요.

규칙:
- 기사 내용에 기반해서 답변하되, 배경지식도 활용하세요
- 모르는 것은 모른다고 솔직히 말하세요
- 한국어로 답변하세요
- 2-4문장으로 간결하게 답변하세요
- 추가로 궁금해할 만한 점이 있다면 마지막에 짧게 제안하세요`,
      messages: [
        {
          role: "user",
          content: `기사 정보:
제목: ${article.title}
출처: ${article.source}
내용: ${article.summary || article.content || "내용 없음"}

사용자 질문: ${question}`,
        },
      ],
    });

    const answer =
      response.content[0].type === "text" ? response.content[0].text : "";

    return NextResponse.json({ answer });
  } catch (err) {
    console.error("Chat error:", err);
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
