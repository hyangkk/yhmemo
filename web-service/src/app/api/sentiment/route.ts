import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const supabase = getServiceSupabase();

    // 최신 센티멘트 1건 (원본 글 포함)
    const { data: latest, error: latestErr } = await supabase
      .from("social_sentiment")
      .select("*")
      .order("analyzed_at", { ascending: false })
      .limit(1)
      .single();

    if (latestErr && latestErr.code !== "PGRST116") {
      console.error("Sentiment latest error:", latestErr);
    }

    // 최근 24시간 히스토리 (추세용)
    const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
    const { data: history, error: histErr } = await supabase
      .from("social_sentiment")
      .select("overall_score, overall_label, analyzed_at")
      .gte("analyzed_at", since)
      .order("analyzed_at", { ascending: true });

    if (histErr) {
      console.error("Sentiment history error:", histErr);
    }

    if (!latest) {
      return NextResponse.json({ latest: null, history: [], hasData: false });
    }

    // jsonb 문자열 파싱 헬퍼
    function parseJsonb(val: unknown): Record<string, unknown> | unknown[] {
      if (typeof val === "string") {
        try { return JSON.parse(val); } catch { return {}; }
      }
      return (val as Record<string, unknown>) || {};
    }

    return NextResponse.json({
      latest: {
        overallScore: latest.overall_score,
        overallLabel: latest.overall_label,
        assetScores: parseJsonb(latest.asset_scores),
        trendingTopics: latest.trending_topics || [],
        summary: latest.summary || "",
        riskAlert: latest.risk_alert || "",
        sourceFeeds: parseJsonb(latest.source_feeds),
        bullishSignals: latest.bullish_signals || [],
        bearishSignals: latest.bearish_signals || [],
        analyzedAt: latest.analyzed_at,
      },
      history: (history || []).map((h: { overall_score: number; overall_label: string; analyzed_at: string }) => ({
        score: h.overall_score,
        label: h.overall_label,
        time: h.analyzed_at,
      })),
      hasData: true,
    });
  } catch (err) {
    console.error("Sentiment API error:", err);
    return NextResponse.json(
      { error: "Failed to fetch sentiment data" },
      { status: 500 }
    );
  }
}
