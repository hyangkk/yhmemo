import { NextResponse } from "next/server";
import { getSecret } from "@/lib/secrets";
import Anthropic from "@anthropic-ai/sdk";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

export async function POST(request: Request) {
  try {
    const { question, transcript, videoTitle } = await request.json();

    if (!question || !transcript) {
      return NextResponse.json({ error: "질문과 자막 데이터가 필요합니다." }, { status: 400 });
    }

    const apiKey = await getSecret("ANTHROPIC_API_KEY");
    if (!apiKey) {
      return NextResponse.json({ error: "API 키가 설정되지 않았습니다." }, { status: 500 });
    }

    const maxChars = 300_000;
    const truncatedTranscript = transcript.length > maxChars ? transcript.slice(0, maxChars) : transcript;
    const titleHint = videoTitle ? ` (${videoTitle})` : "";

    const client = new Anthropic({ apiKey });
    const response = await client.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 3000,
      system: `당신은 YouTube 영상${titleHint}의 내용을 완벽히 이해한 전문가입니다. 자막 내용을 바탕으로 질문에 정확하게 답변하세요. 자막에 없는 내용은 '영상에서 다루지 않은 내용'이라고 명시하세요. 마크다운 포맷으로 작성하세요.`,
      messages: [
        { role: "user", content: `[영상 자막]\n${truncatedTranscript}\n\n[질문]\n${question}` },
      ],
    });

    const answer = response.content[0].type === "text" ? response.content[0].text : "";

    return NextResponse.json({ answer });
  } catch (error) {
    console.error("YouTube chat error:", error);
    return NextResponse.json({ error: "답변 생성 중 오류가 발생했습니다." }, { status: 500 });
  }
}
