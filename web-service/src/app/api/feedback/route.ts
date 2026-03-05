import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const { type, message, article_id } = body;

    if (!type || !message) {
      return NextResponse.json({ error: "type과 message는 필수입니다" }, { status: 400 });
    }

    const supabase = getServiceSupabase();

    const { error } = await supabase.from("feedback").insert({
      type,
      message: message.slice(0, 1000),
      article_id: article_id || null,
      created_at: new Date().toISOString(),
    });

    if (error) {
      // 테이블이 없으면 무시하고 성공 처리 (로그만)
      console.error("Feedback save error:", error.message);
    }

    return NextResponse.json({ ok: true });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
